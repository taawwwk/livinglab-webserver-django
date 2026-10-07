import datetime
import io
import json

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import ShopSite, WaterLevelReading

KEY = 'test-key-1'
URL = '/api/shop/readings/'
KST = datetime.timezone(datetime.timedelta(hours=9))


def ts(minutes_ago=0, seconds=0):
    """현재 기준 과거 시각 (KST ISO 문자열)."""
    t = timezone.now() - datetime.timedelta(minutes=minutes_ago, seconds=seconds)
    return t.astimezone(KST).replace(microsecond=0).isoformat()


@override_settings(SHOP_API_KEYS=[KEY, 'test-key-2'])
class ShopTestCase(TestCase):
    def setUp(self):
        # baseline 150cm, 수위 30cm 이상 warn, 60cm 이상 danger
        self.site = ShopSite.objects.create(name='대학가 가게 1호', baseline_cm=150.0,
                                            warn_level_cm=30.0, danger_level_cm=60.0)

    def post(self, body, key=KEY, raw=None):
        headers = {'HTTP_X_API_KEY': key} if key is not None else {}
        return self.client.post(URL, raw if raw is not None else json.dumps(body),
                                content_type='application/json', **headers)

    def get(self, url, key=KEY, **params):
        headers = {'HTTP_X_API_KEY': key} if key is not None else {}
        return self.client.get(url, params, **headers)

    def latest(self, site=None):
        return self.get(f'/api/shop/sites/{(site or self.site).pk}/latest/').json()


class PostReadingTests(ShopTestCase):
    def test_single(self):
        r = self.post({'site_id': self.site.pk, 'measured_at': '2026-10-06T10:15:30+09:00', 'distance_cm': 123.4})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json(), {'site_id': self.site.pk, 'created': 1, 'skipped': 0})
        reading = WaterLevelReading.objects.get()
        self.assertEqual(reading.distance_cm, 123.4)
        self.assertEqual(reading.measured_at, datetime.datetime(2026, 10, 6, 1, 15, 30, tzinfo=datetime.timezone.utc))
        self.assertIsNotNone(reading.received_at)

    def test_batch_with_null(self):
        r = self.post({'site_id': self.site.pk, 'readings': [
            {'measured_at': ts(1), 'distance_cm': 120.0},
            {'measured_at': ts(0, 50), 'distance_cm': None},
            {'measured_at': ts(0, 40), 'distance_cm': 0},
        ]})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['created'], r.json()['skipped']), (3, 0))
        self.assertEqual(sorted(WaterLevelReading.objects.values_list('distance_cm', flat=True),
                                key=lambda v: (v is not None, v)), [None, 0.0, 120.0])

    def test_resend_is_idempotent(self):
        body = {'site_id': self.site.pk, 'measured_at': '2026-10-06T10:15:30+09:00', 'distance_cm': 100.0}
        self.assertEqual(self.post(body).status_code, 201)
        r = self.post(body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['created'], r.json()['skipped']), (0, 1))
        # 같은 순간을 UTC 표기로 보내도 중복으로 본다
        r = self.post(dict(body, measured_at='2026-10-06T01:15:30Z'))
        self.assertEqual(r.json()['skipped'], 1)
        self.assertEqual(WaterLevelReading.objects.count(), 1)

    def test_batch_partial_overlap_and_in_batch_duplicate(self):
        self.post({'site_id': self.site.pk, 'measured_at': '2026-10-06T10:00:00+09:00', 'distance_cm': 100.0})
        r = self.post({'site_id': self.site.pk, 'readings': [
            {'measured_at': '2026-10-06T10:00:00+09:00', 'distance_cm': 100.0},  # 이미 있음
            {'measured_at': '2026-10-06T10:00:10+09:00', 'distance_cm': 101.0},
            {'measured_at': '2026-10-06T10:00:10+09:00', 'distance_cm': 999.0},  # 요청 내 중복
        ]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()['created'], r.json()['skipped']), (1, 2))
        self.assertEqual(WaterLevelReading.objects.filter(distance_cm=101.0).count(), 1)

    def test_auth(self):
        body = {'site_id': self.site.pk, 'measured_at': ts(), 'distance_cm': 100.0}
        for key in (None, '', 'wrong-key', KEY + ' '):
            r = self.post(body, key=key)
            self.assertEqual(r.status_code, 401, key)
            self.assertEqual(r['WWW-Authenticate'], 'X-API-Key')
        self.assertEqual(self.post(body, key='test-key-2').status_code, 201)
        with self.settings(SHOP_API_KEYS=[]):
            self.assertEqual(self.post(dict(body, measured_at=ts(1)), key=KEY).status_code, 401)
        self.assertEqual(WaterLevelReading.objects.count(), 1)

    def test_invalid_values_are_400_and_nothing_saved(self):
        base = {'site_id': self.site.pk, 'measured_at': ts(), 'distance_cm': 100.0}
        cases = {
            'negative': dict(base, distance_cm=-0.1),
            'too large': dict(base, distance_cm=1000.1),
            'string': dict(base, distance_cm='abc'),
            'missing distance key': {k: v for k, v in base.items() if k != 'distance_cm'},
            'naive time': dict(base, measured_at='2026-10-08T10:15:30'),
            'bad time': dict(base, measured_at='2026-13-08T10:15:30+09:00'),
            'future time': dict(base, measured_at=(timezone.now() + datetime.timedelta(minutes=10)).isoformat()),
            'unknown site': dict(base, site_id=9999),
            'empty batch': {'site_id': self.site.pk, 'readings': []},
            'one bad item in batch': {'site_id': self.site.pk, 'readings': [
                {'measured_at': ts(1), 'distance_cm': 100.0}, {'measured_at': ts(), 'distance_cm': -5}]},
        }
        for name, body in cases.items():
            r = self.post(body)
            self.assertEqual(r.status_code, 400, f'{name}: {r.content}')
        self.assertEqual(self.post(None, raw='{"site_id": 1, "measured_at": "x", "distance_cm": NaN}').status_code, 400)
        self.assertEqual(self.post(None, raw='[1, 2]').status_code, 400)
        self.assertFalse(WaterLevelReading.objects.exists())
        # 경계값 1000은 허용
        self.assertEqual(self.post(dict(base, distance_cm=1000)).status_code, 201)

    def test_batch_size_limit(self):
        start = timezone.now() - datetime.timedelta(days=1)
        readings = [{'measured_at': (start + datetime.timedelta(seconds=10 * i)).isoformat(), 'distance_cm': 100.0}
                    for i in range(1001)]
        r = self.post({'site_id': self.site.pk, 'readings': readings})
        self.assertEqual(r.status_code, 400)
        r = self.post({'site_id': self.site.pk, 'readings': readings[:1000]})
        self.assertEqual((r.status_code, r.json()['created']), (201, 1000))

    def test_danger_logs_warning(self):
        with self.assertLogs('shopsense', level='WARNING') as logs:
            self.post({'site_id': self.site.pk, 'measured_at': ts(), 'distance_cm': 80.0})  # 수위 70 ≥ 60
        self.assertIn('DANGER', logs.output[0])
        # 밀린 배치에서는 가장 최근 값으로만 판정한다 (과거 위험값 → 지금 정상이면 경고 없음)
        with self.assertNoLogs('shopsense', level='WARNING'):
            self.post({'site_id': self.site.pk, 'readings': [
                {'measured_at': ts(5), 'distance_cm': 50.0}, {'measured_at': ts(4), 'distance_cm': 140.0}]})


class GetReadingsTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        for minutes, distance in ((30, 140.0), (20, None), (10, 100.0)):
            WaterLevelReading.objects.create(site=self.site, distance_cm=distance,
                                             measured_at=timezone.now() - datetime.timedelta(minutes=minutes))

    def test_default_desc_with_level(self):
        r = self.get(URL, site_id=self.site.pk)
        self.assertEqual(r.status_code, 200)
        rows = r.json()['readings']
        self.assertEqual([x['distance_cm'] for x in rows], [100.0, None, 140.0])
        self.assertEqual([x['level_cm'] for x in rows], [50.0, None, 10.0])
        self.assertTrue(rows[0]['measured_at'].endswith('+09:00'))

    def test_asc_limit_and_range(self):
        rows = self.get(URL, site_id=self.site.pk, order='asc', limit=2).json()['readings']
        self.assertEqual([x['distance_cm'] for x in rows], [140.0, None])
        start = (timezone.now() - datetime.timedelta(minutes=25)).astimezone(KST).isoformat()
        end = (timezone.now() - datetime.timedelta(minutes=5)).astimezone(KST).isoformat()
        rows = self.get(URL, site_id=self.site.pk, **{'from': start, 'to': end}).json()['readings']
        self.assertEqual([x['distance_cm'] for x in rows], [100.0, None])

    def test_level_follows_baseline_correction(self):
        ShopSite.objects.filter(pk=self.site.pk).update(baseline_cm=160.0)
        rows = self.get(URL, site_id=self.site.pk).json()['readings']
        self.assertEqual(rows[0]['level_cm'], 60.0)

    def test_errors(self):
        self.assertEqual(self.get(URL, key=None, site_id=self.site.pk).status_code, 401)
        self.assertEqual(self.get(URL, key='nope', site_id=self.site.pk).status_code, 401)
        self.assertEqual(self.get(URL).status_code, 400)
        self.assertEqual(self.get(URL, site_id=9999).status_code, 404)
        for params in ({'from': '10/08'}, {'order': 'up'}, {'limit': 0}, {'limit': 'x'}, {'limit': 10001}):
            self.assertEqual(self.get(URL, site_id=self.site.pk, **params).status_code, 400, params)


class LatestStatusTests(ShopTestCase):
    def add(self, distance, minutes_ago=0, received_minutes_ago=None):
        reading = WaterLevelReading.objects.create(
            site=self.site, distance_cm=distance,
            measured_at=timezone.now() - datetime.timedelta(minutes=minutes_ago))
        if received_minutes_ago is not None:
            WaterLevelReading.objects.filter(pk=reading.pk).update(
                received_at=timezone.now() - datetime.timedelta(minutes=received_minutes_ago))
        return reading

    def test_no_data(self):
        body = self.latest()
        self.assertEqual((body['status'], body['stale'], body['reading']), ('no_data', True, None))
        self.assertIsNone(body['last_received_at'])

    def test_status_levels_and_boundaries(self):
        # baseline 150 → distance 120: 수위 30(=warn 경계), 90: 60(=danger 경계)
        for minutes, distance, expected in ((4, 140.0, 'normal'), (3, 120.1, 'normal'), (2, 120.0, 'warn'),
                                            (1, 90.1, 'warn'), (0, 90.0, 'danger')):
            self.add(distance, minutes_ago=minutes)
            body = self.latest()
            self.assertEqual(body['status'], expected, distance)
            self.assertEqual(body['reading']['level_cm'], 150.0 - distance)
            self.assertFalse(body['stale'])

    def test_failed_latest_reading_is_no_data_with_last_valid(self):
        self.add(140.0, minutes_ago=1)
        self.add(None, minutes_ago=0)
        body = self.latest()
        self.assertEqual(body['status'], 'no_data')
        self.assertIsNone(body['reading']['level_cm'])
        self.assertEqual(body['last_valid_reading']['distance_cm'], 140.0)

    def test_thresholds_not_set(self):
        site = ShopSite.objects.create(name='임계값 없음', baseline_cm=150.0)
        WaterLevelReading.objects.create(site=site, distance_cm=10.0, measured_at=timezone.now())
        self.assertEqual(self.latest(site)['status'], 'normal')

    def test_stale(self):
        self.add(140.0, received_minutes_ago=6)
        body = self.latest()
        self.assertEqual((body['status'], body['stale']), ('normal', True))
        self.add(140.0, minutes_ago=-0.1, received_minutes_ago=1)
        self.assertFalse(self.latest()['stale'])

    def test_auth_and_404(self):
        url = f'/api/shop/sites/{self.site.pk}/latest/'
        self.assertEqual(self.get(url, key=None).status_code, 401)
        self.assertEqual(self.get('/api/shop/sites/9999/latest/').status_code, 404)


class HealthAndCommandTests(ShopTestCase):
    def test_health_without_key(self):
        r = self.client.get('/api/shop/health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')

    def test_check_stale_sites(self):
        fresh = ShopSite.objects.create(name='정상 가게', baseline_cm=100.0)
        WaterLevelReading.objects.create(site=fresh, distance_cm=90.0, measured_at=timezone.now())
        old = WaterLevelReading.objects.create(site=self.site, distance_cm=90.0, measured_at=timezone.now())
        WaterLevelReading.objects.filter(pk=old.pk).update(received_at=timezone.now() - datetime.timedelta(minutes=15))
        ShopSite.objects.create(name='설치만 됨', baseline_cm=100.0)

        out = io.StringIO()
        with self.assertLogs('shopsense', level='WARNING') as logs:
            call_command('check_stale_sites', '--minutes', '10', stdout=out)
        text = out.getvalue()
        self.assertIn('대학가 가게 1호', text)
        self.assertIn('15분 전', text)
        self.assertIn('설치만 됨', text)
        self.assertIn('수신 기록 없음', text)
        self.assertNotIn('정상 가게', text)
        self.assertIn('checked=3 stale=2', text)
        self.assertEqual(len(logs.output), 2)

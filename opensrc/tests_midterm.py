"""7주차 데이터 수집 실습 · 8주차 중간평가: 센서 가동 판정, 칸 인정, 점수, 대시보드 API, TA CSV."""
import datetime
import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from sensor.models import IpDb, SensorData
from sensor.views import normalize_sensor_name

from . import grading
from .models import CampusSensor, CollectionDay, SlotAssignment, Submission

KST = datetime.timezone(datetime.timedelta(hours=9))
DAY = datetime.date(2026, 10, 28)


def at(date, hour, minute=0):
    return datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=KST)


MIDTERM_SETTINGS = dict(OPENSRC_TEAM_COUNT=9, OPENSRC_SLOT_HOURS=range(9, 18), OPENSRC_SENSOR_ONLINE_MINUTES=10,
                        OPENSRC_MIDTERM_FULL_SCORE=10, OPENSRC_MIDTERM_PENALTY=2, OPENSRC_MIDTERM_CACHE_SECONDS=0)


class NormalizeTests(TestCase):
    def test_opensrc_names_are_not_collapsed_into_lab_sensors(self):
        self.assertEqual(normalize_sensor_name('opensrc_team1'), 'opensrc_team1')
        self.assertEqual(normalize_sensor_name(' Opensrc_Team3 '), 'opensrc_team3')
        self.assertEqual(normalize_sensor_name('sensor1'), 'sensor 01')

    def test_sensing_endpoint_keeps_opensrc_name(self):
        r = self.client.get('/sensor/sensing/', {'mac': 'B8:27:EB:00:00:01', 'sensor': 'Opensrc_team1', 'sender': 'pi',
                                                 'mode': 'direct', 'temp': 21.5, 'co2': 450, 'time': 1792000000})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SensorData.objects.get().sensor, 'opensrc_team1')
        self.client.get('/sensor/sensing/', {'sensor': 'opensrc_team1', 'ip': '172.30.1.2'})
        self.assertEqual(IpDb.objects.get().sensor, 'opensrc_team1')


@override_settings(**MIDTERM_SETTINGS)
class GradingTests(TestCase):
    def setUp(self):
        self.sensors = [
            CampusSensor.objects.create(number=n, ble_name=f'opensrc_team{n}', lab_sensor=f'opensrc_team{n}',
                                        ble_mac='B8:27:EB:00:00:01' if n == 1 else '')
            for n in range(1, 6)
        ]
        CollectionDay.objects.create(date=DAY)
        self.slot = SlotAssignment.objects.create(date=DAY, start_hour=10, team_no=3)
        self.now = at(DAY, 12)  # 10–11 칸이 끝난 뒤

    # --- helpers -------------------------------------------------------
    def lab(self, number, when, via='data'):
        name = f'opensrc_team{number}'
        if via == 'data':
            SensorData.objects.create(sensor=name, mac='x', receiver='pi', mode='direct',
                                      temperature=20, co2=400, sensing_time=when.timestamp())
        else:
            IpDb.objects.create(sensor=name, ip='10.0.0.1', time=int(when.timestamp()))

    def upload(self, team_no, when, sensor='opensrc_team1', mac='', rssi=-60, lat=36.62, lon=127.45, source='upload'):
        s = Submission.objects.create(source=source, team=f'Team {team_no}', team_no=team_no, sensor=sensor, mac=mac,
                                      lat=lat, lon=lon, rssi=rssi, status='ok')
        Submission.objects.filter(pk=s.pk).update(received_at=when)
        return s

    def slot_result(self, now=None):
        return grading.evaluate_slot(DAY, 10, self.slot, self.sensors, now or self.now)

    # --- 센서 가동 ---------------------------------------------------------
    def test_online_from_either_table_within_slot_only(self):
        self.lab(1, at(DAY, 10, 5))
        self.lab(2, at(DAY, 10, 59), via='ip')
        self.lab(3, at(DAY, 9, 59))   # 칸 밖
        self.lab(4, at(DAY, 11, 0))   # 칸 밖 (end 미포함)
        online = grading.sensors_online_between(self.sensors, at(DAY, 10), at(DAY, 11))
        self.assertEqual(sorted(s.number for s in online), [1, 2])

    def test_realtime_status(self):
        self.lab(1, self.now - datetime.timedelta(minutes=9))
        self.lab(2, self.now - datetime.timedelta(minutes=11), via='ip')
        self.lab(2, self.now - datetime.timedelta(hours=5))
        rows = grading.sensor_status(self.sensors, self.now)
        by = {r['number']: r for r in rows}
        self.assertTrue(by[1]['online'])
        self.assertFalse(by[2]['online'])
        self.assertEqual(by[2]['last_seen'], '2026-10-28 11:49:00')  # 두 테이블 중 더 최근 것, KST
        self.assertEqual(by[2]['last_source'], 'ip')
        self.assertFalse(by[5]['online'])
        self.assertIsNone(by[5]['last_seen'])

    # --- 유효 데이터·센서 대응 ---------------------------------------------
    def test_valid_row_rules(self):
        ok = {'rssi': -60, 'lat': 36.6, 'lon': 127.4}
        self.assertTrue(grading.is_valid_row(ok))
        for bad in ({'rssi': None}, {'rssi': 0}, {'rssi': -101}, {'rssi': 1}, {'lat': None}, {'lat': 0}, {'lon': 0.0}):
            self.assertFalse(grading.is_valid_row({**ok, **bad}), bad)

    def test_match_sensor(self):
        m = lambda mac, name: getattr(grading.match_sensor(self.sensors, mac, name), 'number', None)
        self.assertEqual(m('b8-27-eb-00-00-01', 'whatever'), 1)         # 등록된 MAC 우선
        self.assertEqual(m('', 'Opensrc_Team 2'), 2)                      # 기기명 (대소문자·공백 무시)
        self.assertEqual(m('AA:BB:CC:DD:EE:FF', 'opemsrc_team5'), 5)      # 오타 → team 번호
        self.assertIsNone(m('AA:BB:CC:DD:EE:FF', 'team9 sensor'))         # 없는 번호
        self.assertIsNone(m('', ''))

    # --- 칸 판정 -------------------------------------------------------------
    def test_slot_ok_when_every_online_sensor_has_valid_data(self):
        for n in (1, 2, 3):
            self.lab(n, at(DAY, 10, 10))
        self.upload(3, at(DAY, 10, 20), sensor='opensrc_team1', lat=36.620, lon=127.450)
        self.upload(3, at(DAY, 10, 21), sensor='opensrc_team2', lat=36.621, lon=127.451)
        self.upload(3, at(DAY, 10, 22), sensor='OPENSRC_TEAM3', lat=36.622, lon=127.452)
        self.upload(3, at(DAY, 10, 23), sensor='opensrc_team4', lat=36.623, lon=127.453)  # 미가동 센서: 요구 대상 아님
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_OK)
        self.assertEqual((r['online'], r['collected'], r['missing'], r['extra']), ([1, 2, 3], [1, 2, 3], [], [4]))
        self.assertEqual((r['rows'], r['valid_rows']), (4, 4))

    def test_slot_missing_when_an_online_sensor_has_no_valid_data(self):
        for n in (1, 2):
            self.lab(n, at(DAY, 10, 10))
        self.upload(3, at(DAY, 10, 20), sensor='opensrc_team1', lat=36.620)
        self.upload(3, at(DAY, 10, 21), sensor='opensrc_team2', rssi=None, lat=36.621)   # rssi 없음 → 무효
        self.upload(3, at(DAY, 10, 22), sensor='opensrc_team2', rssi=0, lat=36.622)      # rssi 0 → 무효
        self.upload(3, at(DAY, 10, 23), sensor='opensrc_team2', lat=0, lon=0)            # 위경도 0 → 무효
        self.upload(3, at(DAY, 11, 0), sensor='opensrc_team2', lat=36.624)               # 칸 밖
        self.upload(4, at(DAY, 10, 30), sensor='opensrc_team2', lat=36.625)              # 다른 팀
        self.upload(3, at(DAY, 10, 31), sensor='opensrc_team2', lat=36.626, source='test')  # 4주차 행
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_MISSING)
        self.assertEqual((r['online'], r['collected'], r['missing']), ([1, 2], [1], [2]))
        self.assertEqual((r['rows'], r['valid_rows']), (4, 1))

    def test_slot_review_when_all_locations_identical(self):
        for n in (1, 2):
            self.lab(n, at(DAY, 10, 10))
        self.upload(3, at(DAY, 10, 20), sensor='opensrc_team1')
        self.upload(3, at(DAY, 10, 21), sensor='opensrc_team2')
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_REVIEW)
        self.assertTrue(r['fixed_location'])
        self.assertEqual(r['missing'], [])
        # 누락이 있으면 검토가 아니라 누락
        self.lab(4, at(DAY, 10, 10))
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_MISSING)
        self.assertTrue(r['fixed_location'])

    def test_single_row_is_not_flagged_as_fixed(self):
        self.lab(1, at(DAY, 10, 10))
        self.upload(3, at(DAY, 10, 20), sensor='opensrc_team1')
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_OK)
        self.assertFalse(r['fixed_location'])

    def test_slot_review_when_no_sensor_online(self):
        self.upload(3, at(DAY, 10, 20), sensor='opensrc_team1')
        r = self.slot_result()
        self.assertEqual(r['status'], grading.STATUS_REVIEW)
        self.assertIn('가동 기록이 있는 센서가 없음', r['notes'][0])

    def test_pending_progress_and_unassigned(self):
        self.lab(1, at(DAY, 10, 10))
        self.assertEqual(self.slot_result(now=at(DAY, 9, 59))['status'], grading.STATUS_PENDING)
        r = self.slot_result(now=at(DAY, 10, 30))
        self.assertEqual(r['status'], grading.STATUS_PROGRESS)
        self.assertEqual(r['missing'], [1])  # 진행 중에도 현재까지의 누락을 보여준다
        self.assertEqual(grading.evaluate_slot(DAY, 11, None, self.sensors, self.now)['status'],
                         grading.STATUS_UNASSIGNED)

    # --- 점수 ----------------------------------------------------------------
    def test_scores(self):
        self.assertEqual(grading.score(0), 10)
        self.assertEqual(grading.score(3), 4)
        self.assertEqual(grading.score(6), 0)

    def test_evaluate_grid_and_team_summary(self):
        day2 = DAY + datetime.timedelta(days=1)
        CollectionDay.objects.create(date=day2)
        SlotAssignment.objects.create(date=DAY, start_hour=11, team_no=3)
        SlotAssignment.objects.create(date=DAY, start_hour=12, team_no=3)
        SlotAssignment.objects.create(date=day2, start_hour=9, team_no=3)
        SlotAssignment.objects.create(date=day2, start_hour=10, team_no=5)
        # 10시 칸: 인정 / 11시 칸: 누락 / 12시 칸: 진행 중 / 다음날: 예정
        self.lab(1, at(DAY, 10, 10))
        self.upload(3, at(DAY, 10, 20))
        self.lab(1, at(DAY, 11, 10))
        now = at(DAY, 12, 30)

        data = grading.evaluate(now=now)
        self.assertEqual(data['dates'], ['2026-10-28', '2026-10-29'])
        self.assertEqual(data['hours'], list(range(9, 18)))
        self.assertEqual(len(data['slots']), 18)
        by = {(s['date'], s['hour']): s['status'] for s in data['slots']}
        self.assertEqual(by[('2026-10-28', 9)], 'unassigned')
        self.assertEqual(by[('2026-10-28', 10)], 'ok')
        self.assertEqual(by[('2026-10-28', 11)], 'missing')
        self.assertEqual(by[('2026-10-28', 12)], 'progress')
        self.assertEqual(by[('2026-10-29', 9)], 'pending')
        self.assertEqual(data['now'], '2026-10-28 12:30:00')

        teams = {t['team_no']: t for t in data['teams']}
        self.assertEqual(len(teams), 9)
        t3 = teams[3]
        self.assertEqual((t3['slots'], t3['ok'], t3['missing'], t3['remaining'], t3['score'], t3['final']),
                         (4, 1, 1, 2, 8, False))
        self.assertEqual((teams[5]['slots'], teams[5]['score'], teams[5]['final']), (1, 10, False))
        self.assertEqual((teams[9]['slots'], teams[9]['score'], teams[9]['final']), (0, 10, True))

    def test_dates_fall_back_to_assignments(self):
        CollectionDay.objects.all().delete()
        self.assertEqual(grading.collection_dates(), [DAY])

    def test_inactive_sensor_ignored(self):
        CampusSensor.objects.filter(number=1).update(active=False)
        self.lab(1, at(DAY, 10, 10))
        data = grading.evaluate(now=self.now)
        self.assertEqual([s['number'] for s in data['sensors']], [2, 3, 4, 5])
        slot = next(s for s in data['slots'] if s['hour'] == 10)
        self.assertEqual(slot['status'], 'review')  # 가동 센서 없음
        self.assertEqual(slot['online'], [])


@override_settings(**MIDTERM_SETTINGS)
class MidtermViewTests(TestCase):
    def setUp(self):
        CampusSensor.objects.create(number=1, ble_name='opensrc_team1', lab_sensor='opensrc_team1', location='도서관')
        CollectionDay.objects.create(date=DAY)
        SlotAssignment.objects.create(date=DAY, start_hour=9, team_no=1)
        SlotAssignment.objects.create(date=DAY, start_hour=10, team_no=2)

    def test_dashboard_is_public(self):
        r = self.client.get('/sensor/opensrc/check/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '중간평가')
        self.assertEqual(self.client.get('/sensor/opensrc/check').status_code, 200)

    def test_status_api(self):
        r = self.client.get('/sensor/opensrc/api/midterm/')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['dates'], ['2026-10-28'])
        self.assertEqual(len(data['slots']), 9)
        self.assertEqual(data['sensors'][0]['location'], '도서관')
        self.assertEqual(data['online_minutes'], 10)
        self.assertEqual(data['timezone'], 'Asia/Seoul')
        self.assertEqual({s['team_no'] for s in data['slots']}, {1, 2, None})

    def test_export_requires_staff(self):
        r = self.client.get('/sensor/opensrc/midterm_scores.csv')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])

        User.objects.create_user('student', password='pw', is_staff=False)
        self.client.login(username='student', password='pw')
        self.assertEqual(self.client.get('/sensor/opensrc/midterm_scores.csv').status_code, 302)

        User.objects.create_user('ta', password='pw', is_staff=True)
        self.client.login(username='ta', password='pw')
        r = self.client.get('/sensor/opensrc/midterm_scores.csv')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('text/csv'))
        lines = r.content.decode('utf-8-sig').strip().splitlines()
        self.assertTrue(lines[0].startswith('팀,총점,확정,인정,검토 필요,누락,미완료,칸1,칸1 결과'))
        self.assertEqual(len(lines), 10)  # 헤더 + 9팀
        self.assertTrue(lines[1].startswith('1,10,N,0,0,0,1,2026-10-28 09–10,예정,0,0,'))

        r = self.client.get('/sensor/opensrc/midterm_scores.csv?format=long')
        lines = r.content.decode('utf-8-sig').strip().splitlines()
        self.assertEqual(lines[0], '팀,칸,결과,가동 센서 수,수집 센서 수,누락 센서,비고,총점,확정')
        self.assertEqual(len(lines), 3)  # 헤더 + 배정 2칸


class MergeMigrationTests(TestCase):
    """0003: 5주차 TeamSubmission 행이 Submission(source='upload', team_no) 으로 옮겨진다."""

    def test_merge_copies_rows_and_fills_team_no(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate([('opensrc', '0002_teamsubmission_and_more')])
        apps = executor.loader.project_state([('opensrc', '0002_teamsubmission_and_more')]).apps
        OldSubmission = apps.get_model('opensrc', 'Submission')
        TeamSubmission = apps.get_model('opensrc', 'TeamSubmission')
        OldSubmission.objects.create(team='team 1', sensor='opensrc_week_3', status='verified')
        t = TeamSubmission.objects.create(team='Team 7', sensor='Opensrc_team7', mac='AA', sender='s', temp=1, humidity=2,
                                          aqi=3, tvoc=4, eco2=5, timestamp=6, lat=7, lon=8, status='ok', detail='')
        TeamSubmission.objects.filter(pk=t.pk).update(received_at=at(DAY, 10))

        executor = MigrationExecutor(connection)
        executor.migrate([('opensrc', '0003_midterm_merge_submissions')])
        rows = sorted(Submission.objects.values_list('source', 'team', 'team_no', 'sensor', 'status'))
        self.assertEqual(rows, [('test', 'team 1', None, 'opensrc_week_3', 'verified'),
                                ('upload', 'Team 7', 7, 'Opensrc_team7', 'ok')])
        self.assertEqual(Submission.objects.get(source='upload').received_at, at(DAY, 10))
        self.assertNotIn('opensrc_team_submission', connection.introspection.table_names())

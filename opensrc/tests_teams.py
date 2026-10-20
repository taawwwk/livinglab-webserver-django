import datetime
import json
import time

from django.test import TestCase, override_settings
from django.utils import timezone

from sensor.models import SensorData, SensorLocation

from .models import Submission

VALUES = {'sensor': 'team1 sensor', 'mac': 'DC:A6:32:AA:BB:CC', 'sender': 'abcd-1234',
          'temp': 23.4, 'humidity': 51.2, 'AQI': 2, 'TVOC': 120, 'eCO2': 450,
          'timestamp': 1790000000, 'lat': 36.62, 'lon': 127.45}


def body(**overrides):
    b = {'key': 'opensrc-team 1', 'team': 'Team 1', **VALUES}
    b.update(overrides)
    return b


@override_settings(OPENSRC_TEAM_COUNT=9)
class TeamUploadTests(TestCase):
    url = '/sensor/opensrc/upload/'

    def post(self, data, url=None):
        return self.client.post(url or self.url, json.dumps(data), content_type='')

    def test_upload_ok(self):
        r = self.post(body())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['result'], 'Success')
        self.assertEqual(r.json()['status'], 'ok')
        s = Submission.objects.get()
        self.assertEqual((s.team, s.sensor, s.eco2), ('Team 1', 'team1 sensor', 450))
        self.assertEqual((s.source, s.team_no, s.rssi), ('upload', 1, None))
        # 7주차 전 앱은 rssi 를 안 보낸다 → 저장은 되지만 경고
        self.assertIn('rssi', r.json()['warning'])
        self.assertIn('rssi 없음', s.detail)

    def test_key_forms_and_team_optional(self):
        # 공백/대소문자 차이는 허용하고, team은 생략해도 key로 판별한다
        for key in ('opensrc-team 9', 'opensrc-team9', 'OPENSRC-TEAM 9 '):
            data = body(key=key)
            del data['team']
            self.assertEqual(self.post(data).status_code, 200, key)
        self.assertEqual(set(Submission.objects.values_list('team', 'team_no')), {('Team 9', 9)})

    def test_no_trailing_slash_and_form_encoded(self):
        self.assertEqual(self.post(body(), url='/sensor/opensrc/upload').status_code, 200)
        r = self.client.post(self.url, {k: str(v) for k, v in body().items()})
        self.assertEqual(r.status_code, 200, r.content)

    def test_bad_key(self):
        for key in ('opensrc2026', 'opensrc-team 10', 'opensrc-team', ''):
            r = self.post(body(key=key))
            self.assertEqual(r.status_code, 400, key)
        self.assertFalse(Submission.objects.exists())

    def test_team_must_match_key(self):
        for team in ('Team 2', 2, '2', 'team2'):
            r = self.post(body(key='opensrc-team 1', team=team))
            self.assertEqual(r.status_code, 400, team)
            self.assertIn('Team 1', r.json()['message'])
        r = self.post(body(key='opensrc-team 1', team='abc'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('정수', r.json()['message'])
        self.assertFalse(Submission.objects.exists())

    def test_team_as_integer(self):
        # 7주차 안내: team 은 1~9 정수. 문자열 "Team 3", "3", "3팀" 도 받는다
        for team in (3, '3', 'Team 3', ' team3 ', '3팀'):
            r = self.post(body(key='opensrc-team 3', team=team))
            self.assertEqual(r.status_code, 200, (team, r.content))
        self.assertEqual(set(Submission.objects.values_list('team', 'team_no')), {('Team 3', 3)})

    def test_rssi(self):
        r = self.post(body(rssi=-67))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('warning', r.json())
        self.assertEqual(Submission.objects.get().rssi, -67)
        self.assertEqual(Submission.objects.get().detail, '')
        # 범위 밖 rssi 는 저장하되 out_of_range 로 표시
        r = self.post(body(rssi=12))
        self.assertEqual(r.json()['status'], 'out_of_range')
        self.assertIn('rssi', r.json()['detail'])
        # 형식 오류도 저장은 되고 경고
        r = self.post(body(rssi='strong'))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Submission.objects.order_by('-id').first().rssi)
        self.assertIn('rssi 형식 오류', r.json()['detail'])

    def test_required_fields(self):
        for field in VALUES:
            data = body()
            del data[field]
            r = self.post(data)
            self.assertEqual(r.status_code, 400, field)
            self.assertIn(field, r.json()['message'])
        self.assertFalse(Submission.objects.exists())

    def test_out_of_range_is_stored_not_rejected(self):
        r = self.post(body(humidity=250, temp=-100))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'out_of_range')
        s = Submission.objects.get()
        self.assertEqual(s.status, 'out_of_range')
        self.assertIn('humidity', s.detail)
        self.assertIn('temp', s.detail)

    def test_stale_clock_flagged(self):
        # RTC 없는 Pi가 1970년으로 시작하는 경우
        self.post(body(timestamp=100))
        self.assertIn('timestamp', Submission.objects.get().detail)

    def test_read_endpoints(self):
        self.post(body())
        self.post(body(key='opensrc-team 2', team='Team 2', mac='DC:A6:32:00:00:01', eCO2=99999))
        self.assertEqual(self.client.get('/sensor/opensrc/teams/').status_code, 200)

        teams = self.client.get('/sensor/opensrc/api/teams/summary').json()['teams']
        self.assertEqual(len(teams), 9)  # 전송이 없는 팀도 0건으로 나온다
        self.assertEqual([(t['team'], t['total'], t['normal'], t['sensors']) for t in teams[:3]],
                         [('Team 1', 1, 1, 1), ('Team 2', 1, 0, 1), ('Team 3', 0, 0, 0)])

        rows = self.client.get('/sensor/opensrc/api/teams/latest?status=ok').json()['rows']
        self.assertEqual([r['team'] for r in rows], ['Team 1'])

        csv_body = b''.join(self.client.get('/sensor/opensrc/teams_export.csv?team=Team 2')
                            .streaming_content)
        self.assertIn(b'Team 2', csv_body)
        self.assertNotIn(b'Team 1', csv_body)

    def test_week4_endpoint_untouched(self):
        # 5주차 key로 4주차 API를 쓸 수는 없다
        r = self.post(body(), url='/sensor/opensrc/test/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('key', r.json()['message'])


@override_settings(OPENSRC_TEAM_COUNT=9)
class TeamDataApiTests(TestCase):
    url = '/sensor/opensrc/data/'

    def make(self, team, received_at, **overrides):
        values = dict(VALUES, **overrides)
        s = Submission.objects.create(
            source=Submission.SOURCE_UPLOAD, team=team, team_no=int(team.split()[1]),
            sensor=values['sensor'], mac=values['mac'], sender=values['sender'],
            temp=values['temp'], humidity=values['humidity'], aqi=values['AQI'],
            tvoc=values['TVOC'], eco2=values['eCO2'], timestamp=values['timestamp'],
            lat=values['lat'], lon=values['lon'], status=Submission.STATUS_OK,
        )
        # received_at은 auto_now_add라 생성 후에 덮어쓴다
        aware = timezone.make_aware(datetime.datetime.strptime(received_at, '%Y-%m-%d %H:%M:%S'),
                                    timezone.get_current_timezone())
        Submission.objects.filter(pk=s.pk).update(received_at=aware)
        return s

    def setUp(self):
        self.make('Team 1', '2026-10-01 09:00:00', temp=20.0)
        self.make('Team 1', '2026-10-02 23:30:00', temp=21.0)
        self.make('Team 1', '2026-10-03 08:00:00', temp=22.0)
        self.make('Team 2', '2026-10-02 10:00:00', temp=30.0)
        # 4주차 행은 팀 데이터 조회에 섞이지 않는다
        Submission.objects.create(source='test', team='Team 1', sensor='sensor 01', status='verified', temp=99.0)

    def test_own_team_only_sorted_ascending(self):
        r = self.client.get(self.url, {'key': 'opensrc-team 1'})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual((payload['team'], payload['count']), ('Team 1', 3))
        self.assertEqual([row['temp'] for row in payload['data']], [20.0, 21.0, 22.0])
        self.assertEqual([row['received_at'] for row in payload['data']],
                         ['2026-10-01 09:00:00', '2026-10-02 23:30:00', '2026-10-03 08:00:00'])
        self.assertEqual(set(payload['data'][0]), {
            'team', 'sensor', 'mac', 'temp', 'humidity', 'AQI', 'TVOC', 'eCO2',
            'timestamp', 'lat', 'lon', 'rssi', 'sender', 'received_at', 'status'})

    def test_date_range_filters(self):
        def temps(**params):
            params['key'] = 'opensrc-team 1'
            return [row['temp'] for row in self.client.get(self.url, params).json()['data']]

        # 날짜만 주면 end 당일까지 포함한다
        self.assertEqual(temps(start='2026-10-02', end='2026-10-02'), [21.0])
        self.assertEqual(temps(start='2026-10-02'), [21.0, 22.0])
        self.assertEqual(temps(end='2026-10-01'), [20.0])
        self.assertEqual(temps(start='2026-10-02 23:00', end='2026-10-03 07:00'), [21.0])
        self.assertEqual(temps(start='2026-10-05'), [])

    def test_team_all(self):
        payload = self.client.get(self.url, {'key': 'opensrc-team 1', 'team': 'all'}).json()
        self.assertEqual((payload['team'], payload['count']), ('all', 4))
        self.assertEqual(sorted({row['team'] for row in payload['data']}), ['Team 1', 'Team 2'])
        # 다른 팀을 콕 집어 요청하는 것은 막는다
        r = self.client.get(self.url, {'key': 'opensrc-team 1', 'team': 'Team 2'})
        self.assertEqual(r.status_code, 400)

    def test_bad_key(self):
        for params in ({}, {'key': ''}, {'key': 'opensrc2026'}, {'key': 'opensrc-team 99'}):
            r = self.client.get(self.url, params)
            self.assertEqual(r.status_code, 400, params)
            self.assertEqual(r.json()['result'], 'Fail')
            self.assertIn('key', r.json()['message'])

    def test_bad_date_format(self):
        for param in ('start', 'end'):
            r = self.client.get(self.url, {'key': 'opensrc-team 1', param: '2026/10/01'})
            self.assertEqual(r.status_code, 400)
            self.assertIn(param, r.json()['message'])
            self.assertIn('2026/10/01', r.json()['message'])

    def test_csv_format(self):
        r = self.client.get(self.url, {'key': 'opensrc-team 1', 'format': 'csv'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('text/csv'))
        self.assertIn('attachment', r['Content-Disposition'])
        lines = b''.join(r.streaming_content).decode('utf-8-sig').strip().splitlines()
        self.assertEqual(lines[0], 'received_at,team,sensor,mac,temp,humidity,AQI,TVOC,'
                                   'eCO2,timestamp,lat,lon,rssi,sender,status')
        self.assertEqual(len(lines), 4)  # 헤더 + Team 1 데이터 3건
        self.assertTrue(lines[1].startswith('2026-10-01 09:00:00,Team 1,'))

    def test_no_trailing_slash(self):
        r = self.client.get('/sensor/opensrc/data', {'key': 'opensrc-team 2'})
        self.assertEqual(r.json()['count'], 1)


@override_settings(OPENSRC_TEAM_COUNT=9, OPENSRC_LAB_SENSOR='sensor 03',
                   OPENSRC_LAB_SENSOR_BY_TEAM={'Team 4': 'sensor 01', 'Team 5': 'sensor 02'})
class LabDataApiTests(TestCase):
    url = '/sensor/opensrc/data/'

    @staticmethod
    def kst(text):
        return timezone.make_aware(datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S'),
                                   timezone.get_current_timezone()).timestamp()

    def lab(self, sensing_time, sensor='sensor 01', temperature=25.5, co2=500):
        return SensorData.objects.create(
            sensor=sensor, mac='D8:3A:DD:00:00:01', receiver='sensor', mode='direct',
            temperature=temperature, co2=co2, sensing_time=sensing_time)

    def get(self, **params):
        params.setdefault('key', 'opensrc-team 4')
        params.setdefault('source', 'lab')
        return self.client.get(self.url, params)

    def setUp(self):
        SensorLocation.objects.create(sensor='sensor 01', latitude=36.626906, longitude=127.457722)

    def test_default_window_is_last_14_days(self):
        now = time.time()
        self.lab(now - 86400, temperature=21.0)
        self.lab(now - 20 * 86400, temperature=99.0)                 # 14일 밖
        self.lab(now - 86400, sensor='sensor 02', temperature=77.0)  # 다른 센서
        payload = self.get().json()
        self.assertEqual((payload['source'], payload['sensor'], payload['count']), ('lab', 'sensor 01', 1))
        row = payload['data'][0]
        self.assertEqual(set(row), {'received_at', 'sensor', 'mac', 'temp', 'co2', 'timestamp',
                                    'lat', 'lon', 'sender'})
        self.assertEqual((row['temp'], row['sender'], row['lat'], row['lon']),
                         (21.0, 'sensor', 36.626906, 127.457722))

    def test_range_order_and_raw_values(self):
        self.lab(self.kst('2026-09-11 12:00:00') + 0.25, temperature=-50.0, co2=0)
        self.lab(self.kst('2026-09-10 09:00:00'))
        self.lab(self.kst('2026-09-12 08:00:00'))
        rows = self.get(start='2026-09-10', end='2026-09-11').json()['data']
        self.assertEqual([r['received_at'] for r in rows],
                         ['2026-09-10 09:00:00', '2026-09-11 12:00:00'])
        # 센서 오류값(-50℃, co2 0)과 소수점 timestamp도 정제 없이 그대로
        self.assertEqual((rows[1]['temp'], rows[1]['co2']), (-50.0, 0))
        self.assertEqual(rows[1]['timestamp'], self.kst('2026-09-11 12:00:00') + 0.25)

        # end만 주면 그 시점부터 14일 전까지
        self.assertEqual(self.get(end='2026-09-12').json()['count'], 3)

    def test_span_limit_and_bad_dates(self):
        r = self.get(start='2026-08-01', end='2026-09-30')
        self.assertEqual(r.status_code, 400)
        self.assertIn('31일', r.json()['message'])
        r = self.get(start='09-01')
        self.assertEqual(r.status_code, 400)
        self.assertIn('start', r.json()['message'])

    def test_key_and_source_validation(self):
        for params in ({'key': ''}, {'key': 'opensrc2026'}):
            r = self.get(**params)
            self.assertEqual(r.status_code, 400)
            self.assertIn('key', r.json()['message'])
        r = self.get(source='weather')
        self.assertEqual(r.status_code, 400)
        self.assertIn('source', r.json()['message'])

    def test_csv(self):
        self.lab(self.kst('2026-09-10 09:00:00'), temperature=21.5, co2=612)
        r = self.get(start='2026-09-10', end='2026-09-10', format='csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        lines = b''.join(r.streaming_content).decode('utf-8-sig').strip().splitlines()
        self.assertEqual(lines[0], 'received_at,sensor,mac,temp,co2,timestamp,lat,lon,sender')
        self.assertTrue(lines[1].startswith('2026-09-10 09:00:00,sensor 01,D8:3A:DD:00:00:01,21.5,612,'))

    def test_team_mode_unchanged(self):
        # source가 없거나 team이면 기존 팀 데이터 응답 형식 그대로
        for params in ({}, {'source': 'team'}):
            payload = self.client.get(self.url, {'key': 'opensrc-team 4', **params}).json()
            self.assertEqual((payload['team'], payload['count']), ('Team 4', 0))

    def test_sensor_assigned_per_team(self):
        now = time.time()
        for sensor, temp in (('sensor 01', 21.0), ('sensor 02', 22.0), ('sensor 03', 23.0)):
            self.lab(now - 3600, sensor=sensor, temperature=temp)

        def fetch(team_no, **extra):
            payload = self.get(key=f'opensrc-team {team_no}', **extra).json()
            return payload['sensor'], [r['sensor'] for r in payload['data']], [r['temp'] for r in payload['data']]

        self.assertEqual(fetch(4), ('sensor 01', ['sensor 01'], [21.0]))
        self.assertEqual(fetch(5), ('sensor 02', ['sensor 02'], [22.0]))
        # 매핑에 없는 팀은 OPENSRC_LAB_SENSOR 기본값
        self.assertEqual(fetch(9), ('sensor 03', ['sensor 03'], [23.0]))
        # 학생이 쿼리로 센서를 바꿀 수 없다 (sensor, team=all 모두 무시)
        self.assertEqual(fetch(4, sensor='sensor 02'), ('sensor 01', ['sensor 01'], [21.0]))
        self.assertEqual(fetch(4, team='all'), ('sensor 01', ['sensor 01'], [21.0]))
        # CSV 파일명에도 배정된 센서가 들어간다
        r = self.get(key='opensrc-team 5', format='csv')
        self.assertIn('opensrc_lab_sensor_02.csv', r['Content-Disposition'])


class LabSensorMappingSettingsTests(TestCase):
    def test_every_team_has_distinct_sensor(self):
        from django.conf import settings
        mapping = settings.OPENSRC_LAB_SENSOR_BY_TEAM
        self.assertEqual(set(mapping), {f'Team {n}' for n in range(1, settings.OPENSRC_TEAM_COUNT + 1)})
        self.assertEqual(len(set(mapping.values())), len(mapping))

import json

from django.test import TestCase, override_settings

from .models import TeamSubmission

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
        s = TeamSubmission.objects.get()
        self.assertEqual((s.team, s.sensor, s.eco2), ('Team 1', 'team1 sensor', 450))

    def test_key_forms_and_team_optional(self):
        # 공백/대소문자 차이는 허용하고, team은 생략해도 key로 판별한다
        for key in ('opensrc-team 9', 'opensrc-team9', 'OPENSRC-TEAM 9 '):
            data = body(key=key)
            del data['team']
            self.assertEqual(self.post(data).status_code, 200, key)
        self.assertEqual(set(TeamSubmission.objects.values_list('team', flat=True)), {'Team 9'})

    def test_no_trailing_slash_and_form_encoded(self):
        self.assertEqual(self.post(body(), url='/sensor/opensrc/upload').status_code, 200)
        r = self.client.post(self.url, {k: str(v) for k, v in body().items()})
        self.assertEqual(r.status_code, 200, r.content)

    def test_bad_key(self):
        for key in ('opensrc2026', 'opensrc-team 10', 'opensrc-team', ''):
            r = self.post(body(key=key))
            self.assertEqual(r.status_code, 400, key)
        self.assertFalse(TeamSubmission.objects.exists())

    def test_team_must_match_key(self):
        r = self.post(body(key='opensrc-team 1', team='Team 2'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Team 1', r.json()['message'])

    def test_required_fields(self):
        for field in VALUES:
            data = body()
            del data[field]
            r = self.post(data)
            self.assertEqual(r.status_code, 400, field)
            self.assertIn(field, r.json()['message'])
        self.assertFalse(TeamSubmission.objects.exists())

    def test_out_of_range_is_stored_not_rejected(self):
        r = self.post(body(humidity=250, temp=-100))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'out_of_range')
        s = TeamSubmission.objects.get()
        self.assertEqual(s.status, 'out_of_range')
        self.assertIn('humidity', s.detail)
        self.assertIn('temp', s.detail)

    def test_stale_clock_flagged(self):
        # RTC 없는 Pi가 1970년으로 시작하는 경우
        self.post(body(timestamp=100))
        self.assertIn('timestamp', TeamSubmission.objects.get().detail)

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

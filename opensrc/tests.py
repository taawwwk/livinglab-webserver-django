import json
import struct

from django.test import TestCase, override_settings

from . import otp
from .models import Submission

KEY = b'test-secret'
MAC = 'DC:A6:32:12:34:56'
VALUES = {'temp': 23.45, 'humidity': 51.2, 'AQI': 2, 'TVOC': 120, 'eCO2': 450, 'timestamp': 1790000000}


def make_raw(values=VALUES, mac=MAC, key=KEY, tag_len=8):
    payload = struct.pack('<hHBHHI', round(values['temp'] * 100), round(values['humidity'] * 100),
                          values['AQI'], values['TVOC'], values['eCO2'], values['timestamp'])
    return (payload + otp.compute_tag(key, otp.parse_mac(mac), payload, tag_len)).hex()


def body(**overrides):
    b = {'key': 'opensrc2026', 'team': 'team 1', 'sensor': 'sensor 01', 'mac': MAC,
         'lat': 36.62, 'lon': 127.45, 'sender': 'abcd-1234', 'raw': make_raw(), **VALUES}
    b.update(overrides)
    return b


@override_settings(OPENSRC_HMAC_KEY=KEY, OPENSRC_TAG_LEN=8, OPENSRC_API_KEY='opensrc2026')
class SubmitTests(TestCase):
    url = '/sensor/opensrc/test/'

    def post(self, data, url=None, **kwargs):
        # 강의자료상 "Header: None" — Content-Type 없이 보내도 받아야 한다
        return self.client.post(url or self.url, json.dumps(data), content_type='', **kwargs)

    def test_verified(self):
        r = self.post(body())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['result'], 'Success')
        self.assertEqual(r.json()['received_data'], {'team': 'team 1', 'sensor': 'sensor 01'})
        self.assertEqual(Submission.objects.get().status, 'verified')

    def test_no_trailing_slash_and_colon_hex(self):
        raw = make_raw()
        colon = ':'.join(raw[i:i + 2] for i in range(0, len(raw), 2)).upper()
        r = self.post(body(raw=colon, mac=MAC.lower()), url='/sensor/opensrc/test')
        self.assertEqual(r.status_code, 200, r.content)

    def test_form_encoded(self):
        r = self.client.post(self.url, {k: str(v) for k, v in body().items()})
        self.assertEqual(r.status_code, 200, r.content)

    def test_fabricated_value_in_raw(self):
        forged = dict(VALUES, temp=30.0)
        raw = make_raw(forged, key=b'guess')
        r = self.post(body(raw=raw, temp=30.0))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Submission.objects.get().status, 'bad_tag')

    def test_other_sensor_mac(self):
        r = self.post(body(mac='DC:A6:32:00:00:01'))
        self.assertEqual(Submission.objects.get().status, 'bad_tag')
        self.assertEqual(r.json()['result'], 'Fail')

    def test_parse_mismatch_returns_expected(self):
        r = self.post(body(humidity=5120))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['status'], 'value_mismatch')
        self.assertIn('humidity', r.json()['message'])
        self.assertEqual(r.json()['expected']['humidity'], 51.2)

    def test_missing_raw_and_bad_raw(self):
        self.post(body(raw=''))
        self.post(body(raw='zz'))
        self.post(body(raw=make_raw()[:26]))  # 태그 없는 기존 13바이트 패킷
        self.assertEqual(list(Submission.objects.order_by('id').values_list('status', flat=True)),
                         ['no_raw', 'bad_raw', 'bad_raw'])

    def test_wrong_key_not_stored(self):
        r = self.post(body(key='nope'))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Submission.objects.exists())

    def test_negative_temperature(self):
        v = dict(VALUES, temp=-5.25)
        r = self.post(body(raw=make_raw(v), temp=-5.25))
        self.assertEqual(r.status_code, 200, r.content)

    def test_read_endpoints(self):
        self.post(body())
        self.post(body(team='team 2', raw=''))
        self.assertEqual(self.client.get('/sensor/opensrc/check/').status_code, 200)
        teams = self.client.get('/sensor/opensrc/api/summary').json()['teams']
        self.assertEqual([(t['team'], t['verified'], t['total']) for t in teams],
                         [('team 1', 1, 1), ('team 2', 0, 1)])
        rows = self.client.get('/sensor/opensrc/api/latest?team=team 1').json()['rows']
        self.assertEqual(len(rows), 1)
        csv_body = b''.join(self.client.get('/sensor/opensrc/export.csv?status=verified').streaming_content)
        self.assertIn('team 1'.encode(), csv_body)
        self.assertNotIn('team 2'.encode(), csv_body)

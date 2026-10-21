import datetime

from django.test import TestCase

from .models import IpDb, SensorData

KST = datetime.timezone(datetime.timedelta(hours=9))


def epoch(text):
    return datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST).timestamp()


class LatestSensorIpTests(TestCase):
    url = '/sensor/new/ip'

    def data(self, sensor, mac, when, mode='direct'):
        SensorData.objects.create(sensor=sensor, mac=mac, receiver='pi', mode=mode,
                                  temperature=20, co2=400, sensing_time=epoch(when))

    def test_latest_ip_with_mac_and_kst_time(self):
        IpDb.objects.create(sensor='sensor 01', ip='172.30.1.1', time=int(epoch('2026-10-21 09:00:00')))
        IpDb.objects.create(sensor='sensor 01', ip='172.30.1.2', time=int(epoch('2026-10-21 14:20:45')))
        IpDb.objects.create(sensor='sensor 02', ip='172.30.2.1', time=int(epoch('2026-10-01 00:00:05')))
        self.data('sensor 01', 'D8:3A:DD:00:00:01', '2026-10-21 10:00:00')
        self.data('sensor 01', 'D8:3A:DD:00:00:99', '2026-10-21 11:00:00')
        # 더 최근이지만 폰이 보낸 mobile 행의 mac(UUID)은 쓰지 않는다
        self.data('sensor 01', 'FAA379DA-A41A-53CF-C3BC-F1873953ED2B', '2026-10-21 12:00:00', mode='mobile')
        self.data('sensor 02', 'FAA379DA-0000', '2026-10-21 12:00:00', mode='mobile')

        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        rows = {row['sensor']: row for row in r.json()}
        self.assertEqual(rows['sensor 01'], {'sensor': 'sensor 01', 'ip': '172.30.1.2',
                                             'mac': 'D8:3A:DD:00:00:99', 'time': '2026-10-21 14:20:45'})
        # direct 측정 데이터가 없는 센서는 mac null, 자정 직후 시각도 KST 날짜로
        self.assertEqual(rows['sensor 02'], {'sensor': 'sensor 02', 'ip': '172.30.2.1',
                                             'mac': None, 'time': '2026-10-01 00:00:05'})

    def test_empty(self):
        self.assertEqual(self.client.get(self.url).json(), [])

"""중간평가 대시보드 테스트용 샘플 데이터.

    python manage.py seed_midterm                 # 센서 5대, 수집 날짜 5일, 배정표 45칸, 샘플 수신/업로드
    python manage.py seed_midterm --start 2026-10-28
    python manage.py seed_midterm --no-samples    # 설정만 넣고 샘플 데이터는 넣지 않음
    python manage.py seed_midterm --reset         # 이 명령이 넣은 것을 모두 지움

샘플 행은 receiver/sender 가 'opensrc-seed' 라서 --reset 으로 골라 지울 수 있다.
livinglab 테이블(sensor_sensor_data)에도 샘플 행이 들어가므로 운영 DB에서는 --no-samples 를 쓸 것.
"""
import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from opensrc.models import CampusSensor, CollectionDay, SlotAssignment, Submission
from sensor.models import IpDb, SensorData

SEED = 'opensrc-seed'

# 강의자료 5~10쪽
SENSORS = [
    (1, '도서관 뒷편 (진로창업본부 입구)'),
    (2, '사회과학대 입구'),
    (3, '사회과학대 옆 이마트24 건너편'),
    (4, '테니스장 앞'),
    (5, '테니스장 건너편'),
]


def rotation(day_index, hour_index, team_count):
    """강의자료 15쪽 배정 예시: 09–10 행이 1,3,5,7,9팀, 다음 행은 한 팀씩 밀린다."""
    return (hour_index + 2 * day_index) % team_count + 1


class Command(BaseCommand):
    help = '중간평가 대시보드용 설정(센서·날짜·배정표)과 샘플 데이터를 넣는다'

    def add_arguments(self, parser):
        parser.add_argument('--start', help='수집 시작 날짜 (YYYY-MM-DD). 기본: 오늘(KST) - 2일, 5일 연속')
        parser.add_argument('--days', type=int, default=5)
        parser.add_argument('--no-samples', action='store_true', help='수신/업로드 샘플 데이터는 넣지 않음')
        parser.add_argument('--reset', action='store_true', help='이 명령이 넣은 설정과 샘플 데이터를 모두 삭제')

    def handle(self, *args, **opts):
        if opts['reset']:
            return self.reset()
        today = timezone.localdate()
        start = datetime.date.fromisoformat(opts['start']) if opts['start'] else today - datetime.timedelta(days=2)
        dates = [start + datetime.timedelta(days=i) for i in range(opts['days'])]
        hours = list(settings.OPENSRC_SLOT_HOURS)

        with transaction.atomic():
            sensors = []
            for number, location in SENSORS:
                s, _ = CampusSensor.objects.update_or_create(
                    number=number,
                    defaults={'ble_name': f'opensrc_team{number}', 'lab_sensor': f'opensrc_team{number}',
                              'location': location, 'active': True})
                sensors.append(s)
            for d in dates:
                CollectionDay.objects.get_or_create(date=d)
            created = 0
            for j, d in enumerate(dates):
                for i, h in enumerate(hours):
                    _, was_created = SlotAssignment.objects.get_or_create(
                        date=d, start_hour=h,
                        defaults={'team_no': rotation(j, i, settings.OPENSRC_TEAM_COUNT)})
                    created += was_created
        self.stdout.write(f'센서 {len(sensors)}대, 수집 날짜 {dates[0]}~{dates[-1]}, 배정 {created}칸 추가')

        if not opts['no_samples']:
            self.samples(sensors, dates, hours)
        self.stdout.write(self.style.SUCCESS('완료. 대시보드: /sensor/opensrc/check/'))

    # ------------------------------------------------------------------
    def samples(self, sensors, dates, hours):
        now = timezone.now()
        tz = timezone.get_current_timezone()
        n_lab = n_sub = 0

        # 실시간 상태: 센서 1~3은 방금 수신(ON), 4는 30분 전(OFF), 5는 기록 없음(OFF)
        for s, ago in ((sensors[0], 1), (sensors[1], 2), (sensors[2], 3), (sensors[3], 30)):
            n_lab += self.lab_row(s, now - datetime.timedelta(minutes=ago))

        # 지난 칸마다 시나리오를 돌려가며 넣는다
        k = 0
        for d in dates:
            for h in hours:
                start = datetime.datetime.combine(d, datetime.time(h), tzinfo=tz)
                end = start + datetime.timedelta(hours=1)
                if end > now:
                    continue
                slot = SlotAssignment.objects.get(date=d, start_hour=h)
                online = sensors[:4]  # 센서 5는 전원이 꺼져 있었다 → 요구 대상 아님
                for s in online:
                    n_lab += self.lab_row(s, start + datetime.timedelta(minutes=5))
                    n_lab += self.lab_row(s, start + datetime.timedelta(minutes=35))
                scenario = k % 5
                k += 1
                base = start + datetime.timedelta(minutes=10)
                if scenario == 0:    # 인정: 가동 센서 4대 모두 유효 데이터
                    for i, s in enumerate(online):
                        n_sub += self.upload(slot.team_no, s, base, i, rssi=-60 - i)
                elif scenario == 1:  # 누락: 센서 4 없음
                    for i, s in enumerate(online[:3]):
                        n_sub += self.upload(slot.team_no, s, base, i, rssi=-70)
                elif scenario == 2:  # 검토 필요: 위경도 전부 동일한 고정값
                    for i, s in enumerate(online):
                        n_sub += self.upload(slot.team_no, s, base, 0, rssi=-65)
                elif scenario == 3:  # 누락: rssi 없이 올림 → 유효 데이터 0건
                    for i, s in enumerate(online):
                        n_sub += self.upload(slot.team_no, s, base, i, rssi=None)
                else:                # 인정: 기기명 오타·대문자, MAC 미등록이어도 기기명으로 대응
                    for i, s in enumerate(online):
                        n_sub += self.upload(slot.team_no, s, base, i, rssi=-55,
                                             name=s.ble_name.upper().replace('OPENSRC', 'OPEMSRC' if i == 1 else 'OPENSRC'))
        self.stdout.write(f'샘플: livinglab 수신 {n_lab}건, 업로드 {n_sub}건')

    def lab_row(self, sensor, when):
        SensorData.objects.create(sensor=sensor.lab_sensor, mac=f'SEED:{sensor.number:02d}', receiver=SEED,
                                  mode='direct', temperature=21.5, co2=450, sensing_time=when.timestamp())
        IpDb.objects.create(sensor=sensor.lab_sensor, ip=f'10.0.0.{sensor.number}', time=int(when.timestamp()))
        return 2

    def upload(self, team_no, sensor, when, offset, rssi, name=None):
        sub = Submission.objects.create(
            source=Submission.SOURCE_UPLOAD, team=f'Team {team_no}', team_no=team_no,
            sensor=name or sensor.ble_name, mac=sensor.ble_mac or f'SEED:{sensor.number:02d}', sender=SEED,
            temp=22.0, humidity=50.0, aqi=1, tvoc=100, eco2=420, timestamp=int(when.timestamp()),
            lat=36.6269 + offset * 0.0003, lon=127.4577 + offset * 0.0003, rssi=rssi,
            status=Submission.STATUS_OK, detail='' if rssi is not None else 'rssi 없음')
        # received_at은 auto_now_add라 만든 뒤에 덮어쓴다
        Submission.objects.filter(pk=sub.pk).update(received_at=when + datetime.timedelta(seconds=offset))
        return 1

    def reset(self):
        a = SensorData.objects.filter(receiver=SEED).delete()[0]
        b = IpDb.objects.filter(ip__startswith='10.0.0.', sensor__startswith='opensrc_team').delete()[0]
        c = Submission.objects.filter(sender=SEED).delete()[0]
        d = SlotAssignment.objects.all().delete()[0]
        e = CollectionDay.objects.all().delete()[0]
        f = CampusSensor.objects.filter(ble_name__startswith='opensrc_team').delete()[0]
        self.stdout.write(f'삭제: livinglab 수신 {a + b}건, 업로드 {c}건, 배정 {d}칸, 날짜 {e}일, 센서 {f}대')

import datetime
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_team_no(value):
    if not 1 <= value <= settings.OPENSRC_TEAM_COUNT:
        raise ValidationError(f'팀 번호는 1~{settings.OPENSRC_TEAM_COUNT} 사이여야 합니다')


def validate_slot_hour(value):
    if value not in settings.OPENSRC_SLOT_HOURS:
        hours = list(settings.OPENSRC_SLOT_HOURS)
        raise ValidationError(f'시작 시각은 {hours[0]}~{hours[-1]}시 사이여야 합니다')


class Submission(models.Model):
    """학생 앱이 전송한 센서 데이터 (4주차 test/ 와 5주차 이후 upload/ 를 한 테이블에 모은다).

    - source='test'  : 4주차 연구실 센서 릴레이. raw HMAC 검증 결과가 status에 남는다.
    - source='upload': 5주차 이후 팀 key로 올리는 데이터. 팀이 직접 만든 센서라 검증은 하지 않고
                       물리적으로 불가능한 값만 표시한다. 7주차 중간평가 채점도 이 행들로 한다.
    검증에 실패한 요청도 사유와 함께 남긴다.
    """

    SOURCE_TEST = 'test'
    SOURCE_UPLOAD = 'upload'
    SOURCE_CHOICES = [
        (SOURCE_TEST, '4주차 (test/)'),
        (SOURCE_UPLOAD, '팀 업로드 (upload/)'),
    ]

    # 4주차 (raw 검증)
    STATUS_VERIFIED = 'verified'
    STATUS_MISMATCH = 'value_mismatch'
    STATUS_BAD_TAG = 'bad_tag'
    STATUS_BAD_RAW = 'bad_raw'
    STATUS_NO_RAW = 'no_raw'
    # 5주차 이후 (팀 업로드)
    STATUS_OK = 'ok'
    STATUS_OUT_OF_RANGE = 'out_of_range'
    STATUS_CHOICES = [
        (STATUS_VERIFIED, '검증 성공'),
        (STATUS_MISMATCH, '값 불일치'),
        (STATUS_BAD_TAG, '태그 불일치'),
        (STATUS_BAD_RAW, 'raw 형식 오류'),
        (STATUS_NO_RAW, 'raw 없음'),
        (STATUS_OK, '정상'),
        (STATUS_OUT_OF_RANGE, '범위 이상'),
    ]

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_UPLOAD, db_index=True)
    team = models.CharField(max_length=100, db_index=True)
    # key에서 뽑은 팀 번호. 4주차 데이터(팀명이 자유 입력)는 null.
    team_no = models.PositiveSmallIntegerField(null=True, blank=True)
    sensor = models.CharField(max_length=100)
    mac = models.CharField(max_length=32, blank=True)
    sender = models.CharField(max_length=100, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)

    # 학생이 파싱해서 보낸 값
    temp = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    aqi = models.IntegerField(null=True, blank=True)
    tvoc = models.IntegerField(null=True, blank=True)
    eco2 = models.IntegerField(null=True, blank=True)
    timestamp = models.BigIntegerField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    # 7주차부터: 폰이 측정한 센서 BLE RSSI (dBm). 중간평가 유효 데이터 판정에 쓴다.
    rssi = models.IntegerField(null=True, blank=True)

    # 4주차 전용: BLE 패킷 원문과 서버가 직접 디코드한 값
    raw = models.CharField(max_length=128, blank=True)
    decoded = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'opensrc_submission'
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['team', 'received_at']),
            models.Index(fields=['team_no', 'received_at']),
            models.Index(fields=['source', 'received_at']),
        ]

    @property
    def verified(self):
        return self.status == self.STATUS_VERIFIED

    def __str__(self):
        return f'{self.team} / {self.sensor} ({self.status})'


# ---------------------------------------------------------------------------
# 7주차 데이터 수집 실습 · 8주차 중간평가
# ---------------------------------------------------------------------------

def normalize_mac(value):
    """'AA:BB:cc-dd ee ff' → 'aabbccddeeff'. 비교 전용."""
    return re.sub(r'[^0-9a-f]', '', str(value or '').lower())


def normalize_name(value):
    """'Opensrc_Team 1' → 'opensrcteam1'. 비교 전용."""
    return re.sub(r'[^0-9a-z]', '', str(value or '').lower())


class CampusSensor(models.Model):
    """캠퍼스에 설치한 중간평가용 센서 (opensrc_team1~5).

    학생 앱이 올린 데이터는 BLE MAC(등록된 경우) → BLE 기기명 순으로 이 센서에 대응시킨다.
    가동 여부는 센서가 WiFi로 livinglab 테이블(sensor_sensor_data, sensor_ip_db)에 올린
    수신 기록을 lab_sensor 이름으로 찾아 판단한다.
    """

    number = models.PositiveSmallIntegerField('번호', unique=True)
    ble_name = models.CharField('BLE 기기명', max_length=100, help_text='광고 패킷의 기기명. 예: opensrc_team1')
    ble_mac = models.CharField('BLE MAC', max_length=32, blank=True,
                               help_text='폰에서 보이는 광고 주소. 모르면 비워두면 기기명으로만 대응시킨다')
    lab_sensor = models.CharField('livinglab 센서 이름', max_length=100,
                                  help_text='sensor_sensor_data / sensor_ip_db 의 sensor 값. 예: opensrc_team1')
    location = models.CharField('설치 위치', max_length=200, blank=True)
    active = models.BooleanField('사용', default=True, help_text='끄면 대시보드·채점에서 제외')

    class Meta:
        db_table = 'opensrc_campus_sensor'
        ordering = ['number']
        verbose_name = '캠퍼스 센서'
        verbose_name_plural = '캠퍼스 센서'

    def __str__(self):
        return f'센서 {self.number} ({self.ble_name})'

    def matches(self, mac, name):
        """학생이 보낸 (mac, sensor) 가 이 센서인지."""
        if self.ble_mac and normalize_mac(mac) == normalize_mac(self.ble_mac):
            return True
        return normalize_name(name) == normalize_name(self.ble_name)


class CollectionDay(models.Model):
    """데이터 수집 기간 (하루에 한 행). 대시보드 그리드의 열이 된다."""

    date = models.DateField('날짜', unique=True)

    class Meta:
        db_table = 'opensrc_collection_day'
        ordering = ['date']
        verbose_name = '수집 날짜'
        verbose_name_plural = '수집 날짜'

    def __str__(self):
        return self.date.strftime('%Y-%m-%d (%a)')


class SlotAssignment(models.Model):
    """시간대 배정표: 날짜 × 시작 시각 한 칸을 팀 하나가 담당한다."""

    date = models.DateField('날짜')
    start_hour = models.PositiveSmallIntegerField('시작 시각', validators=[validate_slot_hour],
                                                  help_text='9 = 09:00~10:00, …, 17 = 17:00~18:00')
    team_no = models.PositiveSmallIntegerField('팀', validators=[validate_team_no])

    class Meta:
        db_table = 'opensrc_slot_assignment'
        ordering = ['date', 'start_hour']
        unique_together = [('date', 'start_hour')]
        verbose_name = '시간대 배정'
        verbose_name_plural = '시간대 배정'

    def __str__(self):
        return f'{self.date} {self.start_hour:02d}:00 → {self.team_no}팀'

    @property
    def label(self):
        return f'{self.start_hour:02d}–{self.start_hour + 1:02d}'

    def start(self, tz):
        return datetime.datetime.combine(self.date, datetime.time(self.start_hour), tzinfo=tz)

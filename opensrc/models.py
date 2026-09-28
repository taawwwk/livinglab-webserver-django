from django.db import models


class Submission(models.Model):
    """학생 앱이 전송한 센서 데이터. 검증에 실패한 요청도 사유와 함께 남긴다."""

    STATUS_VERIFIED = 'verified'
    STATUS_MISMATCH = 'value_mismatch'
    STATUS_BAD_TAG = 'bad_tag'
    STATUS_BAD_RAW = 'bad_raw'
    STATUS_NO_RAW = 'no_raw'
    STATUS_CHOICES = [
        (STATUS_VERIFIED, '검증 성공'),
        (STATUS_MISMATCH, '값 불일치'),
        (STATUS_BAD_TAG, '태그 불일치'),
        (STATUS_BAD_RAW, 'raw 형식 오류'),
        (STATUS_NO_RAW, 'raw 없음'),
    ]

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    team = models.CharField(max_length=100, db_index=True)
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

    raw = models.CharField(max_length=128, blank=True)
    # raw를 서버가 직접 디코드한 값 (태그 검증 통과 시 신뢰 가능한 기준값)
    decoded = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'opensrc_submission'
        ordering = ['-received_at']
        indexes = [models.Index(fields=['team', 'received_at'])]

    @property
    def verified(self):
        return self.status == self.STATUS_VERIFIED

    def __str__(self):
        return f'{self.team} / {self.sensor} ({self.status})'


class TeamSubmission(models.Model):
    """5주차 실습: 팀이 직접 만든 센서의 데이터.

    센서가 팀 소유라 HMAC 키를 넣어봐야 학생이 키를 갖게 되므로 검증하지 않는다.
    대신 팀별 key로 팀을 식별하고, 물리적으로 불가능한 값만 표시해 둔다.
    """

    STATUS_OK = 'ok'
    STATUS_OUT_OF_RANGE = 'out_of_range'
    STATUS_CHOICES = [
        (STATUS_OK, '정상'),
        (STATUS_OUT_OF_RANGE, '범위 이상'),
    ]

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    team = models.CharField(max_length=20, db_index=True)
    sensor = models.CharField(max_length=100)
    mac = models.CharField(max_length=32)
    sender = models.CharField(max_length=100)
    client_ip = models.GenericIPAddressField(null=True, blank=True)

    temp = models.FloatField()
    humidity = models.FloatField()
    aqi = models.IntegerField()
    tvoc = models.IntegerField()
    eco2 = models.IntegerField()
    timestamp = models.BigIntegerField()
    lat = models.FloatField()
    lon = models.FloatField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'opensrc_team_submission'
        ordering = ['-received_at']
        indexes = [models.Index(fields=['team', 'received_at'])]

    def __str__(self):
        return f'{self.team} / {self.sensor} ({self.status})'

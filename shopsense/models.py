from django.db import models


class ShopSite(models.Model):
    """수위센서 설치 장소 (가게 1곳 = 1개 site)."""

    name = models.CharField(max_length=100)  # 예: "대학가 가게 1호"
    installed_at = models.DateTimeField(null=True, blank=True)
    # 센서에서 평상시 바닥까지의 거리. 현장에서 줄자로 재서 입력한다.
    baseline_cm = models.FloatField()
    # 수위(= baseline_cm - 측정거리) 임계값. 비워두면 해당 단계 판정을 하지 않는다.
    warn_level_cm = models.FloatField(null=True, blank=True)
    danger_level_cm = models.FloatField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = 'shopsense_site'
        verbose_name = '설치 장소'
        verbose_name_plural = '설치 장소'

    def __str__(self):
        return self.name


class WaterLevelReading(models.Model):
    """초음파 수위센서(JSN-SR04T) 측정값.

    수위(level_cm)는 저장하지 않는다. baseline_cm이 나중에 보정될 수 있어서
    조회할 때마다 baseline_cm - distance_cm으로 계산한다 (shopsense.levels 참고).
    """

    # site_id 단독 인덱스는 아래 (site, ...) 복합 인덱스들이 대신하므로 만들지 않는다
    site = models.ForeignKey(ShopSite, on_delete=models.PROTECT, related_name='readings', db_index=False)
    measured_at = models.DateTimeField()               # Pi가 측정한 시각 (NTP 기준)
    received_at = models.DateTimeField(auto_now_add=True)  # 서버 수신 시각
    # 센서-수면 거리. 측정 실패는 버리지 않고 null로 남긴다 (실패 구간 분석용).
    distance_cm = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'shopsense_reading'
        verbose_name = '수위 측정값'
        verbose_name_plural = '수위 측정값'
        constraints = [
            # 같은 측정값이 재전송돼도 한 번만 저장 (idempotent).
            # Postgres가 이 제약용으로 (site_id, measured_at) 인덱스를 만들므로 기간 조회도 이 인덱스를 쓴다.
            models.UniqueConstraint(fields=['site', 'measured_at'], name='shopsense_reading_site_measured_uniq'),
        ]
        indexes = [
            # "마지막 수신 시각"(stale 판정) 조회용
            models.Index(fields=['site', 'received_at'], name='shopsense_rd_site_received_idx'),
        ]

    def __str__(self):
        return f'{self.site_id} @ {self.measured_at}: {self.distance_cm}'

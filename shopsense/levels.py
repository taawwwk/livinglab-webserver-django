"""수위 계산과 상태 판정. API, 알람, management command가 같은 기준을 쓰도록 한 곳에 둔다."""
import datetime

from django.db.models import Max
from django.utils import timezone

STATUS_NORMAL = 'normal'
STATUS_WARN = 'warn'
STATUS_DANGER = 'danger'
STATUS_NO_DATA = 'no_data'

# 마지막 수신 후 이 시간이 지나면 latest API에서 stale: true
STALE_AFTER = datetime.timedelta(minutes=5)


def level_cm(site, distance_cm):
    """수위 = baseline - 측정거리. 측정 실패(null)면 None."""
    if distance_cm is None:
        return None
    return site.baseline_cm - distance_cm


def level_status(site, level):
    """수위 → normal / warn / danger. 수위를 모르면 no_data. 임계값이 비어 있으면 그 단계는 건너뛴다."""
    if level is None:
        return STATUS_NO_DATA
    if site.danger_level_cm is not None and level >= site.danger_level_cm:
        return STATUS_DANGER
    if site.warn_level_cm is not None and level >= site.warn_level_cm:
        return STATUS_WARN
    return STATUS_NORMAL


def last_received_at(site):
    return site.readings.aggregate(last=Max('received_at'))['last']


def is_stale(last_received, now=None, after=STALE_AFTER):
    if last_received is None:
        return True
    return (now or timezone.now()) - last_received >= after

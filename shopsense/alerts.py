"""수위 알람. 지금은 로그만 남긴다.

실제 발송(카카오톡 알림톡/문자/푸시)을 붙일 때는 _notify()만 구현하면 된다.
그때 고려할 것:
- 10초마다 측정값이 들어오므로 같은 상태가 이어지는 동안 반복 발송하지 않도록
  사이트별 마지막 알림 상태·시각을 저장해 쿨다운을 둘 것
- 센서 위로 물이 차서 블라인드 존(JSN-SR04T 약 20~25cm)에 들어가면 측정 실패(null)가
  이어질 수 있다. danger 직후의 연속 실패는 별도 경보로 취급하는 것을 검토할 것
"""
import logging

from . import levels

logger = logging.getLogger('shopsense')


def check_and_notify(reading):
    """측정값 1건의 상태를 판정하고, 위험하면 알린다. 판정한 상태를 반환한다."""
    site = reading.site
    level = levels.level_cm(site, reading.distance_cm)
    status = levels.level_status(site, level)

    if status == levels.STATUS_DANGER:
        logger.warning(
            'shopsense DANGER: site=%s(%s) level=%.1fcm >= danger=%.1fcm measured_at=%s',
            site.pk, site.name, level, site.danger_level_cm, reading.measured_at.isoformat(),
        )
        _notify(site, reading, status, level)
    elif status == levels.STATUS_WARN:
        logger.info(
            'shopsense warn: site=%s(%s) level=%.1fcm >= warn=%.1fcm measured_at=%s',
            site.pk, site.name, level, site.warn_level_cm, reading.measured_at.isoformat(),
        )
    return status


def _notify(site, reading, status, level):
    """TODO: 카카오톡/문자/푸시 발송. 이번 범위에서는 구현하지 않는다."""

"""7주차 데이터 수집 실습 · 8주차 중간평가 채점 로직.

칸(슬롯) = 수집 날짜 × 1시간 시간대. 칸마다 담당 팀이 하나 배정된다 (SlotAssignment).

칸 인정 기준
  1. 그 1시간 안에 livinglab 테이블(sensor_sensor_data, sensor_ip_db)에 수신 기록이 1건이라도 있는
     캠퍼스 센서를 "가동" 센서로 본다. 가동하지 않은 센서는 요구 대상에서 빠진다 (감점 없음).
  2. 담당 팀이 같은 1시간 안에 가동 센서마다 유효 데이터를 1건 이상 올렸으면 인정.
     유효 데이터: rssi가 null·0이 아니고 -100~0, 위도·경도가 null·0이 아님.
  3. 칸 안의 유효 데이터 위경도가 전부 같은 값이면 자동 불인정하지 않고 "검토 필요"로 표시한다.
     가동 센서가 0대인 칸도 요구 대상이 없어 자동 인정되는 대신 "검토 필요"로 표시한다.
점수 = 만점 − 누락 칸 × 감점 (최저 0). 검토 필요 칸은 점수에서는 인정으로 센다.

모든 시각은 Asia/Seoul(settings.TIME_ZONE) 기준이다.
"""
import datetime

from django.conf import settings
from django.utils import timezone

from sensor.models import IpDb, SensorData

from .models import CampusSensor, CollectionDay, SlotAssignment, Submission, normalize_mac, normalize_name

STATUS_OK = 'ok'                  # 인정
STATUS_MISSING = 'missing'        # 미수집 (누락)
STATUS_REVIEW = 'review'          # 검토 필요
STATUS_PROGRESS = 'progress'      # 진행 중인 칸
STATUS_PENDING = 'pending'        # 아직 안 지난 칸
STATUS_UNASSIGNED = 'unassigned'  # 담당 팀 없음

STATUS_LABELS = {
    STATUS_OK: '인정',
    STATUS_MISSING: '누락',
    STATUS_REVIEW: '검토 필요',
    STATUS_PROGRESS: '진행 중',
    STATUS_PENDING: '예정',
    STATUS_UNASSIGNED: '미배정',
}

RSSI_MIN, RSSI_MAX = -100, 0


def tz():
    return timezone.get_current_timezone()


def slot_hours():
    return list(settings.OPENSRC_SLOT_HOURS)


def slot_label(hour):
    return f'{hour:02d}–{hour + 1:02d}'


def collection_dates():
    """admin에 입력한 수집 날짜. 없으면 배정표에 있는 날짜로 대신한다."""
    dates = list(CollectionDay.objects.values_list('date', flat=True))
    if not dates:
        dates = sorted(set(SlotAssignment.objects.values_list('date', flat=True)))
    return dates


def slot_bounds(date, hour):
    start = datetime.datetime.combine(date, datetime.time(hour), tzinfo=tz())
    return start, start + datetime.timedelta(hours=1)


def active_sensors():
    return list(CampusSensor.objects.filter(active=True))


def fmt(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M:%S') if dt else None


# ---------------------------------------------------------------------------
# livinglab 수신 (센서 가동 여부)
# ---------------------------------------------------------------------------

def _lab_names(sensors):
    return [s.lab_sensor for s in sensors]


def sensors_online_between(sensors, start, end):
    """[start, end) 안에 livinglab 수신이 1건이라도 있는 센서 집합."""
    names = _lab_names(sensors)
    if not names:
        return set()
    seen = set(SensorData.objects
               .filter(sensor__in=names, sensing_time__gte=start.timestamp(), sensing_time__lt=end.timestamp())
               .values_list('sensor', flat=True).distinct())
    seen |= set(IpDb.objects
                .filter(sensor__in=names, time__gte=int(start.timestamp()), time__lt=int(end.timestamp()))
                .values_list('sensor', flat=True).distinct())
    return {s for s in sensors if s.lab_sensor in seen}


def _from_epoch(epoch):
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc) if epoch is not None else None


def last_receptions(sensor):
    """센서의 마지막 livinglab 수신 시각 (측정 데이터, IP 기록) — 각각 aware datetime 또는 None.

    측정 데이터는 sensor 를 = 대신 범위로 건다 (sensor/views.latest_direct_mac 과 같은 이유:
    측정이 오래 멈춘 센서에서 플래너가 전체 sensing_time 인덱스를 거꾸로 훑지 않게).
    """
    last_data = (SensorData.objects
                 .filter(sensor__gte=sensor.lab_sensor, sensor__lte=sensor.lab_sensor)
                 .order_by('-sensor', '-sensing_time').values_list('sensing_time', flat=True).first())
    last_ip = (IpDb.objects.filter(sensor=sensor.lab_sensor)
               .order_by('-time').values_list('time', flat=True).first())
    return _from_epoch(last_data), _from_epoch(float(last_ip) if last_ip is not None else None)


def sensor_status(sensors, now):
    """실시간 ON/OFF.

    측정 데이터가 최근 OPENSRC_SENSOR_ONLINE_MINUTES(10분) 안에 있거나, IP 기록이 최근
    OPENSRC_SENSOR_IP_ONLINE_MINUTES(70분) 안에 있으면 ON. 측정 프로그램이 멈추고 IP만
    60분마다 보내는 센서(캠퍼스 센서 3·4 = sensor 31·32)도 켜져 있으면 ON 으로 보이게 하려는 것.
    """
    data_threshold = now - datetime.timedelta(minutes=settings.OPENSRC_SENSOR_ONLINE_MINUTES)
    ip_threshold = now - datetime.timedelta(minutes=settings.OPENSRC_SENSOR_IP_ONLINE_MINUTES)
    rows = []
    for s in sensors:
        last_data, last_ip = last_receptions(s)
        candidates = [(t, src) for t, src in ((last_data, 'data'), (last_ip, 'ip')) if t is not None]
        last, source = max(candidates) if candidates else (None, None)
        rows.append({
            'number': s.number,
            'name': s.ble_name,
            'mac': s.ble_mac,
            'lab_sensor': s.lab_sensor,
            'location': s.location,
            'online': bool((last_data and last_data >= data_threshold) or (last_ip and last_ip >= ip_threshold)),
            'last_seen': fmt(last),
            'last_source': source,
            'last_data': fmt(last_data),
            'last_ip': fmt(last_ip),
        })
    return rows


# ---------------------------------------------------------------------------
# 학생 업로드 (유효 데이터, 센서 대응)
# ---------------------------------------------------------------------------

def is_valid_row(row):
    rssi, lat, lon = row.get('rssi'), row.get('lat'), row.get('lon')
    return (rssi is not None and RSSI_MIN <= rssi <= RSSI_MAX and rssi != 0
            and lat not in (None, 0) and lon not in (None, 0))


def team_rows_between(team_no, start, end):
    """담당 팀이 [start, end) 안에 올린 행 (서버 수신 시각 기준). 유효/무효 모두."""
    return list(Submission.objects
                .filter(source=Submission.SOURCE_UPLOAD, team_no=team_no,
                        received_at__gte=start, received_at__lt=end)
                .values('mac', 'sensor', 'lat', 'lon', 'rssi'))


def match_sensor(sensors, mac, name):
    """학생이 보낸 (mac, sensor) → CampusSensor. 등록된 BLE MAC 또는 BLE 기기명이 일치하면 그 센서.

    sensor 는 학생이 BLE 패킷에서 읽은 device name 이라 기기명은 대소문자·공백·기호만 무시하고 정확히 비교한다.
    (5주차 자기 팀 센서 'team3 sensor' 같은 이름이 캠퍼스 센서 3으로 잡히지 않도록 번호만으로는 맞추지 않는다.)
    iOS 는 MAC 대신 UUID 를 주므로 MAC 이 등록돼 있어도 기기명 일치는 계속 인정한다.
    """
    nmac = normalize_mac(mac)
    if nmac:
        for s in sensors:
            if s.ble_mac and nmac == normalize_mac(s.ble_mac):
                return s
    nname = normalize_name(name)
    for s in sensors:
        if nname and nname == normalize_name(s.ble_name):
            return s
    return None


# ---------------------------------------------------------------------------
# 칸 판정 · 점수
# ---------------------------------------------------------------------------

def evaluate_slot(date, hour, assignment, sensors, now):
    start, end = slot_bounds(date, hour)
    result = {
        'date': date.isoformat(),
        'hour': hour,
        'label': slot_label(hour),
        'team_no': assignment.team_no if assignment else None,
        'status': STATUS_UNASSIGNED,
        'online': [],      # 가동 센서 번호
        'collected': [],   # 유효 데이터가 있는 가동 센서 번호
        'missing': [],     # 가동인데 유효 데이터가 없는 센서 번호
        'extra': [],       # 유효 데이터는 있지만 그 시간엔 가동 기록이 없는 센서 번호
        'rows': 0,         # 담당 팀이 올린 전체 행 수
        'valid_rows': 0,   # 그중 유효 행 수
        'unmatched_rows': 0,
        'fixed_location': False,
        'notes': [],
    }
    if assignment is None:
        return result
    if now < start:
        result['status'] = STATUS_PENDING
        return result

    online = sensors_online_between(sensors, start, end)
    rows = team_rows_between(assignment.team_no, start, end)
    valid = [r for r in rows if is_valid_row(r)]

    collected, unmatched = set(), 0
    for r in valid:
        s = match_sensor(sensors, r['mac'], r['sensor'])
        if s is None:
            unmatched += 1
        else:
            collected.add(s)

    missing = online - collected
    fixed = len(valid) >= 2 and len({(r['lat'], r['lon']) for r in valid}) == 1

    result.update({
        'online': sorted(s.number for s in online),
        'collected': sorted(s.number for s in online & collected),
        'missing': sorted(s.number for s in missing),
        'extra': sorted(s.number for s in collected - online),
        'rows': len(rows),
        'valid_rows': len(valid),
        'unmatched_rows': unmatched,
        'fixed_location': fixed,
    })
    if unmatched:
        result['notes'].append(f'센서를 알 수 없는 유효 데이터 {unmatched}건 (mac/기기명 불일치)')
    if len(rows) > len(valid):
        result['notes'].append(f'무효 데이터 {len(rows) - len(valid)}건 (rssi 또는 위경도가 null·0·범위 밖)')
    if fixed:
        result['notes'].append('유효 데이터의 위경도가 전부 동일한 값')
    if not online:
        result['notes'].append('이 시간에 가동 기록이 있는 센서가 없음')

    if now < end:
        result['status'] = STATUS_PROGRESS
    elif missing:
        result['status'] = STATUS_MISSING
    elif not online or fixed:
        result['status'] = STATUS_REVIEW
    else:
        result['status'] = STATUS_OK
    return result


def score(missing_count):
    return max(0, settings.OPENSRC_MIDTERM_FULL_SCORE - settings.OPENSRC_MIDTERM_PENALTY * missing_count)


def team_summary(slots):
    teams = []
    for team_no in range(1, settings.OPENSRC_TEAM_COUNT + 1):
        mine = [s for s in slots if s['team_no'] == team_no]
        counts = {status: sum(1 for s in mine if s['status'] == status) for status in STATUS_LABELS}
        teams.append({
            'team_no': team_no,
            'slots': len(mine),
            'ok': counts[STATUS_OK],
            'review': counts[STATUS_REVIEW],
            'missing': counts[STATUS_MISSING],
            'remaining': counts[STATUS_PROGRESS] + counts[STATUS_PENDING],
            'score': score(counts[STATUS_MISSING]),
            'final': counts[STATUS_PROGRESS] + counts[STATUS_PENDING] == 0,
        })
    return teams


def evaluate(now=None):
    """대시보드·채점 CSV가 함께 쓰는 전체 평가 결과 (JSON 직렬화 가능한 dict)."""
    now = now or timezone.now()
    sensors = active_sensors()
    dates = collection_dates()
    hours = slot_hours()
    assignments = {(a.date, a.start_hour): a for a in SlotAssignment.objects.all()}
    slots = [evaluate_slot(d, h, assignments.get((d, h)), sensors, now) for d in dates for h in hours]
    return {
        'now': fmt(now),
        'timezone': str(tz()),
        'online_minutes': settings.OPENSRC_SENSOR_ONLINE_MINUTES,
        'ip_online_minutes': settings.OPENSRC_SENSOR_IP_ONLINE_MINUTES,
        'full_score': settings.OPENSRC_MIDTERM_FULL_SCORE,
        'penalty': settings.OPENSRC_MIDTERM_PENALTY,
        'dates': [d.isoformat() for d in dates],
        'hours': hours,
        'labels': {h: slot_label(h) for h in hours},
        'status_labels': STATUS_LABELS,
        'sensors': sensor_status(sensors, now),
        'slots': slots,
        'teams': team_summary(slots),
    }

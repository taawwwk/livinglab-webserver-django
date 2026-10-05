"""5주차 실습: 팀이 직접 만든 센서 데이터 업로드 API와 조회 화면.

6주차 데이터 분석 실습에서는 아래 data() 뷰로 자기 팀 데이터를 내려받는다.
"""
import datetime
import logging
import re
import time

from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .common import client_ip, csv_response, fail, get, load_body, ok, to_number
from .models import TeamSubmission

logger = logging.getLogger('opensrc')

# 물리적으로 불가능한 값 표시용. 거절하지는 않는다 — 팀이 직접 만든 센서라
# 초기 이상값도 실습 데이터의 일부다.
RANGES = [
    ('temp', 'temp', -40, 85),
    ('humidity', 'humidity', 0, 100),
    # 팀마다 AQI 정의가 다를 수 있어 (1~5 지수, 0~500 IAQ 등) 넓게 잡는다
    ('AQI', 'aqi', 0, 500),
    ('TVOC', 'tvoc', 0, 60000),
    ('eCO2', 'eco2', 400, 60000),
    ('lat', 'lat', -90, 90),
    ('lon', 'lon', -180, 180),
]
# 2020-01-01 이후 ~ 하루 뒤까지. 학생 Pi에 RTC가 없어 시계가 틀어지는 경우를 잡는다.
TS_MIN = 1577836800
TS_FUTURE_MARGIN = 86400

REQUIRED = [
    ('sensor', str), ('mac', str), ('sender', str),
    ('temp', float), ('humidity', float), ('AQI', int), ('TVOC', int), ('eCO2', int),
    ('timestamp', int), ('lat', float), ('lon', float),
]


def team_keys():
    """{'Team 1': 'opensrc-team 1', ...}"""
    return {f'Team {n}': f'opensrc-team {n}' for n in range(1, settings.OPENSRC_TEAM_COUNT + 1)}


def _normalize(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def team_for_key(key):
    """공백과 대소문자 차이는 무시하고 팀을 찾는다."""
    given = _normalize(key)
    for team, valid in team_keys().items():
        if given == _normalize(valid):
            return team
    return None


@csrf_exempt
@require_POST
def upload(request):
    body = load_body(request)
    if body is None:
        return fail('body를 JSON으로 파싱할 수 없습니다')

    team = team_for_key(get(body, 'key'))
    if team is None:
        return fail('key가 올바르지 않습니다 (팀별로 발급된 key를 사용하세요)')

    # team을 함께 보냈다면 key가 가리키는 팀과 같아야 한다 (다른 팀 key를 쓰면 바로 알 수 있게)
    given_team = get(body, 'team')
    if given_team and _normalize(given_team) != _normalize(team):
        return fail(f'key는 {team}의 것인데 team은 "{given_team}"입니다')

    values, missing = {}, []
    for field, cast in REQUIRED:
        raw = get(body, field)
        if cast is str:
            value = str(raw).strip() if raw is not None else ''
        else:
            value = to_number(raw, cast)
        if value is None or value == '':
            missing.append(field)
        else:
            values[field] = value
    if missing:
        return fail('필수 값이 없거나 형식이 잘못되었습니다: ' + ', '.join(missing))

    sub = TeamSubmission(
        team=team,
        sensor=values['sensor'][:100],
        mac=values['mac'][:32],
        sender=values['sender'][:100],
        client_ip=client_ip(request),
        temp=values['temp'], humidity=values['humidity'], aqi=values['AQI'],
        tvoc=values['TVOC'], eco2=values['eCO2'], timestamp=values['timestamp'],
        lat=values['lat'], lon=values['lon'],
    )

    out_of_range = [key for key, field, low, high in RANGES if not low <= getattr(sub, field) <= high]
    if not TS_MIN <= sub.timestamp <= time.time() + TS_FUTURE_MARGIN:
        out_of_range.append('timestamp')
    if out_of_range:
        sub.status = TeamSubmission.STATUS_OUT_OF_RANGE
        sub.detail = '범위를 벗어난 값: ' + ', '.join(out_of_range)
    else:
        sub.status = TeamSubmission.STATUS_OK
    sub.save()

    if sub.status == TeamSubmission.STATUS_OUT_OF_RANGE:
        logger.info(f'opensrc team upload out of range: team={team} detail={sub.detail}')
    return ok({
        'result': 'Success',
        'message': f'Data received from {team} successfully!',
        'received_data': {'team': team, 'sensor': sub.sensor},
        'status': sub.status,
        'detail': sub.detail,
    })


def _serialize(s):
    return {
        'received_at': timezone.localtime(s.received_at).strftime('%Y-%m-%d %H:%M:%S'),
        'team': s.team,
        'sensor': s.sensor,
        'mac': s.mac,
        'temp': s.temp,
        'humidity': s.humidity,
        'AQI': s.aqi,
        'TVOC': s.tvoc,
        'eCO2': s.eco2,
        'timestamp': s.timestamp,
        'lat': s.lat,
        'lon': s.lon,
        'sender': s.sender,
        'status': s.status,
        'detail': s.detail,
    }


def _filtered(request):
    qs = TeamSubmission.objects.all()
    team = request.GET.get('team')
    if team:
        qs = qs.filter(team=team)
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return qs


@require_GET
def page(request):
    return render(request, 'opensrc/teams.html')


@require_GET
def latest(request):
    try:
        limit = min(max(int(request.GET.get('limit', 100)), 1), 1000)
    except ValueError:
        limit = 100
    return JsonResponse({'rows': [_serialize(s) for s in _filtered(request)[:limit]]})


@require_GET
def summary(request):
    rows = {
        r['team']: r for r in TeamSubmission.objects.values('team').annotate(
            total=Count('id'),
            normal=Count('id', filter=Q(status=TeamSubmission.STATUS_OK)),
            sensors=Count('mac', distinct=True),
            last=Max('received_at'),
        )
    }
    # 아직 전송이 없는 팀도 0건으로 보여준다
    teams = []
    for team in team_keys():
        r = rows.get(team)
        teams.append({
            'team': team,
            'total': r['total'] if r else 0,
            'normal': r['normal'] if r else 0,
            'sensors': r['sensors'] if r else 0,
            'last': timezone.localtime(r['last']).strftime('%Y-%m-%d %H:%M:%S') if r else None,
        })
    return JsonResponse({'teams': teams})


@require_GET
def export_csv(request):
    header = ['received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'AQI', 'TVOC',
              'eCO2', 'timestamp', 'lat', 'lon', 'sender', 'status', 'detail']
    filename = f"opensrc_teams_{request.GET.get('team') or 'all'}.csv".replace(' ', '_')
    return csv_response(header, _filtered(request).order_by('received_at'), _serialize, filename)


# ---------------------------------------------------------------------------
# 6주차 데이터 분석 실습용 조회 API
# ---------------------------------------------------------------------------

# values()로 가져올 DB 컬럼. 수만 행을 다루므로 필요한 것만 꺼낸다.
DATA_COLUMNS = ['received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'aqi', 'tvoc',
                'eco2', 'timestamp', 'lat', 'lon', 'sender', 'status']
DATA_HEADER = ['received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'AQI', 'TVOC',
               'eCO2', 'timestamp', 'lat', 'lon', 'sender', 'status']
DATE_FORMATS = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']


def _data_row(v):
    """values() 딕셔너리 → 응답 한 행. 업로드된 원본값을 그대로 내보낸다."""
    return {
        'received_at': timezone.localtime(v['received_at']).strftime('%Y-%m-%d %H:%M:%S'),
        'team': v['team'],
        'sensor': v['sensor'],
        'mac': v['mac'],
        'temp': v['temp'],
        'humidity': v['humidity'],
        'AQI': v['aqi'],
        'TVOC': v['tvoc'],
        'eCO2': v['eco2'],
        'timestamp': v['timestamp'],
        'lat': v['lat'],
        'lon': v['lon'],
        'sender': v['sender'],
        'status': v['status'],
    }


def _parse_bound(value, is_end):
    """KST 문자열 → aware datetime. 날짜만 주면 end는 그날 끝까지 포함한다."""
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if is_end and fmt == '%Y-%m-%d':
            parsed += datetime.timedelta(days=1)  # 그날 23:59:59까지 포함
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return None


@require_GET
def data(request):
    """팀 키로 자기 팀 데이터를 조회한다 (6주차 pandas 실습용)."""
    team = team_for_key(request.GET.get('key'))
    if team is None:
        return fail('key가 올바르지 않습니다 (팀별로 발급된 key를 사용하세요)')

    qs = TeamSubmission.objects.all()
    scope = request.GET.get('team')
    if not scope:
        qs = qs.filter(team=team)
    elif _normalize(scope) == 'all':
        team = 'all'  # 7주차 팀 간 비교용
    elif _normalize(scope) == _normalize(team):
        qs = qs.filter(team=team)
    else:
        return fail(f'team은 생략하거나 "all" 또는 "{team}"이어야 합니다')

    for param, is_end in (('start', False), ('end', True)):
        value = request.GET.get(param)
        if not value:
            continue
        bound = _parse_bound(value, is_end)
        if bound is None:
            return fail(f'{param} 형식이 올바르지 않습니다: "{value}" '
                        '(예: 2026-10-01 또는 "2026-10-01 13:00")')
        qs = qs.filter(**{f'received_at__{"lt" if is_end else "gte"}': bound})

    qs = qs.order_by('received_at').values(*DATA_COLUMNS)

    if (request.GET.get('format') or 'json').lower() == 'csv':
        filename = f'opensrc_{team}.csv'.replace(' ', '_')
        return csv_response(DATA_HEADER, qs, _data_row, filename)

    rows = [_data_row(v) for v in qs.iterator(chunk_size=2000)]
    return ok({'team': team, 'count': len(rows), 'data': rows})

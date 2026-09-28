import logging

from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import otp
from .common import client_ip, csv_response, fail, get, load_body, ok, to_number
from .models import Submission

logger = logging.getLogger('opensrc')

# 학생이 보낸 값과 raw 디코드 값을 비교할 필드: (요청 키, 모델 필드, 허용 오차)
COMPARED_FIELDS = [
    ('temp', 'temp', 0.011),
    ('humidity', 'humidity', 0.011),
    ('AQI', 'aqi', 0),
    ('TVOC', 'tvoc', 0),
    ('eCO2', 'eco2', 0),
    ('timestamp', 'timestamp', 0),
]


@csrf_exempt
@require_POST
def submit(request):
    body = load_body(request)
    if body is None:
        return fail('body를 JSON으로 파싱할 수 없습니다')
    if get(body, 'key') != settings.OPENSRC_API_KEY:
        return fail('key가 올바르지 않습니다')

    team = str(get(body, 'team') or '').strip()
    sensor = str(get(body, 'sensor') or '').strip()
    if not team or not sensor:
        return fail('team, sensor는 필수입니다')

    # 폰 쪽 정보. 실내에서 GPS가 안 잡히면 lat/lon에 0을 보내도록 안내한다.
    sender = str(get(body, 'sender') or '').strip()
    lat = to_number(get(body, 'lat'), float)
    lon = to_number(get(body, 'lon'), float)
    missing = [k for k, v in (('sender', sender), ('lat', lat), ('lon', lon)) if v in (None, '')]
    if missing:
        return fail('필수 값이 없거나 형식이 잘못되었습니다: ' + ', '.join(missing))

    sub = Submission(
        team=team[:100],
        sensor=sensor[:100],
        mac=str(get(body, 'mac') or '').strip()[:32],
        sender=sender[:100],
        client_ip=client_ip(request),
        temp=to_number(get(body, 'temp'), float),
        humidity=to_number(get(body, 'humidity'), float),
        aqi=to_number(get(body, 'AQI'), int),
        tvoc=to_number(get(body, 'TVOC'), int),
        eco2=to_number(get(body, 'eCO2'), int),
        timestamp=to_number(get(body, 'timestamp'), int),
        lat=lat,
        lon=lon,
        raw=str(get(body, 'raw') or '').strip()[:128],
    )

    if not sub.raw:
        sub.status, sub.detail = Submission.STATUS_NO_RAW, 'raw 필드가 없습니다'
    else:
        try:
            tag_ok, decoded = otp.verify(sub.raw, sub.mac, settings.OPENSRC_HMAC_KEY, settings.OPENSRC_TAG_LEN)
        except otp.RawError as e:
            sub.status, sub.detail = Submission.STATUS_BAD_RAW, str(e)
        else:
            sub.decoded = decoded
            if not tag_ok:
                sub.status = Submission.STATUS_BAD_TAG
                sub.detail = '태그 검증 실패 (raw 또는 mac이 수신한 패킷과 다릅니다)'
            else:
                mismatched = [
                    key for key, field, tol in COMPARED_FIELDS
                    if getattr(sub, field) is None or abs(getattr(sub, field) - decoded[key]) > tol
                ]
                if mismatched:
                    sub.status = Submission.STATUS_MISMATCH
                    sub.detail = '파싱 값 불일치: ' + ', '.join(mismatched)
                else:
                    sub.status = Submission.STATUS_VERIFIED

    sub.save()

    if sub.verified:
        return ok({
            'result': 'Success',
            'message': f'Data received from {team} successfully!',
            'received_data': {'team': team, 'sensor': sensor},
            'verified': True,
        })

    logger.info(f'opensrc rejected: team={team} status={sub.status} detail={sub.detail}')
    extra = {'received_data': {'team': team, 'sensor': sensor}, 'verified': False, 'status': sub.status}
    if sub.status == Submission.STATUS_MISMATCH:
        # 태그가 통과했으므로 정답을 알려줘도 편법에 쓸 수 없다. 파서 디버깅용.
        extra['expected'] = sub.decoded
    return fail(sub.detail, **extra)


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
    qs = Submission.objects.all()
    team = request.GET.get('team')
    if team:
        qs = qs.filter(team=team)
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return qs


@require_GET
def check(request):
    return render(request, 'opensrc/check.html')


@require_GET
def latest(request):
    try:
        limit = min(max(int(request.GET.get('limit', 100)), 1), 1000)
    except ValueError:
        limit = 100
    rows = [_serialize(s) for s in _filtered(request)[:limit]]
    return JsonResponse({'rows': rows})


@require_GET
def summary(request):
    teams = (
        Submission.objects.values('team')
        .annotate(
            total=Count('id'),
            verified=Count('id', filter=Q(status=Submission.STATUS_VERIFIED)),
            last=Max('received_at'),
        )
        .order_by('team')
    )
    return JsonResponse({'teams': [
        {**t, 'last': timezone.localtime(t['last']).strftime('%Y-%m-%d %H:%M:%S')}
        for t in teams
    ]})


@require_GET
def export_csv(request):
    header = ['received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'AQI', 'TVOC',
              'eCO2', 'timestamp', 'lat', 'lon', 'sender', 'status', 'detail']
    filename = f"opensrc_{request.GET.get('team') or 'all'}.csv".replace(' ', '_')
    return csv_response(header, _filtered(request).order_by('received_at'), _serialize, filename)

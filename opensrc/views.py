import csv
import json
import logging
from urllib.parse import quote

from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import otp
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


def _fail(message, http_status=400, **extra):
    return JsonResponse({'result': 'Fail', 'message': message, **extra}, status=http_status)


def _load_body(request):
    """JSON body가 기본이고, Retrofit @FormUrlEncoded(@Field)로 보낸 경우도 받는다."""
    try:
        body = json.loads(request.body or b'{}')
        if isinstance(body, dict):
            return body
    except (ValueError, UnicodeDecodeError):
        pass
    if request.POST:
        return request.POST.dict()
    return None


def _get(body, key):
    # 'AQI' / 'aqi' / 'Aqi'처럼 대소문자만 다르게 보내도 받아준다
    if key in body:
        return body[key]
    lowered = key.lower()
    for k, v in body.items():
        if k.lower() == lowered:
            return v
    return None


def _to_number(value, cast):
    if value is None or value == '':
        return None
    try:
        return cast(float(value)) if cast is int else cast(value)
    except (TypeError, ValueError):
        return None


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@csrf_exempt
@require_POST
def submit(request):
    body = _load_body(request)
    if body is None:
        return _fail('body를 JSON으로 파싱할 수 없습니다')
    if _get(body, 'key') != settings.OPENSRC_API_KEY:
        return _fail('key가 올바르지 않습니다')

    team = str(_get(body, 'team') or '').strip()
    sensor = str(_get(body, 'sensor') or '').strip()
    if not team or not sensor:
        return _fail('team, sensor는 필수입니다')

    sub = Submission(
        team=team[:100],
        sensor=sensor[:100],
        mac=str(_get(body, 'mac') or '').strip()[:32],
        sender=str(_get(body, 'sender') or '').strip()[:100],
        client_ip=_client_ip(request),
        temp=_to_number(_get(body, 'temp'), float),
        humidity=_to_number(_get(body, 'humidity'), float),
        aqi=_to_number(_get(body, 'AQI'), int),
        tvoc=_to_number(_get(body, 'TVOC'), int),
        eco2=_to_number(_get(body, 'eCO2'), int),
        timestamp=_to_number(_get(body, 'timestamp'), int),
        lat=_to_number(_get(body, 'lat'), float),
        lon=_to_number(_get(body, 'lon'), float),
        raw=str(_get(body, 'raw') or '').strip()[:128],
    )

    if not sub.raw:
        sub.status, sub.detail = Submission.STATUS_NO_RAW, 'raw 필드가 없습니다'
    else:
        try:
            ok, decoded = otp.verify(sub.raw, sub.mac, settings.OPENSRC_HMAC_KEY, settings.OPENSRC_TAG_LEN)
        except otp.RawError as e:
            sub.status, sub.detail = Submission.STATUS_BAD_RAW, str(e)
        else:
            sub.decoded = decoded
            if not ok:
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
        return JsonResponse({
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
    return _fail(sub.detail, **extra)


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


class _Echo:
    def write(self, value):
        return value


@require_GET
def export_csv(request):
    header = ['received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'AQI', 'TVOC',
              'eCO2', 'timestamp', 'lat', 'lon', 'status', 'detail']
    writer = csv.writer(_Echo())

    def rows():
        yield '﻿'  # 엑셀에서 한글이 깨지지 않도록 BOM
        yield writer.writerow(header)
        for s in _filtered(request).order_by('received_at').iterator(chunk_size=2000):
            d = _serialize(s)
            yield writer.writerow([d[h] for h in header])

    filename = f"opensrc_{request.GET.get('team') or 'all'}.csv".replace(' ', '_')
    resp = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
    # 팀명이 한글이어도 파일명이 깨지지 않도록 RFC 5987 형식 사용
    resp['Content-Disposition'] = f"attachment; filename=\"opensrc.csv\"; filename*=UTF-8''{quote(filename)}"
    return resp

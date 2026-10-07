import datetime
import logging

from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import alerts, levels
from .authentication import DeviceAPIKeyAuthentication, ViewerAuthentication
from .models import ShopSite, WaterLevelReading
from .serializers import BatchReadingSerializer, SingleReadingSerializer
from .throttling import DeviceKeyRateThrottle

logger = logging.getLogger('shopsense')

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000


def _iso(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _reading_json(site, reading):
    if reading is None:
        return None
    return {
        'measured_at': _iso(reading.measured_at),
        'received_at': _iso(reading.received_at),
        'distance_cm': reading.distance_cm,
        'level_cm': levels.level_cm(site, reading.distance_cm),
    }


def _bad_request(message):
    return Response({'detail': message}, status=http.HTTP_400_BAD_REQUEST)


def _parse_query_time(value, is_end):
    """조회용 from/to. 사람이 손으로 넣는 값이라 타임존이 없으면 KST로 본다. 날짜만 주면 to는 그날 끝까지."""
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is None:
        try:
            day = parse_date(value)
        except ValueError:
            return None
        if day is None:
            return None
        parsed = datetime.datetime.combine(day + datetime.timedelta(days=1 if is_end else 0), datetime.time())
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


class ReadingsView(APIView):
    """POST: 측정값 저장 (Pi) / GET: 기간 조회."""

    permission_classes = [IsAuthenticated]

    def get_authenticators(self):
        # 쓰기(장비)와 읽기(나중에 사장님 웹)의 인증을 분리해 둔다
        if self.request.method == 'POST':
            return [DeviceAPIKeyAuthentication()]
        return [ViewerAuthentication()]

    def get_throttles(self):
        # 쓰기만 키당 횟수 제한 (settings.SHOP_POST_RATE). 초과 시 429 + Retry-After
        if self.request.method == 'POST':
            return [DeviceKeyRateThrottle()]
        return []

    def post(self, request):
        if not isinstance(request.data, dict):
            return _bad_request('JSON 객체를 보내야 합니다.')
        batch = 'readings' in request.data
        serializer = (BatchReadingSerializer if batch else SingleReadingSerializer)(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        site = ShopSite.objects.filter(pk=data['site_id']).first()
        if site is None:
            return _bad_request(f'site_id={data["site_id"]}인 설치 장소가 없습니다.')

        items = data['readings'] if batch else [data]
        # 같은 요청 안의 중복 시각은 첫 번째만 쓴다
        unique = {}
        for item in items:
            unique.setdefault(item['measured_at'], item['distance_cm'])

        existing = set(site.readings.filter(measured_at__in=unique.keys())
                       .values_list('measured_at', flat=True))
        new = [WaterLevelReading(site=site, measured_at=t, distance_cm=d)
               for t, d in unique.items() if t not in existing]
        with transaction.atomic():
            # 동시에 같은 값이 들어와도 유니크 제약이 막고, ignore_conflicts로 오류 없이 넘어간다
            WaterLevelReading.objects.bulk_create(new, ignore_conflicts=True)

        if new:
            # 알람은 이번에 새로 들어온 값 중 가장 최근 것 기준 (밀린 배치로 과거 경보가 쏟아지지 않게)
            alerts.check_and_notify(max(new, key=lambda r: r.measured_at))

        created = len(new)
        return Response(
            {'site_id': site.pk, 'created': created, 'skipped': len(items) - created},
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK,
        )

    def get(self, request):
        params = request.query_params
        try:
            site_id = int(params.get('site_id', ''))
        except ValueError:
            return _bad_request('site_id(정수)가 필요합니다.')
        site = get_object_or_404(ShopSite, pk=site_id)

        qs = site.readings.all()
        for name, is_end in (('from', False), ('to', True)):
            value = params.get(name)
            if not value:
                continue
            bound = _parse_query_time(value, is_end)
            if bound is None:
                return _bad_request(f'{name} 형식이 올바르지 않습니다: "{value}" '
                                    '(예: 2026-10-08 또는 2026-10-08T10:00:00+09:00)')
            qs = qs.filter(**{'measured_at__lt' if is_end else 'measured_at__gte': bound})

        order = (params.get('order') or 'desc').lower()
        if order not in ('asc', 'desc'):
            return _bad_request('order는 asc 또는 desc입니다.')
        try:
            limit = int(params.get('limit') or DEFAULT_LIMIT)
        except ValueError:
            return _bad_request('limit은 정수입니다.')
        if not 1 <= limit <= MAX_LIMIT:
            return _bad_request(f'limit은 1~{MAX_LIMIT} 사이여야 합니다.')

        rows = qs.order_by('measured_at' if order == 'asc' else '-measured_at')[:limit]
        readings = [_reading_json(site, r) for r in rows]
        return Response({
            'site_id': site.pk,
            'baseline_cm': site.baseline_cm,
            'order': order,
            'count': len(readings),
            'readings': readings,
        })


class SiteLatestView(APIView):
    authentication_classes = [ViewerAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, site_id):
        site = get_object_or_404(ShopSite, pk=site_id)
        latest = site.readings.order_by('-measured_at').first()
        last_valid = (latest if latest is not None and latest.distance_cm is not None
                      else site.readings.filter(distance_cm__isnull=False).order_by('-measured_at').first())
        last_received = levels.last_received_at(site)
        level = levels.level_cm(site, latest.distance_cm) if latest else None

        return Response({
            'site': {
                'id': site.pk,
                'name': site.name,
                'baseline_cm': site.baseline_cm,
                'warn_level_cm': site.warn_level_cm,
                'danger_level_cm': site.danger_level_cm,
            },
            # 최신 측정이 실패(null)면 수위를 알 수 없으므로 no_data
            'status': levels.level_status(site, level),
            'stale': levels.is_stale(last_received),
            'last_received_at': _iso(last_received),
            'reading': _reading_json(site, latest),
            # 최신값이 측정 실패일 때 참고용으로 마지막 정상 측정값
            'last_valid_reading': _reading_json(site, last_valid),
        })


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            logger.exception('shopsense health: DB 연결 실패')
            return Response({'status': 'error', 'db': 'unavailable'}, status=http.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'status': 'ok', 'time': _iso(timezone.now())})

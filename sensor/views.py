from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import F, Q, Avg, Count, FloatField, ExpressionWrapper
from django.db.models.functions import Floor
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import time
import logging
import re
import requests
import shutil
import subprocess
import os
import pytz
from datetime import datetime, timedelta
from pathlib import Path

from .models import SensorData, IpDb, SensorCheckDb, MobileCheckDb, SensorLocation, PWSObservation, PWSLatest, PWSStation, CCTVStation, CCTVRecording

logger = logging.getLogger(__name__)

KST = pytz.timezone('Asia/Seoul')


def normalize_sensor_name(sensor_name):
    """
    센서 이름 정규화
    sensor1, sensor 1, sensor01, sensor 01 → sensor 01
    opensrc_team1, Opensrc_Team1 → opensrc_team1 (정규화하지 않음)
    """
    if not sensor_name:
        return sensor_name

    sensor_name = sensor_name.strip().lower()

    # 오픈소스 수업용 캠퍼스 센서(opensrc_team1 …)는 숫자를 뽑으면 연구실 'sensor 01'과 섞이므로
    # 소문자화만 하고 이름을 그대로 둔다 (opensrc.models.CampusSensor.lab_sensor 와 맞춰야 함)
    if 'opensrc' in sensor_name:
        return sensor_name

    # 숫자만 추출
    match = re.search(r'(\d+)', sensor_name)
    if match:
        num = int(match.group(1))
        return f"sensor {num:02d}"

    return sensor_name


@require_http_methods(["GET"])
def sensor_sensing(request):
    """센서 데이터 수신 및 IP/위치 관리 (멀티 퍼포즈 엔드포인트)"""
    logger.debug(f"sensor_sensing called with params: {dict(request.GET)}")

    # 센서 데이터 수신 (temperature, co2, time 포함)
    if all(k in request.GET for k in ['temp', 'co2', 'time']):
        return receive_sensor_data(request)

    # IP 기록 (ip 파라미터 포함)
    elif 'ip' in request.GET:
        return record_sensor_ip(request)

    # 위치 설정 (latitude, longitude 포함)
    elif all(k in request.GET for k in ['latitude', 'longitude']):
        return set_sensor_location(request)

    else:
        available_params = list(request.GET.keys())
        return JsonResponse({
            'error': 'Invalid parameters',
            'received': available_params,
            'message': 'Provide either (temp+co2+time) for sensor data, (ip) for IP, or (latitude+longitude) for location'
        }, status=400)


def receive_sensor_data(request):
    """센서 데이터 수신"""
    try:
        # 필수 파라미터 검증
        required = ['mac', 'sensor', 'sender', 'temp', 'co2', 'time']
        missing = [p for p in required if p not in request.GET]
        if missing:
            return JsonResponse({
                'error': 'Missing required parameters',
                'missing': missing
            }, status=400)

        mac = request.GET.get('mac').strip()
        sensor = normalize_sensor_name(request.GET.get('sensor'))
        sender = request.GET.get('sender').strip()
        mode = request.GET.get('mode', 'direct').strip()

        try:
            temp = float(request.GET.get('temp'))
            co2 = int(request.GET.get('co2'))
            sensing_time = float(request.GET.get('time'))
        except (ValueError, TypeError) as e:
            return JsonResponse({
                'error': 'Invalid data types',
                'details': f'temp must be float, co2 must be int, time must be float. Error: {str(e)}'
            }, status=400)

        rssi = request.GET.get('rssi')

        if not all([mac, sensor, sender]):
            return JsonResponse({
                'error': 'Empty required parameters',
                'details': f'mac={bool(mac)}, sensor={bool(sensor)}, sender={bool(sender)}'
            }, status=400)

        # 원시 데이터 저장
        data = SensorData.objects.create(
            sensor=sensor,
            mac=mac,
            receiver=sender,
            mode=mode,
            temperature=temp,
            co2=co2,
            sensing_time=sensing_time,
            rssi=int(rssi) if rssi else None,
        )

        # 센서 30여 대가 10초 주기로 올라와 INFO로 두면 로그가 이것만으로 가득 찬다
        logger.debug(f"Sensor data saved: {sensor} - temp={temp}, co2={co2}")

        # 최신 상태 스냅샷 업데이트
        if mode == 'direct':
            SensorCheckDb.objects.update_or_create(
                sensor=sensor,
                defaults={
                    'temperature': int(temp),
                    'co2': co2,
                    'sensing_time': sensing_time,
                }
            )
        elif mode == 'mobile':
            MobileCheckDb.objects.update_or_create(
                sensor=sensor,
                defaults={
                    'temperature': int(temp),
                    'co2': co2,
                    'rssi': int(rssi) if rssi else -100,
                    'receiver': sender,
                    'sensing_time': sensing_time,
                }
            )

        return JsonResponse({'status': 'success', 'message': 'Data received', 'id': data.id})

    except Exception as e:
        logger.exception(f"Error receiving sensor data: {str(e)}")
        return JsonResponse({
            'error': 'Server error',
            'details': str(e) if logger.isEnabledFor(logging.DEBUG) else 'Internal error'
        }, status=400)


@require_http_methods(["GET"])
def record_sensor_ip(request):
    """센서 IP 기록"""
    try:
        sensor = normalize_sensor_name(request.GET.get('sensor', ''))
        ip = request.GET.get('ip', '').strip()

        if not sensor or not ip:
            return JsonResponse({
                'error': 'Missing required parameters',
                'required': ['sensor', 'ip']
            }, status=400)

        IpDb.objects.create(
            sensor=sensor,
            ip=ip,
            time=int(time.time()),
        )

        logger.info(f"IP recorded: {sensor} -> {ip}")
        return JsonResponse({'status': 'success', 'message': 'IP recorded'})

    except Exception as e:
        logger.exception(f"Error recording IP: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)


def set_sensor_location(request):
    """센서 위치 설정"""
    try:
        sensor = normalize_sensor_name(request.GET.get('sensor', ''))

        if not sensor:
            return JsonResponse({
                'error': 'Missing sensor parameter'
            }, status=400)

        try:
            latitude = float(request.GET.get('latitude'))
            longitude = float(request.GET.get('longitude'))
        except (ValueError, TypeError) as e:
            return JsonResponse({
                'error': 'Invalid coordinate format',
                'details': 'latitude and longitude must be valid floats'
            }, status=400)

        location, created = SensorLocation.objects.update_or_create(
            sensor=sensor,
            defaults={
                'latitude': latitude,
                'longitude': longitude,
            }
        )

        action = 'created' if created else 'updated'
        logger.info(f"Location {action}: {sensor} ({latitude}, {longitude})")
        return JsonResponse({
            'status': 'success',
            'message': f'Location {action}',
            'action': action
        })

    except Exception as e:
        logger.exception(f"Error setting location: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)


@api_view(['GET'])
def sensor_map(request):
    """최신 센서 데이터 통합 조회 (지도용)"""
    # sensor_check_db와 location 조인
    direct_sensors = SensorCheckDb.objects.all().values(
        'sensor', 'temperature', 'co2', 'sensing_time'
    )
    mobile_sensors = MobileCheckDb.objects.all().values(
        'sensor', 'temperature', 'co2', 'sensing_time'
    )

    result = []

    # Direct 센서 데이터
    for sensor_data in direct_sensors:
        try:
            location = SensorLocation.objects.get(sensor=sensor_data['sensor'])
            current_time = time.time()
            is_fresh = (current_time - sensor_data['sensing_time']) < 3600

            result.append({
                'sensor': sensor_data['sensor'],
                'latitude': location.latitude,
                'longitude': location.longitude,
                'temperature': sensor_data['temperature'],
                'co2': sensor_data['co2'],
                'time': datetime.fromtimestamp(sensor_data['sensing_time']).strftime('%a %b %d %H:%M:%S %Y'),
                'fresh': is_fresh,
                'mode': 'direct',
            })
        except SensorLocation.DoesNotExist:
            pass

    # Mobile 센서 데이터
    for sensor_data in mobile_sensors:
        try:
            location = SensorLocation.objects.get(sensor=sensor_data['sensor'])
            current_time = time.time()
            is_fresh = (current_time - sensor_data['sensing_time']) < 3600

            result.append({
                'sensor': sensor_data['sensor'],
                'latitude': location.latitude,
                'longitude': location.longitude,
                'temperature': sensor_data['temperature'],
                'co2': sensor_data['co2'],
                'time': datetime.fromtimestamp(sensor_data['sensing_time']).strftime('%a %b %d %H:%M:%S %Y'),
                'fresh': is_fresh,
                'mode': 'mobile',
            })
        except SensorLocation.DoesNotExist:
            pass

    return Response(result)


@api_view(['GET'])
def realtime_stats(request):
    """실시간 온도/CO2/강수량 평균 통계 (대시보드 상단 카드용)"""
    now_ts = time.time()
    fresh_window = 3600  # 1시간 이내 데이터만 유효한 것으로 간주

    direct = SensorCheckDb.objects.filter(sensing_time__gte=now_ts - fresh_window)
    mobile = MobileCheckDb.objects.filter(sensing_time__gte=now_ts - fresh_window)

    temps = [d.temperature for d in direct] + [m.temperature for m in mobile]
    co2s = [d.co2 for d in direct] + [m.co2 for m in mobile]
    precip_values = [p.precipRate for p in PWSLatest.objects.all() if p.precipRate is not None]

    return Response({
        'temperature': round(sum(temps) / len(temps), 1) if temps else None,
        'co2': round(sum(co2s) / len(co2s)) if co2s else None,
        'precipRate': round(sum(precip_values) / len(precip_values), 2) if precip_values else None,
        'sensor_count': len(temps),
        'updated_at': datetime.fromtimestamp(now_ts, tz=KST).isoformat(),
    })


def _parse_time_param(value, default):
    """쿼리 파라미터를 unix timestamp(float)로 변환 (unix timestamp 또는 ISO datetime 문자열 지원)"""
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = KST.localize(dt)
        return dt.timestamp()
    except ValueError:
        return default


@api_view(['GET'])
def climate_timeseries(request):
    """기간별 온도/CO2 시계열 집계 조회 (센서별 또는 전체 평균)"""
    now_ts = time.time()
    end = _parse_time_param(request.GET.get('end'), now_ts)
    start = _parse_time_param(request.GET.get('start'), end - 86400)

    if end <= start:
        return Response({'error': 'end must be after start'}, status=400)

    span = end - start
    if span <= 3600:
        bucket_seconds = 60
    elif span <= 6 * 3600:
        bucket_seconds = 300
    elif span <= 86400:
        bucket_seconds = 900
    elif span <= 7 * 86400:
        bucket_seconds = 3600
    elif span <= 31 * 86400:
        bucket_seconds = 21600
    else:
        bucket_seconds = 86400

    qs = SensorData.objects.filter(sensing_time__gte=start, sensing_time__lte=end)

    sensors_param = request.GET.get('sensors', '').strip()
    if sensors_param and sensors_param != 'all':
        sensor_list = [s.strip() for s in sensors_param.split(',') if s.strip()]
        qs = qs.filter(sensor__in=sensor_list)
    else:
        registered = list(SensorLocation.objects.values_list('sensor', flat=True))
        qs = qs.filter(sensor__in=registered)

    bucket_expr = ExpressionWrapper(
        Floor(F('sensing_time') / bucket_seconds) * bucket_seconds,
        output_field=FloatField(),
    )

    rows = (
        qs.annotate(bucket=bucket_expr)
          .values('bucket')
          .annotate(avg_temp=Avg('temperature'), avg_co2=Avg('co2'), count=Count('id'))
          .order_by('bucket')
    )

    data = [
        {
            'time': datetime.fromtimestamp(row['bucket'], tz=KST).isoformat(),
            'temperature': round(row['avg_temp'], 2) if row['avg_temp'] is not None else None,
            'co2': round(row['avg_co2'], 1) if row['avg_co2'] is not None else None,
            'count': row['count'],
        }
        for row in rows
    ]

    return Response({
        'bucket_seconds': bucket_seconds,
        'start': start,
        'end': end,
        'data': data,
    })


def dashboard(request):
    """센서맵 + 실시간 통계 + 시계열 분석 통합 대시보드"""
    sensors = list(SensorLocation.objects.order_by('sensor').values_list('sensor', flat=True))
    return render(request, 'sensor/dashboard.html', {
        'sensors': sensors,
        'naver_map_client_id': 'y79pv4zb9e',
    })


@api_view(['GET'])
def latest_sensor_data(request):
    """최신 센서 데이터 조회 (DB 원시 데이터)"""
    latest_data = {}

    # 각 센서별 최신 데이터 1건만 조회
    for sensor_name in SensorData.objects.values_list('sensor', flat=True).distinct():
        latest = SensorData.objects.filter(sensor=sensor_name).order_by('-sensing_time').first()
        if latest:
            latest_data[sensor_name] = {
                'sensor': latest.sensor,
                'mac': latest.mac,
                'receiver': latest.receiver,
                'mode': latest.mode,
                'temperature': latest.temperature,
                'co2': latest.co2,
                'sensing_time': latest.sensing_time,
                'rssi': latest.rssi,
            }

    return Response(list(latest_data.values()))


@api_view(['GET'])
def latest_sensor_ips(request):
    """최신 센서 IP 조회"""
    latest_ips = {}

    # 각 센서별 최신 IP 1건만 조회
    for sensor_name in IpDb.objects.values_list('sensor', flat=True).distinct():
        latest = IpDb.objects.filter(sensor=sensor_name).order_by('-time').first()
        if latest:
            latest_ips[sensor_name] = {
                'sensor': latest.sensor,
                'ip': latest.ip,
                'time': latest.time,
            }

    return Response(list(latest_ips.values()))


def fetch_pws_data():
    """PWS API에서 데이터 수집 (자동 호출용)"""
    API_KEY = "0bdb9c7bdcfc41f19b9c7bdcfce1f1c6"
    STATION_IDS = ["ICHEON28", "ICHEONGJ6", "ICHEON24"]
    API_URL = "https://api.weather.com/v2/pws/observations/current"

    for station_id in STATION_IDS:
        try:
            params = {
                'stationId': station_id,
                'format': 'json',
                'units': 'm',  # Metric
                'apiKey': API_KEY,
                'numericPrecision': 'decimal'
            }

            response = requests.get(API_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if 'observations' not in data or len(data['observations']) == 0:
                logger.warning(f"PWS {station_id}: No observations returned")
                continue

            obs = data['observations'][0]

            # PWSStation 업데이트 (메타데이터)
            station, created = PWSStation.objects.update_or_create(
                stationID=station_id,
                defaults={
                    'stationName': obs.get('neighborhood') or '',
                    'neighborhood': obs.get('neighborhood') or '',
                    'country': obs.get('country') or '',
                    'latitude': obs.get('lat', 0),
                    'longitude': obs.get('lon', 0),
                    'elevation': obs.get('imperial', {}).get('elev'),
                    'softwareType': obs.get('softwareType') or '',
                }
            )

            # PWSObservation 저장 (새로운 데이터만)
            obs_time = datetime.fromisoformat(obs['obsTimeUtc'].replace('Z', '+00:00'))
            metric = obs.get('metric', {})

            # 마지막 저장 데이터와 비교 - 새로운 데이터만 저장
            last = PWSLatest.objects.filter(stationID=station_id).first()
            if last and last.obsTimeUtc == obs_time:
                logger.debug(f"PWS {station_id}: Data unchanged (obsTimeUtc={obs_time}), skipping save")
                continue

            PWSObservation.objects.update_or_create(
                stationID=station_id,
                obsTimeUtc=obs_time,
                defaults={
                    'obsTimeLocal': obs.get('obsTimeLocal', ''),
                    'temperature': metric.get('temp'),
                    'dewpoint': metric.get('dewpt'),
                    'heatIndex': metric.get('heatIndex'),
                    'windChill': metric.get('windChill'),
                    'humidity': obs.get('humidity'),
                    'pressure': metric.get('pressure'),
                    'windSpeed': metric.get('windSpeed'),
                    'windGust': metric.get('windGust'),
                    'winddir': obs.get('winddir'),
                    'precipRate': metric.get('precipRate'),
                    'precipTotal': metric.get('precipTotal'),
                    'solarRadiation': obs.get('solarRadiation'),
                    'uv': obs.get('uv'),
                    'qcStatus': obs.get('qcStatus', -1),
                }
            )

            # PWSLatest 업데이트 (최신 스냅샷)
            PWSLatest.objects.update_or_create(
                stationID=station_id,
                defaults={
                    'obsTimeUtc': obs_time,
                    'temperature': metric.get('temp'),
                    'humidity': obs.get('humidity'),
                    'pressure': metric.get('pressure'),
                    'windSpeed': metric.get('windSpeed'),
                    'windGust': metric.get('windGust'),
                    'winddir': obs.get('winddir'),
                    'precipRate': metric.get('precipRate'),
                    'dewpoint': metric.get('dewpt'),
                    'heatIndex': metric.get('heatIndex'),
                }
            )

            logger.info(f"PWS {station_id}: New data saved (obsTimeUtc={obs_time})")

        except requests.exceptions.RequestException as e:
            logger.error(f"PWS {station_id}: Request error - {str(e)}")
        except Exception as e:
            logger.exception(f"PWS {station_id}: Error - {str(e)}")


CCTV_ROOT = Path('/mnt/storage/cctv')

# 세그먼트 파일명에 쓰는 시각 포맷. ffmpeg -strftime 이 직접 확장하므로
# 파이썬 strptime 포맷과 동일한 문자열을 그대로 넘긴다.
SEGMENT_TIME_FORMAT = '%Y-%m-%d_%H-%M-%S'

CCTV_CONFIG = {
    'segment_duration': 300,      # 5분 단위로 파일 분할
    'record_start_hour': 5,       # KST 05:00부터
    'record_end_hour': 20,        # KST 20:00까지 (20:00 정각에 종료)
    'stall_timeout': 900,         # 새 세그먼트가 15분간 안 나오면 스트림 행으로 보고 재시작
    'min_free_gb': 100,           # 여유 공간이 이 밑이면 신규 녹화 중단 (DB가 같은 볼륨에 있음)
    'min_segment_mb': 1,          # 이보다 작은 파일은 failed로 표시
}

CCTV_STATIONS = {
    'ICHEONGJ6': {
        'cctvID': 'ICHEON_J6',
        'url': 'http://211.236.64.77:1935/91/playlist.m3u8',
        'location': 'Sangdang-Sageori',
    },
    'ICHEON24': {
        'cctvID': 'ICHEON_24',
        'url': 'http://211.236.64.77:1935/124/playlist.m3u8',
        'location': 'Heungdeok-Sageori',
    },
    'ICHEON28': [
        {
            'cctvID': 'ICHEON_28_A',
            'url': 'http://211.236.64.77:1935/108/playlist.m3u8',
            'location': 'Sachang-Sageori',
        },
        {
            'cctvID': 'ICHEON_28_B',
            'url': 'http://211.236.64.77:1935/110/playlist.m3u8',
            'location': 'Gaesin-Ogeori',
        },
    ],
}

cctv_processes = {}


def iter_cctv_configs():
    """(pws_station_id, cctv_info) 쌍을 순회 (ICHEON28만 카메라 2대)"""
    for station_id, config in CCTV_STATIONS.items():
        entries = config if isinstance(config, list) else [config]
        for entry in entries:
            yield station_id, entry


def within_recording_window(now=None):
    """KST 기준 녹화 시간대(05:00~20:00) 안인지 판정"""
    now = now or timezone.localtime()
    return CCTV_CONFIG['record_start_hour'] <= now.hour < CCTV_CONFIG['record_end_hour']


def _parse_segment_start(cctv_id, path):
    """세그먼트 파일명에서 녹화 시작 시각(KST)을 파싱"""
    stem = Path(path).stem
    prefix = f"{cctv_id}_"
    if not stem.startswith(prefix):
        return None
    try:
        return KST.localize(datetime.strptime(stem[len(prefix):], SEGMENT_TIME_FORMAT))
    except ValueError:
        return None


def _current_precip_rate(pws_station):
    """해당 관측소의 최신 강수강도. 상시 녹화이므로 트리거가 아니라 사후 필터링용 메타데이터."""
    latest = PWSLatest.objects.filter(stationID=pws_station).first()
    if latest and latest.precipRate is not None:
        return latest.precipRate
    return 0.0


def register_completed_segments(cctv, output_dir, include_last=False):
    """
    ffmpeg가 써 놓은 세그먼트 파일 중 완성된 것을 CCTVRecording에 등록한다.
    ffmpeg가 아직 돌고 있으면 마지막 파일은 기록 중이므로 제외한다.
    """
    files = sorted(Path(output_dir).glob(f"{cctv.cctvID}_*.mp4"))
    if not include_last:
        files = files[:-1]
    if not files:
        return 0

    paths = [str(f) for f in files]
    known = set(
        CCTVRecording.objects.filter(file_path__in=paths).values_list('file_path', flat=True)
    )
    precip = _current_precip_rate(cctv.pws_station)

    created = 0
    for path in paths:
        if path in known:
            continue

        start = _parse_segment_start(cctv.cctvID, path)
        if start is None:
            logger.warning(f"CCTV {cctv.cctvID}: Unparsable segment filename, skipping - {path}")
            continue

        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            # ffmpeg가 파일을 닫은 시각 = 세그먼트 종료 시각
            end = datetime.fromtimestamp(os.path.getmtime(path), tz=KST)
        except OSError as e:
            logger.warning(f"CCTV {cctv.cctvID}: Cannot stat segment {path} - {e}")
            continue

        CCTVRecording.objects.create(
            cctv_station=cctv,
            start_time=start,
            end_time=end,
            file_path=path,
            precipRate_trigger=precip,
            status='completed' if size_mb >= CCTV_CONFIG['min_segment_mb'] else 'failed',
            duration_minutes=max(int((end - start).total_seconds() / 60), 0),
            file_size_mb=round(size_mb, 2),
        )
        created += 1

    return created


def start_cctv_recording(cctv):
    """
    카메라 1대에 대해 장시간 ffmpeg 프로세스를 띄운다.
    segment 먹서가 5분마다 파일을 끊어주므로 세그먼트마다 재접속하지 않아 영상이 끊기지 않는다.
    """
    output_dir = CCTV_ROOT / cctv.pws_station / timezone.localtime().strftime('%Y-%m-%d')
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(output_dir / f"{cctv.cctvID}_{SEGMENT_TIME_FORMAT}.mp4")

    cmd = [
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
        # 입력이 멎었을 때 영원히 매달리지 않도록 읽기 타임아웃 + 자동 재접속
        '-rw_timeout', '15000000',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_on_network_error', '1',
        '-reconnect_delay_max', '10',
        '-i', cctv.url,
        '-an', '-c:v', 'copy',
        '-f', 'segment',
        '-segment_time', str(CCTV_CONFIG['segment_duration']),
        '-segment_atclocktime', '1',  # 정각 기준 5분 경계로 끊어 분석하기 쉽게
        '-reset_timestamps', '1',
        '-strftime', '1',
        '-segment_format', 'mp4',
        output_pattern,
    ]

    # 컨테이너 OS 시간대는 UTC다. Django가 프로세스 TZ를 바꿔주긴 하지만 그 암묵적 동작에
    # 파일명을 의존시키지 않도록 자식 프로세스에 KST를 명시한다.
    env = {**os.environ, 'TZ': 'Asia/Seoul'}

    # stdout/stderr를 아무도 읽지 않으면 ffmpeg의 진행 로그가 파이프 버퍼를 채워
    # write()가 블로킹되고 녹화가 통째로 멈춘다 -> DEVNULL로 버림
    process = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )

    now = time.monotonic()
    cctv_processes[cctv.cctvID] = {
        'process': process,
        'output_dir': output_dir,
        'segment_count': 0,
        'last_progress_at': now,
    }

    logger.info(f"CCTV {cctv.cctvID}: Recording started (pid={process.pid}, dir={output_dir})")


def stop_cctv_recording(cctv_station_id, reason='window_closed'):
    """ffmpeg를 종료하고 남은 세그먼트를 등록한다."""
    state = cctv_processes.pop(cctv_station_id, None)
    if state is None:
        return

    process = state['process']
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"CCTV {cctv_station_id}: SIGTERM timed out, sending SIGKILL")
                process.kill()
                process.wait()  # kill 뒤에도 reap 해야 좀비가 남지 않는다
        else:
            process.wait()
    except Exception as e:
        logger.exception(f"CCTV {cctv_station_id}: Error terminating ffmpeg - {e}")

    registered = 0
    try:
        cctv = CCTVStation.objects.get(cctvID=cctv_station_id)
        registered = register_completed_segments(cctv, state['output_dir'], include_last=True)
    except CCTVStation.DoesNotExist:
        logger.error(f"CCTV {cctv_station_id}: Station not found while stopping")
    except Exception as e:
        logger.exception(f"CCTV {cctv_station_id}: Error registering segments on stop - {e}")

    logger.info(
        f"CCTV {cctv_station_id}: Recording stopped "
        f"(reason={reason}, {registered} new segment(s) registered)"
    )


def cleanup_orphan_recordings():
    """
    프로세스가 죽으면서 'recording'인 채 남은 과거 레코드를 정리한다.
    현재 방식은 세그먼트가 완성된 뒤에만 행을 만들므로 'recording' 상태는 더 이상 생기지 않는다.
    """
    orphans = CCTVRecording.objects.filter(status='recording')
    count = orphans.update(status='failed')
    if count:
        logger.warning(f"CCTV: Marked {count} orphaned 'recording' row(s) as failed")
    return count


def monitor_cctv_recording():
    """
    KST 05:00~20:00 동안 CCTV 4대를 상시 녹화한다 (5분 세그먼트).
    매분 호출되어 프로세스 생존/진행 상태를 확인하고 완성된 세그먼트를 DB에 등록한다.
    """
    try:
        in_window = within_recording_window()

        free_gb = shutil.disk_usage(CCTV_ROOT).free / (1024 ** 3)
        space_ok = free_gb >= CCTV_CONFIG['min_free_gb']
        if not space_ok:
            # DB도 같은 볼륨에 있으므로 디스크를 채우면 수집 전체가 죽는다
            logger.error(
                f"CCTV: Free space {free_gb:.1f}GB below {CCTV_CONFIG['min_free_gb']}GB floor "
                f"- recording halted"
            )

        for pws_station, info in iter_cctv_configs():
            cctv_id = info['cctvID']
            try:
                cctv, _ = CCTVStation.objects.get_or_create(
                    cctvID=cctv_id,
                    defaults={
                        'pws_station': pws_station,
                        'url': info['url'],
                        'location_name': info['location'],
                    },
                )

                if not (in_window and space_ok):
                    if cctv_id in cctv_processes:
                        stop_cctv_recording(
                            cctv_id,
                            reason='window_closed' if not in_window else 'low_disk_space',
                        )
                    continue

                state = cctv_processes.get(cctv_id)

                if state is None:
                    start_cctv_recording(cctv)
                    continue

                process = state['process']
                if process.poll() is not None:
                    logger.warning(
                        f"CCTV {cctv_id}: ffmpeg exited unexpectedly "
                        f"(code={process.returncode}), restarting"
                    )
                    stop_cctv_recording(cctv_id, reason='process_exited')
                    start_cctv_recording(cctv)
                    continue

                # 진행 감시: 프로세스는 살아있는데 새 세그먼트가 안 나오면 스트림이 물린 것
                segment_count = len(list(Path(state['output_dir']).glob(f"{cctv_id}_*.mp4")))
                if segment_count > state['segment_count']:
                    state['segment_count'] = segment_count
                    state['last_progress_at'] = time.monotonic()
                elif time.monotonic() - state['last_progress_at'] > CCTV_CONFIG['stall_timeout']:
                    logger.error(
                        f"CCTV {cctv_id}: No new segment for "
                        f"{CCTV_CONFIG['stall_timeout']}s - stream stalled, forcing restart"
                    )
                    stop_cctv_recording(cctv_id, reason='stalled')
                    start_cctv_recording(cctv)
                    continue

                register_completed_segments(cctv, state['output_dir'])

            except Exception as e:
                # 카메라 1대의 실패가 나머지 3대를 막지 않도록 개별 격리
                logger.exception(f"CCTV {cctv_id}: Monitor iteration failed - {e}")

    except Exception as e:
        logger.exception(f"CCTV monitoring error: {str(e)}")

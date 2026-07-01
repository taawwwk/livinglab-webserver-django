from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import time
import logging
import re
import requests
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path

from .models import SensorData, IpDb, SensorCheckDb, MobileCheckDb, SensorLocation, PWSObservation, PWSLatest, PWSStation, CCTVStation, CCTVRecording

logger = logging.getLogger(__name__)


def normalize_sensor_name(sensor_name):
    """
    센서 이름 정규화
    sensor1, sensor 1, sensor01, sensor 01 → sensor 01
    """
    if not sensor_name:
        return sensor_name

    sensor_name = sensor_name.strip().lower()

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

        logger.info(f"Sensor data saved: {sensor} - temp={temp}, co2={co2}")

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
            })
        except SensorLocation.DoesNotExist:
            pass

    return Response(result)


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
    API_KEY = "272cc24526044000acc2452604300041"
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

            # PWSObservation 저장 (원시 데이터)
            obs_time = datetime.fromisoformat(obs['obsTimeUtc'].replace('Z', '+00:00'))
            metric = obs.get('metric', {})

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

            logger.info(f"PWS {station_id}: Data saved successfully")

        except requests.exceptions.RequestException as e:
            logger.error(f"PWS {station_id}: Request error - {str(e)}")
        except Exception as e:
            logger.exception(f"PWS {station_id}: Error - {str(e)}")


CCTV_CONFIG = {
    'precipRate_threshold': 0.1,
    'min_duration': 1800,
    'max_duration': 7200,
    'resolution': '720x480',
    'codec': 'h264',
    'bitrate': '1500k',
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


def start_cctv_recording(cctv_station_id, precipRate):
    """CCTV 녹화 시작"""
    try:
        cctv = CCTVStation.objects.get(cctvID=cctv_station_id)

        # 녹화 디렉토리 생성
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_dir = f"/mnt/storage/cctv/{cctv.pws_station}/{timestamp}"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        output_file = f"{output_dir}/recording.mp4"

        # ffmpeg 명령어 (원본 스트림 복사)
        cmd = [
            'ffmpeg',
            '-i', cctv.url,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-t', str(CCTV_CONFIG['max_duration']),
            '-y',
            output_file,
        ]

        # ffmpeg 프로세스 시작
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cctv_processes[cctv_station_id] = {
            'process': process,
            'file_path': output_file,
            'output_dir': output_dir,
        }

        # 녹화 기록 생성
        CCTVRecording.objects.create(
            cctv_station=cctv,
            file_path=output_file,
            precipRate_trigger=precipRate,
            status='recording',
        )

        logger.info(f"CCTV {cctv_station_id}: Recording started (precipRate={precipRate}mm/hr)")

    except CCTVStation.DoesNotExist:
        logger.error(f"CCTV {cctv_station_id}: Station not found")
    except Exception as e:
        logger.exception(f"CCTV {cctv_station_id}: Error starting recording - {str(e)}")


def stop_cctv_recording(cctv_station_id, status='completed'):
    """CCTV 녹화 종료"""
    try:
        if cctv_station_id not in cctv_processes:
            return

        process_info = cctv_processes[cctv_station_id]
        process = process_info['process']

        # ffmpeg 프로세스 종료
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

        # 파일 크기 계산
        file_path = process_info['file_path']
        file_size_mb = 0
        if os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # 녹화 기록 업데이트
        recording = CCTVRecording.objects.filter(
            file_path=file_path,
            status='recording'
        ).first()

        if recording:
            recording.end_time = timezone.now()
            recording.status = status
            if recording.start_time:
                duration = (recording.end_time - recording.start_time).total_seconds() / 60
                recording.duration_minutes = int(duration)
            recording.file_size_mb = file_size_mb
            recording.save()

        del cctv_processes[cctv_station_id]

        logger.info(f"CCTV {cctv_station_id}: Recording stopped ({file_size_mb:.2f}MB, status={status})")

    except Exception as e:
        logger.exception(f"CCTV {cctv_station_id}: Error stopping recording - {str(e)}")


def monitor_preciprate_and_cctv():
    """강수량 모니터링 및 CCTV 자동 제어"""
    try:
        # PWS 최신 데이터 조회
        pws_stations = PWSLatest.objects.all()

        for pws in pws_stations:
            precipRate = pws.precipRate or 0
            threshold = CCTV_CONFIG['precipRate_threshold']

            # CCTV 설정 찾기
            cctv_config = CCTV_STATIONS.get(pws.stationID)
            if not cctv_config:
                continue

            # ICHEON28은 리스트, 나머지는 딕셔너리
            if isinstance(cctv_config, list):
                cctv_list = cctv_config
            else:
                cctv_list = [cctv_config]

            for cctv_info in cctv_list:
                cctv_id = cctv_info['cctvID']

                # 강수량 초과: 녹화 시작
                if precipRate > threshold:
                    if cctv_id not in cctv_processes:
                        # 스테이션 정보 저장 (없으면 생성)
                        CCTVStation.objects.get_or_create(
                            cctvID=cctv_id,
                            defaults={
                                'pws_station': pws.stationID,
                                'url': cctv_info['url'],
                                'location_name': cctv_info['location'],
                            }
                        )
                        start_cctv_recording(cctv_id, precipRate)

                # 강수량 정상: 녹화 중이면 종료
                elif cctv_id in cctv_processes:
                    stop_cctv_recording(cctv_id, status='completed')

    except Exception as e:
        logger.exception(f"CCTV monitoring error: {str(e)}")

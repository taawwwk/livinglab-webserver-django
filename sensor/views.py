from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import F, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import time
import logging
import re
from datetime import datetime, timedelta

from .models import SensorData, IpDb, SensorCheckDb, MobileCheckDb, SensorLocation

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

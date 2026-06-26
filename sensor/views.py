from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import F, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import time
from datetime import datetime, timedelta

from .models import SensorData, IpDb, SensorCheckDb, MobileCheckDb, SensorLocation


@require_http_methods(["GET"])
def sensor_sensing(request):
    """센서 데이터 수신 및 IP/위치 관리 (멀티 퍼포즈 엔드포인트)"""

    # 센서 데이터 수신 (temperature, co2, time 포함)
    if 'temp' in request.GET and 'co2' in request.GET and 'time' in request.GET:
        return receive_sensor_data(request)

    # IP 기록 (ip 파라미터 포함)
    elif 'ip' in request.GET:
        return record_sensor_ip(request)

    # 위치 설정 (latitude, longitude 포함)
    elif 'latitude' in request.GET and 'longitude' in request.GET:
        return set_sensor_location(request)

    else:
        return JsonResponse({'error': 'Invalid parameters'}, status=400)


def receive_sensor_data(request):
    """센서 데이터 수신"""
    try:
        mac = request.GET.get('mac', '')
        sensor = request.GET.get('sensor', '')
        sender = request.GET.get('sender', '')
        mode = request.GET.get('mode', 'direct')
        temp = float(request.GET.get('temp', 0))
        co2 = int(request.GET.get('co2', 0))
        sensing_time = float(request.GET.get('time', time.time()))
        rssi = request.GET.get('rssi')

        if not mac or not sensor or not sender:
            return JsonResponse({'error': 'Missing required parameters'}, status=400)

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

        return JsonResponse({'status': 'success', 'message': 'Data received'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def record_sensor_ip(request):
    """센서 IP 기록"""
    try:
        sensor = request.GET.get('sensor', '')
        ip = request.GET.get('ip', '')

        if not sensor or not ip:
            return JsonResponse({'error': 'Missing required parameters'}, status=400)

        IpDb.objects.create(
            sensor=sensor,
            ip=ip,
            time=int(time.time()),
        )

        return JsonResponse({'status': 'success', 'message': 'IP recorded'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def set_sensor_location(request):
    """센서 위치 설정"""
    try:
        sensor = request.GET.get('sensor', '')
        latitude = float(request.GET.get('latitude', 0))
        longitude = float(request.GET.get('longitude', 0))

        if not sensor:
            return JsonResponse({'error': 'Missing sensor parameter'}, status=400)

        location, created = SensorLocation.objects.update_or_create(
            sensor=sensor,
            defaults={
                'latitude': latitude,
                'longitude': longitude,
            }
        )

        return JsonResponse({'status': 'success', 'message': 'Location set'})

    except Exception as e:
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

"""4주차(연구실 센서 릴레이)와 5주차(팀 자체 센서) API가 함께 쓰는 헬퍼."""
import csv
import json
from urllib.parse import quote

from django.http import JsonResponse, StreamingHttpResponse

# 학생들이 응답을 String으로 받아 Logcat에 찍으므로 한글을 \uXXXX로 이스케이프하지 않는다
JSON_PARAMS = {'ensure_ascii': False}


def ok(payload):
    return JsonResponse(payload, json_dumps_params=JSON_PARAMS)


def fail(message, http_status=400, **extra):
    return JsonResponse({'result': 'Fail', 'message': message, **extra}, status=http_status,
                        json_dumps_params=JSON_PARAMS)


def load_body(request):
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


def get(body, key):
    # 'AQI' / 'aqi' / 'Aqi'처럼 대소문자만 다르게 보내도 받아준다
    if key in body:
        return body[key]
    lowered = key.lower()
    for k, v in body.items():
        if k.lower() == lowered:
            return v
    return None


def to_number(value, cast):
    if value is None or value == '':
        return None
    try:
        return cast(float(value)) if cast is int else cast(value)
    except (TypeError, ValueError):
        return None


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class _Echo:
    def write(self, value):
        return value


def csv_response(header, queryset, serialize, filename):
    writer = csv.writer(_Echo())

    def rows():
        yield '﻿'  # 엑셀에서 한글이 깨지지 않도록 BOM
        yield writer.writerow(header)
        for obj in queryset.iterator(chunk_size=2000):
            d = serialize(obj)
            yield writer.writerow([d[h] for h in header])

    resp = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
    # 팀명이 한글이어도 파일명이 깨지지 않도록 RFC 5987 형식 사용
    resp['Content-Disposition'] = f"attachment; filename=\"opensrc.csv\"; filename*=UTF-8''{quote(filename)}"
    return resp

import datetime
import math

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

MAX_DISTANCE_CM = 1000.0   # 이보다 크면 센서 오류로 보고 거절 (JSN-SR04T 실측 범위는 ~450cm)
MAX_BATCH_SIZE = 1000
# NTP가 틀어진 미래 시각 하나가 "최신값"을 계속 차지하지 않도록 허용 오차를 둔다
MAX_FUTURE_SKEW = datetime.timedelta(minutes=5)


class AwareDateTimeField(serializers.DateTimeField):
    """ISO 8601 + 타임존 필수. naive 시각을 KST로 추정하면 UTC로 보낸 값이 9시간 어긋나므로 거절한다."""

    default_error_messages = {
        'naive': '타임존이 포함된 ISO 8601 시각이어야 합니다 (예: 2026-10-08T10:15:30+09:00).',
        'future': '측정 시각이 서버 시각보다 5분 넘게 미래입니다. 라즈베리파이 NTP 동기화를 확인하세요.',
    }

    def to_internal_value(self, value):
        if isinstance(value, str):
            try:
                parsed = parse_datetime(value.strip())
            except ValueError:
                parsed = None  # 형식은 맞지만 값이 틀림(13월 등) → 아래 super()가 invalid로 처리
            if parsed is not None and timezone.is_naive(parsed):
                self.fail('naive')
        result = super().to_internal_value(value)
        if result > timezone.now() + MAX_FUTURE_SKEW:
            self.fail('future')
        return result


class DistanceField(serializers.FloatField):
    """측정 실패는 null로 받는다. 음수·1000 초과·NaN/Infinity는 거절."""

    default_error_messages = {'not_finite': '유한한 숫자여야 합니다.'}

    def __init__(self, **kwargs):
        super().__init__(allow_null=True, min_value=0.0, max_value=MAX_DISTANCE_CM, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            self.fail('not_finite')
        return value


class ReadingSerializer(serializers.Serializer):
    measured_at = AwareDateTimeField()
    # 키 자체는 필수, 값은 null 허용 (측정 실패를 명시적으로 보내게 한다)
    distance_cm = DistanceField()


class SingleReadingSerializer(ReadingSerializer):
    site_id = serializers.IntegerField(min_value=1)


class BatchReadingSerializer(serializers.Serializer):
    site_id = serializers.IntegerField(min_value=1)
    readings = serializers.ListField(child=ReadingSerializer(), min_length=1, max_length=MAX_BATCH_SIZE)

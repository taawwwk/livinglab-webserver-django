"""API 키당 POST 횟수 제한.

공개 주소로 받으므로 키가 유출되거나 장비가 오작동해도 DB에 쏟아붓지 못하게 한다.
요청 기록은 settings.SHOP_THROTTLE_CACHE 캐시에 둔다. 기본 LocMemCache는 gunicorn
worker마다 따로 세서 한도가 worker 수만큼 늘어나므로, worker들이 공유하는 캐시를 써야 한다.
"""
from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class DeviceKeyRateThrottle(SimpleRateThrottle):
    scope = 'shopsense_device'

    def __init__(self):
        # 테스트에서 override_settings로 바꿀 수 있도록 요청마다 읽는다
        self.cache = caches[settings.SHOP_THROTTLE_CACHE]
        super().__init__()

    def get_rate(self):
        return settings.SHOP_POST_RATE  # 예: '60/min'

    def get_cache_key(self, request, view):
        key_id = getattr(request.user, 'key_id', None)
        if key_id is None:
            return None  # 인증되지 않은 요청은 이미 401로 끝나므로 세지 않는다
        return self.cache_format % {'scope': self.scope, 'ident': key_id}

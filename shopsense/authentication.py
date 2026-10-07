"""shopsense API 인증.

- DeviceAPIKeyAuthentication: 현장 라즈베리파이가 측정값을 올릴 때 (POST)
- ViewerAuthentication: 조회 API (GET). 지금은 같은 API 키를 쓰지만, 사장님용
  모니터링 웹을 붙일 때 이 클래스만 세션/토큰 인증으로 바꾸면 되도록 분리해 둔다.

키는 환경변수 SHOP_API_KEYS(콤마 구분)로만 관리한다. 비어 있으면 모든 요청을 거부한다.
"""
import hmac

from django.conf import settings
from rest_framework import authentication, exceptions

API_KEY_HEADER = 'X-API-Key'


class APIKeyClient:
    """API 키로 인증된 호출자. DRF의 IsAuthenticated가 통과하도록 is_authenticated만 제공한다."""

    is_authenticated = True
    is_anonymous = False

    def __init__(self, key_index):
        # 어떤 키로 들어왔는지(키 자체가 아니라 순번)만 남긴다. 키 교체 시 추적용.
        self.key_index = key_index

    def __str__(self):
        return f'api-key#{self.key_index}'


def match_api_key(given):
    """SHOP_API_KEYS 중 일치하는 키의 순번, 없으면 None. 타이밍 공격을 피하려고 compare_digest로 전부 비교한다."""
    matched = None
    given_bytes = given.encode()
    for index, key in enumerate(settings.SHOP_API_KEYS):
        if hmac.compare_digest(given_bytes, key.encode()):
            matched = index
    return matched


class DeviceAPIKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        given = request.headers.get(API_KEY_HEADER)
        if not given:
            return None  # → NotAuthenticated (401)
        index = match_api_key(given)
        if index is None:
            raise exceptions.AuthenticationFailed('API 키가 올바르지 않습니다.')
        return APIKeyClient(index), None

    def authenticate_header(self, request):
        # 이 값이 있어야 DRF가 403이 아닌 401로 응답한다
        return API_KEY_HEADER


class ViewerAuthentication(DeviceAPIKeyAuthentication):
    """조회용 인증. TODO: 사장님 로그인 도입 시 세션/토큰 인증으로 교체."""

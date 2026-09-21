"""라즈베리파이 광고 코드에 붙이는 패킷 생성 모듈 (서버 opensrc/otp.py와 짝).

기존 13바이트 ServiceData 뒤에 HMAC 태그를 붙인다. 앞 13바이트 구조는 그대로라
학생들의 기존 파서(length >= 13)는 수정 없이 동작한다.

사용 예:
    from opensrc_packet import build_service_data, load_key
    KEY = load_key()                     # /etc/opensrc/hmac_key (root 전용)
    MAC = own_mac()                      # 폰에서 보이는 광고 주소와 같아야 함
    data = build_service_data(KEY, MAC, temp, hum, aqi, tvoc, eco2)
    # data(bytes, 21바이트)를 기존 ServiceData 값 자리에 그대로 넣는다

주의:
  - 키, TAG_LEN은 서버 .env의 OPENSRC_HMAC_KEY, OPENSRC_TAG_LEN과 같아야 한다.
  - MAC은 학생 폰이 보는 주소 기준이다. 랜덤 주소로 광고하면 검증이 실패하니
    nRF Connect 등으로 폰에 보이는 주소를 확인할 것.
  - timestamp가 태그에 들어가므로 NTP 동기화가 되어 있어야 한다.
"""
import hashlib
import hmac
import struct
import time

TAG_LEN = 8
KEY_PATH = '/etc/opensrc/hmac_key'


def load_key(path=KEY_PATH):
    with open(path, 'rb') as f:
        return f.read().strip()


def own_mac(hci='hci0'):
    with open(f'/sys/class/bluetooth/{hci}/address') as f:
        return f.read().strip().upper()


def build_service_data(key, mac, temp, humidity, aqi, tvoc, eco2, timestamp=None, tag_len=TAG_LEN):
    if timestamp is None:
        timestamp = int(time.time())
    payload = struct.pack(
        '<hHBHHI',
        round(temp * 100), round(humidity * 100), aqi, tvoc, eco2, timestamp,
    )
    mac_bytes = bytes.fromhex(mac.replace(':', ''))
    tag = hmac.new(key, mac_bytes + payload, hashlib.sha256).digest()[:tag_len]
    return payload + tag

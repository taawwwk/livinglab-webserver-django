"""라즈베리파이 BLE ServiceData 패킷 디코드 및 HMAC 태그 검증.

패킷 구조 (Little-Endian):
  [0~1]   int16   온도 × 100
  [2~3]   uint16  습도 × 100
  [4]     uint8   AQI
  [5~6]   uint16  TVOC (ppb)
  [7~8]   uint16  eCO2 (ppm)
  [9~12]  uint32  Unix Timestamp
  [13~ ]  bytes   tag = HMAC-SHA256(key, MAC 6바이트 || [0~12])[:TAG_LEN]

앞 13바이트는 기존 포맷 그대로라 학생들이 쓰던 파서(length >= 13)와 호환된다.
MAC을 서명에 넣어서 다른 센서의 패킷을 자기 센서 것으로 바꿔 보낼 수 없게 한다.
"""
import hashlib
import hmac
import re
import struct

PAYLOAD_LEN = 13
_PAYLOAD_FMT = '<hHBHHI'


class RawError(ValueError):
    pass


def parse_hex(raw):
    """'0A:1B 2c...' 처럼 구분자가 섞인 hex 문자열도 허용."""
    cleaned = re.sub(r'[\s:\-]', '', str(raw))
    if cleaned.lower().startswith('0x'):
        cleaned = cleaned[2:]
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        raise RawError('raw는 hex 문자열이어야 합니다')


def parse_mac(mac):
    cleaned = re.sub(r'[\s:\-]', '', str(mac))
    if not re.fullmatch(r'[0-9a-fA-F]{12}', cleaned):
        raise RawError('mac 형식이 올바르지 않습니다 (예: AA:BB:CC:DD:EE:FF)')
    return bytes.fromhex(cleaned)


def decode_payload(data):
    temp, hum, aqi, tvoc, eco2, ts = struct.unpack(_PAYLOAD_FMT, data[:PAYLOAD_LEN])
    return {
        'temp': temp / 100.0,
        'humidity': hum / 100.0,
        'AQI': aqi,
        'TVOC': tvoc,
        'eCO2': eco2,
        'timestamp': ts,
    }


def compute_tag(key, mac_bytes, payload, tag_len):
    return hmac.new(key, mac_bytes + payload[:PAYLOAD_LEN], hashlib.sha256).digest()[:tag_len]


def verify(raw, mac, key, tag_len):
    """raw를 검증하고 디코드 값을 반환. 형식 오류면 RawError, 태그 불일치면 (False, decoded)."""
    data = parse_hex(raw)
    if len(data) != PAYLOAD_LEN + tag_len:
        raise RawError(f'raw 길이가 {len(data)}바이트입니다 ({PAYLOAD_LEN + tag_len}바이트여야 함)')
    mac_bytes = parse_mac(mac)
    expected = compute_tag(key, mac_bytes, data, tag_len)
    return hmac.compare_digest(expected, data[PAYLOAD_LEN:]), decode_payload(data)

#!/usr/bin/env python3
"""대학가 가게 침수 실증: JSN-SR04T 수위센서 값을 서버(/api/shop/readings/)로 보낸다.

- 10초마다 5회 측정 → 중앙값(cm). 유효 측정이 부족하면 측정 실패로 보고 distance_cm=null을 보낸다.
- 측정값은 먼저 SQLite 큐(재부팅 후에도 유지)에 넣고, 큐에서 최대 1000건씩 배치로 보낸다.
- 서버 응답 처리:
    2xx               성공 → 큐에서 삭제
    400 (항목별 오류)   그 항목만 버리고 로그 (잘못된 데이터를 계속 재전송하지 않음)
    429               보관, Retry-After 후 재시도
    그 밖의 4xx         요청·설정 문제(키, site_id, URL) → 보관, 5분마다 재시도하며 ERROR 로그
    5xx/네트워크 오류    보관, 지수 백오프로 재시도

설정은 /etc/shopsense.env (SERVER_URL, API_KEY, SITE_ID). 환경변수가 있으면 그 값이 우선한다.
외부 패키지 없이 표준 라이브러리 + RPi.GPIO 호환 모듈(python3-rpi-lgpio 권장)만 쓴다.

    python3 sensor_post.py              # 실제 센서
    python3 sensor_post.py --fake       # 센서 없이 가짜 값으로 (서버 연동 확인용)
    python3 sensor_post.py --once       # 1회 측정·전송 후 종료
"""
import argparse
import dataclasses
import datetime
import json
import logging
import os
import random
import re
import signal
import sqlite3
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request

KST = datetime.timezone(datetime.timedelta(hours=9))
SPEED_OF_SOUND_CM_PER_S = 34300.0  # 20℃ 기준
BATCH_SIZE = 1000                  # 서버 배치 상한
CONFIG_PATH = '/etc/shopsense.env'

log = logging.getLogger('sensorpost')


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Config:
    server_url: str
    api_key: str
    site_id: int
    interval_sec: float = 10.0
    trig_pin: int = 23            # BCM
    echo_pin: int = 24            # BCM
    samples: int = 5
    min_valid_samples: int = 3    # 5회 중 이보다 적게 성공하면 측정 실패(null)
    min_cm: float = 20.0          # JSN-SR04T 블라인드 존. 이보다 가까운 값은 신뢰할 수 없어 실패로 본다
    max_cm: float = 600.0
    queue_path: str = '/var/lib/shopsense/queue.db'
    max_queue: int = 259200       # 10초 주기 30일치. 넘치면 오래된 것부터 버린다
    batches_per_cycle: int = 3    # 주기마다 보낼 최대 배치 수 (밀린 데이터 재전송 속도)
    http_timeout: float = 5.0
    ntp_wait_sec: int = 120
    config_path: str = CONFIG_PATH  # 오류 메시지에 실제로 읽은 설정 파일을 보여주기 위함

    @property
    def readings_url(self):
        return self.server_url.rstrip('/') + '/api/shop/readings/'


def _read_env_file(path):
    values = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                value = re.split(r'\s+#', value, maxsplit=1)[0]  # 값 뒤 주석 제거 ("23   # BCM")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


def load_config(path=CONFIG_PATH, environ=os.environ):
    values = _read_env_file(path)
    values.update({k: v for k, v in environ.items() if k.isupper()})
    missing = [k for k in ('SERVER_URL', 'API_KEY', 'SITE_ID') if not values.get(k)]
    if missing:
        raise SystemExit(f'{path}에 {", ".join(missing)} 값이 필요합니다.')

    optional = {f.name.upper(): f for f in dataclasses.fields(Config)
                if f.name not in ('server_url', 'api_key', 'site_id', 'config_path')}
    kwargs = {}
    for name, field in optional.items():
        if values.get(name):
            kwargs[field.name] = type(field.default)(values[name])
    return Config(server_url=values['SERVER_URL'], api_key=values['API_KEY'],
                  site_id=int(values['SITE_ID']), config_path=path, **kwargs)


# ---------------------------------------------------------------------------
# 센서
# ---------------------------------------------------------------------------

class UltrasonicSensor:
    """JSN-SR04T (모드 1, HC-SR04 호환 트리거). ECHO는 5V 출력이므로 반드시 분압해서 GPIO에 연결."""

    def __init__(self, trig_pin, echo_pin):
        import RPi.GPIO as GPIO  # 파이 5는 python3-rpi-lgpio가 이 이름으로 제공
        self.GPIO = GPIO
        self.trig, self.echo = trig_pin, echo_pin
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.trig, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.echo, GPIO.IN)
        time.sleep(0.5)  # 센서 안정화

    def read_once(self, timeout=0.04):
        """거리(cm) 1회. 응답이 없으면 None. 40ms는 약 6.8m 왕복 시간."""
        GPIO = self.GPIO
        deadline = time.perf_counter() + timeout
        while GPIO.input(self.echo):          # 이전 에코가 끝날 때까지
            if time.perf_counter() > deadline:
                return None

        GPIO.output(self.trig, GPIO.HIGH)
        time.sleep(0.00002)                   # 20µs 트리거 (JSN-SR04T는 10µs 이상 필요)
        GPIO.output(self.trig, GPIO.LOW)

        deadline = time.perf_counter() + timeout
        while not GPIO.input(self.echo):
            if time.perf_counter() > deadline:
                return None
        start = time.perf_counter()
        while GPIO.input(self.echo):
            if time.perf_counter() - start > timeout:
                return None
        return (time.perf_counter() - start) * SPEED_OF_SOUND_CM_PER_S / 2

    def close(self):
        self.GPIO.cleanup((self.trig, self.echo))


class FakeSensor:
    """하드웨어 없이 서버 연동을 확인할 때 쓴다. 가끔 측정 실패를 섞는다."""

    def __init__(self, base_cm=120.0):
        self.base_cm = base_cm

    def read_once(self, timeout=0.04):
        if random.random() < 0.05:
            return None
        return self.base_cm + random.uniform(-1.0, 1.0)

    def close(self):
        pass


def measure(sensor, cfg, gap=0.06):
    """samples회 측정해 유효값의 중앙값(cm, 소수 1자리). 유효값이 min_valid_samples보다 적으면 None."""
    valid = []
    for i in range(cfg.samples):
        value = sensor.read_once()
        if value is not None and cfg.min_cm <= value <= cfg.max_cm:
            valid.append(value)
        if i < cfg.samples - 1:
            time.sleep(gap)                   # JSN-SR04T는 측정 간 50ms 이상 간격 필요
    if len(valid) < cfg.min_valid_samples:
        return None
    return round(statistics.median(valid), 1)


# ---------------------------------------------------------------------------
# 미전송 큐 (SQLite, 재부팅 후에도 유지)
# ---------------------------------------------------------------------------

class Queue:
    def __init__(self, path, max_size):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS pending ('
                        'measured_at TEXT PRIMARY KEY, distance_cm REAL)')
        self.db.commit()
        self.max_size = max_size

    def add(self, measured_at, distance_cm):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO pending VALUES (?, ?)', (measured_at, distance_cm))
            overflow = self.count() - self.max_size
            if overflow > 0:
                self.db.execute('DELETE FROM pending WHERE measured_at IN ('
                                'SELECT measured_at FROM pending ORDER BY measured_at LIMIT ?)', (overflow,))
                log.warning('미전송 큐가 %d건을 넘어 오래된 %d건을 버렸습니다', self.max_size, overflow)

    def peek(self, limit):
        return self.db.execute('SELECT measured_at, distance_cm FROM pending '
                               'ORDER BY measured_at LIMIT ?', (limit,)).fetchall()

    def remove(self, measured_ats):
        measured_ats = list(measured_ats)
        with self.db:
            for i in range(0, len(measured_ats), 500):  # SQLite 변수 개수 제한 회피
                chunk = measured_ats[i:i + 500]
                self.db.execute(f'DELETE FROM pending WHERE measured_at IN ({",".join("?" * len(chunk))})', chunk)

    def count(self):
        return self.db.execute('SELECT COUNT(*) FROM pending').fetchone()[0]

    def close(self):
        self.db.close()


# ---------------------------------------------------------------------------
# 전송
# ---------------------------------------------------------------------------

def post_batch(cfg, items):
    """(status, headers, body_text). 네트워크 오류는 예외로 올린다."""
    payload = {
        'site_id': cfg.site_id,
        # 측정 실패도 distance_cm 키를 null로 명시한다 (서버가 키 누락을 400으로 거절)
        'readings': [{'measured_at': t, 'distance_cm': d} for t, d in items],
    }
    request = urllib.request.Request(
        cfg.readings_url,
        data=json.dumps(payload, allow_nan=False).encode(),
        headers={'Content-Type': 'application/json', 'X-API-Key': cfg.api_key,
                 'User-Agent': 'shopsense-sensorpost/1.0'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.http_timeout) as response:
            return response.status, response.headers, response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode('utf-8', 'replace')


def _item_errors(body):
    """400 응답에서 항목별 오류 {인덱스: 오류}. 항목 오류가 아니면 None."""
    try:
        errors = json.loads(body).get('readings')
    except (ValueError, AttributeError):
        return None
    if not isinstance(errors, dict):
        return None
    try:
        return {int(index): error for index, error in errors.items()}
    except ValueError:
        return None


class Sender:
    CONFIG_ERROR_RETRY_SEC = 300
    MAX_BACKOFF_SEC = 300

    def __init__(self, cfg, queue, post=post_batch, clock=time.monotonic):
        self.cfg, self.queue, self.post, self.clock = cfg, queue, post, clock
        self.next_attempt_at = 0.0
        self.failures = 0

    def _pause(self, seconds):
        self.next_attempt_at = self.clock() + seconds

    def _backoff(self, reason):
        self.failures += 1
        delay = min(self.MAX_BACKOFF_SEC, 10 * 2 ** (self.failures - 1))
        self._pause(delay)
        log.warning('전송 실패(%s). %d초 후 재시도, 미전송 %d건', reason, delay, self.queue.count())

    def flush(self):
        """큐를 최대 batches_per_cycle 배치만큼 보낸다. 대기 중이면 아무것도 하지 않는다."""
        if self.clock() < self.next_attempt_at:
            return
        sent_batches = 0
        while sent_batches < self.cfg.batches_per_cycle:
            items = self.queue.peek(BATCH_SIZE)
            if not items:
                return
            sent_batches += 1
            try:
                status, headers, body = self.post(self.cfg, items)
            except (urllib.error.URLError, OSError) as e:  # 타임아웃·연결 거부·DNS 등
                self._backoff(f'네트워크 오류: {e}')
                return

            if 200 <= status < 300:
                self.queue.remove(t for t, _ in items)
                self.failures = 0
                log.debug('전송 %d건: %s', len(items), body)
                continue

            if status == 429:
                retry_after = _int_or(headers.get('Retry-After') if headers else None, 60)
                self._pause(retry_after)
                log.warning('서버 rate limit(429). %d초 후 재시도, 미전송 %d건', retry_after, self.queue.count())
                return

            if status == 400:
                errors = _item_errors(body) or {}
                bad = [(items[i], error) for i, error in sorted(errors.items()) if 0 <= i < len(items)]
                if bad:
                    # 데이터가 잘못된 항목만 버린다. 나머지는 이어서 다시 보낸다.
                    for (t, d), error in bad:
                        log.error('서버가 거절한 측정값을 버립니다: measured_at=%s distance_cm=%s 오류=%s', t, d, error)
                    self.queue.remove(t for (t, _), _ in bad)
                    continue

            if 400 <= status < 500:
                # 키·site_id·URL 같은 요청/설정 문제. 데이터는 정상이므로 보관하고 천천히 재시도한다.
                self._pause(self.CONFIG_ERROR_RETRY_SEC)
                log.error('요청이 거절되었습니다(HTTP %d). 설정(%s의 SERVER_URL/API_KEY/SITE_ID)을 확인하세요. '
                          '%d초 후 재시도, 미전송 %d건. 응답: %s', status, self.cfg.config_path,
                          self.CONFIG_ERROR_RETRY_SEC, self.queue.count(), body[:300])
                return

            self._backoff(f'HTTP {status}')
            return


def _int_or(value, default):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def wait_for_ntp(timeout_sec):
    """NTP 동기화를 기다린다. measured_at이 틀어지면 서버가 미래 시각을 거절하거나 과거로 잘못 기록된다."""
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            synced = subprocess.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                                    capture_output=True, text=True, timeout=5).stdout.strip() == 'yes'
        except (OSError, subprocess.SubprocessError):
            log.warning('timedatectl을 실행할 수 없어 NTP 동기화를 확인하지 못했습니다')
            return
        if synced:
            return
        if time.monotonic() >= deadline:
            log.warning('NTP 동기화가 %d초 내에 확인되지 않았습니다. 측정 시각이 틀릴 수 있습니다', timeout_sec)
            return
        time.sleep(5)


def now_kst():
    return datetime.datetime.now(KST).replace(microsecond=0).isoformat()  # 예: 2026-10-08T10:15:30+09:00


def run(cfg, sensor, once=False):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    queue = Queue(cfg.queue_path, cfg.max_queue)
    sender = Sender(cfg, queue)
    pending = queue.count()
    log.info('시작: site_id=%s 서버=%s 주기=%ss 미전송 %d건', cfg.site_id, cfg.readings_url, cfg.interval_sec, pending)

    next_tick = time.monotonic()
    try:
        while not stop.is_set():
            measured_at = now_kst()
            distance = measure(sensor, cfg)
            queue.add(measured_at, distance)
            log.info('측정 %s distance_cm=%s', measured_at, distance)
            sender.flush()
            if once:
                break
            next_tick += cfg.interval_sec
            now = time.monotonic()
            if next_tick < now:          # 전송이 오래 걸려 주기를 놓쳤으면 밀린 주기는 건너뛴다
                next_tick = now
            stop.wait(next_tick - now)
    finally:
        sensor.close()
        log.info('종료: 미전송 %d건 (다음 실행 때 이어서 보냄)', queue.count())
        queue.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--fake', action='store_true', help='실제 센서 대신 가짜 값 사용')
    parser.add_argument('--once', action='store_true', help='1회 측정·전송 후 종료')
    parser.add_argument('--config', default=os.environ.get('SHOPSENSE_ENV', CONFIG_PATH))
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    # systemd(journald)가 시각을 붙이므로 로그에는 시각을 넣지 않는다
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(levelname)s %(message)s')
    cfg = load_config(args.config)
    if not args.fake:
        wait_for_ntp(cfg.ntp_wait_sec)
    sensor = FakeSensor() if args.fake else UltrasonicSensor(cfg.trig_pin, cfg.echo_pin)
    run(cfg, sensor, once=args.once)


if __name__ == '__main__':
    main()

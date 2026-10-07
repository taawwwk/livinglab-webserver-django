"""sensor_post.py 단위 테스트 (하드웨어·외부 서버 불필요).

    cd shopsense/pi && python3 -m unittest -v test_sensor_post
"""
import http.server
import json
import os
import tempfile
import threading
import unittest
import urllib.error

import sensor_post as sp


def make_cfg(tmp, **overrides):
    values = dict(server_url='http://127.0.0.1:1', api_key='k', site_id=1,
                  queue_path=os.path.join(tmp, 'q.db'), batches_per_cycle=3)
    values.update(overrides)
    return sp.Config(**values)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ScriptedPost:
    """서버 대신 정해 둔 응답을 차례로 돌려주고, 받은 배치를 기록한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cfg, items):
        self.calls.append(list(items))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        status, headers, body = response
        return status, headers or {}, body if isinstance(body, str) else json.dumps(body)


class SequenceSensor:
    def __init__(self, values):
        self.values = list(values)

    def read_once(self, timeout=0.04):
        return self.values.pop(0)

    def close(self):
        pass


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = make_cfg(self.tmp)

    def measure(self, values):
        return sp.measure(SequenceSensor(values), self.cfg, gap=0)

    def test_median_of_valid_samples(self):
        self.assertEqual(self.measure([120.0, 121.0, 119.0, 500.0, 120.4]), 120.4)
        # 실패·블라인드 존(<20)·범위 초과(>600)는 빼고 중앙값
        self.assertEqual(self.measure([None, 10.0, 130.0, 700.0, 132.0]), None)   # 유효 2개 < 3
        self.assertEqual(self.measure([None, 130.0, 131.0, 700.0, 132.0]), 131.0)

    def test_all_failed_is_none(self):
        self.assertIsNone(self.measure([None] * 5))


class ConfigTests(unittest.TestCase):
    def test_env_file_and_override(self):
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False) as f:
            f.write('# comment\nSERVER_URL=http://203.255.81.72:10021/\nAPI_KEY="abc"\nSITE_ID=3\n'
                    'TRIG_PIN=17   # BCM\nINTERVAL_SEC=5\n')
        cfg = sp.load_config(f.name, environ={'SITE_ID': '4'})
        self.assertEqual((cfg.api_key, cfg.site_id, cfg.trig_pin, cfg.echo_pin, cfg.interval_sec),
                         ('abc', 4, 17, 24, 5.0))
        self.assertEqual(cfg.readings_url, 'http://203.255.81.72:10021/api/shop/readings/')

    def test_missing_required(self):
        with self.assertRaises(SystemExit):
            sp.load_config('/nonexistent', environ={'SERVER_URL': 'http://x'})


class QueueTests(unittest.TestCase):
    def test_persists_across_reopen_and_trims_oldest(self):
        path = os.path.join(tempfile.mkdtemp(), 'sub', 'q.db')
        q = sp.Queue(path, max_size=3)
        for i in range(5):
            q.add(f'2026-10-08T10:00:0{i}+09:00', None if i == 2 else 100.0 + i)
        q.add('2026-10-08T10:00:04+09:00', 999.0)  # 같은 시각은 무시
        q.close()
        q = sp.Queue(path, max_size=3)
        self.assertEqual(q.peek(10), [('2026-10-08T10:00:02+09:00', None),
                                      ('2026-10-08T10:00:03+09:00', 103.0),
                                      ('2026-10-08T10:00:04+09:00', 104.0)])


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = make_cfg(self.tmp)
        self.queue = sp.Queue(self.cfg.queue_path, self.cfg.max_queue)
        self.clock = FakeClock()

    def fill(self, n):
        # 한 트랜잭션으로 넣는다 (건마다 커밋하면 fsync가 n번 일어나 느린 디스크에서 오래 걸린다)
        with self.queue.db:
            self.queue.db.executemany('INSERT OR IGNORE INTO pending VALUES (?, ?)', [
                (f'2026-10-08T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+09:00', 100.0) for i in range(n)])

    def sender(self, post):
        return sp.Sender(self.cfg, self.queue, post=post, clock=self.clock)

    def test_success_splits_into_1000_batches(self):
        self.fill(2500)
        post = ScriptedPost((201, None, {'created': 1}))
        self.sender(post).flush()
        self.assertEqual([len(c) for c in post.calls], [1000, 1000, 500])
        self.assertEqual(self.queue.count(), 0)

    def test_batches_per_cycle_limit(self):
        self.fill(3500)
        post = ScriptedPost((200, None, {'created': 0, 'skipped': 1000}))
        self.sender(post).flush()
        self.assertEqual(len(post.calls), 3)
        self.assertEqual(self.queue.count(), 500)

    def test_item_errors_drop_only_bad_items(self):
        self.fill(5)
        bad_body = {'readings': {'3': {'distance_cm': ['too large']}, '1': {'measured_at': ['bad']}}}
        post = ScriptedPost((400, None, bad_body), (201, None, {}))
        with self.assertLogs('sensorpost', 'ERROR') as logs:
            self.sender(post).flush()
        self.assertEqual(len(logs.output), 2)
        self.assertEqual([len(c) for c in post.calls], [5, 3])   # 나쁜 2건을 빼고 바로 재전송
        self.assertEqual(self.queue.count(), 0)

    def test_config_errors_keep_data_and_pause(self):
        for status, body in ((401, {'detail': 'bad key'}), (403, {}), (404, '<html>'),
                             (400, {'detail': 'site_id=9 없음'}), (400, {'readings': {'99': ['x']}})):
            with self.subTest(status=status, body=body):
                self.queue.remove(t for t, _ in self.queue.peek(10000))
                self.fill(3)
                post = ScriptedPost((status, None, body))
                sender = self.sender(post)
                with self.assertLogs('sensorpost', 'ERROR'):
                    sender.flush()
                self.assertEqual(self.queue.count(), 3)
                self.assertEqual(sender.next_attempt_at, self.clock.now + 300)
                sender.flush()                     # 대기 중에는 보내지 않는다
                self.assertEqual(len(post.calls), 1)

    def test_429_respects_retry_after(self):
        self.fill(2)
        post = ScriptedPost((429, {'Retry-After': '17'}, {'detail': 'throttled'}), (201, None, {}))
        sender = self.sender(post)
        sender.flush()
        self.assertEqual((self.queue.count(), sender.next_attempt_at), (2, self.clock.now + 17))
        self.clock.now += 17
        sender.flush()
        self.assertEqual(self.queue.count(), 0)

    def test_5xx_and_network_errors_back_off(self):
        self.fill(2)
        post = ScriptedPost((502, None, 'bad gateway'), urllib.error.URLError('refused'),
                            TimeoutError('timed out'), (201, None, {}))
        sender = self.sender(post)
        delays = []
        for _ in range(3):
            sender.flush()
            delays.append(sender.next_attempt_at - self.clock.now)
            self.clock.now = sender.next_attempt_at
        self.assertEqual(delays, [10, 20, 40])
        self.assertEqual(self.queue.count(), 2)
        sender.flush()
        self.assertEqual((self.queue.count(), sender.failures), (0, 0))


class HttpPayloadTests(unittest.TestCase):
    """실제 HTTP로 보내서 헤더·JSON 형식을 확인한다."""

    def test_payload_format(self):
        received = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received['path'] = self.path
                received['key'] = self.headers['X-API-Key']
                received['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b'{"created": 2, "skipped": 0}')

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cfg = make_cfg(tempfile.mkdtemp(), server_url=f'http://127.0.0.1:{server.server_port}', site_id=7)
            measured_at = sp.now_kst()
            status, _, _ = sp.post_batch(cfg, [(measured_at, 123.4), (measured_at, None)])
        finally:
            server.shutdown()
        self.assertEqual(status, 201)
        self.assertEqual(received['path'], '/api/shop/readings/')
        self.assertEqual(received['key'], 'k')
        self.assertEqual(received['body']['site_id'], 7)
        self.assertEqual(received['body']['readings'][1], {'measured_at': measured_at, 'distance_cm': None})
        self.assertTrue(measured_at.endswith('+09:00'))
        self.assertRegex(measured_at, r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$')


if __name__ == '__main__':
    unittest.main()

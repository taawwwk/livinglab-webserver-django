# shopsense — 대학가 가게 침수 실증 수위센서 API

현장 라즈베리파이가 초음파 수위센서(JSN-SR04T) 값을 10초마다 보내면 저장하고, 조회·상태 판정을 제공한다.
기존 `sensor`, `opensrc` 앱과 테이블은 건드리지 않는 독립 앱이다.

## 데이터 모델

| 테이블 | 내용 |
|---|---|
| `shopsense_site` (`ShopSite`) | 설치 장소. `baseline_cm`(센서→바닥 거리, 줄자 실측), `warn_level_cm`, `danger_level_cm`(비우면 판정 안 함) |
| `shopsense_reading` (`WaterLevelReading`) | 측정값. `measured_at`(Pi 측정 시각), `received_at`(서버 수신), `distance_cm`(실패 시 null) |

- **수위 `level_cm = baseline_cm - distance_cm`** 은 저장하지 않고 조회할 때 계산한다. baseline을 고치면 과거 값의 수위도 함께 바뀐다.
- `(site, measured_at)` 유니크 제약으로 재전송은 중복 저장되지 않는다. 이 제약의 인덱스가 기간 조회에도 쓰인다.
- 상태: 수위 ≥ danger → `danger`, ≥ warn → `warn`, 그 외 `normal`. 최신 측정이 실패(null)이거나 데이터가 없으면 `no_data`.

## 인증

- 헤더 `X-API-Key: <키>`. 키는 환경변수 `SHOP_API_KEYS`(콤마 구분)에서만 읽는다. 비어 있으면 모든 요청 거부.
- 키가 없거나 틀리면 **401**.
- 쓰기는 `DeviceAPIKeyAuthentication`, 조회는 `ViewerAuthentication`([authentication.py](authentication.py)).
  지금은 둘 다 같은 키를 쓴다. 사장님 로그인을 붙일 때는 `ViewerAuthentication`만 바꾸면 된다.

## Rate limit

- `POST /api/shop/readings/`만 **API 키당 `SHOP_POST_RATE`(기본 `60/min`)** 로 제한한다([throttling.py](throttling.py)). 초과하면 **429**와 `Retry-After`(초) 헤더.
- 401로 끝난 요청(키 없음·오답)은 세지 않는다. 400으로 거절된 요청은 센다(잘못된 데이터를 계속 보내는 장비도 막기 위해).
- 파이 1대는 평소 분당 6회, 밀린 데이터 재전송 중에도 분당 최대 약 24회라 60회 안쪽이다.
  **여러 대가 같은 키를 쓰면 한도를 나눠 쓰게 되므로 장비마다 다른 키**를 `SHOP_API_KEYS`에 넣는 것을 권장한다.
- 카운터는 컨테이너 안 파일 캐시(`/tmp/shopsense_throttle`)에 있어 gunicorn worker 4개가 한도를 공유한다. 컨테이너를 재생성하면 초기화된다.

## API

### `POST /api/shop/readings/` — 측정값 저장
```json
{"site_id": 1, "measured_at": "2026-10-08T10:15:30+09:00", "distance_cm": 123.4}
```
```json
{"site_id": 1, "readings": [
  {"measured_at": "2026-10-08T10:15:30+09:00", "distance_cm": 123.4},
  {"measured_at": "2026-10-08T10:15:40+09:00", "distance_cm": null}
]}
```
- `measured_at`: ISO 8601, **타임존 필수**. 타임존이 없으면 400. 서버 시각보다 5분 넘게 미래여도 400(NTP 이상).
- `distance_cm`: 0~1000 또는 `null`(측정 실패). **키는 반드시 포함**해야 한다. 범위 밖·NaN은 400.
- 배치는 1~1000건. 한 건이라도 잘못되면 전체 400이고 아무것도 저장하지 않는다.
- 응답: `{"site_id": 1, "created": 2, "skipped": 0}`. 새로 저장된 게 있으면 **201**, 전부 중복이면 **200**.
  이미 있는 `(site, measured_at)`은 오류 없이 `skipped`로 센다.
- 새로 저장된 값 중 가장 최근 값이 danger면 WARNING 로그를 남긴다([alerts.py](alerts.py)).

### `GET /api/shop/readings/?site_id=1&from=...&to=...&order=desc&limit=1000`
- `from`/`to`: `2026-10-08` 또는 ISO 시각. 타임존이 없으면 KST로 본다. 날짜만 준 `to`는 그날 끝까지 포함한다.
- `order`: `desc`(기본, 최신순) / `asc`. `limit`: 기본 1000, 최대 10000.
- 각 항목: `measured_at`, `received_at`, `distance_cm`, `level_cm`. 시각은 `+09:00` 표기.

### `GET /api/shop/sites/<id>/latest/`
```json
{"site": {"id": 1, "name": "대학가 가게 1호", "baseline_cm": 150.0, "warn_level_cm": 30.0, "danger_level_cm": 60.0},
 "status": "normal", "stale": false, "last_received_at": "2026-10-08T10:15:31+09:00",
 "reading": {"measured_at": "...", "received_at": "...", "distance_cm": 123.4, "level_cm": 26.6},
 "last_valid_reading": {"...": "최신값이 측정 실패일 때 참고용 마지막 정상값"}}
```
- `stale`: 마지막 수신 후 5분 이상 지났으면(또는 수신 기록이 없으면) `true`.

### `GET /api/shop/health/` — 인증 없음
DB 연결까지 확인한다. 정상이면 200 `{"status": "ok"}`, DB 장애면 503.

## 운영 명령

```bash
# 10분 넘게 수신이 없는 설치 장소를 WARNING 로그 + 표준출력으로 보고
docker exec livinglab_web python manage.py check_stale_sites --minutes 10
```
호스트 crontab 예시 (5분마다):
```
*/5 * * * * docker exec livinglab_web python manage.py check_stale_sites --minutes 10 >> /mnt/storage/livinglab/logs/shopsense_stale.log 2>&1
```

## 배포

코드가 이미지에 COPY되는 구조라 **코드 변경은 재빌드 + 컨테이너 재생성**이 필요하다.
마이그레이션은 web 컨테이너 시작 시(`python manage.py migrate && gunicorn ...`) 자동 실행된다.

```bash
cd /mnt/storage/Workspace/livinglab-webserver-django

# 1) .env에 API 키 추가 (git 미추적 파일)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # 키 생성
echo 'SHOP_API_KEYS=<생성한 키>' >> .env

# 2) web만 재빌드·재생성 (db, scheduler는 그대로). 수 초간 기존 센서 수신이 끊긴다.
docker compose build web
docker compose up -d --no-deps web

# 3) 마이그레이션 적용 확인
docker compose exec web python manage.py showmigrations shopsense
```

| 변경 | 필요한 작업 |
|---|---|
| 코드 변경 (이번 배포 포함) | `build web` + `up -d --no-deps web` |
| `SHOP_API_KEYS`, `SHOP_POST_RATE` 변경 | `up -d --no-deps web` (재빌드 불필요). **`docker compose restart`는 .env를 다시 읽지 않으니 쓰지 말 것** |
| 설치 장소 등록, baseline·임계값 수정 | `/admin/` → 설치 장소. 재시작 불필요 |
| cron 등록, `check_stale_sites` 실행 | 재시작 불필요 |

### 공개 주소 사용 시 주의
파이는 공개 주소(`http://203.255.81.72:10021`)로 보낸다. 호스트 nginx가 `/api/shop/`을 그대로 Django로 넘기므로 인터넷 어디서나 접근할 수 있다.
- 무단 쓰기는 API 키 + 키당 rate limit으로 막는다.
- **HTTP(평문)이라 API 키가 네트워크 경로상에서 그대로 보인다.** 가게 Wi-Fi·통신사 구간에서 키가 노출되면 가짜 측정값을 넣어 알람을 오작동시킬 수 있다.
  장비마다 다른 키를 써서 유출 시 그 키만 빼면 되게 하고, 가능하면 nginx에 TLS(HTTPS)를 붙이는 것을 권장한다.

## 배포 후 검증 (curl)

```bash
BASE=http://203.255.81.72:10021     # 파이가 쓰는 공개 주소 (서버 안에서는 http://127.0.0.1:10021)
KEY=<SHOP_API_KEYS 중 하나>

# 헬스체크 (키 없음)
curl -s $BASE/api/shop/health/

# 단건
curl -s -X POST $BASE/api/shop/readings/ \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"site_id\": 1, \"measured_at\": \"$(date --iso-8601=seconds)\", \"distance_cm\": 123.4}"

# 배치 (측정 실패 null 포함)
curl -s -X POST $BASE/api/shop/readings/ \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"site_id\": 1, \"readings\": [
        {\"measured_at\": \"$(date --iso-8601=seconds -d '-20 sec')\", \"distance_cm\": 123.0},
        {\"measured_at\": \"$(date --iso-8601=seconds -d '-10 sec')\", \"distance_cm\": null}]}"

# 최신값 + 상태
curl -s -H "X-API-Key: $KEY" $BASE/api/shop/sites/1/latest/

# 기간 조회 (시간순 20건)
curl -s -H "X-API-Key: $KEY" "$BASE/api/shop/readings/?site_id=1&from=$(date +%F)&order=asc&limit=20"
```
같은 단건 요청을 다시 보내면 `{"created": 0, "skipped": 1}`(200)이 나와야 한다.
서버 자신은 공유기 헤어핀 NAT가 안 돼 공개 주소로 접속되지 않는다. 서버에서 확인할 때는 `BASE=http://127.0.0.1:10021`.

## 라즈베리파이 클라이언트 ([pi/](pi/))

| 파일 | 설치 위치 |
|---|---|
| [pi/sensor_post.py](pi/sensor_post.py) | `/opt/shopsense/sensor_post.py` |
| [pi/sensorpost.service](pi/sensorpost.service) | `/etc/systemd/system/sensorpost.service` |
| [pi/shopsense.env.example](pi/shopsense.env.example) | `/etc/shopsense.env` (SERVER_URL, API_KEY, SITE_ID) |

### 배선 (JSN-SR04T, BCM 번호)
| 센서 | 파이 |
|---|---|
| 5V | 5V (2번 핀) |
| GND | GND (6번 핀) |
| Trig | GPIO23 (16번 핀) — 3.3V 출력으로 트리거 가능 |
| Echo | **분압 후** GPIO24 (18번 핀) |

**Echo는 5V를 출력한다. 그대로 연결하면 GPIO(3.3V)가 손상된다.** 1kΩ(Echo 쪽) / 2kΩ(GND 쪽) 분압 등으로 3.3V 이하로 낮춘다.

### GPIO 라이브러리 (파이 5)
- 기존 `RPi.GPIO`(`python3-rpi.gpio`)는 **파이 5에서 동작하지 않는다**(GPIO가 RP1 칩으로 바뀜).
- **`python3-rpi-lgpio`** 가 같은 `import RPi.GPIO` 이름으로 lgpio 기반 호환 모듈을 제공한다. 이 코드가 쓰는 `setmode/setup/output/input/cleanup`은 모두 지원된다.
- 파이 4 이하에서도 동작하므로 기종에 상관없이 이것으로 통일하는 것을 권장한다. 두 패키지는 충돌하므로 기존 것을 먼저 지운다.
  ```bash
  sudo apt remove -y python3-rpi.gpio
  sudo apt install -y python3-rpi-lgpio
  ```
- 에코 시간은 파이썬 폴링으로 재므로 해상도는 약 1cm 수준이다. 수위 판정에는 충분하다.

### 설치
```bash
# 전용 계정 (gpio 그룹으로 /dev/gpiochip 접근)
sudo useradd -r -s /usr/sbin/nologin -G gpio shopsense

sudo install -d /opt/shopsense
sudo install -m 755 sensor_post.py /opt/shopsense/
sudo install -m 640 -o root -g shopsense shopsense.env.example /etc/shopsense.env
sudo nano /etc/shopsense.env          # API_KEY, SITE_ID 입력
sudo install -d -o shopsense -g shopsense /var/lib/shopsense   # 미전송 큐 (서비스가 시작되면 자동 생성되지만 수동 테스트용)

# 연결 확인: 가짜 값이 실제 가게 데이터에 섞이지 않도록 admin에서 만든 테스트용 site로 보낸다
sudo -u shopsense env SITE_ID=<테스트용 site id> QUEUE_PATH=/tmp/shopsense-test.db \
     python3 /opt/shopsense/sensor_post.py --fake --once
# 실제 센서 1회 측정·전송 (운영 site)
sudo -u shopsense python3 /opt/shopsense/sensor_post.py --once

sudo install -m 644 sensorpost.service /etc/systemd/system/
sudo systemctl enable --now systemd-time-wait-sync   # NTP 동기화 전에는 시작하지 않게
sudo systemctl daemon-reload
sudo systemctl enable --now sensorpost
journalctl -u sensorpost -f
```
환경변수(`SITE_ID=...` 등)는 `/etc/shopsense.env`보다 우선한다.

### 동작
- 10초마다 5회 측정 → 유효값(20~600cm) 중앙값. 유효값이 3개 미만이면 **`distance_cm: null`을 명시해서** 보낸다.
- `measured_at`은 KST(`+09:00`) ISO 8601, 초 단위.
- 측정값은 먼저 SQLite 큐(`/var/lib/shopsense/queue.db`, 재부팅 후 유지)에 넣고 1000건 단위 배치로 보낸다.
  주기마다 최대 3배치(3000건)까지 보내므로 하루치 밀린 데이터(8,640건)는 약 30초 안에 따라잡는다. 큐는 30일치를 넘으면 오래된 것부터 버린다.

| 서버 응답 | 클라이언트 동작 |
|---|---|
| 2xx (201, 200) | 성공. 큐에서 삭제 |
| 400 + 항목별 오류 | **그 항목만 버리고 ERROR 로그.** 나머지는 바로 재전송 |
| 429 | 보관. `Retry-After`만큼 기다렸다가 재시도 |
| 그 밖의 4xx (401/403 키 오류, 404 URL 오류, site_id 오류 등) | **보관.** 5분마다 재시도하며 ERROR 로그. 설정을 고치면 밀린 데이터가 그대로 올라간다 |
| 5xx, 네트워크 오류 | 보관. 10초 → 20초 → … 최대 5분 간격으로 재시도 |

- NTP: 시작할 때 `timedatectl`로 동기화를 최대 2분 기다린다. 파이 시계가 5분 넘게 앞서면 서버가 해당 측정값을 400으로 거절하므로 버려진다.
- JSN-SR04T는 약 20~25cm 이내를 재지 못한다(블라인드 존). 물이 센서 가까이 차오르면 측정 실패(null)가 이어질 수 있으니,
  설치 높이를 정할 때 위험 수위가 블라인드 존 밖에 있도록 한다.

### 클라이언트 테스트
하드웨어 없이 측정 중앙값, 큐, 배치 분할, 응답별 처리를 확인한다.
```bash
cd shopsense/pi && python3 -m unittest -v test_sensor_post
```

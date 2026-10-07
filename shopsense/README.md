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
| `SHOP_API_KEYS` 추가·교체 | `up -d --no-deps web` (재빌드 불필요). **`docker compose restart`는 .env를 다시 읽지 않으니 쓰지 말 것** |
| 설치 장소 등록, baseline·임계값 수정 | `/admin/` → 설치 장소. 재시작 불필요 |
| nginx 접근 제한, cron 등록, `check_stale_sites` 실행 | 재시작 불필요 |

### 외부 노출 제한 (권장, sudo 필요)
호스트 nginx(`/etc/nginx/sites-available/livinglab-proxy.conf`)가 `0.0.0.0:10021`의 `location /` 전체를 Django로 넘기므로,
**`/api/shop/`은 공인 IP(203.255.81.72:10021)로도 열려 있다.** Tailscale과 로컬에서만 접근하게 하려면 `location /` 위에 추가한다.
```nginx
location /api/shop/ {
    allow 100.64.0.0/10;   # Tailscale
    allow 127.0.0.1;
    allow ::1;
    deny  all;

    proxy_pass http://127.0.0.1:8081;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 배포 후 검증 (curl)

```bash
BASE=http://100.99.10.63:10021      # 서버 Tailscale IP
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

## 라즈베리파이 쪽 구현 시 주의
- 시각은 타임존 포함으로 보낸다. Python: `datetime.now().astimezone().isoformat()` (`datetime.utcnow().isoformat()`은 타임존이 없어 400).
- 응답 200과 201은 모두 성공이다. 실패하면 **같은 `measured_at`으로 재전송**하면 된다(중복 저장 안 됨).
- 네트워크가 끊긴 동안은 로컬에 쌓았다가 배치(최대 1000건)로 보낸다.
- JSN-SR04T는 약 20~25cm 이내가 측정 불가(블라인드 존)다. 물이 센서 가까이 차오르면 측정 실패(null)가 이어질 수 있으니, 설치 높이를 정할 때 위험 수위가 블라인드 존 밖에 있도록 한다.

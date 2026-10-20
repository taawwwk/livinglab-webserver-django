# 오픈소스 수업 7주차 데이터 수집 · 8주차 중간평가 (opensrc 앱)

강의자료 "데이터 수집 및 중간 평가"에서 학생들에게 안내한 규칙을 서버에 구현한 내용이다.
모든 시각은 `Asia/Seoul` 기준이다 (`settings.TIME_ZONE`).

## URL

| URL | 용도 | 접근 |
|---|---|---|
| `POST /sensor/opensrc/upload/` | 학생 앱 업로드 (5주차와 같은 API, `team`·`rssi` 추가) | 팀 key |
| `GET /sensor/opensrc/check/` | **중간평가 대시보드** (센서 ON/OFF, 45칸 그리드, 팀 필터, 팀별 점수) | 공개 |
| `GET /sensor/opensrc/api/midterm/` | 대시보드가 쓰는 JSON | 공개 |
| `GET /sensor/opensrc/midterm_scores.csv` | TA용 팀별 점수 CSV (`?format=long` 이면 칸 단위 한 행) | admin 로그인(staff) |
| `GET /sensor/opensrc/week4/` | 예전 `check/` (4주차 수신 현황) | 공개 |
| `GET /sensor/opensrc/teams/` | 업로드 원본 데이터 표 | 공개 |
| `/admin/` → 오픈소스 실습 데이터 | 캠퍼스 센서 · 수집 날짜 · 시간대 배정 입력 | admin |

## upload API 변경 (기존 앱 호환)

- `team` (선택, 학생에게는 팀 번호 정수를 보내도록 안내): 정수 1~9. `"Team 3"`, `"3"`, `"3팀"` 도 받는다. **key가 가리키는 팀과 다르면 400**, 형식이 아니면 400.
  보내지 않으면 지금처럼 key로 팀을 정한다. 저장 시 `team_no` 컬럼에 정수로도 남긴다.
- `rssi` (선택): 정수 dBm. 없으면 **저장은 하되** `detail='rssi 없음'`, 응답에 `warning` 을 넣는다.
  채점에서는 rssi 가 없거나 0, −100~0 밖이면 유효 데이터가 아니다. −100~0 밖은 `status=out_of_range`.
- 그 밖의 필수 필드·응답 형식은 5주차와 같다.

## 테이블 병합

`opensrc_submission`(4주차 test/)과 `opensrc_team_submission`(5주차 upload/)을 `opensrc_submission` 하나로 합쳤다
(`opensrc/migrations/0003_midterm_merge_submissions.py`).

- 추가 컬럼: `source` (`test` / `upload`), `team_no` (정수, 4주차 행은 null), `rssi` (null 허용).
- 5주차 행은 `source='upload'` 로 복사되고 `team_no` 는 `'Team N'` 에서 채워진다. 복사 후 `opensrc_team_submission` 은 삭제된다.
- 되돌리면(`migrate opensrc 0002`) upload 행을 다시 `opensrc_team_submission` 으로 옮긴다.
- 4주차 조회 뷰(`week4/`, `api/latest`, `api/summary`, `export.csv`)는 `source='test'` 만, 팀 뷰(`teams/`, `data/` 등)는 `source='upload'` 만 본다.

## 설정 (admin에서 입력)

| 모델 | 내용 |
|---|---|
| 캠퍼스 센서 `CampusSensor` | 번호(1~5), BLE 기기명(`opensrc_team1`), BLE MAC(나중에 입력, 비우면 기기명으로만 대응), livinglab 센서 이름, 위치, 사용 여부 |
| 수집 날짜 `CollectionDay` | 하루 한 행. 대시보드 그리드의 열. 비어 있으면 배정표의 날짜를 쓴다 |
| 시간대 배정 `SlotAssignment` | 날짜 × 시작 시각(9~17) × 팀. (날짜, 시작 시각) 유일 |

환경변수(`livinglab/settings.py`): `OPENSRC_SLOT_START`/`OPENSRC_SLOT_END` (기본 9/18), `OPENSRC_SENSOR_ONLINE_MINUTES` (기본 10),
`OPENSRC_MIDTERM_FULL_SCORE` (10), `OPENSRC_MIDTERM_PENALTY` (2), `OPENSRC_MIDTERM_CACHE_SECONDS` (15).

## 센서 가동 판정과 이름 정규화

캠퍼스 센서는 WiFi로 `GET /sensor/sensing/?sensor=opensrc_teamN&...` 에 기온·CO2·IP를 올린다.
`sensor/views.py` 의 `normalize_sensor_name()` 은 이름에 `opensrc` 가 들어가면 숫자 추출을 하지 않고 소문자화만 한다
(안 그러면 `opensrc_team1` → `sensor 01` 로 연구실 센서와 섞인다). Pi 쪽 이름은 admin 의 "livinglab 센서 이름"과 같아야 한다.

- 실시간 ON/OFF: `sensor_sensor_data.sensing_time` 또는 `sensor_ip_db.time` 중 최근 수신이 `OPENSRC_SENSOR_ONLINE_MINUTES` 안이면 ON.
- 채점용 가동: 해당 1시간 칸 안에 두 테이블 중 어디든 수신이 1건이라도 있으면 그 칸에서 "가동".

## 칸 인정 로직 (`opensrc/grading.py`)

1. 가동 센서마다 담당 팀의 유효 데이터가 1건 이상 → **인정(초록)**. 미가동 센서는 요구 대상에서 제외.
2. 유효 데이터: `rssi` null·0 아님, −100~0; `lat`/`lon` null·0 아님. 서버 수신 시각(`received_at`) 기준으로 칸을 가른다.
3. 학생 데이터 → 센서 대응: 등록된 BLE MAC 일치, 또는 BLE device name 일치(대소문자·공백·기호 무시).
   번호만 같은 이름(`team3 sensor` 등 5주차 자기 팀 센서)은 캠퍼스 센서로 보지 않는다.
   iOS 는 MAC 대신 UUID 를 주므로 MAC 을 등록해도 기기명 일치는 계속 인정한다.
4. 가동 센서 중 유효 데이터가 없는 것이 있으면 **누락(빨강)**.
5. 유효 데이터가 2건 이상인데 위경도가 전부 같으면, 또는 가동 센서가 0대면 **검토 필요(노랑)** (자동 불인정 아님, TA 확인).
6. 아직 시작 전 칸은 **예정(회색)**, 진행 중인 칸은 **진행 중(하늘색)** 으로 현재까지의 상태를 보여준다.
7. 점수 = 10 − 2 × 누락 칸 (최저 0). 검토 필요 칸은 점수에서 인정으로 센다. 예정·진행 중 칸이 남아 있으면 "잠정".

## 테스트

호스트에 Django가 없으므로 web 이미지에 레포를 마운트해서 돌린다 (테스트 DB `test_livinglab_sensor` 가 운영 Postgres에 잠깐 생겼다 지워진다).

```bash
docker run --rm --user $(id -u):$(id -g) --network livinglab-webserver-django_livinglab_network \
  -v "$PWD":/app -e HOME=/tmp -e DB_HOST=db -e OPENSRC_HMAC_KEY=test \
  livinglab-webserver-django-web python manage.py test opensrc
```

### 샘플 데이터로 대시보드 확인 (임시 DB)

```bash
docker network create opensrc_demo
docker run -d --name opensrc_demo_db --network opensrc_demo -e POSTGRES_DB=livinglab_sensor \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres postgres:16-alpine
docker run -d --name opensrc_demo_web --network opensrc_demo --user $(id -u):$(id -g) -v "$PWD":/app \
  -e HOME=/tmp -e DB_HOST=opensrc_demo_db -e OPENSRC_HMAC_KEY=test -e DEBUG=True -p 127.0.0.1:18021:18021 \
  livinglab-webserver-django-web sh -c "python manage.py migrate && python manage.py seed_midterm && python manage.py runserver 0.0.0.0:18021"
# http://127.0.0.1:18021/sensor/opensrc/check/
docker rm -f opensrc_demo_web opensrc_demo_db && docker network rm opensrc_demo
```

`seed_midterm` 은 센서 5대, 오늘−2일부터 5일, 강의자료 예시대로 45칸 배정, 그리고 지난 칸마다
인정 / 누락(센서 하나 빠짐) / 검토 필요(위경도 고정) / 누락(rssi 없음) / 인정(기기명 오타·대문자) 시나리오를 돌려가며 넣는다.
`--start 2026-10-28` 로 날짜를 바꾸고, `--no-samples` 면 설정만, `--reset` 이면 이 명령이 넣은 것을 지운다.
샘플은 `sensor_sensor_data` 에도 들어가므로 **운영 DB에서는 `--no-samples` 만** 쓸 것.

### 업로드 수동 테스트

```bash
curl -X POST http://127.0.0.1:18021/sensor/opensrc/upload/ -H 'Content-Type: application/json' -d '{
  "key": "opensrc-team 3", "team": 3, "sensor": "opensrc_team1", "mac": "B8:27:EB:00:00:01", "sender": "phone-uuid",
  "temp": 21.5, "humidity": 48.2, "AQI": 1, "TVOC": 120, "eCO2": 450, "timestamp": 1792300000,
  "lat": 36.6271, "lon": 127.4580, "rssi": -67 }'
```

## 운영 배포 순서

1. 운영 DB 백업 (`opensrc_team_submission` 이 삭제된다).
2. `docker compose build web && docker compose up -d web` — 컨테이너 시작 시 `migrate` 가 실행된다.
3. admin 에서 캠퍼스 센서 5대(기기명·livinglab 이름·위치, MAC은 확인 후), 수집 날짜 5일, 시간대 배정 45칸 입력
   (`python manage.py seed_midterm --no-samples --start YYYY-MM-DD` 로 예시 배정을 넣고 admin에서 고쳐도 된다).
4. 캠퍼스 Pi 가 `sensor=opensrc_teamN` 으로 `/sensor/sensing/` 에 올리는지 확인 → 대시보드 센서 카드가 ON 이 되어야 한다.

# Campus Sensing Living Lab - Backend Server

캠퍼스 환경 센싱 데이터를 수집하고 관리하는 Django REST API 서버입니다.

## 프로젝트 구조

```
Livinglab/
├── docs/                    # 설계 문서
│   ├── api_spec.md
│   ├── architecture.md
│   ├── db_schema.md
│   └── db.txt
├── livinglab/               # Django 메인 설정
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── sensor/                  # 센서 앱
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
├── manage.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 기능

### 센서 데이터 수집
- **GET /sensor/sensing** - 센서 데이터 수신 및 저장
  - 파라미터: `mac`, `sensor`, `sender`, `mode`, `temp`, `co2`, `time`, `rssi` (선택)
  - 최신 상태 스냅샷 자동 업데이트

### 센서 IP 관리
- **GET /sensor/sensing?sensor=X&ip=Y** - 센서 IP 기록

### 센서 위치 관리
- **GET /sensor/sensing?sensor=X&latitude=Y&longitude=Z** - 센서 위치 설정

### 데이터 조회
- **GET /sensor/api/map** - 모든 센서의 최신 데이터 (위치 포함, 지도용)
- **GET /sensor/new/sensor/** - 최신 센서 데이터 조회
- **GET /sensor/new/ip** - 최신 센서 IP 조회

### 관리자 페이지
- **GET /admin/** - Django 관리자 인터페이스

## 설치 및 실행

### 개발 환경 (로컬)

1. Python 3.11+ 설치
2. 가상환경 생성 및 활성화
```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows
```

3. 의존성 설치
```bash
pip install -r requirements.txt
```

4. 데이터베이스 마이그레이션
```bash
python manage.py migrate
```

5. 관리자 계정 생성
```bash
python manage.py createsuperuser
```

6. 개발 서버 실행
```bash
python manage.py runserver
```

### Docker 환경 (프로덕션)

1. `.env.example` 파일을 `.env`로 복사하고 값 수정
```bash
cp .env.example .env
```

2. Docker Compose 실행
```bash
docker-compose up -d
```

3. 마이그레이션 및 관리자 생성 (첫 실행 시)
```bash
docker-compose exec web python manage.py createsuperuser
```

4. 서버 접속
- API: http://localhost:10021
- 관리자: http://localhost:10021/admin

## 데이터베이스 모델

### SensorData
원시 센서 데이터 로그 (39M+ 행)
- sensor: 센서 이름
- mac: 센서 MAC 주소
- receiver: 수신기 정보
- mode: 전송 방식 (direct/mobile)
- temperature: 온도 (℃)
- co2: 이산화탄소 농도 (ppm)
- sensing_time: 센싱 시간 (UNIX timestamp)
- rssi: BLE 신호 세기 (모바일 센싱만)

### SensorCheckDb
직접 통신 센서의 최신 상태 스냅샷
- sensor, temperature, co2, sensing_time

### MobileCheckDb
모바일 릴레이 센서의 최신 상태 스냅샷
- sensor, temperature, co2, rssi, receiver, sensing_time

### IpDb
센서 네트워크 IP 기록
- sensor, ip, time

### SensorLocation
센서 설치 위치
- sensor: 센서 이름 (고유)
- latitude: 위도
- longitude: 경도

## 하드웨어 및 스토리지

### 제약 조건
- **메인 NVMe**: 14GB (시스템 파일만)
- **고성능 4TB SSD**: `/mnt/storage/livinglab/` (DB, 로그)
- **2TB HDD**: `/mnt/backup/` (백업 데이터)

### Docker 볼륨 매핑
```
DB: /mnt/storage/livinglab/db_data
로그: /mnt/storage/livinglab/logs
정적: /mnt/storage/livinglab/staticfiles
백업: /mnt/backup/
```

## 포트 매핑

- **10021**: Django API 서버 (외부 노출)
- **5432**: PostgreSQL (내부만)
- **34253** → **10023**: SSH 관리 (외부)

## API 사용 예시

### 센서 데이터 전송
```bash
curl "http://203.255.81.72:10021/sensor/sensing?mac=D8:3A:DD:C1:88:C8&sensor=sensor%2001&sender=sensor&mode=direct&temp=28.5&co2=400&time=1720000000"
```

### IP 기록
```bash
curl "http://203.255.81.72:10021/sensor/sensing?sensor=sensor%2001&ip=172.30.128.46"
```

### 위치 설정
```bash
curl "http://203.255.81.72:10021/sensor/sensing?sensor=sensor%2001&latitude=36.626906&longitude=127.457722"
```

### 지도 데이터 조회
```bash
curl http://203.255.81.72:10021/sensor/api/map
```

## 문제 해결

### 마이그레이션 오류
```bash
python manage.py makemigrations
python manage.py migrate
```

### 데이터베이스 연결 실패
- PostgreSQL이 실행 중인지 확인
- `.env` 파일의 DB 설정 확인
- Docker 환경의 경우 네트워크 확인

### 포트 이미 사용 중
```bash
# 포트 8000 대신 다른 포트 사용
python manage.py runserver 8001
```

## 라이센스

Copyright 2024 - All Rights Reserved

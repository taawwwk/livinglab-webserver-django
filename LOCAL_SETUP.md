# 로컬 개발 환경 설정 (Anaconda)

## 📋 빠른 시작

### 자동 설정 (권장)
```bash
bash setup_local.sh
```

### 수동 설정
아래 단계를 따라 하세요.

---

## 단계별 설정

### 1️⃣ Conda 환경 생성
```bash
conda create -n livinglab python=3.11
conda activate livinglab
```

### 2️⃣ 의존성 설치
```bash
pip install -r requirements.txt
pip install django-extensions ipython
```

### 3️⃣ 데이터베이스 초기화
```bash
export DJANGO_SETTINGS_MODULE=local_settings
python manage.py migrate
```

### 4️⃣ 관리자 계정 생성 (선택)
```bash
python manage.py createsuperuser
```

예시:
```
Username: admin
Email: admin@example.com
Password: ****
Password (again): ****
```

### 5️⃣ 개발 서버 실행
```bash
export DJANGO_SETTINGS_MODULE=local_settings
python manage.py runserver
```

서버가 시작되면:
- 🌐 API: http://localhost:8000/sensor/
- 👤 관리자: http://localhost:8000/admin/
- 📊 데이터: http://localhost:8000/sensor/api/map (JSON)

---

## 자주 사용하는 명령어

### 셸 접근 (Django Shell)
```bash
export DJANGO_SETTINGS_MODULE=local_settings
python manage.py shell_plus
```

### 마이그레이션 생성
```bash
export DJANGO_SETTINGS_MODULE=local_settings
python manage.py makemigrations
```

### 데이터베이스 재설정
```bash
export DJANGO_SETTINGS_MODULE=local_settings
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

### API 테스트 (curl)
```bash
# 센서 데이터 전송
curl "http://localhost:8000/sensor/sensing?mac=AA:BB:CC:DD:EE:FF&sensor=test_sensor&sender=test&mode=direct&temp=25.5&co2=400&time=1720000000"

# 지도 데이터 조회
curl http://localhost:8000/sensor/api/map

# 최신 센서 데이터
curl http://localhost:8000/sensor/new/sensor/

# 최신 IP 목록
curl http://localhost:8000/sensor/new/ip
```

---

## 환경 변수 설정 (선택)

### macOS/Linux
```bash
# ~/.bashrc 또는 ~/.zshrc에 추가
export DJANGO_SETTINGS_MODULE=local_settings
```

### 또는 .env 파일 사용
```bash
# .env 파일 생성
echo "DJANGO_SETTINGS_MODULE=local_settings" > .env

# .env 로드 (수동)
set -a
source .env
set +a
```

---

## 데이터베이스

### 로컬 개발 (기본값)
- **엔진**: SQLite
- **파일**: `db.sqlite3` (프로젝트 루트)
- **장점**: 별도 설치 불필요, 간단한 테스트

### PostgreSQL 사용 (선택)
로컬에서도 PostgreSQL을 사용하려면:

```bash
# PostgreSQL 설치 (Homebrew - macOS)
brew install postgresql

# PostgreSQL 시작
brew services start postgresql

# 데이터베이스 생성
createdb livinglab_sensor
```

그 후 `local_settings.py` 수정:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'livinglab_sensor',
        'USER': 'postgres',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

---

## 문제 해결

### "No module named 'psycopg2'"
SQLite를 사용 중이면 무시해도 됩니다. 
PostgreSQL을 사용하려면: `pip install psycopg2-binary`

### "port 8000 is already in use"
다른 포트 사용:
```bash
python manage.py runserver 8001
```

### 마이그레이션 오류
```bash
# 마이그레이션 파일 재생성
python manage.py makemigrations sensor
python manage.py migrate
```

### 데이터베이스 잠김
```bash
# SQLite 데이터베이스 재설정
rm db.sqlite3
python manage.py migrate
```

---

## 개발 팁

### Django Shell로 데이터 확인
```bash
python manage.py shell_plus

# 모든 센서 조회
from sensor.models import SensorData
SensorData.objects.count()

# 특정 센서 데이터
SensorData.objects.filter(sensor='test_sensor')

# 위치 정보 추가
from sensor.models import SensorLocation
SensorLocation.objects.create(
    sensor='test_sensor',
    latitude=36.626906,
    longitude=127.457722
)
```

### 정적 파일 수집
```bash
python manage.py collectstatic
```

### 로그 파일 확인
```bash
tail -f logs/django.log  # (존재하는 경우)
```

---

## 프로덕션 배포 준비

로컬 테스트 후 프로덕션 배포:
```bash
# Docker 환경에서 배포
docker-compose up -d

# 또는 서버에 직접 배포
scp -r . user@server:/path/to/livinglab
ssh user@server "cd /path/to/livinglab && bash setup_prod.sh"
```

---

## 추가 리소스

- [Django 공식 문서](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Anaconda 문서](https://docs.conda.io/)

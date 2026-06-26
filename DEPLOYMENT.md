# 프로덕션 배포 가이드 (Ubuntu 26.04 LTS)

## 📋 배포 순서

### 1단계: 서버 사전 준비

```bash
# Ubuntu 업데이트
sudo apt update && sudo apt upgrade -y

# Docker 설치
sudo apt install -y docker.io docker-compose-v2 git curl

# 서비스 자동 시작
sudo systemctl enable docker
sudo systemctl start docker

# 사용자 그룹 추가 (선택: sudo 없이 docker 명령 실행)
sudo usermod -aG docker $USER
newgrp docker
```

### 2단계: 스토리지 구조 확인 및 준비

```bash
# 마운트 확인 (아키텍처 문서 기준)
df -h
# 확인 사항:
# - /mnt/storage/livinglab (4TB SSD) ✓
# - /mnt/backup (2TB HDD) ✓

# 디렉토리 생성
sudo mkdir -p /mnt/storage/livinglab/{db_data,logs,staticfiles}
sudo mkdir -p /mnt/backup

# 권한 설정
sudo chown -R 999:999 /mnt/storage/livinglab/db_data
sudo chown -R 1000:1000 /mnt/storage/livinglab/{logs,staticfiles}
sudo chmod 755 /mnt/storage/livinglab /mnt/backup
```

### 3단계: 코드 배포

```bash
# 프로젝트 디렉토리로 이동
cd /opt  # 또는 선호하는 경로
sudo git clone https://github.com/taawwwk/livinglab-webserver-django.git
cd livinglab-webserver-django

# 또는 기존 디렉토리가 있으면
cd /existing/path
git pull origin main
```

### 4단계: 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# 프로덕션용 설정 (보안 중요!)
sudo nano .env
```

**수정할 항목:**

```env
DEBUG=False
DJANGO_SECRET_KEY=change-this-to-random-secure-string
DB_NAME=livinglab_sensor
DB_USER=postgres
DB_PASSWORD=change-this-to-secure-password
DB_HOST=db
DB_PORT=5432
```

**DJANGO_SECRET_KEY 생성:**
```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5단계: Docker Compose 실행

```bash
# 서비스 시작
docker-compose up -d

# 로그 확인 (문제 확인용)
docker-compose logs -f web
docker-compose logs -f db

# 서비스 상태 확인
docker-compose ps
```

**예상 출력:**
```
NAME                  STATUS
livinglab_db          Up 1 minute (healthy)
livinglab_web         Up 1 minute
```

### 6단계: 초기화 및 관리

```bash
# 데이터베이스 마이그레이션 (자동 실행되지만 확인)
docker-compose exec web python manage.py migrate

# 관리자 계정 생성 (대화형)
docker-compose exec web python manage.py createsuperuser

# 정적 파일 수집 (필요시)
docker-compose exec web python manage.py collectstatic --noinput

# 상태 확인
docker-compose exec web python manage.py check
```

### 7단계: 방화벽 및 네트워크 설정

```bash
# UFW 방화벽 (활성화된 경우)
sudo ufw allow 10021/tcp      # Django API
sudo ufw allow 22/tcp         # SSH
sudo ufw allow 34253/tcp      # SSH 관리 포트 (옵션)

# 또는 iptables 확인
sudo iptables -L -n

# 포트 바인딩 확인
sudo ss -tlnp | grep 10021
```

### 8단계: 접속 및 테스트

```bash
# 로컬 테스트 (서버 내부)
curl http://localhost:10021/sensor/api/map
curl http://127.0.0.1:10021/admin/

# 원격 테스트 (다른 기기)
curl http://203.255.81.72:10021/sensor/api/map

# 센서 데이터 전송 테스트
curl "http://203.255.81.72:10021/sensor/sensing?mac=AA:BB:CC:DD:EE:FF&sensor=test_sensor&sender=test&mode=direct&temp=25.5&co2=400&time=1720000000"
```

---

## 🗂️ 기존 MySQL 데이터 복구 (선택사항)

만약 이전 MySQL 데이터베이스를 복구해야 한다면:

### 옵션 A: 전체 덤프 복구 (권장)

```bash
# 1. MySQL 덤프 파일을 서버로 전송
scp docs/db.txt user@server:/tmp/db.txt

# 2. PostgreSQL 형식으로 변환 (스크립트 필요)
# 또는 기존 데이터가 아직 있으면 mysqldump 사용

# 3. 데이터베이스에 복구
docker-compose exec db psql -U postgres -d livinglab_sensor < /tmp/db.sql
```

### 옵션 B: Django ORM으로 마이그레이션

```bash
# Python 스크립트로 MySQL → PostgreSQL 데이터 이전
docker-compose exec web python manage.py shell < migration_script.py
```

---

## 📊 모니터링 및 유지보수

### 로그 확인

```bash
# 실시간 로그
docker-compose logs -f web

# 특정 줄 수만 표시
docker-compose logs --tail=100 web

# 타임스탬프 포함
docker-compose logs -f --timestamps web
```

### 데이터베이스 백업

```bash
# 일일 백업 스크립트
sudo cat > /usr/local/bin/backup-livinglab.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/mnt/backup/livinglab"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
docker-compose exec -T db pg_dump -U postgres livinglab_sensor > $BACKUP_DIR/db_$TIMESTAMP.sql
gzip $BACKUP_DIR/db_$TIMESTAMP.sql
EOF

sudo chmod +x /usr/local/bin/backup-livinglab.sh

# Cron 작업 (매일 자정)
sudo crontab -e
# 추가: 0 0 * * * /usr/local/bin/backup-livinglab.sh
```

### 디스크 사용량 확인

```bash
# 4TB SSD 사용량
du -sh /mnt/storage/livinglab/*

# PostgreSQL 데이터베이스 크기
docker-compose exec db psql -U postgres -d livinglab_sensor -c "SELECT pg_size_pretty(pg_database_size('livinglab_sensor'));"
```

### 서비스 재시작

```bash
# 특정 서비스만
docker-compose restart web
docker-compose restart db

# 전체 재시작
docker-compose restart
docker-compose up -d
```

---

## ⚠️ 트러블슈팅

### 포트 이미 사용 중
```bash
# 기존 프로세스 확인
sudo lsof -i :10021
sudo kill -9 <PID>

# 또는 다른 포트 사용
# docker-compose.yml에서 ports 수정
```

### 데이터베이스 연결 실패
```bash
# 데이터베이스 상태 확인
docker-compose ps db
docker-compose logs db

# 데이터베이스 수동 확인
docker-compose exec db psql -U postgres -l
```

### 마이그레이션 오류
```bash
# 마이그레이션 상태 확인
docker-compose exec web python manage.py showmigrations

# 특정 앱만 마이그레이션
docker-compose exec web python manage.py migrate sensor
```

### 디스크 공간 부족
```bash
# 오래된 로그 정리
docker system prune -a --volumes

# 특정 날짜 이전 백업 삭제
find /mnt/backup -mtime +30 -delete
```

---

## 🔒 보안 체크리스트

- [ ] `.env` 파일에 강력한 비밀번호 설정
- [ ] `DEBUG=False` 확인
- [ ] `ALLOWED_HOSTS` 설정 (production 환경)
- [ ] HTTPS/SSL 설정 (Nginx reverse proxy)
- [ ] 방화벽 규칙 확인
- [ ] 정기적인 백업 스케줄 설정
- [ ] 로그 모니터링 시스템 구축
- [ ] PostgreSQL 관리자 비밀번호 변경

---

## 📞 지원

문제가 발생하면:

```bash
# 전체 시스템 상태 확인
docker-compose ps
docker-compose logs --tail=50

# 서버 리소스 확인
free -h              # 메모리
df -h                # 디스크
top                  # CPU 사용량
```

---

## 🔄 배포 업데이트

코드 업데이트 시:

```bash
# 최신 코드 가져오기
git pull origin main

# 컨테이너 재빌드 및 시작
docker-compose up -d --build

# 마이그레이션 실행 (필요시)
docker-compose exec web python manage.py migrate
```

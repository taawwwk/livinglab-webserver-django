# Campus Sensing Living Lab - System Architecture Specification

## 1. 하드웨어 및 볼륨 매핑 제약 조건
* **서버 OS**: Ubuntu 26.04 LTS
* **스토리지 환경 제약 (매우 중요)**:
  * 메인 NVMe 디스크는 14GB로 매우 협소하므로 시스템 관련 파일 외에는 저장 금지.
  * **모든 Docker 볼륨, DB 데이터, 로그 적재**는 반드시 고성능 4TB SSD 경로인 **`/mnt/storage/livinglab/`** 내부에서 이루어져야 함.
  * **새벽 백업 데이터**는 물리 2TB HDD 경로인 **`/mnt/backup/`** 내부로 격리 저장함.

## 2. 네트워크 및 포트 토폴로지
* **네트워크 경로**: 외부 센서 패킷 ➡️ 학내망 방화벽/공유기 ➡️ 메인 서버
* **보안 환경**: HTTPS/SSL 및 Reverse Proxy(Nginx)는 생략하며, 학내망 엔터프라이즈 방화벽 정책에 보안을 의존함.
* **포트 매핑**:
  * 외부 `10021` 포트 ➡️ Django 컨테이너 `10021` 포트 (API 및 어드민 서비스 다이렉트 바인딩)
  * 외부 `34253` 포트 ➡️ 메인 서버 호스트 `10023` 포트 (SSH 관리 전용)

## 3. 멀티 컨테이너 구성 및 역할 (Docker Compose)
* **`web` 컨테이너 (Django)**: Nginx 없이 10021 포트를 직접 바인딩하여 가동. 센서가 던지는 `GET /sensor/sensing` 패킷 파싱 후 DB 인서트 및 웹 어드민 제공.
* **`db` 컨테이너 (PostgreSQL)**: 4TB SSD 메모리 기반 데이터베이스 가동. 3,900만 건 규모의 시계열 대용량 데이터 적재 최적화(Index 구성).
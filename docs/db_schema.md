Campus Sensing Living Lab - Database Schema Specification
본 문서는 리빙랩 서버 복구를 위한 데이터베이스 구조 정의서입니다. 레거시 MySQL 덤프 스키마를 계승하되, 대상 DBMS인 PostgreSQL의 데이터 타입과 인프라 환경(4TB SSD 볼륨)에 맞춤 최적화되었습니다.


1. 데이터베이스 핵심 설계 원칙
• 대상 DBMS: PostgreSQL 16+ (TimescaleDB 시계열 확장 호환 설계)
• 기본키(PK) 전략: 레거시 MySQL의 AUTO_INCREMENT는 PostgreSQL의 SERIAL 또는 BIGSERIAL 타입으로 변환합니다.
• 시계열 최적화: 수천만 건의 로그가 쌓이는 sensor_sensor_data 테이블은 대시보드 조회 성능을 위해 sensor 및 sensing_time 필드에 복합 인덱스(Index)를 필수로 구성합니다.


2. 핵심 비즈니스 테이블 명세 (sensor 앱)
① sensor_sensor_data (원시 센서 데이터 로그 테이블)
센서 노드가 직접 혹은 모바일 릴레이를 통해 보낸 모든 환경 데이터 원시 로그가 적재되는 가장 무거운 테이블입니다.
• 레거시 용량 참고: AUTO_INCREMENT 카운터가 약 3,900만 건 이상을 기록한 초대형 테이블입니다.
컬럼명	데이터 타입 (PostgreSQL)	Null 여부	설명 / 매핑 API 파라미터
id	BIGSERIAL	NOT NULL	기본키 (Primary Key)
sensor	VARCHAR(100)	NOT NULL	센서 이름 (e.g., 'sensor 01')
mac	VARCHAR(100)	NOT NULL	센서 기기의 물리 MAC 주소
receiver	VARCHAR(100)	NOT NULL	수신기 정보 (스마트폰 UUID 등)
mode	VARCHAR(20)	NOT NULL	전송 방식 (direct 또는 mobile)
temperature	DOUBLE PRECISION	NOT NULL	측정 온도 (temp 값 매핑)
co2	INTEGER	NOT NULL	측정 이산화탄소 농도 (ppm)
sensing_time	DOUBLE PRECISION	NOT NULL	센싱 시간 (time 타임스탬프 값 매핑)
rssi	INTEGER	NULL	모바일 센싱 시 수집된 BLE 신호 세기

② sensor_location (센서 설치 위치 관리 테이블)
캠퍼스 맵 대시보드 상에 센서를 시각화하기 위해 각 센서 노드의 위경도 좌표를 보관하는 마스터 테이블입니다.
컬럼명	데이터 타입 (PostgreSQL)	Null 여부	설명 / 매핑 API 파라미터
id	BIGSERIAL	NOT NULL	기본키 (Primary Key)
sensor	VARCHAR(100)	NOT NULL	센서 이름 (Unique Key 역할)
latitude	DOUBLE PRECISION	NOT NULL	센서 설치 위도 좌표 (e.g., 36.626906)
longitude	DOUBLE PRECISION	NOT NULL	센서 설치 경도 좌표 (e.g., 127.457722)

③ sensor_ip_db (센서 네트워크 IP 기록 테이블)
각 센서 기기가 학내 와이파이망에서 할당받은 IP 주소를 주기적으로 갱신하여 기록하는 테이블입니다.
컬럼명	데이터 타입 (PostgreSQL)	Null 여부	설명 / 매핑 API 파라미터
id	BIGSERIAL	NOT NULL	기본키 (Primary Key)
sensor	VARCHAR(100)	NOT NULL	IP를 보고한 센서 이름
ip	VARCHAR(100)	NOT NULL	할당받은 IP 주소 (e.g., '172.30.128.46')
time	INTEGER	NOT NULL	IP가 최종 확인된 시점의 UNIX 타임스탬프

④ sensor_sensor_check_db & sensor_mobile_check_db (최신 상태 스냅샷 테이블)
대시보드 지도(sensor/api/map)를 조회할 때, 3,900만 건의 로그를 매번 풀 스캔하면 서버가 다운됩니다. 이를 방지하기 위해 **각 센서별 가장 마지막으로 수집된 데이터 1건만 상시 업데이트(스냅샷)**해두는 캐싱용 테이블입니다.
• sensor_sensor_check_db: 직접 통신(direct)하는 센서들의 최신 상태 스냅샷.
• sensor_mobile_check_db: 모바일 릴레이(mobile)를 통해 수집되는 센서들의 최신 상태 스냅샷.


3. Django 인증 및 시스템 관리 테이블 (참고용)
레거시 장고 시스템이 마이그레이션 도중 참조하는 표준 프레임워크 테이블 구조입니다. (장고가 내부적으로 자동 생성하므로 수동 구축 불필요)
• auth_user / auth_group: 사용자 계정 및 권한 그룹 관리 테이블
• django_admin_log: 장고 어드민 페이지 관리자 활동 로그 테이블
• django_migrations: 데이터베이스 스키마 버전 관리 테이블
• django_session: 사용자 로그인 세션 유지 테이블

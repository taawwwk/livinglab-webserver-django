Campus Sensing Living Lab - API Specification
캠퍼스 내 설치된 센서 기기들의 데이터 수집, IP 기록, 위치 설정 및 조회를 위한 백엔드 API 명세서입니다. 기본 웹 서비스 포트는 **10021**번을 사용합니다.

1. 최신 센서 데이터 조회 API (통합 맵 데이터)
   개요
   설명: 캠퍼스 내에 설치되어 있는 모든 센서들의 최신 가용 데이터를 통합 조회합니다.
   특징: '센서 위치 조회 API'와 '센서 최신 데이터 조회 API'를 동시에 호출하여, 두 데이터를 sensor 필드를 기준으로 자동 결합(Join)하여 반환합니다.
   Method: GET
   URL: http://203.255.81.72:10021/sensor/api/map
   Response 예시 (JSON Array)
    [
      {
        "sensor": "sensor 01",
        "latitude": 36.626906,
        "longitude": 127.457722,
        "temperature": 28,
        "co2": 400,
        "time": "Thu Apr 16 10:48:48 2026",
        "fresh": false
      }
    ]
  참고: 전체 수용 용량(Capacity)은 총 센서 개수인 37개(34 + 3) 기준입니다. 단, pws01, vs01, vs02 3개는 현재 미사용 센서 노드입니다.
  📋 필드 상세 설명
  필드명	타입	설명
  sensor	String	센서 고유 명칭
  latitude	Double	센서가 설치된 물리 위도 좌표
  longitude	Double	센서가 설치된 물리 경도 좌표
  temperature	Integer	센서가 측정한 현재 기온 (Celsius)
  co2	Integer	센서가 측정한 이산화탄소 농도 (ppm)
  time	DateTime	해당 데이터가 데이터베이스에 최종 저장된 날짜/시간
  fresh	Boolean	데이터 갱신 여부 상태값
  - true: 현재 시간 기준 1시간 이내에 데이터가 정상 갱신됨
- false: 마지막 수집 주기가 1시간을 초과함

1. 센서 데이터 전송 API
📌 개요
• 설명: 각 센서 기기 또는 모바일 릴레이 노드로부터 실시간 환경 센싱 데이터를 수집(적재)합니다.
• Method: GET
• URL: http://203.255.81.72:10021/sensor/sensing
📑 Query Parameters
파라미터명	필수 여부	설명	예시 / 비고
mac	필수	센서 기기의 물리적 MAC 주소	D8:3A:DD:C1:88:C8
sensor	필수	센서의 고유 이름	sensor 01, sensor 02 등
sender	필수	데이터 전송 식별자	- sensor: 라즈베리파이(RPI) 센서에서 직접 전송
- 스마트폰 UUID: 릴레이 수집 노드의 UUID
mode	필수	센서 데이터 전송 메커니즘	- direct: 센서가 상위 망으로 직접 HTTP 전송
- mobile: 스마트폰의 BLE 기반 모바일 센싱 및 릴레이
temp	필수	측정한 온도 데이터	실수 또는 정수형
co2	필수	측정한 이산화탄소 농도 데이터	정수형 (ppm)
time	필수	센싱이 발생한 시점의 시간 정보	UNIX Timestamp (초 단위 실수/정수형)
rssi	선택	블루투스 신호 세기	mode=mobile 일 때 스마트폰이 스캔한 센서의 BLE RSSI 값
실제 호출 URL 예시
http://203.255.81.72:10021/sensor/sensing?mac={맥주소}&sensor={이름}&sender={UUID}&mode=mobile&temp={온도}&co2={co2}&time={timestamp}&rssi={rssi}
📥 Response
• 성공 시 200 OK 또는 커스텀 메시지 반환

1. 센서 IP 기록 API
📌 개요
• 설명: 센서 노드가 Wi-Fi 통신을 수행하기 위해 로컬/학내망에서 할당받은 IP 주소를 주기적으로 서버에 보고하고 기록합니다.
• Method: GET
• URL: http://203.255.81.72:10021/sensor/sensing
📑 Query Parameters
파라미터명	타입	설명	예시
sensor	String	IP를 보고하는 센서의 고유 이름	sensor 01
ip	String	센서가 공유기 등으로부터 할당받은 현재 IP 주소	192.168.0.x 또는 학내 사설 IP
호출 URL 예시
http://203.255.81.72:10021/sensor/sensing?sensor={센서이름}&ip={IP주소}/
📥 Response
• 성공 시 200 OK 또는 성공 응답

1. 센서 위치 API
📌 개요
• 설명: 데이터베이스에 기록되어 있는 센서의 고유 설치 위치 좌표를 조회하거나 설정합니다.
• Method: GET
• URL: http://203.255.81.72:10021/sensor/sensing
📑 Query Parameters
파라미터명	타입	설명	예시
sensor	String	위치 정보를 매핑할 센서 이름	sensor 01
latitude	Double	센서가 위치한 지점의 설치 위도	36.626906
longitude	Double	센서가 위치한 지점의 설치 경도	127.457722
호출 URL 예시
http://203.255.81.72:10021/sensor/sensing?sensor={센서이름}&latitude={위도}&longitude={경도}/
📥 Response
• 성공 시 200 OK 또는 성공 응답

1. 최신 센서 데이터 조회 API (DB 원시 데이터)
📌 개요
• 설명: 데이터베이스(DB) 내부에 누적 저장되어 있는 모든 센서들의 가장 최신 로우(Raw) 데이터를 일괄 조회합니다.
• Method: GET
• URL: http://203.255.81.72:10021/sensor/new/sensor/
📥 Response
• 성공 시 200 OK 및 원시 최신 센서 데이터 셋 반환

1. 최신 센서 IP 조회 API
📌 개요
• 설명: 데이터베이스(DB)에 기록되어 있는 모든 센서 노드들의 가장 최신 할당 IP 주소 목록을 조회합니다.
• Method: GET
• URL: http://203.255.81.72:10021/sensor/new/ip
📥 Response
• 성공 시 200 OK 및 최신 IP 리스트 데이터 반환
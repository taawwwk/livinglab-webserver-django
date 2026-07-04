from django.apps import AppConfig


class SensorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sensor'
    verbose_name = 'Sensor Management'

    # PWS 데이터 수집 및 CCTV 모니터링은 gunicorn 워커 프로세스가 아니라
    # `python manage.py runscheduler` 전용 프로세스(scheduler 서비스)에서 단일 실행된다.
    # 워커마다 ready()가 호출되므로 여기서 스케줄러를 시작하면 워커 수만큼 중복 실행된다.

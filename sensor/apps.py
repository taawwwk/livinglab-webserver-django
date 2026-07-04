from django.apps import AppConfig
from apscheduler.schedulers.background import BackgroundScheduler


class SensorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sensor'
    verbose_name = 'Sensor Management'

    def ready(self):
        from .views import fetch_pws_data, monitor_preciprate_and_cctv

        scheduler = BackgroundScheduler()

        # PWS 데이터 수집: 5분마다
        scheduler.add_job(
            fetch_pws_data,
            'interval',
            minutes=5,
            id='pws_data_collection',
            name='PWS Data Collection',
            replace_existing=True,
        )

        # CCTV 강수량 모니터링: 5분마다
        scheduler.add_job(
            monitor_preciprate_and_cctv,
            'interval',
            minutes=5,
            id='cctv_monitoring',
            name='CCTV Precipitation Monitoring',
            replace_existing=True,
        )

        if not scheduler.running:
            scheduler.start()

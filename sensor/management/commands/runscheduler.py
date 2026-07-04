import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the PWS data collection and CCTV monitoring jobs on a schedule (single process).'

    def handle(self, *args, **options):
        from sensor.views import fetch_pws_data, monitor_preciprate_and_cctv

        scheduler = BlockingScheduler()

        scheduler.add_job(
            fetch_pws_data,
            'interval',
            minutes=5,
            id='pws_data_collection',
            name='PWS Data Collection',
            replace_existing=True,
        )

        scheduler.add_job(
            monitor_preciprate_and_cctv,
            'interval',
            minutes=5,
            id='cctv_monitoring',
            name='CCTV Precipitation Monitoring',
            replace_existing=True,
        )

        logger.info('Scheduler started (pws_data_collection, cctv_monitoring)')
        scheduler.start()

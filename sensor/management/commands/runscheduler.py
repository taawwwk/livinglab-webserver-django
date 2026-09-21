import logging
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def cctv_recording_enabled():
    """CCTV 녹화 on/off 스위치 (docker-compose의 CCTV_RECORDING_ENABLED)."""
    return os.environ.get('CCTV_RECORDING_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes')


class Command(BaseCommand):
    help = 'Runs the PWS data collection and CCTV recording jobs on a schedule (single process).'

    def handle(self, *args, **options):
        from sensor.views import cleanup_orphan_recordings, fetch_pws_data, monitor_cctv_recording

        cleanup_orphan_recordings()

        scheduler = BlockingScheduler()

        # interval 트리거는 기본적으로 한 주기가 지나야 처음 실행된다.
        # 재시작 때마다 수집이 비는 것을 막기 위해 두 job 모두 즉시 1회 돌린다.
        start_now = datetime.now()

        scheduler.add_job(
            fetch_pws_data,
            'interval',
            minutes=5,
            id='pws_data_collection',
            name='PWS Data Collection',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
            next_run_time=start_now,
        )

        if cctv_recording_enabled():
            # 상시 녹화라 프로세스가 죽거나 물렸을 때 빨리 복구해야 하므로 1분 주기로 감시한다.
            # 실제 녹화 시간대(KST 05~20시) 판정은 job 안에서 한다.
            scheduler.add_job(
                monitor_cctv_recording,
                'interval',
                minutes=1,
                id='cctv_recording',
                name='CCTV Continuous Recording (KST 05:00-20:00)',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
                next_run_time=start_now,
            )
            jobs = 'pws_data_collection, cctv_recording'
        else:
            jobs = 'pws_data_collection (CCTV recording disabled by CCTV_RECORDING_ENABLED)'

        logger.info(f'Scheduler started ({jobs})')
        scheduler.start()

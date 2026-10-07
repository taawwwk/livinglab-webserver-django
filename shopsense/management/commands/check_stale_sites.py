"""측정값이 한동안 안 들어온 설치 장소를 찾는다 (cron용). 지금은 로그 출력만 한다.

    docker exec livinglab_web python manage.py check_stale_sites --minutes 10
"""
import datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from shopsense import levels
from shopsense.models import ShopSite

logger = logging.getLogger('shopsense')


class Command(BaseCommand):
    help = '마지막 수신 후 N분(기본 10분) 이상 지난 설치 장소를 WARNING 로그로 남긴다.'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=10, help='이 시간 이상 수신이 없으면 stale (기본 10)')

    def handle(self, *args, **options):
        threshold = datetime.timedelta(minutes=options['minutes'])
        now = timezone.now()
        stale = 0
        for site in ShopSite.objects.order_by('pk'):
            last = levels.last_received_at(site)
            if levels.is_stale(last, now=now, after=threshold):
                stale += 1
                if last is None:
                    message = f'shopsense stale: site={site.pk}({site.name}) 수신 기록 없음'
                else:
                    minutes = int((now - last).total_seconds() // 60)
                    message = (f'shopsense stale: site={site.pk}({site.name}) '
                               f'마지막 수신 {timezone.localtime(last):%Y-%m-%d %H:%M:%S} ({minutes}분 전)')
                logger.warning(message)
                self.stdout.write(message)
                # TODO: 알림 발송을 붙일 때 shopsense.alerts에 stale 알림 함수를 추가해 호출
        self.stdout.write(f'checked={ShopSite.objects.count()} stale={stale} threshold={options["minutes"]}min')

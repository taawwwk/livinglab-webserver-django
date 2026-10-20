"""7주차 데이터 수집 실습 · 8주차 중간평가 대시보드와 TA용 채점 CSV."""
import csv
from urllib.parse import quote

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import grading

CACHE_KEY = 'opensrc_midterm_status'


def evaluation():
    """grading.evaluate()를 몇 초 캐시한다 (여러 학생이 동시에 폴링해도 livinglab 조회는 한 번)."""
    seconds = settings.OPENSRC_MIDTERM_CACHE_SECONDS
    if seconds <= 0:
        return grading.evaluate()
    data = cache.get(CACHE_KEY)
    if data is None:
        data = grading.evaluate()
        cache.set(CACHE_KEY, data, seconds)
    return data


@require_GET
def dashboard(request):
    return render(request, 'opensrc/midterm.html', {
        'team_count': settings.OPENSRC_TEAM_COUNT,
        'online_minutes': settings.OPENSRC_SENSOR_ONLINE_MINUTES,
        'full_score': settings.OPENSRC_MIDTERM_FULL_SCORE,
        'penalty': settings.OPENSRC_MIDTERM_PENALTY,
    })


@require_GET
def status(request):
    return JsonResponse(evaluation(), json_dumps_params={'ensure_ascii': False})


def _slot_result(slot):
    label = grading.STATUS_LABELS[slot['status']]
    if slot['status'] == grading.STATUS_REVIEW:
        label += ' (' + '; '.join(slot['notes']) + ')' if slot['notes'] else ''
    return label


@staff_member_required
@require_GET
def export_scores(request):
    """팀별 점수 CSV. 팀 한 행에 담당 칸을 순서대로 펼친다 (칸1 … 칸N).

    ?format=long 이면 (팀, 칸) 한 행씩 — 스프레드시트에서 필터 걸기 좋다.
    """
    data = evaluation()
    slots_by_team = {}
    for slot in data['slots']:
        if slot['team_no'] is not None:
            slots_by_team.setdefault(slot['team_no'], []).append(slot)

    def slot_cells(slot):
        return [f"{slot['date']} {slot['label']}", _slot_result(slot),
                len(slot['online']), len(slot['collected']),
                '센서 ' + ','.join(map(str, slot['missing'])) if slot['missing'] else '',
                '; '.join(slot['notes'])]

    rows = []
    if request.GET.get('format') == 'long':
        header = ['팀', '칸', '결과', '가동 센서 수', '수집 센서 수', '누락 센서', '비고', '총점', '확정']
        for team in data['teams']:
            for slot in slots_by_team.get(team['team_no'], []):
                rows.append([team['team_no']] + slot_cells(slot) + [team['score'], 'Y' if team['final'] else 'N'])
    else:
        width = max([len(v) for v in slots_by_team.values()] or [0])
        header = ['팀', '총점', '확정', '인정', '검토 필요', '누락', '미완료']
        for k in range(1, width + 1):
            header += [f'칸{k}', f'칸{k} 결과', f'칸{k} 가동 센서 수', f'칸{k} 수집 센서 수', f'칸{k} 누락 센서', f'칸{k} 비고']
        for team in data['teams']:
            row = [team['team_no'], team['score'], 'Y' if team['final'] else 'N',
                   team['ok'], team['review'], team['missing'], team['remaining']]
            mine = slots_by_team.get(team['team_no'], [])
            for slot in mine:
                row += slot_cells(slot)
            row += [''] * (6 * (width - len(mine)))
            rows.append(row)

    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f"opensrc_midterm_scores_{data['now'][:10]}.csv"
    resp['Content-Disposition'] = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    resp.write('﻿')  # 엑셀 한글 깨짐 방지 BOM
    writer = csv.writer(resp)
    writer.writerow(header)
    writer.writerows(rows)
    return resp

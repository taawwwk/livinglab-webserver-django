from django.urls import re_path

from . import midterm_views, team_views, views

# POST에 APPEND_SLASH 리다이렉트가 걸리면 body가 사라지므로 끝 슬래시 유무를 둘 다 받는다
urlpatterns = [
    # 4주차: 연구실 센서 릴레이 (raw HMAC 검증). 확인 페이지는 check/ 에서 week4/ 로 옮겼다
    re_path(r'^test/?$', views.submit, name='opensrc_submit'),
    re_path(r'^week4/?$', views.week4, name='opensrc_week4'),
    re_path(r'^api/latest/?$', views.latest, name='opensrc_latest'),
    re_path(r'^api/summary/?$', views.summary, name='opensrc_summary'),
    re_path(r'^export\.csv$', views.export_csv, name='opensrc_export'),

    # 5주차~: 팀 key로 올리는 데이터 (7주차 캠퍼스 센서 수집도 이 API)
    re_path(r'^upload/?$', team_views.upload, name='opensrc_team_upload'),
    re_path(r'^teams/?$', team_views.page, name='opensrc_teams'),
    re_path(r'^api/teams/latest/?$', team_views.latest, name='opensrc_teams_latest'),
    re_path(r'^api/teams/summary/?$', team_views.summary, name='opensrc_teams_summary'),
    re_path(r'^teams_export\.csv$', team_views.export_csv, name='opensrc_teams_export'),

    # 6주차: 데이터 분석 실습용 조회
    re_path(r'^data/?$', team_views.data, name='opensrc_team_data'),

    # 7주차 데이터 수집 · 8주차 중간평가 대시보드 (강의자료에 안내된 URL이 check/)
    re_path(r'^check/?$', midterm_views.dashboard, name='opensrc_check'),
    re_path(r'^api/midterm/?$', midterm_views.status, name='opensrc_midterm_status'),
    re_path(r'^midterm_scores\.csv$', midterm_views.export_scores, name='opensrc_midterm_export'),
]

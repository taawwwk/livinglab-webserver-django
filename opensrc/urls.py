from django.urls import re_path

from . import team_views, views

# POST에 APPEND_SLASH 리다이렉트가 걸리면 body가 사라지므로 끝 슬래시 유무를 둘 다 받는다
urlpatterns = [
    re_path(r'^test/?$', views.submit, name='opensrc_submit'),
    re_path(r'^check/?$', views.check, name='opensrc_check'),
    re_path(r'^api/latest/?$', views.latest, name='opensrc_latest'),
    re_path(r'^api/summary/?$', views.summary, name='opensrc_summary'),
    re_path(r'^export\.csv$', views.export_csv, name='opensrc_export'),

    # 5주차: 팀이 직접 만든 센서
    re_path(r'^upload/?$', team_views.upload, name='opensrc_team_upload'),
    re_path(r'^teams/?$', team_views.page, name='opensrc_teams'),
    re_path(r'^api/teams/latest/?$', team_views.latest, name='opensrc_teams_latest'),
    re_path(r'^api/teams/summary/?$', team_views.summary, name='opensrc_teams_summary'),
    re_path(r'^teams_export\.csv$', team_views.export_csv, name='opensrc_teams_export'),

    # 6주차: 데이터 분석 실습용 조회
    re_path(r'^data/?$', team_views.data, name='opensrc_team_data'),
]

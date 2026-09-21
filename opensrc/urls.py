from django.urls import re_path

from . import views

# POST에 APPEND_SLASH 리다이렉트가 걸리면 body가 사라지므로 끝 슬래시 유무를 둘 다 받는다
urlpatterns = [
    re_path(r'^test/?$', views.submit, name='opensrc_submit'),
    re_path(r'^check/?$', views.check, name='opensrc_check'),
    re_path(r'^api/latest/?$', views.latest, name='opensrc_latest'),
    re_path(r'^api/summary/?$', views.summary, name='opensrc_summary'),
    re_path(r'^export\.csv$', views.export_csv, name='opensrc_export'),
]

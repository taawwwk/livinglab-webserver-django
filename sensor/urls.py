from django.urls import path
from . import views

urlpatterns = [
    path('sensing/', views.sensor_sensing, name='sensor_sensing'),
    path('ip/', views.record_sensor_ip, name='record_sensor_ip'),
    path('api/map', views.sensor_map, name='sensor_map'),
    path('api/realtime', views.realtime_stats, name='realtime_stats'),
    path('api/timeseries', views.climate_timeseries, name='climate_timeseries'),
    path('new/sensor/', views.latest_sensor_data, name='latest_sensor_data'),
    path('new/ip', views.latest_sensor_ips, name='latest_sensor_ips'),
    path('ips/', views.sensor_ips_page, name='sensor_ips_page'),
    path('dashboard/', views.dashboard, name='dashboard'),
]

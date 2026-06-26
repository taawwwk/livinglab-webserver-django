from django.urls import path
from . import views

urlpatterns = [
    path('sensing', views.sensor_sensing, name='sensor_sensing'),
    path('api/map', views.sensor_map, name='sensor_map'),
    path('new/sensor/', views.latest_sensor_data, name='latest_sensor_data'),
    path('new/ip', views.latest_sensor_ips, name='latest_sensor_ips'),
]

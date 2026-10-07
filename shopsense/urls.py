from django.urls import path

from . import views

urlpatterns = [
    path('readings/', views.ReadingsView.as_view(), name='shopsense_readings'),
    path('sites/<int:site_id>/latest/', views.SiteLatestView.as_view(), name='shopsense_site_latest'),
    path('health/', views.HealthView.as_view(), name='shopsense_health'),
]

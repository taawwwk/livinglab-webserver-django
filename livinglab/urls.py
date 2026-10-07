from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sensor/opensrc/', include('opensrc.urls')),
    path('sensor/', include('sensor.urls')),
    path('api/shop/', include('shopsense.urls')),
]

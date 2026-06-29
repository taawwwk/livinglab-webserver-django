from django.contrib import admin
from .models import SensorData, IpDb, SensorCheckDb, MobileCheckDb, SensorLocation, PWSStation, PWSObservation, PWSLatest


@admin.register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'mac', 'temperature', 'co2', 'sensing_time', 'mode')
    list_filter = ('sensor', 'mode', 'sensing_time')
    search_fields = ('sensor', 'mac')
    readonly_fields = ('sensing_time',)


@admin.register(IpDb)
class IpDbAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'ip', 'time')
    list_filter = ('sensor', 'time')
    search_fields = ('sensor', 'ip')


@admin.register(SensorCheckDb)
class SensorCheckDbAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'temperature', 'co2', 'sensing_time')
    list_filter = ('sensor',)
    search_fields = ('sensor',)
    readonly_fields = ('sensing_time',)


@admin.register(MobileCheckDb)
class MobileCheckDbAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'temperature', 'co2', 'rssi', 'receiver', 'sensing_time')
    list_filter = ('sensor', 'receiver')
    search_fields = ('sensor', 'receiver')
    readonly_fields = ('sensing_time',)


@admin.register(SensorLocation)
class SensorLocationAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'latitude', 'longitude')
    search_fields = ('sensor',)


@admin.register(PWSStation)
class PWSStationAdmin(admin.ModelAdmin):
    list_display = ('stationID', 'stationName', 'neighborhood', 'country', 'latitude', 'longitude')
    search_fields = ('stationID', 'stationName')
    readonly_fields = ('createdAt', 'updatedAt')


@admin.register(PWSObservation)
class PWSObservationAdmin(admin.ModelAdmin):
    list_display = ('stationID', 'obsTimeUtc', 'temperature', 'humidity', 'windSpeed', 'qcStatus')
    list_filter = ('stationID', 'obsTimeUtc', 'qcStatus')
    search_fields = ('stationID',)
    readonly_fields = ('obsTimeUtc',)
    date_hierarchy = 'obsTimeUtc'


@admin.register(PWSLatest)
class PWSLatestAdmin(admin.ModelAdmin):
    list_display = ('stationID', 'obsTimeUtc', 'temperature', 'humidity', 'windSpeed', 'pressure')
    search_fields = ('stationID',)
    readonly_fields = ('updatedAt',)

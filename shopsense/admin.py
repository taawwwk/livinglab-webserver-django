from django.contrib import admin

from .models import ShopSite, WaterLevelReading


@admin.register(ShopSite)
class ShopSiteAdmin(admin.ModelAdmin):
    # 현장에서 baseline(줄자로 잰 바닥까지 거리)과 임계값을 입력하는 화면
    list_display = ('id', 'name', 'baseline_cm', 'warn_level_cm', 'danger_level_cm', 'installed_at')
    search_fields = ('name',)


@admin.register(WaterLevelReading)
class WaterLevelReadingAdmin(admin.ModelAdmin):
    list_display = ('site', 'measured_at', 'distance_cm', 'received_at')
    list_filter = ('site',)
    date_hierarchy = 'measured_at'
    readonly_fields = ('site', 'measured_at', 'distance_cm', 'received_at')

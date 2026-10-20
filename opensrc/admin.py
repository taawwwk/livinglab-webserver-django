from django import forms
from django.conf import settings
from django.contrib import admin

from .models import CampusSensor, CollectionDay, SlotAssignment, Submission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'source', 'team', 'team_no', 'sensor', 'mac', 'temp', 'humidity',
                    'rssi', 'status', 'sender', 'client_ip')
    list_filter = ('source', 'status', 'team_no', 'team')
    search_fields = ('team', 'sensor', 'mac', 'sender')
    readonly_fields = [f.name for f in Submission._meta.fields]
    date_hierarchy = 'received_at'


@admin.register(CampusSensor)
class CampusSensorAdmin(admin.ModelAdmin):
    list_display = ('number', 'ble_name', 'ble_mac', 'lab_sensor', 'location', 'active')
    list_editable = ('ble_mac', 'lab_sensor', 'location', 'active')
    ordering = ('number',)


@admin.register(CollectionDay)
class CollectionDayAdmin(admin.ModelAdmin):
    list_display = ('date', 'weekday', 'assigned_slots')
    ordering = ('date',)

    @admin.display(description='요일')
    def weekday(self, obj):
        return '월화수목금토일'[obj.date.weekday()]

    @admin.display(description='배정된 칸')
    def assigned_slots(self, obj):
        return f'{SlotAssignment.objects.filter(date=obj.date).count()} / {len(settings.OPENSRC_SLOT_HOURS)}'


class SlotAssignmentForm(forms.ModelForm):
    """시작 시각·팀을 드롭다운으로. 선택지는 settings를 따르므로 모델 choices 대신 폼에서 만든다."""

    start_hour = forms.TypedChoiceField(
        label='시간대', coerce=int,
        choices=[(h, f'{h:02d}:00 – {h + 1:02d}:00') for h in settings.OPENSRC_SLOT_HOURS])
    team_no = forms.TypedChoiceField(
        label='팀', coerce=int,
        choices=[(n, f'{n}팀') for n in range(1, settings.OPENSRC_TEAM_COUNT + 1)])

    class Meta:
        model = SlotAssignment
        fields = ('date', 'start_hour', 'team_no')


@admin.register(SlotAssignment)
class SlotAssignmentAdmin(admin.ModelAdmin):
    form = SlotAssignmentForm
    list_display = ('date', 'slot', 'team_no')
    list_filter = ('team_no', 'date')
    list_editable = ('team_no',)
    ordering = ('date', 'start_hour')
    list_per_page = 100

    @admin.display(description='시간대', ordering='start_hour')
    def slot(self, obj):
        return obj.label

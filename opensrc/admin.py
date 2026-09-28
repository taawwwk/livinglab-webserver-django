from django.contrib import admin

from .models import Submission, TeamSubmission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'status', 'sender', 'client_ip')
    list_filter = ('status', 'team')
    search_fields = ('team', 'sensor', 'mac', 'sender')
    readonly_fields = [f.name for f in Submission._meta.fields]


@admin.register(TeamSubmission)
class TeamSubmissionAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'team', 'sensor', 'mac', 'temp', 'humidity', 'eco2', 'status', 'sender')
    list_filter = ('status', 'team')
    search_fields = ('team', 'sensor', 'mac', 'sender')
    readonly_fields = [f.name for f in TeamSubmission._meta.fields]

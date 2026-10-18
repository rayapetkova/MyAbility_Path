from django.contrib import admin

from .models import Answer, Deviation, Report, Segment


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "level", "source", "status", "confirmations", "denials", "deviation_users", "created")
    list_filter = ("type", "level", "source", "status")


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("trip_id", "idx", "user_id", "same", "deviation", "extra_m", "route_source", "created")
    list_filter = ("same", "deviation", "route_source")


admin.site.register(Deviation)
admin.site.register(Answer)

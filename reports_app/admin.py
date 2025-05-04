from django.contrib import admin
from .models import ReportConfig, ClippingEntry

@admin.register(ReportConfig)
class ReportConfigAdmin(admin.ModelAdmin):
    list_display = ("client", "month", "created_at")
    list_filter = ("client", "month")

@admin.register(ClippingEntry)
class ClippingEntryAdmin(admin.ModelAdmin):
    list_display = ("report", "article", "media_channel", "valor_cm")
    list_filter = ("media_channel",)


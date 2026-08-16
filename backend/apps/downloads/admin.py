from django.contrib import admin

from .models import DownloadTask


@admin.register(DownloadTask)
class DownloadTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "status", "progress", "created_at")
    list_filter = ("status",)
    search_fields = ("slug", "title", "user__email")

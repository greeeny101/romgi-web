from django.contrib import admin

from .models import GameMetadataCache


@admin.register(GameMetadataCache)
class GameMetadataCacheAdmin(admin.ModelAdmin):
    list_display = ("id", "cache_key", "no_match", "fetched_at")
    list_filter = ("no_match",)
    search_fields = ("cache_key",)

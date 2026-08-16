from django.contrib import admin

from .models import (
    CatalogBuild,
    Entry,
    EntryGroup,
    EntryGroupMember,
    Link,
    Platform,
    Region,
    RegionEntry,
    Source,
    SourceHealth,
    Torrent,
)


@admin.register(CatalogBuild)
class CatalogBuildAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "started_at", "finished_at"]
    list_filter = ["status"]


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ["id", "brand", "name"]
    search_fields = ["id", "name"]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["id", "name"]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "kind", "priority", "auth_required"]


@admin.register(SourceHealth)
class SourceHealthAdmin(admin.ModelAdmin):
    list_display = ["source", "status", "last_checked_at", "entry_count", "link_count"]


class LinkInline(admin.TabularInline):
    model = Link
    extra = 0


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ["slug", "title", "platform", "build"]
    list_filter = ["platform", "build"]
    search_fields = ["slug", "title"]
    inlines = [LinkInline]


admin.site.register(RegionEntry)
admin.site.register(Torrent)
admin.site.register(EntryGroup)
admin.site.register(EntryGroupMember)

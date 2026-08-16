from django.contrib import admin

from .models import Favorite, RecentlyViewed


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ["user", "slug", "title", "platform", "created_at"]
    search_fields = ["slug", "title"]


@admin.register(RecentlyViewed)
class RecentlyViewedAdmin(admin.ModelAdmin):
    list_display = ["user", "slug", "title", "platform", "viewed_at"]
    search_fields = ["slug", "title"]

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import Invite, User, UserSession, UserSettings
from .services import auth as auth_service
from .services import invites as invite_service


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["email"]
    list_display = ["email", "is_staff", "is_active", "date_joined"]
    search_fields = ["email"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ["user", "theme", "max_concurrent_downloads", "debrid_enabled", "metadata_enabled"]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    """
    Registration is invite-only, so this page is how people get accounts.
    `manage.py createinvite` does the same thing from a shell.
    """

    list_display = ["__str__", "email", "status", "created_by", "used_by", "expires_at", "link"]
    list_filter = ["used_at", "expires_at"]
    search_fields = ["code", "email", "note"]
    readonly_fields = ["code", "used_at", "used_by", "link", "created_at", "updated_at"]
    fields = ["email", "note", "expires_at", "link", "code", "used_at", "used_by"]
    actions = ["create_batch"]

    @admin.display(description="Signup link")
    def link(self, obj: Invite):
        if obj.is_used:
            return "—"
        # Rendered as text, not an <a>: this URL points at the SPA, which the
        # admin isn't served from, and it exists to be copied rather than clicked.
        return format_html("<code>{}</code>", obj.signup_url)

    @admin.display(description="Status")
    def status(self, obj: Invite) -> str:
        return obj.status

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Create 5 more open invites")
    def create_batch(self, request, queryset):
        for _ in range(5):
            invite_service.create_invite(created_by=request.user)
        self.message_user(request, "Created 5 invites.")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "ip_address", "user_agent", "last_used_at", "expires_at", "revoked_at"]
    list_filter = ["revoked_at"]
    search_fields = ["user__email", "ip_address"]
    readonly_fields = [f.name for f in UserSession._meta.fields]
    actions = ["revoke"]

    @admin.action(description="Revoke selected sessions")
    def revoke(self, request, queryset):
        count = 0
        for session in queryset.filter(revoked_at__isnull=True):
            auth_service.revoke_session(session)
            count += 1
        self.message_user(request, f"Revoked {count} session(s).")

    def has_add_permission(self, request):
        # Sessions are created by logging in, never by hand.
        return False

from django.contrib import admin

from .models import EncryptedCredential


@admin.register(EncryptedCredential)
class EncryptedCredentialAdmin(admin.ModelAdmin):
    # Deliberately excludes `data` — it's ciphertext in the DB, but there's
    # no reason to even render the decrypted form in the admin.
    list_display = ("id", "user", "provider", "status", "failure_count", "last_validated_at")
    list_filter = ("provider", "status")
    search_fields = ("user__email",)
    readonly_fields = ("last_validated_at", "failure_count")

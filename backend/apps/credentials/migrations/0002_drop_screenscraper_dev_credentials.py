"""ScreenScraper's developer credentials moved from the per-user vault to
instance config (settings.SCREENSCRAPER_DEV_ID/_DEV_PASSWORD), because
ScreenScraper issues them per application rather than per user. Nothing
reads dev_id/dev_password out of EncryptedCredential.data any more, so any
already stored are dead secrets sitting at rest — drop them.

Irreversible on purpose: the reverse would have to invent secrets it never
had, and the forward direction destroys nothing anything still uses.
"""

from django.db import migrations

DEAD_KEYS = ("dev_id", "dev_password")


def drop_dev_credentials(apps, schema_editor):
    EncryptedCredential = apps.get_model("credentials", "EncryptedCredential")
    # Iterated rather than bulk-updated: `data` is an EncryptedJSONField, so
    # the values only exist as plaintext once the descriptor has decrypted
    # them — there is no queryset-level expression that can see inside.
    for credential in EncryptedCredential.objects.filter(provider="screenscraper"):
        data = credential.data or {}
        if not any(key in data for key in DEAD_KEYS):
            continue
        for key in DEAD_KEYS:
            data.pop(key, None)
        credential.data = data
        # Whatever it claimed before, it has not been checked against the new
        # instance-level developer pair.
        credential.status = "unverified"
        credential.save(update_fields=["data", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("credentials", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(drop_dev_credentials, migrations.RunPython.noop),
    ]

"""
Give every existing user the UserSettings row they should always have had.

Until now the row was created only by /auth/register, so anyone made by
`manage.py createsuperuser` or the admin's add form has none — and two readers
(downloads.tasks._should_extract, metadata.api.get_entry_metadata) treated the
missing row as "auto-extract off, metadata off", the opposite of the model's
own defaults. The post_save receiver added alongside this migration covers new
users; this covers the ones already in the database.

Every field takes its model default, which is exactly right: these users have
never expressed a preference, so the defaults are their preferences. The two
M2M fields stay empty, which is also their default state.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserSettings = apps.get_model("accounts", "UserSettings")

    missing = User.objects.filter(settings__isnull=True)
    UserSettings.objects.bulk_create([UserSettings(user_id=user_id) for user_id in missing.values_list("id", flat=True)])


def noop(apps, schema_editor):
    """Deliberately irreversible-but-harmless: rolling back just leaves the rows."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_backfill_user_sessions"),
    ]

    operations = [migrations.RunPython(backfill, noop)]

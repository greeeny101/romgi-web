from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_seed_platforms_regions"),
    ]

    operations = [
        migrations.RenameField(
            model_name="sourcehealth",
            old_name="reason",
            new_name="notes",
        ),
        migrations.AlterField(
            model_name="sourcehealth",
            name="status",
            field=models.CharField(
                choices=[("ok", "ok"), ("error", "error"), ("unknown", "unknown"), ("running", "running")],
                default="unknown",
                max_length=16,
            ),
        ),
    ]

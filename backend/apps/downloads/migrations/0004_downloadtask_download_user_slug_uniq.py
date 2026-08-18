import os
import shutil

from django.conf import settings as django_settings
from django.db import migrations, models


def drop_duplicate_tasks(apps, schema_editor):
    """Collapses the (user, slug) duplicates that accumulated while enqueue
    only refused to re-queue a title that was still in flight — once the
    first attempt finished it stopped matching that guard, so downloading
    the same title again appended a second row. Newest wins, matching the
    replace semantics enqueue now uses. Their staged directories go too,
    since cleanup_expired_staged_files walks rows and would never see them
    again."""
    DownloadTask = apps.get_model("downloads", "DownloadTask")
    seen: set[tuple[int, str]] = set()
    stale: list[int] = []
    for task_id, user_id, slug in DownloadTask.objects.order_by("-created_at", "-id").values_list(
        "id", "user_id", "slug"
    ):
        key = (user_id, slug)
        if key in seen:
            stale.append(task_id)
        else:
            seen.add(key)
    DownloadTask.objects.filter(id__in=stale).delete()
    for task_id in stale:
        shutil.rmtree(os.path.join(django_settings.STAGED_FILES_DIR, str(task_id)), ignore_errors=True)


class Migration(migrations.Migration):
    dependencies = [
        ("downloads", "0003_downloadtask_debrid_relink_attempts_and_more"),
    ]

    operations = [
        migrations.RunPython(drop_duplicate_tasks, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="downloadtask",
            constraint=models.UniqueConstraint(fields=["user", "slug"], name="download_user_slug_uniq"),
        ),
    ]

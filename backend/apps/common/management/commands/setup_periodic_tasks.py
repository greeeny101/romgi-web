"""
Seeds the Beat schedule (django_celery_beat's DatabaseScheduler reads from
DB rows, not code) for every task in the codebase that's meant to run on a
recurring cadence. Idempotent — safe to re-run on every deploy, which is
exactly how it's invoked (see docker-compose.yml's django service command).

A management command rather than a data migration: schedules are
operational config, not schema, and a re-runnable command lets a cadence
change ship as a normal code change instead of a new migration every time.
"""

from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Create/update the Beat schedule rows every periodic task needs to actually run."

    def handle(self, *args, **options):
        self._interval(
            name="Dispatch pending downloads",
            task="apps.downloads.tasks.dispatch_pending_downloads",
            every=5,
            period=IntervalSchedule.MINUTES,
        )
        self._interval(
            name="Clean up expired staged files",
            task="apps.downloads.tasks.cleanup_expired_staged_files",
            every=1,
            period=IntervalSchedule.HOURS,
        )
        self._interval(
            name="Poll active torrents",
            task="apps.torrents.tasks.poll_active_torrents",
            every=3,
            period=IntervalSchedule.SECONDS,
        )
        self._crontab(
            name="Run full catalog ingestion",
            task="apps.ingestion.tasks.run_full_ingestion",
            minute="0",
            hour="3",
            day_of_week="0",  # Sunday
        )
        self._crontab(
            name="Garbage-collect retired catalog builds",
            task="apps.ingestion.tasks.gc_old_builds",
            minute="0",
            hour="4",
        )
        self._crontab(
            name="Revalidate Internet Archive sessions",
            task="apps.credentials.tasks.internet_archive_revalidate",
            minute="0",
            hour="5",
        )
        self.stdout.write(self.style.SUCCESS("Periodic tasks are up to date."))

    def _interval(self, *, name: str, task: str, every: int, period: str) -> None:
        schedule, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
        PeriodicTask.objects.update_or_create(
            task=task,
            defaults={"name": name, "interval": schedule, "crontab": None, "enabled": True},
        )

    def _crontab(self, *, name: str, task: str, minute: str, hour: str, day_of_week: str = "*") -> None:
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week=day_of_week, day_of_month="*", month_of_year="*"
        )
        PeriodicTask.objects.update_or_create(
            task=task,
            defaults={"name": name, "crontab": schedule, "interval": None, "enabled": True},
        )

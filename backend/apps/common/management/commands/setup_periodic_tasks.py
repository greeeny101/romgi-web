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
            name="Dispatch pending BIOS downloads",
            task="apps.bios.tasks.dispatch_pending_bios",
            every=5,
            period=IntervalSchedule.MINUTES,
        )
        self._interval(
            name="Clean up expired staged files",
            task="apps.downloads.tasks.cleanup_expired_staged_files",
            every=1,
            period=IntervalSchedule.HOURS,
        )
        # The two polls carry an expiry, unlike everything else here. A poll
        # is only worth anything at the moment it fires: it reads live state
        # out of qBittorrent, so one that has been queued for four minutes
        # tells nobody anything a fresher one won't. Beat keeps producing them
        # whether or not a worker is consuming, so any worker downtime — a
        # restart, a breakpoint — leaves a backlog of roughly 20 messages a
        # minute that the worker then grinds through before it reaches
        # anything useful. Measured: a 131-deep backlog took ~70 seconds to
        # clear, and apply_selective_priority (the task that actually starts
        # a torrent transferring) sat behind all of it, so the download stayed
        # stopped at 0 bytes with nothing updating.
        #
        # Expiring them makes the backlog evaporate instead: Celery discards a
        # message past its expiry without running it, so the worker reaches
        # real work immediately and progress resumes updating on schedule.
        self._interval(
            name="Poll active torrents",
            task="apps.torrents.tasks.poll_active_torrents",
            every=3,
            period=IntervalSchedule.SECONDS,
            expire_seconds=30,
        )
        self._interval(
            name="Poll active ROM set downloads",
            task="apps.romsets.tasks.poll_active_romsets",
            every=5,
            period=IntervalSchedule.SECONDS,
            expire_seconds=30,
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
        self._crontab(
            name="Prune expired auth tokens and sessions",
            task="apps.accounts.tasks.prune_expired_tokens",
            minute="30",
            hour="5",
        )
        self.stdout.write(self.style.SUCCESS("Periodic tasks are up to date."))

    def _interval(self, *, name: str, task: str, every: int, period: str, expire_seconds: int | None = None) -> None:
        schedule, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
        PeriodicTask.objects.update_or_create(
            task=task,
            defaults={
                "name": name,
                "interval": schedule,
                "crontab": None,
                "enabled": True,
                # None clears it, so a cadence that stops needing an expiry
                # loses one on the next run rather than keeping a stale value.
                "expire_seconds": expire_seconds,
            },
        )

    def _crontab(self, *, name: str, task: str, minute: str, hour: str, day_of_week: str = "*") -> None:
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week=day_of_week, day_of_month="*", month_of_year="*"
        )
        PeriodicTask.objects.update_or_create(
            task=task,
            defaults={"name": name, "crontab": schedule, "interval": None, "enabled": True},
        )

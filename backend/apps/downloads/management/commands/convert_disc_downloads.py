"""
Repair already-completed downloads whose disc set was left in pieces.

extraction._pick_result hands back the largest extracted file. For a plain
archive (one ROM plus a readme) that is right; for a CD rip it is not — the set
is a .cue plus N .bin tracks, and picking the biggest track orphaned the sheet
and every other track. Those downloads reported complete and would not boot.

Everything is still on disk under `<task>/extracted/`, so this repairs in place
and nothing needs re-downloading: it runs the same chdman conversion the
pipeline now does (apps/downloads/chd.py), repoints staged_file at the .chd and
drops the tracks it was built from.

Dry-run by default — it deletes the extracted tracks once a conversion
succeeds, so the change has to be asked for.

    python manage.py convert_disc_downloads              # report what would change
    python manage.py convert_disc_downloads --apply      # commit it
    python manage.py convert_disc_downloads --apply --task 47

Safe to re-run: tasks already pointing at a .chd are skipped, and a task whose
conversion fails keeps its files exactly as they were.
"""

import os
import shutil

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand

from apps.downloads.chd import ChdConversionError, chd_output_path, convert_to_chd, find_disc_sheet
from apps.downloads.models import DownloadTask


class Command(BaseCommand):
    help = "Collapse already-downloaded multi-track disc sets into a single .chd."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Commit the conversions.")
        parser.add_argument("--task", type=int, help="Only this task id.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]

        tasks = DownloadTask.objects.filter(status="completed").exclude(staged_file="").order_by("id")
        if options.get("task"):
            tasks = tasks.filter(id=options["task"])

        candidates = []
        for task in tasks:
            directory = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id))
            extracted_dir = os.path.join(directory, "extracted")
            if task.staged_file.lower().endswith(".chd"):
                continue
            sheet = find_disc_sheet(extracted_dir)
            if sheet:
                candidates.append((task, directory, extracted_dir, sheet))

        if not candidates:
            self.stdout.write("No disc sets need converting.")
            return

        self.stdout.write(f"{len(candidates)} download(s) to convert:")
        for task, _, _, sheet in candidates:
            self.stdout.write(f"  [{task.id}] {task.title} — {os.path.basename(sheet)}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nDry run. Re-run with --apply to convert."))
            return

        converted = failed = 0
        for task, directory, extracted_dir, sheet in candidates:
            self.stdout.write(f"\n[{task.id}] {task.title}")
            chd_path = chd_output_path(sheet, directory)

            # chdman rewrites its progress line constantly; only redraw on a
            # whole percent, or the log is thousands of near-identical lines.
            last_percent = -1

            def report(fraction):
                nonlocal last_percent
                percent = int(fraction * 100)
                if percent != last_percent:
                    last_percent = percent
                    self.stdout.write(f"\r  converting… {percent:3d}%", ending="")
                    self.stdout.flush()

            try:
                convert_to_chd(sheet, chd_path, on_progress=report)
            except ChdConversionError as exc:
                # Leave everything untouched — the tracks are still the only
                # usable copy of this disc.
                if os.path.exists(chd_path):
                    os.remove(chd_path)
                self.stdout.write(self.style.ERROR(f"\r  failed: {exc}"))
                failed += 1
                continue

            size_mb = os.path.getsize(chd_path) / 1024 / 1024
            shutil.rmtree(extracted_dir, ignore_errors=True)
            task.staged_file = os.path.relpath(chd_path, directory)
            task.save(update_fields=["staged_file", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"\r  {task.staged_file} ({size_mb:.0f} MB)"))
            converted += 1

        self.stdout.write(self.style.SUCCESS(f"\nConverted {converted}."))
        if failed:
            self.stdout.write(self.style.ERROR(f"Failed {failed} — those keep their extracted tracks."))

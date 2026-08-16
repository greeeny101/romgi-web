"""
Ports Kotlin SevenZipServiceImpl.kt: .zip via `zipfile`, everything else
via `py7zr` (7z), both zip-slip guarded, 64KB chunks, throttled progress.

One deliberate adaptation: py7zr has no streaming per-entry writer like
Apache Commons Compress, so it can't be told "skip this one unsafe entry
and keep going" mid-extraction the way the Kotlin loop does. Instead the
whole archive is rejected up front if any entry's path would escape
output_dir — strictly safer than a partial per-entry skip, just less
granular.
"""

import os
import time
import zipfile

import py7zr

CHUNK_SIZE = 64 * 1024
PROGRESS_INTERVAL = 0.2


class ExtractionError(Exception):
    pass


def _safe_target(output_dir: str, member_name: str) -> str | None:
    out_dir_abs = os.path.abspath(output_dir)
    target_abs = os.path.abspath(os.path.join(output_dir, member_name))
    if target_abs == out_dir_abs or target_abs.startswith(out_dir_abs + os.sep):
        return target_abs
    return None


def extract_archive(archive_path: str, output_dir: str, on_progress=None) -> str:
    os.makedirs(output_dir, exist_ok=True)
    if archive_path.lower().endswith(".zip"):
        return _extract_zip(archive_path, output_dir, on_progress)
    return _extract_7z(archive_path, output_dir, on_progress)


def _extract_zip(archive_path: str, output_dir: str, on_progress) -> str:
    with zipfile.ZipFile(archive_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and i.file_size > 0]
        for info in infos:
            if _safe_target(output_dir, info.filename) is None:
                raise ExtractionError(f"Unsafe path in archive: {info.filename}")

        total_bytes = sum(i.file_size for i in infos)
        extracted = 0
        last_emit = 0.0
        extracted_files: list[str] = []

        for info in infos:
            target = _safe_target(output_dir, info.filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
                    extracted += len(chunk)
                    now = time.monotonic()
                    if on_progress and now - last_emit >= PROGRESS_INTERVAL:
                        on_progress(extracted, total_bytes)
                        last_emit = now
            extracted_files.append(target)

    if on_progress:
        on_progress(total_bytes, total_bytes)
    return _pick_result(extracted_files, output_dir)


def _extract_7z(archive_path: str, output_dir: str, on_progress) -> str:
    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        infos = archive.list()
        files = [f for f in infos if not f.is_directory]
        for f in files:
            if _safe_target(output_dir, f.filename) is None:
                raise ExtractionError(f"Unsafe path in archive: {f.filename}")

        total_bytes = sum(f.uncompressed for f in files)
        archive.extractall(path=output_dir)
        extracted_files = [
            path
            for f in files
            if (path := _safe_target(output_dir, f.filename)) and os.path.exists(path)
        ]

    if on_progress:
        on_progress(total_bytes, total_bytes)
    return _pick_result(extracted_files, output_dir)


def _pick_result(extracted_files: list[str], output_dir: str) -> str:
    """Matches SevenZipServiceImpl's result selection: the single extracted
    file, or the largest one if there were several, or the output dir."""
    if not extracted_files:
        return output_dir
    if len(extracted_files) == 1:
        return extracted_files[0]
    return max(extracted_files, key=os.path.getsize)

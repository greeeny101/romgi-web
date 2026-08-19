"""
Collapses a multi-track CD rip into a single .chd.

Why this exists: a download serves exactly one file (downloads.api's
download_file streams `staged_file`), but a CD rip extracts to a sheet plus N
track files that are only usable together. extraction._pick_result used to hand
back the largest track, which orphaned the .cue and every other track — the
download looked complete and the game wouldn't boot.

chdman (MAME's CHD tool, installed via mame-tools in the Dockerfile) reads the
sheet, follows it to the tracks, and writes one compressed .chd that every
mainstream CD emulator core reads directly. So the set becomes one file, which
is the shape the endpoint can actually deliver.

Only ever applied when a real disc sheet is present — a sheet is what makes a
pile of files a disc, and without one there's nothing for chdman to read.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# chdman createcd accepts all three. .gdi is Dreamcast's variant; .toc turns up
# on some PC Engine / Saturn rips.
DISC_SHEET_EXTENSIONS = (".cue", ".gdi", ".toc")

# "Compressing, 45.6% complete..." — carriage-return updates on one line.
_PROGRESS_RE = re.compile(rb"(\d+(?:\.\d+)?)\s*%")

# Generous: a dual-layer rip on a slow disk genuinely takes a while, and a
# conversion killed halfway is worse than one that runs long.
CONVERSION_TIMEOUT_SECONDS = 60 * 60


class ChdConversionError(Exception):
    pass


def find_disc_sheet(directory: str) -> str | None:
    """The sheet describing a disc in `directory`, or None if it isn't a disc.

    Picks the largest when there are several: a multi-disc archive can carry
    one sheet per disc, and the biggest is the one listing the most tracks.
    Ties break on name so the choice is stable across runs.
    """
    if not os.path.isdir(directory):
        return None
    sheets = [
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.lower().endswith(DISC_SHEET_EXTENSIONS)
    ]
    if not sheets:
        return None
    return max(sorted(sheets), key=os.path.getsize)


def convert_to_chd(sheet_path: str, output_path: str, on_progress=None) -> str:
    """Run `chdman createcd` over `sheet_path`, writing `output_path`.

    Returns the output path. Raises ChdConversionError if chdman is missing,
    fails, or produces nothing — callers must keep the extracted files until
    this returns, since a failure means the set is still the only usable copy.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # -f so a retry over a half-written .chd from a previous attempt overwrites
    # instead of failing on "file already exists".
    command = ["chdman", "createcd", "-i", sheet_path, "-o", output_path, "-f"]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # chdman rewrites its progress line with \r rather than \n, so line
            # buffering would block until the whole conversion finished.
            bufsize=0,
        )
    except FileNotFoundError as exc:
        raise ChdConversionError(
            "chdman not found — the worker image needs the mame-tools package"
        ) from exc

    tail: list[bytes] = []
    try:
        while True:
            chunk = process.stdout.read(256) if process.stdout else b""
            if not chunk:
                break
            tail.append(chunk)
            # Only the last few KB matter, and a stuck conversion shouldn't be
            # able to grow this without bound.
            if len(tail) > 64:
                del tail[:-64]
            if on_progress:
                matches = _PROGRESS_RE.findall(chunk)
                if matches:
                    on_progress(min(float(matches[-1]) / 100.0, 1.0))
        process.wait(timeout=CONVERSION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise ChdConversionError("chdman timed out") from exc
    finally:
        if process.stdout:
            process.stdout.close()

    output = b"".join(tail).decode("utf-8", "replace").strip()
    if process.returncode != 0:
        logger.warning("chdman failed for %s: %s", sheet_path, output[-2000:])
        raise ChdConversionError(f"chdman exited {process.returncode}")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ChdConversionError("chdman reported success but wrote no output")

    if on_progress:
        on_progress(1.0)
    return output_path


def chd_output_path(sheet_path: str, destination_dir: str) -> str:
    """`<destination_dir>/<sheet name>.chd` — the sheet is named for the game,
    unlike the tracks, which carry a "(Track 3)" suffix."""
    stem = os.path.splitext(os.path.basename(sheet_path))[0]
    return os.path.join(destination_dir, f"{stem}.chd")

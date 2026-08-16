"""
Ports the filename-sanitization half of lib/services/playlist_writer.dart.
The "wait for every group member" gate and the output format itself live in
downloads.tasks.write_playlist — see that module's docstring for why the
output is adapted (per-task API URLs, not shared on-device file paths).
"""

import re


def playlist_file_name(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f"{cleaned or 'playlist'}.m3u"

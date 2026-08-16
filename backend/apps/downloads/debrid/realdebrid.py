"""Ports lib/services/debrid/realdebrid_provider.dart 1:1."""

import requests

from .base import (
    DebridCaching,
    DebridError,
    DebridFileRequest,
    DebridNotCached,
    DebridProvider,
    DebridProviderInfo,
    DebridReady,
    DebridResult,
    sizes_close,
)

BASE_URL = "https://api.real-debrid.com/rest/1.0"
TIMEOUT = (10, 30)


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _auth_error(resp: requests.Response) -> DebridError | None:
    if resp.status_code in (401, 403):
        return DebridError("Invalid or expired token", auth_error=True)
    if resp.status_code == 429:
        return DebridError("Rate limited", rate_limited=True)
    return None


def _pick_file(files: list[dict], req: DebridFileRequest) -> dict | None:
    chosen = None
    if req.file_path:
        basename = req.file_path.rsplit("/", 1)[-1].lower()
        for f in files:
            path = (f.get("path") or "").lower()
            if path == basename or path.endswith("/" + basename):
                chosen = f
                break
    if chosen is None and 0 <= req.file_index < len(files):
        chosen = files[req.file_index]
    if chosen is None and len(files) == 1:
        chosen = files[0]
    if chosen is not None and req.expected_size > 0:
        if not sizes_close(int(chosen.get("bytes") or 0), req.expected_size):
            return None
    return chosen


def _link_for_file(files: list[dict], links: list[str], target: dict) -> str | None:
    selected = sorted((f for f in files if f.get("selected") == 1), key=lambda f: f["id"])
    for idx, f in enumerate(selected):
        if f.get("id") == target.get("id"):
            return links[idx] if idx < len(links) else None
    return None


class RealDebridProvider(DebridProvider):
    info = DebridProviderInfo(id="realdebrid", name="Real-Debrid")

    def validate_key(self, api_key: str) -> str | None:
        try:
            resp = requests.get(f"{BASE_URL}/user", headers=_headers(api_key), timeout=TIMEOUT)
        except requests.RequestException:
            return "Could not reach Real-Debrid"
        if resp.status_code in (401, 403):
            return "Invalid Real-Debrid token"
        if resp.status_code == 200:
            try:
                if isinstance(resp.json(), dict):
                    return None
            except ValueError:
                pass
        return f"Real-Debrid returned {resp.status_code}"

    def resolve_file(self, req: DebridFileRequest, api_key: str) -> DebridResult:
        try:
            return self._resolve(req, api_key)
        except requests.RequestException as exc:
            return DebridError(str(exc) or "Real-Debrid request failed")
        except Exception as exc:  # defensive — never let a malformed response crash the poll loop
            return DebridError(f"Real-Debrid error: {exc}")

    def _resolve(self, req: DebridFileRequest, api_key: str) -> DebridResult:
        headers = _headers(api_key)

        # Find-or-add: addMagnet isn't idempotent, so scan existing torrents
        # (up to 3 pages of 100) by infohash before adding a new one.
        torrent_id = None
        for page in range(1, 4):
            resp = requests.get(f"{BASE_URL}/torrents", headers=headers, params={"limit": 100, "page": page}, timeout=TIMEOUT)
            err = _auth_error(resp)
            if err:
                return err
            try:
                items = resp.json()
            except ValueError:
                items = None
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if (item.get("hash") or "").lower() == req.infohash:
                    torrent_id = item.get("id")
                    break
            if torrent_id or len(items) < 100:
                break

        if torrent_id is None:
            resp = requests.post(f"{BASE_URL}/torrents/addMagnet", headers=headers, data={"magnet": req.magnet}, timeout=TIMEOUT)
            err = _auth_error(resp)
            if err:
                return err
            try:
                torrent_id = resp.json().get("id")
            except ValueError:
                torrent_id = None
            if not torrent_id:
                return DebridError("Real-Debrid did not return an id")

        resp = requests.get(f"{BASE_URL}/torrents/info/{torrent_id}", headers=headers, timeout=TIMEOUT)
        err = _auth_error(resp)
        if err:
            return err
        if resp.status_code == 404:
            return DebridCaching()  # torrent vanished server-side; next poll re-adds by hash
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return DebridCaching()

        status = data.get("status")
        files = data.get("files") or []
        links = data.get("links") or []
        progress = data.get("progress")

        if status in ("magnet_conversion", "queued", "downloading", "compressing", "uploading"):
            return DebridCaching(progress=(progress / 100.0) if progress is not None else None)

        if status == "waiting_files_selection":
            target = _pick_file(files, req)
            if target is None:
                return DebridNotCached()
            resp = requests.post(
                f"{BASE_URL}/torrents/selectFiles/{torrent_id}", headers=headers, data={"files": str(target["id"])}, timeout=TIMEOUT
            )
            err = _auth_error(resp)
            if err:
                return err
            if resp.status_code == 404:
                return DebridCaching()
            if resp.status_code >= 400:
                return DebridError(f"Real-Debrid selectFiles failed ({resp.status_code})", permanent=True)
            return DebridCaching()

        if status == "downloaded":
            target = _pick_file(files, req)
            if target is None:
                return DebridNotCached()
            link = _link_for_file(files, links, target)
            if link is None:
                # Wrong file selected on a prior pass (stale torrent) —
                # drop it and let the next poll re-add + re-select fresh.
                requests.delete(f"{BASE_URL}/torrents/delete/{torrent_id}", headers=headers, timeout=TIMEOUT)
                return DebridCaching()
            resp = requests.post(f"{BASE_URL}/unrestrict/link", headers=headers, data={"link": link}, timeout=TIMEOUT)
            err = _auth_error(resp)
            if err:
                return err
            try:
                body = resp.json()
            except ValueError:
                body = {}
            url = (body or {}).get("download") or ""
            if url:
                size = body.get("filesize")
                return DebridReady(url=url, filename=body.get("filename"), size=int(size) if size else None)
            return DebridError("Real-Debrid did not return a link")

        if status in ("magnet_error", "dead"):
            return DebridNotCached()

        return DebridError(f"Real-Debrid status: {status}")

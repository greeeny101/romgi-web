"""Ports lib/services/debrid/torbox_provider.dart 1:1."""

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

BASE_URL = "https://api.torbox.app/v1/api"
TIMEOUT = (10, 30)

AUTH_ERROR_CODES = {"AUTH_ERROR", "BAD_TOKEN", "OAUTH_VERIFICATION_ERROR", "NO_AUTH"}
PERMANENT_ERROR_CODES = {
    "ACTIVE_LIMIT",
    "MONTHLY_LIMIT",
    "COOLDOWN_LIMIT",
    "DOWNLOAD_TOO_LARGE",
    "INVALID_MAGNET",
    "INVALID_TORRENT",
    "PLAN_RESTRICTED_FEATURE",
    "MISSING_REQUIRED_OPTION",
    "INVALID_OPTION",
}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _auth_error(resp: requests.Response) -> DebridError | None:
    if resp.status_code in (401, 403):
        return DebridError("Invalid or expired API key", auth_error=True)
    if resp.status_code == 429:
        return DebridError("Rate limited", rate_limited=True)
    return None


def _envelope_error(body) -> DebridError | None:
    if not isinstance(body, dict) or body.get("success") is not False:
        return None
    code = body.get("error") or ""
    detail = body.get("detail") or ""
    message = detail or code or "request failed"
    return DebridError(f"TorBox: {message}", auth_error=code in AUTH_ERROR_CODES, permanent=code in PERMANENT_ERROR_CODES)


def _pick_file_id(files: list[dict], req: DebridFileRequest):
    chosen = None
    if req.file_path:
        basename = req.file_path.rsplit("/", 1)[-1].lower()
        for f in files:
            name = (f.get("name") or "").lower()
            if name == basename or name.endswith("/" + basename):
                chosen = f
                break
    if chosen is None and 0 <= req.file_index < len(files):
        chosen = files[req.file_index]
    if chosen is None and len(files) == 1:
        chosen = files[0]
    if chosen is not None and req.expected_size > 0:
        if not sizes_close(int(chosen.get("size") or 0), req.expected_size):
            return None
    return chosen.get("id") if chosen else None


class TorboxProvider(DebridProvider):
    info = DebridProviderInfo(id="torbox", name="TorBox")

    def validate_key(self, api_key: str) -> str | None:
        try:
            resp = requests.get(f"{BASE_URL}/user/me", headers=_headers(api_key), timeout=TIMEOUT)
        except requests.RequestException:
            return "Could not reach TorBox"
        if resp.status_code in (401, 403):
            return "Invalid TorBox API key"
        if resp.status_code == 200:
            try:
                if isinstance(resp.json(), dict):
                    return None
            except ValueError:
                pass
        return f"TorBox returned {resp.status_code}"

    def resolve_file(self, req: DebridFileRequest, api_key: str) -> DebridResult:
        try:
            return self._resolve(req, api_key)
        except requests.RequestException as exc:
            return DebridError(str(exc) or "TorBox request failed")
        except Exception as exc:  # defensive — never let a malformed response crash the poll loop
            return DebridError(f"TorBox error: {exc}")

    def _resolve(self, req: DebridFileRequest, api_key: str) -> DebridResult:
        headers = _headers(api_key)

        # TorBox dedups by infohash server-side, so create-or-get is a
        # single idempotent call (unlike Real-Debrid's find-then-add).
        resp = requests.post(
            f"{BASE_URL}/torrents/createtorrent", headers=headers, data={"magnet": req.magnet, "allow_zip": "false"}, timeout=TIMEOUT
        )
        err = _auth_error(resp)
        if err:
            return err
        try:
            body = resp.json()
        except ValueError:
            body = {}
        err = _envelope_error(body)
        if err:
            return err
        data = body.get("data")
        torrent_id = data.get("torrent_id") if isinstance(data, dict) else None

        if torrent_id:
            resp = requests.get(
                f"{BASE_URL}/torrents/mylist", headers=headers, params={"id": torrent_id, "bypass_cache": "true"}, timeout=TIMEOUT
            )
            err = _auth_error(resp)
            if err:
                return err
            try:
                body = resp.json()
            except ValueError:
                body = {}
            err = _envelope_error(body)
            if err:
                return err
            data = body.get("data")
            torrent = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
        else:
            resp = requests.get(f"{BASE_URL}/torrents/mylist", headers=headers, params={"bypass_cache": "true"}, timeout=TIMEOUT)
            err = _auth_error(resp)
            if err:
                return err
            try:
                body = resp.json()
            except ValueError:
                body = {}
            err = _envelope_error(body)
            if err:
                return err
            torrent = None
            data = body.get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and (item.get("hash") or "").lower() == req.infohash:
                        torrent = item
                        break

        if torrent is None:
            return DebridCaching()  # freshly queued, not indexed by mylist yet

        torrent_id = torrent_id or torrent.get("id")
        present = torrent.get("download_present") is True
        finished = torrent.get("download_finished") is True
        progress = torrent.get("progress")  # TorBox reports 0.0-1.0 directly, no /100 needed

        if not (present and finished) or torrent_id is None:
            return DebridCaching(progress=progress)

        files = torrent.get("files") or []
        file_id = _pick_file_id(files, req)
        if file_id is None:
            return DebridNotCached()

        resp = requests.get(
            f"{BASE_URL}/torrents/requestdl",
            headers=headers,
            params={"token": api_key.strip(), "torrent_id": torrent_id, "file_id": file_id},
            timeout=TIMEOUT,
        )
        err = _auth_error(resp)
        if err:
            return err
        try:
            body = resp.json()
        except ValueError:
            body = {}
        err = _envelope_error(body)
        if err:
            return err
        url = body.get("data")
        if isinstance(url, str) and url:
            return DebridReady(url=url)
        return DebridError("TorBox did not return a download link")

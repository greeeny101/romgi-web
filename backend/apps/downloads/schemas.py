from ninja import Schema


class EnqueueIn(Schema):
    slug: str
    link_id: int | None = None
    group_id: int | None = None  # enqueue every member of a disc group


class DownloadTaskOut(Schema):
    id: int
    slug: str
    title: str
    platform_id: str
    status: str
    progress: float
    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: int
    link_name: str
    link_host: str
    link_is_torrent: bool
    error: str
    group_key: str
    group_title: str
    group_index: int | None
    playlist_file: str
    retry_count: int
    created_at: str
    completed_at: str | None


class VerifyResultOut(Schema):
    exists: bool
    message: str | None

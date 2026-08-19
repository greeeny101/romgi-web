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
    platform_name: str
    status: str
    progress: float
    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: int
    link_name: str
    link_host: str
    link_is_torrent: bool
    source_id: str | None
    source_name: str | None
    region_ids: list[str]
    error: str
    group_key: str
    group_title: str
    group_index: int | None
    playlist_file: str
    retry_count: int
    created_at: str
    completed_at: str | None
    # Whether the staged bytes are still on the server, and when they stop
    # being. A completed task outlives its file — cleanup_expired_staged_files
    # enforces STAGED_FILE_RETENTION_HOURS but keeps the row for history — so
    # "completed" on its own says nothing about whether Save file will work.
    file_available: bool
    expires_at: str | None
    # Size of the staged file as it will actually be saved, which is not
    # total_bytes: that records what came down the wire, and a CD rip that was
    # collapsed into a .chd is a fraction of it. None when nothing is staged.
    file_size: int | None
    # When the user first pulled the bytes down to their own machine, stamped
    # by download_file. Distinct from completed_at: that says the server has
    # the ROM, this says *you* do.
    first_retrieved_at: str | None
    # Moves on every save, unlike first_retrieved_at — this is what the
    # Library's Saved badge shows.
    last_retrieved_at: str | None

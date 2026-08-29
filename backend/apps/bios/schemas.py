from ninja import Schema


class BiosSourceOut(Schema):
    id: str
    name: str
    platform_id: str | None


class SearchResultOut(Schema):
    identifier: str
    title: str
    size: int
    downloads: int
    published: str | None


class SearchOut(Schema):
    items: list[SearchResultOut]
    total: int
    page: int
    page_size: int


class BiosFileOut(Schema):
    name: str
    size: int
    format: str | None = None
    md5: str | None = None


class ItemDetailOut(Schema):
    identifier: str
    title: str
    description: str
    collections: list[str]
    published: str | None
    item_size: int
    # archive.org's login-gated `loggedin` collection. Metadata stays public
    # for these; only /download/ is gated.
    restricted: bool
    # Straight from the metadata API, minus archive.org's own derived files
    # — unlike a romset, where the list has to come from the torrent. A BIOS
    # item is tens of files, so there is nothing to truncate.
    files: list[BiosFileOut]
    file_count: int
    total_size: int


class EnqueueBiosIn(Schema):
    identifier: str
    platform_id: str | None = None
    source_id: str = ""
    # Omitted means "every file in the item".
    names: list[str] | None = None
    extract: bool = False


class BiosDownloadFileOut(Schema):
    name: str
    size: int
    wanted: bool
    progress: float
    done: bool
    error: str


class BiosDownloadOut(Schema):
    id: int
    identifier: str
    title: str
    provider: str
    platform_id: str | None
    source_id: str
    status: str
    progress: float
    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: int
    save_dir: str
    extract: bool
    error: str
    file_count: int
    wanted_count: int
    created_at: str
    completed_at: str | None


class BiosDownloadDetailOut(BiosDownloadOut):
    files: list[BiosDownloadFileOut]

from ninja import Schema


class EmulatorOut(Schema):
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


class RomSetFileOut(Schema):
    path: str
    size: int
    format: str | None = None
    md5: str | None = None
    sha1: str | None = None


class SetFolderOut(Schema):
    """Top-level directory inside the torrent. `path` is "" for files that
    sit at the root."""

    path: str
    file_count: int
    size: int


class ItemDetailOut(Schema):
    identifier: str
    title: str
    description: str
    collections: list[str]
    published: str | None
    item_size: int
    infohash: str | None
    # archive.org's login-gated `loggedin` collection. Metadata stays public
    # for these; only /download/ is gated.
    restricted: bool
    # From the torrent, not the metadata API — the two lists differ in
    # membership, and only the torrent's can actually be downloaded.
    #
    # Capped: a MAME reference set is ~4,800 files, which is 760KB of JSON
    # and 4,800 checkboxes for a browser to lay out. Past the cap the client
    # selects by folder instead, and `files` is only a preview.
    files: list[RomSetFileOut]
    files_truncated: bool
    file_count: int
    folders: list[SetFolderOut]
    total_size: int


class EnqueueRomSetIn(Schema):
    identifier: str
    platform_id: str | None = None
    emulator_id: str = ""
    # Both omitted means "everything in the torrent". `folders` names
    # top-level directories and is expanded server-side, so selecting a
    # 4,736-file `roms/` folder costs one string rather than 4,736.
    paths: list[str] | None = None
    folders: list[str] | None = None
    extract: bool = False


class RomSetDownloadFileOut(Schema):
    path: str
    size: int
    wanted: bool
    progress: float
    done: bool


class RomSetDownloadOut(Schema):
    id: int
    identifier: str
    title: str
    provider: str
    platform_id: str | None
    emulator_id: str
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


class RomSetDownloadDetailOut(RomSetDownloadOut):
    # Capped for the same reason ItemDetailOut.files is: a MAME reference
    # set has ~4,800 of these, and pushing every one through Pydantic on
    # every enqueue and poll is both a large response and a memory spike
    # measured big enough to get the server killed on a busy machine.
    # `wanted_count`/`file_count` on the parent carry the real totals.
    files: list[RomSetDownloadFileOut]
    files_truncated: bool


class LibrarySpaceOut(Schema):
    free: int
    committed: int
    reserve: int
    available: int

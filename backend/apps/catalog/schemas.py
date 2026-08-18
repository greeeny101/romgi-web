from ninja import Schema


class PlatformOut(Schema):
    id: str
    brand: str
    name: str


class RegionOut(Schema):
    id: str
    name: str


class SourceOut(Schema):
    id: str
    name: str
    homepage: str | None
    kind: str
    auth_required: bool
    priority: int


class SourceHealthOut(Schema):
    source_id: str
    status: str
    last_checked_at: str | None
    notes: str | None
    entry_count: int
    link_count: int


class EntrySummaryOut(Schema):
    slug: str
    title: str
    platform_id: str
    boxart_url: str | None
    ra_game_id: int | None
    regions: list[str]


class EntryDetailOut(Schema):
    slug: str
    title: str
    rom_id: str | None
    platform_id: str
    boxart_url: str | None
    ra_game_id: int | None
    ra_num_achievements: int | None
    regions: list[str]
    group_id: int | None


class LinkOut(Schema):
    id: int
    name: str
    type: str
    format: str
    url: str
    filename: str
    host: str
    size: int
    size_str: str
    source_id: str | None
    requires_auth: bool
    is_torrent: bool
    torrent_file_index: int | None


class PaginatedEntries(Schema):
    items: list[EntrySummaryOut]
    total: int
    page: int
    page_size: int


class EntryGroupMemberOut(Schema):
    slug: str
    title: str
    member_index: int | None
    member_label: str | None


class EntryGroupOut(Schema):
    id: int
    kind: str
    title: str | None
    platform_id: str
    member_count: int
    members: list[EntryGroupMemberOut]

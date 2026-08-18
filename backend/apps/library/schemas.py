from ninja import Schema


class FavoriteOut(Schema):
    slug: str
    title: str
    platform_id: str
    boxart_url: str | None
    regions: list[str]
    created_at: str


class RecentlyViewedOut(Schema):
    slug: str
    title: str
    platform_id: str
    boxart_url: str | None
    regions: list[str]
    viewed_at: str

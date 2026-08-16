from ninja import Schema


class FavoriteOut(Schema):
    slug: str
    title: str
    platform_id: str
    boxart_url: str | None
    created_at: str


class RecentlyViewedOut(Schema):
    slug: str
    title: str
    platform_id: str
    boxart_url: str | None
    viewed_at: str

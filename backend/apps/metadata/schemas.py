from ninja import Schema


class GameMetadataOut(Schema):
    description: str | None
    screenshot_urls: list[str]
    artwork_urls: list[str]

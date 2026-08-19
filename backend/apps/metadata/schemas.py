from ninja import Schema


class MediaOut(Schema):
    # `thumb` is what the UI renders; `full` is the original the thumbnail
    # links out to. They're equal for providers with no thumbnail of their own.
    full: str
    thumb: str


class GameMetadataOut(Schema):
    description: str | None
    screenshots: list[MediaOut]
    artwork: list[MediaOut]

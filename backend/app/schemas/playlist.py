from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.job import QualityPreset


class PlaylistInspectItem(BaseModel):
    youtube_id: str
    url: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    position: int


class PlaylistMetadata(BaseModel):
    url: str
    title: str
    thumbnail: str | None = None
    uploader: str | None = None
    item_count: int
    items: list[PlaylistInspectItem]
    notice: str = "Only download or process videos you own or are permitted to use."


class PlaylistInspectRequest(BaseModel):
    url: str


class PlaylistCreateRequest(BaseModel):
    url: str
    selected_video_ids: list[str] = Field(min_length=1, max_length=100)
    preset: QualityPreset = QualityPreset.BALANCED


class PlaylistItemStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    ENHANCING = "enhancing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REMOVED = "removed"


class PlaylistStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlaylistItem(BaseModel):
    id: str
    youtube_id: str
    url: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    position: int
    status: PlaylistItemStatus = PlaylistItemStatus.QUEUED
    stage: str = "Queued"
    progress: float = 0
    video_id: str | None = None
    job_id: str | None = None
    error: str | None = None


class PlaylistRecord(BaseModel):
    id: str
    url: str
    title: str
    thumbnail: str | None = None
    uploader: str | None = None
    preset: QualityPreset
    status: PlaylistStatus = PlaylistStatus.QUEUED
    progress: float = 0
    items: list[PlaylistItem]
    created_at: datetime
    updated_at: datetime

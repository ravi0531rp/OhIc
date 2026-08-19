from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    UPLOAD = "upload"
    YOUTUBE = "youtube"


class VideoMetadata(BaseModel):
    width: int
    height: int
    resolution_label: str
    aspect_ratio: str
    fps: float
    frame_count: int | None = None
    duration: float
    video_codec: str
    audio_codec: str | None = None
    bitrate: int | None = None
    file_size: int
    pixel_format: str | None = None
    dynamic_range: str = "SDR"


class ResolutionTarget(BaseModel):
    width: int
    height: int
    label: str
    recommended: bool = False
    note: str | None = None


class VideoRecord(BaseModel):
    id: str
    source_type: SourceType
    original_name: str
    path: str = Field(exclude=True)
    metadata: VideoMetadata
    targets: list[ResolutionTarget]
    created_at: datetime
    playback_url: str
    title: str | None = None
    thumbnail: str | None = None
    uploader: str | None = None


class YouTubeInspectRequest(BaseModel):
    url: str


class YouTubeDownloadRequest(BaseModel):
    url: str


class YouTubeDownloadStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class YouTubeDownloadProgress(BaseModel):
    stage: str = "Queued"
    percent: float = 0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    attempt: int = 1


class YouTubeDownloadRecord(BaseModel):
    id: str
    url: str
    status: YouTubeDownloadStatus
    progress: YouTubeDownloadProgress
    created_at: datetime
    video: VideoRecord | None = None
    error: str | None = None


class YouTubeMetadata(BaseModel):
    url: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    notice: str = "Only download or process videos you own or are permitted to use."

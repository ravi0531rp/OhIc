from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    UPLOAD = "upload"
    YOUTUBE = "youtube"
    CAMERA = "camera"


class MediaTrack(BaseModel):
    index: int
    kind: str
    codec: str
    language: str | None = None
    title: str | None = None
    channels: int | None = None


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
    field_order: str = "progressive"
    tracks: list[MediaTrack] = Field(default_factory=list)
    chapters: int = 0
    title: str | None = None


class SourceIssue(BaseModel):
    code: str
    severity: str
    title: str
    detail: str


class EnhancementRecipe(BaseModel):
    name: str
    summary: str
    target_height: int
    preset: str
    model_id: str
    deinterlace: str = "off"
    reasons: list[str] = Field(default_factory=list)


class SourceDiagnosis(BaseModel):
    verdict: str
    confidence: str
    issues: list[SourceIssue]
    recipe: EnhancementRecipe


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
    diagnosis: SourceDiagnosis | None = None


class CameraSessionStatus(StrEnum):
    WAITING = "waiting"
    STREAMING = "streaming"
    PROCESSING = "processing"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CameraSession(BaseModel):
    id: str
    status: CameraSessionStatus = CameraSessionStatus.WAITING
    pairing_url: str
    frame_count: int = 0
    created_at: datetime
    video: VideoRecord | None = None
    error: str | None = None


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
    strategy: str = "Automatic"


class YouTubeDownloadRecord(BaseModel):
    id: str
    url: str
    status: YouTubeDownloadStatus
    progress: YouTubeDownloadProgress
    created_at: datetime
    video: VideoRecord | None = None
    error: str | None = None
    failure_code: str | None = None
    recovery_steps: list[str] = Field(default_factory=list)


class YouTubeReliabilityCheck(BaseModel):
    id: str
    label: str
    status: str
    detail: str


class YouTubeReliabilityReport(BaseModel):
    status: str
    yt_dlp_version: str
    node_version: str | None = None
    cookies_configured: bool = False
    po_token_provider: bool = False
    checks: list[YouTubeReliabilityCheck]
    recommendations: list[str]


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

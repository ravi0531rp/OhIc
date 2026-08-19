from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PROCESSING = "processing"
    ENCODING = "encoding"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualityPreset(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM = "maximum"


class JobKind(StrEnum):
    PREVIEW = "preview"
    FULL = "full"
    STREAM = "stream"


class StreamChunkStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCreate(BaseModel):
    video_id: str
    kind: JobKind = JobKind.PREVIEW
    target_width: int = Field(gt=0, le=7680)
    target_height: int = Field(gt=0, le=4320)
    preset: QualityPreset = QualityPreset.BALANCED
    model_id: str = "realesrgan-x2plus"
    preview_timestamp: float = Field(default=0, ge=0)
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    playlist_id: str | None = None


class JobProgress(BaseModel):
    stage: str = "Queued"
    percent: float = 0
    frames_done: int = 0
    frames_total: int | None = None
    processing_fps: float | None = None
    elapsed_seconds: float = 0
    eta_seconds: float | None = None
    detail: str | None = None


class StreamChunk(BaseModel):
    index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    status: StreamChunkStatus = StreamChunkStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=100)
    playback_url: str | None = None


class StreamState(BaseModel):
    chunk_duration: float = Field(gt=0)
    total_chunks: int = Field(gt=0)
    ready_chunks: int = Field(default=0, ge=0)
    buffered_seconds: float = Field(default=0, ge=0)
    chunks: list[StreamChunk]


class JobRecord(BaseModel):
    id: str
    video_id: str
    kind: JobKind
    status: JobStatus
    model_id: str = "realesrgan-x2plus"
    preset: QualityPreset
    target_width: int
    target_height: int
    preview_timestamp: float
    trim_start: float = 0
    trim_end: float | None = None
    playlist_id: str | None = None
    stream: StreamState | None = None
    progress: JobProgress
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_url: str | None = None
    original_preview_url: str | None = None
    output_path: str | None = Field(default=None, exclude=True)
    error: str | None = None
    processing_seconds: float | None = None

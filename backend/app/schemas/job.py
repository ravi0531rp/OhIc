from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.system import ResourceAllocation


class JobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PROCESSING = "processing"
    ENCODING = "encoding"
    PAUSED = "paused"
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


class OutputContainer(StrEnum):
    MP4 = "mp4"
    MKV = "mkv"


class TrackPolicy(StrEnum):
    COMPATIBLE = "compatible"
    PRESERVE = "preserve"


class ScanTreatment(StrEnum):
    AUTO = "auto"
    OFF = "off"
    DEINTERLACE = "deinterlace"
    IVTC = "ivtc"


class ResourcePolicy(StrEnum):
    AUTO = "auto"
    CONSERVATIVE = "conservative"
    PERFORMANCE = "performance"


class StreamChunkStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CheckpointSegmentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"


class CheckpointSegment(BaseModel):
    index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    status: CheckpointSegmentStatus = CheckpointSegmentStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=100)
    output_name: str
    checksum: str | None = None


class JobCheckpoint(BaseModel):
    version: int = 1
    source_fingerprint: str
    settings_signature: str
    segment_seconds: float = Field(gt=0)
    segments: list[CheckpointSegment]


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
    output_container: OutputContainer = OutputContainer.MP4
    track_policy: TrackPolicy = TrackPolicy.COMPATIBLE
    preserve_metadata: bool = True
    preserve_chapters: bool = True
    scan_treatment: ScanTreatment = ScanTreatment.AUTO
    resource_policy: ResourcePolicy = ResourcePolicy.AUTO
    memory_limit_mb: int | None = Field(default=None, ge=512)
    scene_aware: bool = True
    scene_threshold: float = Field(default=0.35, ge=0.1, le=0.9)


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
    output_container: OutputContainer = OutputContainer.MP4
    track_policy: TrackPolicy = TrackPolicy.COMPATIBLE
    preserve_metadata: bool = True
    preserve_chapters: bool = True
    scan_treatment: ScanTreatment = ScanTreatment.AUTO
    resource_policy: ResourcePolicy = ResourcePolicy.AUTO
    memory_limit_mb: int | None = None
    resource_allocation: ResourceAllocation | None = None
    scene_aware: bool = True
    scene_threshold: float = 0.35
    stream: StreamState | None = None
    checkpoint: JobCheckpoint | None = None
    recovered_after_restart: bool = False
    progress: JobProgress
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_url: str | None = None
    original_preview_url: str | None = None
    output_path: str | None = Field(default=None, exclude=True)
    error: str | None = None
    processing_seconds: float | None = None

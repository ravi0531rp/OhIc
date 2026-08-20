from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.job import (
    OutputContainer,
    QualityPreset,
    ResourcePolicy,
    ScanTreatment,
    TrackPolicy,
)


class BatchStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchItem(BaseModel):
    id: str
    video_id: str
    name: str
    job_id: str | None = None
    status: str = "queued"
    progress: float = 0
    error: str | None = None


class BatchCreateRequest(BaseModel):
    video_ids: list[str] = Field(min_length=1, max_length=100)
    preset_id: str | None = None
    preset: QualityPreset = QualityPreset.BALANCED


class BatchRecord(BaseModel):
    id: str
    name: str
    status: BatchStatus
    progress: float = 0
    preset_id: str | None = None
    items: list[BatchItem]
    created_at: datetime
    updated_at: datetime


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_height: int | None = Field(default=None, ge=240, le=4320)
    quality: QualityPreset = QualityPreset.BALANCED
    model_id: str = "realesrgan-x2plus"
    output_container: OutputContainer = OutputContainer.MP4
    track_policy: TrackPolicy = TrackPolicy.COMPATIBLE
    scan_treatment: ScanTreatment = ScanTreatment.AUTO
    resource_policy: ResourcePolicy = ResourcePolicy.AUTO
    memory_limit_mb: int | None = Field(default=None, ge=512)
    scene_aware: bool = True
    scene_threshold: float = Field(default=0.35, ge=0.1, le=0.9)


class PresetRecord(PresetCreate):
    id: str
    created_at: datetime

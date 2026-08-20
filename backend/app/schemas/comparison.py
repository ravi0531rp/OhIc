from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.job import QualityPreset, ScanTreatment


class ComparisonStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComparisonVariant(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    target_width: int = Field(gt=0, le=7680)
    target_height: int = Field(gt=0, le=4320)
    preset: QualityPreset
    model_id: str = "realesrgan-x2plus"
    scan_treatment: ScanTreatment = ScanTreatment.AUTO


class ComparisonCreate(BaseModel):
    video_id: str
    timestamp: float = Field(default=0, ge=0)
    variants: list[ComparisonVariant] = Field(min_length=2, max_length=4)


class ComparisonItem(ComparisonVariant):
    id: str
    job_id: str | None = None
    status: str = "queued"
    progress: float = 0
    output_url: str | None = None
    error: str | None = None


class ComparisonRecord(BaseModel):
    id: str
    video_id: str
    timestamp: float
    status: ComparisonStatus
    progress: float = 0
    items: list[ComparisonItem]
    created_at: datetime
    updated_at: datetime

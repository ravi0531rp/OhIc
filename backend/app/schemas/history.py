from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class HistoryEntryKind(StrEnum):
    ENHANCEMENT = "enhancement"
    CAMERA = "camera"
    PRO = "pro"


class HistoryEntry(BaseModel):
    id: str
    kind: HistoryEntryKind
    reference_id: str
    video_id: str
    title: str
    detail: str
    status: str
    progress: float = Field(default=0, ge=0, le=100)
    stage: str
    created_at: datetime
    updated_at: datetime
    can_pause: bool = False
    can_cancel: bool = False

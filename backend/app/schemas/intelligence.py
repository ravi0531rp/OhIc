from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProSetupState(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    READY = "ready"
    ERROR = "error"


class ProStatus(BaseModel):
    state: ProSetupState = ProSetupState.NOT_INSTALLED
    supported: bool = True
    platform: str = ""
    progress: float = 0
    stage: str = "Pro is optional"
    detail: str = "Nothing has been downloaded."
    qwen_model: str = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    hinglish_model: str = "Trelis/tara"
    detector_model: str = "RF-DETR Small + ByteTrack"
    estimated_download_bytes: int = 10_500_000_000
    installed_at: datetime | None = None
    error: str | None = None


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    TRACKING = "tracking"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscriptWord(BaseModel):
    text: str
    start: float
    end: float
    confidence: float | None = None


class TranscriptSegment(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class BoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class SubjectAppearance(BaseModel):
    start: float
    end: float
    box: BoundingBox
    confidence: float = Field(default=0.5, ge=0, le=1)


class SubjectRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    label: str
    kind: Literal["person", "object"] = "person"
    color: str = "#c7ff47"
    identity_id: str | None = None
    appearances: list[SubjectAppearance] = Field(default_factory=list)
    thumbnail_url: str | None = None


class KeyframeRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: float
    image_url: str


class VideoAnalysis(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    video_id: str
    video_name: str | None = None
    status: AnalysisStatus = AnalysisStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=100)
    stage: str = "Waiting to start"
    transcript_language: str | None = None
    transcription_engine: Literal["whisper_multilingual", "tara_hinglish"] = "whisper_multilingual"
    tracking_model: str = "rf-detr-small+bytetrack"
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    subjects: list[SubjectRecord] = Field(default_factory=list)
    keyframes: list[KeyframeRecord] = Field(default_factory=list)
    subtitle_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class AnalysisCreateRequest(BaseModel):
    video_id: str
    transcribe: bool = True
    track_people: bool = True
    track_objects: bool = True
    transcript_language: str | None = Field(default=None, max_length=12)
    transcription_engine: Literal["whisper_multilingual", "tara_hinglish"] = "whisper_multilingual"


class IdentityRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=500)
    color: str = "#c7ff47"
    reference_thumbnail_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IdentityCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=500)


class SubjectIdentityRequest(BaseModel):
    identity_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)


class EvidenceCitation(BaseModel):
    start: float
    end: float
    label: str
    kind: Literal["transcript", "subject", "frame", "metadata"]
    image_url: str | None = None


class ToolExecution(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)
    result_count: int = 0


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant"]
    content: str
    citations: list[EvidenceCitation] = Field(default_factory=list)
    tool_calls: list[ToolExecution] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ChatSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    analysis_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    current_time: float | None = Field(default=None, ge=0)
    retrieval_sources: set[Literal["transcript", "visual"]] = Field(
        default_factory=lambda: {"transcript", "visual"}, min_length=1
    )


class ChatResponse(BaseModel):
    session: ChatSession
    message: ChatMessage

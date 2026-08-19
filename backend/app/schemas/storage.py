from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class StorageItemKind(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    OUTPUT = "output"


class StorageItem(BaseModel):
    id: str
    kind: StorageItemKind
    name: str
    size: int
    created_at: datetime
    detail: str
    active: bool = False


class StorageCleanupRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class StorageCleanupResult(BaseModel):
    removed_ids: list[str]
    bytes_freed: int

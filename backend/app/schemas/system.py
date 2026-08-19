from pydantic import BaseModel


class DependencyStatus(BaseModel):
    available: bool
    path: str | None = None
    message: str | None = None


class HardwareInfo(BaseModel):
    device: str
    display_name: str
    acceleration: str
    memory_gb: float | None = None


class HealthResponse(BaseModel):
    status: str
    ffmpeg: DependencyStatus
    ffprobe: DependencyStatus
    hardware: HardwareInfo
    version: str = "0.1.0"

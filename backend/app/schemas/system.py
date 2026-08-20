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


class ResourceSnapshot(BaseModel):
    total_memory_mb: int
    available_memory_mb: int
    memory_pressure: str
    cpu_count: int
    load_average: float


class ResourceAllocation(BaseModel):
    policy: str
    tile_size: int
    temporal_window: int
    max_parallel_jobs: int
    available_memory_mb: int
    memory_pressure: str
    rationale: str

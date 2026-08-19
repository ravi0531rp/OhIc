from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_prefix="OHIC_", extra="ignore"
    )

    app_name: str = "OhIc"
    host: str = "127.0.0.1"
    port: int = 8000
    frontend_origin: str = "http://localhost:3000"
    data_dir: Path = Field(default_factory=lambda: Path(__file__).parents[3] / "data")
    model_dir: Path | None = None
    max_upload_gb: float = 20.0
    default_model: str = "realesrgan-x2plus"
    default_codec: str = "h264"
    log_level: str = "INFO"
    stale_temp_hours: int = 24

    @property
    def resolved_model_dir(self) -> Path:
        return self.model_dir or self.data_dir / "models"

    def ensure_directories(self) -> None:
        for name in ("uploads", "downloads", "jobs", "outputs", "temp"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        self.resolved_model_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

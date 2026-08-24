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
    camera_port: int = Field(default=0, ge=0, le=65535)
    camera_pairing_base_url: str | None = None
    data_dir: Path = Field(default_factory=lambda: Path(__file__).parents[3] / "data")
    model_dir: Path | None = None
    max_upload_gb: float = 20.0
    default_model: str = "realesrgan-x2plus"
    default_codec: str = "h264"
    enable_realbasicvsr: bool = True
    log_level: str = "INFO"
    stale_temp_hours: int = 24
    checkpoint_seconds: float = Field(default=30.0, ge=5.0, le=300.0)
    youtube_cookies_file: Path | None = None
    pro_test_mode: bool = False
    pro_qwen_model: str | None = None
    pro_whisper_model: str | None = None

    @property
    def resolved_model_dir(self) -> Path:
        return self.model_dir or self.data_dir / "models"

    def ensure_directories(self) -> None:
        for name in ("uploads", "downloads", "jobs", "outputs", "temp", "intelligence"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        self.resolved_model_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

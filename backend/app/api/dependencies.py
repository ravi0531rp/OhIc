from functools import lru_cache

from app.core.config import get_settings
from app.inference.registry import ModelRegistry
from app.jobs.manager import JobManager
from app.models.database import Database
from app.services.batches import BatchManager
from app.services.comparisons import ComparisonManager
from app.services.playlists import PlaylistManager
from app.services.storage import StorageService
from app.services.videos import VideoService
from app.services.youtube import YouTubeService
from app.services.youtube_downloads import YouTubeDownloadManager


@lru_cache
def get_database() -> Database:
    settings = get_settings()
    return Database(settings.data_dir / "ohic.sqlite3")


@lru_cache
def get_registry() -> ModelRegistry:
    return ModelRegistry(enable_realbasicvsr=get_settings().enable_realbasicvsr)


@lru_cache
def get_video_service() -> VideoService:
    return VideoService(get_settings(), get_database())


@lru_cache
def get_youtube_service() -> YouTubeService:
    settings = get_settings()
    return YouTubeService(settings.data_dir / "downloads", settings.youtube_cookies_file)


@lru_cache
def get_youtube_download_manager() -> YouTubeDownloadManager:
    return YouTubeDownloadManager(get_youtube_service(), get_video_service())


@lru_cache
def get_storage_service() -> StorageService:
    return StorageService(get_settings(), get_database())


@lru_cache
def get_playlist_manager() -> PlaylistManager:
    return PlaylistManager(
        get_database(), get_youtube_service(), get_video_service(), get_job_manager()
    )


@lru_cache
def get_batch_manager() -> BatchManager:
    return BatchManager(get_database(), get_job_manager())


@lru_cache
def get_comparison_manager() -> ComparisonManager:
    return ComparisonManager(get_database(), get_job_manager())


@lru_cache
def get_job_manager() -> JobManager:
    return JobManager(get_settings(), get_database(), get_registry())

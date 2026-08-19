import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.schemas.video import (
    YouTubeDownloadProgress,
    YouTubeDownloadRecord,
    YouTubeDownloadStatus,
)
from app.services.videos import VideoService
from app.services.youtube import YouTubeService
from app.utils.files import validate_youtube_url


class YouTubeDownloadManager:
    def __init__(self, youtube: YouTubeService, videos: VideoService):
        self.youtube = youtube
        self.videos = videos
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-youtube")
        self._records: dict[str, YouTubeDownloadRecord] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def start(self, url: str) -> YouTubeDownloadRecord:
        safe_url = validate_youtube_url(url)
        active_statuses = {
            YouTubeDownloadStatus.QUEUED,
            YouTubeDownloadStatus.DOWNLOADING,
            YouTubeDownloadStatus.PROCESSING,
        }
        with self._lock:
            existing = next(
                (
                    item
                    for item in self._records.values()
                    if item.url == safe_url and item.status in active_statuses
                ),
                None,
            )
            if existing:
                return existing.model_copy(deep=True)
            record = YouTubeDownloadRecord(
                id=str(uuid.uuid4()),
                url=safe_url,
                status=YouTubeDownloadStatus.QUEUED,
                progress=YouTubeDownloadProgress(),
                created_at=datetime.now(UTC),
            )
            self._records[record.id] = record
            self._cancel_events[record.id] = threading.Event()
        self.executor.submit(self._execute, record.id, safe_url)
        return record.model_copy(deep=True)

    def get(self, download_id: str) -> YouTubeDownloadRecord | None:
        with self._lock:
            record = self._records.get(download_id)
            return record.model_copy(deep=True) if record else None

    def cancel(self, download_id: str) -> YouTubeDownloadRecord | None:
        with self._lock:
            record = self._records.get(download_id)
            if not record:
                return None
            if record.status in {
                YouTubeDownloadStatus.COMPLETE,
                YouTubeDownloadStatus.FAILED,
                YouTubeDownloadStatus.CANCELLED,
            }:
                return record.model_copy(deep=True)
            self._cancel_events[download_id].set()
            record.status = YouTubeDownloadStatus.CANCELLED
            record.progress = YouTubeDownloadProgress(
                stage="Cancelled", percent=record.progress.percent, attempt=record.progress.attempt
            )
            return record.model_copy(deep=True)

    def _update(self, download_id: str, **values) -> None:
        with self._lock:
            record = self._records[download_id]
            for key, value in values.items():
                setattr(record, key, value)

    def _execute(self, download_id: str, url: str) -> None:
        current_attempt = 1
        maximum_percent = 0.0
        cancel_event = self._cancel_events[download_id]

        def attempt_hook(attempt: int) -> None:
            nonlocal current_attempt, maximum_percent
            if cancel_event.is_set():
                raise InterruptedError("YouTube download cancelled.")
            current_attempt = attempt
            maximum_percent = 0
            self._update(
                download_id,
                status=YouTubeDownloadStatus.DOWNLOADING,
                progress=YouTubeDownloadProgress(
                    stage=(
                        "Connecting to YouTube" if attempt == 1 else "Trying another YouTube format"
                    ),
                    attempt=attempt,
                ),
            )

        def progress_hook(data: dict) -> None:
            nonlocal maximum_percent
            if cancel_event.is_set():
                raise InterruptedError("YouTube download cancelled.")
            status = data.get("status")
            downloaded = int(data.get("downloaded_bytes") or 0)
            total_value = data.get("total_bytes") or data.get("total_bytes_estimate")
            total = int(total_value) if total_value else None
            percent = min(99.0, downloaded * 100 / total) if total else maximum_percent
            maximum_percent = max(maximum_percent, percent)
            stage = (
                "Combining video and audio" if status == "finished" else "Downloading from YouTube"
            )
            self._update(
                download_id,
                status=(
                    YouTubeDownloadStatus.PROCESSING
                    if status == "finished"
                    else YouTubeDownloadStatus.DOWNLOADING
                ),
                progress=YouTubeDownloadProgress(
                    stage=stage,
                    percent=maximum_percent,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed=data.get("speed"),
                    eta=data.get("eta"),
                    attempt=current_attempt,
                ),
            )

        try:
            if cancel_event.is_set():
                return
            path, info = self.youtube.download(
                url, progress_hook, attempt_hook, cancel_event.is_set
            )
            if cancel_event.is_set():
                path.unlink(missing_ok=True)
                return
            self._update(
                download_id,
                status=YouTubeDownloadStatus.PROCESSING,
                progress=YouTubeDownloadProgress(
                    stage="Inspecting downloaded video", percent=99, attempt=current_attempt
                ),
            )
            video = self.videos.register_download(
                path,
                info["safe_title"],
                info.get("title"),
                info.get("thumbnail"),
                info.get("uploader") or info.get("channel"),
            )
            self._update(
                download_id,
                status=YouTubeDownloadStatus.COMPLETE,
                progress=YouTubeDownloadProgress(
                    stage="Ready", percent=100, attempt=current_attempt
                ),
                video=video,
            )
        except Exception as exc:
            if cancel_event.is_set() or isinstance(exc, InterruptedError):
                self._update(
                    download_id,
                    status=YouTubeDownloadStatus.CANCELLED,
                    progress=YouTubeDownloadProgress(
                        stage="Cancelled", percent=maximum_percent, attempt=current_attempt
                    ),
                )
            else:
                self._update(
                    download_id,
                    status=YouTubeDownloadStatus.FAILED,
                    error=str(exc)[:500],
                )

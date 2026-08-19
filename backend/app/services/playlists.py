import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import structlog

from app.jobs.manager import JobManager
from app.models.database import Database
from app.schemas.job import JobCreate, JobKind, JobStatus
from app.schemas.playlist import (
    PlaylistCreateRequest,
    PlaylistItem,
    PlaylistItemStatus,
    PlaylistRecord,
    PlaylistStatus,
)
from app.services.videos import VideoService
from app.services.youtube import YouTubeService

logger = structlog.get_logger()


class PlaylistManager:
    def __init__(
        self,
        database: Database,
        youtube: YouTubeService,
        videos: VideoService,
        jobs: JobManager,
    ):
        self.database = database
        self.youtube = youtube
        self.videos = videos
        self.jobs = jobs
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-playlist")
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def create(self, request: PlaylistCreateRequest) -> PlaylistRecord:
        metadata = self.youtube.inspect_playlist(request.url)
        selected_ids = set(request.selected_video_ids)
        selected = [item for item in metadata.items if item.youtube_id in selected_ids]
        if len(selected) != len(selected_ids):
            raise ValueError("One or more selected videos are not part of this playlist.")
        now = datetime.now(UTC)
        record = PlaylistRecord(
            id=str(uuid.uuid4()),
            url=metadata.url,
            title=metadata.title,
            thumbnail=metadata.thumbnail,
            uploader=metadata.uploader,
            preset=request.preset,
            items=[PlaylistItem(id=str(uuid.uuid4()), **item.model_dump()) for item in selected],
            created_at=now,
            updated_at=now,
        )
        cancel = threading.Event()
        with self._lock:
            self._cancel[record.id] = cancel
            self.database.save_playlist(record)
        self.executor.submit(self._execute, record.id)
        logger.info("playlist_created", playlist_id=record.id, videos=len(record.items))
        return record

    def get(self, playlist_id: str) -> PlaylistRecord | None:
        record = self.database.get_playlist(playlist_id)
        return self._reconcile(record) if record else None

    def list(self, limit: int = 50) -> list[PlaylistRecord]:
        return [self._reconcile(record) for record in self.database.list_playlists(limit)]

    def _reconcile(self, record: PlaylistRecord) -> PlaylistRecord:
        changed = False
        for item in record.items:
            if item.status != PlaylistItemStatus.COMPLETE:
                continue
            if (item.video_id and not self.database.get_video(item.video_id)) or (
                item.job_id and not self.database.get_job(item.job_id)
            ):
                item.status = PlaylistItemStatus.REMOVED
                item.stage = "Local files removed"
                item.progress = 0
                changed = True
        if changed:
            record.updated_at = datetime.now(UTC)
            self.database.save_playlist(record)
        return record

    @staticmethod
    def _refresh_progress(record: PlaylistRecord) -> None:
        record.progress = (
            sum(item.progress for item in record.items) / len(record.items) if record.items else 0
        )
        record.updated_at = datetime.now(UTC)

    def _mutate(self, playlist_id: str, update: Callable[[PlaylistRecord], None]) -> PlaylistRecord:
        with self._lock:
            record = self.database.get_playlist(playlist_id)
            if not record:
                raise ValueError("Playlist not found.")
            update(record)
            self._refresh_progress(record)
            self.database.save_playlist(record)
            return record

    def _update_item(self, playlist_id: str, item_id: str, **values) -> PlaylistRecord:
        def update(record: PlaylistRecord) -> None:
            item = next(item for item in record.items if item.id == item_id)
            for key, value in values.items():
                setattr(item, key, value)

        return self._mutate(playlist_id, update)

    def _execute(self, playlist_id: str) -> None:
        cancel = self._cancel[playlist_id]
        record = self._mutate(
            playlist_id, lambda value: setattr(value, "status", PlaylistStatus.RUNNING)
        )
        try:
            for item_snapshot in record.items:
                if cancel.is_set():
                    break
                item_id = item_snapshot.id
                self._update_item(
                    playlist_id,
                    item_id,
                    status=PlaylistItemStatus.DOWNLOADING,
                    stage="Connecting to YouTube",
                    progress=1,
                    error=None,
                )
                last_saved = 0.0

                def download_progress(data: dict, item_id: str = item_id) -> None:
                    nonlocal last_saved
                    if cancel.is_set():
                        raise InterruptedError("Playlist cancelled")
                    now = time.monotonic()
                    if now - last_saved < 0.3 and data.get("status") != "finished":
                        return
                    downloaded = int(data.get("downloaded_bytes") or 0)
                    total = data.get("total_bytes") or data.get("total_bytes_estimate")
                    percent = downloaded * 100 / total if total else 0
                    self._update_item(
                        playlist_id,
                        item_id,
                        stage=(
                            "Preparing downloaded video"
                            if data.get("status") == "finished"
                            else "Downloading"
                        ),
                        progress=min(15, max(1, percent * 0.15)),
                    )
                    last_saved = now

                try:
                    path, info = self.youtube.download(
                        item_snapshot.url, progress_hook=download_progress
                    )
                    if cancel.is_set():
                        raise InterruptedError("Playlist cancelled")
                    video = self.videos.register_download(
                        path,
                        info["safe_title"],
                        info.get("title"),
                        info.get("thumbnail"),
                        info.get("uploader") or info.get("channel"),
                    )
                    target = next(
                        (target for target in video.targets if target.recommended),
                        video.targets[0],
                    )
                    job = self.jobs.create(
                        JobCreate(
                            video_id=video.id,
                            kind=JobKind.FULL,
                            target_width=target.width,
                            target_height=target.height,
                            preset=record.preset,
                            playlist_id=playlist_id,
                        )
                    )
                    self._update_item(
                        playlist_id,
                        item_id,
                        status=PlaylistItemStatus.ENHANCING,
                        stage="Queued for enhancement",
                        progress=15,
                        video_id=video.id,
                        job_id=job.id,
                    )
                    while True:
                        if cancel.is_set():
                            self.jobs.cancel(job.id)
                        current = self.database.get_job(job.id)
                        if not current:
                            raise RuntimeError("The playlist enhancement job disappeared.")
                        if current.status in {
                            JobStatus.COMPLETE,
                            JobStatus.FAILED,
                            JobStatus.CANCELLED,
                        }:
                            break
                        self._update_item(
                            playlist_id,
                            item_id,
                            stage=current.progress.stage,
                            progress=15 + current.progress.percent * 0.85,
                        )
                        time.sleep(0.5)
                    if current.status == JobStatus.COMPLETE:
                        self._update_item(
                            playlist_id,
                            item_id,
                            status=PlaylistItemStatus.COMPLETE,
                            stage="Complete",
                            progress=100,
                        )
                    elif current.status == JobStatus.CANCELLED:
                        self._update_item(
                            playlist_id,
                            item_id,
                            status=PlaylistItemStatus.CANCELLED,
                            stage="Cancelled",
                            progress=0,
                        )
                    else:
                        self._update_item(
                            playlist_id,
                            item_id,
                            status=PlaylistItemStatus.FAILED,
                            stage="Enhancement failed",
                            error=current.error,
                            progress=0,
                        )
                except InterruptedError:
                    self._update_item(
                        playlist_id,
                        item_id,
                        status=PlaylistItemStatus.CANCELLED,
                        stage="Cancelled",
                        progress=0,
                    )
                    break
                except Exception as exc:
                    if cancel.is_set():
                        self._update_item(
                            playlist_id,
                            item_id,
                            status=PlaylistItemStatus.CANCELLED,
                            stage="Cancelled",
                            progress=0,
                        )
                        break
                    logger.exception(
                        "playlist_item_failed", playlist_id=playlist_id, item_id=item_id
                    )
                    self._update_item(
                        playlist_id,
                        item_id,
                        status=PlaylistItemStatus.FAILED,
                        stage="Failed",
                        error=str(exc)[:500],
                        progress=0,
                    )
            final = self.database.get_playlist(playlist_id)
            if not final:
                return
            if cancel.is_set():
                for item in final.items:
                    if item.status == PlaylistItemStatus.QUEUED:
                        item.status = PlaylistItemStatus.CANCELLED
                        item.stage = "Cancelled"
                final.status = PlaylistStatus.CANCELLED
            else:
                completed = sum(item.status == PlaylistItemStatus.COMPLETE for item in final.items)
                failed = sum(item.status == PlaylistItemStatus.FAILED for item in final.items)
                if completed == len(final.items):
                    final.status = PlaylistStatus.COMPLETE
                elif completed:
                    final.status = PlaylistStatus.PARTIAL
                elif failed:
                    final.status = PlaylistStatus.FAILED
                else:
                    final.status = PlaylistStatus.CANCELLED
            self._refresh_progress(final)
            self.database.save_playlist(final)
        finally:
            with self._lock:
                self._cancel.pop(playlist_id, None)

    def cancel(self, playlist_id: str) -> PlaylistRecord:
        record = self.database.get_playlist(playlist_id)
        if not record:
            raise ValueError("Playlist not found.")
        if record.status not in {PlaylistStatus.QUEUED, PlaylistStatus.RUNNING}:
            return record
        with self._lock:
            event = self._cancel.get(playlist_id)
            if event:
                event.set()
            else:
                record.status = PlaylistStatus.CANCELLED
        for item in record.items:
            if item.job_id and item.status == PlaylistItemStatus.ENHANCING:
                self.jobs.cancel(item.job_id)
            elif item.status in {
                PlaylistItemStatus.QUEUED,
                PlaylistItemStatus.DOWNLOADING,
            }:
                item.stage = "Stopping…"
        record.updated_at = datetime.now(UTC)
        self.database.save_playlist(record)
        return record

    def delete(self, playlist_id: str) -> None:
        record = self.database.get_playlist(playlist_id)
        if not record:
            raise ValueError("Playlist not found.")
        if record.status in {PlaylistStatus.QUEUED, PlaylistStatus.RUNNING} or (
            playlist_id in self._cancel
        ):
            raise ValueError("Stop this playlist before removing it.")
        self.database.delete_playlist(playlist_id)

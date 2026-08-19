from pathlib import Path

from app.core.config import Settings
from app.models.database import Database
from app.schemas.job import JobStatus
from app.schemas.storage import StorageCleanupResult, StorageItem, StorageItemKind
from app.schemas.video import SourceType
from app.utils.files import ensure_within

ACTIVE_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.PREPARING,
    JobStatus.PROCESSING,
    JobStatus.ENCODING,
}


class StorageService:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.outputs_dir = settings.data_dir / "outputs"

    @staticmethod
    def _size(path: Path) -> int:
        return path.stat().st_size if path.exists() and path.is_file() else 0

    def items(self) -> list[StorageItem]:
        items: list[StorageItem] = []
        for video in self.database.list_videos():
            jobs = self.database.jobs_for_video(video.id)
            items.append(
                StorageItem(
                    id=f"video:{video.id}",
                    kind=(
                        StorageItemKind.DOWNLOAD
                        if video.source_type == SourceType.YOUTUBE
                        else StorageItemKind.UPLOAD
                    ),
                    name=video.title or video.original_name,
                    size=self._size(Path(video.path)),
                    created_at=video.created_at,
                    detail=(
                        f"{video.metadata.width} × {video.metadata.height} source · "
                        f"removes {len(jobs)} linked job(s)"
                    ),
                    active=any(job.status in ACTIVE_STATUSES for job in jobs),
                )
            )
        for job in self.database.list_jobs(10000):
            chunks = list(self.outputs_dir.glob(f"{job.id}-chunk-*.mp4"))
            if not job.output_path and not chunks:
                continue
            output = Path(job.output_path) if job.output_path else None
            original = self.outputs_dir / f"{job.id}-original.mp4"
            items.append(
                StorageItem(
                    id=f"job:{job.id}",
                    kind=StorageItemKind.OUTPUT,
                    name=(
                        "Preview result"
                        if job.kind.value == "preview"
                        else "Streaming enhancement"
                        if job.kind.value == "stream"
                        else "Enhanced video"
                    ),
                    size=(self._size(output) if output else 0) + self._size(original) + sum(
                        self._size(chunk) for chunk in chunks
                    ),
                    created_at=job.created_at,
                    detail=f"{job.target_width} × {job.target_height} · {job.preset.value}",
                    active=job.status in ACTIVE_STATUSES,
                )
            )
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def cleanup(self, ids: list[str]) -> StorageCleanupResult:
        unique_ids = list(dict.fromkeys(ids))
        resolved: list[tuple[str, str]] = []
        for item_id in unique_ids:
            parts = item_id.split(":", 1)
            if len(parts) != 2 or parts[0] not in {"video", "job"} or not parts[1]:
                raise ValueError("Invalid storage selection.")
            resolved.append((parts[0], parts[1]))

        selected_video_ids = {value for kind, value in resolved if kind == "video"}
        jobs_to_remove = {value for kind, value in resolved if kind == "job"}
        videos = []
        for video_id in selected_video_ids:
            video = self.database.get_video(video_id)
            if not video:
                raise ValueError("A selected source no longer exists.")
            linked = self.database.jobs_for_video(video_id)
            if any(job.status in ACTIVE_STATUSES for job in linked):
                raise ValueError("Stop active jobs for this source before deleting it.")
            videos.append(video)
            jobs_to_remove.update(job.id for job in linked)

        jobs = []
        for job_id in jobs_to_remove:
            job = self.database.get_job(job_id)
            if not job:
                continue
            if job.status in ACTIVE_STATUSES:
                raise ValueError("Stop selected jobs before deleting their files.")
            jobs.append(job)

        paths: list[Path] = []
        for job in jobs:
            if job.output_path:
                paths.append(ensure_within(Path(job.output_path), self.outputs_dir))
            paths.append(
                ensure_within(self.outputs_dir / f"{job.id}-original.mp4", self.outputs_dir)
            )
            paths.extend(
                ensure_within(chunk, self.outputs_dir)
                for chunk in self.outputs_dir.glob(f"{job.id}-chunk-*.mp4")
            )
        for video in videos:
            paths.append(ensure_within(Path(video.path), self.settings.data_dir))

        bytes_freed = sum(self._size(path) for path in set(paths))
        for path in set(paths):
            path.unlink(missing_ok=True)
        for job in jobs:
            self.database.delete_job(job.id)
        for video in videos:
            self.database.delete_video(video.id)
        return StorageCleanupResult(removed_ids=unique_ids, bytes_freed=bytes_freed)

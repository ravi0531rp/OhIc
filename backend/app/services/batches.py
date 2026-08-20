import uuid
from datetime import UTC, datetime

from app.jobs.manager import JobManager
from app.models.database import Database
from app.schemas.batch import (
    BatchCreateRequest,
    BatchItem,
    BatchRecord,
    BatchStatus,
    PresetCreate,
    PresetRecord,
)
from app.schemas.job import JobCreate, JobKind, JobStatus


class BatchManager:
    def __init__(self, database: Database, jobs: JobManager):
        self.database = database
        self.jobs = jobs

    @staticmethod
    def _even(value: float) -> int:
        rounded = round(value)
        return rounded if rounded % 2 == 0 else rounded + 1

    def create_preset(self, request: PresetCreate) -> PresetRecord:
        preset = PresetRecord(
            id=str(uuid.uuid4()), created_at=datetime.now(UTC), **request.model_dump()
        )
        self.database.save_preset(preset)
        return preset

    def delete_preset(self, preset_id: str) -> None:
        if not self.database.get_preset(preset_id):
            raise ValueError("Preset not found.")
        self.database.delete_preset(preset_id)

    def create(self, request: BatchCreateRequest) -> BatchRecord:
        video_ids = list(dict.fromkeys(request.video_ids))
        preset = self.database.get_preset(request.preset_id) if request.preset_id else None
        if request.preset_id and not preset:
            raise ValueError("The selected preset no longer exists.")
        videos = []
        for video_id in video_ids:
            video = self.database.get_video(video_id)
            if not video:
                raise ValueError("One of the selected local videos no longer exists.")
            videos.append(video)
        now = datetime.now(UTC)
        record = BatchRecord(
            id=str(uuid.uuid4()),
            name=f"Local batch · {len(videos)} videos",
            status=BatchStatus.QUEUED,
            preset_id=preset.id if preset else None,
            items=[
                BatchItem(id=str(uuid.uuid4()), video_id=video.id, name=video.original_name)
                for video in videos
            ],
            created_at=now,
            updated_at=now,
        )
        self.database.save_batch(record)
        for item, video in zip(record.items, videos, strict=True):
            recommended = next(
                (target for target in video.targets if target.recommended), video.targets[0]
            )
            target_height = (
                preset.target_height if preset and preset.target_height else recommended.height
            )
            target_width = self._even(target_height * video.metadata.width / video.metadata.height)
            try:
                job = self.jobs.create(
                    JobCreate(
                        video_id=video.id,
                        kind=JobKind.FULL,
                        target_width=target_width,
                        target_height=target_height,
                        preset=preset.quality if preset else request.preset,
                        model_id=preset.model_id if preset else "realesrgan-x2plus",
                        output_container=(preset.output_container if preset else "mp4"),
                        track_policy=(preset.track_policy if preset else "compatible"),
                        scan_treatment=(preset.scan_treatment if preset else "auto"),
                        resource_policy=(preset.resource_policy if preset else "auto"),
                        memory_limit_mb=(preset.memory_limit_mb if preset else None),
                        scene_aware=(preset.scene_aware if preset else True),
                        scene_threshold=(preset.scene_threshold if preset else 0.35),
                    )
                )
                item.job_id = job.id
                item.status = job.status.value
            except ValueError as exc:
                item.status = "failed"
                item.error = str(exc)
            record.updated_at = datetime.now(UTC)
            self.database.save_batch(record)
        return self.refresh(record)

    def refresh(self, record: BatchRecord) -> BatchRecord:
        for item in record.items:
            if not item.job_id:
                continue
            job = self.database.get_job(item.job_id)
            if not job:
                item.status = "removed"
                continue
            item.status = job.status.value
            item.progress = job.progress.percent
            item.error = job.error
        statuses = {item.status for item in record.items}
        active = {"queued", "preparing", "processing", "encoding"}
        if statuses and statuses <= {"complete"}:
            record.status = BatchStatus.COMPLETE
        elif statuses & active:
            record.status = BatchStatus.RUNNING
        elif statuses and statuses <= {"paused"}:
            record.status = BatchStatus.PAUSED
        elif statuses and statuses <= {"cancelled"}:
            record.status = BatchStatus.CANCELLED
        elif "complete" in statuses:
            record.status = BatchStatus.PARTIAL
        elif "failed" in statuses:
            record.status = BatchStatus.FAILED
        elif "paused" in statuses:
            record.status = BatchStatus.PAUSED
        record.progress = sum(item.progress for item in record.items) / max(1, len(record.items))
        record.updated_at = datetime.now(UTC)
        self.database.save_batch(record)
        return record

    def get(self, batch_id: str) -> BatchRecord | None:
        record = self.database.get_batch(batch_id)
        return self.refresh(record) if record else None

    def list(self, limit: int = 50) -> list[BatchRecord]:
        return [self.refresh(record) for record in self.database.list_batches(limit)]

    def cancel(self, batch_id: str) -> BatchRecord:
        record = self.database.get_batch(batch_id)
        if not record:
            raise ValueError("Batch not found.")
        for item in record.items:
            if item.job_id:
                self.jobs.cancel(item.job_id)
        return self.refresh(record)

    def pause(self, batch_id: str) -> BatchRecord:
        record = self.database.get_batch(batch_id)
        if not record:
            raise ValueError("Batch not found.")
        for item in record.items:
            if item.job_id:
                self.jobs.pause(item.job_id)
        return self.refresh(record)

    def resume(self, batch_id: str) -> BatchRecord:
        record = self.database.get_batch(batch_id)
        if not record:
            raise ValueError("Batch not found.")
        for item in record.items:
            if not item.job_id:
                continue
            job = self.database.get_job(item.job_id)
            if job and job.status in {JobStatus.PAUSED, JobStatus.FAILED}:
                self.jobs.resume(item.job_id)
        return self.refresh(record)

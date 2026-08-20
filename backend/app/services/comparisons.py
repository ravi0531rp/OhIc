import uuid
from datetime import UTC, datetime

from app.jobs.manager import JobManager
from app.models.database import Database
from app.schemas.comparison import (
    ComparisonCreate,
    ComparisonItem,
    ComparisonRecord,
    ComparisonStatus,
)
from app.schemas.job import JobCreate, JobKind


class ComparisonManager:
    def __init__(self, database: Database, jobs: JobManager):
        self.database = database
        self.jobs = jobs

    def create(self, request: ComparisonCreate) -> ComparisonRecord:
        video = self.database.get_video(request.video_id)
        if not video:
            raise ValueError("The source video no longer exists.")
        now = datetime.now(UTC)
        record = ComparisonRecord(
            id=str(uuid.uuid4()),
            video_id=video.id,
            timestamp=min(request.timestamp, video.metadata.duration),
            status=ComparisonStatus.QUEUED,
            items=[
                ComparisonItem(id=str(uuid.uuid4()), **variant.model_dump())
                for variant in request.variants
            ],
            created_at=now,
            updated_at=now,
        )
        self.database.save_comparison(record)
        for item in record.items:
            try:
                job = self.jobs.create(
                    JobCreate(
                        video_id=video.id,
                        kind=JobKind.PREVIEW,
                        target_width=item.target_width,
                        target_height=item.target_height,
                        preset=item.preset,
                        model_id=item.model_id,
                        preview_timestamp=record.timestamp,
                        scan_treatment=item.scan_treatment,
                    )
                )
                item.job_id = job.id
                item.status = job.status.value
            except ValueError as exc:
                item.status = "failed"
                item.error = str(exc)
            record.updated_at = datetime.now(UTC)
            self.database.save_comparison(record)
        return self.refresh(record)

    def refresh(self, record: ComparisonRecord) -> ComparisonRecord:
        for item in record.items:
            if not item.job_id:
                continue
            job = self.database.get_job(item.job_id)
            if not job:
                item.status = "removed"
                continue
            item.status = job.status.value
            item.progress = job.progress.percent
            item.output_url = job.output_url
            item.error = job.error
        statuses = {item.status for item in record.items}
        active = {"queued", "preparing", "processing", "encoding", "paused"}
        if statuses and statuses <= {"complete"}:
            record.status = ComparisonStatus.COMPLETE
        elif statuses & active:
            record.status = ComparisonStatus.RUNNING
        elif "complete" in statuses:
            record.status = ComparisonStatus.PARTIAL
        elif statuses and statuses <= {"cancelled"}:
            record.status = ComparisonStatus.CANCELLED
        else:
            record.status = ComparisonStatus.FAILED
        record.progress = sum(item.progress for item in record.items) / max(1, len(record.items))
        record.updated_at = datetime.now(UTC)
        self.database.save_comparison(record)
        return record

    def get(self, comparison_id: str) -> ComparisonRecord | None:
        record = self.database.get_comparison(comparison_id)
        return self.refresh(record) if record else None

    def list(self, limit: int = 50) -> list[ComparisonRecord]:
        return [self.refresh(record) for record in self.database.list_comparisons(limit)]

    def cancel(self, comparison_id: str) -> ComparisonRecord:
        record = self.database.get_comparison(comparison_id)
        if not record:
            raise ValueError("Preview comparison not found.")
        for item in record.items:
            if item.job_id:
                self.jobs.cancel(item.job_id)
        return self.refresh(record)

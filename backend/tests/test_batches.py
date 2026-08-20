from datetime import UTC, datetime
from pathlib import Path

from app.models.database import Database
from app.schemas.batch import BatchCreateRequest, PresetCreate
from app.schemas.job import JobProgress, JobRecord, JobStatus
from app.schemas.video import ResolutionTarget, SourceType, VideoMetadata, VideoRecord
from app.services.batches import BatchManager


class FakeJobs:
    def __init__(self, database: Database):
        self.database = database
        self.requests = []

    def create(self, request):
        self.requests.append(request)
        record = JobRecord(
            id=f"job-{len(self.requests)}",
            status=JobStatus.QUEUED,
            progress=JobProgress(),
            created_at=datetime.now(UTC),
            **request.model_dump(),
        )
        self.database.save_job(record)
        return record

    def cancel(self, job_id: str):
        record = self.database.get_job(job_id)
        record.status = JobStatus.CANCELLED
        self.database.save_job(record)

    def pause(self, _job_id: str):
        return None

    def resume(self, _job_id: str):
        return None


def save_video(database: Database, video_id: str, name: str) -> None:
    database.save_video(
        VideoRecord(
            id=video_id,
            source_type=SourceType.UPLOAD,
            original_name=name,
            path=f"/tmp/{name}",
            metadata=VideoMetadata(
                width=854,
                height=480,
                resolution_label="480p",
                aspect_ratio="16:9",
                fps=30,
                duration=10,
                video_codec="H264",
                file_size=1,
            ),
            targets=[
                ResolutionTarget(
                    width=1920, height=1080, label="1080p", recommended=True
                )
            ],
            created_at=datetime.now(UTC),
            playback_url=f"/api/videos/{video_id}/media",
        )
    )


def test_local_batch_uses_saved_preset_and_persists_items(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    save_video(database, "one", "one.mp4")
    save_video(database, "two", "two.mp4")
    jobs = FakeJobs(database)
    manager = BatchManager(database, jobs)  # type: ignore[arg-type]
    preset = manager.create_preset(
        PresetCreate(
            name="Archive",
            target_height=720,
            output_container="mkv",
            track_policy="preserve",
        )
    )

    batch = manager.create(
        BatchCreateRequest(video_ids=["one", "two"], preset_id=preset.id)
    )

    assert len(batch.items) == 2
    assert len(jobs.requests) == 2
    assert all(request.target_height == 720 for request in jobs.requests)
    assert all(request.output_container.value == "mkv" for request in jobs.requests)
    assert database.get_batch(batch.id).items[0].job_id == "job-1"  # type: ignore[union-attr]
    assert database.get_preset(preset.id).name == "Archive"  # type: ignore[union-attr]


def test_batch_progress_is_derived_from_persisted_jobs(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    save_video(database, "one", "one.mp4")
    jobs = FakeJobs(database)
    manager = BatchManager(database, jobs)  # type: ignore[arg-type]
    batch = manager.create(BatchCreateRequest(video_ids=["one"]))
    job = database.get_job(batch.items[0].job_id)
    job.status = JobStatus.COMPLETE
    job.progress.percent = 100
    database.save_job(job)

    refreshed = manager.get(batch.id)

    assert refreshed and refreshed.status.value == "complete"
    assert refreshed.progress == 100

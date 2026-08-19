from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.inference.registry import ModelRegistry
from app.jobs.manager import JobManager
from app.jobs.pipeline import JobRuntime
from app.models.database import Database
from app.schemas.job import JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def test_cancelled_queued_job_never_starts_pipeline(monkeypatch, tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    video = VideoRecord(
        id="video-1",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(tmp_path / "uploads" / "source.mp4"),
        metadata=VideoMetadata(
            width=160,
            height=90,
            resolution_label="90p",
            aspect_ratio="16:9",
            fps=6,
            duration=1,
            video_codec="H264",
            file_size=1,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-1/media",
    )
    database.save_video(video)
    job = JobRecord(
        id="job-1",
        video_id=video.id,
        kind=JobKind.PREVIEW,
        status=JobStatus.CANCELLED,
        model_id="realesrgan-x2plus",
        preset=QualityPreset.BALANCED,
        target_width=320,
        target_height=180,
        preview_timestamp=0,
        progress=JobProgress(stage="Cancelled"),
        created_at=datetime.now(UTC),
    )
    database.save_job(job)
    manager = JobManager(settings, database, ModelRegistry())
    runtime = JobRuntime()
    runtime.stop()
    manager._runtimes[job.id] = runtime
    monkeypatch.setattr(
        "app.jobs.manager.run_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline started")),
    )

    manager._execute(job.id)

    stored = database.get_job(job.id)
    assert stored and stored.status == JobStatus.CANCELLED
    assert job.id not in manager._runtimes
    manager.executor.shutdown(wait=True)

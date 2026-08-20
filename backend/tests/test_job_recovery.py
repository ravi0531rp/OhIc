from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.inference.registry import ModelRegistry
from app.jobs.manager import JobManager, build_checkpoint
from app.jobs.runtime import JobRuntime
from app.models.database import Database
from app.schemas.job import JobCreate, JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def make_video(tmp_path: Path) -> VideoRecord:
    source = tmp_path / "uploads" / "source.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"stable source")
    return VideoRecord(
        id="video-1",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source),
        metadata=VideoMetadata(
            width=160,
            height=90,
            resolution_label="90p",
            aspect_ratio="16:9",
            fps=6,
            duration=75,
            video_codec="H264",
            file_size=source.stat().st_size,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-1/media",
    )


def make_job(video: VideoRecord, status: JobStatus) -> JobRecord:
    request = JobCreate(
        video_id=video.id,
        kind=JobKind.FULL,
        target_width=320,
        target_height=180,
    )
    return JobRecord(
        id="job-1",
        video_id=video.id,
        kind=JobKind.FULL,
        status=status,
        preset=QualityPreset.BALANCED,
        target_width=320,
        target_height=180,
        preview_timestamp=0,
        checkpoint=build_checkpoint(video, request, 75, "job-1", 30),
        progress=JobProgress(stage="Enhancing"),
        created_at=datetime.now(UTC),
    )


def test_checkpoint_plan_covers_range_without_gaps(tmp_path: Path):
    video = make_video(tmp_path)
    request = JobCreate(
        video_id=video.id,
        kind=JobKind.FULL,
        target_width=320,
        target_height=180,
        trim_start=5,
        trim_end=72,
    )

    checkpoint = build_checkpoint(video, request, 72, "job-1", 30)

    assert [(item.start, item.end) for item in checkpoint.segments] == [
        (5, 35),
        (35, 65),
        (65, 72),
    ]
    assert len({item.output_name for item in checkpoint.segments}) == 3


def test_interrupted_job_is_recovered_as_paused_and_can_resume(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    video = make_video(tmp_path)
    database.save_video(video)
    database.save_job(make_job(video, JobStatus.PROCESSING))
    manager = JobManager(settings, database, ModelRegistry())

    assert manager.recover_interrupted() == 1
    recovered = database.get_job("job-1")
    assert recovered and recovered.status == JobStatus.PAUSED
    assert recovered.recovered_after_restart is True

    submitted: list[str] = []
    manager.executor.submit = lambda _callable, job_id: submitted.append(job_id)  # type: ignore[method-assign]
    resumed = manager.resume("job-1")
    assert resumed.status == JobStatus.QUEUED
    assert submitted == ["job-1"]
    manager.executor.shutdown(wait=True)


def test_pause_requests_a_safe_runtime_stop(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    video = make_video(tmp_path)
    database.save_video(video)
    database.save_job(make_job(video, JobStatus.PROCESSING))
    manager = JobManager(settings, database, ModelRegistry())
    runtime = JobRuntime()
    manager._runtimes["job-1"] = runtime

    manager.pause("job-1")

    assert runtime.pause.is_set()
    assert runtime.cancel.is_set()
    assert database.get_job("job-1").progress.stage == "Pausing safely"  # type: ignore[union-attr]
    manager.executor.shutdown(wait=True)

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.inference.realbasicvsr import RealBasicVSREngine
from app.inference.registry import ModelRegistry
from app.jobs.manager import JobManager
from app.models.database import Database
from app.schemas.job import JobCreate, JobKind, JobProgress, JobStatus
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def save_video(database: Database, path: Path, width: int = 160, height: int = 90) -> VideoRecord:
    video = VideoRecord(
        id=f"video-{width}",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(path),
        metadata=VideoMetadata(
            width=width,
            height=height,
            resolution_label=f"{height}p",
            aspect_ratio="16:9",
            fps=6,
            duration=2,
            video_codec="H264",
            file_size=1,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url=f"/api/videos/video-{width}/media",
    )
    database.save_video(video)
    return video


def manager(tmp_path: Path) -> tuple[JobManager, Database]:
    settings = Settings(data_dir=tmp_path, enable_realbasicvsr=True)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    return JobManager(
        settings,
        database,
        ModelRegistry(enable_realbasicvsr=True),
    ), database


def test_realbasicvsr_rejects_streaming_and_inputs_above_720p(tmp_path: Path):
    jobs, database = manager(tmp_path)
    source = save_video(database, tmp_path / "source.mp4")

    with pytest.raises(ValueError, match="does not support watch-while-enhancing"):
        jobs.create(
            JobCreate(
                video_id=source.id,
                kind=JobKind.STREAM,
                target_width=320,
                target_height=180,
                model_id="realbasicvsr-x4-experimental",
            )
        )

    large = save_video(database, tmp_path / "large.mp4", 1920, 1080)
    with pytest.raises(ValueError, match="supports inputs up to 720p"):
        jobs.create(
            JobCreate(
                video_id=large.id,
                kind=JobKind.PREVIEW,
                target_width=1920,
                target_height=1080,
                model_id="realbasicvsr-x4-experimental",
            )
        )
    jobs.executor.shutdown(wait=True)


def test_realbasicvsr_job_uses_temporal_dispatch_and_persists_engine(
    tmp_path: Path, monkeypatch
):
    jobs, database = manager(tmp_path)
    source = save_video(database, tmp_path / "source.mp4")
    monkeypatch.setattr(jobs.executor, "submit", lambda *_args, **_kwargs: None)
    called: list[str] = []

    def temporal_pipeline(job, _video, engine, *_args):
        assert isinstance(engine, RealBasicVSREngine)
        called.append(job.id)
        progress = _args[-1]
        progress(JobProgress(stage="Restoring video", percent=50, frames_done=6, frames_total=12))
        return tmp_path / "result.mp4", None, 1.5

    monkeypatch.setattr("app.jobs.manager.run_realbasicvsr_pipeline", temporal_pipeline)
    job = jobs.create(
        JobCreate(
            video_id=source.id,
            kind=JobKind.PREVIEW,
            target_width=320,
            target_height=180,
            model_id="realbasicvsr-x4-experimental",
            preview_timestamp=1,
        )
    )

    jobs._execute(job.id)

    stored = database.get_job(job.id)
    assert called == [job.id]
    assert stored and stored.status == JobStatus.COMPLETE
    assert stored.model_id == "realbasicvsr-x4-experimental"
    assert stored.processing_seconds == 1.5
    jobs.executor.shutdown(wait=True)

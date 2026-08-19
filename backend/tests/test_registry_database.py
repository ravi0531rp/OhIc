from datetime import UTC, datetime
from pathlib import Path

from app.inference.registry import ModelRegistry
from app.models.database import Database
from app.schemas.job import JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def make_job() -> JobRecord:
    return JobRecord(
        id="job-1",
        video_id="video-1",
        kind=JobKind.PREVIEW,
        status=JobStatus.QUEUED,
        model_id="realesrgan-x2plus",
        preset=QualityPreset.BALANCED,
        target_width=1920,
        target_height=1080,
        preview_timestamp=2,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )


def test_model_registry_hides_test_model_from_product_list():
    registry = ModelRegistry(include_test=True)
    assert registry.get("realesrgan-x2plus").metadata.scale_factors == (2,)
    assert [model.metadata.identifier for model in ModelRegistry().available()] == [
        "realesrgan-x2plus"
    ]
    assert registry.get("lanczos-test").metadata.display_name == "Lanczos test model"


def test_experimental_registry_exposes_realbasicvsr_capabilities_when_enabled():
    registry = ModelRegistry(enable_realbasicvsr=True)
    temporal = registry.get("realbasicvsr-x4-experimental")

    assert temporal.metadata.experimental is True
    assert temporal.metadata.temporal is True
    assert temporal.metadata.supports_stream is False
    assert temporal.metadata.max_input_pixels == 1280 * 720


def test_old_persisted_job_without_model_id_defaults_to_realesrgan():
    payload = make_job().model_dump(mode="json")
    payload.pop("model_id")

    assert JobRecord.model_validate(payload).model_id == "realesrgan-x2plus"


def test_job_lifecycle_persists_in_sqlite(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    job = make_job()
    database.save_job(job)
    stored = database.get_job(job.id)
    assert stored and stored.status == JobStatus.QUEUED
    stored.status = JobStatus.PROCESSING
    stored.output_path = str(tmp_path / "result.mp4")
    stored.progress = JobProgress(stage="Enhancing", percent=42, frames_done=42, frames_total=100)
    database.save_job(stored)
    updated = database.get_job(job.id)
    assert updated and updated.progress.frames_done == 42
    assert updated.output_path == str(tmp_path / "result.mp4")
    assert database.list_jobs()[0].id == job.id


def test_private_video_path_is_persisted_but_excluded_from_api_dump(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    source_path = tmp_path / "source.mp4"
    video = VideoRecord(
        id="video-1",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source_path),
        metadata=VideoMetadata(
            width=160,
            height=90,
            resolution_label="90p",
            aspect_ratio="16:9",
            fps=6,
            duration=1,
            video_codec="H264",
            file_size=100,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-1/media",
    )
    database.save_video(video)
    stored = database.get_video(video.id)
    assert stored and stored.path == str(source_path)
    assert "path" not in stored.model_dump()

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.database import Database
from app.schemas.job import JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord
from app.services.storage import StorageService


def make_video(path: Path) -> VideoRecord:
    return VideoRecord(
        id="video-1",
        source_type=SourceType.YOUTUBE,
        original_name="download.mp4",
        path=str(path),
        metadata=VideoMetadata(
            width=320,
            height=240,
            resolution_label="240p",
            aspect_ratio="4:3",
            fps=30,
            duration=10,
            video_codec="H264",
            file_size=6,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-1/media",
        title="Downloaded video",
    )


def make_job(output: Path, status: JobStatus = JobStatus.COMPLETE) -> JobRecord:
    return JobRecord(
        id="job-1",
        video_id="video-1",
        kind=JobKind.PREVIEW,
        status=status,
        model_id="realesrgan-x2plus",
        preset=QualityPreset.BALANCED,
        target_width=640,
        target_height=480,
        preview_timestamp=2,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
        output_path=str(output) if status == JobStatus.COMPLETE else None,
    )


def setup_storage(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    source = tmp_path / "downloads" / "video-1.mp4"
    output = tmp_path / "outputs" / "job-1.mp4"
    original = tmp_path / "outputs" / "job-1-original.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    original.write_bytes(b"original")
    database.save_video(make_video(source))
    database.save_job(make_job(output))
    return StorageService(settings, database), database, (source, output, original)


def test_inventory_and_source_cleanup_cascade_linked_results(tmp_path: Path):
    storage, database, paths = setup_storage(tmp_path)
    items = storage.items()
    assert {item.id for item in items} == {"video:video-1", "job:job-1"}

    result = storage.cleanup(["video:video-1"])

    assert result.bytes_freed == sum(len(value) for value in (b"source", b"output", b"original"))
    assert not any(path.exists() for path in paths)
    assert database.get_video("video-1") is None
    assert database.get_job("job-1") is None


def test_cleanup_refuses_source_with_active_job(tmp_path: Path):
    storage, database, paths = setup_storage(tmp_path)
    active = make_job(paths[1], JobStatus.QUEUED)
    database.save_job(active)

    with pytest.raises(ValueError, match="Stop active jobs"):
        storage.cleanup(["video:video-1"])

    assert paths[0].exists()
    assert database.get_video("video-1") is not None


def test_cancelled_stream_parts_are_visible_and_can_be_cleaned(tmp_path: Path):
    storage, database, _paths = setup_storage(tmp_path)
    stream_job = make_job(tmp_path / "outputs" / "unused.mp4", JobStatus.CANCELLED)
    stream_job.id = "stream-job"
    stream_job.kind = JobKind.STREAM
    database.save_job(stream_job)
    chunk = tmp_path / "outputs" / "stream-job-chunk-0000.mp4"
    chunk.write_bytes(b"playable-part")

    item = next(item for item in storage.items() if item.id == "job:stream-job")
    assert item.name == "Streaming enhancement"
    assert item.size == len(b"playable-part")

    result = storage.cleanup(["job:stream-job"])
    assert result.bytes_freed == len(b"playable-part")
    assert not chunk.exists()
    assert database.get_job("stream-job") is None

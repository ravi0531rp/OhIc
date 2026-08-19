import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.inference.interpolation import InterpolationModel
from app.jobs.pipeline import JobRuntime, run_pipeline, run_streaming_pipeline
from app.schemas.job import (
    JobKind,
    JobProgress,
    JobRecord,
    JobStatus,
    QualityPreset,
    StreamChunk,
    StreamState,
)
from app.schemas.video import SourceType, VideoRecord
from app.video.probe import probe_video
from app.video.recommendations import recommend_targets


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_cpu_smoke_pipeline_preserves_audio_and_dimensions(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=6:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    source_metadata = probe_video(source)
    video = VideoRecord(
        id="video-smoke",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source),
        metadata=source_metadata,
        targets=recommend_targets(source_metadata),
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-smoke/media",
    )
    job = JobRecord(
        id="job-smoke",
        video_id=video.id,
        kind=JobKind.FULL,
        status=JobStatus.PREPARING,
        model_id="lanczos-test",
        preset=QualityPreset.FAST,
        target_width=320,
        target_height=180,
        preview_timestamp=0,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )
    outputs = tmp_path / "outputs"
    temp = tmp_path / "temp"
    models = tmp_path / "models"
    for directory in (outputs, temp, models):
        directory.mkdir()
    events: list[JobProgress] = []
    result, original, seconds = run_pipeline(
        job,
        video,
        InterpolationModel(),
        models,
        outputs,
        temp,
        "cpu",
        JobRuntime(),
        events.append,
    )
    enhanced = probe_video(result)
    assert original is None
    assert enhanced.width == 320
    assert enhanced.height == 180
    assert enhanced.audio_codec == "AAC"
    assert enhanced.duration == pytest.approx(source_metadata.duration, abs=0.2)
    assert seconds > 0
    assert any(event.stage == "Enhancing" for event in events)


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_full_pipeline_saves_only_selected_time_range(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=6:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    metadata = probe_video(source)
    video = VideoRecord(
        id="video-trim",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source),
        metadata=metadata,
        targets=recommend_targets(metadata),
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-trim/media",
    )
    job = JobRecord(
        id="job-trim",
        video_id=video.id,
        kind=JobKind.FULL,
        status=JobStatus.PREPARING,
        model_id="lanczos-test",
        preset=QualityPreset.FAST,
        target_width=320,
        target_height=180,
        preview_timestamp=0,
        trim_start=0.5,
        trim_end=1.25,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )
    outputs = tmp_path / "outputs"
    temp = tmp_path / "temp"
    models = tmp_path / "models"
    for directory in (outputs, temp, models):
        directory.mkdir()

    result, original, _seconds = run_pipeline(
        job,
        video,
        InterpolationModel(),
        models,
        outputs,
        temp,
        "cpu",
        JobRuntime(),
        lambda _progress: None,
    )

    assert original and original.exists()
    assert probe_video(result).duration == pytest.approx(0.75, abs=0.2)
    assert probe_video(original).duration == pytest.approx(0.75, abs=0.2)


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_streaming_pipeline_publishes_playable_parts_before_final_file(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=6:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    metadata = probe_video(source)
    video = VideoRecord(
        id="video-stream",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source),
        metadata=metadata,
        targets=recommend_targets(metadata),
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-stream/media",
    )
    job = JobRecord(
        id="job-stream",
        video_id=video.id,
        kind=JobKind.STREAM,
        status=JobStatus.PREPARING,
        model_id="lanczos-test",
        preset=QualityPreset.FAST,
        target_width=320,
        target_height=180,
        preview_timestamp=0,
        stream=StreamState(
            chunk_duration=1,
            total_chunks=2,
            chunks=[
                StreamChunk(index=0, start=0, end=1),
                StreamChunk(index=1, start=1, end=2),
            ],
        ),
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )
    outputs = tmp_path / "outputs"
    temp = tmp_path / "temp"
    models = tmp_path / "models"
    for directory in (outputs, temp, models):
        directory.mkdir()
    job_events: list[JobProgress] = []
    stream_events: list[StreamState] = []

    result, original, _seconds = run_streaming_pipeline(
        job,
        video,
        InterpolationModel(),
        models,
        outputs,
        temp,
        "cpu",
        JobRuntime(),
        job_events.append,
        stream_events.append,
    )

    assert original is None
    assert probe_video(result).duration == pytest.approx(2, abs=0.3)
    assert probe_video(result).audio_codec == "AAC"
    assert (outputs / "job-stream-chunk-0000.mp4").exists()
    assert (outputs / "job-stream-chunk-0001.mp4").exists()
    assert any(state.ready_chunks == 1 for state in stream_events)
    assert stream_events[-1].ready_chunks == 2
    assert any(event.stage.startswith("Enhancing part") for event in job_events)

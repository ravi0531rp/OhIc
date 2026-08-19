from datetime import UTC, datetime

from app.jobs.manager import build_stream_state
from app.schemas.job import JobCreate, JobKind, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def make_video() -> VideoRecord:
    return VideoRecord(
        id="video-plan",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path="/tmp/source.mp4",
        metadata=VideoMetadata(
            width=640,
            height=360,
            resolution_label="360p",
            aspect_ratio="16:9",
            fps=30,
            duration=3600,
            video_codec="H264",
            file_size=2 * 1024**3,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-plan/media",
    )


def test_stream_plan_uses_short_startup_part_and_dynamic_chunk_size():
    video = make_video()
    fast = JobCreate(
        video_id=video.id,
        kind=JobKind.STREAM,
        target_width=1280,
        target_height=720,
        preset=QualityPreset.FAST,
    )
    maximum = fast.model_copy(
        update={
            "target_width": 2560,
            "target_height": 1440,
            "preset": QualityPreset.MAXIMUM,
        }
    )

    fast_plan = build_stream_state(video, fast, video.metadata.duration)
    maximum_plan = build_stream_state(video, maximum, video.metadata.duration)

    assert 30 <= fast_plan.chunk_duration <= 120
    assert maximum_plan.chunk_duration < fast_plan.chunk_duration
    assert fast_plan.chunks[0].end - fast_plan.chunks[0].start <= 30
    assert fast_plan.chunks[1].end - fast_plan.chunks[1].start == fast_plan.chunk_duration
    assert fast_plan.chunks[-1].end == video.metadata.duration

from datetime import UTC, datetime

from app.jobs.manager import build_stream_state
from app.schemas.job import JobCreate, JobKind, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def make_video(duration: float = 3600) -> VideoRecord:
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
            duration=duration,
            video_codec="H264",
            file_size=2 * 1024**3,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-plan/media",
    )


def make_request(video: VideoRecord, trim_start: float = 0) -> JobCreate:
    return JobCreate(
        video_id=video.id,
        kind=JobKind.STREAM,
        target_width=1280,
        target_height=720,
        preset=QualityPreset.FAST,
        trim_start=trim_start,
    )


def chunk_durations(plan) -> list[float]:
    return [chunk.end - chunk.start for chunk in plan.chunks]


def test_stream_plan_uses_two_minute_initial_part_for_long_video():
    video = make_video()
    plan = build_stream_state(video, make_request(video), video.metadata.duration)
    durations = chunk_durations(plan)

    assert durations[0] == 120
    assert plan.chunk_duration == 5
    assert all(duration <= 5 for duration in durations[1:])
    assert all(duration == 5 for duration in durations[1:-1])
    assert plan.chunks[-1].end == video.metadata.duration


def test_stream_plan_uses_one_minute_initial_part_below_two_minutes():
    video = make_video(duration=95)
    plan = build_stream_state(video, make_request(video), video.metadata.duration)
    durations = chunk_durations(plan)

    assert durations[0] == 60
    assert durations[1:] == [5] * 7


def test_stream_plan_uses_only_five_second_parts_below_one_minute():
    video = make_video(duration=43)
    plan = build_stream_state(video, make_request(video), video.metadata.duration)
    durations = chunk_durations(plan)

    assert durations[:-1] == [5] * 8
    assert durations[-1] == 3


def test_stream_plan_uses_selected_range_duration_for_thresholds():
    video = make_video()
    request = make_request(video, trim_start=300)
    plan = build_stream_state(video, request, trim_end=345)

    assert chunk_durations(plan) == [5] * 9

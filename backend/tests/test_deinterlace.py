from datetime import UTC, datetime

import pytest

from app.jobs.pipeline import _scan_processing
from app.schemas.job import JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord


def video(field_order: str = "tt", fps: float = 29.97) -> VideoRecord:
    return VideoRecord(
        id="video-1",
        source_type=SourceType.UPLOAD,
        original_name="source.mkv",
        path="/tmp/source.mkv",
        metadata=VideoMetadata(
            width=720,
            height=480,
            resolution_label="480p",
            aspect_ratio="3:2",
            fps=fps,
            duration=10,
            video_codec="MPEG2VIDEO",
            file_size=1,
            field_order=field_order,
        ),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/video-1/media",
    )


def job(scan_treatment: str) -> JobRecord:
    return JobRecord(
        id="job-1",
        video_id="video-1",
        kind=JobKind.FULL,
        status=JobStatus.QUEUED,
        preset=QualityPreset.BALANCED,
        target_width=1440,
        target_height=960,
        preview_timestamp=0,
        scan_treatment=scan_treatment,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )


def test_auto_uses_motion_adaptive_filter_only_for_interlaced_sources():
    interlaced_filter, fps = _scan_processing(job("auto"), video())
    progressive_filter, _ = _scan_processing(job("auto"), video("progressive"))

    assert interlaced_filter and interlaced_filter.startswith("bwdif=")
    assert progressive_filter is None
    assert fps == pytest.approx(29.97)


def test_inverse_telecine_restores_film_cadence():
    filter_chain, fps = _scan_processing(job("ivtc"), video())

    assert filter_chain == "fieldmatch,bwdif=deint=interlaced,decimate"
    assert fps == pytest.approx(23.976)

from datetime import UTC, datetime
from pathlib import Path

from app.jobs.pipeline import _mux_source_tracks
from app.jobs.runtime import JobRuntime
from app.schemas.job import (
    JobKind,
    JobProgress,
    JobRecord,
    JobStatus,
    OutputContainer,
    QualityPreset,
    TrackPolicy,
)


def job() -> JobRecord:
    return JobRecord(
        id="job-1",
        video_id="video-1",
        kind=JobKind.FULL,
        status=JobStatus.PROCESSING,
        preset=QualityPreset.BALANCED,
        target_width=1920,
        target_height=1080,
        preview_timestamp=0,
        output_container=OutputContainer.MKV,
        track_policy=TrackPolicy.PRESERVE,
        progress=JobProgress(),
        created_at=datetime.now(UTC),
    )


def test_archive_mux_maps_all_media_tracks_metadata_and_chapters(monkeypatch, tmp_path: Path):
    command: list[str] = []

    def capture(args, _runtime, _message):
        command.extend(args)

    monkeypatch.setattr("app.jobs.pipeline._run_checked", capture)
    _mux_source_tracks(
        tmp_path / "video.mp4",
        tmp_path / "source.mkv",
        tmp_path / "output.mkv",
        job(),
        JobRuntime(),
        12,
        30,
    )

    assert command[command.index("1:a?") - 1 : command.index("1:a?") + 1] == [
        "-map",
        "1:a?",
    ]
    assert "1:s?" in command
    assert "1:t?" in command
    assert "1:d?" in command
    assert command[command.index("-map_metadata") + 1] == "1"
    assert command[command.index("-map_chapters") + 1] == "1"
    assert command[-1].endswith(".mkv")

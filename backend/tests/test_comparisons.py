from datetime import UTC, datetime
from pathlib import Path

from app.models.database import Database
from app.schemas.comparison import ComparisonCreate, ComparisonVariant
from app.schemas.job import JobProgress, JobRecord, JobStatus
from app.schemas.video import SourceType, VideoMetadata, VideoRecord
from app.services.comparisons import ComparisonManager


class FakeJobs:
    def __init__(self, database: Database):
        self.database = database
        self.requests = []

    def create(self, request):
        self.requests.append(request)
        record = JobRecord(
            id=f"job-{len(self.requests)}",
            status=JobStatus.QUEUED,
            progress=JobProgress(),
            created_at=datetime.now(UTC),
            **request.model_dump(),
        )
        self.database.save_job(record)
        return record

    def cancel(self, _job_id: str):
        return None


def test_comparison_session_persists_each_variant_and_refreshes_progress(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    database.save_video(
        VideoRecord(
            id="video-1",
            source_type=SourceType.UPLOAD,
            original_name="source.mp4",
            path="/tmp/source.mp4",
            metadata=VideoMetadata(
                width=640,
                height=360,
                resolution_label="360p",
                aspect_ratio="16:9",
                fps=30,
                duration=60,
                video_codec="H264",
                file_size=1,
            ),
            targets=[],
            created_at=datetime.now(UTC),
            playback_url="/api/videos/video-1/media",
        )
    )
    jobs = FakeJobs(database)
    manager = ComparisonManager(database, jobs)  # type: ignore[arg-type]
    session = manager.create(
        ComparisonCreate(
            video_id="video-1",
            timestamp=20,
            variants=[
                ComparisonVariant(
                    label="Fast", target_width=1280, target_height=720, preset="fast"
                ),
                ComparisonVariant(
                    label="Maximum", target_width=1280, target_height=720, preset="maximum"
                ),
            ],
        )
    )
    first = database.get_job(session.items[0].job_id)
    first.status = JobStatus.COMPLETE
    first.progress.percent = 100
    first.output_url = "/api/jobs/job-1/result"
    database.save_job(first)

    refreshed = manager.get(session.id)

    assert refreshed and refreshed.status.value == "running"
    assert refreshed.progress == 50
    assert refreshed.items[0].output_url == "/api/jobs/job-1/result"
    assert database.get_comparison(session.id) is not None

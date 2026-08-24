from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models.database import Database
from app.schemas.history import HistoryEntryKind
from app.schemas.intelligence import AnalysisStatus, VideoAnalysis
from app.schemas.job import JobKind, JobProgress, JobRecord, JobStatus, QualityPreset
from app.schemas.video import SourceType, VideoMetadata, VideoRecord
from app.services.history import list_history


def video(identifier: str, source_type: SourceType, created_at: datetime) -> VideoRecord:
    return VideoRecord(
        id=identifier,
        source_type=source_type,
        original_name=f"{identifier}.mp4",
        path=f"/tmp/{identifier}.mp4",
        metadata=VideoMetadata(
            width=1920,
            height=1080,
            resolution_label="1080p",
            aspect_ratio="16:9",
            fps=30,
            duration=12.5,
            video_codec="H264",
            file_size=1024,
        ),
        targets=[],
        created_at=created_at,
        playback_url=f"/api/videos/{identifier}/media",
        title="Phone camera capture" if source_type == SourceType.CAMERA else "Uploaded video",
    )


def test_history_combines_jobs_camera_captures_and_pro_analyses(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    now = datetime.now(UTC)
    camera = video("camera-video", SourceType.CAMERA, now - timedelta(minutes=3))
    upload = video("upload-video", SourceType.UPLOAD, now - timedelta(minutes=4))
    database.save_video(camera)
    database.save_video(upload)
    database.save_job(
        JobRecord(
            id="enhancement-job",
            video_id=upload.id,
            kind=JobKind.FULL,
            status=JobStatus.PROCESSING,
            preset=QualityPreset.BALANCED,
            target_width=1280,
            target_height=720,
            preview_timestamp=0,
            progress=JobProgress(stage="Enhancing", percent=42),
            created_at=now - timedelta(minutes=2),
        )
    )
    database.save_analysis(
        VideoAnalysis(
            id="pro-analysis",
            video_id=camera.id,
            video_name="Phone camera capture",
            status=AnalysisStatus.TRACKING,
            progress=65,
            stage="RF-DETR + OSNet ReID",
            created_at=now - timedelta(minutes=1),
            updated_at=now,
        )
    )

    history = list_history(database)

    assert [entry.kind for entry in history] == [
        HistoryEntryKind.PRO,
        HistoryEntryKind.ENHANCEMENT,
        HistoryEntryKind.CAMERA,
    ]
    assert history[0].reference_id == "pro-analysis"
    assert history[0].can_cancel is True
    assert history[1].reference_id == "enhancement-job"
    assert history[1].can_pause is True
    assert history[2].reference_id == "camera-video"
    assert history[2].status == "complete"
    assert "Ready to enhance or analyze" in history[2].detail
    assert len(list_history(database, limit=2)) == 2

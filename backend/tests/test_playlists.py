import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.database import Database
from app.schemas.job import JobProgress, JobRecord, JobStatus
from app.schemas.playlist import (
    PlaylistCreateRequest,
    PlaylistInspectItem,
    PlaylistMetadata,
    PlaylistStatus,
)
from app.schemas.video import ResolutionTarget, SourceType, VideoMetadata, VideoRecord
from app.services.playlists import PlaylistManager


class FakeYouTube:
    def __init__(self, root: Path):
        self.root = root

    def inspect_playlist(self, url: str) -> PlaylistMetadata:
        return PlaylistMetadata(
            url=url,
            title="Restoration queue",
            uploader="OhIc tests",
            item_count=2,
            items=[
                PlaylistInspectItem(
                    youtube_id=f"video-{index}",
                    url=f"https://youtube.com/watch?v=video-{index}",
                    title=f"Clip {index}",
                    duration=1,
                    position=index,
                )
                for index in (1, 2)
            ],
        )

    def download(self, url: str, progress_hook=None, attempt_hook=None):
        if attempt_hook:
            attempt_hook(1)
        path = self.root / f"{url.rsplit('-', 1)[-1]}.mp4"
        path.write_bytes(b"video")
        if progress_hook:
            progress_hook(
                {
                    "status": "finished",
                    "downloaded_bytes": 5,
                    "total_bytes": 5,
                }
            )
        return path, {"safe_title": path.name, "title": path.stem}


class FakeVideos:
    def __init__(self, database: Database):
        self.database = database

    def register_download(self, path: Path, original_name: str, title, thumbnail, uploader):
        video = VideoRecord(
            id=path.stem,
            source_type=SourceType.YOUTUBE,
            original_name=original_name,
            path=str(path),
            metadata=VideoMetadata(
                width=160,
                height=90,
                resolution_label="90p",
                aspect_ratio="16:9",
                fps=6,
                duration=1,
                video_codec="H264",
                file_size=5,
            ),
            targets=[ResolutionTarget(width=320, height=180, label="180p", recommended=True)],
            created_at=datetime.now(UTC),
            playback_url=f"/api/videos/{path.stem}/media",
            title=title,
        )
        self.database.save_video(video)
        return video


class FakeJobs:
    def __init__(self, database: Database):
        self.database = database

    def create(self, request):
        job = JobRecord(
            id=f"job-{request.video_id}",
            video_id=request.video_id,
            kind=request.kind,
            status=JobStatus.COMPLETE,
            model_id=request.model_id,
            preset=request.preset,
            target_width=request.target_width,
            target_height=request.target_height,
            preview_timestamp=request.preview_timestamp,
            playlist_id=request.playlist_id,
            progress=JobProgress(stage="Complete", percent=100),
            created_at=datetime.now(UTC),
            output_url=f"/api/jobs/job-{request.video_id}/result",
        )
        self.database.save_job(job)
        return job

    def cancel(self, job_id: str):
        return self.database.get_job(job_id)


def test_playlist_batch_persists_selected_items_and_linked_jobs(tmp_path: Path):
    database = Database(tmp_path / "ohic.sqlite3")
    manager = PlaylistManager(
        database,
        FakeYouTube(tmp_path),
        FakeVideos(database),
        FakeJobs(database),
    )
    created = manager.create(
        PlaylistCreateRequest(
            url="https://youtube.com/playlist?list=test",
            selected_video_ids=["video-1", "video-2"],
        )
    )
    manager.executor.shutdown(wait=True)

    stored = Database(database.path).get_playlist(created.id)
    assert stored and stored.status == PlaylistStatus.COMPLETE
    assert stored.progress == 100
    assert [item.status for item in stored.items] == ["complete", "complete"]
    assert all(item.video_id and item.job_id for item in stored.items)
    assert all(database.get_job(item.job_id or "") for item in stored.items)


def test_playlist_must_finish_stopping_before_project_can_be_removed(tmp_path: Path):
    class SlowYouTube(FakeYouTube):
        def __init__(self, root: Path):
            super().__init__(root)
            self.started = threading.Event()

        def download(self, url: str, progress_hook=None, attempt_hook=None):
            self.started.set()
            for value in range(10):
                if progress_hook:
                    progress_hook(
                        {
                            "status": "downloading",
                            "downloaded_bytes": value,
                            "total_bytes": 10,
                        }
                    )
                time.sleep(0.01)
            return super().download(url, progress_hook, attempt_hook)

    database = Database(tmp_path / "ohic.sqlite3")
    youtube = SlowYouTube(tmp_path)
    manager = PlaylistManager(database, youtube, FakeVideos(database), FakeJobs(database))
    created = manager.create(
        PlaylistCreateRequest(
            url="https://youtube.com/playlist?list=test",
            selected_video_ids=["video-1"],
        )
    )
    assert youtube.started.wait(timeout=1)
    stopping = manager.cancel(created.id)
    assert stopping.status == PlaylistStatus.RUNNING
    with pytest.raises(ValueError, match="Stop this playlist"):
        manager.delete(created.id)

    manager.executor.shutdown(wait=True)
    assert manager.get(created.id).status == PlaylistStatus.CANCELLED
    manager.delete(created.id)
    assert manager.get(created.id) is None

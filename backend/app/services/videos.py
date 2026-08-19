import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.models.database import Database
from app.schemas.video import SourceType, VideoRecord
from app.utils.files import validate_video_filename
from app.video.probe import probe_video
from app.video.recommendations import recommend_targets


class UploadTooLargeError(ValueError):
    pass


class VideoService:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    async def save_upload(self, upload: UploadFile) -> VideoRecord:
        original_name = validate_video_filename(upload.filename or "")
        video_id = str(uuid.uuid4())
        suffix = Path(original_name).suffix.lower()
        destination = self.settings.data_dir / "uploads" / f"{video_id}{suffix}"
        maximum = int(self.settings.max_upload_gb * 1024**3)
        total = 0
        try:
            with destination.open("xb") as target:
                while chunk := await upload.read(1024 * 1024 * 4):
                    total += len(chunk)
                    if total > maximum:
                        raise UploadTooLargeError(
                            "Video exceeds the configured "
                            f"{self.settings.max_upload_gb:g} GB limit."
                        )
                    target.write(chunk)
            metadata = probe_video(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        record = VideoRecord(
            id=video_id,
            source_type=SourceType.UPLOAD,
            original_name=original_name,
            path=str(destination),
            metadata=metadata,
            targets=recommend_targets(metadata),
            created_at=datetime.now(UTC),
            playback_url=f"/api/videos/{video_id}/media",
        )
        self.database.save_video(record)
        return record

    def register_download(
        self,
        path: Path,
        original_name: str,
        title: str | None,
        thumbnail: str | None,
        uploader: str | None,
    ) -> VideoRecord:
        video_id = path.stem.split(".")[0]
        metadata = probe_video(path)
        record = VideoRecord(
            id=video_id,
            source_type=SourceType.YOUTUBE,
            original_name=original_name,
            path=str(path),
            metadata=metadata,
            targets=recommend_targets(metadata),
            created_at=datetime.now(UTC),
            playback_url=f"/api/videos/{video_id}/media",
            title=title,
            thumbnail=thumbnail,
            uploader=uploader,
        )
        self.database.save_video(record)
        return record

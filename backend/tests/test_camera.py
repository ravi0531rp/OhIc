import io
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from app.core.config import Settings
from app.models.database import Database
from app.schemas.video import CameraSessionStatus, SourceType
from app.services.camera import CameraSessionManager
from app.services.videos import VideoService


def jpeg_frame(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 90), color).save(output, format="JPEG")
    return output.getvalue()


def test_phone_pairing_streams_frames_and_registers_a_video(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    manager = CameraSessionManager(settings, VideoService(settings, database))
    try:
        session = manager.create()
        token = next(token for token, value in manager._tokens.items() if value == session.id)

        assert session.pairing_url.startswith("http://")
        assert "getUserMedia" in manager.phone_page(token)
        assert "capture=environment" in manager.phone_page(token)
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)):
            manager.add_frame(token, jpeg_frame(color))
        assert manager.get(session.id).status == CameraSessionStatus.STREAMING
        assert manager.latest_frame(session.id).startswith(b"\xff\xd8")

        manager.finish(token)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = manager.get(session.id)
            if current and current.status in {
                CameraSessionStatus.COMPLETE,
                CameraSessionStatus.FAILED,
            }:
                break
            time.sleep(0.03)

        assert current and current.status == CameraSessionStatus.COMPLETE, current.error
        assert current.video and current.video.source_type == SourceType.CAMERA
        assert database.get_video(current.video.id)
    finally:
        manager.close()


def test_phone_native_recording_is_transferred_and_normalized(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    manager = CameraSessionManager(settings, VideoService(settings, database))
    source = tmp_path / "phone.mov"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=161x91:rate=6:duration=1", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac",
            "-shortest", str(source),
        ],
        check=True,
    )
    try:
        session = manager.create()
        token = next(token for token, value in manager._tokens.items() if value == session.id)
        assert manager._server
        port = manager._server.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/camera/{token}/recording",
            data=source.read_bytes(),
            headers={"Content-Type": "video/quicktime"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test server
            assert response.status == 204
        uploading = manager.get(session.id)
        assert uploading
        assert uploading.status == CameraSessionStatus.PROCESSING

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = manager.get(session.id)
            if current and current.status in {
                CameraSessionStatus.COMPLETE,
                CameraSessionStatus.FAILED,
            }:
                break
            time.sleep(0.03)

        assert current and current.status == CameraSessionStatus.COMPLETE, current.error
        assert current.video and current.video.source_type == SourceType.CAMERA
        assert current.video.metadata.width % 2 == 0
        assert current.video.metadata.height % 2 == 0
    finally:
        manager.close()


def test_camera_pairing_rejects_invalid_or_oversized_frames(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    manager = CameraSessionManager(
        settings,
        VideoService(settings, Database(tmp_path / "ohic.sqlite3")),
    )
    try:
        session = manager.create()
        token = next(token for token, value in manager._tokens.items() if value == session.id)
        with pytest.raises(ValueError, match="JPEG"):
            manager.add_frame(token, b"not-an-image")
        with pytest.raises(ValueError, match="at least two"):
            manager.finish(token)
    finally:
        manager.close()

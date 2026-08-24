import io
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from app.core.config import Settings
from app.models.database import Database
from app.schemas.video import CameraSessionStatus, CameraStreamMode, SourceType
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
        assert "MediaRecorder" in manager.phone_page(token)
        assert "/chunk" in manager.phone_page(token)
        assert "audio: true" in manager.phone_page(token)
        assert "continuing with video only" in manager.phone_page(token)
        assert 'capture="environment"' in manager.phone_page(token)
        assert "Enable secure live streaming" in manager.phone_page(token)
        assert manager._server
        port = manager._server.server_address[1]
        with urlopen(  # noqa: S310 - loopback test server
            f"http://127.0.0.1:{port}/camera/{token}", timeout=5
        ) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert "default-src 'self'" in response.headers["Content-Security-Policy"]
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


def test_secure_relay_replaces_the_qr_and_stops_with_the_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    manager = CameraSessionManager(
        settings,
        VideoService(settings, Database(tmp_path / "ohic.sqlite3")),
    )
    command = [
        sys.executable,
        "-u",
        "-c",
        (
            "import time; "
            "print('relay ready: https://quiet-camera-test.trycloudflare.com', flush=True); "
            "time.sleep(60)"
        ),
    ]
    monkeypatch.setattr(manager, "_relay_command", lambda _port: command)
    monkeypatch.setattr(
        manager,
        "_wait_for_relay",
        lambda _process, _output: None,
    )
    process = None
    try:
        session = manager.create()
        waiting_session = manager.create()
        assert session.relay_status.value == "local"
        secure = manager.enable_secure_relay(session.id)
        process = manager._relay_process

        assert secure.relay_status.value == "ready"
        assert secure.pairing_url.startswith(
            "https://quiet-camera-test.trycloudflare.com/camera/"
        )
        assert process and process.poll() is None
        waiting_secure = manager.get(waiting_session.id)
        assert waiting_secure and waiting_secure.relay_status.value == "ready"
        assert waiting_secure.pairing_url.startswith(
            "https://quiet-camera-test.trycloudflare.com/camera/"
        )

        next_session = manager.create()
        assert next_session.relay_status.value == "ready"
        assert next_session.pairing_url.startswith(
            "https://quiet-camera-test.trycloudflare.com/camera/"
        )
    finally:
        manager.close()
    assert process and process.poll() is not None


def test_phone_live_video_chunks_are_durable_and_checkpointable(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    database = Database(tmp_path / "ohic.sqlite3")
    manager = CameraSessionManager(settings, VideoService(settings, database))
    source = tmp_path / "live.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=10:duration=2", "-f", "lavfi", "-i",
            "sine=frequency=660:duration=2", "-c:v", "libvpx", "-c:a", "libopus",
            "-shortest", str(source),
        ],
        check=True,
    )
    try:
        session = manager.create()
        token = next(token for token, value in manager._tokens.items() if value == session.id)
        data = source.read_bytes()
        boundaries = (0, len(data) // 3, len(data) * 2 // 3, len(data))
        chunks = [data[boundaries[index] : boundaries[index + 1]] for index in range(3)]

        manager.add_stream_chunk(
            token, io.BytesIO(chunks[0]), len(chunks[0]), 0, "video/webm;codecs=vp8,opus", 0.7
        )
        duplicate = manager.add_stream_chunk(
            token, io.BytesIO(chunks[0]), len(chunks[0]), 0, "video/webm", 0.7
        )
        assert duplicate.segment_count == 1
        with pytest.raises(ValueError, match="Expected live video chunk 1"):
            manager.add_stream_chunk(
                token, io.BytesIO(chunks[2]), len(chunks[2]), 2, "video/webm", 2
            )
        for sequence in (1, 2):
            manager.add_stream_chunk(
                token,
                io.BytesIO(chunks[sequence]),
                len(chunks[sequence]),
                sequence,
                "video/webm",
                (sequence + 1) * 0.7,
            )

        live = manager.get(session.id)
        assert live
        assert live.status == CameraSessionStatus.STREAMING
        assert live.stream_mode == CameraStreamMode.MEDIA
        assert live.segment_count == 3
        assert live.stream_bytes == len(data)
        assert live.ready_seconds == pytest.approx(2.1)

        checkpoint = manager.checkpoint(session.id)
        assert checkpoint.source_type == SourceType.CAMERA
        assert checkpoint.title == "Phone live checkpoint"
        assert checkpoint.metadata.duration > 1
        assert database.get_video(checkpoint.id)
        assert manager.get(session.id).status == CameraSessionStatus.STREAMING
        assert manager.get(session.id).checkpoint_count == 1

        manager.finish(token)
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
        assert current.video and current.video.metadata.duration > 1
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

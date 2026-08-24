# The paired-phone page is intentionally self-contained so it can be served without static assets.
# ruff: noqa: E501
from __future__ import annotations

import html
import secrets
import shutil
import socket
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from app.core.config import Settings
from app.schemas.video import CameraSession, CameraSessionStatus, CameraStreamMode, VideoRecord
from app.services.phone_camera_page import render_phone_camera_page
from app.services.videos import VideoService

MAX_FRAME_BYTES = 2_000_000
MAX_STREAM_CHUNK_BYTES = 24_000_000
MAX_RECORDING_BYTES = 4_000_000_000


class CameraSessionManager:
    """One-time, LAN-only phone camera bridge with token-scoped routes."""

    def __init__(self, settings: Settings, videos: VideoService):
        self.settings = settings
        self.videos = videos
        self.root = settings.data_dir / "camera"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sessions: dict[str, CameraSession] = {}
        self._tokens: dict[str, str] = {}
        self._latest: dict[str, bytes] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-camera")
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    def create(self) -> CameraSession:
        self._ensure_server()
        session_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(24)
        assert self._server
        port = int(self._server.server_address[1])
        pairing_base = self.settings.camera_pairing_base_url or (
            f"http://{self._lan_address()}:{port}"
        )
        pairing_url = f"{pairing_base.rstrip('/')}/camera/{token}"
        session = CameraSession(
            id=session_id,
            pairing_url=pairing_url,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._sessions[session_id] = session
            self._tokens[token] = session_id
        (self.root / session_id / "frames").mkdir(parents=True, exist_ok=True)
        return session.model_copy(deep=True)

    def get(self, session_id: str) -> CameraSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def latest_frame(self, session_id: str) -> bytes | None:
        with self._lock:
            return self._latest.get(session_id)

    def add_frame(self, token: str, data: bytes) -> CameraSession:
        if len(data) > MAX_FRAME_BYTES or not data.startswith(b"\xff\xd8"):
            raise ValueError("Expected a JPEG camera frame under 2 MB.")
        with self._lock:
            session = self._by_token(token)
            if session.status not in {CameraSessionStatus.WAITING, CameraSessionStatus.STREAMING}:
                raise ValueError("This camera session is no longer accepting frames.")
            session.status = CameraSessionStatus.STREAMING
            session.stream_mode = session.stream_mode or CameraStreamMode.FRAMES
            index = session.frame_count
            session.frame_count += 1
            self._latest[session.id] = data
            if session.stream_mode == CameraStreamMode.FRAMES:
                destination = self.root / session.id / "frames" / f"{index:08d}.jpg"
                destination.write_bytes(data)
            return session.model_copy(deep=True)

    def add_stream_chunk(
        self,
        token: str,
        source: BinaryIO,
        length: int,
        sequence: int,
        content_type: str | None,
        elapsed_seconds: float,
    ) -> CameraSession:
        if length <= 0 or length > MAX_STREAM_CHUNK_BYTES:
            raise ValueError("Expected a live video chunk under 24 MB.")
        if sequence < 0:
            raise ValueError("Live video chunk sequence must be non-negative.")
        mime_type = (content_type or "").split(";", 1)[0].lower()
        if mime_type not in {"video/webm", "video/mp4"}:
            raise ValueError("Live video chunks must use WebM or MP4.")
        with self._lock:
            session = self._by_token(token)
            if session.status not in {CameraSessionStatus.WAITING, CameraSessionStatus.STREAMING}:
                raise ValueError("This camera session is no longer accepting live video.")
            if sequence < session.segment_count:
                return session.model_copy(deep=True)
            if sequence != session.segment_count:
                raise ValueError(f"Expected live video chunk {session.segment_count}.")
            if session.stream_mime_type and session.stream_mime_type != mime_type:
                raise ValueError("The live video format changed during capture.")
            maximum = min(MAX_RECORDING_BYTES, int(self.settings.max_upload_gb * 1024**3))
            if session.stream_bytes + length > maximum:
                raise ValueError(f"Live video exceeds the {maximum // 1024**2} MB limit.")
            session_id = session.id
        incoming = self.root / session_id / f"chunk-{sequence:08d}.part"
        remaining = length
        try:
            with incoming.open("xb") as destination:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("The live video chunk ended unexpectedly.")
                    destination.write(chunk)
                    remaining -= len(chunk)
            with self._lock:
                session = self._by_token(token)
                if session.status not in {
                    CameraSessionStatus.WAITING,
                    CameraSessionStatus.STREAMING,
                }:
                    raise ValueError("This camera session is no longer accepting live video.")
                if sequence != session.segment_count:
                    raise ValueError(f"Expected live video chunk {session.segment_count}.")
                session.stream_mode = CameraStreamMode.MEDIA
                session.stream_mime_type = mime_type
                stream_path = self._stream_path(session)
                with stream_path.open("ab") as destination, incoming.open("rb") as chunk_source:
                    shutil.copyfileobj(chunk_source, destination, 1024 * 1024)
                session.segment_count += 1
                session.stream_bytes += length
                session.ready_seconds = max(session.ready_seconds, elapsed_seconds)
                session.status = CameraSessionStatus.STREAMING
                return session.model_copy(deep=True)
        finally:
            incoming.unlink(missing_ok=True)

    def finish(self, token: str) -> CameraSession:
        with self._lock:
            session = self._by_token(token)
            if session.segment_count < 1 and session.frame_count < 2:
                raise ValueError("Stream at least two frames or one video chunk before finishing.")
            if session.status == CameraSessionStatus.PROCESSING:
                return session.model_copy(deep=True)
            session.status = CameraSessionStatus.PROCESSING
            encoder = self._encode_stream if session.segment_count else self._encode
            self._executor.submit(encoder, session.id)
            return session.model_copy(deep=True)

    def checkpoint(self, session_id: str) -> VideoRecord:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError("Camera session not found.")
            if session.status not in {CameraSessionStatus.STREAMING, CameraSessionStatus.PROCESSING}:
                raise ValueError("Start the phone stream before creating a live checkpoint.")
            checkpoint_id = uuid.uuid4().hex
            output = self.settings.data_dir / "uploads" / f"{checkpoint_id}.mp4"
            if session.segment_count:
                source = self.root / session.id / f"checkpoint-{checkpoint_id}{self._stream_suffix(session)}"
                shutil.copyfile(self._stream_path(session), source)
                frame_count = 0
            elif session.frame_count >= 2:
                source = self.root / session.id / "frames"
                frame_count = session.frame_count
            else:
                raise ValueError("Wait for more live video before creating a checkpoint.")
        try:
            if frame_count:
                completed = self._encode_frames(source, output, frame_count)
            else:
                completed = self._normalize_recording(source, output)
            if completed.returncode:
                output.unlink(missing_ok=True)
                raise ValueError(
                    completed.stderr.strip()[-800:] or "The live buffer is not ready yet."
                )
            video = self.videos.register_camera_capture(
                output, title="Phone live checkpoint"
            )
            with self._lock:
                current = self._sessions.get(session_id)
                if current:
                    current.checkpoint_count += 1
            return video
        finally:
            if not frame_count:
                source.unlink(missing_ok=True)

    def add_recording(
        self,
        token: str,
        source: BinaryIO,
        length: int,
        content_type: str | None,
    ) -> CameraSession:
        limit = min(MAX_RECORDING_BYTES, int(self.settings.max_upload_gb * 1024**3))
        if length <= 0 or length > limit:
            raise ValueError(f"Expected a phone recording smaller than {limit // 1024**2} MB.")
        with self._lock:
            session = self._by_token(token)
            if session.status not in {CameraSessionStatus.WAITING, CameraSessionStatus.STREAMING}:
                raise ValueError("This camera session is no longer accepting a recording.")
            session.status = CameraSessionStatus.PROCESSING
            session.error = None
            session_id = session.id
        suffix = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
            "video/x-m4v": ".m4v",
        }.get((content_type or "").split(";", 1)[0].lower(), ".video")
        temporary = self.root / session_id / "phone-recording.part"
        recording = temporary.with_suffix(suffix)
        remaining = length
        try:
            with temporary.open("wb") as destination:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("The phone recording upload ended unexpectedly.")
                    destination.write(chunk)
                    remaining -= len(chunk)
            temporary.replace(recording)
        except Exception:
            temporary.unlink(missing_ok=True)
            with self._lock:
                session = self._sessions[session_id]
                session.status = CameraSessionStatus.WAITING
            raise
        self._executor.submit(self._encode_recording, session_id, recording)
        current = self.get(session_id)
        if not current:  # the session is retained until the manager shuts down
            raise RuntimeError("Camera session disappeared during recording upload.")
        return current

    def cancel(self, session_id: str) -> CameraSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError("Camera session not found.")
            if session.status not in {CameraSessionStatus.COMPLETE, CameraSessionStatus.FAILED}:
                session.status = CameraSessionStatus.CANCELLED
            return session.model_copy(deep=True)

    def close(self) -> None:
        with self._lock:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
                self._server = None
        self._executor.shutdown(wait=True, cancel_futures=True)

    def phone_page(self, token: str) -> str:
        with self._lock:
            self._by_token(token)
        safe_token = html.escape(token, quote=True)
        return render_phone_camera_page(safe_token)

    def _encode(self, session_id: str) -> None:
        session_dir = self.root / session_id
        output = self.settings.data_dir / "uploads" / f"{session_id}.mp4"
        session = self.get(session_id)
        completed = self._encode_frames(
            session_dir / "frames", output, session.frame_count if session else 0
        )
        self._complete_encoding(session_id, output, completed, "Camera encoding failed.")

    def _encode_stream(self, session_id: str) -> None:
        session = self.get(session_id)
        if not session:
            return
        output = self.settings.data_dir / "uploads" / f"{session_id}.mp4"
        completed = self._normalize_recording(self._stream_path(session), output)
        self._complete_encoding(session_id, output, completed, "Live video conversion failed.")

    def _complete_encoding(
        self,
        session_id: str,
        output: Path,
        completed: subprocess.CompletedProcess[str],
        fallback_error: str,
    ) -> None:
        with self._lock:
            session = self._sessions[session_id]
            if session.status == CameraSessionStatus.CANCELLED:
                output.unlink(missing_ok=True)
                return
            if completed.returncode:
                session.status = CameraSessionStatus.FAILED
                session.error = completed.stderr.strip()[-800:] or fallback_error
                return
            try:
                session.video = self.videos.register_camera_capture(output)
                session.status = CameraSessionStatus.COMPLETE
            except Exception as exc:
                output.unlink(missing_ok=True)
                session.status = CameraSessionStatus.FAILED
                session.error = str(exc)

    def _encode_recording(self, session_id: str, recording: Path) -> None:
        output = self.settings.data_dir / "uploads" / f"{session_id}.mp4"
        completed = self._normalize_recording(recording, output)
        recording.unlink(missing_ok=True)
        self._complete_encoding(
            session_id, output, completed, "Phone video conversion failed."
        )

    @staticmethod
    def _encode_frames(
        frames: Path, output: Path, frame_count: int
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", "8",
                "-i", str(frames / "%08d.jpg"), "-frames:v", str(frame_count),
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-y", str(output),
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )

    @staticmethod
    def _normalize_recording(
        recording: Path, output: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
                "-i", str(recording), "-map", "0:v:0", "-map", "0:a?",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-movflags", "+faststart", "-y", str(output),
            ],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )

    def _stream_path(self, session: CameraSession) -> Path:
        return self.root / session.id / f"live{self._stream_suffix(session)}"

    @staticmethod
    def _stream_suffix(session: CameraSession) -> str:
        return ".mp4" if session.stream_mime_type == "video/mp4" else ".webm"

    def _by_token(self, token: str) -> CameraSession:
        session_id = self._tokens.get(token)
        session = self._sessions.get(session_id or "")
        if not session:
            raise ValueError("Camera pairing token is invalid or expired.")
        return session

    def _ensure_server(self) -> None:
        with self._lock:
            if self._server:
                return
            manager = self

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    parts = urlparse(self.path).path.strip("/").split("/")
                    if len(parts) != 2 or parts[0] != "camera":
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    try:
                        body = manager.phone_page(parts[1]).encode()
                    except ValueError as exc:
                        self.send_error(HTTPStatus.NOT_FOUND, str(exc))
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_POST(self) -> None:  # noqa: N802
                    parts = urlparse(self.path).path.strip("/").split("/")
                    if len(parts) != 3 or parts[0] != "camera":
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    try:
                        if parts[2] == "frame":
                            length = int(self.headers.get("Content-Length", "0"))
                            if length <= 0 or length > MAX_FRAME_BYTES:
                                raise ValueError("Invalid camera frame size.")
                            manager.add_frame(parts[1], self.rfile.read(length))
                        elif parts[2] == "chunk":
                            length = int(self.headers.get("Content-Length", "0"))
                            sequence = int(self.headers.get("X-OhIc-Sequence", "-1"))
                            elapsed_ms = max(
                                0, int(self.headers.get("X-OhIc-Elapsed-Ms", "0"))
                            )
                            manager.add_stream_chunk(
                                parts[1],
                                self.rfile,
                                length,
                                sequence,
                                self.headers.get("Content-Type"),
                                elapsed_ms / 1000,
                            )
                        elif parts[2] == "finish":
                            manager.finish(parts[1])
                        elif parts[2] == "recording":
                            length = int(self.headers.get("Content-Length", "0"))
                            manager.add_recording(
                                parts[1],
                                self.rfile,
                                length,
                                self.headers.get("Content-Type"),
                            )
                        else:
                            self.send_error(HTTPStatus.NOT_FOUND)
                            return
                    except ValueError as exc:
                        self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.end_headers()

                def log_message(self, _format: str, *_args) -> None:
                    return

            self._server = ThreadingHTTPServer(
                ("0.0.0.0", self.settings.camera_port), Handler
            )
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="ohic-camera-pairing",
                daemon=True,
            )
            self._server_thread.start()

    @staticmethod
    def _lan_address() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
        except OSError:
            return socket.gethostbyname(socket.gethostname())
        finally:
            probe.close()

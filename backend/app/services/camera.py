# The paired-phone page is intentionally self-contained so it can be served without static assets.
# ruff: noqa: E501
from __future__ import annotations

import html
import secrets
import socket
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app.core.config import Settings
from app.schemas.video import CameraSession, CameraSessionStatus
from app.services.videos import VideoService

MAX_FRAME_BYTES = 2_000_000


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
        pairing_url = f"http://{self._lan_address()}:{port}/camera/{token}"
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
            index = session.frame_count
            session.frame_count += 1
            self._latest[session.id] = data
            destination = self.root / session.id / "frames" / f"{index:08d}.jpg"
            destination.write_bytes(data)
            return session.model_copy(deep=True)

    def finish(self, token: str) -> CameraSession:
        with self._lock:
            session = self._by_token(token)
            if session.frame_count < 2:
                raise ValueError("Record at least two frames before finishing.")
            if session.status == CameraSessionStatus.PROCESSING:
                return session.model_copy(deep=True)
            session.status = CameraSessionStatus.PROCESSING
            self._executor.submit(self._encode, session.id)
            return session.model_copy(deep=True)

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
        return f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>OhIc phone camera</title><style>body{{background:#090b09;color:#eef0eb;font:16px system-ui;margin:0;padding:22px}}main{{margin:auto;max-width:560px}}video{{background:#000;border-radius:18px;width:100%}}button{{background:#d9ff67;border:0;border-radius:10px;color:#182000;font-weight:700;margin-top:12px;padding:14px;width:100%}}p{{color:#929990;line-height:1.5}}#status{{color:#d9ff67}}</style></head><body><main><h1>OhIc phone camera</h1><p>Keep this page open on the same Wi-Fi network. Your camera frames go only to the paired computer.</p><video autoplay muted playsinline></video><canvas hidden></canvas><p id=status>Requesting camera…</p><button id=stop disabled>Stop and use this video</button><script>const token='{safe_token}',video=document.querySelector('video'),canvas=document.querySelector('canvas'),status=document.querySelector('#status'),stop=document.querySelector('#stop');let timer,frames=0;navigator.mediaDevices?.getUserMedia({{video:{{facingMode:{{ideal:'environment'}}}},audio:false}}).then(stream=>{{video.srcObject=stream;stop.disabled=false;status.textContent='Live · paired with OhIc';timer=setInterval(()=>{{if(!video.videoWidth)return;canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);canvas.toBlob(blob=>{{if(blob)fetch(`/camera/${{token}}/frame`,{{method:'POST',headers:{{'Content-Type':'image/jpeg'}},body:blob}}).then(()=>{{frames++;status.textContent=`Live · ${{frames}} frames sent`;}})}},'image/jpeg',.82)}},125)}}).catch(error=>{{status.textContent=location.protocol==='http:'?'Live camera requires HTTPS in this phone browser. Open OhIc with trusted local HTTPS or use a browser that permits LAN camera access.':`Camera unavailable: ${{error.message}}`;}});stop.onclick=async()=>{{clearInterval(timer);stop.disabled=true;status.textContent='Finishing local video…';const response=await fetch(`/camera/${{token}}/finish`,{{method:'POST'}});status.textContent=response.ok?'Sent. Return to OhIc on your computer.':await response.text();video.srcObject?.getTracks().forEach(track=>track.stop());}};</script></main></body></html>"""

    def _encode(self, session_id: str) -> None:
        session_dir = self.root / session_id
        output = self.settings.data_dir / "uploads" / f"{session_id}.mp4"
        completed = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", "8",
                "-i", str(session_dir / "frames" / "%08d.jpg"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(output),
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        with self._lock:
            session = self._sessions[session_id]
            if session.status == CameraSessionStatus.CANCELLED:
                output.unlink(missing_ok=True)
                return
            if completed.returncode:
                session.status = CameraSessionStatus.FAILED
                session.error = completed.stderr.strip()[-800:] or "Camera encoding failed."
                return
            try:
                session.video = self.videos.register_camera_capture(output)
                session.status = CameraSessionStatus.COMPLETE
            except Exception as exc:
                output.unlink(missing_ok=True)
                session.status = CameraSessionStatus.FAILED
                session.error = str(exc)

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
                        elif parts[2] == "finish":
                            manager.finish(parts[1])
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

            self._server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
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

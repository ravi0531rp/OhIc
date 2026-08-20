import shutil
import subprocess
import uuid
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from time import monotonic

import structlog
import yt_dlp

from app.schemas.playlist import PlaylistInspectItem, PlaylistMetadata
from app.schemas.video import (
    YouTubeMetadata,
    YouTubeReliabilityCheck,
    YouTubeReliabilityReport,
)
from app.utils.files import safe_stem, validate_youtube_url

logger = structlog.get_logger()


class YouTubeError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: str = "unknown",
        recovery_steps: list[str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.recovery_steps = recovery_steps or []


class YouTubeDownloadCancelled(InterruptedError):
    pass


class YouTubeDownloadStalled(RuntimeError):
    pass


class YouTubeService:
    def __init__(self, downloads_dir: Path, cookies_file: Path | None = None):
        self.downloads_dir = downloads_dir
        self.cookies_file = cookies_file

    @staticmethod
    def _diagnose(exc: Exception) -> tuple[str, str, list[str]]:
        text = str(exc).lower()
        if "403" in text or "forbidden" in text or "po token" in text:
            return (
                "youtube_attestation",
                "YouTube rejected every available playback format.",
                [
                    "Update yt-dlp and retry.",
                    "Install a supported PO token provider for restricted playback formats.",
                    "For videos requiring an account, configure a dedicated cookies file.",
                ],
            )
        if "private" in text or "sign in" in text or "login" in text:
            return (
                "authentication_required",
                "This video is private, age-restricted, or requires sign-in.",
                ["Configure a cookies file for an account permitted to view this video."],
            )
        if "geo" in text or "country" in text or "region" in text:
            return (
                "region_restricted",
                "This YouTube video is not available in your region.",
                ["Use a source that is available in your current region."],
            )
        if "429" in text or "rate" in text or "try again later" in text:
            return (
                "rate_limited",
                "YouTube temporarily rate-limited this connection.",
                ["Wait several minutes before retrying.", "Avoid starting many imports at once."],
            )
        if "unavailable" in text or "removed" in text:
            return (
                "unavailable",
                "This YouTube video is unavailable or has been removed.",
                ["Check the URL and confirm that the video still plays on YouTube."],
            )
        return (
            "extractor_failure",
            "YouTube could not provide this video.",
            ["Run the Reliability Center check, update yt-dlp, and retry."],
        )

    @staticmethod
    def _message(exc: Exception) -> str:
        _code, message, steps = YouTubeService._diagnose(exc)
        return f"{message} {' '.join(steps)}" if steps else message

    def reliability_report(self) -> YouTubeReliabilityReport:
        node = shutil.which("node")
        node_version: str | None = None
        if node:
            try:
                node_version = subprocess.run(
                    [node, "--version"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                node_version = None
        distributions = {item.metadata["Name"].lower() for item in metadata.distributions()}
        po_provider = any("pot" in name and "yt" in name for name in distributions)
        cookies = bool(self.cookies_file and self.cookies_file.is_file())
        checks = [
            YouTubeReliabilityCheck(
                id="extractor",
                label="YouTube extractor",
                status="ready",
                detail=f"yt-dlp {yt_dlp.version.__version__}",
            ),
            YouTubeReliabilityCheck(
                id="javascript",
                label="JavaScript challenge runtime",
                status="ready" if node_version else "warning",
                detail=node_version or "Node.js was not found",
            ),
            YouTubeReliabilityCheck(
                id="attestation",
                label="Restricted-format access",
                status="ready" if po_provider or cookies else "optional",
                detail=(
                    "PO-token provider detected"
                    if po_provider
                    else "Cookies file configured"
                    if cookies
                    else "Public videos use automatic fallback clients"
                ),
            ),
        ]
        recommendations: list[str] = []
        if not node_version:
            recommendations.append("Install Node.js 20 or newer for YouTube challenge solving.")
        if not po_provider:
            recommendations.append(
                "A PO-token provider is optional, but improves access when YouTube returns 403."
            )
        return YouTubeReliabilityReport(
            status="ready" if node_version else "degraded",
            yt_dlp_version=yt_dlp.version.__version__,
            node_version=node_version,
            cookies_configured=cookies,
            po_token_provider=po_provider,
            checks=checks,
            recommendations=recommendations,
        )

    @staticmethod
    def _base_options() -> dict:
        # YouTube now requires JavaScript challenge solving for full format support. OhIc already
        # requires Node 22+ for its frontend, and yt-dlp-ejs is installed with yt-dlp[default].
        return {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 15,
        }

    def _options(self) -> dict:
        options = self._base_options()
        if self.cookies_file and self.cookies_file.is_file():
            options["cookiefile"] = str(self.cookies_file)
        return options

    def inspect(self, url: str) -> YouTubeMetadata:
        safe_url = validate_youtube_url(url)
        options = {**self._options(), "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(safe_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            code, message, steps = self._diagnose(exc)
            raise YouTubeError(message, code, steps) from exc
        if not info or info.get("_type") == "playlist":
            raise YouTubeError("Playlists are not supported yet. Paste a single video link.")
        return YouTubeMetadata(
            url=safe_url,
            title=info.get("title") or "YouTube video",
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("channel"),
            width=info.get("width"),
            height=info.get("height"),
            fps=info.get("fps"),
        )

    def inspect_playlist(self, url: str) -> PlaylistMetadata:
        safe_url = validate_youtube_url(url)
        options = {
            **self._options(),
            "noplaylist": False,
            "extract_flat": "in_playlist",
            "playlistend": 100,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(safe_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            code, message, steps = self._diagnose(exc)
            raise YouTubeError(message, code, steps) from exc
        if not info or info.get("_type") != "playlist":
            raise YouTubeError("This link is not a YouTube playlist.")
        items: list[PlaylistInspectItem] = []
        for position, entry in enumerate(info.get("entries") or [], start=1):
            if not entry or not entry.get("id"):
                continue
            youtube_id = str(entry["id"])
            thumbnails = entry.get("thumbnails") or []
            thumbnail = entry.get("thumbnail") or (
                thumbnails[-1].get("url") if thumbnails else None
            )
            items.append(
                PlaylistInspectItem(
                    youtube_id=youtube_id,
                    url=f"https://www.youtube.com/watch?v={youtube_id}",
                    title=entry.get("title") or f"Video {position}",
                    thumbnail=thumbnail,
                    duration=entry.get("duration"),
                    uploader=entry.get("uploader") or entry.get("channel"),
                    position=position,
                )
            )
        if not items:
            raise YouTubeError("This playlist has no available videos.")
        return PlaylistMetadata(
            url=safe_url,
            title=info.get("title") or "YouTube playlist",
            thumbnail=info.get("thumbnail") or items[0].thumbnail,
            uploader=info.get("uploader") or info.get("channel"),
            item_count=len(items),
            items=items,
        )

    def download(
        self,
        url: str,
        progress_hook: Callable[[dict], None] | None = None,
        attempt_hook: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[Path, dict]:
        safe_url = validate_youtube_url(url)
        video_id = str(uuid.uuid4())
        template = str(self.downloads_dir / f"{video_id}.%(ext)s")
        strategies = [
            {
                # web_embedded currently provides normal HTTPS formats without a PO token. Keep
                # it isolated: combining clients lets yt-dlp select a throttled TV/mweb URL.
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
            },
            {
                "format": ("b[ext=mp4][vcodec!=none][acodec!=none]/b[vcodec!=none][acodec!=none]"),
                "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
            },
            {
                "format": ("b[ext=mp4][vcodec!=none][acodec!=none]/b[vcodec!=none][acodec!=none]"),
                "extractor_args": {"youtube": {"player_client": ["android_vr"]}},
            },
        ]
        last_error: yt_dlp.utils.DownloadError | None = None
        info: dict | None = None
        prepared: Path | None = None
        for attempt, strategy in enumerate(strategies, start=1):
            if cancel_check and cancel_check():
                raise YouTubeDownloadCancelled("YouTube download cancelled.")
            if attempt_hook:
                attempt_hook(attempt)
            slow_since: float | None = None

            def guarded_progress(data: dict) -> None:
                nonlocal slow_since
                if cancel_check and cancel_check():
                    raise YouTubeDownloadCancelled("YouTube download cancelled.")
                speed = float(data.get("speed") or 0)
                eta = float(data.get("eta") or 0)
                downloaded = int(data.get("downloaded_bytes") or 0)
                is_unusably_slow = downloaded >= 2 * 1024 * 1024 and 0 < speed < 32 * 1024
                if is_unusably_slow and eta > 30 * 60:
                    slow_since = slow_since or monotonic()
                    if monotonic() - slow_since >= 10:
                        raise YouTubeDownloadStalled(
                            "YouTube selected a throttled stream; trying another format."
                        )
                else:
                    slow_since = None
                if progress_hook:
                    progress_hook(data)

            options = {
                **self._options(),
                **strategy,
                "merge_output_format": "mp4",
                "outtmpl": template,
                "restrictfilenames": True,
            }
            options["progress_hooks"] = [guarded_progress]
            try:
                with yt_dlp.YoutubeDL(options) as client:
                    info = client.extract_info(safe_url, download=True)
                    prepared = Path(client.prepare_filename(info))
                logger.info("youtube_download_succeeded", attempt=attempt)
                break
            except YouTubeDownloadCancelled:
                for partial in self.downloads_dir.glob(f"{video_id}.*"):
                    partial.unlink(missing_ok=True)
                raise
            except (yt_dlp.utils.DownloadError, YouTubeDownloadStalled) as exc:
                last_error = exc
                reason = (
                    "throttled"
                    if isinstance(exc, YouTubeDownloadStalled)
                    else "forbidden" if "403" in str(exc) else "format_unavailable"
                )
                logger.warning("youtube_download_attempt_failed", attempt=attempt, reason=reason)
                for partial in self.downloads_dir.glob(f"{video_id}.*"):
                    partial.unlink(missing_ok=True)
            except InterruptedError:
                for partial in self.downloads_dir.glob(f"{video_id}.*"):
                    partial.unlink(missing_ok=True)
                raise
            except Exception:
                for partial in self.downloads_dir.glob(f"{video_id}.*"):
                    partial.unlink(missing_ok=True)
                raise
        if info is None or prepared is None:
            assert last_error is not None
            if isinstance(last_error, YouTubeDownloadStalled):
                raise YouTubeError(
                    "YouTube only offered a throttled stream. Please retry in a few minutes."
                ) from last_error
            code, message, steps = self._diagnose(last_error)
            raise YouTubeError(message, code, steps) from last_error
        candidates = list(self.downloads_dir.glob(f"{video_id}.*"))
        path = next((item for item in candidates if item.suffix.lower() == ".mp4"), prepared)
        if not path.exists():
            raise YouTubeError("YouTube download finished without a playable video file.")
        info["safe_title"] = f"{safe_stem(info.get('title') or 'youtube-video')}{path.suffix}"
        return path, info

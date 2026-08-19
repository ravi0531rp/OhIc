import uuid
from collections.abc import Callable
from pathlib import Path
from time import monotonic

import structlog
import yt_dlp

from app.schemas.playlist import PlaylistInspectItem, PlaylistMetadata
from app.schemas.video import YouTubeMetadata
from app.utils.files import safe_stem, validate_youtube_url

logger = structlog.get_logger()


class YouTubeError(RuntimeError):
    pass


class YouTubeDownloadCancelled(InterruptedError):
    pass


class YouTubeDownloadStalled(RuntimeError):
    pass


class YouTubeService:
    def __init__(self, downloads_dir: Path):
        self.downloads_dir = downloads_dir

    @staticmethod
    def _message(exc: Exception) -> str:
        text = str(exc).lower()
        if "403" in text or "forbidden" in text:
            return (
                "YouTube rejected every available playback format. This video may require "
                "sign-in, a PO token, or a newer yt-dlp release."
            )
        if "private" in text:
            return "This YouTube video is private or requires sign-in."
        if "geo" in text or "country" in text:
            return "This YouTube video is not available in your region."
        if "unavailable" in text or "removed" in text:
            return "This YouTube video is unavailable or has been removed."
        return "YouTube could not provide this video. Updating yt-dlp may help."

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

    def inspect(self, url: str) -> YouTubeMetadata:
        safe_url = validate_youtube_url(url)
        options = {**self._base_options(), "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(safe_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise YouTubeError(self._message(exc)) from exc
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
            **self._base_options(),
            "noplaylist": False,
            "extract_flat": "in_playlist",
            "playlistend": 100,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(safe_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise YouTubeError(self._message(exc)) from exc
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
                **self._base_options(),
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
            raise YouTubeError(self._message(last_error)) from last_error
        candidates = list(self.downloads_dir.glob(f"{video_id}.*"))
        path = next((item for item in candidates if item.suffix.lower() == ".mp4"), prepared)
        if not path.exists():
            raise YouTubeError("YouTube download finished without a playable video file.")
        info["safe_title"] = f"{safe_stem(info.get('title') or 'youtube-video')}{path.suffix}"
        return path, info

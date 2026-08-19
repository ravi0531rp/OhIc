import re
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def validate_video_filename(filename: str) -> str:
    clean = Path(filename).name
    if not clean or clean in {".", ".."}:
        raise ValueError("The selected file has an invalid name.")
    if Path(clean).suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
        raise ValueError(f"Unsupported video format. Choose one of: {allowed}.")
    return clean


def safe_stem(filename: str, fallback: str = "video") -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return stem[:80] or fallback


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise ValueError("Enter a valid YouTube URL.")
    if parsed.username or parsed.password:
        raise ValueError("YouTube URLs containing credentials are not supported.")
    return url.strip()


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("The requested file is outside the OhIc data directory.")
    return resolved

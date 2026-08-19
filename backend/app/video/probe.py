import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

from app.schemas.video import VideoMetadata


class VideoProbeError(RuntimeError):
    pass


def parse_rate(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def resolution_label(height: int) -> str:
    standards = (
        (2160, "4K"),
        (1440, "1440p"),
        (1080, "1080p"),
        (720, "720p"),
        (480, "480p"),
        (360, "360p"),
    )
    closest = min(standards, key=lambda item: abs(item[0] - height))
    return closest[1] if abs(closest[0] - height) <= max(24, height * 0.12) else f"{height}p"


def _aspect(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    simple = (width // divisor, height // divisor)
    if simple[0] > 40 or simple[1] > 40:
        ratio = width / height
        common = [(16 / 9, "16:9"), (4 / 3, "4:3"), (21 / 9, "21:9"), (1.0, "1:1")]
        return min(common, key=lambda item: abs(item[0] - ratio))[1]
    return f"{simple[0]}:{simple[1]}"


def parse_ffprobe(payload: dict, file_size: int) -> VideoMetadata:
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise VideoProbeError("This file does not contain a readable video stream.")
    fmt = payload.get("format", {})
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    duration = float(video.get("duration") or fmt.get("duration") or 0)
    fps = parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    frames = video.get("nb_frames")
    frame_count = int(frames) if frames and str(frames).isdigit() else None
    if frame_count is None and duration > 0 and fps > 0:
        frame_count = round(duration * fps)
    tags = video.get("color_transfer") or ""
    dynamic_range = "HDR" if tags in {"smpte2084", "arib-std-b67"} else "SDR"
    return VideoMetadata(
        width=width,
        height=height,
        resolution_label=resolution_label(height),
        aspect_ratio=_aspect(width, height),
        fps=round(fps, 3),
        frame_count=frame_count,
        duration=duration,
        video_codec=str(video.get("codec_name") or "unknown").upper(),
        audio_codec=str(audio.get("codec_name")).upper() if audio else None,
        bitrate=int(fmt.get("bit_rate")) if str(fmt.get("bit_rate", "")).isdigit() else None,
        file_size=file_size,
        pixel_format=video.get("pix_fmt"),
        dynamic_range=dynamic_range,
    )


def probe_video(path: Path, ffprobe: str = "ffprobe") -> VideoMetadata:
    args = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-print_format",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise VideoProbeError("FFprobe is not installed. Install FFmpeg and restart OhIc.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProbeError("Video inspection timed out.") from exc
    if result.returncode != 0:
        raise VideoProbeError("This video format could not be decoded.")
    try:
        return parse_ffprobe(json.loads(result.stdout), path.stat().st_size)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise VideoProbeError("FFprobe returned incomplete video metadata.") from exc

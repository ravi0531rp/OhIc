from __future__ import annotations

import json
import os
import platform
import resource
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

import numpy as np

from app.inference.realbasicvsr.chunking import recommended_window, temporal_windows
from app.jobs.runtime import JobRuntime
from app.video.probe import probe_video

ProgressCallback = Callable[[str, float, str | None], None]


class SequenceEnhancer(Protocol):
    identifier: str
    display_name: str
    scale: int
    device: str
    model_load_seconds: float

    def enhance_sequence(
        self, frames: Sequence[np.ndarray], cancel: Event | None = None
    ) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class RealBasicVSRRunStats:
    engine: str
    device: str
    model: str
    input_resolution: str
    model_resolution: str
    output_resolution: str
    fps: float
    duration_seconds: float
    frame_count: int
    window_frames: int
    overlap_frames: int
    model_load_seconds: float
    decode_seconds: float
    inference_seconds: float
    encoding_seconds: float
    total_seconds: float
    processing_fps: float
    peak_rss_mb: float
    output_bytes: int
    audio_mode: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _read_exact(pipe, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        block = pipe.read(size - len(result))
        if not block:
            break
        result.extend(block)
    return bytes(result)


def _target_size(
    source_width: int,
    source_height: int,
    scale: int,
    target_width: int | None,
    target_height: int | None,
) -> tuple[int, int]:
    if target_width is None and target_height is None:
        return source_width * scale, source_height * scale
    ratio = source_width / source_height
    if target_width is None:
        assert target_height is not None
        target_width = round(target_height * ratio)
    elif target_height is None:
        target_height = round(target_width / ratio)
    if target_width < 2 or target_height < 2:
        raise ValueError("Output dimensions must be at least 2×2.")
    target_width -= target_width % 2
    target_height -= target_height % 2
    if abs(target_width / target_height - ratio) > 0.01:
        raise ValueError("Output dimensions must preserve the source aspect ratio.")
    return target_width, target_height


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if platform.system() == "Darwin" else peak / 1024


def _run_ffmpeg(args: list[str], runtime: JobRuntime, message: str) -> None:
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    runtime.add(process)
    _, stderr = process.communicate()
    runtime.remove(process)
    if runtime.cancel.is_set():
        raise InterruptedError("RealBasicVSR processing was cancelled.")
    if process.returncode:
        detail = stderr.decode(errors="replace")[-1000:] if stderr else ""
        raise RuntimeError(f"{message} {detail}".strip())


def run_experimental_pipeline(
    source: Path,
    output: Path,
    engine: SequenceEnhancer,
    *,
    runtime: JobRuntime | None = None,
    progress: ProgressCallback | None = None,
    window_frames: int | None = None,
    overlap_frames: int | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
    max_input_pixels: int = 1280 * 720,
    start_at: float = 0,
    duration: float | None = None,
    temp_root: Path | None = None,
) -> RealBasicVSRRunStats:
    """Run bounded temporal inference without registering an application model."""
    runtime = runtime or JobRuntime()
    metadata = probe_video(source)
    start_at = max(0.0, min(start_at, metadata.duration))
    available_duration = max(0.0, metadata.duration - start_at)
    selected_duration = min(duration, available_duration) if duration else available_duration
    if selected_duration <= 0:
        raise ValueError("The selected RealBasicVSR range is empty.")
    if metadata.width * metadata.height > max_input_pixels:
        raise ValueError(
            "This source is above the experimental RealBasicVSR 720p input limit. "
            "Use a smaller source or Real-ESRGAN; spatial tiling is not yet considered safe."
        )
    suggested_window, suggested_overlap = recommended_window(metadata.width, metadata.height)
    window_frames = window_frames or suggested_window
    overlap_frames = suggested_overlap if overlap_frames is None else overlap_frames
    if window_frames - 2 * overlap_frames < 1:
        raise ValueError("Window size must be larger than twice the temporal overlap.")
    model_width = metadata.width * engine.scale
    model_height = metadata.height * engine.scale
    output_width, output_height = _target_size(
        metadata.width,
        metadata.height,
        engine.scale,
        target_width,
        target_height,
    )
    fps = metadata.fps or 30.0
    total_frames = max(1, round(selected_duration * fps))
    output.parent.mkdir(parents=True, exist_ok=True)
    if temp_root:
        temp_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    decode_seconds = 0.0
    inference_seconds = 0.0
    encoding_seconds = 0.0
    frames_done = 0
    audio_mode = "none"

    with tempfile.TemporaryDirectory(
        prefix="ohic-realbasicvsr-", dir=temp_root
    ) as temp_name:
        workdir = Path(temp_name)
        video_only = workdir / "restored-video.mp4"
        final_output = workdir / "restored-final.mp4"
        log_path = workdir / "ffmpeg.log"
        if progress:
            progress("Decoding", 0, f"{metadata.width}×{metadata.height} at {fps:g} FPS")
        decoder_log = log_path.open("wb")
        encoder_log = log_path.open("ab")
        decoder_args = ["ffmpeg", "-v", "error"]
        if start_at:
            decoder_args += ["-ss", f"{start_at:.3f}"]
        decoder_args += ["-i", str(source)]
        if duration is not None:
            decoder_args += ["-t", f"{selected_duration:.3f}"]
        decoder_args += [
            "-map",
            "0:v:0",
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        decoder = subprocess.Popen(decoder_args, stdout=subprocess.PIPE, stderr=decoder_log)
        encoder_args = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{model_width}x{model_height}",
            "-framerate",
            f"{fps:g}",
            "-i",
            "pipe:0",
            "-an",
        ]
        if (output_width, output_height) != (model_width, model_height):
            encoder_args += [
                "-vf",
                f"scale={output_width}:{output_height}:flags=lanczos",
            ]
        encoder_args += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video_only),
        ]
        encoder = subprocess.Popen(encoder_args, stdin=subprocess.PIPE, stderr=encoder_log)
        runtime.add(decoder)
        runtime.add(encoder)
        frame_bytes = metadata.width * metadata.height * 3

        def decoded_frames():
            nonlocal decode_seconds
            assert decoder.stdout
            while not runtime.cancel.is_set():
                read_started = time.perf_counter()
                raw = _read_exact(decoder.stdout, frame_bytes)
                decode_seconds += time.perf_counter() - read_started
                if len(raw) != frame_bytes:
                    return
                yield np.frombuffer(raw, dtype=np.uint8).reshape(
                    metadata.height, metadata.width, 3
                )

        try:
            assert encoder.stdin
            for window in temporal_windows(decoded_frames(), window_frames, overlap_frames):
                if runtime.cancel.is_set():
                    raise InterruptedError("RealBasicVSR processing was cancelled.")
                if len(window.frames) < 2:
                    raise RuntimeError("RealBasicVSR requires a video with at least two frames.")
                if progress:
                    progress(
                        "Restoring",
                        min(95.0, frames_done / max(1, total_frames) * 95),
                        f"Window {window.index + 1} · frames {window.start_frame + 1}–"
                        f"{window.start_frame + len(window.frames)}",
                    )
                inference_started = time.perf_counter()
                restored = engine.enhance_sequence(window.frames, runtime.cancel)
                inference_seconds += time.perf_counter() - inference_started
                encode_started = time.perf_counter()
                for frame in restored[window.emit_start : window.emit_end]:
                    encoder.stdin.write(frame.tobytes())
                    frames_done += 1
                encoding_seconds += time.perf_counter() - encode_started
                if progress:
                    progress(
                        "Restoring",
                        min(95.0, frames_done / max(1, total_frames) * 95),
                        f"Restored {frames_done} of {total_frames} frames",
                    )
            if runtime.cancel.is_set():
                raise InterruptedError("RealBasicVSR processing was cancelled.")
            if progress:
                progress("Encoding", 96, "Finishing the restored video stream")
            encoder.stdin.close()
            decoder.wait(timeout=60)
            encoding_wait = time.perf_counter()
            encoder.wait(timeout=300)
            encoding_seconds += time.perf_counter() - encoding_wait
            runtime.remove(decoder)
            runtime.remove(encoder)
            decoder_log.close()
            encoder_log.close()
            if decoder.returncode or encoder.returncode or not video_only.exists():
                detail = log_path.read_text(errors="replace")[-1200:]
                raise RuntimeError(f"FFmpeg could not encode the restored video. {detail}".strip())

            if progress:
                progress("Muxing audio", 97, "Copying the source audio when compatible")
            mux_started = time.perf_counter()
            if metadata.audio_codec:
                copy_args = [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(video_only),
                ]
                if start_at:
                    copy_args += ["-ss", f"{start_at:.3f}"]
                if duration is not None:
                    copy_args += ["-t", f"{selected_duration:.3f}"]
                copy_args += [
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0?",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(final_output),
                ]
                try:
                    _run_ffmpeg(copy_args, runtime, "Source audio could not be copied.")
                    audio_mode = "copy"
                except RuntimeError:
                    final_output.unlink(missing_ok=True)
                    transcode_args = [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-i",
                        str(video_only),
                    ]
                    if start_at:
                        transcode_args += ["-ss", f"{start_at:.3f}"]
                    if duration is not None:
                        transcode_args += ["-t", f"{selected_duration:.3f}"]
                    transcode_args += [
                        "-i",
                        str(source),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0?",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-shortest",
                        "-movflags",
                        "+faststart",
                        str(final_output),
                    ]
                    _run_ffmpeg(transcode_args, runtime, "Source audio could not be muxed.")
                    audio_mode = "aac"
            else:
                _run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-i",
                        str(video_only),
                        "-c",
                        "copy",
                        "-movflags",
                        "+faststart",
                        str(final_output),
                    ],
                    runtime,
                    "The restored video could not be finalized.",
                )
            encoding_seconds += time.perf_counter() - mux_started
            if progress:
                progress("Finalizing", 99, str(output))
            os.replace(final_output, output)
        finally:
            runtime.close_processes()
            decoder_log.close()
            encoder_log.close()

    total_seconds = engine.model_load_seconds + time.perf_counter() - started
    return RealBasicVSRRunStats(
        engine=engine.identifier,
        device=engine.device,
        model=engine.display_name,
        input_resolution=f"{metadata.width}x{metadata.height}",
        model_resolution=f"{model_width}x{model_height}",
        output_resolution=f"{output_width}x{output_height}",
        fps=fps,
        duration_seconds=frames_done / fps,
        frame_count=frames_done,
        window_frames=window_frames,
        overlap_frames=overlap_frames,
        model_load_seconds=engine.model_load_seconds,
        decode_seconds=decode_seconds,
        inference_seconds=inference_seconds,
        encoding_seconds=encoding_seconds,
        total_seconds=total_seconds,
        processing_fps=frames_done / inference_seconds if inference_seconds else 0,
        peak_rss_mb=_peak_rss_mb(),
        output_bytes=output.stat().st_size,
        audio_mode=audio_mode,
    )

import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.inference.base import VideoEnhancementModel
from app.schemas.job import (
    JobKind,
    JobProgress,
    JobRecord,
    QualityPreset,
    StreamChunkStatus,
    StreamState,
)
from app.schemas.video import VideoRecord

ProgressSink = Callable[[JobProgress], None]
StreamProgressSink = Callable[[StreamState], None]


@dataclass
class JobRuntime:
    cancel: threading.Event = field(default_factory=threading.Event)
    processes: list[subprocess.Popen] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def add(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.processes.append(process)

    def remove(self, process: subprocess.Popen) -> None:
        with self.lock:
            if process in self.processes:
                self.processes.remove(process)

    def stop(self) -> None:
        self.cancel.set()
        self.close_processes()

    def close_processes(self) -> None:
        with self.lock:
            for process in self.processes:
                if process.poll() is None:
                    process.terminate()
            self.processes.clear()


def _preset_config(preset: QualityPreset, device: str) -> tuple[int, str, int]:
    if preset == QualityPreset.FAST:
        return (512 if device != "cpu" else 192, "veryfast", 21)
    if preset == QualityPreset.MAXIMUM:
        return (256 if device != "cpu" else 128, "slow", 17)
    return (384 if device != "cpu" else 160, "medium", 19)


def _run_checked(args: list[str], runtime: JobRuntime, error_message: str) -> None:
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    runtime.add(process)
    _, stderr = process.communicate()
    runtime.remove(process)
    if runtime.cancel.is_set():
        raise InterruptedError("Enhancement cancelled")
    if process.returncode != 0:
        detail = stderr.decode(errors="replace")[-1200:] if stderr else ""
        raise RuntimeError(f"{error_message} {detail}".strip())


def _read_frame(pipe, frame_bytes: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < frame_bytes:
        chunk = pipe.read(frame_bytes - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def run_pipeline(
    job: JobRecord,
    video: VideoRecord,
    model: VideoEnhancementModel,
    model_dir: Path,
    outputs_dir: Path,
    temp_root: Path,
    device: str,
    runtime: JobRuntime,
    progress: ProgressSink,
) -> tuple[Path, Path | None, float]:
    started = time.monotonic()
    workdir = temp_root / job.id
    workdir.mkdir(parents=True, exist_ok=True)
    source = Path(video.path)
    video_only = workdir / "enhanced-video.mp4"
    output = outputs_dir / f"{job.id}.mp4"
    if job.kind == JobKind.PREVIEW:
        duration = min(5.0, max(0.1, video.metadata.duration))
        start_at = min(
            max(0.0, job.preview_timestamp - duration / 2),
            max(0, video.metadata.duration - duration),
        )
    else:
        start_at = max(0.0, job.trim_start)
        end_at = min(job.trim_end or video.metadata.duration, video.metadata.duration)
        selected_duration = max(0.1, end_at - start_at)
        is_trimmed = start_at > 0.001 or end_at < video.metadata.duration - 0.001
        duration = selected_duration if is_trimmed else None
    original_preview = (
        outputs_dir / f"{job.id}-original.mp4"
        if job.kind == JobKind.PREVIEW or duration is not None
        else None
    )
    total_frames = (
        max(1, round((duration or video.metadata.duration) * video.metadata.fps))
        if video.metadata.fps
        else video.metadata.frame_count
    )
    tile_size, encoder_preset, crf = _preset_config(job.preset, device)
    log_path = workdir / "ffmpeg.log"
    try:
        progress(JobProgress(stage="Preparing video", percent=2, frames_total=total_frames))
        if original_preview:
            _run_checked(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start_at:.3f}",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(original_preview),
                ],
                runtime,
                "The selected source section could not be prepared.",
            )
        model.load(
            device,
            model_dir,
            lambda stage, pct, detail: progress(
                JobProgress(
                    stage=stage,
                    percent=min(12, 4 + pct * 0.08),
                    frames_total=total_frames,
                    detail=detail,
                )
            ),
        )
        decode_args = ["ffmpeg", "-v", "error"]
        if start_at:
            decode_args += ["-ss", f"{start_at:.3f}"]
        decode_args += ["-i", str(source)]
        if duration:
            decode_args += ["-t", f"{duration:.3f}"]
        decode_args += ["-map", "0:v:0", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        decode_log = log_path.open("wb")
        decoder = subprocess.Popen(decode_args, stdout=subprocess.PIPE, stderr=decode_log)
        encode_args = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{job.target_width}x{job.target_height}",
            "-r",
            f"{video.metadata.fps or 30}",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            encoder_preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            str(video_only),
        ]
        encode_log = log_path.open("ab")
        encoder = subprocess.Popen(encode_args, stdin=subprocess.PIPE, stderr=encode_log)
        runtime.add(decoder)
        runtime.add(encoder)
        frame_bytes = video.metadata.width * video.metadata.height * 3
        frames_done = 0
        smoothed_fps: float | None = None
        last_time = time.monotonic()
        assert decoder.stdout and encoder.stdin
        while not runtime.cancel.is_set():
            raw = _read_frame(decoder.stdout, frame_bytes)
            if len(raw) != frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                video.metadata.height, video.metadata.width, 3
            )
            try:
                enhanced = model.enhance_frame(
                    frame, (job.target_width, job.target_height), tile_size, runtime.cancel
                )
            except RuntimeError as exc:
                if "memory" not in str(exc).lower() and "allocate" not in str(exc).lower():
                    raise
                safer_tile = max(64, tile_size // 2)
                progress(
                    JobProgress(
                        stage="Optimizing memory",
                        percent=12 + (frames_done / max(1, total_frames or 1)) * 78,
                        frames_done=frames_done,
                        frames_total=total_frames,
                        detail=f"Retrying with {safer_tile}px tiles",
                    )
                )
                enhanced = model.enhance_frame(
                    frame, (job.target_width, job.target_height), safer_tile, runtime.cancel
                )
                tile_size = safer_tile
            encoder.stdin.write(enhanced.tobytes())
            frames_done += 1
            now = time.monotonic()
            instant = 1 / max(0.001, now - last_time)
            smoothed_fps = instant if smoothed_fps is None else smoothed_fps * 0.9 + instant * 0.1
            last_time = now
            elapsed = now - started
            eta = (
                (max(0, total_frames - frames_done) / smoothed_fps)
                if total_frames and smoothed_fps
                else None
            )
            progress(
                JobProgress(
                    stage="Enhancing",
                    percent=min(90, 12 + frames_done / max(1, total_frames or frames_done) * 78),
                    frames_done=frames_done,
                    frames_total=total_frames,
                    processing_fps=smoothed_fps,
                    elapsed_seconds=elapsed,
                    eta_seconds=eta,
                )
            )
        if runtime.cancel.is_set():
            raise InterruptedError("Enhancement cancelled")
        encoder.stdin.close()
        decoder.wait(timeout=30)
        encoder.wait(timeout=120)
        runtime.remove(decoder)
        runtime.remove(encoder)
        decode_log.close()
        encode_log.close()
        if decoder.returncode != 0 or encoder.returncode != 0 or not video_only.exists():
            raise RuntimeError(
                "FFmpeg could not encode the enhanced video. See the local backend log."
            )
        progress(
            JobProgress(
                stage="Adding audio", percent=94, frames_done=frames_done, frames_total=total_frames
            )
        )
        mux_args = ["ffmpeg", "-y", "-v", "error", "-i", str(video_only)]
        if start_at:
            mux_args += ["-ss", f"{start_at:.3f}"]
        if duration:
            mux_args += ["-t", f"{duration:.3f}"]
        mux_args += [
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
            str(output),
        ]
        _run_checked(mux_args, runtime, "Audio could not be added to the enhanced video.")
        progress(
            JobProgress(
                stage="Finalizing", percent=99, frames_done=frames_done, frames_total=total_frames
            )
        )
        return output, original_preview, time.monotonic() - started
    except Exception:
        output.unlink(missing_ok=True)
        if original_preview:
            original_preview.unlink(missing_ok=True)
        raise
    finally:
        runtime.close_processes()
        shutil.rmtree(workdir, ignore_errors=True)


def run_streaming_pipeline(
    job: JobRecord,
    video: VideoRecord,
    model: VideoEnhancementModel,
    model_dir: Path,
    outputs_dir: Path,
    temp_root: Path,
    device: str,
    runtime: JobRuntime,
    progress: ProgressSink,
    stream_progress: StreamProgressSink,
) -> tuple[Path, None, float]:
    if not job.stream or not job.stream.chunks:
        raise RuntimeError("The async enhancement has no playable parts.")
    started = time.monotonic()
    stream = job.stream.model_copy(deep=True)
    stream_workdir = temp_root / f"{job.id}-stream"
    stream_workdir.mkdir(parents=True, exist_ok=True)
    output = outputs_dir / f"{job.id}.mp4"
    selected_duration = sum(chunk.end - chunk.start for chunk in stream.chunks)
    total_frames = max(1, round(selected_duration * (video.metadata.fps or 30)))
    completed_frames = 0
    ready_paths: list[Path] = []
    active_index: int | None = None

    try:
        for chunk in stream.chunks:
            if runtime.cancel.is_set():
                raise InterruptedError("Enhancement cancelled")
            active_index = chunk.index
            chunk.status = StreamChunkStatus.PROCESSING
            chunk.progress = 0
            stream_progress(stream.model_copy(deep=True))
            child = job.model_copy(deep=True)
            child.id = f"{job.id}-chunk-{chunk.index:04d}"
            child.kind = JobKind.FULL
            child.trim_start = chunk.start
            child.trim_end = chunk.end
            child.stream = None
            chunk_frames = max(1, round((chunk.end - chunk.start) * (video.metadata.fps or 30)))
            stream_emit_clock = [0.0]

            def update_chunk(
                value: JobProgress,
                current_chunk=chunk,
                planned_frames=chunk_frames,
                base_frames=completed_frames,
                emit_clock=stream_emit_clock,
            ) -> None:
                current_chunk.progress = min(99, value.percent)
                now = time.monotonic()
                if now - emit_clock[0] >= 0.5 or value.percent >= 99:
                    stream_progress(stream.model_copy(deep=True))
                    emit_clock[0] = now
                stage = (
                    f"Enhancing part {current_chunk.index + 1} of {stream.total_chunks}"
                    if value.stage == "Enhancing"
                    else f"Preparing part {current_chunk.index + 1} of {stream.total_chunks}"
                )
                if value.stage in {"Adding audio", "Finalizing"}:
                    stage = (
                        f"Packaging part {current_chunk.index + 1} of {stream.total_chunks}"
                    )
                current_frames = min(planned_frames, value.frames_done)
                overall_frames = base_frames + current_frames
                progress(
                    JobProgress(
                        stage=stage,
                        percent=min(96, 2 + overall_frames / total_frames * 94),
                        frames_done=overall_frames,
                        frames_total=total_frames,
                        processing_fps=value.processing_fps,
                        elapsed_seconds=now - started,
                        eta_seconds=(
                            (total_frames - overall_frames) / value.processing_fps
                            if value.processing_fps
                            else None
                        ),
                        detail=(
                            f"{stream.ready_chunks} part(s) ready to watch"
                            if stream.ready_chunks
                            else "The first playable part is being prepared"
                        ),
                    )
                )

            chunk_output, chunk_original, _seconds = run_pipeline(
                child,
                video,
                model,
                model_dir,
                outputs_dir,
                temp_root,
                device,
                runtime,
                update_chunk,
            )
            if chunk_original:
                chunk_original.unlink(missing_ok=True)
            chunk.status = StreamChunkStatus.READY
            chunk.progress = 100
            chunk.playback_url = f"/api/jobs/{job.id}/stream/{chunk.index}"
            stream.ready_chunks += 1
            stream.buffered_seconds += chunk.end - chunk.start
            completed_frames += chunk_frames
            ready_paths.append(chunk_output)
            stream_progress(stream.model_copy(deep=True))
            progress(
                JobProgress(
                    stage=f"Part {chunk.index + 1} ready · enhancing the next part",
                    percent=min(96, 2 + completed_frames / total_frames * 94),
                    frames_done=min(total_frames, completed_frames),
                    frames_total=total_frames,
                    elapsed_seconds=time.monotonic() - started,
                    detail=f"{stream.buffered_seconds:.0f} seconds ready to watch",
                )
            )

        progress(
            JobProgress(
                stage="Joining enhanced parts",
                percent=98,
                frames_done=total_frames,
                frames_total=total_frames,
                elapsed_seconds=time.monotonic() - started,
                detail="Playback remains available while the final file is assembled",
            )
        )
        manifest = stream_workdir / "parts.txt"
        manifest.write_text(
            "".join(f"file '{path.resolve().as_posix()}'\n" for path in ready_paths),
            encoding="utf-8",
        )
        _run_checked(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            runtime,
            "The enhanced parts could not be joined.",
        )
        return output, None, time.monotonic() - started
    except InterruptedError:
        if active_index is not None:
            stream.chunks[active_index].status = StreamChunkStatus.CANCELLED
            stream_progress(stream.model_copy(deep=True))
        output.unlink(missing_ok=True)
        raise
    except Exception:
        if active_index is not None:
            stream.chunks[active_index].status = StreamChunkStatus.FAILED
            stream_progress(stream.model_copy(deep=True))
        output.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stream_workdir, ignore_errors=True)

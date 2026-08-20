import hashlib
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.inference.base import VideoEnhancementModel
from app.inference.realbasicvsr.engine import (
    RealBasicVSREngine,
    is_mps_runtime_failure,
    select_device,
)
from app.inference.realbasicvsr.video_pipeline import run_experimental_pipeline
from app.jobs.runtime import JobRuntime
from app.schemas.job import (
    CheckpointSegmentStatus,
    JobCheckpoint,
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
CheckpointProgressSink = Callable[[JobCheckpoint], None]


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


def _job_output(outputs_dir: Path, job: JobRecord) -> Path:
    return outputs_dir / f"{job.id}.{job.output_container.value}"


def _scan_processing(job: JobRecord, video: VideoRecord) -> tuple[str | None, float]:
    source_fps = video.metadata.fps or 30.0
    interlaced = video.metadata.field_order not in {"progressive", "unknown", ""}
    if job.scan_treatment.value == "ivtc":
        return "fieldmatch,bwdif=deint=interlaced,decimate", source_fps * 0.8
    if job.scan_treatment.value == "deinterlace" or (
        job.scan_treatment.value == "auto" and interlaced
    ):
        return "bwdif=mode=send_frame:parity=auto:deint=all", source_fps
    return None, source_fps


def _mux_source_tracks(
    enhanced_video: Path,
    source: Path,
    output: Path,
    job: JobRecord,
    runtime: JobRuntime,
    start_at: float,
    duration: float | None,
) -> None:
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(enhanced_video)]
    if start_at:
        args += ["-ss", f"{start_at:.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", str(source), "-map", "0:v:0", "-map", "1:a?"]
    if job.output_container.value == "mkv" and job.track_policy.value == "preserve":
        args += ["-map", "1:s?", "-map", "1:d?", "-map", "1:t?", "-c", "copy"]
    else:
        args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    args += ["-map_metadata", "1" if job.preserve_metadata else "-1"]
    args += ["-map_chapters", "1" if job.preserve_chapters else "-1"]
    args += ["-shortest"]
    if job.output_container.value == "mp4":
        args += ["-movflags", "+faststart"]
    args.append(str(output))
    _run_checked(args, runtime, "Source audio and media tracks could not be preserved.")


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
    output = _job_output(outputs_dir, job)
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
        max(1, round((duration or video.metadata.duration) * _scan_processing(job, video)[1]))
        if video.metadata.fps
        else video.metadata.frame_count
    )
    scan_filter, output_fps = _scan_processing(job, video)
    tile_size, encoder_preset, crf = _preset_config(job.preset, device)
    if job.resource_allocation:
        tile_size = min(tile_size, job.resource_allocation.tile_size)
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
        if scan_filter:
            decode_args += ["-vf", scan_filter]
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
            f"{output_fps:g}",
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
        _mux_source_tracks(video_only, source, output, job, runtime, start_at, duration)
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


def run_realbasicvsr_pipeline(
    job: JobRecord,
    video: VideoRecord,
    engine: RealBasicVSREngine,
    model_dir: Path,
    outputs_dir: Path,
    temp_root: Path,
    runtime: JobRuntime,
    progress: ProgressSink,
) -> tuple[Path, Path | None, float]:
    """Run preview/full jobs through the temporal RealBasicVSR engine."""
    source = Path(video.path)
    output = _job_output(outputs_dir, job)
    restored_base = outputs_dir / f"{job.id}-restored-base.mp4"
    if job.kind == JobKind.PREVIEW:
        selected_duration = min(5.0, max(0.1, video.metadata.duration))
        start_at = min(
            max(0.0, job.preview_timestamp - selected_duration / 2),
            max(0, video.metadata.duration - selected_duration),
        )
        duration: float | None = selected_duration
    else:
        start_at = max(0.0, job.trim_start)
        end_at = min(job.trim_end or video.metadata.duration, video.metadata.duration)
        selected_duration = max(0.1, end_at - start_at)
        is_trimmed = start_at > 0.001 or end_at < video.metadata.duration - 0.001
        duration = selected_duration if is_trimmed else None
    original = (
        outputs_dir / f"{job.id}-original.mp4"
        if job.kind == JobKind.PREVIEW or duration is not None
        else None
    )
    total_frames = max(1, round(selected_duration * (video.metadata.fps or 30)))
    started = time.monotonic()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    try:
        progress(JobProgress(stage="Preparing video", percent=2, frames_total=total_frames))
        if original:
            _run_checked(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start_at:.3f}",
                    "-t",
                    f"{selected_duration:.3f}",
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
                    str(original),
                ],
                runtime,
                "The selected source section could not be prepared.",
            )

        device = select_device("auto")

        def load(selected_device: str) -> None:
            engine.load(
                selected_device,
                model_dir,
                lambda percent: progress(
                    JobProgress(
                        stage="Downloading model",
                        percent=min(10, 3 + percent * 0.07),
                        frames_total=total_frames,
                        detail="First use only",
                    )
                ),
            )
            progress(
                JobProgress(
                    stage="Loading model",
                    percent=11,
                    frames_total=total_frames,
                    detail=f"{engine.display_name} · {selected_device.upper()}",
                )
            )

        emit_started = time.monotonic()
        last_processing_rate: float | None = None

        def update(stage: str, percent: float, detail: str | None) -> None:
            nonlocal last_processing_rate
            elapsed = time.monotonic() - emit_started
            if stage == "Restoring":
                mapped_percent = min(92, 12 + percent * 0.84)
                frames_done = min(total_frames, round(total_frames * percent / 95))
                rate = frames_done / elapsed if frames_done and elapsed else None
                if rate:
                    last_processing_rate = rate
                eta = (total_frames - frames_done) / rate if rate else None
                display_stage = "Restoring video"
            else:
                mapped_percent = {
                    "Decoding": 12,
                    "Encoding": 94,
                    "Muxing audio": 97,
                    "Finalizing": 99,
                }.get(stage, min(99, percent))
                frames_done = total_frames if mapped_percent >= 94 else 0
                rate = last_processing_rate
                eta = None
                display_stage = stage
            progress(
                JobProgress(
                    stage=display_stage,
                    percent=mapped_percent,
                    frames_done=frames_done,
                    frames_total=total_frames,
                    processing_fps=rate,
                    elapsed_seconds=elapsed,
                    eta_seconds=eta,
                    detail=detail,
                )
            )

        load(device)
        scan_filter, output_fps = _scan_processing(job, video)
        try:
            stats = run_experimental_pipeline(
                source,
                restored_base,
                engine,
                runtime=runtime,
                progress=update,
                target_width=job.target_width,
                target_height=job.target_height,
                start_at=start_at,
                duration=duration,
                temp_root=temp_root,
                input_filter=scan_filter,
                output_fps=output_fps,
                window_frames=(
                    job.resource_allocation.temporal_window
                    if job.resource_allocation
                    else None
                ),
                scene_aware=job.scene_aware,
                scene_threshold=job.scene_threshold,
            )
        except RuntimeError as error:
            if device != "mps" or not is_mps_runtime_failure(error):
                raise
            progress(
                JobProgress(
                    stage="Switching to CPU",
                    percent=11,
                    frames_total=total_frames,
                    detail="Apple Metal could not run this configuration",
                )
            )
            engine.unload()
            load("cpu")
            stats = run_experimental_pipeline(
                source,
                restored_base,
                engine,
                runtime=runtime,
                progress=update,
                target_width=job.target_width,
                target_height=job.target_height,
                start_at=start_at,
                duration=duration,
                temp_root=temp_root,
                input_filter=scan_filter,
                output_fps=output_fps,
                window_frames=(
                    job.resource_allocation.temporal_window
                    if job.resource_allocation
                    else None
                ),
                scene_aware=job.scene_aware,
                scene_threshold=job.scene_threshold,
            )
        _mux_source_tracks(
            restored_base,
            source,
            output,
            job,
            runtime,
            start_at,
            selected_duration if duration is not None else None,
        )
        restored_base.unlink(missing_ok=True)
        return output, original, max(stats.total_seconds, time.monotonic() - started)
    except Exception:
        output.unlink(missing_ok=True)
        restored_base.unlink(missing_ok=True)
        if original:
            original.unlink(missing_ok=True)
        raise
    finally:
        engine.unload()
        runtime.close_processes()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _concat_parts(
    paths: list[Path], destination: Path, workdir: Path, runtime: JobRuntime
) -> None:
    manifest = workdir / f"{destination.stem}-parts.txt"
    manifest.write_text(
        "".join(f"file '{path.resolve().as_posix()}'\n" for path in paths),
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
            str(destination),
        ],
        runtime,
        "The completed enhancement checkpoints could not be joined.",
    )


def run_checkpointed_pipeline(
    job: JobRecord,
    video: VideoRecord,
    model: VideoEnhancementModel | RealBasicVSREngine,
    model_dir: Path,
    outputs_dir: Path,
    temp_root: Path,
    device: str,
    runtime: JobRuntime,
    progress: ProgressSink,
    checkpoint_progress: CheckpointProgressSink,
) -> tuple[Path, Path | None, float]:
    """Enhance durable ranges and reuse verified ranges after a pause or restart."""
    if not job.checkpoint or not job.checkpoint.segments:
        raise RuntimeError("This job has no resume checkpoint plan.")
    started = time.monotonic()
    checkpoint = job.checkpoint.model_copy(deep=True)
    workdir = temp_root / f"{job.id}-checkpoint"
    workdir.mkdir(parents=True, exist_ok=True)
    output = _job_output(outputs_dir, job)
    selected_duration = sum(segment.end - segment.start for segment in checkpoint.segments)
    total_frames = max(1, round(selected_duration * (video.metadata.fps or 30)))
    completed_frames = 0
    ready_paths: list[Path] = []
    original_paths: list[Path] = []

    try:
        for segment in checkpoint.segments:
            segment_path = outputs_dir / segment.output_name
            original_path = outputs_dir / f"{segment_path.stem}-original.mp4"
            valid = (
                segment.status == CheckpointSegmentStatus.READY
                and segment_path.exists()
                and segment.checksum == _file_checksum(segment_path)
            )
            segment_frames = max(
                1, round((segment.end - segment.start) * (video.metadata.fps or 30))
            )
            if valid:
                ready_paths.append(segment_path)
                if original_path.exists():
                    original_paths.append(original_path)
                completed_frames += segment_frames
                continue
            segment.status = CheckpointSegmentStatus.PROCESSING
            segment.progress = 0
            segment.checksum = None
            checkpoint_progress(checkpoint.model_copy(deep=True))

            child = job.model_copy(deep=True)
            child.id = segment_path.stem
            child.kind = JobKind.FULL
            child.trim_start = segment.start
            child.trim_end = segment.end
            child.stream = None
            child.checkpoint = None

            def update_segment(
                value: JobProgress,
                current=segment,
                planned_frames=segment_frames,
                base_frames=completed_frames,
            ) -> None:
                current.progress = min(99, value.percent)
                checkpoint_progress(checkpoint.model_copy(deep=True))
                current_frames = min(planned_frames, value.frames_done)
                overall_frames = base_frames + current_frames
                progress(
                    JobProgress(
                        stage=(
                            f"Checkpoint {current.index + 1} of "
                            f"{len(checkpoint.segments)} · {value.stage}"
                        ),
                        percent=min(98, overall_frames / total_frames * 98),
                        frames_done=overall_frames,
                        frames_total=total_frames,
                        processing_fps=value.processing_fps,
                        elapsed_seconds=time.monotonic() - started,
                        eta_seconds=(
                            (total_frames - overall_frames) / value.processing_fps
                            if value.processing_fps
                            else None
                        ),
                        detail="Completed checkpoints are saved locally and will be reused.",
                    )
                )

            if isinstance(model, RealBasicVSREngine):
                segment_output, segment_original, _ = run_realbasicvsr_pipeline(
                    child,
                    video,
                    model,
                    model_dir,
                    outputs_dir,
                    temp_root,
                    runtime,
                    update_segment,
                )
            else:
                segment_output, segment_original, _ = run_pipeline(
                    child,
                    video,
                    model,
                    model_dir,
                    outputs_dir,
                    temp_root,
                    device,
                    runtime,
                    update_segment,
                )
            segment.status = CheckpointSegmentStatus.READY
            segment.progress = 100
            segment.checksum = _file_checksum(segment_output)
            ready_paths.append(segment_output)
            if segment_original:
                original_paths.append(segment_original)
            completed_frames += segment_frames
            checkpoint_progress(checkpoint.model_copy(deep=True))

        progress(
            JobProgress(
                stage="Joining saved checkpoints",
                percent=99,
                frames_done=total_frames,
                frames_total=total_frames,
                elapsed_seconds=time.monotonic() - started,
            )
        )
        _concat_parts(ready_paths, output, workdir, runtime)
        is_trimmed = job.trim_start > 0.001 or (
            job.trim_end is not None
            and job.trim_end < video.metadata.duration - 0.001
        )
        original = outputs_dir / f"{job.id}-original.mp4" if is_trimmed else None
        if original and len(original_paths) == len(ready_paths):
            _concat_parts(original_paths, original, workdir, runtime)
        elif original:
            original = None
        return output, original, time.monotonic() - started
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
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
    output = _job_output(outputs_dir, job)
    selected_duration = sum(chunk.end - chunk.start for chunk in stream.chunks)
    total_frames = max(1, round(selected_duration * (video.metadata.fps or 30)))
    completed_frames = 0
    ready_paths: list[Path] = []
    active_index: int | None = None

    stream.ready_chunks = 0
    stream.buffered_seconds = 0
    for saved_chunk in stream.chunks:
        saved_path = outputs_dir / f"{job.id}-chunk-{saved_chunk.index:04d}.mp4"
        if saved_chunk.status == StreamChunkStatus.READY and saved_path.exists():
            ready_paths.append(saved_path)
            stream.ready_chunks += 1
            stream.buffered_seconds += saved_chunk.end - saved_chunk.start
            completed_frames += max(
                1, round((saved_chunk.end - saved_chunk.start) * (video.metadata.fps or 30))
            )
        elif saved_chunk.status != StreamChunkStatus.QUEUED:
            saved_chunk.status = StreamChunkStatus.QUEUED
            saved_chunk.progress = 0
            saved_chunk.playback_url = None
    stream_progress(stream.model_copy(deep=True))

    try:
        for chunk in stream.chunks:
            if runtime.cancel.is_set():
                raise InterruptedError("Enhancement cancelled")
            chunk_path = outputs_dir / f"{job.id}-chunk-{chunk.index:04d}.mp4"
            if chunk.status == StreamChunkStatus.READY and chunk_path.exists():
                continue
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
            stream.chunks[active_index].status = (
                StreamChunkStatus.QUEUED
                if runtime.pause.is_set()
                else StreamChunkStatus.CANCELLED
            )
            stream.chunks[active_index].progress = 0
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

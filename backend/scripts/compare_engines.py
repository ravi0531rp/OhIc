#!/usr/bin/env python3
"""Process one short clip through Real-ESRGAN and RealBasicVSR."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.device import detect_hardware  # noqa: E402
from app.inference.realbasicvsr.engine import (  # noqa: E402
    RealBasicVSREngine,
    is_mps_runtime_failure,
    select_device,
)
from app.inference.realbasicvsr.video_pipeline import run_experimental_pipeline  # noqa: E402
from app.inference.realesrgan import RealESRGANModel  # noqa: E402
from app.jobs.pipeline import JobRuntime, run_pipeline  # noqa: E402
from app.schemas.job import (  # noqa: E402
    JobKind,
    JobProgress,
    JobRecord,
    JobStatus,
    QualityPreset,
)
from app.schemas.video import SourceType, VideoRecord  # noqa: E402
from app.video.probe import probe_video  # noqa: E402
from app.video.recommendations import recommend_targets  # noqa: E402


def emit(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create Original, Real-ESRGAN, and RealBasicVSR comparison videos"
    )
    result.add_argument("--input", required=True, type=Path)
    result.add_argument("--output-dir", type=Path, default=Path("tmp/comparison"))
    result.add_argument("--start", type=float, default=0)
    result.add_argument("--duration", type=float, default=10)
    result.add_argument("--target-width", type=int)
    result.add_argument("--target-height", type=int)
    result.add_argument("--device", choices=("auto", "mps", "cuda", "cpu"), default="auto")
    result.add_argument("--chunk-frames", type=int)
    result.add_argument("--overlap-frames", type=int)
    result.add_argument("--allow-large-input", action="store_true")
    return result


def target_size(width: int, height: int, requested_width: int | None, requested_height: int | None):
    ratio = width / height
    output_width = requested_width or (
        round(requested_height * ratio) if requested_height else width * 2
    )
    output_height = requested_height or round(output_width / ratio)
    output_width -= output_width % 2
    output_height -= output_height % 2
    if abs(output_width / output_height - ratio) > 0.01:
        raise ValueError("Comparison target dimensions must preserve the source aspect ratio.")
    return output_width, output_height


def prepare_clip(source: Path, destination: Path, start: float, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
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
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        check=True,
    )


def main() -> int:
    args = parser().parse_args()
    source = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not source.is_file():
        emit("error", message=f"Input video does not exist: {source}")
        return 2
    if args.start < 0 or args.duration <= 0:
        emit("error", message="Start must be non-negative and duration must be positive.")
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    original = output_dir / "original.mp4"
    realesrgan_output = output_dir / "realesrgan.mp4"
    realbasicvsr_output = output_dir / "realbasicvsr.mp4"
    report_path = output_dir / "comparison.json"

    try:
        emit("stage", stage="Preparing identical source clip")
        prepare_clip(source, original, args.start, args.duration)
        metadata = probe_video(original)
        width, height = target_size(
            metadata.width,
            metadata.height,
            args.target_width,
            args.target_height,
        )
        video = VideoRecord(
            id="comparison-source",
            source_type=SourceType.UPLOAD,
            original_name=original.name,
            path=str(original),
            metadata=metadata,
            targets=recommend_targets(metadata),
            created_at=datetime.now(UTC),
            playback_url="",
        )

        emit("stage", stage="Running Real-ESRGAN", target=f"{width}x{height}")
        realesrgan = RealESRGANModel()
        frame_events: list[JobProgress] = []
        job = JobRecord(
            id="comparison-realesrgan",
            video_id=video.id,
            kind=JobKind.FULL,
            status=JobStatus.PREPARING,
            model_id=realesrgan.metadata.identifier,
            preset=QualityPreset.BALANCED,
            target_width=width,
            target_height=height,
            preview_timestamp=0,
            progress=JobProgress(),
            created_at=datetime.now(UTC),
        )
        hardware = detect_hardware()
        frame_device = (
            hardware.device
            if hardware.device in realesrgan.metadata.supported_devices
            else "cpu"
        )
        try:
            generated, _original, realesrgan_seconds = run_pipeline(
                job,
                video,
                realesrgan,
                settings.resolved_model_dir,
                output_dir,
                settings.data_dir / "temp",
                frame_device,
                JobRuntime(),
                frame_events.append,
            )
            os.replace(generated, realesrgan_output)
        finally:
            realesrgan.unload()
        last_frame_event = next(
            (event for event in reversed(frame_events) if event.processing_fps),
            JobProgress(),
        )

        emit("stage", stage="Running RealBasicVSR", target=f"{width}x{height}")
        temporal = RealBasicVSREngine()
        requested_device = select_device(args.device)
        temporal.load(
            requested_device,
            settings.resolved_model_dir,
            lambda percent: emit(
                "progress", stage="Downloading RealBasicVSR", percent=round(percent, 2)
            ),
        )
        try:
            try:
                temporal_stats = run_experimental_pipeline(
                    original,
                    realbasicvsr_output,
                    temporal,
                    runtime=JobRuntime(),
                    progress=lambda stage, percent, detail: emit(
                        "progress", stage=stage, percent=round(percent, 2), detail=detail
                    ),
                    window_frames=args.chunk_frames,
                    overlap_frames=args.overlap_frames,
                    target_width=width,
                    target_height=height,
                    max_input_pixels=(
                        7680 * 4320 if args.allow_large_input else 1280 * 720
                    ),
                )
            except RuntimeError as error:
                should_retry_on_cpu = (
                    args.device == "auto"
                    and requested_device == "mps"
                    and is_mps_runtime_failure(error)
                )
                if not should_retry_on_cpu:
                    raise
                emit("warning", message="Apple Metal failed; retrying RealBasicVSR on CPU")
                temporal.unload()
                temporal.load("cpu", settings.resolved_model_dir)
                temporal_stats = run_experimental_pipeline(
                    original,
                    realbasicvsr_output,
                    temporal,
                    runtime=JobRuntime(),
                    target_width=width,
                    target_height=height,
                    max_input_pixels=(
                        7680 * 4320 if args.allow_large_input else 1280 * 720
                    ),
                )
        finally:
            temporal.unload()

        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "path": str(source),
                "clip": str(original),
                "start_seconds": args.start,
                "duration_seconds": metadata.duration,
                "resolution": f"{metadata.width}x{metadata.height}",
                "fps": metadata.fps,
                "bytes": original.stat().st_size,
            },
            "target_resolution": f"{width}x{height}",
            "realesrgan": {
                "path": str(realesrgan_output),
                "device": frame_device,
                "processing_seconds": realesrgan_seconds,
                "processing_fps": last_frame_event.processing_fps,
                "bytes": realesrgan_output.stat().st_size,
            },
            "realbasicvsr": json.loads(temporal_stats.to_json()) | {
                "path": str(realbasicvsr_output)
            },
            "visual_checklist": [
                "temporal consistency and flicker",
                "face, hair, and mouth stability",
                "text shape stability",
                "foliage shimmer and fine detail",
                "motion smear or ghosting",
                "invented detail",
                "window boundary jumps",
                "color fidelity",
            ],
        }
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        emit(
            "complete",
            output_dir=str(output_dir),
            report=str(report_path),
            elapsed_seconds=round(
                realesrgan_seconds + temporal_stats.total_seconds, 3
            ),
        )
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        emit("error", message=str(error))
        return 1


if __name__ == "__main__":
    started = time.perf_counter()
    code = main()
    emit("exit", code=code, wall_seconds=round(time.perf_counter() - started, 3))
    raise SystemExit(code)

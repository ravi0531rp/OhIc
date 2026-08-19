#!/usr/bin/env python3
"""Run the isolated RealBasicVSR experiment against one local video."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.inference.realbasicvsr.engine import RealBasicVSREngine, select_device  # noqa: E402
from app.inference.realbasicvsr.video_pipeline import run_experimental_pipeline  # noqa: E402
from app.jobs.pipeline import JobRuntime  # noqa: E402


def emit(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Experimental bounded-memory RealBasicVSR x4 video restoration"
    )
    result.add_argument("--input", required=True, type=Path, help="Source video")
    result.add_argument("--output", required=True, type=Path, help="Restored MP4")
    result.add_argument("--device", choices=("auto", "mps", "cuda", "cpu"), default="auto")
    result.add_argument("--model-dir", type=Path, help="Checkpoint cache directory")
    result.add_argument("--chunk-frames", type=int, help="Total frames retained per window")
    result.add_argument("--overlap-frames", type=int, help="Context frames at each boundary")
    result.add_argument("--target-width", type=int, help="Optional final Lanczos width")
    result.add_argument("--target-height", type=int, help="Optional final Lanczos height")
    result.add_argument(
        "--allow-large-input",
        action="store_true",
        help="Override the experimental 720p input safety limit",
    )
    result.add_argument("--debug", action="store_true", help="Print a traceback on failure")
    return result


def mps_runtime_failure(error: RuntimeError) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("mps", "metal", "not implemented", "placeholder"))


def main() -> int:
    args = parser().parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        emit("error", message=f"Input video does not exist: {source}")
        return 2
    if source == output:
        emit("error", message="Input and output paths must be different.")
        return 2

    model_dir = (args.model_dir or get_settings().resolved_model_dir).expanduser().resolve()
    requested_device = args.device
    engine = RealBasicVSREngine()
    runtime = JobRuntime()

    def load(device: str) -> None:
        emit("stage", stage="Preparing model", device=device)
        engine.load(
            device,
            model_dir,
            lambda percent: emit(
                "progress", stage="Downloading model", percent=round(percent, 2)
            ),
        )
        emit(
            "stage",
            stage="Model ready",
            device=device,
            seconds=round(engine.model_load_seconds, 3),
        )

    def progress(stage: str, percent: float, detail: str | None) -> None:
        emit("progress", stage=stage, percent=round(percent, 2), detail=detail)

    try:
        device = select_device(requested_device)
        load(device)
        try:
            stats = run_experimental_pipeline(
                source,
                output,
                engine,
                runtime=runtime,
                progress=progress,
                window_frames=args.chunk_frames,
                overlap_frames=args.overlap_frames,
                target_width=args.target_width,
                target_height=args.target_height,
                max_input_pixels=(7680 * 4320 if args.allow_large_input else 1280 * 720),
            )
        except RuntimeError as error:
            if requested_device != "auto" or device != "mps" or not mps_runtime_failure(error):
                raise
            emit(
                "warning",
                message=(
                    "RealBasicVSR could not run this configuration on Apple Metal; "
                    "retrying on CPU."
                ),
                detail=str(error),
            )
            engine.unload()
            runtime = JobRuntime()
            load("cpu")
            stats = run_experimental_pipeline(
                source,
                output,
                engine,
                runtime=runtime,
                progress=progress,
                window_frames=args.chunk_frames,
                overlap_frames=args.overlap_frames,
                target_width=args.target_width,
                target_height=args.target_height,
                max_input_pixels=(7680 * 4320 if args.allow_large_input else 1280 * 720),
            )
        emit("complete", output=str(output), stats=json.loads(stats.to_json()))
        return 0
    except KeyboardInterrupt:
        runtime.stop()
        emit("cancelled", message="RealBasicVSR processing was interrupted.")
        return 130
    except Exception as error:
        runtime.stop()
        emit("error", message=str(error))
        if args.debug:
            traceback.print_exc()
        return 1
    finally:
        engine.unload()


if __name__ == "__main__":
    raise SystemExit(main())

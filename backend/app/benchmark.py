import argparse
import time

import numpy as np

from app.core.config import get_settings
from app.core.device import detect_hardware
from app.inference.registry import ModelRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark an OhIc enhancement model")
    parser.add_argument("--model", default="lanczos-test")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    registry = ModelRegistry(include_test=True)
    model = registry.get(args.model)
    hardware = detect_hardware()
    device = hardware.device if device_supported(model, hardware.device) else "cpu"
    model.load(device, get_settings().resolved_model_dir)
    frame = np.random.default_rng(42).integers(0, 256, (args.height, args.width, 3), dtype=np.uint8)
    started = time.perf_counter()
    for _ in range(args.frames):
        model.enhance_frame(frame, (args.width * 2, args.height * 2), 192)
    elapsed = time.perf_counter() - started
    print(f"device: {hardware.display_name} ({device})")
    print(f"model: {model.metadata.display_name}")
    print(f"source: {args.width}x{args.height}")
    print(f"destination: {args.width * 2}x{args.height * 2}")
    print(f"frames: {args.frames}")
    print(f"total_seconds: {elapsed:.3f}")
    print(f"inference_fps: {args.frames / elapsed:.3f}")


def device_supported(model, device: str) -> bool:
    return device in model.metadata.supported_devices


if __name__ == "__main__":
    main()

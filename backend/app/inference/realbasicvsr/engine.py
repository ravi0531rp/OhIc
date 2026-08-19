from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock

import numpy as np

from app.inference.base import ModelMetadata
from app.inference.realbasicvsr.model import RealBasicVSRNet
from app.inference.weights import download_weight

REALBASICVSR_CHECKPOINT = (
    "realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth"
)
REALBASICVSR_CHECKPOINT_URL = (
    "https://download.openmmlab.com/mmediting/restorers/real_basicvsr/"
    + REALBASICVSR_CHECKPOINT
)
REALBASICVSR_CHECKPOINT_SHA256 = (
    "52f77c2c835aaa3fe675b3959b2f85010a6c6f63f77f7e279394646e55a4e376"
)
DownloadProgress = Callable[[float], None]


def select_device(requested: str = "auto") -> str:
    import torch

    if requested not in {"auto", "mps", "cuda", "cpu"}:
        raise ValueError(f"Unsupported RealBasicVSR device: {requested}")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("Apple Metal is not available to PyTorch on this system.")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available to PyTorch on this system.")
    if requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def is_mps_runtime_failure(error: RuntimeError) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("mps", "metal", "not implemented", "placeholder"))


def checkpoint_state(checkpoint: object) -> dict[str, object]:
    if not isinstance(checkpoint, dict):
        raise RuntimeError("The RealBasicVSR checkpoint has an unsupported structure.")
    state = checkpoint.get("state_dict", checkpoint)
    if not isinstance(state, dict):
        raise RuntimeError("The RealBasicVSR checkpoint does not contain model weights.")
    for prefix in ("generator_ema.", "generator."):
        selected = {
            key.removeprefix(prefix): value
            for key, value in state.items()
            if key.startswith(prefix)
        }
        if selected:
            return selected
    raise RuntimeError("The RealBasicVSR generator weights are missing from the checkpoint.")


class RealBasicVSREngine:
    metadata = ModelMetadata(
        identifier="realbasicvsr-x4-experimental",
        display_name="RealBasicVSR ×4",
        scale_factors=(4,),
        supported_devices=("mps", "cuda", "cpu"),
        weights=(REALBASICVSR_CHECKPOINT,),
        license="Apache-2.0; checkpoint redistribution terms require review",
        source_url="https://github.com/ckkelvinchan/RealBasicVSR",
        description="Temporally-aware restoration with better frame-to-frame consistency",
        experimental=True,
        temporal=True,
        supports_stream=False,
        max_input_pixels=1280 * 720,
    )
    identifier = metadata.identifier
    display_name = metadata.display_name
    scale = 4

    def __init__(self) -> None:
        self._model: RealBasicVSRNet | None = None
        self._device = "cpu"
        self._lock = RLock()
        self.model_load_seconds = 0.0

    @property
    def device(self) -> str:
        return self._device

    def load(
        self,
        device: str,
        model_dir: Path,
        download_progress: DownloadProgress | None = None,
    ) -> Path:
        import torch

        with self._lock:
            if self._model is not None and self._device == device:
                return model_dir / REALBASICVSR_CHECKPOINT
            started = time.perf_counter()
            checkpoint_path = download_weight(
                REALBASICVSR_CHECKPOINT_URL,
                model_dir / REALBASICVSR_CHECKPOINT,
                download_progress,
                sha256=REALBASICVSR_CHECKPOINT_SHA256,
                minimum_size=100_000_000,
            )
            try:
                checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
                model = RealBasicVSRNet(sequential_cleaning=True)
                model.load_state_dict(checkpoint_state(checkpoint), strict=True)
            except Exception as exc:
                raise RuntimeError(
                    "RealBasicVSR could not load its validated checkpoint. "
                    "Remove the cached file and retry."
                ) from exc
            try:
                model.eval().requires_grad_(False).to(device=device, dtype=torch.float32)
            except Exception as exc:
                self._clear_cache(device)
                label = "Apple Metal/MPS" if device == "mps" else device.upper()
                raise RuntimeError(
                    f"RealBasicVSR could not initialize on {label} for this configuration."
                ) from exc
            self._model = model
            self._device = device
            self.model_load_seconds = time.perf_counter() - started
            return checkpoint_path

    def enhance_sequence(
        self, frames: list[np.ndarray] | tuple[np.ndarray, ...], cancel: Event | None = None
    ) -> list[np.ndarray]:
        import torch

        if self._model is None:
            raise RuntimeError("RealBasicVSR has not been loaded.")
        if len(frames) < 2:
            raise ValueError("RealBasicVSR needs at least two adjacent frames.")
        if cancel and cancel.is_set():
            raise InterruptedError("RealBasicVSR processing was cancelled.")
        array = np.stack(frames)
        if array.dtype != np.uint8 or array.ndim != 4 or array.shape[-1] != 3:
            raise ValueError("RealBasicVSR expects RGB uint8 video frames.")
        tensor = torch.from_numpy(array.copy()).permute(0, 3, 1, 2).unsqueeze(0)
        tensor = tensor.to(self._device, dtype=torch.float32) / 255.0
        with torch.inference_mode():
            output = self._model(tensor).clamp_(0, 1)
        if cancel and cancel.is_set():
            raise InterruptedError("RealBasicVSR processing was cancelled.")
        output = (output[0].float().cpu().permute(0, 2, 3, 1).numpy() * 255.0).round()
        return [frame.astype(np.uint8) for frame in output]

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._clear_cache(self._device)

    @staticmethod
    def _clear_cache(device: str) -> None:
        try:
            import torch

            if device == "mps" and hasattr(torch, "mps"):
                torch.mps.empty_cache()
            elif device == "cuda":
                torch.cuda.empty_cache()
        except RuntimeError:
            pass

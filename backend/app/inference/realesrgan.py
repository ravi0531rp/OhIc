from pathlib import Path
from threading import Event, RLock

import numpy as np
from PIL import Image

from app.inference.base import ModelMetadata, ProgressCallback, VideoEnhancementModel
from app.inference.weights import download_weight


class RealESRGANModel(VideoEnhancementModel):
    metadata = ModelMetadata(
        identifier="realesrgan-x2plus",
        display_name="Real-ESRGAN ×2",
        scale_factors=(2,),
        supported_devices=("mps", "cuda", "cpu"),
        weights=("RealESRGAN_x2plus.pth",),
        license="BSD-3-Clause",
        source_url="https://github.com/xinntao/Real-ESRGAN",
    )
    weight_url = (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
    )

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"
        self._lock = RLock()

    def load(self, device: str, model_dir: Path, progress: ProgressCallback | None = None) -> None:
        import torch

        from app.inference.rrdbnet import RRDBNet

        with self._lock:
            if self._model is not None and self._device == device:
                return
            if progress:
                progress("Downloading AI model", 0, "First use only")
            weight_path = download_weight(
                self.weight_url,
                model_dir / self.metadata.weights[0],
                lambda percent: (
                    progress("Downloading AI model", percent, "First use only")
                    if progress
                    else None
                ),
            )
            if progress:
                progress("Loading AI model", 0, self.metadata.display_name)
            network = RRDBNet(scale=2, num_blocks=23)
            try:
                checkpoint = torch.load(weight_path, map_location="cpu", weights_only=True)
                state = checkpoint.get("params_ema") or checkpoint.get("params") or checkpoint
                network.load_state_dict(state, strict=True)
            except Exception as exc:
                weight_path.unlink(missing_ok=True)
                raise RuntimeError(
                    "AI model validation failed. The model will be downloaded again next time."
                ) from exc
            network.eval().requires_grad_(False).to(device)
            if device == "cuda":
                network.half()
            self._model = network
            self._device = device
            if progress:
                progress("Loading AI model", 100, self.metadata.display_name)

    def unload(self) -> None:
        with self._lock:
            self._model = None
            try:
                import torch

                if self._device == "mps":
                    torch.mps.empty_cache()
                elif self._device == "cuda":
                    torch.cuda.empty_cache()
            except (ImportError, RuntimeError):
                pass

    def _run_tile(self, tile: np.ndarray) -> np.ndarray:
        import torch

        assert self._model is not None
        height, width = tile.shape[:2]
        if height % 2 or width % 2:
            tile = np.pad(tile, ((0, height % 2), (0, width % 2), (0, 0)), mode="edge")
        tensor = torch.from_numpy(tile.copy()).permute(2, 0, 1).unsqueeze(0)
        tensor = tensor.to(
            self._device, dtype=torch.float16 if self._device == "cuda" else torch.float32
        )
        tensor = tensor / 255.0
        with torch.inference_mode():
            output = self._model(tensor).clamp_(0, 1)
        array = (output[0].float().cpu().permute(1, 2, 0).numpy() * 255.0).round()
        return array[: height * 2, : width * 2].astype(np.uint8)

    def _tiled(self, frame: np.ndarray, tile_size: int, cancel: Event | None) -> np.ndarray:
        height, width = frame.shape[:2]
        scale, pad = 2, 12
        output = np.empty((height * scale, width * scale, 3), dtype=np.uint8)
        for top in range(0, height, tile_size):
            for left in range(0, width, tile_size):
                if cancel and cancel.is_set():
                    raise InterruptedError("Enhancement cancelled")
                bottom, right = min(top + tile_size, height), min(left + tile_size, width)
                ext_top, ext_left = max(0, top - pad), max(0, left - pad)
                ext_bottom, ext_right = min(height, bottom + pad), min(width, right + pad)
                enhanced = self._run_tile(frame[ext_top:ext_bottom, ext_left:ext_right])
                crop_top, crop_left = (top - ext_top) * scale, (left - ext_left) * scale
                crop_bottom = crop_top + (bottom - top) * scale
                crop_right = crop_left + (right - left) * scale
                output[top * scale : bottom * scale, left * scale : right * scale] = enhanced[
                    crop_top:crop_bottom, crop_left:crop_right
                ]
        return output

    def enhance_frame(
        self,
        frame: np.ndarray,
        target_size: tuple[int, int],
        tile_size: int,
        cancel: Event | None = None,
    ) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("The AI model has not been loaded.")
        if cancel and cancel.is_set():
            raise InterruptedError("Enhancement cancelled")
        enhanced = self._tiled(frame, tile_size, cancel) if tile_size > 0 else self._run_tile(frame)
        if (enhanced.shape[1], enhanced.shape[0]) != target_size:
            enhanced = np.asarray(
                Image.fromarray(enhanced).resize(target_size, Image.Resampling.LANCZOS)
            )
        return enhanced

    def estimate_memory(self, width: int, height: int, tile_size: int) -> int:
        pixels = min(width * height, tile_size * tile_size if tile_size else width * height)
        return int(pixels * 64 * 4 * 8)

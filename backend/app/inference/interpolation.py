from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image, ImageFilter

from app.inference.base import ModelMetadata, ProgressCallback, VideoEnhancementModel


class InterpolationModel(VideoEnhancementModel):
    """Deterministic test model. It is never presented as AI in the product UI."""

    metadata = ModelMetadata(
        identifier="lanczos-test",
        display_name="Lanczos test model",
        scale_factors=(1, 2, 4),
        supported_devices=("cpu",),
        weights=(),
        license="MIT",
        source_url="https://ffmpeg.org/",
    )

    def load(self, device: str, model_dir: Path, progress: ProgressCallback | None = None) -> None:
        if progress:
            progress("Loading test model", 100, None)

    def unload(self) -> None:
        return None

    def enhance_frame(
        self,
        frame: np.ndarray,
        target_size: tuple[int, int],
        tile_size: int,
        cancel: Event | None = None,
    ) -> np.ndarray:
        if cancel and cancel.is_set():
            raise InterruptedError("Enhancement cancelled")
        image = Image.fromarray(frame).resize(target_size, Image.Resampling.LANCZOS)
        return np.asarray(image.filter(ImageFilter.UnsharpMask(radius=1, percent=70, threshold=3)))

    def estimate_memory(self, width: int, height: int, tile_size: int) -> int:
        return width * height * 12

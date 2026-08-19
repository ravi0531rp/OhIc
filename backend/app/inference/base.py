from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np

ProgressCallback = Callable[[str, float, str | None], None]


@dataclass(frozen=True)
class ModelMetadata:
    identifier: str
    display_name: str
    scale_factors: tuple[int, ...]
    supported_devices: tuple[str, ...]
    weights: tuple[str, ...]
    license: str
    source_url: str
    description: str = "Frame-based video enhancement"
    experimental: bool = False
    temporal: bool = False
    supports_stream: bool = True
    max_input_pixels: int | None = None


class VideoEnhancementModel(ABC):
    metadata: ModelMetadata

    @abstractmethod
    def load(self, device: str, model_dir: Path, progress: ProgressCallback | None = None) -> None:
        """Load model weights onto a device."""

    @abstractmethod
    def unload(self) -> None:
        """Release model memory."""

    @abstractmethod
    def enhance_frame(
        self,
        frame: np.ndarray,
        target_size: tuple[int, int],
        tile_size: int,
        cancel: Event | None = None,
    ) -> np.ndarray:
        """Enhance one RGB uint8 frame and return RGB uint8 pixels."""

    def enhance_frames(
        self,
        frames: list[np.ndarray],
        target_size: tuple[int, int],
        tile_size: int,
        cancel: Event | None = None,
    ) -> list[np.ndarray]:
        return [self.enhance_frame(frame, target_size, tile_size, cancel) for frame in frames]

    @abstractmethod
    def estimate_memory(self, width: int, height: int, tile_size: int) -> int:
        """Estimate peak bytes for one frame."""

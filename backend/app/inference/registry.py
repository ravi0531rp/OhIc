from app.inference.base import VideoEnhancementModel
from app.inference.interpolation import InterpolationModel
from app.inference.realesrgan import RealESRGANModel


class ModelRegistry:
    def __init__(self, include_test: bool = False) -> None:
        self._models: dict[str, VideoEnhancementModel] = {}
        self.register(RealESRGANModel())
        if include_test:
            self.register(InterpolationModel())

    def register(self, model: VideoEnhancementModel) -> None:
        self._models[model.metadata.identifier] = model

    def get(self, identifier: str) -> VideoEnhancementModel:
        try:
            return self._models[identifier]
        except KeyError as exc:
            raise ValueError(f"Unknown enhancement model: {identifier}") from exc

    def available(self) -> list[VideoEnhancementModel]:
        return list(self._models.values())

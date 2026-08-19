from app.inference.base import VideoEnhancementModel
from app.inference.interpolation import InterpolationModel
from app.inference.realbasicvsr import RealBasicVSREngine
from app.inference.realesrgan import RealESRGANModel

EnhancementBackend = VideoEnhancementModel | RealBasicVSREngine


class ModelRegistry:
    def __init__(
        self, include_test: bool = False, enable_realbasicvsr: bool = False
    ) -> None:
        self._models: dict[str, EnhancementBackend] = {}
        self.register(RealESRGANModel())
        if enable_realbasicvsr:
            self.register(RealBasicVSREngine())
        if include_test:
            self.register(InterpolationModel())

    def register(self, model: EnhancementBackend) -> None:
        self._models[model.metadata.identifier] = model

    def get(self, identifier: str) -> EnhancementBackend:
        try:
            return self._models[identifier]
        except KeyError as exc:
            raise ValueError(f"Unknown enhancement model: {identifier}") from exc

    def available(self) -> list[EnhancementBackend]:
        return list(self._models.values())

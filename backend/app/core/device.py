from app.schemas.system import HardwareInfo


def detect_hardware() -> HardwareInfo:
    try:
        import torch

        if torch.backends.mps.is_available():
            return HardwareInfo(
                device="mps", display_name="MPS device", acceleration="Hardware acceleration"
            )
        if torch.cuda.is_available():
            memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return HardwareInfo(
                device="cuda",
                display_name="CUDA device",
                acceleration="Hardware acceleration",
                memory_gb=memory,
            )
    except ImportError:
        pass
    return HardwareInfo(device="cpu", display_name="CPU", acceleration="CPU processing")

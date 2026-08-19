import platform
import subprocess

from app.schemas.system import HardwareInfo


def _apple_chip_name() -> str:
    if platform.system() != "Darwin":
        return "Apple Silicon"
    try:
        name = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        return name or "Apple Silicon"
    except (OSError, subprocess.SubprocessError):
        return "Apple Silicon"


def detect_hardware() -> HardwareInfo:
    try:
        import torch

        if torch.backends.mps.is_available():
            return HardwareInfo(
                device="mps", display_name=_apple_chip_name(), acceleration="Metal acceleration"
            )
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return HardwareInfo(
                device="cuda", display_name=name, acceleration="CUDA acceleration", memory_gb=memory
            )
    except ImportError:
        pass
    return HardwareInfo(
        device="cpu", display_name=platform.processor() or "CPU", acceleration="CPU processing"
    )

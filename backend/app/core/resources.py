import os
import platform
import re
import subprocess
from pathlib import Path

from app.schemas.system import ResourceAllocation, ResourceSnapshot


def _memory() -> tuple[int, int]:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(os.sysconf("SC_PHYS_PAGES") * page_size / 1024**2)
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        available = int(available_pages * page_size / 1024**2)
        if total > 0 and available > 0:
            return total, available
    except (OSError, ValueError):
        pass
    if platform.system() == "Darwin":
        try:
            total = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout.strip()
            ) // 1024**2
            output = subprocess.run(
                ["vm_stat"], check=True, capture_output=True, text=True, timeout=2
            ).stdout
            page_match = re.search(r"page size of (\d+) bytes", output)
            page_size = int(page_match.group(1)) if page_match else 4096
            pages = 0
            for label in ("Pages free", "Pages inactive", "Pages speculative"):
                match = re.search(rf"{label}:\s+(\d+)", output)
                pages += int(match.group(1)) if match else 0
            return total, max(1, pages * page_size // 1024**2)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) // 1024
        return values.get("MemTotal", 4096), values.get("MemAvailable", 2048)
    return 4096, 2048


def resource_snapshot() -> ResourceSnapshot:
    total, available = _memory()
    ratio = available / max(1, total)
    pressure = "critical" if ratio < 0.12 else "elevated" if ratio < 0.25 else "normal"
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    return ResourceSnapshot(
        total_memory_mb=total,
        available_memory_mb=available,
        memory_pressure=pressure,
        cpu_count=os.cpu_count() or 1,
        load_average=round(load, 2),
    )


def plan_resources(
    policy: str,
    target_pixels: int,
    memory_limit_mb: int | None = None,
) -> ResourceAllocation:
    snapshot = resource_snapshot()
    budget = min(snapshot.available_memory_mb, memory_limit_mb or snapshot.available_memory_mb)
    tile = 128 if budget < 2048 else 192 if budget < 4096 else 256 if budget < 8192 else 384
    window = 5 if budget < 4096 else 7 if budget < 8192 else 9
    if target_pixels >= 3840 * 2160:
        tile = min(tile, 256)
    if policy == "conservative":
        tile = min(tile, 160)
        window = min(window, 5)
    elif policy == "performance" and snapshot.memory_pressure == "normal":
        tile = min(512, tile + 128)
        window = min(11, window + 2)
    parallel = 1 if target_pixels >= 1920 * 1080 else max(1, min(2, snapshot.cpu_count // 4))
    if snapshot.memory_pressure != "normal" or policy == "conservative":
        parallel = 1
    return ResourceAllocation(
        policy=policy,
        tile_size=tile,
        temporal_window=window,
        max_parallel_jobs=parallel,
        available_memory_mb=snapshot.available_memory_mb,
        memory_pressure=snapshot.memory_pressure,
        rationale=(
            f"{snapshot.memory_pressure.title()} memory pressure · "
            f"{budget} MB available within this job's limit"
        ),
    )

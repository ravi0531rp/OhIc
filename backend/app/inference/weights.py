import os
from collections.abc import Callable
from pathlib import Path

import httpx


class WeightDownloadError(RuntimeError):
    pass


def download_weight(
    url: str,
    destination: Path,
    progress: Callable[[float], None] | None = None,
) -> Path:
    if destination.exists() and destination.stat().st_size > 1_000_000:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            written = 0
            with temporary.open("wb") as target:
                for chunk in response.iter_bytes(1024 * 1024):
                    target.write(chunk)
                    written += len(chunk)
                    if progress and total:
                        progress(min(100.0, written / total * 100))
        if temporary.stat().st_size < 1_000_000:
            raise WeightDownloadError("Downloaded model file is unexpectedly small.")
        os.replace(temporary, destination)
        return destination
    except (OSError, httpx.HTTPError) as exc:
        temporary.unlink(missing_ok=True)
        raise WeightDownloadError(
            "The AI model could not be downloaded. Check your connection and try again."
        ) from exc

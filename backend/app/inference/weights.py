import os
from collections.abc import Callable
from hashlib import sha256 as sha256_digest
from pathlib import Path

import httpx


class WeightDownloadError(RuntimeError):
    pass


def download_weight(
    url: str,
    destination: Path,
    progress: Callable[[float], None] | None = None,
    *,
    sha256: str | None = None,
    minimum_size: int = 1_000_000,
) -> Path:
    def valid(path: Path) -> bool:
        if not path.exists() or path.stat().st_size < minimum_size:
            return False
        if not sha256:
            return True
        digest = sha256_digest()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().lower() == sha256.lower()

    if valid(destination):
        return destination
    destination.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
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
        if not valid(temporary):
            raise WeightDownloadError("Downloaded model file failed integrity validation.")
        os.replace(temporary, destination)
        return destination
    except (OSError, httpx.HTTPError, WeightDownloadError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, WeightDownloadError):
            raise
        raise WeightDownloadError(
            "The AI model could not be downloaded. Check your connection and try again."
        ) from exc

import os
import shutil
from pathlib import Path

import pytest

from app.services.youtube import YouTubeService
from app.video.probe import probe_video


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("OHIC_RUN_NETWORK_TESTS") != "1" or shutil.which("ffmpeg") is None,
    reason="Set OHIC_RUN_NETWORK_TESTS=1 to exercise live YouTube ingestion",
)
def test_live_youtube_inspect_download_and_probe(tmp_path: Path):
    service = YouTubeService(tmp_path)
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    inspected = service.inspect(url)
    path, _info = service.download(url)
    metadata = probe_video(path)

    assert inspected.title
    assert path.suffix == ".mp4"
    assert metadata.width > 0 and metadata.height > 0
    assert metadata.duration > 0
    assert metadata.audio_codec is not None


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("OHIC_RUN_LARGE_YOUTUBE_TESTS") != "1" or shutil.which("ffmpeg") is None,
    reason="Set OHIC_RUN_LARGE_YOUTUBE_TESTS=1 to test the 403 fallback regression",
)
def test_live_youtube_403_falls_back_to_embedded_client(tmp_path: Path):
    service = YouTubeService(tmp_path)
    path, info = service.download("https://www.youtube.com/watch?v=XDhJ8lVGbl8")
    metadata = probe_video(path)

    assert info["title"] == "Lec 1 | MIT 18.03 Differential Equations, Spring 2006"
    assert (metadata.width, metadata.height) == (320, 240)
    assert metadata.duration > 2900
    assert metadata.audio_codec == "AAC"

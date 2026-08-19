from pathlib import Path

import pytest

from app.utils.files import ensure_within, safe_stem, validate_video_filename, validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://m.youtube.com/watch?v=abc123",
    ],
)
def test_youtube_url_validation(url: str):
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://example.com/a", "javascript:alert(1)"]
)
def test_youtube_url_validation_rejects_other_schemes_and_hosts(url: str):
    with pytest.raises(ValueError):
        validate_youtube_url(url)


def test_filename_validation_strips_directories_and_checks_extension():
    assert validate_video_filename("../../holiday.MOV") == "holiday.MOV"
    with pytest.raises(ValueError):
        validate_video_filename("payload.sh")
    assert safe_stem("a weird / name!.mp4") == "name"


def test_ensure_within_blocks_path_traversal(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    assert ensure_within(root / "video.mp4", root) == root / "video.mp4"
    with pytest.raises(ValueError):
        ensure_within(tmp_path / "private.mp4", root)

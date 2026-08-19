from pathlib import Path

import pytest
import yt_dlp

from app.services.youtube import YouTubeService


def test_download_retries_with_alternate_player_clients(monkeypatch, tmp_path: Path):
    attempts: list[dict] = []
    progress: list[dict] = []
    attempt_numbers: list[int] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict):
            self.options = options
            attempts.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url: str, download: bool):
            assert download
            if len(attempts) == 1:
                partial = Path(self.options["outtmpl"].replace("%(ext)s", "mp4.part"))
                partial.write_bytes(b"partial")
                raise yt_dlp.utils.DownloadError("HTTP Error 403: Forbidden")
            for hook in self.options.get("progress_hooks", []):
                hook(
                    {
                        "status": "downloading",
                        "downloaded_bytes": 50,
                        "total_bytes": 100,
                        "speed": 25,
                        "eta": 2,
                    }
                )
            output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
            output.write_bytes(b"valid-video-placeholder")
            return {"title": "Test clip", "ext": "mp4"}

        def prepare_filename(self, _info: dict) -> str:
            return self.options["outtmpl"].replace("%(ext)s", "mp4")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    service = YouTubeService(tmp_path)
    path, info = service.download(
        "https://youtu.be/jNQXAC9IVRw",
        progress.append,
        attempt_numbers.append,
    )

    assert path.exists()
    assert info["safe_title"] == "Test-clip.mp4"
    assert len(attempts) == 2
    assert attempts[0]["js_runtimes"] == {"node": {}}
    assert attempts[0]["extractor_args"] == {
        "youtube": {"player_client": ["web_embedded"]}
    }
    assert attempts[1]["extractor_args"] == {
        "youtube": {"player_client": ["web_embedded"]}
    }
    assert not list(tmp_path.glob("*.part"))
    assert attempt_numbers == [1, 2]
    assert progress[0]["downloaded_bytes"] == 50


def test_forbidden_error_explains_all_retries_were_used():
    error = yt_dlp.utils.DownloadError("HTTP Error 403: Forbidden")
    message = YouTubeService._message(error)
    assert "every available playback format" in message
    assert "PO token" in message


def test_playlist_inspection_returns_selectable_flat_items(monkeypatch, tmp_path: Path):
    options_seen: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict):
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url: str, download: bool):
            assert not download
            return {
                "_type": "playlist",
                "title": "Old films",
                "channel": "Archive",
                "entries": [
                    {"id": "abc", "title": "First", "duration": 12},
                    {"id": "def", "title": "Second", "duration": 34},
                ],
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    result = YouTubeService(tmp_path).inspect_playlist("https://youtube.com/playlist?list=test")

    assert result.title == "Old films"
    assert [item.youtube_id for item in result.items] == ["abc", "def"]
    assert result.items[0].url == "https://www.youtube.com/watch?v=abc"
    assert options_seen[0]["extract_flat"] == "in_playlist"
    assert options_seen[0]["noplaylist"] is False


def test_unexpected_download_abort_removes_partial_file(monkeypatch, tmp_path: Path):
    class FakeYoutubeDL:
        def __init__(self, options: dict):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url: str, download: bool):
            partial = Path(self.options["outtmpl"].replace("%(ext)s", "mp4.part"))
            partial.write_bytes(b"partial")
            raise RuntimeError("cancel wrapper")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    with pytest.raises(RuntimeError, match="cancel wrapper"):
        YouTubeService(tmp_path).download("https://youtu.be/jNQXAC9IVRw")
    assert not list(tmp_path.glob("*.part"))


def test_throttled_stream_is_abandoned_for_next_strategy(monkeypatch, tmp_path: Path):
    attempts: list[dict] = []
    clock = iter([100.0, 100.0, 111.0])

    class FakeYoutubeDL:
        def __init__(self, options: dict):
            self.options = options
            attempts.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url: str, download: bool):
            assert download
            if len(attempts) == 1:
                partial = Path(self.options["outtmpl"].replace("%(ext)s", "mp4.part"))
                partial.write_bytes(b"partial")
                hook = self.options["progress_hooks"][0]
                slow = {
                    "status": "downloading",
                    "downloaded_bytes": 3 * 1024 * 1024,
                    "total_bytes": 80 * 1024 * 1024,
                    "speed": 1024,
                    "eta": 3600,
                }
                hook(slow)
                hook(slow)
            output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
            output.write_bytes(b"valid-video-placeholder")
            return {"title": "Recovered clip", "ext": "mp4"}

        def prepare_filename(self, _info: dict) -> str:
            return self.options["outtmpl"].replace("%(ext)s", "mp4")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr("app.services.youtube.monotonic", lambda: next(clock))

    path, _info = YouTubeService(tmp_path).download("https://youtu.be/jNQXAC9IVRw")

    assert path.exists()
    assert len(attempts) == 2
    assert not list(tmp_path.glob("*.part"))

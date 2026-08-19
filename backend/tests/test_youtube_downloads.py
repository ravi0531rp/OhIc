import threading
import time

from app.schemas.video import YouTubeDownloadStatus
from app.services.youtube_downloads import YouTubeDownloadManager


class BlockingYouTube:
    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def download(self, _url, _progress_hook, attempt_hook, cancel_check):
        self.calls += 1
        attempt_hook(1)
        self.started.set()
        self.release.wait(timeout=2)
        if cancel_check():
            raise InterruptedError("cancelled")
        raise AssertionError("test download should be cancelled")


class UnusedVideos:
    def register_download(self, *_args):
        raise AssertionError("cancelled download must not be registered")


def test_duplicate_active_url_reuses_download_and_can_be_cancelled():
    youtube = BlockingYouTube()
    manager = YouTubeDownloadManager(youtube, UnusedVideos())
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    first = manager.start(url)
    assert youtube.started.wait(timeout=1)
    duplicate = manager.start(url)

    assert duplicate.id == first.id
    assert youtube.calls == 1
    cancelled = manager.cancel(first.id)
    assert cancelled is not None
    assert cancelled.status == YouTubeDownloadStatus.CANCELLED

    youtube.release.set()
    for _ in range(50):
        if manager.get(first.id).status == YouTubeDownloadStatus.CANCELLED:
            break
        time.sleep(0.01)
    assert manager.get(first.id).status == YouTubeDownloadStatus.CANCELLED
    manager.executor.shutdown(wait=True)

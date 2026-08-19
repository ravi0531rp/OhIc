import hashlib
import subprocess
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.inference.realbasicvsr.chunking import recommended_window, temporal_windows
from app.inference.realbasicvsr.engine import checkpoint_state, select_device
from app.inference.realbasicvsr.video_pipeline import run_experimental_pipeline
from app.inference.weights import download_weight
from app.jobs.pipeline import JobRuntime
from app.video.probe import probe_video


def test_temporal_windows_cover_every_frame_once_with_bounded_overlap():
    source = list(range(43))
    windows = list(temporal_windows(source, window_frames=12, overlap_frames=2))

    assert [item for window in windows for item in window.emitted_frames] == source
    assert all(len(window.frames) <= 12 for window in windows)
    assert [window.start_frame for window in windows] == [0, 8, 16, 24, 32]
    assert windows[0].emit_start == 0
    assert all(window.emit_start == 2 for window in windows[1:])


def test_temporal_window_validation_and_resolution_defaults():
    with pytest.raises(ValueError, match="larger than twice"):
        list(temporal_windows(range(10), window_frames=4, overlap_frames=2))
    assert recommended_window(640, 360) == (30, 5)
    assert recommended_window(854, 480) == (16, 3)
    assert recommended_window(1280, 720) == (8, 1)


def test_realbasicvsr_device_selection_is_engine_specific(monkeypatch):
    import torch

    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert select_device("auto") == "mps"
    assert select_device("cuda") == "cuda"
    assert select_device("cpu") == "cpu"

    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert select_device("auto") == "cuda"
    with pytest.raises(RuntimeError, match="Apple Metal"):
        select_device("mps")


def test_checkpoint_prefers_ema_generator_and_rejects_invalid_structure():
    state = checkpoint_state(
        {
            "state_dict": {
                "generator.weight": "ordinary",
                "generator_ema.weight": "ema",
                "discriminator.weight": "ignored",
            }
        }
    )
    assert state == {"weight": "ema"}
    with pytest.raises(RuntimeError, match="generator weights"):
        checkpoint_state({"state_dict": {"discriminator.weight": "unused"}})


def test_weight_download_validates_hash_and_replaces_corrupt_cache(
    tmp_path: Path, monkeypatch
):
    payload = b"verified-realbasicvsr-checkpoint"
    expected_hash = hashlib.sha256(payload).hexdigest()
    destination = tmp_path / "model.pth"
    destination.write_bytes(b"corrupt")

    class Response:
        headers = {"content-length": str(len(payload))}

        def raise_for_status(self):
            return None

        def iter_bytes(self, _size):
            yield payload

    class Stream:
        def __enter__(self):
            return Response()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(httpx, "stream", lambda *_args, **_kwargs: Stream())
    progress: list[float] = []
    result = download_weight(
        "https://example.test/model.pth",
        destination,
        progress.append,
        sha256=expected_hash,
        minimum_size=1,
    )

    assert result.read_bytes() == payload
    assert progress[-1] == 100
    assert not destination.with_suffix(".pth.part").exists()


class SyntheticSequenceEngine:
    identifier = "synthetic-sequence-test"
    display_name = "Synthetic sequence test"
    scale = 4
    device = "cpu"
    model_load_seconds = 0.0

    def enhance_sequence(self, frames, cancel=None):
        if cancel and cancel.is_set():
            raise InterruptedError
        return [np.repeat(np.repeat(frame, 4, axis=0), 4, axis=1) for frame in frames]


def make_synthetic_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:rate=6:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_experimental_video_pipeline_preserves_fps_duration_and_audio(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "restored.mp4"
    make_synthetic_video(source)
    events: list[tuple[str, float, str | None]] = []

    stats = run_experimental_pipeline(
        source,
        output,
        SyntheticSequenceEngine(),
        progress=lambda stage, percent, detail: events.append((stage, percent, detail)),
        window_frames=4,
        overlap_frames=1,
        target_width=128,
        target_height=128,
    )

    source_metadata = probe_video(source)
    output_metadata = probe_video(output)
    assert output_metadata.width == 128
    assert output_metadata.height == 128
    assert output_metadata.fps == pytest.approx(source_metadata.fps, abs=0.01)
    assert output_metadata.duration == pytest.approx(source_metadata.duration, abs=0.2)
    assert output_metadata.audio_codec == "AAC"
    assert stats.frame_count == 6
    assert stats.audio_mode == "copy"
    assert stats.processing_fps > 0
    assert any(stage == "Restoring" for stage, _percent, _detail in events)
    assert [percent for _stage, percent, _detail in events] == sorted(
        percent for _stage, percent, _detail in events
    )


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_experimental_video_pipeline_applies_selected_range(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "selected-range.mp4"
    make_synthetic_video(source)

    stats = run_experimental_pipeline(
        source,
        output,
        SyntheticSequenceEngine(),
        window_frames=4,
        overlap_frames=1,
        target_width=128,
        target_height=128,
        start_at=0.25,
        duration=0.5,
    )

    output_metadata = probe_video(output)
    assert output_metadata.duration == pytest.approx(0.5, abs=0.2)
    assert output_metadata.audio_codec == "AAC"
    assert stats.frame_count == 3


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg is required",
)
def test_experimental_video_pipeline_cancellation_does_not_publish_output(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "cancelled.mp4"
    make_synthetic_video(source)
    runtime = JobRuntime()

    class CancellingEngine(SyntheticSequenceEngine):
        def enhance_sequence(self, frames, cancel=None):
            restored = super().enhance_sequence(frames, cancel)
            runtime.cancel.set()
            return restored

    with pytest.raises(InterruptedError, match="cancelled"):
        run_experimental_pipeline(
            source,
            output,
            CancellingEngine(),
            runtime=runtime,
            window_frames=4,
            overlap_frames=1,
            target_width=128,
            target_height=128,
        )

    assert not output.exists()

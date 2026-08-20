from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from app.inference.realbasicvsr.chunking import TemporalWindow


@dataclass(frozen=True)
class SceneWindow:
    scene_index: int
    window: TemporalWindow[np.ndarray]


def scene_change_score(previous: np.ndarray, current: np.ndarray) -> float:
    """Estimate a hard cut using sparse luma difference and color histogram distance."""
    step_y = max(1, previous.shape[0] // 72)
    step_x = max(1, previous.shape[1] // 96)
    left = previous[::step_y, ::step_x].astype(np.float32)
    right = current[::step_y, ::step_x].astype(np.float32)
    luma_left = left[..., 0] * 0.2126 + left[..., 1] * 0.7152 + left[..., 2] * 0.0722
    luma_right = right[..., 0] * 0.2126 + right[..., 1] * 0.7152 + right[..., 2] * 0.0722
    pixel_difference = float(np.mean(np.abs(luma_left - luma_right)) / 255.0)
    histogram_difference = 0.0
    for channel in range(3):
        before, _ = np.histogram(left[..., channel], bins=16, range=(0, 256), density=True)
        after, _ = np.histogram(right[..., channel], bins=16, range=(0, 256), density=True)
        histogram_difference += float(np.abs(before - after).sum() * 8)
    return min(1.0, max(pixel_difference, histogram_difference / 3))


def scene_aware_windows(
    frames: Iterable[np.ndarray],
    window_frames: int,
    overlap_frames: int,
    threshold: float,
) -> Iterator[SceneWindow]:
    """Yield bounded temporal windows, resetting all context at detected hard cuts."""
    stride = window_frames - 2 * overlap_frames
    if window_frames < 2 or overlap_frames < 0 or stride < 1:
        raise ValueError("Window size must be at least two and larger than twice the overlap.")
    if not 0 < threshold <= 1:
        raise ValueError("Scene threshold must be between zero and one.")
    buffer: list[np.ndarray] = []
    scene_index = 0
    window_index = 0
    global_start = 0
    first_in_scene = True
    previous: np.ndarray | None = None

    def emit(final: bool) -> SceneWindow:
        nonlocal buffer, first_in_scene, global_start, window_index
        count = len(buffer) if final else window_frames
        current = tuple(buffer[:count])
        emit_start = 0 if first_in_scene else min(overlap_frames, len(current))
        emit_end = len(current) if final else max(emit_start, len(current) - overlap_frames)
        result = SceneWindow(
            scene_index,
            TemporalWindow(window_index, global_start, current, emit_start, emit_end),
        )
        window_index += 1
        if final:
            global_start += len(buffer)
            buffer = []
            first_in_scene = True
        else:
            del buffer[:stride]
            global_start += stride
            first_in_scene = False
        return result

    for frame in frames:
        cut = previous is not None and scene_change_score(previous, frame) >= threshold
        if cut and buffer:
            while len(buffer) > window_frames:
                yield emit(final=False)
            yield emit(final=True)
            scene_index += 1
        buffer.append(frame)
        previous = frame
        if len(buffer) >= window_frames + stride:
            yield emit(final=False)
    if buffer:
        while len(buffer) > window_frames:
            yield emit(final=False)
        yield emit(final=True)

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

Frame = TypeVar("Frame")


@dataclass(frozen=True)
class TemporalWindow(Generic[Frame]):
    index: int
    start_frame: int
    frames: tuple[Frame, ...]
    emit_start: int
    emit_end: int

    @property
    def emitted_frames(self) -> tuple[Frame, ...]:
        return self.frames[self.emit_start : self.emit_end]


def recommended_window(width: int, height: int) -> tuple[int, int]:
    """Bound the largest retained feature tensors to a similar rough size."""
    pixels = width * height
    if pixels <= 640 * 360:
        return 30, 5
    if pixels <= 854 * 480:
        return 16, 3
    return 8, 1


def temporal_windows(
    frames: Iterable[Frame], window_frames: int, overlap_frames: int
) -> Iterator[TemporalWindow[Frame]]:
    """Yield bounded overlapping windows while emitting every input exactly once.

    A non-final window with W frames emits its center and keeps context at the
    right edge. The following window starts 2 * overlap frames earlier, so it
    has both left and right temporal context around its emitted center.
    """
    if overlap_frames < 0:
        raise ValueError("Temporal overlap cannot be negative.")
    stride = window_frames - 2 * overlap_frames
    if window_frames < 2 or stride < 1:
        raise ValueError("Window size must be at least two and larger than twice the overlap.")

    iterator = iter(frames)

    def take(limit: int) -> list[Frame]:
        values: list[Frame] = []
        for _ in range(limit):
            try:
                values.append(next(iterator))
            except StopIteration:
                break
        return values

    current = take(window_frames)
    if not current:
        return
    index = 0
    start = 0
    while True:
        retained = current[stride:] if len(current) == window_frames else []
        following = take(stride)
        final = not following
        emit_start = 0 if index == 0 else min(overlap_frames, len(current))
        emit_end = len(current) if final else max(emit_start, len(current) - overlap_frames)
        yield TemporalWindow(index, start, tuple(current), emit_start, emit_end)
        if final:
            return
        current = retained + following
        start += stride
        index += 1

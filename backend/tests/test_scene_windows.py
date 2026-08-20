import numpy as np

from app.inference.realbasicvsr.scenes import scene_aware_windows, scene_change_score


def frame(value: int) -> np.ndarray:
    return np.full((24, 32, 3), value, dtype=np.uint8)


def test_hard_cut_score_separates_scene_change_from_small_exposure_shift():
    assert scene_change_score(frame(0), frame(255)) > 0.9
    assert scene_change_score(frame(100), frame(105)) < 0.1


def test_temporal_windows_never_cross_detected_scene_cut_and_emit_every_frame_once():
    source = [frame(0) for _ in range(12)] + [frame(255) for _ in range(12)]

    windows = list(
        scene_aware_windows(source, window_frames=8, overlap_frames=1, threshold=0.35)
    )
    emitted = [
        int(value[0, 0, 0])
        for scene_window in windows
        for value in scene_window.window.emitted_frames
    ]

    assert {item.scene_index for item in windows} == {0, 1}
    assert all(
        len({int(value[0, 0, 0]) for value in item.window.frames}) == 1
        for item in windows
    )
    assert emitted == [0] * 12 + [255] * 12


def test_single_frame_scene_is_emitted_once():
    source = [frame(0), frame(255), frame(0)]
    windows = list(
        scene_aware_windows(source, window_frames=4, overlap_frames=1, threshold=0.35)
    )

    assert [len(item.window.emitted_frames) for item in windows] == [1, 1, 1]

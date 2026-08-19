from app.schemas.video import VideoMetadata
from app.video.recommendations import recommend_targets


def metadata(width: int, height: int) -> VideoMetadata:
    return VideoMetadata(
        width=width,
        height=height,
        resolution_label=f"{height}p",
        aspect_ratio="16:9",
        fps=30,
        duration=10,
        video_codec="H264",
        file_size=1,
    )


def test_480p_recommends_1080p_and_preserves_ratio():
    targets = recommend_targets(metadata(854, 480))
    assert [target.height for target in targets] == [720, 1080, 1440]
    recommended = next(target for target in targets if target.recommended)
    assert recommended.height == 1080
    assert recommended.width % 2 == 0
    assert abs(recommended.width / recommended.height - 854 / 480) < 0.01


def test_4k_does_not_recommend_absurd_upscale():
    targets = recommend_targets(metadata(3840, 2160))
    assert len(targets) == 1
    assert targets[0].height == 2160

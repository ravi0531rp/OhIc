from app.schemas.video import VideoMetadata
from app.video.diagnosis import diagnose_source


def metadata(**changes) -> VideoMetadata:
    values = {
        "width": 720,
        "height": 480,
        "resolution_label": "480p",
        "aspect_ratio": "3:2",
        "fps": 29.97,
        "duration": 600,
        "video_codec": "H264",
        "bitrate": 450_000,
        "file_size": 30_000_000,
        "field_order": "tt",
    }
    values.update(changes)
    return VideoMetadata(**values)


def test_diagnosis_finds_interlacing_compression_and_low_resolution():
    result = diagnose_source(metadata())

    assert {issue.code for issue in result.issues} >= {
        "interlaced",
        "compression",
        "low_resolution",
    }
    assert result.recipe.deinterlace == "auto"
    assert result.recipe.target_height == 1080
    assert result.recipe.model_id == "realesrgan-x2plus"


def test_diagnosis_avoids_unnecessary_upscale_for_clean_4k():
    result = diagnose_source(
        metadata(
            width=3840,
            height=2160,
            resolution_label="4K",
            fps=30,
            bitrate=30_000_000,
            field_order="progressive",
        )
    )

    assert result.recipe.target_height == 2160
    assert result.recipe.preset == "fast"
    assert "avoid unnecessary" in result.verdict.lower()

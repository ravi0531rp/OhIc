from app.video.probe import parse_ffprobe, parse_rate, resolution_label


def test_parse_rate_handles_fraction_and_invalid_values():
    assert parse_rate("30000/1001") == 30000 / 1001
    assert parse_rate("0/0") == 0
    assert parse_rate(None) == 0


def test_parse_ffprobe_extracts_useful_metadata():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 854,
                "height": 480,
                "avg_frame_rate": "30000/1001",
                "nb_frames": "4020",
                "pix_fmt": "yuv420p",
                "color_transfer": "bt709",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "134.1", "bit_rate": "1200000"},
    }
    result = parse_ffprobe(payload, file_size=20_000_000)
    assert result.width == 854
    assert result.height == 480
    assert result.resolution_label == "480p"
    assert result.aspect_ratio == "16:9"
    assert result.video_codec == "H264"
    assert result.audio_codec == "AAC"
    assert result.frame_count == 4020
    assert result.dynamic_range == "SDR"


def test_resolution_label_does_not_overstate_unusual_sizes():
    assert resolution_label(480) == "480p"
    assert resolution_label(600) == "600p"

from app.schemas.video import ResolutionTarget, VideoMetadata

HEIGHTS = [720, 1080, 1440, 2160]


def even(value: float) -> int:
    rounded = round(value)
    return rounded if rounded % 2 == 0 else rounded + 1


def recommend_targets(metadata: VideoMetadata) -> list[ResolutionTarget]:
    height = metadata.height
    if height < 400:
        candidates = [720, 1080, 1440]
        recommended = 720
    elif height < 600:
        candidates = [720, 1080, 1440]
        recommended = 1080
    elif height < 900:
        candidates = [1080, 1440, 2160]
        recommended = 1080
    elif height < 1300:
        candidates = [1440, 2160]
        recommended = 1440
    elif height < 1900:
        candidates = [2160]
        recommended = 2160
    else:
        candidates = [height]
        recommended = height
    ratio = metadata.width / metadata.height
    targets = []
    for target_height in candidates:
        target_width = even(target_height * ratio)
        label = "4K" if target_height == 2160 else f"{target_height}p"
        is_recommended = target_height == recommended
        targets.append(
            ResolutionTarget(
                width=target_width,
                height=target_height,
                label=label,
                recommended=is_recommended,
                note="Best balance of detail and processing time." if is_recommended else None,
            )
        )
    return targets

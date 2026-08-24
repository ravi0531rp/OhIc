from app.schemas.video import ResolutionTarget, VideoMetadata

HEIGHTS = [720, 1080, 1440, 2160]
DOWNSIZE_HEIGHTS = [360, 480, 720, 1080, 1440]


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
    downsizes = [value for value in DOWNSIZE_HEIGHTS if value < height]
    if len(downsizes) > 3:
        downsizes = downsizes[-3:]
    candidates = list(dict.fromkeys([*downsizes, *candidates]))
    ratio = metadata.width / metadata.height
    targets = []
    for target_height in candidates:
        target_width = even(target_height * ratio)
        label = "4K" if target_height == 2160 else f"{target_height}p"
        is_recommended = target_height == recommended
        is_downsize = target_height < height
        targets.append(
            ResolutionTarget(
                width=target_width,
                height=target_height,
                label=label,
                recommended=is_recommended,
                note=(
                    "Smaller export for sharing and reduced storage."
                    if is_downsize
                    else "Best balance of detail and processing time."
                    if is_recommended
                    else None
                ),
            )
        )
    return targets

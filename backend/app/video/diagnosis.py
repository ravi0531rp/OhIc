from app.schemas.video import (
    EnhancementRecipe,
    SourceDiagnosis,
    SourceIssue,
    VideoMetadata,
)
from app.video.recommendations import recommend_targets


def diagnose_source(metadata: VideoMetadata) -> SourceDiagnosis:
    """Turn stable probe facts into an explainable, conservative enhancement recipe."""
    issues: list[SourceIssue] = []
    interlaced = metadata.field_order not in {"progressive", "unknown", ""}
    if interlaced:
        issues.append(
            SourceIssue(
                code="interlaced",
                severity="high",
                title="Interlaced scan detected",
                detail="Alternating fields can create combing around motion.",
            )
        )
    if metadata.height < 720:
        issues.append(
            SourceIssue(
                code="low_resolution",
                severity="medium",
                title="Limited source resolution",
                detail=f"The source is {metadata.resolution_label}; a moderate upscale is safest.",
            )
        )
    bits_per_pixel_frame = (
        metadata.bitrate / max(1, metadata.width * metadata.height * metadata.fps)
        if metadata.bitrate and metadata.fps
        else None
    )
    if bits_per_pixel_frame is not None and bits_per_pixel_frame < 0.07:
        issues.append(
            SourceIssue(
                code="compression",
                severity="medium",
                title="Heavy compression likely",
                detail=(
                    "The bitrate is low for this resolution and frame rate; "
                    "blocking may be visible."
                ),
            )
        )
    if 0 < metadata.fps < 23:
        issues.append(
            SourceIssue(
                code="low_frame_rate",
                severity="low",
                title="Low frame rate",
                detail="Enhancement will preserve the original motion cadence.",
            )
        )
    if metadata.dynamic_range == "HDR":
        issues.append(
            SourceIssue(
                code="hdr",
                severity="low",
                title="HDR source",
                detail="Color and transfer metadata should be preserved during export.",
            )
        )

    target = next(
        (item for item in recommend_targets(metadata) if item.recommended),
        recommend_targets(metadata)[0],
    )
    long_or_large = metadata.duration > 30 * 60 or metadata.width * metadata.height > 1920 * 1080
    preset = "fast" if long_or_large else "balanced"
    reasons = [item.title for item in issues[:3]] or ["Source already has healthy fundamentals"]
    if interlaced:
        verdict = "Deinterlace before enhancement"
    elif any(item.code == "compression" for item in issues):
        verdict = "Compressed source; use a conservative restoration"
    elif metadata.height < 720:
        verdict = "Good candidate for a moderate upscale"
    else:
        verdict = "Clean source; avoid unnecessary enlargement"
    return SourceDiagnosis(
        verdict=verdict,
        confidence="high" if metadata.bitrate and metadata.field_order else "medium",
        issues=issues,
        recipe=EnhancementRecipe(
            name="Recommended restoration",
            summary=(
                f"{target.label} with {preset.title()} processing"
                + (" after motion-adaptive deinterlacing" if interlaced else "")
            ),
            target_height=target.height,
            preset=preset,
            model_id="realesrgan-x2plus",
            deinterlace="auto" if interlaced else "off",
            reasons=reasons,
        ),
    )

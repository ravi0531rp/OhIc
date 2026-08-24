from app.models.database import Database
from app.schemas.history import HistoryEntry, HistoryEntryKind
from app.schemas.intelligence import AnalysisStatus
from app.schemas.job import JobKind, JobStatus
from app.schemas.video import SourceType

ACTIVE_JOBS = {
    JobStatus.QUEUED,
    JobStatus.PREPARING,
    JobStatus.PROCESSING,
    JobStatus.ENCODING,
}
ACTIVE_ANALYSES = {
    AnalysisStatus.QUEUED,
    AnalysisStatus.TRANSCRIBING,
    AnalysisStatus.TRACKING,
    AnalysisStatus.INDEXING,
}


def _job_title(
    kind: JobKind, playlist_id: str | None, trim_start: float, trim_end: float | None
) -> str:
    if playlist_id:
        return "Playlist enhancement"
    if kind == JobKind.STREAM:
        return "Watch-while-enhancing"
    if kind == JobKind.PREVIEW:
        return "Preview enhancement"
    if trim_start or trim_end:
        return "Range enhancement"
    return "Full video enhancement"


def list_history(database: Database, limit: int = 100) -> list[HistoryEntry]:
    videos = {video.id: video for video in database.list_videos()}
    entries = []
    for job in database.list_jobs(limit):
        video = videos.get(job.video_id)
        source_name = (video.title or video.original_name) if video else "Video"
        entries.append(
            HistoryEntry(
                id=f"enhancement:{job.id}",
                kind=HistoryEntryKind.ENHANCEMENT,
                reference_id=job.id,
                video_id=job.video_id,
                title=_job_title(job.kind, job.playlist_id, job.trim_start, job.trim_end),
                detail=(
                    f"{source_name} · {job.model_id} · "
                    f"{job.target_width} × {job.target_height} · {job.preset.value}"
                ),
                status=job.status.value,
                progress=job.progress.percent,
                stage=job.progress.stage,
                created_at=job.created_at,
                updated_at=job.completed_at or job.started_at or job.created_at,
                can_pause=job.status in ACTIVE_JOBS,
                can_cancel=job.status in ACTIVE_JOBS or job.status == JobStatus.PAUSED,
            )
        )
    for analysis in database.list_analyses(limit):
        entries.append(
            HistoryEntry(
                id=f"pro:{analysis.id}",
                kind=HistoryEntryKind.PRO,
                reference_id=analysis.id,
                video_id=analysis.video_id,
                title=f"Pro analysis · {analysis.video_name or 'Video'}",
                detail=(
                    f"{analysis.transcription_engine.replace('_', ' ')} · "
                    f"{analysis.tracking_model}"
                ),
                status=analysis.status.value,
                progress=analysis.progress,
                stage=analysis.stage,
                created_at=analysis.created_at,
                updated_at=analysis.updated_at,
                can_cancel=analysis.status in ACTIVE_ANALYSES,
            )
        )
    for video in videos.values():
        if video.source_type != SourceType.CAMERA:
            continue
        entries.append(
            HistoryEntry(
                id=f"camera:{video.id}",
                kind=HistoryEntryKind.CAMERA,
                reference_id=video.id,
                video_id=video.id,
                title=video.title or "Phone camera capture",
                detail=(
                    f"{video.metadata.resolution_label} · "
                    f"{video.metadata.duration:.1f}s · Ready to enhance or analyze"
                ),
                status="complete",
                progress=100,
                stage="Capture ready",
                created_at=video.created_at,
                updated_at=video.created_at,
            )
        )
    return sorted(entries, key=lambda entry: entry.created_at, reverse=True)[:limit]

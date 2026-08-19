import asyncio
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api.dependencies import (
    get_database,
    get_job_manager,
    get_playlist_manager,
    get_registry,
    get_storage_service,
    get_video_service,
    get_youtube_download_manager,
    get_youtube_service,
)
from app.core.device import detect_hardware
from app.schemas.job import JobCreate, JobRecord, JobStatus
from app.schemas.playlist import (
    PlaylistCreateRequest,
    PlaylistInspectRequest,
    PlaylistMetadata,
    PlaylistRecord,
    PlaylistStatus,
)
from app.schemas.storage import StorageCleanupRequest, StorageCleanupResult, StorageItem
from app.schemas.system import HealthResponse
from app.schemas.video import (
    VideoRecord,
    YouTubeDownloadRecord,
    YouTubeDownloadRequest,
    YouTubeDownloadStatus,
    YouTubeInspectRequest,
    YouTubeMetadata,
)
from app.services.dependencies import dependency_status
from app.services.videos import UploadTooLargeError
from app.services.youtube import YouTubeError
from app.utils.files import ensure_within
from app.video.probe import VideoProbeError

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ffmpeg = dependency_status("ffmpeg")
    ffprobe = dependency_status("ffprobe")
    return HealthResponse(
        status="ok" if ffmpeg.available and ffprobe.available else "degraded",
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        hardware=detect_hardware(),
    )


@router.get("/models")
def models() -> list[dict]:
    return [model.metadata.__dict__ for model in get_registry().available()]


@router.post("/videos/upload", response_model=VideoRecord)
async def upload_video(file: UploadFile = File(...)) -> VideoRecord:
    try:
        return await get_video_service().save_upload(file)
    except (ValueError, UploadTooLargeError, VideoProbeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/videos/{video_id}", response_model=VideoRecord)
def get_video(video_id: str) -> VideoRecord:
    video = get_database().get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    return video


@router.get("/videos/{video_id}/media")
def video_media(video_id: str) -> FileResponse:
    video = get_database().get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    path = ensure_within(Path(video.path), get_video_service().settings.data_dir)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The local source file has been removed.")
    return FileResponse(path, media_type="video/mp4", filename=video.original_name)


@router.post("/videos/youtube/inspect", response_model=YouTubeMetadata)
async def youtube_inspect(request: YouTubeInspectRequest) -> YouTubeMetadata:
    try:
        return await asyncio.to_thread(get_youtube_service().inspect, request.url)
    except (ValueError, YouTubeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/playlists/inspect", response_model=PlaylistMetadata)
async def playlist_inspect(request: PlaylistInspectRequest) -> PlaylistMetadata:
    try:
        return await asyncio.to_thread(get_youtube_service().inspect_playlist, request.url)
    except (ValueError, YouTubeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/playlists", response_model=PlaylistRecord, status_code=202)
async def create_playlist(request: PlaylistCreateRequest) -> PlaylistRecord:
    try:
        return await asyncio.to_thread(get_playlist_manager().create, request)
    except (ValueError, YouTubeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/playlists", response_model=list[PlaylistRecord])
def list_playlists(limit: int = 50) -> list[PlaylistRecord]:
    return get_playlist_manager().list(min(max(limit, 1), 100))


@router.get("/playlists/{playlist_id}", response_model=PlaylistRecord)
def get_playlist(playlist_id: str) -> PlaylistRecord:
    playlist = get_playlist_manager().get(playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found.")
    return playlist


@router.post("/playlists/{playlist_id}/cancel", response_model=PlaylistRecord)
def cancel_playlist(playlist_id: str) -> PlaylistRecord:
    try:
        return get_playlist_manager().cancel(playlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: str) -> None:
    try:
        get_playlist_manager().delete(playlist_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=409 if detail.startswith("Stop") else 404, detail=detail
        ) from exc


@router.get("/playlists/{playlist_id}/events")
async def playlist_events(playlist_id: str) -> StreamingResponse:
    if not get_playlist_manager().get(playlist_id):
        raise HTTPException(status_code=404, detail="Playlist not found.")

    async def stream():
        previous = ""
        while True:
            playlist = get_playlist_manager().get(playlist_id)
            if not playlist:
                return
            payload = playlist.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            if playlist.status not in {PlaylistStatus.QUEUED, PlaylistStatus.RUNNING}:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/videos/youtube/download", response_model=YouTubeDownloadRecord, status_code=202)
def youtube_download(request: YouTubeDownloadRequest) -> YouTubeDownloadRecord:
    try:
        return get_youtube_download_manager().start(request.url)
    except (ValueError, YouTubeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/videos/youtube/downloads/{download_id}", response_model=YouTubeDownloadRecord)
def youtube_download_status(download_id: str) -> YouTubeDownloadRecord:
    record = get_youtube_download_manager().get(download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download not found.")
    return record


@router.post(
    "/videos/youtube/downloads/{download_id}/cancel", response_model=YouTubeDownloadRecord
)
def cancel_youtube_download(download_id: str) -> YouTubeDownloadRecord:
    record = get_youtube_download_manager().cancel(download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download not found.")
    return record


@router.get("/videos/youtube/downloads/{download_id}/events")
async def youtube_download_events(download_id: str) -> StreamingResponse:
    if not get_youtube_download_manager().get(download_id):
        raise HTTPException(status_code=404, detail="Download not found.")

    async def stream():
        previous = ""
        while True:
            record = get_youtube_download_manager().get(download_id)
            if not record:
                return
            payload = record.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            if record.status in {
                YouTubeDownloadStatus.COMPLETE,
                YouTubeDownloadStatus.FAILED,
                YouTubeDownloadStatus.CANCELLED,
            }:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/storage/items", response_model=list[StorageItem])
def storage_items() -> list[StorageItem]:
    return get_storage_service().items()


@router.post("/storage/cleanup", response_model=StorageCleanupResult)
def cleanup_storage(request: StorageCleanupRequest) -> StorageCleanupResult:
    try:
        return get_storage_service().cleanup(request.ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs", response_model=JobRecord, status_code=202)
def create_job(request: JobCreate) -> JobRecord:
    try:
        return get_job_manager().create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs", response_model=list[JobRecord])
def list_jobs(limit: int = 20) -> list[JobRecord]:
    return get_database().list_jobs(min(max(limit, 1), 100))


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str) -> JobRecord:
    job = get_database().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobRecord)
def cancel_job(job_id: str) -> JobRecord:
    try:
        return get_job_manager().cancel(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if not get_database().get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")

    async def stream():
        previous = ""
        while True:
            job = get_database().get_job(job_id)
            if not job:
                return
            payload = job.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            if job.status in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED}:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/jobs/{job_id}/stream/{chunk_index}")
def job_stream_chunk(job_id: str, chunk_index: int) -> FileResponse:
    job = get_database().get_job(job_id)
    if not job or not job.stream or chunk_index < 0 or chunk_index >= len(job.stream.chunks):
        raise HTTPException(status_code=404, detail="Enhanced part not found.")
    chunk = job.stream.chunks[chunk_index]
    if chunk.status.value != "ready":
        raise HTTPException(status_code=425, detail="This enhanced part is not ready yet.")
    outputs_dir = get_video_service().settings.data_dir / "outputs"
    path = ensure_within(outputs_dir / f"{job_id}-chunk-{chunk_index:04d}.mp4", outputs_dir)
    if not path.exists():
        raise HTTPException(status_code=410, detail="This enhanced part has been removed.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def _job_file(job_id: str, original: bool = False) -> FileResponse:
    job = get_database().get_job(job_id)
    if not job or job.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=404, detail="Completed result not found.")
    value = (
        get_video_service().settings.data_dir / "outputs" / f"{job_id}-original.mp4"
        if original
        else Path(job.output_path or "")
    )
    path = ensure_within(value, get_video_service().settings.data_dir / "outputs")
    if not path.exists():
        raise HTTPException(status_code=410, detail="The local result file has been removed.")
    filename = f"OhIc-{job_id[:8]}{'-original' if original else ''}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/jobs/{job_id}/result")
def job_result(job_id: str) -> FileResponse:
    return _job_file(job_id)


@router.get("/jobs/{job_id}/original")
def job_original(job_id: str) -> FileResponse:
    return _job_file(job_id, original=True)

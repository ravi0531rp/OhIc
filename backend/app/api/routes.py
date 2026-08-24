import asyncio
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api.dependencies import (
    get_batch_manager,
    get_camera_manager,
    get_comparison_manager,
    get_database,
    get_intelligence_manager,
    get_job_manager,
    get_playlist_manager,
    get_pro_setup_service,
    get_registry,
    get_storage_service,
    get_video_service,
    get_youtube_download_manager,
    get_youtube_service,
)
from app.core.device import detect_hardware
from app.core.resources import resource_snapshot
from app.schemas.batch import BatchCreateRequest, BatchRecord, PresetCreate, PresetRecord
from app.schemas.comparison import ComparisonCreate, ComparisonRecord
from app.schemas.intelligence import (
    AnalysisCreateRequest,
    AnalysisStatus,
    ChatRequest,
    ChatResponse,
    ChatSession,
    IdentityCreateRequest,
    IdentityRecord,
    ProStatus,
    SubjectIdentityRequest,
    VideoAnalysis,
)
from app.schemas.job import JobCreate, JobRecord, JobStatus
from app.schemas.playlist import (
    PlaylistCreateRequest,
    PlaylistInspectRequest,
    PlaylistMetadata,
    PlaylistRecord,
    PlaylistStatus,
)
from app.schemas.storage import StorageCleanupRequest, StorageCleanupResult, StorageItem
from app.schemas.system import HealthResponse, ResourceSnapshot
from app.schemas.video import (
    CameraSession,
    VideoRecord,
    YouTubeDownloadRecord,
    YouTubeDownloadRequest,
    YouTubeDownloadStatus,
    YouTubeInspectRequest,
    YouTubeMetadata,
    YouTubeReliabilityReport,
)
from app.services.dependencies import dependency_status
from app.services.videos import UploadTooLargeError
from app.services.youtube import YouTubeError
from app.utils.files import ensure_within
from app.video.probe import VideoProbeError

router = APIRouter(prefix="/api")


@router.post("/camera/sessions", response_model=CameraSession, status_code=201)
def create_camera_session() -> CameraSession:
    return get_camera_manager().create()


@router.get("/camera/sessions/{session_id}", response_model=CameraSession)
def get_camera_session(session_id: str) -> CameraSession:
    session = get_camera_manager().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Camera session not found.")
    return session


@router.get("/camera/sessions/{session_id}/frame")
def camera_session_frame(session_id: str) -> Response:
    frame = get_camera_manager().latest_frame(session_id)
    if not frame:
        return Response(status_code=204)
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/camera/sessions/{session_id}/cancel", response_model=CameraSession)
def cancel_camera_session(session_id: str) -> CameraSession:
    try:
        return get_camera_manager().cancel(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pro/status", response_model=ProStatus)
def pro_status() -> ProStatus:
    return get_pro_setup_service().status()


@router.post("/pro/install", response_model=ProStatus, status_code=202)
def install_pro() -> ProStatus:
    return get_pro_setup_service().start_install()


@router.post("/pro/unload", status_code=204)
def unload_pro_model() -> None:
    get_intelligence_manager().unload_chat_model()


@router.post("/pro/analyses", response_model=VideoAnalysis, status_code=202)
def create_analysis(request: AnalysisCreateRequest) -> VideoAnalysis:
    try:
        return get_intelligence_manager().create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pro/analyses", response_model=list[VideoAnalysis])
def list_analyses(limit: int = 50) -> list[VideoAnalysis]:
    return get_intelligence_manager().list(min(max(limit, 1), 100))


@router.get("/pro/videos/{video_id}/analysis", response_model=VideoAnalysis | None)
def video_analysis(video_id: str) -> VideoAnalysis | None:
    if not get_database().get_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found.")
    return get_intelligence_manager().for_video(video_id)


@router.get("/pro/analyses/{analysis_id}", response_model=VideoAnalysis)
def get_analysis(analysis_id: str) -> VideoAnalysis:
    analysis = get_intelligence_manager().get(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return analysis


@router.post("/pro/analyses/{analysis_id}/cancel", response_model=VideoAnalysis)
def cancel_analysis(analysis_id: str) -> VideoAnalysis:
    try:
        return get_intelligence_manager().cancel(analysis_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pro/analyses/{analysis_id}/events")
async def analysis_events(analysis_id: str) -> StreamingResponse:
    if not get_intelligence_manager().get(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")

    async def stream():
        previous = ""
        while True:
            analysis = get_intelligence_manager().get(analysis_id)
            if not analysis:
                return
            payload = analysis.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            if analysis.status in {
                AnalysisStatus.READY,
                AnalysisStatus.FAILED,
                AnalysisStatus.CANCELLED,
            }:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.6)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/pro/analyses/{analysis_id}/subtitles.vtt")
def analysis_subtitles(analysis_id: str) -> FileResponse:
    if not get_intelligence_manager().get(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")
    path = get_intelligence_manager().subtitle_path(analysis_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Subtitles are not ready.")
    return FileResponse(path, media_type="text/vtt", filename="OhIc-subtitles.vtt")


@router.get("/pro/analyses/{analysis_id}/frames/{index}")
def analysis_frame(analysis_id: str, index: int) -> FileResponse:
    analysis = get_intelligence_manager().get(analysis_id)
    if not analysis or index < 0 or index >= len(analysis.keyframes):
        raise HTTPException(status_code=404, detail="Keyframe not found.")
    path = get_intelligence_manager().frame_path_by_index(analysis_id, index)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Keyframe was removed.")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/pro/analyses/{analysis_id}/subjects/{subject_id}/thumbnail")
def subject_thumbnail(analysis_id: str, subject_id: str) -> FileResponse:
    analysis = get_intelligence_manager().get(analysis_id)
    if not analysis or not any(subject.id == subject_id for subject in analysis.subjects):
        raise HTTPException(status_code=404, detail="Subject not found.")
    path = get_intelligence_manager().subject_thumbnail_path(analysis_id, subject_id)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Subject thumbnail was removed.")
    return FileResponse(path, media_type="image/jpeg")


@router.post(
    "/pro/analyses/{analysis_id}/subjects/{subject_id}/identity",
    response_model=VideoAnalysis,
)
def tag_subject(
    analysis_id: str, subject_id: str, request: SubjectIdentityRequest
) -> VideoAnalysis:
    try:
        return get_intelligence_manager().tag_subject(analysis_id, subject_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pro/identities", response_model=list[IdentityRecord])
def list_identities() -> list[IdentityRecord]:
    return get_database().list_identities()


@router.post("/pro/identities", response_model=IdentityRecord, status_code=201)
def create_identity(request: IdentityCreateRequest) -> IdentityRecord:
    return get_intelligence_manager().create_identity(request)


@router.post("/pro/analyses/{analysis_id}/chat", response_model=ChatResponse)
async def analysis_chat(analysis_id: str, request: ChatRequest) -> ChatResponse:
    try:
        return await asyncio.to_thread(get_intelligence_manager().chat, analysis_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/pro/analyses/{analysis_id}/chat", response_model=ChatSession | None)
def analysis_chat_history(analysis_id: str) -> ChatSession | None:
    if not get_intelligence_manager().get(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return get_database().latest_chat_for_analysis(analysis_id)


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


@router.get("/system/resources", response_model=ResourceSnapshot)
def system_resources() -> ResourceSnapshot:
    return resource_snapshot()


@router.get("/models")
def models() -> list[dict]:
    return [model.metadata.__dict__ for model in get_registry().available()]


@router.post("/videos/upload", response_model=VideoRecord)
async def upload_video(file: UploadFile = File(...)) -> VideoRecord:
    try:
        return await get_video_service().save_upload(file)
    except (ValueError, UploadTooLargeError, VideoProbeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/videos/upload/batch", response_model=list[VideoRecord])
async def upload_video_batch(files: list[UploadFile] = File(...)) -> list[VideoRecord]:
    if not files or len(files) > 100:
        raise HTTPException(status_code=400, detail="Choose between 1 and 100 video files.")
    saved: list[VideoRecord] = []
    try:
        for file in files:
            saved.append(await get_video_service().save_upload(file))
        return saved
    except (ValueError, UploadTooLargeError, VideoProbeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/presets", response_model=list[PresetRecord])
def list_presets() -> list[PresetRecord]:
    return get_database().list_presets()


@router.post("/presets", response_model=PresetRecord, status_code=201)
def create_preset(request: PresetCreate) -> PresetRecord:
    return get_batch_manager().create_preset(request)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: str) -> None:
    try:
        get_batch_manager().delete_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/batches", response_model=BatchRecord, status_code=202)
def create_batch(request: BatchCreateRequest) -> BatchRecord:
    try:
        return get_batch_manager().create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/batches", response_model=list[BatchRecord])
def list_batches(limit: int = 50) -> list[BatchRecord]:
    return get_batch_manager().list(min(max(limit, 1), 100))


@router.post("/batches/{batch_id}/pause", response_model=BatchRecord)
def pause_batch(batch_id: str) -> BatchRecord:
    try:
        return get_batch_manager().pause(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/resume", response_model=BatchRecord)
def resume_batch(batch_id: str) -> BatchRecord:
    try:
        return get_batch_manager().resume(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/cancel", response_model=BatchRecord)
def cancel_batch(batch_id: str) -> BatchRecord:
    try:
        return get_batch_manager().cancel(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/comparisons", response_model=ComparisonRecord, status_code=202)
def create_comparison(request: ComparisonCreate) -> ComparisonRecord:
    try:
        return get_comparison_manager().create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/comparisons", response_model=list[ComparisonRecord])
def list_comparisons(limit: int = 50) -> list[ComparisonRecord]:
    return get_comparison_manager().list(min(max(limit, 1), 100))


@router.get("/comparisons/{comparison_id}", response_model=ComparisonRecord)
def get_comparison(comparison_id: str) -> ComparisonRecord:
    record = get_comparison_manager().get(comparison_id)
    if not record:
        raise HTTPException(status_code=404, detail="Preview comparison not found.")
    return record


@router.post("/comparisons/{comparison_id}/cancel", response_model=ComparisonRecord)
def cancel_comparison(comparison_id: str) -> ComparisonRecord:
    try:
        return get_comparison_manager().cancel(comparison_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/videos/{video_id}", response_model=VideoRecord)
def get_video(video_id: str) -> VideoRecord:
    video = get_database().get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    return get_video_service().ensure_diagnosis(video)


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


@router.get("/videos/youtube/reliability", response_model=YouTubeReliabilityReport)
def youtube_reliability() -> YouTubeReliabilityReport:
    return get_youtube_service().reliability_report()


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


@router.post("/videos/youtube/downloads/{download_id}/cancel", response_model=YouTubeDownloadRecord)
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


@router.post("/jobs/{job_id}/pause", response_model=JobRecord)
def pause_job(job_id: str) -> JobRecord:
    try:
        return get_job_manager().pause(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/resume", response_model=JobRecord)
def resume_job(job_id: str) -> JobRecord:
    try:
        return get_job_manager().resume(job_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=404 if detail == "Job not found." else 409, detail=detail
        ) from exc


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
            if job.status in {
                JobStatus.COMPLETE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.PAUSED,
            }:
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
    suffix = ".mp4" if original else path.suffix.lower()
    filename = f"OhIc-{job_id[:8]}{'-original' if original else ''}{suffix}"
    media_type = "video/x-matroska" if suffix == ".mkv" else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/jobs/{job_id}/result")
def job_result(job_id: str) -> FileResponse:
    return _job_file(job_id)


@router.get("/jobs/{job_id}/original")
def job_original(job_id: str) -> FileResponse:
    return _job_file(job_id, original=True)

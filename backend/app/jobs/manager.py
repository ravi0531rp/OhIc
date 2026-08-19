import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import sqrt

import structlog

from app.core.config import Settings
from app.core.device import detect_hardware
from app.inference.registry import ModelRegistry
from app.jobs.pipeline import JobRuntime, run_pipeline, run_streaming_pipeline
from app.models.database import Database
from app.schemas.job import (
    JobCreate,
    JobKind,
    JobProgress,
    JobRecord,
    JobStatus,
    QualityPreset,
    StreamChunk,
    StreamState,
)
from app.schemas.video import VideoRecord

logger = structlog.get_logger()


def build_stream_state(video: VideoRecord, request: JobCreate, trim_end: float) -> StreamState:
    """Plan short independently playable parts without creating hundreds of tiny files."""
    source_pixels = max(1, video.metadata.width * video.metadata.height)
    target_pixels = request.target_width * request.target_height
    upscale_work = max(1.0, target_pixels / source_pixels)
    preset_work = {
        QualityPreset.FAST: 0.75,
        QualityPreset.BALANCED: 1.0,
        QualityPreset.MAXIMUM: 1.5,
    }[request.preset]
    selected_duration = max(0.1, trim_end - request.trim_start)
    megabytes_per_minute = (
        video.metadata.file_size / (1024 * 1024) / max(video.metadata.duration / 60, 0.1)
    )
    decode_work = min(1.35, max(0.85, sqrt(max(1.0, megabytes_per_minute) / 30)))
    duration_work = 1.15 if selected_duration > 2 * 60 * 60 else 1.0
    raw_seconds = 120 / sqrt(upscale_work * preset_work * decode_work * duration_work)
    chunk_duration = float(min(120, max(30, round(raw_seconds / 15) * 15)))
    startup_duration = min(30.0, max(10.0, chunk_duration / 2))

    chunks: list[StreamChunk] = []
    cursor = request.trim_start
    while cursor < trim_end - 0.001:
        span = startup_duration if not chunks else chunk_duration
        end = min(trim_end, cursor + span)
        chunks.append(StreamChunk(index=len(chunks), start=cursor, end=end))
        cursor = end
    return StreamState(
        chunk_duration=chunk_duration,
        total_chunks=len(chunks),
        chunks=chunks,
    )


class JobManager:
    def __init__(self, settings: Settings, database: Database, registry: ModelRegistry):
        self.settings = settings
        self.database = database
        self.registry = registry
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-enhance")
        self._runtimes: dict[str, JobRuntime] = {}
        self._lock = threading.RLock()

    def create(self, request: JobCreate) -> JobRecord:
        video = self.database.get_video(request.video_id)
        if not video:
            raise ValueError("The source video no longer exists.")
        if request.target_width % 2 or request.target_height % 2:
            raise ValueError("Output dimensions must be even for browser-compatible encoding.")
        if (
            request.target_width / request.target_height
            != video.metadata.width / video.metadata.height
        ):
            expected = request.target_height * video.metadata.width / video.metadata.height
            if abs(expected - request.target_width) > 4:
                raise ValueError("Output dimensions must preserve the source aspect ratio.")
        if request.trim_start >= video.metadata.duration:
            raise ValueError("The range start must be before the end of the video.")
        trim_end = min(request.trim_end or video.metadata.duration, video.metadata.duration)
        if trim_end <= request.trim_start + 0.1:
            raise ValueError("Choose an enhancement range of at least 0.1 seconds.")
        self.registry.get(request.model_id)
        job = JobRecord(
            id=str(uuid.uuid4()),
            video_id=request.video_id,
            kind=request.kind,
            status=JobStatus.QUEUED,
            model_id=request.model_id,
            preset=request.preset,
            target_width=request.target_width,
            target_height=request.target_height,
            preview_timestamp=request.preview_timestamp,
            trim_start=request.trim_start,
            trim_end=(trim_end if request.trim_end is not None else None),
            playlist_id=request.playlist_id,
            stream=(
                build_stream_state(video, request, trim_end)
                if request.kind == JobKind.STREAM
                else None
            ),
            progress=JobProgress(),
            created_at=datetime.now(UTC),
        )
        runtime = JobRuntime()
        with self._lock:
            self._runtimes[job.id] = runtime
        self.database.save_job(job)
        self.executor.submit(self._execute, job.id)
        logger.info("job_created", job_id=job.id, kind=job.kind, model=job.model_id)
        return job

    def _execute(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if not job:
            return
        video = self.database.get_video(job.video_id)
        runtime = self._runtimes[job_id]
        if job.status == JobStatus.CANCELLED or runtime.cancel.is_set():
            self._cancelled(job_id)
            with self._lock:
                self._runtimes.pop(job_id, None)
            return
        if not video:
            self._fail(job, "The source video no longer exists.")
            return
        job.status = JobStatus.PREPARING
        job.started_at = datetime.now(UTC)
        self.database.save_job(job)

        def update(value: JobProgress) -> None:
            fresh = self.database.get_job(job_id)
            if not fresh or fresh.status in {JobStatus.CANCELLED, JobStatus.FAILED}:
                return
            fresh.progress = value
            if value.stage == "Enhancing" or value.stage.startswith("Enhancing part"):
                fresh.status = JobStatus.PROCESSING
            elif value.stage in {
                "Adding audio",
                "Finalizing",
                "Joining enhanced parts",
            } or value.stage.startswith("Packaging part"):
                fresh.status = JobStatus.ENCODING
            self.database.save_job(fresh)

        def update_stream(value: StreamState) -> None:
            fresh = self.database.get_job(job_id)
            if not fresh or fresh.status in {JobStatus.CANCELLED, JobStatus.FAILED}:
                return
            fresh.stream = value
            self.database.save_job(fresh)

        try:
            hardware = detect_hardware()
            pipeline = run_streaming_pipeline if job.kind == JobKind.STREAM else run_pipeline
            pipeline_args = (
                job,
                video,
                self.registry.get(job.model_id),
                self.settings.resolved_model_dir,
                self.settings.data_dir / "outputs",
                self.settings.data_dir / "temp",
                hardware.device,
                runtime,
                update,
            )
            output, original, seconds = (
                pipeline(*pipeline_args, stream_progress=update_stream)
                if job.kind == JobKind.STREAM
                else pipeline(*pipeline_args)
            )
            if runtime.cancel.is_set():
                raise InterruptedError("Enhancement cancelled")
            fresh = self.database.get_job(job_id) or job
            fresh.status = JobStatus.COMPLETE
            fresh.completed_at = datetime.now(UTC)
            fresh.output_path = str(output)
            fresh.output_url = f"/api/jobs/{job_id}/result"
            fresh.original_preview_url = f"/api/jobs/{job_id}/original" if original else None
            fresh.processing_seconds = seconds
            fresh.progress = JobProgress(
                stage="Complete",
                percent=100,
                frames_done=fresh.progress.frames_done,
                frames_total=fresh.progress.frames_total,
                processing_fps=fresh.progress.processing_fps,
                elapsed_seconds=seconds,
            )
            self.database.save_job(fresh)
            logger.info("job_completed", job_id=job_id, seconds=seconds)
        except InterruptedError:
            self._cancelled(job_id)
        except Exception as exc:
            logger.exception("job_failed", job_id=job_id)
            message = str(exc)
            if "memory" in message.lower() or "allocate" in message.lower():
                message = (
                    "Not enough memory for this resolution. Try Balanced mode or a lower target."
                )
            self._fail(self.database.get_job(job_id) or job, message)
        finally:
            with self._lock:
                self._runtimes.pop(job_id, None)

    def _fail(self, job: JobRecord, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error = message[:500]
        job.completed_at = datetime.now(UTC)
        self.database.save_job(job)

    def _cancelled(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if not job:
            return
        job.status = JobStatus.CANCELLED
        job.error = None
        job.completed_at = datetime.now(UTC)
        job.progress.stage = "Cancelled"
        self.database.save_job(job)

    def cancel(self, job_id: str) -> JobRecord:
        job = self.database.get_job(job_id)
        if not job:
            raise ValueError("Job not found.")
        if job.status in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED}:
            return job
        with self._lock:
            runtime = self._runtimes.get(job_id)
            if runtime:
                runtime.stop()
        self._cancelled(job_id)
        return self.database.get_job(job_id) or job

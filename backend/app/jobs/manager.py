import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.core.config import Settings
from app.core.device import detect_hardware
from app.core.resources import plan_resources
from app.inference.realbasicvsr import RealBasicVSREngine
from app.inference.registry import ModelRegistry
from app.jobs.pipeline import (
    JobRuntime,
    run_checkpointed_pipeline,
    run_pipeline,
    run_realbasicvsr_pipeline,
    run_streaming_pipeline,
)
from app.models.database import Database
from app.schemas.job import (
    CheckpointSegment,
    JobCheckpoint,
    JobCreate,
    JobKind,
    JobProgress,
    JobRecord,
    JobStatus,
    StreamChunk,
    StreamState,
)
from app.schemas.video import VideoRecord

logger = structlog.get_logger()

ACTIVE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.PREPARING,
    JobStatus.PROCESSING,
    JobStatus.ENCODING,
}


def _source_fingerprint(video: VideoRecord) -> str:
    source = Path(video.path)
    try:
        stat = source.stat()
        identity = f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        identity = f"{source}:{video.metadata.file_size}:{video.metadata.duration}"
    return hashlib.sha256(identity.encode()).hexdigest()


def build_checkpoint(
    video: VideoRecord,
    request: JobCreate,
    trim_end: float,
    job_id: str,
    segment_seconds: float,
) -> JobCheckpoint:
    signature_payload = {
        "model_id": request.model_id,
        "preset": request.preset.value,
        "target": [request.target_width, request.target_height],
        "range": [request.trim_start, trim_end],
        "output": [request.output_container.value, request.track_policy.value],
        "metadata": [request.preserve_metadata, request.preserve_chapters],
        "scan_treatment": request.scan_treatment.value,
        "resources": [request.resource_policy.value, request.memory_limit_mb],
        "scenes": [request.scene_aware, request.scene_threshold],
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True).encode()
    ).hexdigest()
    segments: list[CheckpointSegment] = []
    cursor = request.trim_start
    while cursor < trim_end - 0.001:
        end = min(trim_end, cursor + segment_seconds)
        index = len(segments)
        segments.append(
            CheckpointSegment(
                index=index,
                start=cursor,
                end=end,
                output_name=(
                    f"{job_id}-checkpoint-{index:04d}.{request.output_container.value}"
                ),
            )
        )
        cursor = end
    return JobCheckpoint(
        source_fingerprint=_source_fingerprint(video),
        settings_signature=signature,
        segment_seconds=segment_seconds,
        segments=segments,
    )


def build_stream_state(video: VideoRecord, request: JobCreate, trim_end: float) -> StreamState:
    """Front-load the buffer, then publish short independently playable parts."""
    selected_duration = max(0.1, trim_end - request.trim_start)
    if selected_duration >= 120:
        initial_chunk_duration = 120.0
    elif selected_duration >= 60:
        initial_chunk_duration = 60.0
    else:
        initial_chunk_duration = 5.0
    followup_chunk_duration = 5.0

    chunks: list[StreamChunk] = []
    cursor = request.trim_start
    while cursor < trim_end - 0.001:
        span = initial_chunk_duration if not chunks else followup_chunk_duration
        end = min(trim_end, cursor + span)
        chunks.append(StreamChunk(index=len(chunks), start=cursor, end=end))
        cursor = end
    return StreamState(
        chunk_duration=followup_chunk_duration,
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
        backend = self.registry.get(request.model_id)
        if request.kind == JobKind.STREAM and not backend.metadata.supports_stream:
            raise ValueError(
                f"{backend.metadata.display_name} does not support watch-while-enhancing yet. "
                "Use Preview or Enhance full video."
            )
        if request.kind == JobKind.STREAM and request.output_container.value != "mp4":
            raise ValueError("Watch-while-enhancing requires browser-compatible MP4 output.")
        if request.scan_treatment.value == "ivtc" and not 29 <= video.metadata.fps <= 31:
            raise ValueError("Inverse telecine is only available for 29.97 or 30 FPS sources.")
        if (
            backend.metadata.max_input_pixels
            and video.metadata.width * video.metadata.height
            > backend.metadata.max_input_pixels
        ):
            raise ValueError(
                f"{backend.metadata.display_name} currently supports inputs up to 720p. "
                "Use Real-ESRGAN for this source."
            )
        job_id = str(uuid.uuid4())
        job = JobRecord(
            id=job_id,
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
            output_container=request.output_container,
            track_policy=request.track_policy,
            preserve_metadata=request.preserve_metadata,
            preserve_chapters=request.preserve_chapters,
            scan_treatment=request.scan_treatment,
            resource_policy=request.resource_policy,
            memory_limit_mb=request.memory_limit_mb,
            scene_aware=request.scene_aware,
            scene_threshold=request.scene_threshold,
            stream=(
                build_stream_state(video, request, trim_end)
                if request.kind == JobKind.STREAM
                else None
            ),
            checkpoint=(
                build_checkpoint(
                    video,
                    request,
                    trim_end,
                    job_id,
                    self.settings.checkpoint_seconds,
                )
                if request.kind == JobKind.FULL
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
        runtime = self._runtimes.get(job_id)
        if not runtime:
            return
        if job.status == JobStatus.CANCELLED or runtime.cancel.is_set():
            self._paused(job_id) if runtime.pause.is_set() else self._cancelled(job_id)
            with self._lock:
                self._runtimes.pop(job_id, None)
            return
        if not video:
            self._fail(job, "The source video no longer exists.")
            return
        job.status = JobStatus.PREPARING
        job.started_at = datetime.now(UTC)
        job.resource_allocation = plan_resources(
            job.resource_policy.value,
            job.target_width * job.target_height,
            job.memory_limit_mb,
        )
        self.database.save_job(job)

        def update(value: JobProgress) -> None:
            fresh = self.database.get_job(job_id)
            if not fresh or fresh.status in {
                JobStatus.CANCELLED,
                JobStatus.FAILED,
                JobStatus.PAUSED,
            }:
                return
            fresh.progress = value
            if value.stage in {"Enhancing", "Restoring video"} or value.stage.startswith(
                "Enhancing part"
            ):
                fresh.status = JobStatus.PROCESSING
            elif value.stage in {
                "Adding audio",
                "Encoding",
                "Finalizing",
                "Joining enhanced parts",
                "Muxing audio",
            } or value.stage.startswith("Packaging part"):
                fresh.status = JobStatus.ENCODING
            self.database.save_job(fresh)

        def update_stream(value: StreamState) -> None:
            fresh = self.database.get_job(job_id)
            if not fresh or fresh.status in {
                JobStatus.CANCELLED,
                JobStatus.FAILED,
                JobStatus.PAUSED,
            }:
                return
            fresh.stream = value
            self.database.save_job(fresh)

        def update_checkpoint(value: JobCheckpoint) -> None:
            fresh = self.database.get_job(job_id)
            if not fresh or fresh.status in {
                JobStatus.CANCELLED,
                JobStatus.FAILED,
                JobStatus.PAUSED,
            }:
                return
            fresh.checkpoint = value
            self.database.save_job(fresh)

        try:
            backend = self.registry.get(job.model_id)
            common_args = (
                job,
                video,
                backend,
                self.settings.resolved_model_dir,
                self.settings.data_dir / "outputs",
                self.settings.data_dir / "temp",
            )
            hardware = detect_hardware()
            if job.checkpoint:
                output, original, seconds = run_checkpointed_pipeline(
                    *common_args,
                    hardware.device,
                    runtime,
                    update,
                    update_checkpoint,
                )
            elif isinstance(backend, RealBasicVSREngine):
                output, original, seconds = run_realbasicvsr_pipeline(
                    *common_args, runtime, update
                )
            else:
                pipeline_args = (*common_args, hardware.device, runtime, update)
                output, original, seconds = (
                    run_streaming_pipeline(*pipeline_args, stream_progress=update_stream)
                    if job.kind == JobKind.STREAM
                    else run_pipeline(*pipeline_args)
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
            logger.info(
                "job_completed",
                job_id=job_id,
                engine=job.model_id,
                seconds=seconds,
                input_resolution=f"{video.metadata.width}x{video.metadata.height}",
                output_resolution=f"{job.target_width}x{job.target_height}",
                fps=video.metadata.fps,
                frame_count=fresh.progress.frames_done,
                processing_fps=fresh.progress.processing_fps,
            )
        except InterruptedError:
            self._paused(job_id) if runtime.pause.is_set() else self._cancelled(job_id)
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

    def _paused(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if not job:
            return
        job.status = JobStatus.PAUSED
        job.error = None
        job.completed_at = None
        job.progress.stage = "Paused safely"
        job.progress.detail = "Completed checkpoints are saved locally."
        self.database.save_job(job)

    def pause(self, job_id: str) -> JobRecord:
        job = self.database.get_job(job_id)
        if not job:
            raise ValueError("Job not found.")
        if job.status not in ACTIVE_JOB_STATUSES:
            return job
        with self._lock:
            runtime = self._runtimes.get(job_id)
            if runtime:
                runtime.request_pause()
        job.progress.stage = "Pausing safely"
        job.progress.detail = "Finishing checkpoint bookkeeping…"
        self.database.save_job(job)
        return job

    def resume(self, job_id: str) -> JobRecord:
        job = self.database.get_job(job_id)
        if not job:
            raise ValueError("Job not found.")
        if job.status not in {JobStatus.PAUSED, JobStatus.FAILED}:
            raise ValueError("Only paused or recoverable failed jobs can be resumed.")
        video = self.database.get_video(job.video_id)
        if not video:
            raise ValueError("The source video no longer exists.")
        if job.checkpoint and job.checkpoint.source_fingerprint != _source_fingerprint(video):
            raise ValueError(
                "The source file changed, so this checkpoint cannot be resumed safely."
            )
        runtime = JobRuntime()
        with self._lock:
            if job_id in self._runtimes:
                raise ValueError("The job is still pausing. Try Resume again in a moment.")
            self._runtimes[job_id] = runtime
        job.status = JobStatus.QUEUED
        job.error = None
        job.completed_at = None
        job.recovered_after_restart = False
        job.progress.stage = "Queued to resume"
        self.database.save_job(job)
        self.executor.submit(self._execute, job_id)
        return job

    def recover_interrupted(self) -> int:
        recovered = 0
        for job in self.database.list_jobs(10000):
            if job.status not in ACTIVE_JOB_STATUSES:
                continue
            job.status = JobStatus.PAUSED
            job.recovered_after_restart = True
            job.completed_at = None
            job.progress.stage = "Recovered after restart"
            job.progress.detail = "Resume to continue from the last verified checkpoint."
            self.database.save_job(job)
            recovered += 1
        return recovered

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

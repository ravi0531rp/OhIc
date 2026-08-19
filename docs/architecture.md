# Architecture

OhIc is split into a browser workspace and a localhost-only Python engine.

## Boundaries

- **Frontend:** React 19, TypeScript and vinext/Vite. It never reads complete video files into
  JavaScript memory. It uses native video elements, REST APIs and an SSE job stream.
- **API:** FastAPI with Pydantic request/response models, streaming multipart ingestion, safe
  media routes and polished client-safe errors.
- **Persistence:** SQLite stores serialized typed job/video records and paths. Video bytes stay
  in filesystem-managed UUID locations.
- **Jobs:** a single-worker executor prevents concurrent jobs from exhausting local memory.
  Each runtime owns a cancellation event and all child processes.
- **Video:** FFprobe inspects streams. FFmpeg decodes RGB frames and encodes output progressively;
  audio is attached after the video stream completes.
- **Inference:** a central registry exposes engine metadata and capabilities. Frame engines use
  `VideoEnhancementModel`; temporal engines own bounded sequence inference. Jobs dispatch by the
  persisted engine ID.

## Processing sequence

1. Validate and stream a source into an application-managed location.
2. Parse ffprobe JSON into `VideoMetadata` and calculate aspect-safe targets.
3. Create a typed SQLite job and start its isolated runtime.
4. Download and structurally validate official model weights on first use.
5. Pipe frames from FFmpeg to the selected model without retaining the complete video.
6. Process either one frame at a time in tiles or bounded overlapping temporal windows.
7. Pipe RGB output into a progressive H.264 encoder.
8. Mux the source audio, use `-shortest`, add browser fast-start metadata, and atomically expose
   the complete result through its stored job record.
9. Remove the job temp directory after success, error or cancellation.

## Extension points

Frame-oriented restoration backends implement `VideoEnhancementModel` and register under a stable
ID. RealBasicVSR demonstrates the temporal boundary: its engine owns sequence enhancement while
its video pipeline owns context windows, audio, timestamps, cancellation, and device fallback.
Capability metadata prevents unsupported stream or oversized-input jobs. Future denoise,
interpolation and color stages should be separate typed pipeline stages rather than flags embedded
in an engine adapter.

## Current durability model

Source and completed-output metadata survive process restarts. A queued or in-process job is not
resumed after a hard process stop in v0.1; adding recovery requires a startup reconciliation pass
and resumable frame checkpoints.

# Development

## Local services

`./scripts/dev.sh` starts the FastAPI engine on `127.0.0.1:8000` and the vinext/Vite workspace on
`localhost:3000`. The script owns both processes and terminates the engine when the frontend exits.

Python code lives under `backend/app/`. HTTP routes call services; services call video, inference
and job modules. Do not put FFmpeg argument construction or model logic inside API routes.

## Adding a model

1. Implement `VideoEnhancementModel` in `backend/app/inference/`.
2. Declare a stable ID, display name, scales, devices, weights, upstream source and license.
3. Download weights into the configured model directory through the weight manager.
4. Validate checkpoint structure before accepting the cached file.
5. Register the adapter in `ModelRegistry`.
6. Add unit tests that do not require downloading weights.
7. Test real load and one-frame inference on every claimed device.
8. Record practical findings in `model-evaluation.md`.

Never silently substitute a resize for an advertised AI model. The `lanczos-test` adapter exists
only for CI and smoke testing and is hidden from product APIs.

## FFmpeg rules

- Use argument arrays, never `shell=True`.
- Keep user strings out of output paths; use UUIDs.
- Register every long-lived process with `JobRuntime` so cancellation can terminate it.
- Drain or redirect stderr to avoid pipe deadlocks.
- Verify output before setting a job to complete.
- Keep browser output dimensions even and use `yuv420p` for broad H.264 playback.

## Test data

Generate tiny fixtures with FFmpeg lavfi. Do not commit downloaded or copyrighted video. The smoke
test creates a 160×90 test pattern plus a sine-wave AAC track at runtime.

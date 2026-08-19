# OhIc

**Restore, upscale, compare, and stream enhanced video.**

OhIc is a free, open-source video enhancement workspace. Import a file or permitted YouTube video,
choose the enhancement engine, detail, and output size, preview the result, and restore and upscale
it locally. The final result is a browser-friendly MP4 with source audio when available.

This README is for people using OhIc. If you are installing it for development, changing the
code, integrating the API, or tuning its configuration, see the
**[Developer README](DEVELOPER_README.md)**.

## Interface preview

<p align="center">
  <img src="public/UI1.png" alt="OhIc enhancement workspace showing video playback, resolution targets, quality controls, preview selection, and watch-while-enhancing" width="960">
</p>

<p align="center"><sub>The enhancement workspace after importing a video.</sub></p>

## What you can do

- Import local MP4, MOV, MKV, AVI, WebM, and M4V files.
- Inspect and download a permitted YouTube video with visible download percentage, speed, size,
  ETA, retry status, and a stop button.
- Import a YouTube playlist, select exactly which videos to process, and follow every item from
  download through enhancement. All videos are selected by default.
- Review resolution, frame rate, duration, file size, codec, aspect ratio, and SDR/HDR detection
  before processing.
- Choose an aspect-safe recommended output such as 720p, 1080p, 1440p, or 4K.
- Choose fast frame-by-frame Real-ESRGAN or experimental, temporally aware RealBasicVSR for
  supported videos.
- Pick **Fast**, **Balanced**, or **Maximum** quality.
- Test the exact enhancement pipeline on a five-second preview.
- Enhance the full video or save only a custom start-to-end range.
- Watch an enhanced video before the entire job finishes with adaptive, independently playable
  parts.
- Follow real enhancement progress, including stage, frames processed, processing FPS, elapsed
  time, and ETA.
- Leave an active session and reopen it from History without losing the chosen resolution,
  quality preset, preview point, range, or live progress.
- Stop queued or running downloads, enhancements, and playlist batches.
- Compare original and enhanced video with a draggable wipe or side-by-side view, synchronized
  playback, zoom, and frame stepping.
- Select and delete saved uploads, YouTube downloads, results, previews, and streaming parts from
  the Storage panel.

## Privacy and network use

Normal video uploads and AI processing happen on your computer. OhIc has no account system,
analytics, telemetry, or cloud video-processing service. Its local database contains metadata and
file locations—not copies of your video bytes.

Network access is used only when you ask OhIc to:

- inspect or download a YouTube video or playlist; or
- download an official AI model the first time you select its engine.

Use YouTube features only for videos you own or are permitted to download and process.

## Requirements

- macOS 13 or newer and Linux are supported.
- OhIc uses MPS or CUDA acceleration when available and falls back to CPU processing.
- Python 3.11 or 3.12, managed through [uv](https://docs.astral.sh/uv/).
- Node.js 22.13 or newer.
- FFmpeg, including FFprobe.
- At least about 500 MB for application dependencies, plus roughly 67 MB for Real-ESRGAN or
  141 MB for the optional RealBasicVSR checkpoint.
- Enough free disk space for the imported source, temporary processing data, streaming parts, and
  final result. Long or high-resolution videos can require several times the source file size.

CPU enhancement works, but it can be very slow. Supported hardware acceleration is strongly
recommended for longer videos.

## Install and start

On macOS, install the prerequisites:

```bash
brew install ffmpeg uv node
```

Then download OhIc and run its setup:

```bash
git clone <your-ohic-repository-url>
cd OhIc
./scripts/setup.sh
./scripts/start.sh
```

Open [http://localhost:3000](http://localhost:3000). Keep the Terminal window running while you
use OhIc. Press `Control-C` in that window to stop it.

The first run with an engine downloads its official checkpoint. Validated models are cached
locally for later jobs.

For platform-specific setup, manual commands, Docker, or non-default ports, follow the
[complete developer setup](DEVELOPER_README.md#setup-from-a-fresh-clone).

## Enhance one video

1. Open OhIc and choose **Local file** or **YouTube**.
2. Drop or browse to a local video. For YouTube, paste a single-video link, inspect it, confirm it
   is the correct video, and start the download.
3. Review the detected source details and choose an AI engine. **Real-ESRGAN ×2** is the reliable
   default. **RealBasicVSR ×4** is an experimental temporal option for sources up to 720p; it can
   reduce frame-to-frame flicker but needs substantially more memory and processing time.
4. Select an output resolution. OhIc marks a sensible target as **Recommended** and always
   preserves the source aspect ratio.
5. Choose a quality mode:

   - **Fast** is best for quick checks and long videos.
   - **Balanced** is the recommended detail-to-time tradeoff.
   - **Maximum** uses the slowest, finest pass and the highest output quality setting.

6. Move the preview marker to a representative moment and run the five-second preview.
7. Inspect the preview in the comparison viewer. You can drag the before/after divider, switch to
   side by side, zoom, pause, and use the arrow keys or frame buttons.
8. Return to the workspace and choose one of the full actions:

   - **Enhance full video** waits for one complete downloadable result.
   - **Enhance selected range** processes and saves only your chosen timestamps.
   - **Watch while enhancing** starts playback as soon as the first enhanced part is ready.

9. Download the completed MP4 from the result view.

RealBasicVSR supports previews, complete videos, and custom timestamp ranges. It does not yet
support **Watch while enhancing**, playlists, sources above 720p, or resuming a partially processed
job after the backend stops. OhIc disables unsupported actions instead of silently switching the
engine.

### Select only part of a video

The saved output defaults to the full source. Switch **Saved output range** from **Full** to
**Custom**, then choose the start and end. You can move the source player to an exact moment and
use **Use playhead** for either boundary. The selection must be at least 0.1 seconds long.

The preview marker is separate from the saved-output range: it controls which five seconds are
used for a preview, while the custom range controls the final or watch-while-enhancing output.

## Enhance a YouTube playlist

1. Open **YouTube**, switch from **Single video** to **Playlist**, and paste the playlist URL.
2. Inspect the playlist. OhIc lists up to 100 available videos and selects all of them by default.
3. Clear individual videos, use **Clear** to start over, or use **Select all** to restore the full
   selection.
4. Choose Fast, Balanced, or Maximum quality and start the playlist.
5. Open **Playlists** at any time to see the saved batch, its overall progress, and the stage and
   result for each video.

Playlist videos are processed sequentially to protect local memory. Each selected video is
downloaded, assigned its recommended output resolution, enhanced, and saved. The playlist remains
available when you move to another enhancement session or reopen the app. You can stop an active
batch, open completed items, or remove a finished playlist record. Removing the playlist record
does not delete its local videos; use **Storage** for that.

## Watch while enhancing

This mode divides the chosen full video or custom range into independently playable parts. For a
selection of at least two minutes, the first part is two minutes. For a selection from one minute
to under two minutes, the first part is one minute. Selections under one minute use five-second
parts throughout. After any larger first part, every later part is at most five seconds.

Each part becomes playable as soon as it finishes. OhIc advances to the next ready part
automatically behind one continuous full-duration player and timeline; internal part boundaries are
not exposed as separate videos. You can seek anywhere in the enhanced range that is already
buffered. If playback catches up with processing, it pauses at the buffer edge and resumes when
more video is available. You can leave the viewer and reopen it from **History** without losing the
rolling buffer. When processing finishes, OhIc joins the internal parts into one downloadable MP4.

<p align="center">
  <img src="public/UI2.png" alt="OhIc watch-while-enhancing player showing a continuous video timeline, rolling buffer, and live enhancement progress" width="960">
</p>

<p align="center"><sub>Watch the enhanced portion on one continuous timeline while the ready buffer grows in the background.</sub></p>

This design front-loads the main wait and reduces the chance of later pauses. It cannot make
enhancement run in real time, so a demanding upscale can still reach a part boundary before the
next part is ready.

## Track, reopen, and stop work

The top navigation provides three persistent views:

- **History** lists preview, full-video, custom-range, playlist, and watch-while-enhancing jobs.
  Open any row to return to the exact session. Active rows show **View live** and a **Stop** button.
- **Playlists** preserves playlist batches and each selected video's state.
- **Storage** lists the local files managed by OhIc and their disk usage.

Only one enhancement runs at a time. Additional jobs wait in the queue. Stopping a queued job
prevents it from starting; stopping a running job terminates its active media processes and removes
its incomplete final output. Already playable streaming parts may remain until you delete them
from Storage.

History and playlist metadata survive normal app restarts. A job that is actively processing does
not resume after the local engine itself is stopped or the computer is restarted.

## Manage local storage

Open **Storage**, select one or more inactive items, review their combined size, and choose
**Delete selected**. Active sources and outputs are locked until their jobs are stopped.

Deleting a source also removes its linked results and History records. Deleting an output removes
that job's result, preview comparison file, and any watch-while-enhancing parts. Deletion is
permanent, so download or copy anything you want to keep first.

By default, OhIc stores its working data in the repository's `data` folder.

## Understanding the result

OhIc's AI engines synthesize plausible visual detail and then size the frame exactly for the chosen
output. They can make many low-resolution or compressed videos look clearer, but cannot recover
facts that are absent from the source. Do not treat reconstructed faces, text, license plates, or
objects as forensic evidence.

Real-ESRGAN enhances frames independently, so difficult motion, grain, flashing detail, or heavy
compression can shimmer. RealBasicVSR considers nearby frames, but may instead produce motion
smear, ghosting, or unstable detail. Always use a representative preview before a long job.

## Troubleshooting

### “OhIc's local engine is not running”

Make sure `./scripts/start.sh` is still running in Terminal. If it stopped, run it again from the
OhIc folder, then refresh the browser. The health page at
[http://localhost:8000/api/health](http://localhost:8000/api/health) should report FFmpeg,
FFprobe, and the detected accelerator.

### FFmpeg or FFprobe is missing

Install FFmpeg and restart OhIc:

```bash
brew install ffmpeg
```

### A YouTube video will not download

Confirm that the video is public, available in your region, and permitted for you to download.
Then update the backend dependencies and retry:

```bash
cd backend
uv lock --upgrade-package yt-dlp
uv sync --group dev
cd ..
./scripts/start.sh
```

YouTube changes frequently. Some videos require sign-in or a YouTube PO token and cannot be
downloaded by OhIc's anonymous local downloader. OhIc automatically tries several compatible
formats and abandons unusably throttled streams instead of appearing stuck.

### The first enhancement cannot download the AI model

Check the internet connection and retry. A partial or invalid model is discarded automatically.
The next job downloads a clean copy.

### Enhancement runs out of memory

Try a lower target resolution or Fast/Balanced quality. OhIc automatically retries once with
smaller tiles, but very large frames can still exceed available GPU or unified memory.

### Processing is slower than expected

Real-ESRGAN evaluates every frame. Start with a five-second preview, use the recommended target,
and choose Fast. CPU processing can be much slower than playback speed; use supported hardware
acceleration when available.

### A result disappeared

The source or output may have been removed in Storage or outside OhIc. The app keeps metadata and
media files separately, so moving or deleting managed files manually can leave an unavailable
History entry.

More diagnostics—including ports, CORS, logs, live YouTube tests, model cache recovery, and data
inspection—are in the [developer troubleshooting guide](DEVELOPER_README.md#troubleshooting).

## Current limitations

- Output is H.264 video with optional AAC audio in an MP4 container.
- Subtitle streams, attachments, chapters, multiple audio tracks, HDR-preserving output, and
  source metadata are not carried into the result.
- HDR sources are detected, but enhancement currently passes through an 8-bit RGB pipeline and
  produces SDR output.
- RealBasicVSR is experimental, limited to 720p input, and unavailable for playlists and
  watch-while-enhancing.
- Playlist imports are limited to the first 100 available entries and use each video's recommended
  resolution; per-item resolution and timestamp ranges are not currently configurable.
- YouTube sign-in, cookies, and PO-token configuration are not exposed in the app.
- Enhancement runs in the local backend process and does not survive that process being stopped.
- Only one enhancement, one standalone YouTube download, and one playlist workflow are dispatched
  at a time in their respective queues. They can still contend for disk, network, and CPU.

## Documentation and license

- [Developer README](DEVELOPER_README.md)—complete setup, configuration, architecture, API,
  pipeline, persistence, tests, Docker, and contribution guide
- [Architecture notes](docs/architecture.md)—short architectural overview
- [Model evaluation](docs/model-evaluation.md)—why Real-ESRGAN ×2 was selected
- [RealBasicVSR experiment](docs/realbasicvsr-experiment.md)—temporal engine status and limits
- [Third-party notices](THIRD_PARTY_NOTICES.md)—upstream software and model licensing

OhIc is licensed under the [MIT License](LICENSE). Third-party software and model weights retain
their own licenses.

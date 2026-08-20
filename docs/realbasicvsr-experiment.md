# RealBasicVSR experiment

## Goal and current status

This branch evaluates whether RealBasicVSR gives visibly steadier, more useful restoration than
OhIc's frame-by-frame Real-ESRGAN path while remaining practical on local hardware. It is an
experiment, not a production replacement.

Phases 1–3 are implemented on the experimental branch. The real checkpoint, bounded overlapping
temporal windows, FFmpeg video plumbing, statistics, cancellation-safe cleanup, and source audio
handling are available through both a research CLI and normal preview/full jobs. The app exposes
an explicit experimental engine selector, persists that choice in History, validates capabilities
before queueing, and provides a repeatable two-engine comparison command.

Still intentionally unsupported:

- resumable jobs after a backend process stop;
- watch-while-enhancing and playlist batches with RealBasicVSR;
- inputs above 1280×720 unless the research CLI's explicit override is used;
- spatial tiling or HDR-preserving output.

## Why this needs a separate path

Real-ESRGAN receives one RGB frame and returns one enhanced RGB frame. RealBasicVSR first cleans a
sequence, estimates optical flow in both directions, propagates features through time, and then
produces an enhanced sequence. Treating it as a frame adapter would remove the information being
evaluated.

The temporal boundary therefore represents `enhance_sequence(frames)` and its video pipeline
represents `enhance_video`. The frame-oriented `VideoEnhancementModel.enhance_frame` contract
remains unchanged; the job layer dispatches each registered engine to the correct pipeline.

## Upstream implementation and dependency choice

References:

- [official RealBasicVSR repository](https://github.com/ckkelvinchan/RealBasicVSR);
- [CVPR 2022 paper](https://arxiv.org/abs/2111.12704);
- [current MMagic RealBasicVSR model page](https://github.com/open-mmlab/mmagic/tree/main/configs/real_basicvsr);
- [MMagic RealBasicVSR implementation](https://github.com/open-mmlab/mmagic/tree/main/mmagic/models/editors/real_basicvsr).

The official 2022 inference script depends on the older MMEditing/MMCV stack, reads an entire
video into a Python list, and uses OpenCV for output. Current MMagic's normal runtime dependency
set is much broader than this application needs. Installing either stack into OhIc would add
substantial compatibility risk, especially on macOS and Apple Silicon.

OhIc therefore contains only a checkpoint-compatible inference adaptation of the official
RealBasicVSR generator, BasicVSR propagation network, SPyNet, and small PyTorch helpers. Training,
discriminators, metrics, registry, MMCV, MMEngine, OpenCV, and unrelated model code are excluded.
The adaptation keeps the upstream module names and inference math; strict loading confirms that
all 320 EMA generator tensors in the official checkpoint are consumed. PyTorch is the only model
runtime dependency, and it was already required by OhIc.

## Checkpoint and cache

The experiment downloads:

```text
realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth
```

Source:
[OpenMMLab model hosting](https://download.openmmlab.com/mmediting/restorers/real_basicvsr/realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth)

Verified properties:

| Property | Value |
| --- | --- |
| Size | 148,239,017 bytes (about 141 MiB) |
| SHA-256 | `52f77c2c835aaa3fe675b3959b2f85010a6c6f63f77f7e279394646e55a4e376` |
| Generator | RealBasicVSR ×4, 64 channels, 20 propagation and 20 cleaning blocks |
| Preferred state | `generator_ema` |

The file is cached under `OHIC_MODEL_DIR`, or `data/models/` by default. Downloads use a `.part`
file, report progress when the server supplies a length, verify the complete SHA-256, and rename
atomically. Interrupted and invalid partial files are removed. Checkpoints are ignored by Git and
are never bundled in this repository.

## Licensing and redistribution

- The official RealBasicVSR repository is Apache License 2.0.
- MMagic is Apache License 2.0. The adapted inference files retain source links and attribution.
- BasicSR is also Apache License 2.0, but it is not a runtime or vendored dependency here.
- The official model page publishes the checkpoint but does not state a separate checkpoint-only
  license. This branch downloads it from upstream rather than redistributing it. Anyone packaging
  or redistributing the checkpoint should confirm the applicable model terms with OpenMMLab or
  the authors instead of assuming the application license applies.

Apache attribution and license obligations remain in force for the adapted code. See
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## Enable it in the app

The engine is registered by default on this branch. To hide it from `/api/models` and the UI:

```dotenv
OHIC_ENABLE_REALBASICVSR=false
```

Restart the backend after changing the setting. Select **RealBasicVSR ×4** under **AI engine** for
a supported single video. Preview, complete-video, and custom-range jobs use the temporal path;
History restores the choice. The API model ID is `realbasicvsr-x4-experimental`.

The app rejects sources above 1280×720 and disables watch-while-enhancing for this engine. It never
silently replaces a selected temporal job with Real-ESRGAN.

## Run the isolated experiment

Complete the normal backend setup and ensure FFmpeg/FFprobe are available. No additional Python
package is needed.

From the repository root:

```bash
backend/.venv/bin/python backend/scripts/test_realbasicvsr.py \
  --input /path/to/input.mp4 \
  --output /path/to/realbasicvsr-output.mp4
```

Useful options:

```text
--device auto|mps|cuda|cpu
--chunk-frames N
--overlap-frames N
--target-width N
--target-height N
--model-dir PATH
--allow-large-input
--debug
```

RealBasicVSR natively produces ×4 frames. `--target-width` and `--target-height` apply one final
high-quality Lanczos resize in FFmpeg; they do not change the model scale. Supplying one dimension
derives the other from the source aspect ratio. The default output is the native ×4 result.

The CLI emits JSON lines for model download/load, decoding, each restoration window, audio muxing,
errors, and completion. The completion event includes model/device, input/model/output resolution,
FPS, duration, frame count, window/overlap, model load time, decode/inference/encoding/total time,
effective inference FPS, peak process RSS, output size, and audio mode.

## Temporal windows and memory bound

The model is recurrent and bidirectional: a full-video result can depend on distant earlier and
later frames. No small overlap can be mathematically identical to processing an unbounded video in
one pass. Carrying only forward hidden state would still omit the backward pass, so this path does
not claim exact chunk equivalence.

Instead, each window includes left and right context. Only the center is emitted; context outputs
are discarded. This avoids duplicate frames and reduces boundary discontinuity while bounding
memory. Defaults scale down with input pixels because retained 64-channel features and ×4 output
frames dominate memory:

| Input size | Total window | Context on each side | Emitted center stride |
| --- | ---: | ---: | ---: |
| Up to 640×360 | 30 frames | 5 frames | 20 frames |
| Up to 854×480 | 16 frames | 3 frames | 10 frames |
| Up to 1280×720 | 8 frames | 1 frame | 6 frames |

These values are conservative engineering starting points, not quality-optimal constants. The
30-frame low-resolution window aligns with the sequence length used by the published checkpoint's
training configuration. Boundary behavior must still be judged visually and compared against a
single-window result on short clips.

Spatial tiling is not enabled. Optical flow and propagated features cross spatial boundaries, so
ordinary image tiles could introduce seams or incorrect motion. The CLI rejects inputs above
1280×720 by default. `--allow-large-input` is an explicit research override, not a promise that the
video will fit in memory.

## Device and precision status

| Device | Experimental status | Precision |
| --- | --- | --- |
| MPS | Experimental; actual small-clip inference verified | FP32 |
| CUDA | Expected from upstream/PyTorch graph; not tested in this branch yet | FP32 |
| CPU | Supported and used as automatic fallback | FP32 |

MPS validation on 19 August 2026 used a compatible Apple Silicon system with Python 3.11 and
PyTorch 2.13. The official checkpoint processed a two-frame 64×64 RGB clip on MPS and produced a
valid result. The final test file preserved 2 FPS, exactly 1.000-second duration, H.264 video, and
copied AAC audio. Performance and memory vary materially by source and hardware, so run the
comparison command on the intended system instead of relying on one machine's timing.

This proves that the tested operators and tiny configuration run on this MPS stack. It does not
prove that 360p–720p clips fit or perform acceptably. `--device auto` tries MPS first and retries the
whole job on CPU only when the first attempt reports an MPS/Metal unsupported-operation failure.
An explicitly selected device fails instead of silently changing hardware. CUDA and CPU remain
available without globally changing Real-ESRGAN device selection.

FP16 is deliberately disabled. It has not been validated for numerical stability or MPS operator
coverage. CUDA mixed precision can be evaluated separately after FP32 correctness baselines exist.

## FFmpeg, FPS, audio, and color

FFmpeg remains the only video plumbing layer:

1. FFprobe reads source resolution, duration, average FPS, frame count, and audio presence.
2. FFmpeg decodes the first video stream to `rgb24` through a bounded pipe.
3. Python normalizes RGB uint8 to `[0, 1]`, runs sequence inference, clamps to `[0, 1]`, and writes
   restored RGB uint8 frames to a second pipe.
4. FFmpeg encodes H.264/yuv420p and applies optional Lanczos final sizing.
5. Scene-aware windowing resets overlap at hard cuts so propagated features never cross scenes.
6. Final mux maps all audio/chapters/metadata into MP4 or preserves every compatible source track
   in MKV archive mode.
7. The finalized result is moved into place only after every stage succeeds.

Output FPS equals FFprobe's average source FPS and frame count is preserved. The current raw-frame
prototype produces constant-frame-rate output, so exact variable-frame-rate timestamps are not
yet preserved. Frame interpolation is not performed.

The RGB path avoids an RGB/BGR swap and uses the same FFmpeg color conversion boundary as the
production pipeline. Formal BT.601/BT.709, range, gamma, HDR, rotation, and metadata round-trip
validation is still outstanding. Do not use experimental output as evidence that those properties are
preserved.

## Cancellation and cleanup

The CLI registers decoder and encoder processes in `JobRuntime`, checks cancellation between
temporal windows, removes its temporary directory on every exit, exposes no partial output as a
success, releases model references, and clears MPS/CUDA caches where supported. `Ctrl+C` terminates
active FFmpeg processes and returns exit code 130. An inference kernel already executing cannot be
interrupted mid-window, which is why windows remain deliberately bounded.

## Test and benchmark workflow

### Experiment log

#### Experiment 1 — integration and comparison smoke test

- Input: synthetic 64×64 RGB clip, 2 FPS, 1 second, 2 frames, AAC audio.
- Device: MPS, FP32.
- Output: 128×128 H.264/AAC, 2 FPS, exactly 1 second for both engines.
- Real-ESRGAN: 1.077 seconds, about 3.50 processing FPS, 22,211 bytes.
- RealBasicVSR: two-frame window with no overlap; 0.495 seconds including model load, about
  9.33 inference FPS, 18,634 bytes, about 581 MiB peak process RSS.
- Job integration: actual preview and full jobs completed; an in-flight full job cancelled without
  publishing a partial output and cleaned its temporary workspace.
- Visual observations: this generated clip validates plumbing, not perceptual quality. It is too
  short and simple to judge temporal stability, faces, motion, chunk boundaries, or product fit.

These figures are a correctness smoke test, not a representative speed comparison. The checkpoint
was warm in the local cache, and the very small input does not reflect normal decoder, model, or
memory scaling.

Run the engineering tests without downloading the model:

```bash
cd backend
uv run pytest tests/test_realbasicvsr_experiment.py
```

They cover temporal coverage/no duplicates, overlap validation, resolution-based defaults,
engine-specific device choice, EMA checkpoint selection, hash/cache recovery, and an end-to-end
synthetic FFmpeg path that preserves FPS, duration, dimensions, and audio. A cancellation test
also verifies that stopping between windows does not publish a partial final output.

For visual evaluation, use short local or clearly redistributable clips. Do not commit test video.

| Class | Suggested source | Inspect carefully |
| --- | --- | --- |
| Old compressed footage | 360p/480p, strong macroblocking | artifact amplification, flicker |
| Faces | moderate motion and close faces | eyes, mouths, hair, invented texture |
| High motion | sport, pans, camera shake | ghosting, smearing, temporal lag |
| Fine detail | buildings, text, foliage | changing glyphs, shimmer, unstable edges |
| Poor source | blur, noise, mixed compression | hallucination, color and contrast shifts |

For every clip, compare original, Real-ESRGAN, and RealBasicVSR at the same selected source range
and final dimensions. The comparison command prepares one shared source clip before running either
engine, so both receive identical decoded content:

```bash
backend/.venv/bin/python backend/scripts/compare_engines.py \
  --input /path/to/input.mp4 \
  --output-dir tmp/comparison \
  --start 30 \
  --duration 10 \
  --target-width 1280 \
  --target-height 720
```

The directory contains `original.mp4`, `realesrgan.mp4`, `realbasicvsr.mp4`, and
`comparison.json`. The report records device, time, FPS, dimensions, file sizes, temporal window
configuration, and a visual checklist covering consistency, faces, text, foliage, motion,
hallucination, boundaries, and color. Optional `--device`, `--chunk-frames`, `--overlap-frames`,
and `--allow-large-input` arguments match the isolated experiment.

Watch-while-enhancing remains unsupported for RealBasicVSR until independent temporal windows are
visually proven not to introduce objectionable boundary artifacts. Full and range jobs are split
into durable checkpoints; after a hard-process restart, completed checkpoint files are verified and
reused while the interrupted checkpoint is regenerated from its scene boundary-aware input range.

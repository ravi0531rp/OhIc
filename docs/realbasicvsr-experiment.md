# RealBasicVSR experiment

## Goal and current status

This branch evaluates whether RealBasicVSR gives visibly steadier, more useful restoration than
OhIc's frame-by-frame Real-ESRGAN path while remaining practical on local hardware. It is an
experiment, not a production replacement.

Phase 1 is implemented as an isolated CLI path. It uses the real RealBasicVSR checkpoint, bounded
overlapping temporal windows, FFmpeg video plumbing, output statistics, cancellation-safe process
cleanup, and optional source-audio stream copy. It is intentionally not registered in the app yet.
Real-ESRGAN remains the only production engine and all existing requests behave as before.

Not implemented in phase 1:

- app/API engine selection;
- preview and history integration;
- resumable jobs;
- watch-while-enhancing;
- comparison automation;
- spatial tiling or HDR-preserving output.

## Why this needs a separate path

Real-ESRGAN receives one RGB frame and returns one enhanced RGB frame. RealBasicVSR first cleans a
sequence, estimates optical flow in both directions, propagates features through time, and then
produces an enhanced sequence. Treating it as a frame adapter would remove the information being
evaluated.

The phase-one boundary therefore represents `enhance_sequence(frames)` and the end-to-end CLI
represents `enhance_video`. The production `VideoEnhancementModel.enhance_frame` contract is left
unchanged until the job layer has a genuinely video-oriented engine contract.

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
one pass. Carrying only forward hidden state would still omit the backward pass, so phase 1 does
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

| Device | Phase-one status | Precision |
| --- | --- | --- |
| MPS | Experimental; actual small-clip inference verified | FP32 |
| CUDA | Expected from upstream/PyTorch graph; not tested in this branch yet | FP32 |
| CPU | Supported and used as automatic fallback | FP32 |

MPS validation on 19 August 2026 used an Apple M3 Pro MacBook Pro with 36 GB unified memory,
macOS 26.6.1, Python 3.11.15, and PyTorch 2.13.0. The official checkpoint processed a two-frame
64×64 RGB clip on MPS and produced a valid result. Measured inference was 2.392 seconds, or 0.836
FPS, with about 514 MiB peak process RSS. The final test file preserved 2 FPS, exactly 1.000-second
duration, H.264 video, and copied AAC audio.

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
5. The first source audio stream is copied when MP4-compatible; otherwise it is encoded to AAC.
6. The finalized fast-start MP4 is moved into place only after every stage succeeds.

Output FPS equals FFprobe's average source FPS and frame count is preserved. The current raw-frame
prototype produces constant-frame-rate output, so exact variable-frame-rate timestamps are not
yet preserved. Frame interpolation is not performed.

The RGB path avoids an RGB/BGR swap and uses the same FFmpeg color conversion boundary as the
production pipeline. Formal BT.601/BT.709, range, gamma, HDR, rotation, and metadata round-trip
validation is still outstanding. Do not use phase-one output as evidence that those properties are
preserved.

## Cancellation and cleanup

The CLI registers decoder and encoder processes in `JobRuntime`, checks cancellation between
temporal windows, removes its temporary directory on every exit, exposes no partial output as a
success, releases model references, and clears MPS/CUDA caches where supported. `Ctrl+C` terminates
active FFmpeg processes and returns exit code 130. An inference kernel already executing cannot be
interrupted mid-window, which is why windows remain deliberately bounded.

## Test and benchmark workflow

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

For every clip, compare original, Real-ESRGAN, and RealBasicVSR at the same final dimensions and
encoding settings. Record temporal consistency, face stability, text shape, foliage shimmer,
motion artifacts, hallucination, chunk-boundary jumps, color fidelity, processing FPS, peak RSS,
and output size. A comparison script is phase 3; phase 1 prints the RealBasicVSR measurements needed
for a manual comparison.

## Phase-two integration boundary

The next milestone should introduce a video-job engine interface rather than extending the current
frame method. The production job runner can then dispatch Real-ESRGAN to its streaming frame path
and RealBasicVSR to this bounded sequence path through one central registry. API requests without
an engine must continue to default to `realesrgan-x2plus`; old persisted jobs already carry that
model ID. RealBasicVSR should be behind a disabled-by-default capability flag until preview, full
jobs, progress, cancellation, errors, and history have all been tested.

Watch-while-enhancing remains unsupported for RealBasicVSR until independent temporal windows are
visually proven not to introduce boundary artifacts. Hard-process resume is also unsupported
because recurrent state and context are not persisted.

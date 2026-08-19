# Model evaluation

Evaluation date: 2026-08-18.

This was a focused MVP engineering evaluation, not a perceptual benchmark. The selected
Real-ESRGAN path was integrated and verified through checkpoint loading and real inference.
Unmeasured values are marked accordingly.

| Candidate | Quality and temporal behavior | Hardware support | Memory and speed | Setup complexity | Decision |
| --- | --- | --- | --- | --- | --- |
| Real-ESRGAN ×2/×4 | Strong general restoration per frame; possible shimmer because frames are independent | The RRDB operations work through PyTorch on MPS, CUDA, and CPU. The ×2 checkpoint completed real inference validation. | Tile-dependent; benchmark representative sources on the intended deployment hardware. | Moderate. OhIc implements the checkpoint-compatible RRDBNet directly to avoid older BasicSR coupling. | **Default: official ×2 checkpoint** |
| Real-ESRGAN NCNN/Vulkan | Comparable model family; upstream notes tile-block differences | Portable Vulkan builds are available upstream, but this backend has not been integrated or benchmarked in OhIc. | Not measured | Requires an external binary and a separate model lifecycle. | Consider as an optional backend after cross-platform benchmarks. |
| BasicVSR++ | Temporal propagation should reduce frame-to-frame inconsistency on suitable footage. | Its OpenMMLab and deformable-alignment stack adds operator and packaging risk across accelerators. | Expected to retain frame windows and require materially more memory; not measured. | High | Revisit as a quality-focused temporal backend after verifying maintained device support. |
| RealBasicVSR | Designed for real-world degraded video and temporally aware restoration. | No cross-platform validation was completed in this evaluation. | Expected to exceed per-frame ×2 inference; not measured. | High | Future maximum-quality candidate. |

## Verified implementation facts

- `RealESRGAN_x2plus.pth` is downloaded from the official upstream release, not committed.
- The checkpoint exposes `params_ema`, a 12-channel pixel-unshuffle input, and two upsample stages.
- OhIc validates the complete state dictionary with strict loading.
- PyTorch inference validation produced a 32×32 RGB result from a 16×16 input without substituting
  a non-AI resize.
- The adapter accepts odd tile edges by padding to the ×2 pixel-unshuffle requirement and cropping
  output back to the expected size.
- Final non-integer target sizing uses Lanczos after the genuine ×2 model output.

## Known issues

- Per-frame inference does not guarantee temporal consistency.
- Memory estimates remain conservative heuristics until benchmarks cover representative sources
  and deployment hardware.
- PyTorch and model updates can change accelerator behavior; dependency updates should repeat a
  checkpoint load and one-frame inference on each claimed device.
- HDR is detected, but the current RGB8 pipeline produces SDR output.

## Recommendation

Keep Real-ESRGAN ×2 as the first reliable backend, keep tiling automatic, and guide users through
a five-second preview. Evaluate NCNN on representative clips and multiple hardware classes before
offering it. Prototype a temporal backend only after confirming maintained operator support and a
reproducible installation path.

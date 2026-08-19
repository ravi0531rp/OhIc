# Model evaluation

Evaluation date: 2026-08-18. Target: Apple M3 Pro, 36 GB unified memory, macOS.

This was a focused MVP engineering spike, not a perceptual benchmark. Only the selected
Real-ESRGAN path was integrated and device-tested. Unmeasured values are marked accordingly.

| Candidate | Quality / temporal behavior | Apple Silicon | Memory / speed | Setup complexity | Decision |
| --- | --- | --- | --- | --- | --- |
| Real-ESRGAN ×2/×4 | Strong general restoration per frame; possible shimmer because frames are independent | Official RRDB operations load and run on PyTorch MPS. The ×2 checkpoint was structurally loaded and a real inference pass completed on M3 Pro | Tile-dependent; practical full-video figures require the benchmark command on representative sources | Moderate. Upstream Python package has older BasicSR coupling, so OhIc implements the checkpoint-compatible RRDBNet directly | **MVP default: official ×2 checkpoint** |
| Real-ESRGAN NCNN/Vulkan | Comparable model family; upstream notes tile-block differences | Upstream publishes portable macOS assets, but no current M3 GPU result was established in this spike | Not measured | External binary and model lifecycle add packaging work | Keep as an optional future backend after an M3 benchmark |
| BasicVSR++ | Temporal propagation should reduce frame-to-frame inconsistency on suitable footage | No official MPS support claim was found. Its OpenMMLab/deformable-alignment stack raises operator and build risk on MPS | Expected to retain frame windows and require materially more unified memory; not measured | High on a clean local install | Do not block MVP; revisit as a high-quality temporal backend |
| RealBasicVSR | Designed for real-world degraded video and temporally aware restoration | No verified MPS run in this spike | Not measured; expected above per-frame ×2 inference | High OpenMMLab dependency burden and sequence handling | Future maximum-quality candidate |

## Verified MVP facts

- Official `RealESRGAN_x2plus.pth` is downloaded from the upstream GitHub release, not committed.
- The checkpoint exposes `params_ema`, a 12-channel pixel-unshuffle input and two upsample stages.
- OhIc validates the complete state dict with strict loading.
- On the target M3 Pro, PyTorch selected `mps`; the network loaded and produced a 32×32 RGB output
  from a 16×16 input without CPU fallback or unsupported-operator failure.
- The adapter accepts odd tile edges by padding to the ×2 pixel-unshuffle requirement and cropping
  output back to the exact expected size.
- Final non-integer target sizing uses Lanczos after the real ×2 model output, matching the
  upstream concept of arbitrary outscale.

## Known issues

- Per-frame inference does not guarantee temporal consistency.
- Memory estimates are conservative heuristics until representative M3 benchmark data is stored.
- PyTorch and model versions can change MPS behavior; every dependency update should repeat a
  real checkpoint load and one-frame device inference.
- HDR is detected but the v0.1 RGB8 pipeline produces SDR output.

## Recommendation

Ship Real-ESRGAN ×2 as the first reliable backend, keep tiling automatic, and guide users through
a five-second preview. Benchmark NCNN on the same M3 clips before offering it. Prototype
BasicVSR++ only after confirming a maintained MPS-compatible deformable-convolution path; temporal
quality is attractive but not worth destabilizing installation for the MVP.

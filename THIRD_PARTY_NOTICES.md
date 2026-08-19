# Third-party notices

OhIc does not bundle third-party model weights in Git. On first use it downloads the official
`RealESRGAN_x2plus.pth` release asset from the Real-ESRGAN project.

| Component | Use | License / source |
| --- | --- | --- |
| Real-ESRGAN code and weights | Default restoration model | BSD-3-Clause, [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) |
| RealBasicVSR / MMagic inference code | Experimental temporal restoration adapter | Apache-2.0, [ckkelvinchan/RealBasicVSR](https://github.com/ckkelvinchan/RealBasicVSR) and [open-mmlab/mmagic](https://github.com/open-mmlab/mmagic) |
| RealBasicVSR checkpoint | Optional experimental ×4 model, downloaded but not redistributed | [OpenMMLab model page](https://github.com/open-mmlab/mmagic/tree/main/configs/real_basicvsr); no separate checkpoint-only license was located, so redistribution requires an independent terms review |
| PyTorch | Tensor inference and MPS/CUDA support | BSD-style, [pytorch/pytorch](https://github.com/pytorch/pytorch) |
| FFmpeg | Decode, encode and audio muxing | LGPL/GPL depending on the local build, [ffmpeg.org](https://ffmpeg.org/legal.html) |
| yt-dlp | YouTube metadata and permitted downloads | Unlicense, [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| FastAPI | Local HTTP API | MIT |
| React, vinext and Vite | Browser workspace | MIT |
| Lucide | Interface icons | ISC |

Each dependency remains subject to its own license. Users distributing packaged builds should
review the exact FFmpeg build and dependency versions they ship.

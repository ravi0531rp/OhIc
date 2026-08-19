"""Minimal RealBasicVSR inference graph adapted from OpenMMLab MMagic.

The upstream implementation is Apache-2.0 licensed. This adaptation removes
MMCV/MMEngine registration, logging, training, and initialization helpers while
preserving the checkpoint-compatible inference module hierarchy and math.

Sources:
https://github.com/open-mmlab/mmagic/tree/main/mmagic/models/editors/real_basicvsr
https://github.com/open-mmlab/mmagic/blob/main/mmagic/models/editors/basicvsr/basicvsr_net.py
"""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F


def flow_warp(
    feature: Tensor,
    flow: Tensor,
    interpolation: str = "bilinear",
    padding_mode: str = "zeros",
    align_corners: bool = True,
) -> Tensor:
    """Warp a feature map with pixel-space optical flow."""
    if feature.size()[-2:] != flow.size()[1:3]:
        raise ValueError("Feature and optical-flow spatial sizes must match.")
    _, _, height, width = feature.size()
    grid_y, grid_x = torch.meshgrid(
        torch.arange(height, device=flow.device, dtype=feature.dtype),
        torch.arange(width, device=flow.device, dtype=feature.dtype),
        indexing="ij",
    )
    grid = torch.stack((grid_x, grid_y), 2)
    grid_flow = grid + flow
    grid_x = 2.0 * grid_flow[:, :, :, 0] / max(width - 1, 1) - 1.0
    grid_y = 2.0 * grid_flow[:, :, :, 1] / max(height - 1, 1) - 1.0
    sample_grid = torch.stack((grid_x, grid_y), dim=3).to(dtype=feature.dtype)
    return F.grid_sample(
        feature,
        sample_grid,
        mode=interpolation,
        padding_mode=padding_mode,
        align_corners=align_corners,
    )


class ResidualBlockNoBN(nn.Module):
    def __init__(self, mid_channels: int = 64, res_scale: float = 1.0) -> None:
        super().__init__()
        self.res_scale = res_scale
        self.conv1 = nn.Conv2d(mid_channels, mid_channels, 3, 1, 1, bias=True)
        self.conv2 = nn.Conv2d(mid_channels, mid_channels, 3, 1, 1, bias=True)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, value: Tensor) -> Tensor:
        return value + self.conv2(self.relu(self.conv1(value))) * self.res_scale


class PixelShufflePack(nn.Module):
    def __init__(
        self, in_channels: int, out_channels: int, scale_factor: int, upsample_kernel: int
    ) -> None:
        super().__init__()
        self.scale_factor = scale_factor
        self.upsample_conv = nn.Conv2d(
            in_channels,
            out_channels * scale_factor * scale_factor,
            upsample_kernel,
            padding=(upsample_kernel - 1) // 2,
        )

    def forward(self, value: Tensor) -> Tensor:
        return F.pixel_shuffle(self.upsample_conv(value), self.scale_factor)


class _ConvModule(nn.Module):
    """Checkpoint-compatible subset of MMCV ConvModule."""

    def __init__(self, in_channels: int, out_channels: int, activate: bool = True) -> None:
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, 7, 1, 3)
        self.activate = nn.ReLU(inplace=True) if activate else nn.Identity()

    def forward(self, value: Tensor) -> Tensor:
        return self.activate(self.conv(value))


class SPyNetBasicModule(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.basic_module = nn.Sequential(
            _ConvModule(8, 32),
            _ConvModule(32, 64),
            _ConvModule(64, 32),
            _ConvModule(32, 16),
            _ConvModule(16, 2, activate=False),
        )

    def forward(self, value: Tensor) -> Tensor:
        return self.basic_module(value)


class SPyNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.basic_module = nn.ModuleList([SPyNetBasicModule() for _ in range(6)])
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    def compute_flow(self, reference: Tensor, supporting: Tensor) -> Tensor:
        batch, _, height, width = reference.size()
        references = [(reference - self.mean) / self.std]
        supporting_frames = [(supporting - self.mean) / self.std]
        for _ in range(5):
            references.append(
                F.avg_pool2d(references[-1], 2, 2, count_include_pad=False)
            )
            supporting_frames.append(
                F.avg_pool2d(supporting_frames[-1], 2, 2, count_include_pad=False)
            )
        references.reverse()
        supporting_frames.reverse()
        flow = references[0].new_zeros(batch, 2, height // 32, width // 32)
        for level, current_reference in enumerate(references):
            flow_up = (
                flow
                if level == 0
                else F.interpolate(flow, scale_factor=2, mode="bilinear", align_corners=True)
                * 2.0
            )
            warped = flow_warp(
                supporting_frames[level],
                flow_up.permute(0, 2, 3, 1),
                padding_mode="border",
            )
            flow = flow_up + self.basic_module[level](
                torch.cat((current_reference, warped, flow_up), 1)
            )
        return flow

    def forward(self, reference: Tensor, supporting: Tensor) -> Tensor:
        height, width = reference.shape[2:4]
        width_up = width if width % 32 == 0 else 32 * (width // 32 + 1)
        height_up = height if height % 32 == 0 else 32 * (height // 32 + 1)
        reference = F.interpolate(
            reference, size=(height_up, width_up), mode="bilinear", align_corners=False
        )
        supporting = F.interpolate(
            supporting, size=(height_up, width_up), mode="bilinear", align_corners=False
        )
        flow = F.interpolate(
            self.compute_flow(reference, supporting),
            size=(height, width),
            mode="bilinear",
            align_corners=False,
        )
        flow[:, 0] *= width / width_up
        flow[:, 1] *= height / height_up
        return flow


class ResidualBlocksWithInputConv(nn.Module):
    def __init__(self, in_channels: int, out_channels: int = 64, num_blocks: int = 30) -> None:
        super().__init__()
        self.main = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, 1, 1, bias=True),
            nn.LeakyReLU(negative_slope=0.1, inplace=True),
            nn.Sequential(*(ResidualBlockNoBN(out_channels) for _ in range(num_blocks))),
        )

    def forward(self, feature: Tensor) -> Tensor:
        return self.main(feature)


class BasicVSRNet(nn.Module):
    def __init__(self, mid_channels: int = 64, num_blocks: int = 20) -> None:
        super().__init__()
        self.mid_channels = mid_channels
        self.spynet = SPyNet()
        self.backward_resblocks = ResidualBlocksWithInputConv(
            mid_channels + 3, mid_channels, num_blocks
        )
        self.forward_resblocks = ResidualBlocksWithInputConv(
            mid_channels + 3, mid_channels, num_blocks
        )
        self.fusion = nn.Conv2d(mid_channels * 2, mid_channels, 1, 1, 0, bias=True)
        self.upsample1 = PixelShufflePack(mid_channels, mid_channels, 2, 3)
        self.upsample2 = PixelShufflePack(mid_channels, 64, 2, 3)
        self.conv_hr = nn.Conv2d(64, 64, 3, 1, 1)
        self.conv_last = nn.Conv2d(64, 3, 3, 1, 1)
        self.img_upsample = nn.Upsample(scale_factor=4, mode="bilinear", align_corners=False)
        self.lrelu = nn.LeakyReLU(negative_slope=0.1, inplace=True)

    def compute_flow(self, frames: Tensor) -> tuple[Tensor, Tensor]:
        batch, count, channels, height, width = frames.size()
        first = frames[:, :-1].reshape(-1, channels, height, width)
        second = frames[:, 1:].reshape(-1, channels, height, width)
        backward = self.spynet(first, second).view(batch, count - 1, 2, height, width)
        forward = self.spynet(second, first).view(batch, count - 1, 2, height, width)
        return forward, backward

    def forward(self, frames: Tensor) -> Tensor:
        batch, count, _, height, width = frames.size()
        if count < 2:
            raise ValueError("RealBasicVSR requires at least two neighboring frames.")
        flows_forward, flows_backward = self.compute_flow(frames)
        outputs: list[Tensor] = []
        feature = frames.new_zeros(batch, self.mid_channels, height, width)
        for index in range(count - 1, -1, -1):
            if index < count - 1:
                feature = flow_warp(
                    feature, flows_backward[:, index].permute(0, 2, 3, 1)
                )
            feature = self.backward_resblocks(torch.cat((frames[:, index], feature), dim=1))
            outputs.append(feature)
        outputs.reverse()

        feature = torch.zeros_like(feature)
        for index in range(count):
            current = frames[:, index]
            if index > 0:
                feature = flow_warp(
                    feature, flows_forward[:, index - 1].permute(0, 2, 3, 1)
                )
            feature = self.forward_resblocks(torch.cat((current, feature), dim=1))
            output = self.lrelu(self.fusion(torch.cat((outputs[index], feature), dim=1)))
            output = self.lrelu(self.upsample1(output))
            output = self.lrelu(self.upsample2(output))
            output = self.conv_last(self.lrelu(self.conv_hr(output)))
            outputs[index] = output + self.img_upsample(current)
        return torch.stack(outputs, dim=1)


class RealBasicVSRNet(nn.Module):
    """Checkpoint-compatible RealBasicVSR x4 generator."""

    def __init__(self, sequential_cleaning: bool = True) -> None:
        super().__init__()
        self.dynamic_refine_thres = 1.0
        self.sequential_cleaning = sequential_cleaning
        self.image_cleaning = nn.Sequential(
            ResidualBlocksWithInputConv(3, 64, 20),
            nn.Conv2d(64, 3, 3, 1, 1, bias=True),
        )
        self.basicvsr = BasicVSRNet(64, 20)

    def forward(self, frames: Tensor) -> Tensor:
        batch, count, channels, height, width = frames.size()
        for _ in range(3):
            if self.sequential_cleaning:
                residues = []
                for index in range(count):
                    residue = self.image_cleaning(frames[:, index])
                    frames[:, index] += residue
                    residues.append(residue)
                stacked = torch.stack(residues, dim=1)
            else:
                flattened = frames.view(-1, channels, height, width)
                stacked = self.image_cleaning(flattened)
                frames = (flattened + stacked).view(batch, count, channels, height, width)
            if torch.mean(torch.abs(stacked)) < self.dynamic_refine_thres:
                break
        return self.basicvsr(frames)

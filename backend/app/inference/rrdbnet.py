from torch import Tensor, cat, nn
from torch.nn import functional as F


class ResidualDenseBlock(nn.Module):
    def __init__(self, features: int = 64, growth: int = 32):
        super().__init__()
        self.conv1 = nn.Conv2d(features, growth, 3, 1, 1)
        self.conv2 = nn.Conv2d(features + growth, growth, 3, 1, 1)
        self.conv3 = nn.Conv2d(features + growth * 2, growth, 3, 1, 1)
        self.conv4 = nn.Conv2d(features + growth * 3, growth, 3, 1, 1)
        self.conv5 = nn.Conv2d(features + growth * 4, features, 3, 1, 1)
        self.activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: Tensor) -> Tensor:
        x1 = self.activation(self.conv1(x))
        x2 = self.activation(self.conv2(cat((x, x1), 1)))
        x3 = self.activation(self.conv3(cat((x, x1, x2), 1)))
        x4 = self.activation(self.conv4(cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, features: int = 64, growth: int = 32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(features, growth)
        self.rdb2 = ResidualDenseBlock(features, growth)
        self.rdb3 = ResidualDenseBlock(features, growth)

    def forward(self, x: Tensor) -> Tensor:
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, scale: int = 2, num_blocks: int = 23):
        super().__init__()
        features = 64
        self.scale = scale
        input_channels = 12 if scale == 2 else 3
        self.conv_first = nn.Conv2d(input_channels, features, 3, 1, 1)
        self.body = nn.Sequential(*(RRDB(features, 32) for _ in range(num_blocks)))
        self.conv_body = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_hr = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_last = nn.Conv2d(features, 3, 3, 1, 1)
        self.activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: Tensor) -> Tensor:
        if self.scale == 2:
            x = F.pixel_unshuffle(x, downscale_factor=2)
        feat = self.conv_first(x)
        body = self.conv_body(self.body(feat)) + feat
        out = self.activation(self.conv_up1(F.interpolate(body, scale_factor=2, mode="nearest")))
        out = self.activation(self.conv_up2(F.interpolate(out, scale_factor=2, mode="nearest")))
        return self.conv_last(self.activation(self.conv_hr(out)))

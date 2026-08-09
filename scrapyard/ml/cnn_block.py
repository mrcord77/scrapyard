"""
cnn_block — Reusable torch convolutional building blocks: ConvBlock (conv-norm-act-pool), ResidualBlock with automatic shortcut projection, and a make_cnn() stacker.

### PART-META-JSON
{
  "name": "cnn_block",
  "layer": "ml",
  "purpose": "Composable CNN building blocks for rapid prototyping: ConvBlock bundles Conv2d + optional BatchNorm + activation + optional MaxPool with same-padding defaults; ResidualBlock implements a 2-conv residual unit that auto-projects the shortcut when channels/stride change; make_cnn(channels=[...]) stacks ConvBlocks into a feature extractor. All blocks are ordinary nn.Modules usable inside any torch model.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "torch"
  ],
  "inputs": "ConvBlock(in_ch, out_ch, kernel_size=3, stride=1, norm=True, activation='relu', pool=None); ResidualBlock(in_ch, out_ch, stride=1); make_cnn([3, 16, 32], pool=2).",
  "outputs": "nn.Module instances producing (N, out_ch, H', W') feature maps; make_cnn returns nn.Sequential.",
  "files_created": [],
  "security_notes": "Pure torch computation - no I/O, network, or serialization. Shape errors surface as standard torch RuntimeErrors; the blocks validate activation names and channel counts up front so misconfiguration fails at construction, not mid-training.",
  "ai_usage": "backbone = make_cnn([3, 16, 32], pool=2); feats = backbone(images); or embed ResidualBlock(64, 128, stride=2) in a custom net.",
  "example": "from scrapyard.ml.cnn_block import ConvBlock, ResidualBlock, make_cnn",
  "import_path": "scrapyard.ml.cnn_block"
}
### END-PART-META
"""
from typing import List, Optional

import torch
from torch import nn

_ACTIVATIONS = {
    "relu": nn.ReLU,
    "gelu": nn.GELU,
    "leaky_relu": nn.LeakyReLU,
    "silu": nn.SiLU,
    "tanh": nn.Tanh,
    "none": nn.Identity,
}


def _make_activation(name: str) -> nn.Module:
    try:
        return _ACTIVATIONS[name]()
    except KeyError:
        raise ValueError(f"Unknown activation '{name}'. "
                         f"Choose from {sorted(_ACTIVATIONS)}")


class ConvBlock(nn.Module):
    """Conv2d -> (BatchNorm2d) -> activation -> (MaxPool2d), same-padding."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int = 3,
                 stride: int = 1, norm: bool = True, activation: str = "relu",
                 pool: Optional[int] = None):
        super().__init__()
        if in_channels < 1 or out_channels < 1:
            raise ValueError("channel counts must be >= 1")
        padding = kernel_size // 2
        layers: List[nn.Module] = [
            nn.Conv2d(in_channels, out_channels, kernel_size,
                      stride=stride, padding=padding, bias=not norm)]
        if norm:
            layers.append(nn.BatchNorm2d(out_channels))
        layers.append(_make_activation(activation))
        if pool:
            layers.append(nn.MaxPool2d(pool))
        self.block = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class ResidualBlock(nn.Module):
    """Two 3x3 conv-bn units with a residual shortcut; the shortcut is
    auto-projected (1x1 conv) when shape changes (channels or stride)."""

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1,
                 activation: str = "relu"):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, stride=stride,
                               padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.act = _make_activation(activation)
        if stride != 1 or in_channels != out_channels:
            self.shortcut: nn.Module = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 1, stride=stride, bias=False),
                nn.BatchNorm2d(out_channels))
        else:
            self.shortcut = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.act(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return self.act(out + self.shortcut(x))


def make_cnn(channels: List[int], kernel_size: int = 3, pool: Optional[int] = None,
             activation: str = "relu", norm: bool = True) -> nn.Sequential:
    """Stack ConvBlocks along a channel progression, e.g. [3, 16, 32, 64]."""
    if len(channels) < 2:
        raise ValueError("channels needs at least [in, out]")
    blocks = [ConvBlock(channels[i], channels[i + 1], kernel_size=kernel_size,
                        pool=pool, activation=activation, norm=norm)
              for i in range(len(channels) - 1)]
    return nn.Sequential(*blocks)


def _selftest():
    torch.manual_seed(0)
    x = torch.randn(2, 3, 16, 16)

    # ConvBlock keeps spatial dims with same-padding, changes channels
    blk = ConvBlock(3, 8)
    y = blk(x)
    assert y.shape == (2, 8, 16, 16), y.shape

    # pooling halves spatial dims
    blk_p = ConvBlock(3, 8, pool=2)
    assert blk_p(x).shape == (2, 8, 8, 8)

    # stride-2 conv halves dims without pool
    assert ConvBlock(3, 8, stride=2)(x).shape == (2, 8, 8, 8)

    # no-norm variant uses bias and still runs
    blk_nb = ConvBlock(3, 8, norm=False, activation="gelu")
    assert blk_nb(x).shape == (2, 8, 16, 16)
    assert blk_nb.block[0].bias is not None

    # ResidualBlock identity shortcut: same channels/stride
    res_same = ResidualBlock(3, 3)
    assert isinstance(res_same.shortcut, nn.Identity)
    assert res_same(x).shape == (2, 3, 16, 16)

    # projected shortcut on channel/stride change
    res_proj = ResidualBlock(3, 16, stride=2)
    assert not isinstance(res_proj.shortcut, nn.Identity)
    assert res_proj(x).shape == (2, 16, 8, 8)

    # residual path actually contributes (output != plain conv path)
    with torch.no_grad():
        res_same.eval()
        plain = res_same.act(res_same.bn2(res_same.conv2(
            res_same.act(res_same.bn1(res_same.conv1(x))))))
        withres = res_same(x)
    assert not torch.allclose(plain, withres), "shortcut must affect the output"

    # make_cnn stacks blocks; gradients flow end to end
    net = make_cnn([3, 8, 16], pool=2)
    out = net(x)
    assert out.shape == (2, 16, 4, 4)
    out.sum().backward()
    g = net[0].block[0].weight.grad
    assert g is not None and float(g.abs().sum()) > 0

    # validation errors
    for bad in (lambda: ConvBlock(0, 8), lambda: ConvBlock(3, 8, activation="warp"),
                lambda: make_cnn([3])):
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    print("cnn_block selftest passed")


if __name__ == "__main__":
    _selftest()

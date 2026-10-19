"""Model: timm backbone + two linear heads, and the probability wrapper (SPEC-012 section 4.1).

Requires the ``train`` extra (torch, timm). ADR-005: one backbone, a ``type`` head (``T``
classes, ``other`` included) and a ``grade`` head (5 logits with cross-entropy, 4 with CORN).
``ProbabilityWrapper`` turns the logits into probabilities inside the graph, so the ONNX model
always outputs ``type_probs [N, T]`` and ``grade_probs [N, 5]`` whatever the loss was.
"""

from __future__ import annotations

from typing import Literal

import timm
import torch
from torch import nn

N_GRADES = 5
GradeHead = Literal["ce", "corn"]


def corn_probabilities(logits: torch.Tensor) -> torch.Tensor:
    """CORN logits ``[N, 4]`` -> class probabilities ``[N, 5]``.

    ``s = sigmoid(logits)`` are the conditional probabilities ``P(y > k | y > k - 1)``; their
    cumulative product ``c`` is ``P(y > k)``; then ``p = [1 - c0, c0 - c1, c1 - c2, c2 - c3,
    c3]``. The cumulative product is written out (no ``cumprod``), which every ONNX opset
    supports; ``c`` never increases, so no probability is negative.
    """
    s = torch.sigmoid(logits)
    cumulative = [s[:, 0:1]]
    for k in range(1, s.shape[1]):
        cumulative.append(cumulative[-1] * s[:, k : k + 1])
    c = torch.cat(cumulative, dim=1)
    first = 1.0 - c[:, 0:1]
    middle = c[:, :-1] - c[:, 1:]
    last = c[:, -1:]
    return torch.cat([first, middle, last], dim=1)


class PartQCNet(nn.Module):
    """``forward(x) -> (type_logits [N, T], grade_logits [N, 5 or 4])``."""

    def __init__(self, backbone: nn.Module, n_features: int, n_types: int, grade_head: GradeHead):
        super().__init__()
        if grade_head not in ("ce", "corn"):
            raise ValueError(f"grade_head must be 'ce' or 'corn', got {grade_head!r}")
        if n_types < 2:
            raise ValueError("n_types must be >= 2 (other included)")
        self.backbone = backbone
        self.grade_head_kind: GradeHead = grade_head
        self.type_head = nn.Linear(n_features, n_types)
        self.grade_head = nn.Linear(n_features, N_GRADES - 1 if grade_head == "corn" else N_GRADES)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        return self.type_head(features), self.grade_head(features)


def build_model(backbone: str, n_types: int, grade_head: GradeHead, pretrained: bool) -> PartQCNet:
    """``timm.create_model(backbone, pretrained=pretrained, num_classes=0)`` + the two heads.

    ``pretrained=True`` downloads the ImageNet weights (Colab); the tests use ``False``.
    """
    body = timm.create_model(backbone, pretrained=pretrained, num_classes=0)
    n_features = getattr(body, "head_hidden_size", None) or body.num_features
    return PartQCNet(body, int(n_features), n_types, grade_head)


class ProbabilityWrapper(nn.Module):
    """``forward(image) -> (type_probs, grade_probs)``; this is the module exported to ONNX.

    Softmax on both heads; with CORN, ``corn_probabilities`` on the grade head. The kind of the
    grade head is read from ``model.grade_head_kind`` (``"ce"`` when absent).
    """

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model
        self.grade_head_kind: str = getattr(model, "grade_head_kind", "ce")

    def forward(self, image: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        type_logits, grade_logits = self.model(image)
        type_probs = torch.softmax(type_logits, dim=1)
        if self.grade_head_kind == "corn":
            grade_probs = corn_probabilities(grade_logits)
        else:
            grade_probs = torch.softmax(grade_logits, dim=1)
        return type_probs, grade_probs


def set_trainable(model: PartQCNet, unfreeze_last_blocks: int | None) -> list[nn.Module]:
    """Freeze the backbone and unfreeze its last ``unfreeze_last_blocks`` stages (phase B).

    ``None`` or ``0`` keeps the whole backbone frozen (phase A). The heads are always trainable.
    With ``n > 0``, the last ``n`` stages of ``backbone.blocks`` and every child of the backbone
    registered after ``blocks`` (``conv_head`` etc.) are unfrozen. Returns the backbone modules
    that stay frozen, which the training loop keeps in ``eval()`` (BatchNorm statistics frozen).

    Raises:
        ValueError: the backbone has no ``blocks`` (not a timm MobileNetV3/EfficientNet).
    """
    body = model.backbone
    for p in body.parameters():
        p.requires_grad_(False)
    for head in (model.type_head, model.grade_head):
        for p in head.parameters():
            p.requires_grad_(True)
    children = list(body.named_children())
    if not unfreeze_last_blocks:
        return [module for _, module in children]
    blocks = getattr(body, "blocks", None)
    if not isinstance(blocks, nn.Sequential):
        raise ValueError("the backbone has no 'blocks' sequence: cannot unfreeze its last stages")
    n = min(unfreeze_last_blocks, len(blocks))
    trainable: list[nn.Module] = list(blocks[len(blocks) - n :])
    names = [name for name, _ in children]
    trainable += [module for _, module in children[names.index("blocks") + 1 :]]
    for module in trainable:
        for p in module.parameters():
            p.requires_grad_(True)
    trainable_ids = {id(m) for m in trainable}
    frozen = [module for name, module in children if name != "blocks"]
    frozen = [m for m in frozen if id(m) not in trainable_ids]
    frozen += [stage for stage in blocks[: len(blocks) - n]]
    return frozen

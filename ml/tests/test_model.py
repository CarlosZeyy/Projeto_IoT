"""Author tests for qc_ml.model and the loss of qc_ml.train (SPEC-012 §4.1-4.2; CA-01..03).

Need torch (extra ``train``); skipped in the CI.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("timm")

import torch.nn.functional as F  # noqa: E402

from qc_ml.model import (  # noqa: E402
    ProbabilityWrapper,
    build_model,
    corn_probabilities,
    set_trainable,
)
from qc_ml.train import compute_loss  # noqa: E402


@pytest.fixture(scope="module")
def ce_model():
    torch.manual_seed(0)
    return build_model("mobilenetv3_large_100", 3, "ce", pretrained=False).eval()


def test_ca01_shapes_and_probabilities(ce_model) -> None:
    x = torch.randn(2, 3, 224, 224)
    with torch.no_grad():
        type_logits, grade_logits = ce_model(x)
        assert tuple(type_logits.shape) == (2, 3) and tuple(grade_logits.shape) == (2, 5)
        type_probs, grade_probs = ProbabilityWrapper(ce_model).eval()(x)
    for probs in (type_probs, grade_probs):
        assert torch.allclose(probs.sum(dim=1), torch.ones(2), atol=1e-5)
        assert bool((probs >= 0).all())


def test_ca01_corn_head() -> None:
    torch.manual_seed(0)
    model = build_model("mobilenetv3_large_100", 3, "corn", pretrained=False).eval()
    x = torch.randn(2, 3, 224, 224)
    with torch.no_grad():
        type_logits, grade_logits = model(x)
        assert tuple(type_logits.shape) == (2, 3) and tuple(grade_logits.shape) == (2, 4)
        _, grade_probs = ProbabilityWrapper(model).eval()(x)
    assert tuple(grade_probs.shape) == (2, 5)
    assert torch.allclose(grade_probs.sum(dim=1), torch.ones(2), atol=1e-5)
    assert bool((grade_probs >= 0).all())


def test_ca02_corn_probabilities_of_zero_logits() -> None:
    probs = corn_probabilities(torch.zeros(1, 4, dtype=torch.float64))
    expected = torch.tensor([[0.5, 0.25, 0.125, 0.0625, 0.0625]], dtype=torch.float64)
    assert torch.allclose(probs, expected, atol=1e-6)


def test_corn_probabilities_never_negative() -> None:
    logits = torch.randn(1000, 4) * 20
    probs = corn_probabilities(logits)
    assert bool((probs >= 0).all())
    assert torch.allclose(probs.sum(dim=1), torch.ones(1000), atol=1e-5)


def test_efficientnet_backbone_builds() -> None:
    model = build_model("efficientnet_b0", 3, "ce", pretrained=False).eval()
    with torch.no_grad():
        type_logits, grade_logits = model(torch.zeros(1, 3, 224, 224))
    assert tuple(type_logits.shape) == (1, 3) and tuple(grade_logits.shape) == (1, 5)


def test_ca03_loss_without_any_grade_is_the_type_ce() -> None:
    torch.manual_seed(1)
    type_logits, grade_logits = torch.randn(4, 3), torch.randn(4, 5)
    type_idx = torch.tensor([2, 2, 0, 1])
    grade_idx = torch.full((4,), -1)
    parts = compute_loss(type_logits, grade_logits, type_idx, grade_idx)
    expected = F.cross_entropy(type_logits, type_idx, label_smoothing=0.1)
    assert torch.isfinite(parts.total)
    assert torch.allclose(parts.total, expected)
    assert float(parts.grade_loss) == 0.0
    corn = compute_loss(type_logits, torch.randn(4, 4), type_idx, grade_idx, grade_head="corn")
    assert torch.allclose(corn.total, expected)


def test_ca03_mixed_batch_masks_the_grade_term() -> None:
    torch.manual_seed(2)
    type_logits, grade_logits = torch.randn(5, 3), torch.randn(5, 5)
    type_idx = torch.tensor([0, 1, 2, 0, 2])
    grade_idx = torch.tensor([3, 0, -1, 4, -1])
    weights = [1.0, 1.0, 1.0, 1.0, 2.0]
    parts = compute_loss(
        type_logits, grade_logits, type_idx, grade_idx, lambda_grade=0.5, grade_weights=weights
    )
    mask = grade_idx >= 0
    expected_grade = F.cross_entropy(
        grade_logits[mask], grade_idx[mask], weight=torch.tensor(weights), label_smoothing=0.1
    )
    assert torch.allclose(parts.grade_loss, expected_grade)
    expected_type = F.cross_entropy(type_logits, type_idx, label_smoothing=0.1)
    assert torch.allclose(parts.total, expected_type + 0.5 * expected_grade)


def test_corn_loss_uses_only_graded_rows() -> None:
    from coral_pytorch.losses import corn_loss

    torch.manual_seed(3)
    type_logits, grade_logits = torch.randn(4, 3), torch.randn(4, 4)
    grade_idx = torch.tensor([1, -1, 4, 0])
    parts = compute_loss(type_logits, grade_logits, torch.tensor([0, 2, 1, 0]), grade_idx,
                         grade_head="corn", grade_weights=[9.0] * 5)  # fmt: skip
    mask = grade_idx >= 0
    assert torch.allclose(parts.grade_loss, corn_loss(grade_logits[mask], grade_idx[mask], 5))


def test_set_trainable_phases(ce_model) -> None:
    frozen = set_trainable(ce_model, None)
    backbone_params = list(ce_model.backbone.parameters())
    assert not any(p.requires_grad for p in backbone_params)
    assert all(p.requires_grad for p in ce_model.type_head.parameters())
    assert len(frozen) == len(list(ce_model.backbone.children()))

    frozen = set_trainable(ce_model, 2)
    blocks = ce_model.backbone.blocks
    assert all(p.requires_grad for p in blocks[-1].parameters())
    assert all(p.requires_grad for p in blocks[-2].parameters())
    assert not any(p.requires_grad for p in blocks[-3].parameters())
    assert all(p.requires_grad for p in ce_model.backbone.conv_head.parameters())
    assert not any(p.requires_grad for p in ce_model.backbone.conv_stem.parameters())
    frozen_ids = {id(m) for m in frozen}
    assert id(ce_model.backbone.conv_stem) in frozen_ids and id(blocks[0]) in frozen_ids
    assert id(blocks[-1]) not in frozen_ids and id(ce_model.backbone.conv_head) not in frozen_ids

"""Training in two phases with a masked grade loss (SPEC-012 section 4.2; skill ml-pipeline §4).

Phase A: frozen backbone, AdamW with ``lr_a`` for ``epochs_a`` epochs. Phase B: the last
``unfreeze_last_blocks`` stages of ``backbone.blocks`` and everything after them are unfrozen,
AdamW with ``lr_b`` for up to ``epochs_b_max`` epochs, with early stopping on the validation
grade QWK. The best checkpoint is the epoch (A or B) with the highest validation grade QWK; a tie
goes to the lower validation loss and then to the earlier epoch. The test split is never read
here (R-11): the rows come only from ``split.rows_for(..., "train")`` and ``(..., "val")``.

The pure helpers (``TrainConfig``, ``grade_class_weights``, ``EarlyStopper``) work without torch,
so they can be tested in the CI; everything else needs the ``train`` extra.

CLI::

    python -m qc_ml.train --config ml/configs/partqc-mnv3-v1.json [--resume]
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import platform
import random
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

from qc_ml import split
from qc_ml.artifacts import TRAINING_CONFIG_FILE, labels_to_dict, write_json
from qc_ml.config import TrainConfig, load_config
from qc_ml.data import DEFAULT_LABELS, GRADES, configure_logging, load_manifest
from qc_ml.errors import ConfigError, TrainError
from qc_ml.evaluate import quadratic_weighted_kappa
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error

try:  # the CI has no torch: only the pure helpers of this module are usable there
    import torch
except ImportError:  # pragma: no cover - exercised by the import test without torch
    torch = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from torch import nn

__all__ = [
    "ConfigError",
    "EarlyStopper",
    "LossParts",
    "TrainConfig",
    "TrainError",
    "TrainResult",
    "compute_loss",
    "grade_class_weights",
    "load_config",
    "run",
    "set_seeds",
    "train",
]

logger = logging.getLogger(__name__)

WEIGHT_RATIO = 0.6  # skill ml-pipeline §4: weights when a grade has < 60% of the mean
UNDEFINED_QWK = -1.0  # SPEC-012 §4.2: an undefined QWK counts as -1 to pick the best epoch
LAST_CHECKPOINT = "last.pt"
BEST_CHECKPOINT = "best.pt"
VERSIONED_DISTRIBUTIONS: tuple[str, ...] = (
    "torch",
    "torchvision",
    "timm",
    "numpy",
    "scikit-learn",
    "onnx",
    "onnxruntime",
    "coral-pytorch",
    "qc-preprocess",
    "qc-ml",
)


# ---------------------------------------------------------------------------------------------
# Pure helpers (no torch)
# ---------------------------------------------------------------------------------------------


def grade_class_weights(counts: Mapping[str, int]) -> list[float] | None:
    """Class weights of the grade loss from the number of training images with each grade.

    ``mean = total / 5``; when some grade has ``count < 0.6 * mean``, returns
    ``mean / count_g`` for the 5 grades (in severity order); otherwise ``None``.

    Raises:
        TrainError: a grade with no training image (or missing, or a negative count), or an
            unknown grade.
    """
    unknown = sorted(set(counts) - set(GRADES))
    if unknown:
        raise TrainError(f"unknown grades in the counts: {', '.join(unknown)}")
    values = [int(counts.get(grade, 0)) for grade in GRADES]
    empty = [grade for grade, value in zip(GRADES, values, strict=True) if value <= 0]
    if empty:
        raise TrainError(
            f"no training image with grade {', '.join(empty)}: the grade head cannot learn it"
        )
    mean = sum(values) / len(GRADES)
    if not any(value < WEIGHT_RATIO * mean for value in values):
        return None
    return [mean / value for value in values]


@dataclass
class EarlyStopper:
    """Stop when the monitored value has not improved by more than ``min_delta`` for
    ``patience`` consecutive epochs.

    ``step(value)`` is called once per epoch (epochs numbered from 1) and returns ``True`` when
    training must stop. ``best_epoch`` is the epoch of the best value seen; ``None`` counts as
    ``-1`` (undefined QWK).
    """

    patience: int = 5
    min_delta: float = 1e-4
    best_value: float | None = None
    best_epoch: int | None = None
    epoch: int = 0
    bad_epochs: int = 0
    should_stop: bool = False

    def __post_init__(self) -> None:
        if self.patience < 1:
            raise ValueError("patience must be >= 1")
        if self.min_delta < 0:
            raise ValueError("min_delta must be >= 0")

    def step(self, value: float | None) -> bool:
        self.epoch += 1
        current = UNDEFINED_QWK if value is None or not math.isfinite(value) else float(value)
        if self.best_value is None or current > self.best_value + self.min_delta:
            self.best_value = current
            self.best_epoch = self.epoch
            self.bad_epochs = 0
        else:
            self.bad_epochs += 1
        self.should_stop = self.bad_epochs >= self.patience
        return self.should_stop

    __call__ = step

    def state_dict(self) -> dict[str, Any]:
        return {
            "patience": self.patience,
            "min_delta": self.min_delta,
            "best_value": self.best_value,
            "best_epoch": self.best_epoch,
            "epoch": self.epoch,
            "bad_epochs": self.bad_epochs,
            "should_stop": self.should_stop,
        }

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> EarlyStopper:
        return cls(**dict(state))


def qwk_key(value: float | None) -> float:
    """The value used to compare epochs: an undefined QWK counts as -1."""
    return UNDEFINED_QWK if value is None else value


def is_better(candidate: Mapping[str, Any], best: Mapping[str, Any] | None) -> bool:
    """Best epoch rule: higher ``val_grade_qwk``; tie -> lower ``val_loss``; tie -> earlier."""
    if best is None:
        return True
    a = (qwk_key(candidate["val_grade_qwk"]), -candidate["val_loss"], -candidate["epoch"])
    b = (qwk_key(best["val_grade_qwk"]), -best["val_loss"], -best["epoch"])
    return a > b


def library_versions() -> dict[str, str | None]:
    """Versions of Python and of each library of ``training_config.json`` (``None`` if absent)."""
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for name in VERSIONED_DISTRIBUTIONS:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def git_commit() -> str | None:
    """``git rev-parse HEAD`` of the working directory, or ``None`` outside a checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and len(commit) == 40 else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _require_torch() -> None:
    if torch is None:
        raise TrainError("training needs the train extra: uv sync --all-packages --extra train")


# ---------------------------------------------------------------------------------------------
# Torch helpers
# ---------------------------------------------------------------------------------------------


class LossParts(NamedTuple):
    total: Any  # torch.Tensor
    type_loss: Any
    grade_loss: Any


def compute_loss(
    type_logits: Any,
    grade_logits: Any,
    type_idx: Any,
    grade_idx: Any,
    *,
    grade_head: str = "ce",
    label_smoothing: float = 0.1,
    lambda_grade: float = 1.0,
    grade_weights: Any = None,
) -> LossParts:
    """``CE(type, label_smoothing) + lambda_grade * CE_masked(grade, label_smoothing, weight)``.

    The grade term uses only the rows with ``grade_idx >= 0``; without any such row it is ``0``
    (never ``NaN``). With ``grade_head="corn"`` the grade term is ``coral_pytorch``'s
    ``corn_loss`` on the same rows, without label smoothing nor weights.
    """
    _require_torch()
    import torch.nn.functional as functional

    type_loss = functional.cross_entropy(type_logits, type_idx, label_smoothing=label_smoothing)
    mask = grade_idx >= 0
    if not bool(mask.any()):
        grade_loss = type_logits.new_zeros(())
    elif grade_head == "corn":
        from coral_pytorch.losses import corn_loss

        grade_loss = corn_loss(grade_logits[mask], grade_idx[mask], num_classes=len(GRADES))
    else:
        weight = None
        if grade_weights is not None:
            weight = torch.as_tensor(
                grade_weights, dtype=grade_logits.dtype, device=grade_logits.device
            )
        grade_loss = functional.cross_entropy(
            grade_logits[mask], grade_idx[mask], weight=weight, label_smoothing=label_smoothing
        )
    return LossParts(type_loss + lambda_grade * grade_loss, type_loss, grade_loss)


def set_seeds(seed: int) -> None:
    """Seed ``random``, ``numpy`` and ``torch`` (CUDA too); deterministic algorithms (warn only)."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")  # deterministic cuBLAS
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.backends.cudnn.benchmark = False


def seed_worker(worker_id: int) -> None:
    """``worker_init_fn`` of the DataLoaders: derive ``numpy``/``random`` seeds from torch's."""
    worker_seed = torch.initial_seed() % 2**32
    np.random.seed(worker_seed)
    random.seed(worker_seed)


def epoch_generator(seed: int, epoch: int) -> Any:
    """Shuffling generator of one epoch: the same order with or without ``--resume``."""
    return torch.Generator().manual_seed(seed * 100_003 + epoch)


def _rng_state() -> dict[str, Any]:
    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }


def _set_rng_state(state: Mapping[str, Any]) -> None:
    python_state = state["python"]
    random.setstate((python_state[0], tuple(python_state[1]), python_state[2]))
    numpy_state = state["numpy"]
    np.random.set_state(
        (numpy_state[0], np.asarray(numpy_state[1], dtype=np.uint32), *numpy_state[2:])
    )
    torch.set_rng_state(state["torch"])
    if state["cuda"] and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def _atomic_save(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def _device_name(device: Any) -> str:
    if device.type == "cuda":
        return f"cuda ({torch.cuda.get_device_name(device)})"
    return str(device)


# ---------------------------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------------------------


@dataclass
class TrainResult:
    """The model with the weights of the best epoch (CPU, ``eval()``) and its record."""

    model: Any  # PartQCNet
    training_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class _State:
    history: list[dict[str, Any]] = field(default_factory=list)
    best: dict[str, Any] | None = None
    stopper: EarlyStopper | None = None
    stopped_early: bool = False
    last_epoch: int = 0
    last_phase: str | None = None
    optimizer: dict[str, Any] | None = None


def _run_epoch(
    model: nn.Module,
    loader: Any,
    device: Any,
    config: TrainConfig,
    weights: list[float] | None,
    optimizer: Any = None,
) -> tuple[float, float | None, float | None]:
    """One pass; trains when ``optimizer`` is given. Returns ``(loss, type_acc, grade_qwk)``."""
    from qc_ml.model import corn_probabilities

    training = optimizer is not None
    total_loss = 0.0
    n_seen = 0
    type_hits = 0
    true_grades: list[np.ndarray] = []
    pred_grades: list[np.ndarray] = []
    with torch.set_grad_enabled(training):
        for images, type_idx, grade_idx in loader:
            images = images.to(device, non_blocking=True)
            type_idx = type_idx.to(device)
            grade_idx = grade_idx.to(device)
            type_logits, grade_logits = model(images)
            loss = compute_loss(
                type_logits,
                grade_logits,
                type_idx,
                grade_idx,
                grade_head=config.grade_head,
                label_smoothing=config.label_smoothing,
                lambda_grade=config.lambda_grade,
                grade_weights=weights,
            ).total
            if training:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            batch = images.shape[0]
            total_loss += float(loss.detach()) * batch
            n_seen += batch
            if not training:
                type_hits += int((type_logits.argmax(dim=1) == type_idx).sum())
                if config.grade_head == "corn":
                    grade_probs = corn_probabilities(grade_logits)
                else:
                    grade_probs = torch.softmax(grade_logits, dim=1)
                mask = grade_idx >= 0
                true_grades.append(grade_idx[mask].cpu().numpy())
                pred_grades.append(grade_probs.argmax(dim=1)[mask].cpu().numpy())
    loss_mean = total_loss / n_seen if n_seen else float("nan")
    if training:
        return loss_mean, None, None
    accuracy = type_hits / n_seen if n_seen else None
    true = np.concatenate(true_grades) if true_grades else np.zeros(0, dtype=np.int64)
    pred = np.concatenate(pred_grades) if pred_grades else np.zeros(0, dtype=np.int64)
    return loss_mean, accuracy, quadratic_weighted_kappa(true, pred)


def _load_resume(config: TrainConfig) -> dict[str, Any]:
    path = config.checkpoints_dir / LAST_CHECKPOINT
    if not path.is_file():
        raise TrainError(f"nothing to resume: {path} does not exist")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("config") != config.to_dict():
        raise ConfigError(
            f"--resume needs the same configuration as {path}; start without --resume instead"
        )
    return checkpoint


def train(config: TrainConfig, *, resume: bool = False) -> TrainResult:
    """Train, keep the best epoch and write ``training_config.json`` in the model directory.

    Raises:
        TrainError: no torch, an empty split or a grade without training images.
        ConfigError: ``resume`` with a checkpoint of another configuration.
        ManifestError, SplitError: invalid dataset or split.
    """
    _require_torch()
    from torch.utils.data import DataLoader

    from qc_ml.dataset import PartsDataset
    from qc_ml.model import build_model, set_trainable
    from qc_preprocess import PreprocessParams

    started_at = _now()
    set_seeds(config.seed)
    df = load_manifest(config.dataset_dir)
    split_df = split.load_split(config.split_file)
    train_rows = split.rows_for(df, split_df, "train")
    val_rows = split.rows_for(df, split_df, "val")
    if train_rows.empty or val_rows.empty:
        raise TrainError("the train and val splits must both have images")
    labels = DEFAULT_LABELS
    counts = {grade: int((train_rows["grade"] == grade).sum()) for grade in GRADES}
    weights = grade_class_weights(counts)
    if config.grade_head == "corn":
        weights = None  # CORN: no class weights (SPEC-012 §4.2)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    params = PreprocessParams()
    train_ds = PartsDataset(
        train_rows, config.dataset_dir, labels, params, train=True, seed=config.seed
    )
    val_ds = PartsDataset(val_rows, config.dataset_dir, labels, params, train=False)
    model = build_model(
        config.backbone, len(labels.object_types), config.grade_head, config.pretrained
    ).to(device)

    state = _State()
    checkpoint: dict[str, Any] | None = None
    if resume:
        checkpoint = _load_resume(config)
        model.load_state_dict(checkpoint["model"])
        started_at = checkpoint["started_at"]
        state = _State(
            history=list(checkpoint["history"]),
            best=checkpoint["best"],
            stopper=(
                EarlyStopper.from_state(checkpoint["stopper"]) if checkpoint["stopper"] else None
            ),
            stopped_early=bool(checkpoint["stopped_early"]),
            last_epoch=int(checkpoint["epoch"]),
            last_phase=checkpoint["phase"],
            optimizer=checkpoint["optimizer"],
        )
        _set_rng_state(checkpoint["rng"])
        logger.info("resuming after epoch %d (phase %s)", state.last_epoch, state.last_phase)

    loader_options: dict[str, Any] = {
        "batch_size": config.batch_size,
        "num_workers": config.num_workers,
        "worker_init_fn": seed_worker,
        "pin_memory": device.type == "cuda",
    }
    val_loader = DataLoader(val_ds, shuffle=False, **loader_options)
    checkpoints_dir = config.checkpoints_dir
    total_epochs = config.epochs_a + config.epochs_b_max
    phase_now: str | None = None
    frozen: list[nn.Module] = []
    optimizer: Any = None
    for epoch in range(state.last_epoch + 1, total_epochs + 1):
        if state.stopped_early:
            break
        phase = "A" if epoch <= config.epochs_a else "B"
        if phase != phase_now:
            frozen = set_trainable(model, None if phase == "A" else config.unfreeze_last_blocks)
            lr = config.lr_a if phase == "A" else config.lr_b
            optimizer = torch.optim.AdamW(
                [p for p in model.parameters() if p.requires_grad],
                lr=lr,
                weight_decay=config.weight_decay,
            )
            if state.optimizer is not None and state.last_phase == phase:
                optimizer.load_state_dict(state.optimizer)  # resumed in the middle of a phase
            state.optimizer = None
            if phase == "B" and (state.stopper is None or state.last_phase != "B"):
                state.stopper = EarlyStopper(config.patience, config.min_delta)
            phase_now = phase
            logger.info("phase %s from epoch %d (lr %g)", phase, epoch, lr)

        train_ds.set_epoch(epoch)
        model.train()
        for module in frozen:
            module.eval()  # frozen stages keep their BatchNorm statistics
        train_loader = DataLoader(
            train_ds,
            shuffle=True,
            generator=epoch_generator(config.seed, epoch),
            **loader_options,
        )
        train_loss, _, _ = _run_epoch(model, train_loader, device, config, weights, optimizer)
        model.eval()
        val_loss, val_accuracy, val_qwk = _run_epoch(model, val_loader, device, config, weights)
        entry = {
            "epoch": epoch,
            "phase": phase,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_type_accuracy": val_accuracy,
            "val_grade_qwk": val_qwk,
        }
        state.history.append(entry)
        logger.info("epoch %d (%s): %s", epoch, phase, entry)
        if is_better(entry, state.best):
            state.best = {k: entry[k] for k in ("epoch", "phase", "val_grade_qwk", "val_loss")}
            _atomic_save(
                {"model": model.state_dict(), "best": state.best},
                checkpoints_dir / BEST_CHECKPOINT,
            )
        if phase == "B" and state.stopper is not None:
            state.stopped_early = state.stopper.step(val_qwk)
        _atomic_save(
            {
                "config": config.to_dict(),
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "epoch": epoch,
                "phase": phase,
                "history": state.history,
                "best": state.best,
                "stopper": state.stopper.state_dict() if state.stopper else None,
                "stopped_early": state.stopped_early,
                "started_at": started_at,
                "rng": _rng_state(),
            },
            checkpoints_dir / LAST_CHECKPOINT,
        )
        if state.stopped_early:
            logger.info("early stop after epoch %d", epoch)

    if state.best is None:
        raise TrainError("no epoch was trained")
    best_checkpoint = torch.load(
        checkpoints_dir / BEST_CHECKPOINT, map_location="cpu", weights_only=True
    )
    model = model.cpu()
    model.load_state_dict(best_checkpoint["model"])
    model.eval()

    record = {
        "model_version": config.model_version,
        "config": config.to_dict(),
        "deviations_from_defaults": config.deviations_from_defaults,
        "labels": labels_to_dict(labels),
        "split_file": split_df.attrs.get("split_file"),
        "split_sha256": split_df.attrs.get("split_sha256"),
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        "grade_class_weights": weights,
        "history": state.history,
        "best_epoch": state.best["epoch"],
        "best_val_grade_qwk": state.best["val_grade_qwk"],
        "stopped_early": state.stopped_early,
        "versions": library_versions(),
        "device": _device_name(device),
        "git_commit": git_commit(),
        "started_at": started_at,
        "finished_at": _now(),
        "smoke": config.smoke,
    }
    write_json(config.model_dir / TRAINING_CONFIG_FILE, record)
    logger.info(
        "best epoch %s (val_grade_qwk %s); %s written",
        record["best_epoch"],
        record["best_val_grade_qwk"],
        config.model_dir / TRAINING_CONFIG_FILE,
    )
    return TrainResult(model=model, training_config=record)


def run(config: TrainConfig, *, resume: bool = False) -> TrainResult:
    return train(config, resume=resume)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.train", description="Train the model (train/val splits only)."
    )
    parser.add_argument("--config", required=True, help="ml/configs/<model_version>.json")
    parser.add_argument("--resume", action="store_true", help="continue from last.pt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when ``training_config.json`` was written, 2 on any error."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        run(load_config(args.config), resume=args.resume)
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error("train", exc)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

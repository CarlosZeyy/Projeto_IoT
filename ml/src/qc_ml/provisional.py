"""Provisional model, only to rehearse the flow (SPEC-041 sections 4.2 to 4.4, ADR-024).

Trains on external images only, whose grades are agent suggestions (``labeler`` =
``agent-suggestion``), and writes a model directory that the edge can load. Its inspections are
published as ``source=simulated`` (the name of the version decides, section 4.1).

There is no split, no validation and no test here (R-11 stays intact: no own photo enters this
set), so **no quality metric of this model exists**: only phase A of ``qc_ml.train``, with the
last epoch as the model, and fixed thresholds. Nothing here calls ``qc_ml.split.load_split``,
``rows_for``, ``make_split``, ``qc_ml.thresholds`` or ``qc_ml.evaluate``, and nothing reads or
writes ``split_v*``, ``metrics.json``, the CHANGELOG or a Release.

Torch is imported only inside the function that trains; this module works without it up to the
refusal ``training needs the train extra``.

CLI::

    python -m qc_ml.provisional --dataset-dir <D> --models-root <M> \
        [--external-sources <R>] [--model-version partqc-mnv3-provisional-v1] \
        [--epochs 8] [--seed 42] [--smoke]
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from qc_ml.artifacts import DECISION_FILE, write_json
from qc_ml.config import (
    CONTRACT_VERSION_PATTERN,
    EPOCHS_A_RANGE,
    SKILL_DEFAULTS,
    VERSION_NAME_PATTERN,
    is_provisional_version,
)
from qc_ml.data import (
    AGENT_SUGGESTION_LABELER,
    NO_GRADE,
    OVERRIDE_COLUMNS,
    OVERRIDES_FILE,
    ModelLabels,
    configure_logging,
    is_external_item,
    load_manifest,
    parse_csv,
    print_problems,
)
from qc_ml.decision import Thresholds, write_decision
from qc_ml.errors import ManifestError, TrainError
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error
from qc_ml.train import (
    compute_loss,
    epoch_generator,
    git_commit,
    grade_class_weights,
    graded_training_counts,
    library_versions,
    model_labels_for,
    require_torch,
    seed_worker,
    set_seeds,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_VERSION = "partqc-mnv3-provisional-v1"
REPORT_FILE = "provisional_report.json"
GIT_ENTRY_NAME = ".git"  # the rule of qc_edge.importer.inside_git_repository
BACKBONE = "mobilenetv3_large_100"  # N-01
SMOKE_BACKBONE = "mobilenetv3_small_050"
GRADE_HEAD = "ce"
DEFAULT_EPOCHS = 8
SMOKE_EPOCHS = 1
NUM_WORKERS = 2
SMOKE_NUM_WORKERS = 0
REQUIRED_TYPES: tuple[str, ...] = ("screw", "nut", "other")
# Section 4.2: there is no validation to choose them from.
FIXED_THRESHOLDS = Thresholds(
    type_threshold=0.50, unusable_threshold=0.50, grade_review_threshold=0.60
)
DECISION_SOURCE = "fixed_defaults"
NOTICE = (
    "Provisional model for rehearsal only (ADR-024). Grades are agent suggestions, not human "
    "labels. No validation or test split; no quality metric exists for this model."
)

NOT_PROVISIONAL = "not a provisional model version"
PATHS_IN_GIT = "provisional paths must be outside a Git repository"
MODEL_DIR_EXISTS = "model directory already exists"
OWN_IMAGES = "provisional dataset has own images: "
OTHER_LABELERS = "provisional dataset has other labelers: "
OTHER_TYPES = "provisional dataset has other types: "
NEEDS_TYPES = "provisional dataset needs the types: "


class ProvisionalRefusal(Exception):
    """A refusal of section 4.3; the message goes alone to the stderr (exit 2)."""


def inside_git_repository(path: Path) -> bool:
    """Whether ``path`` or a directory above it, up to the root, has a ``.git`` entry.

    The same rule of ``qc_edge.importer.inside_git_repository`` (``qc_ml`` does not import
    ``qc_edge``): the entry may be a directory or a file (a worktree). The caller resolves
    ``path`` first.
    """
    return any(os.path.lexists(directory / GIT_ENTRY_NAME) for directory in (path, *path.parents))


def _check_version(model_version: str) -> None:
    if not (
        is_provisional_version(model_version)
        and VERSION_NAME_PATTERN.fullmatch(model_version)
        and CONTRACT_VERSION_PATTERN.fullmatch(model_version)
    ):
        raise ProvisionalRefusal(NOT_PROVISIONAL)


def _check_model_dir(model_dir: Path) -> None:
    """An existing and non-empty directory is refused; so is a file or a symbolic link there."""
    if not os.path.lexists(model_dir):
        return
    if model_dir.is_symlink() or not model_dir.is_dir() or any(model_dir.iterdir()):
        raise ProvisionalRefusal(MODEL_DIR_EXISTS)


def _override_rows_of_other_labelers(df: pd.DataFrame, dataset_dir: Path) -> int:
    """Lines of ``labels_overrides.csv`` of non-excluded images with another ``labeler``.

    ``load_manifest`` has already validated the file; it keeps no ``labeler`` of an override in
    the ``DataFrame`` (SPEC-041 section 4.3).
    """
    path = dataset_dir / OVERRIDES_FILE
    if not path.is_file():
        return 0
    excluded = df.attrs["excluded_items"]
    table = parse_csv(path.read_bytes(), OVERRIDES_FILE, OVERRIDE_COLUMNS)
    return sum(
        1
        for _, row in table.rows
        if row["image_path"] not in excluded and row["labeler"] != AGENT_SUGGESTION_LABELER
    )


def _check_dataset(df: pd.DataFrame, dataset_dir: Path) -> None:
    """The dataset refusals of section 4.3, in its order, from own images to the missing types."""
    own_images = sum(1 for item_id in df["item_id"] if not is_external_item(str(item_id)))
    if own_images:
        raise ProvisionalRefusal(f"{OWN_IMAGES}{own_images}")
    other_labelers = int((df["labeler"] != AGENT_SUGGESTION_LABELER).sum())
    other_labelers += _override_rows_of_other_labelers(df, dataset_dir)
    if other_labelers:
        raise ProvisionalRefusal(f"{OTHER_LABELERS}{other_labelers}")
    present = {str(object_type) for object_type in df["object_type"]}
    other_types = sorted(present - set(REQUIRED_TYPES))
    if other_types:
        raise ProvisionalRefusal(f"{OTHER_TYPES}{', '.join(other_types)}")
    missing_types = [t for t in REQUIRED_TYPES if t not in present]
    if missing_types:
        raise ProvisionalRefusal(f"{NEEDS_TYPES}{', '.join(missing_types)}")


def train_model(
    df: pd.DataFrame,
    dataset_dir: Path,
    labels: ModelLabels,
    weights: list[float] | None,
    *,
    epochs: int,
    seed: int,
    smoke: bool,
) -> tuple[Any, list[float]]:
    """Phase A of ``qc_ml.train`` over every row of ``df``: ``(model, train loss by epoch)``.

    The backbone stays frozen, with its BatchNorm statistics, and the model is the one of the
    last epoch (no validation, no early stopping, no checkpoints). The model comes back on the
    CPU, in ``eval()``.

    Raises:
        TrainError: no torch.
    """
    require_torch()
    import torch
    from torch.utils.data import DataLoader

    from qc_ml.dataset import PartsDataset
    from qc_ml.model import build_model, set_trainable
    from qc_preprocess import PreprocessParams

    set_seeds(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dataset = PartsDataset(df, dataset_dir, labels, PreprocessParams(), train=True, seed=seed)
    model = build_model(
        SMOKE_BACKBONE if smoke else BACKBONE, len(labels.object_types), GRADE_HEAD, not smoke
    ).to(device)
    frozen = set_trainable(model, None)
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=SKILL_DEFAULTS["lr_a"],
        weight_decay=SKILL_DEFAULTS["weight_decay"],
    )
    losses: list[float] = []
    for epoch in range(1, epochs + 1):
        dataset.set_epoch(epoch)
        model.train()
        for module in frozen:
            module.eval()
        loader = DataLoader(
            dataset,
            shuffle=True,
            generator=epoch_generator(seed, epoch),
            batch_size=SKILL_DEFAULTS["batch_size"],
            num_workers=SMOKE_NUM_WORKERS if smoke else NUM_WORKERS,
            worker_init_fn=seed_worker,
            pin_memory=device.type == "cuda",
        )
        total_loss = 0.0
        for images, type_idx, grade_idx in loader:
            images = images.to(device, non_blocking=True)
            type_logits, grade_logits = model(images)
            loss = compute_loss(
                type_logits,
                grade_logits,
                type_idx.to(device),
                grade_idx.to(device),
                grade_head=GRADE_HEAD,
                label_smoothing=SKILL_DEFAULTS["label_smoothing"],
                lambda_grade=SKILL_DEFAULTS["lambda_grade"],
                grade_weights=weights,
            ).total
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * images.shape[0]
        losses.append(total_loss / len(dataset))
        logger.info("epoch %d: train_loss %s", epoch, losses[-1])
    return model.cpu().eval(), losses


def _images_by_type_grade(df: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Type -> grade (or ``none``) -> number of images."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for object_type, grade in zip(df["object_type"], df["grade"], strict=True):
        counts[str(object_type)][NO_GRADE if grade is None else str(grade)] += 1
    return {
        object_type: dict(sorted(counts[object_type].items())) for object_type in sorted(counts)
    }


def build_report(
    df: pd.DataFrame,
    *,
    model_version: str,
    model_sha256: str,
    epochs: int,
    seed: int,
    smoke: bool,
    losses: Sequence[float],
) -> dict[str, Any]:
    """``provisional_report.json`` (section 4.4): counts and the training loss, never a metric."""
    by_source = Counter(str(source) for source in df["source_id"] if source is not None)
    return {
        "model_version": model_version,
        "model_sha256": model_sha256,
        "provisional": True,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "manifest_sha256": df.attrs["manifest_sha256"],
        "n_images": len(df),
        "n_items": int(df["item_id"].nunique()),
        "images_by_type_grade": _images_by_type_grade(df),
        "by_source": dict(sorted(by_source.items())),
        "epochs": epochs,
        "seed": seed,
        "smoke": smoke,
        "train_loss_by_epoch": list(losses),
        "decision_source": DECISION_SOURCE,
        "versions": library_versions(),
        "git_commit": git_commit(),
        "notice": NOTICE,
    }


def _write_model_dir(
    model: Any,
    model_dir: Path,
    labels: ModelLabels,
    report_fields: dict[str, Any],
    df: pd.DataFrame,
) -> str:
    """Write the 7 files of section 4.2; on any error, delete what was written.

    The directories created above ``model_dir`` also go, so that a failure leaves nothing.
    """
    from qc_ml.export import write_model_dir

    created_parents = [p for p in model_dir.parents if not os.path.lexists(p)]
    try:
        digest = write_model_dir(model, model_dir, labels)  # with the parity check
        write_decision(model_dir / DECISION_FILE, FIXED_THRESHOLDS)
        write_json(
            model_dir / REPORT_FILE,
            build_report(df, model_version=model_dir.name, model_sha256=digest, **report_fields),
        )
    except BaseException:
        shutil.rmtree(model_dir, ignore_errors=True)
        for parent in created_parents:
            try:
                parent.rmdir()
            except OSError:
                break
        raise
    return digest


def run(
    dataset_dir: Path | str,
    models_root: Path | str,
    *,
    external_sources: Path | str | None = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    epochs: int = DEFAULT_EPOCHS,
    seed: int = 42,
    smoke: bool = False,
) -> Path:
    """Check everything in the order of section 4.3, train and write; return the model directory.

    Raises:
        ProvisionalRefusal: a refusal of section 4.3.
        ManifestError: invalid manifest.
        TrainError: a grade without images, or no torch.
    """
    _check_version(model_version)
    dataset_real = Path(os.path.realpath(dataset_dir))
    models_real = Path(os.path.realpath(models_root))
    if inside_git_repository(dataset_real) or inside_git_repository(models_real):
        raise ProvisionalRefusal(PATHS_IN_GIT)
    model_dir = models_real / model_version
    _check_model_dir(model_dir)

    # The only call that accepts the suggested grades (SPEC-041 section 4.9).
    df = load_manifest(dataset_real, external_sources=external_sources, allow_agent_suggestion=True)
    _check_dataset(df, dataset_real)
    labels = model_labels_for(df, df)
    weights = grade_class_weights(graded_training_counts(df, labels))
    low, high = EPOCHS_A_RANGE
    if not smoke and not low <= epochs <= high:
        raise ProvisionalRefusal(f"epochs must be in [{low}, {high}]")
    require_torch()

    n_epochs = SMOKE_EPOCHS if smoke else epochs
    model, losses = train_model(
        df, dataset_real, labels, weights, epochs=n_epochs, seed=seed, smoke=smoke
    )
    report_fields = {"epochs": n_epochs, "seed": seed, "smoke": smoke, "losses": losses}
    digest = _write_model_dir(model, model_dir, labels, report_fields, df)
    logger.info("provisional model written: %s (sha256 %s)", model_dir, digest)
    return model_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.provisional",
        description="Train the provisional model, only to rehearse the flow (ADR-024).",
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--models-root", required=True, type=Path)
    parser.add_argument(
        "--external-sources",
        type=Path,
        default=None,
        help="registry of the external sources (default: ml/external_sources.csv)",
    )
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke", action="store_true", help="tiny backbone, 1 epoch: tests only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when the model directory was written, 2 on any error (message on stderr)."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        run(
            args.dataset_dir,
            args.models_root,
            external_sources=args.external_sources,
            model_version=args.model_version,
            epochs=args.epochs,
            seed=args.seed,
            smoke=args.smoke,
        )
    except (ProvisionalRefusal, TrainError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except ManifestError as exc:
        print_problems(exc.problems, sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error("provisional", exc)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

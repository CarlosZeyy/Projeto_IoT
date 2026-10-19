"""Synthetic dataset for the tests of SPEC-011 and SPEC-012 (SPEC-011 section 4.6).

Same layout as the collect mode (SPEC-010): ``root/raw/<object_type>/<grade or _>/
<item_id>__<angle>__<ts>.jpg`` and a valid ``root/manifest.csv``. Images are 256x256 baseline
JPEGs on a light background: screw = rectangle, nut = hexagon with a hole, other = circle, with an
orange (rust) fraction that grows with the grade. No real photo is ever used (R-02, R-14).

No torch here.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from qc_ml.data import (
    GRADED_OBJECT_TYPES,
    GRADES,
    KNOWN_OBJECT_TYPES,
    MANIFEST_COLUMNS,
    MANIFEST_FILE,
    RAW_DIR,
)

IMAGE_SIZE = 256
JPEG_QUALITY = 90
NO_GRADE_DIR = "_"
FILE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
CAPTURED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
BASE_TIME = datetime(2026, 10, 22, 14, 0, 0, tzinfo=UTC)
LABELER = "a"
CAPTURE_DEVICE = "synthetic"
ITEM_PREFIXES: dict[str, str] = {"screw": "S", "nut": "N", "other": "O"}
MAX_ITEMS_PER_TYPE = 999

# Fraction of the part covered by rust, by grade index (perfect .. unusable).
RUST_FRACTION: tuple[float, ...] = (0.0, 0.05, 0.15, 0.40, 0.70)
BACKGROUND = (236, 236, 230)
METAL = (150, 152, 158)
RUST = (196, 98, 34)
OTHER_COLORS: tuple[tuple[int, int, int], ...] = (
    (40, 90, 170),
    (60, 140, 70),
    (170, 50, 60),
    (90, 70, 50),
    (30, 30, 30),
)


def _polygon(cx: float, cy: float, radius: float, sides: int, angle: float) -> list[tuple]:
    return [
        (
            cx + radius * np.cos(angle + 2 * np.pi * k / sides),
            cy + radius * np.sin(angle + 2 * np.pi * k / sides),
        )
        for k in range(sides)
    ]


def _rectangle(cx: float, cy: float, w: float, h: float, angle: float) -> list[tuple]:
    cos, sin = np.cos(angle), np.sin(angle)
    corners = ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    return [(cx + x * cos - y * sin, cy + x * sin + y * cos) for x, y in corners]


def _shape_mask(object_type: str, rng: np.random.Generator) -> np.ndarray:
    mask = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    cx = IMAGE_SIZE / 2 + float(rng.uniform(-15, 15))
    cy = IMAGE_SIZE / 2 + float(rng.uniform(-15, 15))
    angle = float(rng.uniform(-np.pi / 6, np.pi / 6))
    if object_type == "screw":
        w, h = float(rng.uniform(50, 70)), float(rng.uniform(150, 190))
        draw.polygon(_rectangle(cx, cy, w, h, angle), fill=255)
    elif object_type == "nut":
        radius = float(rng.uniform(60, 80))
        draw.polygon(_polygon(cx, cy, radius, 6, angle), fill=255)
        hole = 0.4 * radius
        draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=0)
    else:
        radius = float(rng.uniform(50, 80))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    return np.asarray(mask) > 0


def _rust_mask(shape: np.ndarray, fraction: float, rng: np.random.Generator) -> np.ndarray:
    rust = np.zeros_like(shape)
    if fraction <= 0:
        return rust
    target = fraction * shape.sum()
    ys, xs = np.nonzero(shape)
    layer = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    draw = ImageDraw.Draw(layer)
    for _ in range(2000):
        k = int(rng.integers(0, len(xs)))
        r = float(rng.uniform(5, 15))
        draw.ellipse((xs[k] - r, ys[k] - r, xs[k] + r, ys[k] + r), fill=255)
        rust = (np.asarray(layer) > 0) & shape
        if rust.sum() >= target:
            break
    return rust


def make_synthetic_image(
    object_type: str, grade: str | None, rng: np.random.Generator
) -> Image.Image:
    """One 256x256 RGB image of ``object_type`` with the rust fraction of ``grade``."""
    if object_type not in KNOWN_OBJECT_TYPES:
        raise ValueError(f"object_type must be one of {KNOWN_OBJECT_TYPES}, got {object_type!r}")
    noise = rng.normal(0, 3, size=(IMAGE_SIZE, IMAGE_SIZE, 3))
    pixels = np.asarray(BACKGROUND, dtype=np.float64) + noise
    shape = _shape_mask(object_type, rng)
    if object_type == "other":
        color = OTHER_COLORS[int(rng.integers(0, len(OTHER_COLORS)))]
    else:
        color = METAL
    pixels[shape] = np.asarray(color, dtype=np.float64) + noise[shape] * 2
    if grade is not None:
        rust = _rust_mask(shape, RUST_FRACTION[GRADES.index(grade)], rng)
        pixels[rust] = np.asarray(RUST, dtype=np.float64) + noise[rust] * 3
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def _jpeg_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)  # baseline: a single scan marker
    return buffer.getvalue()


def _write_images(
    root: Path,
    item_id: str,
    object_type: str,
    grade: str | None,
    n_images: int,
    start: datetime,
    rng: np.random.Generator,
) -> list[list[str]]:
    rows: list[list[str]] = []
    folder = root / RAW_DIR / object_type / (grade or NO_GRADE_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    for j in range(n_images):
        angle = j % 5
        ts = start + timedelta(seconds=j)
        name = f"{item_id}__{angle}__{ts.strftime(FILE_TIMESTAMP_FORMAT)}.jpg"
        (folder / name).write_bytes(_jpeg_bytes(make_synthetic_image(object_type, grade, rng)))
        image_path = f"{RAW_DIR}/{object_type}/{grade or NO_GRADE_DIR}/{name}"
        rows.append(
            [
                image_path,
                item_id,
                object_type,
                grade or "",
                LABELER,
                str(angle),
                ts.strftime(CAPTURED_AT_FORMAT),
                CAPTURE_DEVICE,
                "",
            ]
        )
    return rows


def make_synthetic_dataset(
    root: Path,
    *,
    items_per_stratum: int = 4,
    images_per_item: int = 2,
    include_other: bool = True,
    seed: int = 0,
) -> Path:
    """Create a synthetic dataset in ``root`` and return ``root``.

    For ``screw`` and ``nut``: ``items_per_stratum`` items per grade, numbered ``S-001``... and
    ``N-001``... with the grades in round robin (``S-001`` perfect, ``S-002`` good, ``S-003``
    fair, ``S-004`` poor, ``S-005`` unusable, ``S-006`` perfect...). With ``include_other``:
    ``items_per_stratum`` items ``O-001``... without grade. Each item has ``images_per_item``
    images with ``angle = j % 5``; timestamps are unique and increase from 2026-10-22T14:00:00Z.

    Raises:
        FileExistsError: ``root/manifest.csv`` already exists.
        ValueError: non-positive counts or more than 999 items of a type.
    """
    if items_per_stratum < 1 or images_per_item < 1:
        raise ValueError("items_per_stratum and images_per_item must be >= 1")
    if items_per_stratum * len(GRADES) > MAX_ITEMS_PER_TYPE:
        raise ValueError(f"at most {MAX_ITEMS_PER_TYPE} items per type")
    root = Path(root)
    manifest = root / MANIFEST_FILE
    if manifest.exists():
        raise FileExistsError(f"{manifest} already exists")
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    plan: list[tuple[str, str, str | None]] = []
    for object_type in GRADED_OBJECT_TYPES:
        prefix = ITEM_PREFIXES[object_type]
        for k in range(items_per_stratum * len(GRADES)):
            plan.append((f"{prefix}-{k + 1:03d}", object_type, GRADES[k % len(GRADES)]))
    if include_other:
        for k in range(items_per_stratum):
            plan.append((f"{ITEM_PREFIXES['other']}-{k + 1:03d}", "other", None))

    rows: list[list[str]] = []
    for index, (item_id, object_type, grade) in enumerate(plan):
        start = BASE_TIME + timedelta(seconds=index * images_per_item)
        rows += _write_images(root, item_id, object_type, grade, images_per_item, start, rng)

    with manifest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(MANIFEST_COLUMNS)
        writer.writerows(rows)
    return root


def add_synthetic_item(
    root: Path,
    item_id: str,
    object_type: str,
    grade: str | None,
    *,
    n_images: int = 2,
    seed: int = 1,
) -> list[str]:
    """Append ``n_images`` synthetic images of one item to an existing dataset.

    Works for a new item and for new images of an existing item. Timestamps start one second after
    the latest ``captured_at`` of the manifest, so file names never collide. Returns the new
    ``image_path`` values.
    """
    root = Path(root)
    manifest = root / MANIFEST_FILE
    with manifest.open("r", encoding="utf-8", newline="") as fh:
        captured = [row["captured_at"] for row in csv.DictReader(fh)]
    latest = max(
        (datetime.strptime(c, CAPTURED_AT_FORMAT).replace(tzinfo=UTC) for c in captured),
        default=BASE_TIME,
    )
    rng = np.random.default_rng(seed)
    rows = _write_images(
        root, item_id, object_type, grade, n_images, latest + timedelta(seconds=1), rng
    )
    with manifest.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return [row[0] for row in rows]

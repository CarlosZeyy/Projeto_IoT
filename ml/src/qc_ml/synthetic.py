"""Synthetic dataset for the tests of SPEC-011 and SPEC-012 (SPEC-011 section 4.6).

Same layout as the collect mode (SPEC-010): ``root/raw/<object_type>/<grade or _>/
<item_id>__<angle>__<ts>.jpg`` and a valid ``root/manifest.csv``. Images are 256x256 baseline
JPEGs on a light background: screw = rectangle, nut = hexagon with a hole, other = circle, with an
orange (rust) fraction that grows with the grade. No real photo is ever used (R-02, R-14).

SPEC-035 section 4.7: optional contributor items (``S-501``...) and external images
(``XS-0001``...), with ``root/sources.csv`` and the registry ``root/external_sources.csv``.

No torch here.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from qc_ml.data import (
    EXTERNAL_PREFIX,
    EXTERNAL_SOURCE_COLUMNS,
    EXTERNAL_SOURCES_FILE,
    GRADED_OBJECT_TYPES,
    GRADES,
    KNOWN_OBJECT_TYPES,
    MANIFEST_COLUMNS,
    MANIFEST_FILE,
    RAW_DIR,
    SOURCE_COLUMNS,
    SOURCES_FILE,
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
CONTRIBUTOR_FIRST_NUMBER = 501  # docs/dataset-protocol.md section 10.3 (recommendation)
MAX_EXTERNAL_ITEMS_PER_TYPE = 9999
SYNTHETIC_CONTRIBUTOR = "c01"
SYNTHETIC_SOURCE = (
    "synthetic",
    "Synthetic dataset",
    "https://example.org/synthetic",
    "CC0-1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "Synthetic test images",
    "2026-10-20",
)

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


def _strata(include_other: bool) -> list[tuple[str, str | None]]:
    """The 10 ``screw``/``nut`` x grade strata and, with ``include_other``, ``other``."""
    strata: list[tuple[str, str | None]] = [
        (object_type, grade) for object_type in GRADED_OBJECT_TYPES for grade in GRADES
    ]
    if include_other:
        strata.append(("other", None))
    return strata


def _write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def make_synthetic_dataset(
    root: Path,
    *,
    items_per_stratum: int = 4,
    images_per_item: int = 2,
    include_other: bool = True,
    seed: int = 0,
    external_items_per_stratum: int = 0,
    contributor_items_per_stratum: int = 0,
) -> Path:
    """Create a synthetic dataset in ``root`` and return ``root``.

    For ``screw`` and ``nut``: ``items_per_stratum`` items per grade, numbered ``S-001``... and
    ``N-001``... with the grades in round robin (``S-001`` perfect, ``S-002`` good, ``S-003``
    fair, ``S-004`` poor, ``S-005`` unusable, ``S-006`` perfect...). With ``include_other``:
    ``items_per_stratum`` items ``O-001``... without grade. Each item has ``images_per_item``
    images with ``angle = j % 5``; timestamps are unique and increase from 2026-10-22T14:00:00Z.

    SPEC-035 section 4.7 ("stratum" = each ``screw``/``nut`` x grade and, with
    ``include_other``, ``other``):

    - ``contributor_items_per_stratum = c``: ``c`` contributor items per stratum, numbered from
      501 per letter (``S-501``, ``S-502``..., continuing across the strata of the letter), each
      with ``images_per_item`` images and one ``contributor`` line (``c01``) per image in
      ``sources.csv``;
    - ``external_items_per_stratum = k``: ``k`` external items per stratum, ``XS-0001``... per
      letter, each with 1 image (angle 0) and one ``external`` line per image (``source_id``
      ``synthetic``, ``source_ref`` ``synthetic/<item_id>.png``); ``root/external_sources.csv``
      gets the single source ``synthetic`` (``CC0-1.0``).

    ``input_sha256`` is the SHA-256 of the file written. With ``c = k = 0`` (the default) the
    files are byte for byte the ones of SPEC-011, and neither ``sources.csv`` nor
    ``external_sources.csv`` is created. The own items come first, so their images do not depend
    on ``c`` and ``k``.

    Raises:
        FileExistsError: ``root/manifest.csv`` already exists.
        ValueError: non-positive counts, negative ``c``/``k`` or too many items of a type.
    """
    if items_per_stratum < 1 or images_per_item < 1:
        raise ValueError("items_per_stratum and images_per_item must be >= 1")
    if external_items_per_stratum < 0 or contributor_items_per_stratum < 0:
        raise ValueError(
            "external_items_per_stratum and contributor_items_per_stratum must be >= 0"
        )
    if items_per_stratum * len(GRADES) > MAX_ITEMS_PER_TYPE:
        raise ValueError(f"at most {MAX_ITEMS_PER_TYPE} items per type")
    last_contributor = CONTRIBUTOR_FIRST_NUMBER - 1 + contributor_items_per_stratum * len(GRADES)
    if last_contributor > MAX_ITEMS_PER_TYPE:
        raise ValueError(f"contributor items go up to {MAX_ITEMS_PER_TYPE} per type")
    if external_items_per_stratum * len(GRADES) > MAX_EXTERNAL_ITEMS_PER_TYPE:
        raise ValueError(f"at most {MAX_EXTERNAL_ITEMS_PER_TYPE} external items per type")
    root = Path(root)
    manifest = root / MANIFEST_FILE
    if manifest.exists():
        raise FileExistsError(f"{manifest} already exists")
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    # (item_id, object_type, grade, n_images, origin)
    plan: list[tuple[str, str, str | None, int, str]] = []
    for object_type in GRADED_OBJECT_TYPES:
        prefix = ITEM_PREFIXES[object_type]
        for k in range(items_per_stratum * len(GRADES)):
            item_id = f"{prefix}-{k + 1:03d}"
            plan.append((item_id, object_type, GRADES[k % len(GRADES)], images_per_item, "capture"))
    if include_other:
        for k in range(items_per_stratum):
            item_id = f"{ITEM_PREFIXES['other']}-{k + 1:03d}"
            plan.append((item_id, "other", None, images_per_item, "capture"))
    contributor_next: dict[str, int] = {}
    external_next: dict[str, int] = {}
    for object_type, grade in _strata(include_other):
        prefix = ITEM_PREFIXES[object_type]
        for _ in range(contributor_items_per_stratum):
            number = contributor_next.get(prefix, CONTRIBUTOR_FIRST_NUMBER)
            contributor_next[prefix] = number + 1
            plan.append(
                (f"{prefix}-{number:03d}", object_type, grade, images_per_item, "contributor")
            )
    for object_type, grade in _strata(include_other):
        prefix = ITEM_PREFIXES[object_type]
        for _ in range(external_items_per_stratum):
            number = external_next.get(prefix, 1)
            external_next[prefix] = number + 1
            item_id = f"{EXTERNAL_PREFIX}{prefix}-{number:04d}"
            plan.append((item_id, object_type, grade, 1, "external"))

    rows: list[list[str]] = []
    source_rows: list[list[str]] = []
    offset = 0  # seconds after BASE_TIME
    for index, (item_id, object_type, grade, n_images, origin) in enumerate(plan):
        if origin == "capture":
            offset = index * images_per_item  # the timestamps of SPEC-011
        start = BASE_TIME + timedelta(seconds=offset)
        item_rows = _write_images(root, item_id, object_type, grade, n_images, start, rng)
        offset += n_images
        rows += item_rows
        if origin == "capture":
            continue
        for row in item_rows:
            digest = hashlib.sha256((root / row[0]).read_bytes()).hexdigest()
            if origin == "contributor":
                source_rows.append([row[0], origin, SYNTHETIC_CONTRIBUTOR, "", "", digest])
            else:
                ref = f"synthetic/{item_id}.png"
                source_rows.append([row[0], origin, "", SYNTHETIC_SOURCE[0], ref, digest])

    _write_csv(manifest, MANIFEST_COLUMNS, rows)
    if source_rows:
        _write_csv(root / SOURCES_FILE, SOURCE_COLUMNS, source_rows)
    if external_items_per_stratum:
        _write_csv(root / EXTERNAL_SOURCES_FILE, EXTERNAL_SOURCE_COLUMNS, [list(SYNTHETIC_SOURCE)])
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

"""Confusion matrices as PNG, drawn with Pillow only (SPEC-012 section 4.7; no matplotlib).

Labels in PT-BR (ADR-012): the grades come from ``qc_contracts.GRADE_LABELS_PT``; the model class
``other`` is shown as "outro" (it becomes ``unknown`` only after the decision rule).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from qc_contracts import (
    GRADE_LABELS_PT,
    GRADE_OPTIONAL_OBJECT_TYPES,
    OBJECT_TYPE_LABELS_PT,
    Grade,
    ObjectType,
)

CELL = 96
LEFT = 170
TOP = 110
BOTTOM = 40
RIGHT = 30
BACKGROUND = (255, 255, 255)
GRID = (120, 120, 120)
TEXT = (20, 20, 20)

TYPE_LABELS_PT: dict[str, str] = {
    "screw": OBJECT_TYPE_LABELS_PT[ObjectType.SCREW],
    "nut": OBJECT_TYPE_LABELS_PT[ObjectType.NUT],
    "other": "outro",
    # SPEC-016: the hand tools, with the PT-BR labels of the contract.
    **{
        member.value: OBJECT_TYPE_LABELS_PT[member]
        for member in ObjectType
        if member in GRADE_OPTIONAL_OBJECT_TYPES
    },
}


def type_label_pt(object_type: str) -> str:
    return TYPE_LABELS_PT.get(object_type, object_type)


def grade_label_pt(grade: str) -> str:
    return GRADE_LABELS_PT[Grade(grade)]


# Fonts with Latin-1 glyphs, looked up by file name in the system font directories (Pillow
# searches them on Linux, macOS and Windows). Pillow's embedded default font has no accented
# letters, so without any of these the labels are drawn without accents ("inutilizavel").
FONT_CANDIDATES: tuple[str, ...] = (
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "NotoSans-Regular.ttf",
    "Arial.ttf",
    "arial.ttf",
)


@dataclass(frozen=True)
class _Fonts:
    title: ImageFont.ImageFont | ImageFont.FreeTypeFont
    label: ImageFont.ImageFont | ImageFont.FreeTypeFont
    cell: ImageFont.ImageFont | ImageFont.FreeTypeFont
    accents: bool


def _fonts() -> _Fonts:
    for name in FONT_CANDIDATES:
        try:
            return _Fonts(
                ImageFont.truetype(name, 18),
                ImageFont.truetype(name, 14),
                ImageFont.truetype(name, 16),
                accents=True,
            )
        except OSError:
            continue
    try:
        sizes = [ImageFont.load_default(size=n) for n in (18, 14, 16)]
    except (TypeError, OSError):  # Pillow without FreeType: bitmap font
        sizes = [ImageFont.load_default()] * 3
    return _Fonts(*sizes, accents=False)


def _plain(text: str) -> str:
    """``text`` without diacritics (for a font without accented glyphs)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _cell_color(fraction: float) -> tuple[int, int, int]:
    """White (0) to dark blue (1)."""
    f = min(1.0, max(0.0, fraction))
    return (int(255 - 205 * f), int(255 - 165 * f), int(255 - 55 * f))


def _centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (box[0] + box[2] - (right - left)) / 2 - left
    y = (box[1] + box[3] - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def confusion_png(
    path: Path, matrix: Sequence[Sequence[int]], labels_pt: Sequence[str], title: str
) -> None:
    """Draw ``matrix`` (rows = true class, columns = predicted) with counts in each cell.

    The color of a cell is its count divided by the row total (empty rows stay white).
    """
    counts = np.asarray(matrix, dtype=np.int64)
    n = len(labels_pt)
    if counts.shape != (n, n):
        raise ValueError(f"matrix must be {n}x{n}, got {counts.shape}")
    width = LEFT + n * CELL + RIGHT
    height = TOP + n * CELL + BOTTOM
    img = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(img)
    fonts = _fonts()
    title_font, label_font, cell_font = fonts.title, fonts.label, fonts.cell
    if not fonts.accents:
        title = _plain(title)
        labels_pt = [_plain(label) for label in labels_pt]
    note = "cor: fração da linha (classe verdadeira)"
    note = note if fonts.accents else _plain(note)

    draw.text((16, 12), title, font=title_font, fill=TEXT)
    _centered(draw, (LEFT, 40, LEFT + n * CELL, 62), "Previsto", label_font, TEXT)
    draw.text((16, TOP - 26), "Verdadeiro", font=label_font, fill=TEXT)
    row_totals = counts.sum(axis=1)
    for j, label in enumerate(labels_pt):
        x0 = LEFT + j * CELL
        _centered(draw, (x0, TOP - 40, x0 + CELL, TOP - 4), label, label_font, TEXT)
    for i, label in enumerate(labels_pt):
        y0 = TOP + i * CELL
        _centered(draw, (16, y0, LEFT - 8, y0 + CELL), label, label_font, TEXT)
        for j in range(n):
            x0 = LEFT + j * CELL
            fraction = counts[i, j] / row_totals[i] if row_totals[i] else 0.0
            box = (x0, y0, x0 + CELL, y0 + CELL)
            draw.rectangle(box, fill=_cell_color(fraction), outline=GRID)
            color = (255, 255, 255) if fraction > 0.55 else TEXT
            _centered(draw, box, str(int(counts[i, j])), cell_font, color)
    _centered(
        draw,
        (LEFT, TOP + n * CELL + 6, LEFT + n * CELL, height - 6),
        note,
        label_font,
        GRID,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")

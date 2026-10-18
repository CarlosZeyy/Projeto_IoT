"""Author tests for qc_ml.agreement (SPEC-011 section 4.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sklearn.metrics import cohen_kappa_score

from qc_ml import agreement
from qc_ml.data import GRADES, MANIFEST_COLUMNS


def _write_pair(
    root: Path, first: list[int], second: list[int], write_csv, object_type: str = "screw"
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, g in enumerate(first):
        path = f"raw/{object_type}/{GRADES[g]}/S-{k + 1:03d}__0__20261022T1400{k:02d}Z.jpg"
        rows.append([path, f"S-{k + 1:03d}", object_type, GRADES[g], "a", "0", "t", "dev", ""])
    write_csv(root / "manifest.csv", list(MANIFEST_COLUMNS), rows)
    write_csv(
        root / "labels_second.csv",
        ["image_path", "grade", "labeler"],
        [[r[0], GRADES[g], "b"] for r, g in zip(rows, second, strict=True)],
    )
    return root / "manifest.csv", root / "labels_second.csv"


def _run(first: Path, second: Path, out: Path) -> int:
    return agreement.main(["--first", str(first), "--second", str(second), "--out", str(out)])


def test_known_values(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    a = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    b = [0, 1, 2, 3, 4, 1, 1, 3, 3, 3]
    first, second = _write_pair(tmp_path / "d", a, b, write_csv)
    out = tmp_path / "out/agreement.json"
    assert _run(first, second, out) == 0
    result = json.loads(out.read_text())
    assert result["n_pairs"] == 10 and result["n_excluded_pairs"] == 0
    assert result["qwk"] == pytest.approx(32 / 35, abs=1e-4)
    assert result["qwk"] == pytest.approx(cohen_kappa_score(a, b, weights="quadratic"))
    assert result["exact_agreement"] == 0.7
    assert result["off_by_one_agreement"] == 1.0
    assert result["confusion"][0][1] == 1
    assert sum(map(sum, result["confusion"])) == 10
    assert result["meets_minimum"] is True and result["meets_desired"] is True
    assert result["grades"] == list(GRADES)
    assert result["labeler_first"] == "a" and result["labeler_second"] == "b"
    assert result["targets"] == {"minimum": 0.6, "desired": 0.8}
    assert len(result["first_sha256"]) == 64 and len(result["second_sha256"]) == 64
    assert "generated_at" in result


def test_inverted_ratings(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    a = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    first, second = _write_pair(tmp_path / "d", a, a[::-1], write_csv)
    out = tmp_path / "agreement.json"
    assert _run(first, second, out) == 0
    result = json.loads(out.read_text())
    assert result["qwk"] == pytest.approx(-1.0, abs=1e-6)
    assert result["meets_minimum"] is False


def test_unknown_image_is_exit_2(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    first, second = _write_pair(tmp_path / "d", [0, 1], [0, 1], write_csv)
    with second.open("a", encoding="utf-8") as fh:
        fh.write("raw/screw/good/S-999__0__20261022T140000Z.jpg,good,b\n")
    out = tmp_path / "agreement.json"
    assert _run(first, second, out) == 2
    assert not out.exists()


def test_invalid_grade_and_no_pairs(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    first, second = _write_pair(tmp_path / "d", [0, 1], [0, 1], write_csv)
    second.write_text(second.read_text().replace(",good,", ",rusty,"))
    out = tmp_path / "agreement.json"
    assert _run(first, second, out) == 2
    first, second = _write_pair(tmp_path / "e", [0, 1], [0, 1], write_csv, object_type="other")
    assert _run(first, second, out) == 2
    assert not out.exists()


def test_empty_second_grade_is_skipped(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    first, second = _write_pair(tmp_path / "d", [0, 1, 2], [0, 1, 2], write_csv)
    second.write_text(second.read_text().replace(",fair,", ",,"))
    out = tmp_path / "agreement.json"
    assert _run(first, second, out) == 0
    assert json.loads(out.read_text())["n_pairs"] == 2


def test_overrides_are_not_applied(dataset: Path, tmp_path: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    rows = [r for r in read_rows(dataset) if r["object_type"] == "screw"][:10]
    write_csv(
        dataset / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[r["image_path"], "unusable", "b", "x"] for r in rows],
    )
    write_csv(
        dataset / "labels_second.csv",
        ["image_path", "grade", "labeler"],
        [[r["image_path"], r["grade"], "b"] for r in rows],
    )
    out = tmp_path / "agreement.json"
    assert _run(dataset / "manifest.csv", dataset / "labels_second.csv", out) == 0
    assert json.loads(out.read_text())["exact_agreement"] == 1.0


def test_excluded_images_leave_both_files(dataset: Path, tmp_path: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    rows = [r for r in read_rows(dataset) if r["object_type"] in ("screw", "nut")]
    victim = next(r for r in rows if r["item_id"] == "S-002")
    others = [r for r in rows if r is not victim][:9]
    (dataset / victim["image_path"]).unlink()
    write_csv(
        dataset / "exclusions.csv", ["image_path", "reason"], [[victim["image_path"], "person"]]
    )
    write_csv(
        dataset / "labels_second.csv",
        ["image_path", "grade", "labeler"],
        [[r["image_path"], r["grade"], "b"] for r in [victim, *others]],
    )
    out = tmp_path / "agreement.json"
    assert _run(dataset / "manifest.csv", dataset / "labels_second.csv", out) == 0
    result = json.loads(out.read_text())
    assert result["n_pairs"] == 9 and result["n_excluded_pairs"] == 1


def test_degenerate_qwk_is_null(tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    first, second = _write_pair(tmp_path / "d", [2, 2, 2], [2, 2, 2], write_csv)
    out = tmp_path / "agreement.json"
    assert _run(first, second, out) == 0
    result = json.loads(out.read_text())
    assert result["exact_agreement"] == 1.0
    assert result["qwk"] is None
    assert result["meets_minimum"] is False and result["meets_desired"] is False

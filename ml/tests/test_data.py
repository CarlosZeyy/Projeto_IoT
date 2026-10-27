"""Author tests for qc_ml.data: manifest, overrides, exclusions, orphans and report (SPEC-011)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from qc_ml import data
from qc_ml.data import (
    RESULT_COLUMNS,
    build_data_report,
    dominant_grade,
    find_raw_images,
    load_exclusions,
    load_manifest,
)
from qc_ml.errors import ManifestError, ManifestProblem, SplitError


def _codes(err: ManifestError) -> list[str]:
    return [p.code for p in err.problems]


def _problems(root: Path, **kwargs) -> list[ManifestProblem]:
    with pytest.raises(ManifestError) as info:
        load_manifest(root, **kwargs)
    return info.value.problems


def _first(rows, **match) -> dict[str, str]:
    return next(r for r in rows if all(r[k] == v for k, v in match.items()))


# ---------- happy path ----------


def test_loads_the_synthetic_dataset(dataset: Path) -> None:
    df = load_manifest(dataset)
    assert len(df) == 88
    assert list(df.columns) == list(RESULT_COLUMNS)
    other = df[df["object_type"] == "other"]
    assert len(other) == 8
    assert all(g is None for g in other["grade"])
    assert all(g is None for g in other["grade_original"])
    assert df["angle"].dtype == "int64"
    assert not df["overridden"].any()
    assert (df["grade"].fillna("x") == df["grade_original"].fillna("x")).all()
    assert len(df.attrs["manifest_sha256"]) == 64
    assert df.attrs["n_excluded"] == 0


def test_manifest_sha256_matches_the_file(dataset: Path) -> None:
    df = load_manifest(dataset)
    assert df.attrs["manifest_sha256"] == data.manifest_sha256(dataset)


# ---------- row problems ----------


def test_missing_file(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    victim = read_rows(dataset)[10]["image_path"]
    (dataset / victim).unlink()
    problems = _problems(dataset)
    assert [(p.code, p.image_path, p.line) for p in problems] == [("missing_file", victim, 12)]


def test_unreadable_image_only_with_verify(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    victim = read_rows(dataset)[3]["image_path"]
    (dataset / victim).write_bytes(b"not an image")
    problems = _problems(dataset)
    assert [(p.code, p.image_path) for p in problems] == [("unreadable_image", victim)]
    assert len(load_manifest(dataset, verify_images=False)) == 88


def test_too_many_jpeg_scans_is_its_own_code(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    rows = read_rows(dataset)
    motion = _first(rows, object_type="screw")["image_path"]
    broken = rows[-1]["image_path"]
    path = dataset / motion
    path.write_bytes(path.read_bytes() + b"\xff\xda" * 64)
    (dataset / broken).write_bytes(b"not an image")
    problems = _problems(dataset)
    by_code = {p.code: p for p in problems}
    assert sorted(by_code) == ["too_many_jpeg_scans", "unreadable_image"]
    assert by_code["too_many_jpeg_scans"].image_path == motion
    assert "JPEG scans" in by_code["too_many_jpeg_scans"].message
    assert "dataset-protocol" in by_code["too_many_jpeg_scans"].message
    assert by_code["unreadable_image"].image_path == broken
    assert len(load_manifest(dataset, verify_images=False)) == 88


def test_too_many_jpeg_scans_cli_counts(dataset: Path, rows_io, capsys) -> None:
    read_rows, _, _ = rows_io
    rows = read_rows(dataset)
    path = dataset / _first(rows, object_type="screw")["image_path"]
    path.write_bytes(path.read_bytes() + b"\xff\xda" * 64)
    (dataset / rows[-1]["image_path"]).write_bytes(b"not an image")
    capsys.readouterr()
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 2
    out = capsys.readouterr().out.splitlines()
    assert out[-2:] == ["count too_many_jpeg_scans: 1", "count unreadable_image: 1"]


def test_item_type_conflict_and_prefix_mismatch(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    index = next(i for i, r in enumerate(rows) if r["item_id"] == "S-001")
    rows[index]["object_type"] = "nut"
    write_rows(dataset, rows)
    problems = _problems(dataset)
    conflict = [p for p in problems if p.code == "item_type_conflict"]
    assert len(conflict) == 1 and "S-001" in conflict[0].message
    mismatch = [p for p in problems if p.code == "item_prefix_mismatch"]
    assert [p.line for p in mismatch] == [index + 2]


def test_grade_on_other_and_missing_grade_with_lines(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    i_other = next(i for i, r in enumerate(rows) if r["object_type"] == "other")
    i_screw = 5
    rows[i_other]["grade"] = "fair"
    rows[i_screw]["grade"] = ""
    write_rows(dataset, rows)
    found = {(p.code, p.line) for p in _problems(dataset)}
    assert found == {("grade_on_other", i_other + 2), ("missing_grade", i_screw + 2)}


def test_invalid_values(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    rows[0]["grade"] = "rusty"
    rows[1]["angle"] = "7"
    rows[2]["item_id"] = "X-1"
    rows[3]["angle"] = "1.0"
    rows[4]["object_type"] = "unknown"
    write_rows(dataset, rows)
    codes = sorted(p.code for p in _problems(dataset))
    assert codes == [
        "invalid_angle",
        "invalid_angle",
        "invalid_grade",
        "invalid_item_id",
        "invalid_object_type",
        "item_type_conflict",  # S-003 now has "screw" and "unknown"
    ]


def test_item_id_with_unicode_digits_is_invalid(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    for row in rows:
        if row["item_id"] == "S-001":
            row["item_id"] = "S-\u0660\u0661\u0662"
    write_rows(dataset, rows)
    assert {p.code for p in _problems(dataset)} == {"invalid_item_id"}


def test_tool_prefix_is_not_accepted_yet(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    for row in rows:
        if row["item_id"] == "O-001":
            row["item_id"] = "T-001"
    write_rows(dataset, rows)
    assert {p.code for p in _problems(dataset)} == {"item_prefix_mismatch"}


def test_all_problems_in_one_error_and_cli(dataset: Path, rows_io, capsys) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    (dataset / rows[0]["image_path"]).unlink()
    i_other = next(i for i, r in enumerate(rows) if r["object_type"] == "other")
    rows[i_other]["grade"] = "good"
    rows[7]["angle"] = "9"
    write_rows(dataset, rows)
    problems = _problems(dataset)
    assert sorted(p.code for p in problems) == ["grade_on_other", "invalid_angle", "missing_file"]
    capsys.readouterr()
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 2
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == [str(p) for p in problems]
    assert out[3:] == [
        "count grade_on_other: 1",
        "count invalid_angle: 1",
        "count missing_file: 1",
    ]


def test_str_of_error_has_one_problem_per_line(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    rows = read_rows(dataset)
    for row in rows[:2]:
        (dataset / row["image_path"]).unlink()
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset)
    lines = str(info.value).splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("manifest.csv:2: missing_file: ")


def test_duplicate_image_path(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    write_rows(dataset, [*rows, dict(rows[0])])
    problems = _problems(dataset)
    assert [(p.code, p.line) for p in problems] == [("duplicate_image_path", 90)]


def test_missing_column_aborts(dataset: Path) -> None:
    manifest = dataset / "manifest.csv"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("labeler,", "rater,", 1), encoding="utf-8")
    problems = _problems(dataset)
    assert [(p.code, p.line) for p in problems] == [("missing_column", 1)]
    assert "labeler" in problems[0].message


def test_bom_is_reported_as_missing_column(dataset: Path) -> None:
    manifest = dataset / "manifest.csv"
    manifest.write_bytes(b"\xef\xbb\xbf" + manifest.read_bytes())
    problems = _problems(dataset)
    assert [p.code for p in problems] == ["missing_column"]
    assert "BOM" in problems[0].message


def test_malformed_row_and_invalid_utf8(dataset: Path) -> None:
    manifest = dataset / "manifest.csv"
    original = manifest.read_bytes()
    manifest.write_bytes(original + b"raw/x.jpg,S-001\n")
    assert [p.code for p in _problems(dataset)] == ["malformed_row"]
    manifest.write_bytes(original + b"\xff\xfe\n")
    assert [p.code for p in _problems(dataset)] == ["unreadable_csv"]


def test_invalid_image_path(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    rows[0]["image_path"] = "../outside.jpg"
    rows[1]["image_path"] = "/etc/passwd"
    write_rows(dataset, rows)
    codes = [p.code for p in _problems(dataset, verify_images=False)]
    assert codes.count("invalid_image_path") == 2
    assert codes.count("orphan_image") == 2  # their real files lost the manifest row


def test_manifest_is_read_as_csv_not_by_lines(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    rows[0]["notes"] = "a\u2028b\u2029c\u202ed"
    rows[1]["capture_device"] = "Phone\x85X"
    rows[2]["notes"] = 'with "quotes", commas\nand a newline'
    write_rows(dataset, rows)
    assert len((dataset / "manifest.csv").read_text(encoding="utf-8").splitlines()) > 89
    df = load_manifest(dataset)
    assert len(df) == 88
    assert df.loc[0, "notes"] == "a\u2028b\u2029c\u202ed"
    assert df.loc[1, "capture_device"] == "Phone\x85X"
    assert df.loc[2, "notes"] == 'with "quotes", commas\nand a newline'


def test_problem_line_is_the_record_number(dataset: Path, rows_io) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    rows[0]["notes"] = "line\nbreak"
    rows[3]["angle"] = "x"
    write_rows(dataset, rows)
    assert [(p.code, p.line) for p in _problems(dataset)] == [("invalid_angle", 5)]


# ---------- overrides ----------


def test_override_changes_the_grade(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    target = _first(read_rows(dataset), item_id="S-003", grade="fair")["image_path"]
    write_csv(
        dataset / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[target, "poor", "b", "crosta"]],
    )
    df = load_manifest(dataset)
    row = df[df["image_path"] == target].iloc[0]
    assert (row["grade"], row["grade_original"], row["overridden"]) == ("poor", "fair", True)
    assert df["overridden"].sum() == 1
    plain = load_manifest(dataset, apply_overrides=False)
    assert not plain["overridden"].any()
    assert plain[plain["image_path"] == target].iloc[0]["grade"] == "fair"


def test_last_override_wins_and_unknown_image(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    target = read_rows(dataset)[0]["image_path"]
    header = ["image_path", "grade", "labeler", "reason"]
    write_csv(
        dataset / "labels_overrides.csv",
        header,
        [[target, "good", "b", "r1"], [target, "poor", "b", "r2"]],
    )
    df = load_manifest(dataset)
    assert df[df["image_path"] == target].iloc[0]["grade"] == "poor"
    write_csv(dataset / "labels_overrides.csv", header, [["raw/nope.jpg", "good", "b", "r"]])
    problems = _problems(dataset)
    assert [(p.code, p.file, p.line) for p in problems] == [
        ("override_unknown_image", "labels_overrides.csv", 2)
    ]


def test_override_fills_a_missing_grade(dataset: Path, rows_io) -> None:
    read_rows, write_rows, write_csv = rows_io
    rows = read_rows(dataset)
    rows[0]["grade"] = ""
    write_rows(dataset, rows)
    write_csv(
        dataset / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[rows[0]["image_path"], "good", "b", "agreed"]],
    )
    df = load_manifest(dataset)
    assert df.loc[0, "grade"] == "good" and df.loc[0, "grade_original"] is None


def test_override_problems(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    rows = read_rows(dataset)
    write_csv(
        dataset / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[rows[0]["image_path"], "good", "b", " "], [rows[1]["image_path"], "rusty", "b", "r"]],
    )
    assert [(p.code, p.line) for p in _problems(dataset)] == [
        ("override_missing_reason", 2),
        ("invalid_grade", 3),
    ]


# ---------- orphans ----------


def test_orphan_image_with_and_without_verify(dataset: Path, capsys) -> None:
    folder = dataset / "raw/screw/fair"
    orphan = folder / "S-099__0__20261022T141503Z.jpg"
    orphan.write_bytes(next(folder.iterdir()).read_bytes())
    (folder / "tmpab12cd").write_bytes(b"partial")
    for verify in (True, False):
        problems = _problems(dataset, verify_images=verify)
        assert [(p.code, p.image_path, p.line) for p in problems] == [
            ("orphan_image", "raw/screw/fair/S-099__0__20261022T141503Z.jpg", None)
        ]
    capsys.readouterr()
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 2
    assert "count orphan_image: 1" in capsys.readouterr().out.splitlines()


def test_find_raw_images_does_not_follow_symlinks(dataset: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.jpg").write_bytes(b"x")
    os.symlink(outside, dataset / "raw/linkdir")
    os.symlink(outside / "x.jpg", dataset / "raw/link.jpg")
    (dataset / "raw/upper.JPG").write_bytes(b"x")
    found = find_raw_images(dataset)
    assert "raw/upper.JPG" in found
    assert not any("link" in p for p in found)
    assert len(found) == 89


# ---------- exclusions ----------


def _exclude(dataset: Path, write_csv, entries: list[list[str]]) -> None:
    write_csv(dataset / "exclusions.csv", ["image_path", "reason"], entries)


def test_exclusion_removes_the_row(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    victim = _first(read_rows(dataset), item_id="S-002")["image_path"]
    (dataset / victim).unlink()
    _exclude(dataset, write_csv, [[victim, "person"]])
    df = load_manifest(dataset)
    assert len(df) == 87 and victim not in set(df["image_path"])
    assert df.attrs["n_excluded"] == 1
    assert build_data_report(df)["n_excluded"] == 1
    assert load_exclusions(dataset) == frozenset({victim})
    assert len(load_manifest(dataset, apply_overrides=False)) == 87


def test_exclusion_problems(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    victim = _first(read_rows(dataset), item_id="S-002")["image_path"]
    _exclude(dataset, write_csv, [[victim, "person"]])
    problems = _problems(dataset)
    assert [(p.code, p.image_path) for p in problems] == [("excluded_file_present", victim)]
    with pytest.raises(ManifestError):
        load_exclusions(dataset)
    (dataset / victim).unlink()
    _exclude(dataset, write_csv, [[victim, "selfie"]])
    assert [p.code for p in _problems(dataset)] == ["exclusion_invalid_reason"]
    _exclude(dataset, write_csv, [[victim, ""]])
    assert [p.code for p in _problems(dataset)] == ["exclusion_invalid_reason"]
    _exclude(dataset, write_csv, [[victim, "other"], ["raw/screw/x.jpg", "other"]])
    problems = _problems(dataset)
    assert [(p.code, p.image_path) for p in problems] == [
        ("exclusion_unknown_image", "raw/screw/x.jpg")
    ]


def test_excluded_image_override_is_ignored(dataset: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    victim = _first(read_rows(dataset), item_id="S-002")["image_path"]
    (dataset / victim).unlink()
    _exclude(dataset, write_csv, [[victim, "person"]])
    write_csv(
        dataset / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[victim, "poor", "b", "r"]],
    )
    df = load_manifest(dataset)
    assert len(df) == 87 and not df["overridden"].any()


def test_excluded_row_does_not_hide_duplicates(dataset: Path, rows_io) -> None:
    read_rows, write_rows, write_csv = rows_io
    rows = read_rows(dataset)
    victim = rows[0]["image_path"]
    write_rows(dataset, [*rows, dict(rows[0])])
    (dataset / victim).unlink()
    _exclude(dataset, write_csv, [[victim, "person"]])
    assert [p.code for p in _problems(dataset)] == ["duplicate_image_path"]


def test_no_exclusions_file(dataset: Path) -> None:
    assert load_exclusions(dataset) == frozenset()


# ---------- dominant grade ----------


def test_dominant_grade() -> None:
    assert dominant_grade(["good", "good", "poor"]) == "good"
    assert dominant_grade(["good", "poor"]) == "poor"  # tie -> most severe
    assert dominant_grade([None, None]) == "none"
    assert dominant_grade([]) == "none"


# ---------- report ----------


def test_report(dataset: Path, tmp_path: Path, capsys) -> None:
    from qc_ml import split

    assert split.main(["--dataset-dir", str(dataset), "--splits-dir", str(tmp_path / "s")]) == 0
    out = tmp_path / "reports" / "data_report.json"
    argv = ["report", "--dataset-dir", str(dataset), "--split", str(tmp_path / "s/split_v1.csv")]
    assert data.main([*argv, "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report) == {
        "generated_at",
        "manifest_sha256",
        "split_file",
        "split_sha256",
        "n_images",
        "n_items",
        "n_overridden",
        "n_excluded",
        "counts",
        "items_per_grade",
        "images_per_item",
        "below_target",
        "below_minimum",
        "counts_by_origin",
        "n_contributors",
        "by_source",
        "external_fraction_train",
        "tool_grade_coverage",  # SPEC-016 section 4.6
    }
    assert report["n_images"] == 88 and report["n_items"] == 44
    assert report["split_file"] == "split_v1.csv"
    assert len(report["split_sha256"]) == 64
    assert len(report["below_target"]) == 10
    assert {(e["object_type"], e["grade"]) for e in report["below_target"]} == {
        (t, g) for t in ("screw", "nut") for g in data.GRADES
    }
    assert report["below_target"][0] == {
        "object_type": "screw",
        "grade": "perfect",
        "n_images": 8,
        "n_items": 4,
    }
    assert len(report["below_minimum"]) == 10
    assert report["counts"]["other"]["none"]["total"] == 8
    assert sum(report["counts"]["screw"]["fair"][s] for s in ("train", "val", "test")) == 8
    assert report["items_per_grade"]["nut"]["poor"] == 4
    assert report["images_per_item"] == {"min": 2, "median": 2.0, "mean": 2.0, "max": 2}
    text = out.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(dataset) not in text


def test_report_without_split(dataset: Path) -> None:
    report = build_data_report(load_manifest(dataset))
    assert report["split_file"] is None and report["split_sha256"] is None
    assert report["counts"]["screw"]["good"] == {"total": 8}


def test_report_with_outdated_split(dataset: Path) -> None:
    df = load_manifest(dataset)
    split_df = pd.DataFrame({"image_path": list(df["image_path"])[1:], "split": "train"})
    with pytest.raises(SplitError, match="split outdated"):
        build_data_report(df, split_df)


def test_cli_validate_ok_and_missing_manifest(dataset: Path, tmp_path: Path, capsys) -> None:
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 0
    assert "manifest ok: 88 images, 44 items" in capsys.readouterr().out
    assert data.main(["validate", "--dataset-dir", str(tmp_path / "nothing")]) == 2
    assert data.main(["bogus"]) == 2

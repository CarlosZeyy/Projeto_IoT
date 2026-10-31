"""Author tests of SPEC-040 Part B: ``n_items_test_by_grade`` and ``warnings`` in the CHANGELOG
(section 4.6), a type already extended is never new (section 4.7) and the line continuations of
``ml/README.md`` (section 4.8).

Synthetic data and ``tmp_path`` only; no torch."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from qc_ml import report as report_mod
from qc_ml import split
from qc_ml.data import load_manifest
from qc_ml.split import (
    load_split,
    new_object_types,
    recorded_deferred_types,
    recorded_extended_types,
    type_decision_problems,
)
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

ML = Path(__file__).resolve().parents[1]
COUNT_LINE = "report failed: invalid count in metrics.json: "
WARNING_LINE = "report failed: invalid warning in metrics.json: "
BASE: dict = {
    "model_version": "partqc-test-v1",
    "evaluated_at": "2026-11-02T13:00:00+00:00",
    "n_items_test_by_grade": {"perfect": 3, "good": 2},
    "warnings": ["few test items for pliers: 1"],
}
ORIGIN_COUNTS: dict = {
    "train": {"n_images": 10, "by_origin": {"external": 0}, "by_source": {}},
    "val": {"n_images": 5, "by_origin": {"external": 0}, "by_source": {}},
    "test": {"n_images": 5, "by_origin": {"external": 0}, "by_source": {}},
}


# ---------------------------------------------------------------------------------------------
# Section 4.6: changelog
# ---------------------------------------------------------------------------------------------


def _changelog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], metrics: dict
) -> tuple[int, str, list[str], bytes, bytes]:
    """Run ``changelog --append``: exit, stdout, stderr lines, CHANGELOG before and after."""
    model_dir = tmp_path / "model"
    model_dir.mkdir(exist_ok=True)
    (model_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes("# Histórico\n\nconteúdo\n".encode())
    before = target.read_bytes()
    code = report_mod.main(
        [
            "changelog",
            "--model-dir",
            str(model_dir),
            "--append",
            str(target),
            "--external-sources",
            str(tmp_path / "absent.csv"),
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err.splitlines(), before, target.read_bytes()


@pytest.mark.parametrize(
    ("value", "fields"),
    [
        ({"good": -1}, ["n_items_test_by_grade.good"]),
        ({"good": "3\n## forged"}, ["n_items_test_by_grade.good"]),
        ({"good": 2.0}, ["n_items_test_by_grade.good"]),
        ({"good": True}, ["n_items_test_by_grade.good"]),
        ({"good": None}, ["n_items_test_by_grade.good"]),
        ({"bad\nkey": 1}, ["n_items_test_by_grade"]),
        (["good", 1], ["n_items_test_by_grade"]),
        ("text", ["n_items_test_by_grade"]),
        (3, ["n_items_test_by_grade"]),
        (0, ["n_items_test_by_grade"]),
        (False, ["n_items_test_by_grade"]),
        # both kinds: the field once, then the grades in the order of Grade
        (
            {"unusable": -1, "bad": 1, "worse": 2, "perfect": "x"},
            [
                "n_items_test_by_grade",
                "n_items_test_by_grade.perfect",
                "n_items_test_by_grade.unusable",
            ],
        ),
    ],
)
def test_invalid_grade_counts_write_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: object, fields: list[str]
) -> None:
    metrics = {**BASE, "n_items_test_by_grade": value}
    code, out, err, before, after = _changelog(tmp_path, capsys, metrics)
    assert code == 2
    assert out == ""
    assert after == before
    assert err == [COUNT_LINE + field for field in fields]
    assert "forged" not in "\n".join(err)


@pytest.mark.parametrize("value", [None, {}, [], ""])
def test_empty_grade_counts_show_no_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: object
) -> None:
    code, out, err, _, _ = _changelog(tmp_path, capsys, {**BASE, "n_items_test_by_grade": value})
    assert code == 0
    assert err == []
    assert "Peças no teste por grau" not in out


def test_absent_grade_counts_and_warnings_are_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err, _, _ = _changelog(tmp_path, capsys, {"model_version": "partqc-test-v1"})
    assert code == 0
    assert err == []
    assert "Peças no teste por grau" not in out
    assert "- _(a preencher)_" in out


def test_valid_grade_counts_keep_the_line_and_its_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metrics = {**BASE, "n_items_test_by_grade": {"good": 2, "fair": 0}}
    code, out, _, _, after = _changelog(tmp_path, capsys, metrics)
    assert code == 0
    assert "Peças no teste por grau: good: 2, fair: 0." in out
    assert "Peças no teste por grau: good: 2, fair: 0." in after.decode()


@pytest.mark.parametrize(
    ("value", "fields"),
    [
        (["ok", "line\n## forged"], ["warnings.1"]),
        (["a\rb"], ["warnings.0"]),
        (["a\tb"], ["warnings.0"]),
        (["a\u0085b"], ["warnings.0"]),
        (["a b"], ["warnings.0"]),
        (["a b"], ["warnings.0"]),
        (["a\u001b[31m"], ["warnings.0"]),
        (["a‮b"], ["warnings.0"]),
        (["a​b"], ["warnings.0"]),
        (["a\ud800b"], ["warnings.0"]),
        ([3], ["warnings.0"]),
        ([None], ["warnings.0"]),
        ([["nested"]], ["warnings.0"]),
        (["a\nb", "ok", {"code": "x"}], ["warnings.0", "warnings.2"]),
        ("text", ["warnings"]),
        ("", ["warnings"]),
        ({}, ["warnings"]),
        (None, ["warnings"]),
        (0, ["warnings"]),
    ],
)
def test_invalid_warnings_write_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: object, fields: list[str]
) -> None:
    code, out, err, before, after = _changelog(tmp_path, capsys, {**BASE, "warnings": value})
    assert code == 2
    assert out == ""
    assert after == before
    assert err == [WARNING_LINE + field for field in fields]
    assert "forged" not in "\n".join(err)


def test_valid_warnings_keep_their_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metrics = {
        **BASE,
        # a non-breaking space (Zs) is not in the refused categories
        "warnings": ["few test items for pliers: 1", "acentuação ok", "a b"],
    }
    code, out, err, _, _ = _changelog(tmp_path, capsys, metrics)
    assert code == 0
    assert err == []
    lines = out.splitlines()
    assert "- few test items for pliers: 1" in lines
    assert "- acentuação ok" in lines
    assert "- a b" in lines


def test_every_invalid_field_in_the_order_of_the_spec(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    counts = json.loads(json.dumps(ORIGIN_COUNTS))
    counts["train"]["n_images"] = -1
    metrics = {
        **BASE,
        "counts": counts,
        "n_items_test_by_grade": {"good": -1},
        "warnings": ["a\nb"],
    }
    code, out, err, before, after = _changelog(tmp_path, capsys, metrics)
    assert code == 2
    assert out == ""
    assert after == before
    assert err == [
        COUNT_LINE + "counts.train.n_images",
        COUNT_LINE + "n_items_test_by_grade.good",
        WARNING_LINE + "warnings.0",
    ]


def test_invalid_warning_is_found_with_the_data_section_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metrics = {**BASE, "counts": ORIGIN_COUNTS, "warnings": ["a\nb"]}
    code, _, err, _, _ = _changelog(tmp_path, capsys, metrics)
    assert code == 2
    assert err == [WARNING_LINE + "warnings.0"]


def test_changelog_entry_raises_before_any_line() -> None:
    with pytest.raises(report_mod.InvalidCountsError) as info:
        report_mod.changelog_entry({**BASE, "n_items_test_by_grade": {"good": -1}, "warnings": [1]})
    assert info.value.fields == ["n_items_test_by_grade.good"]
    assert info.value.warning_fields == ["warnings.0"]
    assert str(info.value).splitlines() == [
        "invalid count in metrics.json: n_items_test_by_grade.good",
        "invalid warning in metrics.json: warnings.0",
    ]


def test_release_notes_does_not_check_these_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    bad = {"n_items_test_by_grade": {"bad\nkey": -1}, "warnings": ["a\nb"]}
    (model_dir / "metrics.json").write_text(json.dumps(bad), encoding="utf-8")
    (model_dir / "model.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    code = report_mod.main(
        [
            "release-notes",
            "--model-dir",
            str(model_dir),
            "--external-sources",
            str(tmp_path / "absent.csv"),
        ]
    )
    assert code == 0
    assert "bad" not in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# Section 4.7: a type already extended is never new
# ---------------------------------------------------------------------------------------------


def _cli(dataset: Path, splits: Path, *extra: str) -> int:
    return split.main(["--dataset-dir", str(dataset), "--splits-dir", str(splits), *extra])


def _split_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["image_path"]: row["split"] for row in csv.DictReader(fh)}


def _new_files(splits: Path) -> list[str]:
    return sorted(p.name for p in splits.iterdir() if p.name.startswith("split_v3"))


@pytest.fixture
def extended_then_excluded(tmp_path: Path) -> tuple[Path, Path, list[str], list[str]]:
    """``split_v1`` without tools, ``split_v2`` extending ``pliers`` (3 items), then every old
    ``pliers`` image excluded and deleted and 3 new ``T-`` items of ``pliers`` added."""
    dataset = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=8)
    splits = tmp_path / "splits"
    assert _cli(dataset, splits) == 0
    old: list[str] = []
    for number in range(1, 4):
        old += add_synthetic_item(dataset, f"T-{number:03d}", "pliers", "good")
    assert _cli(dataset, splits, "--extend-test-types", "pliers") == 0
    assert "test" in {_split_map(splits / "split_v2.csv")[p] for p in old}
    rows = "".join(f"{path},other\n" for path in old)
    (dataset / "exclusions.csv").write_text(f"image_path,reason\n{rows}", encoding="utf-8")
    for path in old:
        (dataset / path).unlink()
    new: list[str] = []
    for number in range(11, 14):
        new += add_synthetic_item(dataset, f"T-{number:03d}", "pliers", "good")
    return dataset, splits, old, new


def _forget_extension(splits: Path, *, value: object = ...) -> None:
    """``split_v2.json`` without the key, or with ``value`` in it."""
    meta_path = splits / "split_v2.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["test_extended_types"]
    if value is not ...:
        meta["test_extended_types"] = value
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def test_second_extension_is_refused(
    extended_then_excluded: tuple[Path, Path, list[str], list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, splits, _, _ = extended_then_excluded
    capsys.readouterr()
    assert _cli(dataset, splits, "--extend-test-types", "pliers") == 2
    assert "object type is not new: pliers" in capsys.readouterr().err.splitlines()
    assert _new_files(splits) == []


def test_deferring_an_extended_type_is_refused(
    extended_then_excluded: tuple[Path, Path, list[str], list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, splits, _, _ = extended_then_excluded
    capsys.readouterr()
    assert _cli(dataset, splits, "--defer-types", "pliers") == 2
    assert "object type is not new: pliers" in capsys.readouterr().err.splitlines()
    assert _new_files(splits) == []


def test_new_items_of_an_extended_type_follow_adr_014(
    extended_then_excluded: tuple[Path, Path, list[str], list[str]],
) -> None:
    dataset, splits, old, new = extended_then_excluded
    v1 = _split_map(splits / "split_v1.csv")
    v2 = _split_map(splits / "split_v2.csv")
    assert _cli(dataset, splits) == 0
    v3 = _split_map(splits / "split_v3.csv")
    assert {v3[p] for p in new} <= {"train", "val"}
    assert not set(old) & set(v3)
    for path, name in {**v1, **v2}.items():
        if path not in old:
            assert v3[path] == name
    meta = json.loads((splits / "split_v3.json").read_text(encoding="utf-8"))
    assert meta["test_extended_types"] == []
    # an extension recorded in any earlier version counts: v2 stays the only one with the key
    add_synthetic_item(dataset, "T-021", "pliers", "good")
    assert _cli(dataset, splits, "--extend-test-types", "pliers") == 2
    assert _cli(dataset, splits) == 0
    assert _split_map(splits / "split_v4.csv")[new[0]] == v3[new[0]]


@pytest.mark.parametrize("value", [..., "pliers", [1], {"pliers": 1}, None])
def test_extension_without_a_readable_record_is_new_again(
    extended_then_excluded: tuple[Path, Path, list[str], list[str]],
    capsys: pytest.CaptureFixture[str],
    value: object,
) -> None:
    dataset, splits, _, new = extended_then_excluded
    _forget_extension(splits, value=value)
    capsys.readouterr()
    assert _cli(dataset, splits) == 2
    assert "new object type without decision: pliers" in capsys.readouterr().err.splitlines()
    assert _new_files(splits) == []
    assert _cli(dataset, splits, "--extend-test-types", "pliers") == 0
    assert "test" in {_split_map(splits / "split_v3.csv")[p] for p in new}


@pytest.mark.parametrize("damage", ["missing", "not json", "not utf-8", "not an object"])
def test_unusable_json_counts_as_an_empty_list(tmp_path: Path, damage: str) -> None:
    (tmp_path / "split_v1.json").write_text(
        json.dumps({"test_extended_types": ["drill"]}), encoding="utf-8"
    )
    path = tmp_path / "split_v2.json"
    if damage == "not json":
        path.write_text("{", encoding="utf-8")
    elif damage == "not utf-8":
        path.write_bytes(b'{"test_extended_types": ["\xff"]}')
    elif damage == "not an object":
        path.write_text('["pliers"]', encoding="utf-8")
    assert recorded_extended_types(tmp_path, [1, 2]) == {"drill"}
    assert recorded_deferred_types(path.with_suffix(".csv")) is None


def test_recorded_extended_types_is_the_union_of_the_versions(tmp_path: Path) -> None:
    (tmp_path / "split_v1.json").write_text(
        json.dumps({"test_extended_types": []}), encoding="utf-8"
    )
    (tmp_path / "split_v2.json").write_text(
        json.dumps({"test_extended_types": ["pliers"]}), encoding="utf-8"
    )
    (tmp_path / "split_v3.json").write_text(json.dumps({"seed": 42}), encoding="utf-8")
    (tmp_path / "split_v4.json").write_text(
        json.dumps({"test_extended_types": ["drill", "saw"]}), encoding="utf-8"
    )
    assert recorded_extended_types(tmp_path, [1, 2, 3, 4]) == {"pliers", "drill", "saw"}
    assert recorded_extended_types(tmp_path, []) == set()


def test_deferred_types_keep_their_contract(tmp_path: Path) -> None:
    path = tmp_path / "split_v1.json"
    path.write_text(json.dumps({"seed": 42}), encoding="utf-8")
    assert recorded_deferred_types(path.with_suffix(".csv")) == []
    path.write_text(json.dumps({"deferred_types": ["drill"]}), encoding="utf-8")
    assert recorded_deferred_types(path.with_suffix(".csv")) == ["drill"]
    path.write_text(json.dumps({"deferred_types": [1]}), encoding="utf-8")
    assert recorded_deferred_types(path.with_suffix(".csv")) is None


def test_extended_before_is_optional_and_by_name(tmp_path: Path) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=4, tool_items_per_stratum=1)
    plain = make_synthetic_dataset(tmp_path / "plain", items_per_stratum=4)
    assert _cli(plain, tmp_path / "splits") == 0
    df = load_manifest(dataset)
    v1 = load_split(tmp_path / "splits" / "split_v1.csv")
    assert "pliers" in new_object_types(df, [v1])
    assert "pliers" not in new_object_types(df, [v1], extended_before={"pliers"})
    without_lists = type_decision_problems(df, [v1], extended_before={"pliers"})
    assert "new object type without decision: pliers" not in without_lists
    listed = type_decision_problems(df, [v1], ["pliers"], extended_before=["pliers"])
    assert "object type is not new: pliers" in listed
    # no earlier version: split_v1 does not use the lists
    assert type_decision_problems(df, [], ["pliers"], extended_before={"pliers"}) == []
    with pytest.raises(TypeError):
        type_decision_problems(df, [v1], [], [], {"pliers"})  # type: ignore[misc]


def test_split_v1_does_not_change(tmp_path: Path) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds", tool_items_per_stratum=1)
    assert _cli(dataset, tmp_path / "s1") == 0
    assert _cli(dataset, tmp_path / "s1") == 0  # no new version: nothing changed
    assert sorted(p.name for p in (tmp_path / "s1").iterdir()) == [
        "split_v1.csv",
        "split_v1.json",
        "split_v1.sha256",
    ]


# ---------------------------------------------------------------------------------------------
# Section 4.8: README
# ---------------------------------------------------------------------------------------------


def _code_lines() -> list[str]:
    text = (ML / "README.md").read_text(encoding="utf-8")
    return [
        line for block in re.findall(r"```bash\n(.*?)```", text, re.S) for line in block.split("\n")
    ]


def test_readme_examples_have_line_continuations() -> None:
    lines = _code_lines()
    found = 0
    for index, line in enumerate(lines):
        if "--defer-types" in line or "--extend-test-types" in line:
            found += 1
            stripped = line.lstrip()
            assert stripped.startswith(("--defer-types", "--extend-test-types")), line
            assert lines[index - 1].endswith(" \\"), lines[index - 1]
            assert stripped.count("--") == 1, line
    assert found == 3  # one --defer-types in the first example, both options in the second
    for line in lines:
        if "python -m qc_ml.split" in line:
            assert "  " not in line.lstrip(), line

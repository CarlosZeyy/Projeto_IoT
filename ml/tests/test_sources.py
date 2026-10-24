"""Author tests of SPEC-035 sections 4.1-4.3 and 4.7: item_id of external images, sources.csv,
the registry of external sources and the synthetic generator. Synthetic data only, no torch."""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from qc_ml import data
from qc_ml import split as split_mod
from qc_ml.data import (
    ALLOWED_LICENSES,
    EXTERNAL_SOURCE_COLUMNS,
    ITEM_ID_PATTERN,
    SOURCE_COLUMNS,
    ExternalSource,
    is_external_item,
    item_type_letter,
    load_external_sources,
    load_manifest,
    load_sources,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import make_synthetic_dataset

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_HEADER = "source_id,title,url,license,license_url,attribution,retrieved_at"
SOURCE = {
    "source_id": "synthetic",
    "title": "Synthetic dataset",
    "url": "https://example.org/synthetic",
    "license": "CC0-1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "attribution": "Synthetic test images",
    "retrieved_at": "2026-10-20",
}


@pytest.fixture(scope="module")
def _mixed_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("mixed") / "ds",
        contributor_items_per_stratum=1,
        external_items_per_stratum=1,
    )


@pytest.fixture
def mixed(_mixed_template: Path, tmp_path: Path) -> Path:
    """CA-02 dataset: 4/2 with one contributor and one external item per stratum (121 rows)."""
    return Path(shutil.copytree(_mixed_template, tmp_path / "ds"))


def _load(root: Path, **kwargs) -> object:
    return load_manifest(root, external_sources=root / "external_sources.csv", **kwargs)


def _codes(root: Path) -> list[str]:
    with pytest.raises(ManifestError) as info:
        _load(root)
    return [p.code for p in info.value.problems]


def _problems(root: Path) -> list:
    with pytest.raises(ManifestError) as info:
        _load(root)
    return info.value.problems


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        records = list(csv.reader(fh))
    return records[0], records[1:]


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _edit_sources(root: Path, edit) -> None:
    header, rows = _read(root / "sources.csv")
    rows = [dict(zip(header, r, strict=True)) for r in rows]
    rows = edit(rows)
    _write(root / "sources.csv", header, [[r[c] for c in header] for r in rows])


def _first(rows: list[dict[str, str]], origin: str) -> dict[str, str]:
    return next(r for r in rows if r["origin"] == origin)


def _write_registry(root: Path, *sources: dict[str, str]) -> None:
    _write(
        root / "external_sources.csv",
        list(EXTERNAL_SOURCE_COLUMNS),
        [[s[c] for c in EXTERNAL_SOURCE_COLUMNS] for s in sources],
    )


# ---------- CA-01: item_id ----------


def test_ca01_item_id_pattern() -> None:
    for good in ("S-012", "O-500", "XS-0001", "XN-9999", "XO-0042", "XT-0001", "T-001"):
        assert ITEM_ID_PATTERN.fullmatch(good), good
    for bad in (
        "XS-001",
        "XS-00001",
        "X-0001",
        "XX-0001",
        "xS-0001",
        "SX-0001",
        "XS-0001\n",
        "XS-０００１",
        "S-0001",
        "",
    ):
        assert not ITEM_ID_PATTERN.fullmatch(bad), bad
    assert is_external_item("XN-0002") is True
    assert is_external_item("N-002") is False
    assert is_external_item("XN-002") is False
    assert item_type_letter("XO-0042") == "O"
    assert item_type_letter("S-001") == "S"
    assert split_mod.ITEM_ID_PATTERN is data.ITEM_ID_PATTERN
    match = split_mod.IMAGE_FILE_PATTERN.fullmatch("XS-0001__0__20261022T141503Z.jpg")
    assert match and match.group(1) == "XS-0001"
    assert split_mod.IMAGE_FILE_PATTERN.fullmatch("XS-001__0__20261022T141503Z.jpg") is None
    match = split_mod.IMAGE_FILE_PATTERN.fullmatch("S-012__3__20261020T101112Z.jpg")
    assert match and match.group(1) == "S-012"


@pytest.mark.parametrize(
    ("item_id", "object_type", "ok"),
    [
        ("XS-0001", "screw", True),
        ("XN-0001", "nut", True),
        ("XO-0001", "other", True),
        ("XS-0001", "nut", False),
        ("XT-0001", "screw", False),
    ],
)
def test_prefix_of_external_item(dataset: Path, rows_io, item_id, object_type, ok) -> None:
    read_rows, write_rows, _ = rows_io
    rows = read_rows(dataset)
    row = next(r for r in rows if r["object_type"] == object_type)
    row["item_id"] = item_id
    write_rows(dataset, rows)
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset)
    codes = {p.code for p in info.value.problems}
    # Without sources.csv an external item is always missing_source; the prefix check is apart.
    assert ("item_prefix_mismatch" in codes) is (not ok)
    if item_id.startswith("X"):
        assert "missing_source" in codes


# ---------- CA-02 / CA-03: columns and attrs ----------


def test_ca02_origin_columns(mixed: Path) -> None:
    df = _load(mixed)
    assert len(df) == 121
    assert df["origin"].value_counts().to_dict() == {
        "capture": 88,
        "contributor": 22,
        "external": 11,
    }
    contributors = df[df["origin"] == "contributor"]
    assert set(contributors["contributor"]) == {"c01"}
    assert df.loc[df["origin"] != "contributor", "contributor"].isna().all()
    assert set(df.loc[df["origin"] == "external", "source_id"]) == {"synthetic"}
    assert df.loc[df["origin"] != "external", "source_id"].isna().all()
    assert (
        df.attrs["sources_sha256"]
        == hashlib.sha256((mixed / "sources.csv").read_bytes()).hexdigest()
    )
    assert (
        df.attrs["external_sources_sha256"]
        == hashlib.sha256((mixed / "external_sources.csv").read_bytes()).hexdigest()
    )
    assert list(df.columns)[-3:] == ["origin", "contributor", "source_id"]
    assert all(is_external_item(i) for i in df.loc[df["origin"] == "external", "item_id"])


def test_ca03_without_sources(dataset: Path, tmp_path: Path) -> None:
    df = load_manifest(dataset, external_sources=tmp_path / "absent.csv")
    assert len(df) == 88
    assert set(df["origin"]) == {"capture"}
    assert df["contributor"].isna().all() and df["source_id"].isna().all()
    assert df.attrs["sources_sha256"] is None
    assert df.attrs["external_sources_sha256"] is None


def test_default_registry_is_the_repository_one(dataset: Path) -> None:
    assert data.DEFAULT_EXTERNAL_SOURCES == ROOT / "ml" / "external_sources.csv"
    df = load_manifest(dataset)
    expected = hashlib.sha256(data.DEFAULT_EXTERNAL_SOURCES.read_bytes()).hexdigest()
    assert df.attrs["external_sources_sha256"] == expected


# ---------- CA-04: sources.csv problems ----------

NEW_SHA = "f" * 64


def _set(which: str, **values: str):
    def edit(rows):
        _first(rows, which).update(values)
        return rows

    return edit


def _drop_external(rows):
    target = next(r for r in rows if "/XS-" in r["image_path"])
    return [r for r in rows if r is not target]


def _repeat_input(rows):
    rows[1]["input_sha256"] = rows[0]["input_sha256"]
    return rows


def _repeat_path(rows):
    return [*rows, {**rows[0], "input_sha256": NEW_SHA}]


def _unknown_image(rows):
    return [
        *rows,
        {**_first(rows, "contributor"), "image_path": "raw/x/none.jpg"} | {"input_sha256": NEW_SHA},
    ]


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (_set("external", source_id="desconhecida"), "unknown_source_id"),
        (_set("external", source_id=""), "unknown_source_id"),
        (_set("external", source_ref=""), "invalid_source_ref"),
        (_set("external", source_ref="a‮b"), "invalid_source_ref"),
        (_set("external", source_ref="x" * 201), "invalid_source_ref"),
        (_set("external", contributor="c01"), "invalid_contributor"),
        (_set("contributor", contributor="C01"), "invalid_contributor"),
        (_set("contributor", contributor=""), "invalid_contributor"),
        (_set("contributor", source_id="synthetic"), "source_fields_mismatch"),
        (_set("contributor", source_ref="a.png"), "source_fields_mismatch"),
        (_set("contributor", origin="capture"), "invalid_origin"),
        (_set("contributor", origin=""), "invalid_origin"),
        (_set("contributor", input_sha256="a" * 63), "invalid_input_sha256"),
        (_set("contributor", input_sha256="A" * 64), "invalid_input_sha256"),
        (_repeat_input, "duplicate_input"),
        (_repeat_path, "duplicate_source_row"),
        (_unknown_image, "source_unknown_image"),
        (_drop_external, "missing_source"),
        (_set("contributor", image_path="../x.jpg"), "invalid_image_path"),
    ],
)
def test_ca04_sources_problems(mixed: Path, edit, code: str) -> None:
    _edit_sources(mixed, edit)
    problems = _problems(mixed)
    assert code in [p.code for p in problems]
    files = {p.file for p in problems if p.code == code}
    assert files == ({"manifest.csv"} if code == "missing_source" else {"sources.csv"})


def test_ca04_own_image_marked_external(mixed: Path) -> None:
    df = _load(mixed)
    own = df[df["item_id"] == "S-001"].iloc[0]["image_path"]

    def edit(rows):
        return [*rows, {**_first(rows, "external"), "image_path": own, "input_sha256": NEW_SHA}]

    _edit_sources(mixed, edit)
    assert "external_item_mismatch" in _codes(mixed)


def test_contributor_line_for_external_item(mixed: Path) -> None:
    def edit(rows):
        row = _first(rows, "external")
        row.update(origin="contributor", contributor="c02", source_id="", source_ref="")
        return rows

    _edit_sources(mixed, edit)
    assert _codes(mixed) == ["external_item_mismatch"]


def test_ca04_missing_column(mixed: Path) -> None:
    header, rows = _read(mixed / "sources.csv")
    _write(mixed / "sources.csv", header[:-1], [r[:-1] for r in rows])
    codes = _codes(mixed)
    assert "missing_column" in codes
    assert "missing_source" not in codes  # no noise from an unreadable sources.csv


def test_ca04_validate_cli_counts(mixed: Path, capsys) -> None:
    _edit_sources(mixed, _drop_external)
    argv = ["validate", "--dataset-dir", str(mixed)]
    assert data.main([*argv, "--external-sources", str(mixed / "external_sources.csv")]) == 2
    assert "count missing_source: 1" in capsys.readouterr().out.splitlines()


def test_validate_cli_ok_with_sources(mixed: Path, capsys) -> None:
    argv = ["validate", "--dataset-dir", str(mixed)]
    assert data.main([*argv, "--external-sources", str(mixed / "external_sources.csv")]) == 0
    assert "manifest ok: 121 images" in capsys.readouterr().out


def test_external_without_registry_is_unknown_source(mixed: Path, tmp_path: Path) -> None:
    with pytest.raises(ManifestError) as info:
        load_manifest(mixed, external_sources=tmp_path / "absent.csv")
    codes = {p.code for p in info.value.problems}
    assert codes == {"unknown_source_id"}
    assert len(info.value.problems) == 11


def test_load_sources(mixed: Path) -> None:
    registry = load_external_sources(mixed / "external_sources.csv")
    frame = load_sources(mixed, registry)
    assert list(frame.columns) == list(SOURCE_COLUMNS)
    assert len(frame) == 33
    assert (
        frame.attrs["sources_sha256"]
        == hashlib.sha256((mixed / "sources.csv").read_bytes()).hexdigest()
    )
    with pytest.raises(ManifestError) as info:
        load_sources(mixed, {})
    assert {p.code for p in info.value.problems} == {"unknown_source_id"}


def test_load_sources_absent(dataset: Path) -> None:
    frame = load_sources(dataset, {})
    assert frame.empty and frame.attrs["sources_sha256"] is None


# ---------- CA-05: registry ----------


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("license", "CC-BY-ND-4.0", "invalid_license"),
        ("license", "unknown", "invalid_license"),
        ("license", "", "invalid_license"),
        ("license", "CC-BY-NC-SA-4.0", "invalid_license"),
        ("license", "CC-BY-SA-4.0", "invalid_license"),
        ("license", "CC-BY-NC-4.0", "invalid_license"),
        ("license", "cc0-1.0", "invalid_license"),
        ("url", "http://example.org/x", "invalid_url"),
        ("url", "https://", "invalid_url"),
        ("url", "https://example.org/a b", "invalid_url"),
        ("url", "https://example.org/" + "a" * 281, "invalid_url"),
        ("license_url", "ftp://example.org", "invalid_url"),
        ("retrieved_at", "2026-02-30", "invalid_date"),
        ("retrieved_at", "2026-1-01", "invalid_date"),
        ("source_id", "Synthetic", "invalid_source_id"),
        ("source_id", "ab", "invalid_source_id"),
        ("source_id", "-abc", "invalid_source_id"),
        ("attribution", "line\nbreak", "invalid_text"),
        ("attribution", "", "invalid_text"),
        ("attribution", "a" * 501, "invalid_text"),
        ("title", "a b", "invalid_text"),
        ("title", "", "invalid_text"),
    ],
)
def test_ca05_registry_problems(mixed: Path, field: str, value: str, code: str) -> None:
    _write_registry(mixed, {**SOURCE, field: value})
    problems = _problems(mixed)
    assert code in [p.code for p in problems]
    assert {p.file for p in problems if p.code == code} == {"external_sources.csv"}
    with pytest.raises(ManifestError):
        load_external_sources(mixed / "external_sources.csv")


def test_ca05_duplicate_source_id(mixed: Path) -> None:
    _write_registry(mixed, SOURCE, SOURCE)
    problems = _problems(mixed)
    assert [p.code for p in problems] == ["duplicate_source_id"]
    assert problems[0].file == "external_sources.csv" and problems[0].line == 3


def test_ca05_header_only_registry_without_externals(dataset: Path, tmp_path: Path) -> None:
    registry = tmp_path / "external_sources.csv"
    registry.write_text(REGISTRY_HEADER + "\n", encoding="utf-8")
    assert len(load_manifest(dataset, external_sources=registry)) == 88
    assert load_external_sources(registry) == {}


def test_registry_is_validated_even_when_unused(dataset: Path, tmp_path: Path) -> None:
    registry = tmp_path / "external_sources.csv"
    _write(
        registry,
        list(EXTERNAL_SOURCE_COLUMNS),
        [[{**SOURCE, "license": "CC-BY-SA-4.0"}[c] for c in EXTERNAL_SOURCE_COLUMNS]],
    )
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset, external_sources=registry)
    assert [p.code for p in info.value.problems] == ["invalid_license"]


def test_load_external_sources_values(mixed: Path, tmp_path: Path) -> None:
    from datetime import date

    registry = load_external_sources(mixed / "external_sources.csv")
    assert registry == {
        "synthetic": ExternalSource(**{**SOURCE, "retrieved_at": date(2026, 10, 20)})
    }
    assert load_external_sources(tmp_path / "absent.csv") == {}
    for license_id in ALLOWED_LICENSES:
        _write_registry(mixed, {**SOURCE, "license": license_id})
        assert load_external_sources(mixed / "external_sources.csv")["synthetic"].license == (
            license_id
        )


# ---------- CA-06: exclusion ----------


def test_ca06_excluded_external_image(mixed: Path) -> None:
    df = _load(mixed)
    image = df[df["item_id"] == "XS-0001"].iloc[0]["image_path"]
    (mixed / image).unlink()
    _write(mixed / "exclusions.csv", ["image_path", "reason"], [[image, "other"]])
    df = _load(mixed)
    assert len(df) == 120
    assert "XS-0001" not in set(df["item_id"])


def test_excluded_lines_are_not_checked(mixed: Path) -> None:
    df = _load(mixed)
    image = df[df["item_id"] == "S-501"].iloc[0]["image_path"]
    (mixed / image).unlink()
    _write(mixed / "exclusions.csv", ["image_path", "reason"], [[image, "other"]])

    def edit(rows):
        row = next(r for r in rows if r["image_path"] == image)
        row.update(contributor="BAD", input_sha256=rows[0]["input_sha256"])
        return rows

    _edit_sources(mixed, edit)
    assert len(_load(mixed)) == 120


# ---------- CA-14: registry of the repository ----------


def test_ca14_repository_registry() -> None:
    path = ROOT / "ml" / "external_sources.csv"
    assert path.read_text(encoding="utf-8").splitlines()[0] == REGISTRY_HEADER
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    load_external_sources(path)
    result = subprocess.run(
        ["git", "check-ignore", "ml/external_sources.csv"], cwd=ROOT, capture_output=True
    )
    assert result.returncode == 1


# ---------- CA-15 and section 4.7: generator ----------


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_ca15_default_generator_unchanged(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b", external_items_per_stratum=0, contributor_items_per_stratum=0
    )
    assert _tree(a) == _tree(b)
    for root in (a, b):
        assert not (root / "sources.csv").exists()
        assert not (root / "external_sources.csv").exists()


def test_generator_layout(mixed: Path, _template: Path) -> None:
    header, rows = _read(mixed / "sources.csv")
    assert header == list(SOURCE_COLUMNS)
    contributors = [r for r in rows if r[1] == "contributor"]
    externals = [r for r in rows if r[1] == "external"]
    assert len(contributors) == 22 and len(externals) == 11
    for row in rows:
        assert row[5] == hashlib.sha256((mixed / row[0]).read_bytes()).hexdigest()
    assert all(r[2] == "c01" and r[3] == r[4] == "" for r in contributors)
    assert {r[3] for r in externals} == {"synthetic"}
    df = _load(mixed)
    screw_contributors = sorted(set(df.loc[df["origin"] == "contributor", "item_id"]))
    assert [i for i in screw_contributors if i.startswith("S-")] == [
        "S-501",
        "S-502",
        "S-503",
        "S-504",
        "S-505",
    ]
    assert set(df.loc[df["item_id"] == "S-501", "grade"]) == {"perfect"}
    assert set(df.loc[df["item_id"] == "S-505", "grade"]) == {"unusable"}
    externals_df = df[df["origin"] == "external"]
    assert set(externals_df["angle"]) == {0}
    assert sorted(i for i in externals_df["item_id"] if i.startswith("XS-")) == [
        f"XS-{k:04d}" for k in range(1, 6)
    ]
    assert sorted(i for i in externals_df["item_id"] if i.startswith("XO-")) == ["XO-0001"]
    refs = {r[0]: r[4] for r in externals}
    for _, row in externals_df.iterrows():
        assert refs[row["image_path"]] == f"synthetic/{row['item_id']}.png"
    reg_header, reg_rows = _read(mixed / "external_sources.csv")
    assert reg_header == list(EXTERNAL_SOURCE_COLUMNS)
    assert reg_rows == [[SOURCE[c] for c in EXTERNAL_SOURCE_COLUMNS]]
    # The own images do not depend on the contributor and external items.
    own = {k: v for k, v in _tree(mixed).items() if k.startswith("raw/")}
    for name, content in _tree(_template).items():
        if name.startswith("raw/"):
            assert own[name] == content, name


def test_generator_contributors_only(tmp_path: Path) -> None:
    root = make_synthetic_dataset(tmp_path / "ds", contributor_items_per_stratum=1)
    assert (root / "sources.csv").is_file()
    assert not (root / "external_sources.csv").exists()
    assert len(load_manifest(root, external_sources=tmp_path / "absent.csv")) == 110


def test_generator_limits(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "a", external_items_per_stratum=-1)
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "b", contributor_items_per_stratum=100)

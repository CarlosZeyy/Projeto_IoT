"""Acceptance tests for SPEC-045 (official model with the contributors' photos), qc-ml part.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per CA, at least, for CAs 01 to 12. CA-13 (operation) and
CAs 14 to 16 (manual) happen after the merge and stay pending in the test report. Tests named
``test_extra_*`` are exploratory edge cases around sections 4.1 to 4.3 that no CA spells out.

Rules followed (``docs/architecture.md`` section 10, R-11 and R-14):

* every dataset is synthetic (``make_synthetic_dataset``) and lives under ``tmp_path``; nothing
  under ``ml/data/``, the inbox or the backup is read, and no real photo is used (section 4.5);
* the CLIs run through ``python -m`` in a subprocess, called as in ``test_spec_041.py``;
* the evaluation uses the ONNX fixture ``tiny_model_no_nut`` (no torch).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from qc_ml import split as split_mod
from qc_ml.data import (
    IDENTIFIED_TOOL_OBJECT_TYPES,
    KNOWN_OBJECT_TYPES,
    MANIFEST_COLUMNS,
    POWER_TOOL_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    derive_model_labels,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.split import split_stratum
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
TINY_NO_NUT = REPO_ROOT / "ml" / "tests" / "fixtures" / "tiny_model_no_nut"
OFFICIAL_VERSION = "partqc-tinyacc-v1"
GRADES = ("perfect", "good", "fair", "poor", "unusable")
SPLITS = ("train", "val", "test")
HAND_TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)
NEW_TOOLS = ("hammer", "wrench", "spirit_level")
EXPECTED_FLOOR = (
    ("screw", "perfect"),
    ("screw", "good"),
    ("screw", "fair"),
    ("screw", "poor"),
    ("screw", "unusable"),
    ("other", "none"),
)
NO_NUT_TYPES = ("screw", "other", "hammer", "wrench", "spirit_level")
# CA-07: SHA-256 of split_v1.csv produced by the code of the merge-base of this branch with main,
# commit 555c4b64e9f597756a3ea614d5e3ecaeb24590a6 (merge of PR #75, SPEC-044), computed by the
# tester in a detached worktree of that commit (PYTHONPATH pointing to its ml/src), for
# make_synthetic_dataset(items_per_stratum=3, images_per_item=3) and the default seed (42).
CA07_BASE_SHA256 = "7f18e97f68e275e26be2ae8042f0473467afce6d478f7fbb43f0d420bc6eddc9"
# Same commit and procedure, --seed 42 --allow-below-floor, other datasets with only screw, nut,
# other, contributors and ungraded tools (section 4.2, last bullet: byte for byte the same).
BASE_SHA256_MORE = {
    "default": (
        {},
        "6c516727e74b3929eca8bc801641c36e9840476fcfed53a680f931e5bab21dfe",
    ),
    "five_per_stratum_seed7": (
        {"items_per_stratum": 5, "images_per_item": 2, "seed": 7},
        "20bc4ed1552be8c0d5eba4a5e64ab89cdd8872e1f30f4dc54a14551d36fdd3f0",
    ),
    "contributors": (
        {"items_per_stratum": 3, "images_per_item": 3, "contributor_items_per_stratum": 1},
        "dbcaf6abd6a552c74fcdcd71896dd6d052e01ab2dd09e8f8fbdf9bbb2d80a04d",
    ),
    "power_and_identified": (
        {
            "items_per_stratum": 3,
            "images_per_item": 3,
            "power_tool_items_per_type": 3,
            "identified_tool_items_per_type": 3,
        },
        "9c1e4dcd8f2ebe10c2f45d165be8da86b7c528e54040a2c1748a21ffb57ac22e",
    ),
}


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["HF_HUB_OFFLINE"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_module(
    module: str, *args: object, cwd: Path, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *(str(a) for a in args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=_env(),
        timeout=timeout,
        check=False,
    )


def split_cli(ds: Path, splits: Path, *extra: object) -> subprocess.CompletedProcess[str]:
    return run_module(
        "qc_ml.split",
        "--dataset-dir",
        ds,
        "--splits-dir",
        splits,
        "--external-sources",
        ds / "external_sources.csv",
        *extra,
        cwd=ds.parent,
    )


def read_rows(ds: Path) -> list[dict[str, str]]:
    with (ds / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(ds: Path, rows: Iterable[dict[str, str]]) -> None:
    with (ds / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def drop_rows(ds: Path, should_drop: Callable[[dict[str, str]], bool]) -> list[dict[str, str]]:
    """Remove matching images from the manifest, from ``sources.csv`` and from the disk."""
    rows = read_rows(ds)
    dropped = [r for r in rows if should_drop(r)]
    assert dropped, "the predicate matched no manifest row"
    write_rows(ds, [r for r in rows if not should_drop(r)])
    gone = {r["image_path"] for r in dropped}
    for path in gone:
        (ds / path).unlink()
    sources = ds / "sources.csv"
    if sources.exists():
        with sources.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            header = list(reader.fieldnames or ())
            keep = [[r[c] for c in header] for r in reader if r["image_path"] not in gone]
        with sources.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(keep)
    return dropped


def read_split(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["image_path"]: r["split"] for r in csv.DictReader(fh)}


def read_meta(splits: Path, version: int = 1) -> dict[str, Any]:
    return json.loads((splits / f"split_v{version}.json").read_text(encoding="utf-8"))


def split_files(root: Path) -> list[Path]:
    return sorted(root.rglob("split_v*"))


def snapshot(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): (None if p.is_dir() else p.read_bytes())
        for p in sorted(root.rglob("*"))
    }


def item_info(ds: Path) -> dict[str, tuple[str, str]]:
    """``image_path -> (item_id, object_type)``."""
    return {r["image_path"]: (r["item_id"], r["object_type"]) for r in read_rows(ds)}


def items_by_split(ds: Path, assignment: dict[str, str]) -> dict[str, dict[str, set[str]]]:
    """``object_type -> split -> {item_id}`` for the images in ``assignment``."""
    info = item_info(ds)
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for path, which in assignment.items():
        item, kind = info[path]
        out[kind][which].add(item)
    return out


def warnings_with(meta: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [w for w in meta["warnings"] if isinstance(w, dict) and w.get("code") == code]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage_with(graded: dict[str, bool]) -> dict[str, dict[str, Any]]:
    """A ``tool_grade_coverage``-shaped mapping with every hand tool."""
    return {
        tool: {
            "graded": graded.get(tool, False),
            "by_grade": {g: {"n_images": 0, "n_items": 0} for g in GRADES},
        }
        for tool in HAND_TOOLS
    }


def tiny_config(root: Path, ds: Path, split_file: Path) -> SimpleNamespace:
    config = {
        "model_version": OFFICIAL_VERSION,
        "dataset_dir": str(ds),
        "split_file": str(split_file),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
    }
    path = root / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return SimpleNamespace(config=path, model_dir=root / "models" / OFFICIAL_VERSION, root=root)


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _no_nut_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acc045_no_nut")
    return make_synthetic_dataset(
        root / "ds", items_per_stratum=3, images_per_item=3, include_nut=False
    )


@pytest.fixture
def no_nut_ds(_no_nut_template: Path, tmp_path: Path) -> Path:
    """The CA-02 dataset: 18 items (15 screw, 3 other), 54 images, no nut."""
    return Path(shutil.copytree(_no_nut_template, tmp_path / "ds"))


@pytest.fixture(scope="session")
def _identified_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acc045_identified")
    return make_synthetic_dataset(
        root / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        identified_tool_items_per_type=3,
    )


@pytest.fixture
def identified_ds(_identified_template: Path, tmp_path: Path) -> Path:
    """The CA-08/CA-09 dataset: the CA-02 one plus 3 items of each identification-only tool."""
    return Path(shutil.copytree(_identified_template, tmp_path / "ds"))


# ---------------------------------------------------------------------------------------------
# CA-01 to CA-12
# ---------------------------------------------------------------------------------------------


def test_ca01_floor_is_the_fixed_list_without_nuts() -> None:
    assert tuple(tuple(s) for s in split_mod.FLOOR_STRATA) == EXPECTED_FLOOR
    assert len(split_mod.FLOOR_STRATA) == 6
    assert not [s for s in split_mod.FLOOR_STRATA if s[0] == "nut"]


def test_ca02_split_v1_without_nuts(no_nut_ds: Path, tmp_path: Path) -> None:
    rows = read_rows(no_nut_ds)
    assert len(rows) == 54
    assert len({r["item_id"] for r in rows}) == 18
    assert not [r for r in rows if r["object_type"] == "nut"]
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in ("split_v1.csv", "split_v1.sha256", "split_v1.json"):
        assert (splits / name).is_file(), name
    assignment = read_split(splits / "split_v1.csv")
    assert len(assignment) == 54
    info = item_info(no_nut_ds)
    for which in SPLITS:
        images = [p for p, v in assignment.items() if v == which]
        assert len(images) == 18, which
        assert len({info[p][0] for p in images}) == 6, which
    meta = read_meta(splits)
    assert warnings_with(meta, "below_floor") == []
    assert "below the floor" not in proc.stderr


def _drop_one_screw_fair(ds: Path) -> str:
    item = next(
        r["item_id"] for r in read_rows(ds) if r["object_type"] == "screw" and r["grade"] == "fair"
    )
    drop_rows(ds, lambda r: r["item_id"] == item)
    assert len({r["item_id"] for r in read_rows(ds)}) == 17
    return item


def test_ca03_below_the_floor_is_refused(no_nut_ds: Path, tmp_path: Path) -> None:
    _drop_one_screw_fair(no_nut_ds)
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert [ln for ln in proc.stderr.splitlines() if "below the floor" in ln] == [
        "split_v1 below the floor: screw/fair"
    ]
    assert "Traceback" not in proc.stderr
    assert split_files(tmp_path) == []


def test_ca03_allow_below_floor_records_the_warning(no_nut_ds: Path, tmp_path: Path) -> None:
    _drop_one_screw_fair(no_nut_ds)
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits, "--allow-below-floor")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    meta = read_meta(splits)
    assert {"code": "below_floor", "stratum": "screw/fair"} in meta["warnings"]
    assert warnings_with(meta, "below_floor") == [{"code": "below_floor", "stratum": "screw/fair"}]


def test_ca04_nut_is_split_but_not_part_of_the_floor(no_nut_ds: Path, tmp_path: Path) -> None:
    added = add_synthetic_item(no_nut_ds, "N-001", "nut", "fair", n_images=3)
    assert len(added) == 3
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    meta = read_meta(splits)
    small = warnings_with(meta, "small_stratum")
    assert any("nut/fair" in json.dumps(w) for w in small), meta["warnings"]
    assert warnings_with(meta, "below_floor") == []
    assignment = read_split(splits / "split_v1.csv")
    nut_paths = [p for p, (item, _) in item_info(no_nut_ds).items() if item == "N-001"]
    assert sorted(nut_paths) == sorted(added)
    assert [assignment[p] for p in nut_paths] == ["train"] * 3


def test_ca05_split_stratum_cases() -> None:
    ungraded = coverage_with({})
    graded_pliers = coverage_with({"pliers": True})

    assert split_stratum("pliers", ("pliers", "good"), ungraded) == ("pliers", "none")
    assert split_stratum("pliers", ("pliers", "good"), graded_pliers) == ("pliers", "good")
    for coverage in (ungraded, graded_pliers):
        assert split_stratum("hammer", ("hammer", "none"), coverage) == ("hammer", "none")
        assert split_stratum("drill", ("drill", "none"), coverage) == ("drill", "none")
        assert split_stratum("screw", ("screw", "fair"), coverage) == ("screw", "fair")
        assert split_stratum("other", ("other", "none"), coverage) == ("other", "none")


def test_ca06_tools_in_split_v1_by_whole_type(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        tool_items_per_stratum=1,
        identified_tool_items_per_type=3,
    )
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    by_type = items_by_split(ds, read_split(splits / "split_v1.csv"))
    for tool in HAND_TOOLS:
        counts = {which: len(by_type[tool][which]) for which in SPLITS}
        assert counts == {"train": 3, "val": 1, "test": 1}, (tool, counts)
    for tool in NEW_TOOLS:
        counts = {which: len(by_type[tool][which]) for which in SPLITS}
        assert counts == {"train": 1, "val": 1, "test": 1}, (tool, counts)
    meta = read_meta(splits)
    graded_strata = {f"{tool}/{grade}" for tool in HAND_TOOLS for grade in GRADES}
    for warning in warnings_with(meta, "small_stratum"):
        text = json.dumps(warning)
        assert not [s for s in graded_strata if s in text], warning


def test_ca07_same_split_without_tools(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=3, images_per_item=3)
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sha256_of(splits / "split_v1.csv") == CA07_BASE_SHA256


def test_ca08_defer_types_in_split_v1(identified_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"

    first = split_cli(identified_ds, splits, "--defer-types", "spirit_level")

    assert first.returncode == 0, first.stdout + first.stderr
    v1 = read_split(splits / "split_v1.csv")
    assert not [p for p in v1 if p.startswith("raw/spirit_level/")]
    assert read_meta(splits)["deferred_types"] == ["spirit_level"]
    v1_files = {p.name: p.read_bytes() for p in splits.glob("split_v1.*")}

    again = split_cli(identified_ds, splits)

    assert again.returncode == 2, again.stdout + again.stderr
    assert "new object type without decision: spirit_level" in again.stderr
    assert not (splits / "split_v2.csv").exists()

    extend = split_cli(identified_ds, splits, "--extend-test-types", "spirit_level")

    assert extend.returncode == 0, extend.stdout + extend.stderr
    v2 = read_split(splits / "split_v2.csv")
    by_type = items_by_split(identified_ds, v2)
    assert {w: len(by_type["spirit_level"][w]) for w in SPLITS} == dict.fromkeys(SPLITS, 1)
    assert {p: v2[p] for p in v1} == v1
    assert {p.name: p.read_bytes() for p in splits.glob("split_v1.*")} == v1_files


def test_ca08_deferred_type_without_images(no_nut_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits, "--defer-types", "nut")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "deferred type without images: nut" in proc.stderr.splitlines()
    assert split_files(tmp_path) == []
    assert not splits.exists() or snapshot(splits) == {}


def test_ca09_type_without_images_is_out_of_the_model(identified_ds: Path) -> None:
    df = load_manifest(identified_ds, external_sources=identified_ds / "external_sources.csv")

    labels = derive_model_labels(df, df)

    assert tuple(labels.object_types) == NO_NUT_TYPES
    assert tuple(labels.ungraded_object_types) == NEW_TOOLS


def test_ca10_thresholds_and_evaluate_without_nut(identified_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    proc = split_cli(identified_ds, splits)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    env = tiny_config(tmp_path, identified_ds, splits / "split_v1.csv")
    shutil.copytree(TINY_NO_NUT, env.model_dir)
    fixture_labels = json.loads((TINY_NO_NUT / "labels.json").read_text(encoding="utf-8"))

    for module in ("qc_ml.thresholds", "qc_ml.evaluate"):
        run = run_module(module, "--config", env.config, cwd=env.root)
        assert run.returncode == 0, f"{module}\n{run.stdout}\n{run.stderr}"

    decision = json.loads((env.model_dir / "decision.json").read_text(encoding="utf-8"))
    for key in ("type_threshold", "unusable_threshold", "grade_review_threshold"):
        assert isinstance(decision[key], int | float), key
    metrics = json.loads((env.model_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["labels"]["object_types"] == fixture_labels["object_types"]
    assert "nut" not in metrics["labels"]["object_types"]
    confusion = np.asarray(metrics["type_confusion"])
    assert confusion.shape == (5, 5)
    assert metrics["grade_qwk"] is not None
    assert metrics["type_accuracy"] is not None
    assert metrics["n_items_test_by_grade"] == dict.fromkeys(GRADES, 1)


def test_ca11_generator_include_nut(tmp_path: Path) -> None:
    default = make_synthetic_dataset(tmp_path / "default")
    explicit = make_synthetic_dataset(tmp_path / "explicit", include_nut=True)
    assert snapshot(default) == snapshot(explicit)

    without = make_synthetic_dataset(tmp_path / "without", include_nut=False)

    ids = {r["item_id"] for r in read_rows(without)}
    assert not [i for i in ids if i.startswith(("N-", "XN-"))]
    default_ids = {r["item_id"] for r in read_rows(default)}

    def own(values: set[str]) -> set[str]:
        return {i for i in values if i.startswith(("S-", "O-"))}

    assert own(ids) == own(default_ids)
    assert own(ids)


def test_ca12_dataset_is_out_of_git() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "ml/data"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert listed.stdout == ""
    paths = [
        "ml/data/manifest.csv",
        "ml/data/sources.csv",
        "ml/data/raw/hammer/_/T-601__0__20261105T120000Z.jpg",
    ]
    ignored = subprocess.run(
        ["git", "check-ignore", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode == 0, ignored.stderr
    assert ignored.stdout.splitlines() == paths


# ---------------------------------------------------------------------------------------------
# Exploratory (no CA)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(BASE_SHA256_MORE))
def test_extra_split_v1_unchanged_for_more_datasets(case: str, tmp_path: Path) -> None:
    kwargs, expected = BASE_SHA256_MORE[case]
    ds = make_synthetic_dataset(tmp_path / "ds", **kwargs)
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits, "--seed", "42", "--allow-below-floor")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sha256_of(splits / "split_v1.csv") == expected


@pytest.mark.parametrize(
    ("deferred", "strata"),
    [
        ("other", ["other/none"]),
        ("screw", [f"screw/{g}" for g in GRADES]),
    ],
)
def test_extra_deferring_a_floor_type_is_below_the_floor(
    no_nut_ds: Path, tmp_path: Path, deferred: str, strata: list[str]
) -> None:
    proc = split_cli(no_nut_ds, tmp_path / "splits", "--defer-types", deferred)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if "below the floor" in ln]
    assert sorted(ln.removeprefix("split_v1 below the floor: ") for ln in lines) == sorted(strata)
    assert split_files(tmp_path) == []


def test_extra_unknown_defer_type_in_split_v1(no_nut_ds: Path, tmp_path: Path) -> None:
    proc = split_cli(no_nut_ds, tmp_path / "splits", "--defer-types", "bolt")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "unknown object type: bolt" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert split_files(tmp_path) == []


@pytest.mark.parametrize("value", ["Spirit_Level", "nível", " spirit_level"])
def test_extra_odd_defer_values_are_refused_or_trimmed(
    identified_ds: Path, tmp_path: Path, value: str
) -> None:
    proc = split_cli(identified_ds, tmp_path / "splits", "--defer-types", value)

    assert "Traceback" not in proc.stderr
    if proc.returncode == 0:
        # Only a value equal to a known type after trimming may be accepted.
        assert value.strip() == "spirit_level", value
        assert read_meta(tmp_path / "splits")["deferred_types"] == ["spirit_level"]
    else:
        assert proc.returncode == 2
        assert "unknown object type" in proc.stderr
        assert split_files(tmp_path) == []


def test_extra_deferred_types_follow_the_known_order(identified_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"

    proc = split_cli(identified_ds, splits, "--defer-types", "spirit_level,hammer")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    expected = [t for t in KNOWN_OBJECT_TYPES if t in {"spirit_level", "hammer"}]
    assert read_meta(splits)["deferred_types"] == expected
    v1 = read_split(splits / "split_v1.csv")
    assert not [p for p in v1 if p.startswith(("raw/spirit_level/", "raw/hammer/"))]
    assert [p for p in v1 if p.startswith("raw/wrench/")]


def test_extra_extend_test_types_has_no_effect_in_split_v1(
    identified_ds: Path, tmp_path: Path
) -> None:
    plain = split_cli(identified_ds, tmp_path / "plain")
    extended = split_cli(identified_ds, tmp_path / "ext", "--extend-test-types", "spirit_level")

    assert plain.returncode == 0, plain.stderr
    assert extended.returncode == 0, extended.stderr
    assert (tmp_path / "plain" / "split_v1.csv").read_bytes() == (
        tmp_path / "ext" / "split_v1.csv"
    ).read_bytes()
    assert "--extend-test-types" in extended.stdout + extended.stderr


def test_extra_small_stratum_cites_the_type_stratum(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        identified_tool_items_per_type=2,
    )
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    small = warnings_with(read_meta(splits), "small_stratum")
    for tool in NEW_TOOLS:
        assert any(f"{tool}/none" in json.dumps(w) for w in small), (tool, small)


def test_extra_power_tools_split_by_type_in_split_v1(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        power_tool_items_per_type=3,
    )
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    by_type = items_by_split(ds, read_split(splits / "split_v1.csv"))
    for tool in POWER_TOOL_OBJECT_TYPES:
        assert {w: len(by_type[tool][w]) for w in SPLITS} == dict.fromkeys(SPLITS, 1), tool


def test_extra_graded_hand_tool_keeps_the_grade_strata(no_nut_ds: Path, tmp_path: Path) -> None:
    # 5 pliers items per grade with 12 images each: 60 images and 5 items per grade, the grade
    # criterion of SPEC-016 section 4.6, so pliers is graded and keeps the grade strata.
    for g_index, grade in enumerate(GRADES):
        for k in range(5):
            item = f"T-{g_index * 5 + k + 1:03d}"
            add_synthetic_item(no_nut_ds, item, "pliers", grade, n_images=12, seed=g_index * 5 + k)
    df = load_manifest(no_nut_ds, external_sources=no_nut_ds / "external_sources.csv")
    assert tool_grade_coverage(df)["pliers"]["graded"] is True
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assignment = read_split(splits / "split_v1.csv")
    rows = read_rows(no_nut_ds)
    grade_of = {r["item_id"]: r["grade"] for r in rows if r["object_type"] == "pliers"}
    item_of = {r["image_path"]: r["item_id"] for r in rows}
    per_grade: dict[str, Counter[str]] = defaultdict(Counter)
    seen: set[str] = set()
    for path, which in assignment.items():
        item = item_of[path]
        if item in grade_of and item not in seen:
            seen.add(item)
            per_grade[grade_of[item]][which] += 1
    for grade in GRADES:
        assert dict(per_grade[grade]) == {"train": 3, "val": 1, "test": 1}, grade


def test_extra_split_stratum_on_real_coverage_and_nut(no_nut_ds: Path) -> None:
    df = load_manifest(no_nut_ds, external_sources=no_nut_ds / "external_sources.csv")
    coverage = tool_grade_coverage(df)
    assert set(coverage) == set(TOOL_OBJECT_TYPES)
    for tool in TOOL_OBJECT_TYPES:
        assert split_stratum(tool, (tool, "poor"), coverage) == (tool, "none")
    for tool in (*POWER_TOOL_OBJECT_TYPES, *IDENTIFIED_TOOL_OBJECT_TYPES):
        assert split_stratum(tool, (tool, "none"), coverage) == (tool, "none")
    for grade in GRADES:
        assert split_stratum("nut", ("nut", grade), coverage) == ("nut", grade)


def test_extra_externals_stay_in_train_without_nuts(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        external_items_per_stratum=1,
    )
    ids = {r["item_id"] for r in read_rows(ds)}
    assert not [i for i in ids if i.startswith(("N-", "XN-"))]
    assert [i for i in ids if i.startswith("XS-")]
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    info = item_info(ds)
    for path, which in read_split(splits / "split_v1.csv").items():
        if info[path][0].startswith("X"):
            assert which == "train", path
    assert warnings_with(read_meta(splits), "below_floor") == []


def test_extra_generator_without_nuts_with_contributors_and_externals(tmp_path: Path) -> None:
    kwargs = {"items_per_stratum": 2, "contributor_items_per_stratum": 1}
    kwargs["external_items_per_stratum"] = 1
    with_nut = make_synthetic_dataset(tmp_path / "with", **kwargs)
    without = make_synthetic_dataset(tmp_path / "without", include_nut=False, **kwargs)

    ids = {r["item_id"] for r in read_rows(without)}
    assert not [i for i in ids if i.startswith(("N-", "XN-"))]
    prefixes = ("S-", "O-", "XS-", "XO-")
    assert {i for i in ids if i.startswith(prefixes)} == {
        r["item_id"] for r in read_rows(with_nut) if r["item_id"].startswith(prefixes)
    }
    manifest_paths = {r["image_path"] for r in read_rows(without)}
    with (without / "sources.csv").open(encoding="utf-8", newline="") as fh:
        source_paths = {r["image_path"] for r in csv.DictReader(fh)}
    assert source_paths <= manifest_paths
    for path in manifest_paths:
        assert (without / path).is_file(), path
    nut_dir = without / "raw" / "nut"
    assert not nut_dir.exists() or not list(nut_dir.rglob("*.*"))

    proc = run_module(
        "qc_ml.data",
        "validate",
        "--dataset-dir",
        without,
        "--external-sources",
        without / "external_sources.csv",
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_extra_fixture_no_nut_is_versioned_and_consistent() -> None:
    labels = json.loads((TINY_NO_NUT / "labels.json").read_text(encoding="utf-8"))
    assert labels["object_types"] == list(NO_NUT_TYPES)
    assert labels["ungraded_object_types"] == list(NEW_TOOLS)
    assert labels["grades"] == list(GRADES)
    recorded = (TINY_NO_NUT / "model.sha256").read_text(encoding="utf-8").split()[0]
    assert recorded == sha256_of(TINY_NO_NUT / "model.onnx")
    listed = subprocess.run(
        ["git", "ls-files", "ml/tests/fixtures/tiny_model_no_nut"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    names = {Path(p).name for p in listed}
    assert {"model.onnx", "model.sha256", "labels.json", "preprocessing.json"} <= names
    assert {"decision.json", "parity_fixture.npz"} <= names


def test_extra_readme_has_the_operation_section() -> None:
    text = (REPO_ROOT / "ml" / "README.md").read_text(encoding="utf-8")
    assert "Modelo oficial com as fotos dos colegas (ADR-025)" in text
    assert "--defer-types" in text
    assert "plano-v2.csv" in text


def test_extra_split_v1_without_deferral_records_no_deferred_type(
    no_nut_ds: Path, tmp_path: Path
) -> None:
    splits = tmp_path / "splits"

    proc = split_cli(no_nut_ds, splits)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert read_meta(splits).get("deferred_types", []) == []


def test_extra_same_deferral_again_keeps_split_v1(identified_ds: Path, tmp_path: Path) -> None:
    # ADR-022, decision 4: the deferred type is still new; deferring it again is a decision.
    splits = tmp_path / "splits"
    assert split_cli(identified_ds, splits, "--defer-types", "spirit_level").returncode == 0
    before = snapshot(splits)

    again = split_cli(identified_ds, splits, "--defer-types", "spirit_level")

    assert again.returncode == 0, again.stdout + again.stderr
    assert snapshot(splits) == before


def test_extra_defer_and_extend_the_same_type_in_split_v1(
    identified_ds: Path, tmp_path: Path
) -> None:
    splits = tmp_path / "splits"

    proc = split_cli(
        identified_ds, splits, "--defer-types", "hammer", "--extend-test-types", "hammer"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    meta = read_meta(splits)
    assert meta["deferred_types"] == ["hammer"]
    assert not meta.get("test_extended_types")
    assert not [p for p in read_split(splits / "split_v1.csv") if p.startswith("raw/hammer/")]


def test_extra_readers_ignore_the_deferred_images(identified_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert split_cli(identified_ds, splits, "--defer-types", "spirit_level").returncode == 0
    df = load_manifest(identified_ds, external_sources=identified_ds / "external_sources.csv")
    split_df = split_mod.load_split(splits / "split_v1.csv")

    assigned = split_mod.assign_splits(df, split_df)

    deferred = df["object_type"] == "spirit_level"
    assert deferred.any()
    assert assigned[deferred].isna().all()
    assert set(assigned[~deferred]) == set(SPLITS)
    test_rows = split_mod.rows_for(df, split_df, "test")
    assert "spirit_level" not in set(test_rows["object_type"])

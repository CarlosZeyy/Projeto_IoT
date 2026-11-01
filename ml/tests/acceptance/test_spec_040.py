"""Acceptance tests for SPEC-040 (consolidated maintenance), ML part: CA-12 to CA-15.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Tests named ``test_extra_*`` are exploratory edge cases around sections 4.6 to
4.8 that no CA spells out.

Rules followed (``docs/architecture.md`` section 10, R-11 and R-14): every dataset is synthetic
(``make_synthetic_dataset`` plus images drawn here with Pillow) and lives under a temporary
directory; nothing under ``ml/data/`` is read; the ``metrics.json`` is written by the test (no
torch); the CLIs run through ``python -m`` in a subprocess (never pytest).
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Collection
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from qc_ml.data import load_manifest
from qc_ml.split import load_split, new_object_types, type_decision_problems
from qc_ml.synthetic import make_synthetic_dataset

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "ml" / "README.md"
COUNT_PREFIX = "report failed: invalid count in metrics.json: "
WARNING_PREFIX = "report failed: invalid warning in metrics.json: "
ORIGINAL = "# CHANGELOG\n\n## anterior\n\nconteúdo de antes\n".encode()
METRICS: dict[str, Any] = {
    "model_version": "partqc-test-v1",
    "counts": {
        "train": {
            "n_images": 44,
            "by_origin": {"capture": 44, "contributor": 0, "external": 0},
            "by_source": {},
        },
        "val": {
            "n_images": 20,
            "by_origin": {"capture": 20, "contributor": 0, "external": 0},
            "by_source": {},
        },
        "test": {
            "n_images": 22,
            "by_origin": {"capture": 22, "contributor": 0, "external": 0},
            "by_source": {},
        },
    },
}
MANIFEST_HEADER = [
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_module(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env=_env(),
        check=False,
    )


# --------------------------------------------------------------------------- CA-12 and CA-13


def model_dir(tmp_path: Path, **fields: Any) -> Path:
    target = tmp_path / "model"
    target.mkdir(exist_ok=True)
    (target / "model.sha256").write_text("0123456789abcdef" * 4 + "\n", encoding="utf-8")
    metrics = json.loads(json.dumps(METRICS))
    metrics.update(fields)
    (target / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return target


def changelog(tmp_path: Path, **fields: Any) -> tuple[subprocess.CompletedProcess[str], Path]:
    model = model_dir(tmp_path, **fields)
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes(ORIGINAL)
    args = ["changelog", "--model-dir", str(model), "--append", str(target)]
    return run_module("qc_ml.report", args, tmp_path), target


def assert_refused(
    proc: subprocess.CompletedProcess[str], target: Path, *lines: str, absent: Collection[str] = ()
) -> None:
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert target.read_bytes() == ORIGINAL
    assert proc.stderr.splitlines() == list(lines), proc.stderr
    for word in absent:
        assert word not in proc.stderr, word


GOOD_FIELD = "n_items_test_by_grade.good"
WHOLE_FIELD = "n_items_test_by_grade"


@pytest.mark.parametrize(
    "value, field",
    [
        ({"good": -1}, GOOD_FIELD),
        ({"good": "3\n## forjado"}, GOOD_FIELD),
        ({"good": 2.0}, GOOD_FIELD),
        ({"good": True}, GOOD_FIELD),
        ({"bad\nkey": 1}, WHOLE_FIELD),
        (["good", 1], WHOLE_FIELD),
    ],
    ids=["negative", "text", "float", "bool", "bad-key", "list"],
)
def test_ca12_invalid_counts_write_nothing(tmp_path: Path, value: Any, field: str) -> None:
    proc, target = changelog(tmp_path, n_items_test_by_grade=value)
    assert_refused(proc, target, COUNT_PREFIX + field, absent=("forjado", "bad"))


def test_ca12_valid_counts_keep_the_line(tmp_path: Path) -> None:
    proc, target = changelog(tmp_path, n_items_test_by_grade={"good": 2, "fair": 0})
    assert proc.returncode == 0, proc.stderr
    assert "Peças no teste por grau: good: 2, fair: 0." in proc.stdout
    body = target.read_bytes()
    assert body.startswith(ORIGINAL)
    assert "Peças no teste por grau: good: 2, fair: 0.".encode() in body[len(ORIGINAL) :]


@pytest.mark.parametrize(
    "value, index",
    [
        (["ok", "linha\n## forjada"], "warnings.1"),
        (["a\rb"], "warnings.0"),
        (["a b"], "warnings.0"),
        (["a\u001b[31m"], "warnings.0"),
        (["a‮b"], "warnings.0"),
        ([3], "warnings.0"),
        ("texto", "warnings"),
    ],
    ids=["newline", "cr", "zl", "esc", "rlo", "number", "text"],
)
def test_ca13_invalid_warnings_write_nothing(tmp_path: Path, value: Any, index: str) -> None:
    proc, target = changelog(tmp_path, warnings=value)
    assert_refused(proc, target, WARNING_PREFIX + index, absent=("forjada",))


def test_ca13_valid_warnings_keep_their_lines(tmp_path: Path) -> None:
    proc, target = changelog(tmp_path, warnings=["few test items for pliers: 1", "acentuação ok"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "- few test items for pliers: 1" in lines
    assert "- acentuação ok" in lines
    appended = target.read_bytes()[len(ORIGINAL) :].decode("utf-8").splitlines()
    assert "- acentuação ok" in appended


@pytest.mark.parametrize(
    "value",
    [
        {"good": 10**30},
        {"good": 0},
        {g: 1 for g in ("perfect", "good", "fair", "poor", "unusable")},
    ],
    ids=["huge", "zero", "all"],
)
def test_extra_ca12_more_valid_counts(tmp_path: Path, value: dict[str, int]) -> None:
    proc, _ = changelog(tmp_path, n_items_test_by_grade=value)
    assert proc.returncode == 0, proc.stderr
    assert "Peças no teste por grau: " in proc.stdout


@pytest.mark.parametrize("value", [None, {}, [], ""], ids=["null", "object", "list", "text"])
def test_extra_ca12_empty_value_shows_no_line_and_is_valid(tmp_path: Path, value: Any) -> None:
    """Section 4.6: only "presente e não vazio" is checked."""
    proc, _ = changelog(tmp_path, n_items_test_by_grade=value)
    assert proc.returncode == 0, proc.stderr
    assert "Peças no teste por grau" not in proc.stdout


@pytest.mark.parametrize(
    "value, field",
    [
        ({"unknown": 1}, WHOLE_FIELD),
        ({"GOOD": 1}, WHOLE_FIELD),
        ({"good ": 1}, WHOLE_FIELD),
        ({"": 1}, WHOLE_FIELD),
        ({"good": None}, GOOD_FIELD),
        ({"good": [1]}, GOOD_FIELD),
        ({"good": {"x": 1}}, GOOD_FIELD),
        ({"good": 1e3}, GOOD_FIELD),
        ("good: 1\n## forjado", WHOLE_FIELD),
        (5, WHOLE_FIELD),
        (True, WHOLE_FIELD),
    ],
    ids=ascii,
)
def test_extra_ca12_more_invalid_counts(tmp_path: Path, value: Any, field: str) -> None:
    proc, target = changelog(tmp_path, n_items_test_by_grade=value)
    assert_refused(proc, target, COUNT_PREFIX + field, absent=("forjado",))


def test_extra_ca12_without_the_fields_is_valid(tmp_path: Path) -> None:
    proc, target = changelog(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert target.read_bytes().startswith(ORIGINAL)


@pytest.mark.parametrize(
    "char",
    [" ", "\u0085", "‍", "﻿", "\u0000", "\t", "\ud83d", "­", "\U000e0001"],
    ids=ascii,
)
def test_extra_ca13_every_forbidden_category(tmp_path: Path, char: str) -> None:
    proc, target = changelog(tmp_path, warnings=[f"a{char}b"])
    assert_refused(proc, target, WARNING_PREFIX + "warnings.0")


@pytest.mark.parametrize(
    "value",
    [{"a": 1}, 3, True, None],
    ids=["object", "number", "bool", "null"],
)
def test_extra_ca13_not_a_list(tmp_path: Path, value: Any) -> None:
    proc, target = changelog(tmp_path, warnings=value)
    assert_refused(proc, target, WARNING_PREFIX + "warnings")


@pytest.mark.parametrize("item", [None, ["x"], {"x": 1}, True, 1.5], ids=ascii)
def test_extra_ca13_item_that_is_not_text(tmp_path: Path, item: Any) -> None:
    proc, target = changelog(tmp_path, warnings=["ok", item])
    assert_refused(proc, target, WARNING_PREFIX + "warnings.1")


def test_extra_ca13_empty_list_is_valid(tmp_path: Path) -> None:
    proc, _ = changelog(tmp_path, warnings=[])
    assert proc.returncode == 0, proc.stderr


def test_extra_ca13_visible_characters_are_valid(tmp_path: Path) -> None:
    text = "## pliers: 1 | `x` — 日本語 🙂 a b"
    proc, _ = changelog(tmp_path, warnings=[text])
    assert proc.returncode == 0, proc.stderr
    assert f"- {text}" in proc.stdout.splitlines()


def test_extra_ca13_every_invalid_field_in_the_order_of_the_spec(tmp_path: Path) -> None:
    metrics_counts = json.loads(json.dumps(METRICS["counts"]))
    metrics_counts["train"]["n_images"] = -1
    proc, target = changelog(
        tmp_path,
        counts=metrics_counts,
        n_items_test_by_grade={"good": -1, "fair": "x"},
        warnings=["ok", "a\nb", 3],
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert target.read_bytes() == ORIGINAL
    lines = proc.stderr.splitlines()
    assert all(ln.startswith((COUNT_PREFIX, WARNING_PREFIX)) for ln in lines), lines
    fields = [ln.rsplit(": ", 1)[1] for ln in lines]
    assert "counts.train.n_images" in fields
    assert fields.index("counts.train.n_images") < fields.index(GOOD_FIELD)
    assert set(fields[-4:]) == {
        GOOD_FIELD,
        "n_items_test_by_grade.fair",
        "warnings.1",
        "warnings.2",
    }
    assert fields[-2:] == ["warnings.1", "warnings.2"]


def test_extra_ca13_also_without_append(tmp_path: Path) -> None:
    model = model_dir(tmp_path, warnings=["a\nb"], n_items_test_by_grade={"good": -1})
    proc = run_module("qc_ml.report", ["changelog", "--model-dir", str(model)], tmp_path)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.splitlines() == [COUNT_PREFIX + GOOD_FIELD, WARNING_PREFIX + "warnings.0"]


def test_extra_ca13_release_notes_does_not_change(tmp_path: Path) -> None:
    model = model_dir(tmp_path, warnings=["a\nb"], n_items_test_by_grade={"good": -1})
    registry = tmp_path / "external_sources.csv"
    registry.write_text(
        "source_id,title,url,license,license_url,attribution,retrieved_at\n", encoding="utf-8"
    )
    args = ["release-notes", "--model-dir", str(model), "--external-sources", str(registry)]
    proc = run_module("qc_ml.report", args, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "invalid" not in proc.stderr


# --------------------------------------------------------------------------- CA-14


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def add_piece(root: Path, item_id: str, object_type: str, grade: str, hour: int) -> list[str]:
    """Three images of one physical piece (files + manifest rows), in the SPEC-010 layout."""
    rows = read_rows(root / "manifest.csv")
    paths = []
    for angle in range(3):
        ts = f"20261203T{hour:02d}00{angle:02d}Z"
        rel = f"raw/{object_type}/{grade}/{item_id}__{angle}__{ts}.jpg"
        digest = hashlib.sha256(rel.encode()).digest()
        image = Image.new("RGB", (64, 64), (200 + digest[0] % 50, 200 + digest[1] % 50, 210))
        for x in range(20, 44):
            for y in range(8, 56):
                image.putpixel((x, y), (90 + digest[2] % 60, 90, 100))
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        image.save(root / rel, format="JPEG", quality=90)
        rows.append(
            {
                "image_path": rel,
                "item_id": item_id,
                "object_type": object_type,
                "grade": grade,
                "labeler": "a",
                "angle": str(angle),
                "captured_at": f"2026-12-03T{hour:02d}:00:{angle:02d}Z",
                "capture_device": "synthetic",
                "notes": "",
            }
        )
        paths.append(rel)
    write_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    return paths


def exclude_type(root: Path, object_type: str) -> list[str]:
    """Every image of the type in the manifest goes to ``exclusions.csv`` and is deleted."""
    victims = [
        r["image_path"] for r in read_rows(root / "manifest.csv") if r["object_type"] == object_type
    ]
    path = root / "exclusions.csv"
    known = read_rows(path) if path.exists() else []
    known_paths = {r["image_path"] for r in known}
    known += [{"image_path": v, "reason": "other"} for v in victims if v not in known_paths]
    write_rows(path, ["image_path", "reason"], known)
    for victim in victims:
        (root / victim).unlink(missing_ok=True)
    return victims


def split_cli(state: SimpleNamespace, *extra: str) -> subprocess.CompletedProcess[str]:
    args = [
        "--dataset-dir",
        str(state.dataset),
        "--splits-dir",
        str(state.splits),
        "--seed",
        "42",
        *extra,
    ]
    return run_module("qc_ml.split", args, state.dataset.parent)


def read_split(path: Path) -> dict[str, str]:
    return {r["image_path"]: r["split"] for r in read_rows(path)}


def snapshot(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.iterdir()) if p.is_file()}


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``split_v1`` without tools, ``split_v2`` extending ``pliers`` (3 ``T-`` pieces with test),
    every ``pliers`` image of the manifest excluded and deleted, and 3 new ``T-`` pieces."""
    root = tmp_path_factory.mktemp("s040_chain")
    dataset = make_synthetic_dataset(root / "ds")
    state = SimpleNamespace(dataset=dataset, splits=root / "splits")
    first = split_cli(state)
    assert first.returncode == 0, first.stdout + first.stderr
    for n in range(1, 4):
        add_piece(dataset, f"T-00{n}", "pliers", "fair", n)
    second = split_cli(state, "--extend-test-types", "pliers")
    assert second.returncode == 0, second.stdout + second.stderr
    meta = json.loads((state.splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["test_extended_types"] == ["pliers"]
    v2 = read_split(state.splits / "split_v2.csv")
    assert any("/pliers/" in p and which == "test" for p, which in v2.items())
    exclude_type(dataset, "pliers")
    for n in range(4, 7):
        add_piece(dataset, f"T-00{n}", "pliers", "fair", n)
    return root


@pytest.fixture
def state(chain: Path, tmp_path: Path) -> SimpleNamespace:
    target = Path(shutil.copytree(chain, tmp_path / "copy"))
    return SimpleNamespace(dataset=target / "ds", splits=target / "splits")


def new_pliers_images(state: SimpleNamespace) -> list[str]:
    return [
        r["image_path"]
        for r in read_rows(state.dataset / "manifest.csv")
        if r["item_id"] in {"T-004", "T-005", "T-006"}
    ]


def excluded_images(state: SimpleNamespace) -> set[str]:
    return {r["image_path"] for r in read_rows(state.dataset / "exclusions.csv")}


def test_ca14_second_extension_is_refused_and_writes_nothing(state: SimpleNamespace) -> None:
    before = snapshot(state.splits)
    proc = split_cli(state, "--extend-test-types", "pliers")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "object type is not new: pliers" in proc.stderr.splitlines()
    assert snapshot(state.splits) == before
    assert not list(state.splits.glob("split_v3*"))


def test_ca14_without_the_lists_new_pieces_are_never_in_test(state: SimpleNamespace) -> None:
    proc = split_cli(state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v3 = read_split(state.splits / "split_v3.csv")
    new = new_pliers_images(state)
    assert len(new) == 9
    for path in new:
        assert v3[path] in ("train", "val"), (path, v3[path])
    # "continua no manifest": an image excluded keeps its manifest row (load_manifest requires
    # it) but it left the dataset. Reading recorded in the test report.
    excluded = excluded_images(state)
    kept = 0
    for name in ("split_v1.csv", "split_v2.csv"):
        for path, which in read_split(state.splits / name).items():
            if path not in excluded:
                assert v3[path] == which, (name, path)
                kept += 1
            else:
                assert path not in v3 or v3[path] == which, path
    assert kept > 0


def _drop_key(state: SimpleNamespace) -> None:
    path = state.splits / "split_v2.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    del meta["test_extended_types"]
    path.write_text(json.dumps(meta), encoding="utf-8")


def test_ca14_json_without_the_key_makes_the_type_new_again(state: SimpleNamespace) -> None:
    _drop_key(state)
    before = snapshot(state.splits)
    plain = split_cli(state)
    assert plain.returncode == 2, plain.stdout + plain.stderr
    assert "new object type without decision: pliers" in plain.stderr.splitlines()
    assert "Traceback" not in plain.stderr
    assert snapshot(state.splits) == before
    extended = split_cli(state, "--extend-test-types", "pliers")
    assert extended.returncode == 0, extended.stdout + extended.stderr
    assert (state.splits / "split_v3.csv").exists()


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        "\xff\xfe",
        "[]",
        '{"test_extended_types": "pliers"}',
        '{"test_extended_types": ["pliers", 3]}',
        '{"test_extended_types": {"pliers": 1}}',
        '{"test_extended_types": null}',
    ],
    ids=["absent", "not-json", "not-utf8", "list", "text", "mixed", "object", "null"],
)
def test_extra_ca14_unusable_json_counts_as_an_empty_list(
    state: SimpleNamespace, content: str | None
) -> None:
    path = state.splits / "split_v2.json"
    if content is None:
        path.unlink()
    elif content == "\xff\xfe":
        path.write_bytes(b"\xff\xfe\x00")
    else:
        path.write_text(content, encoding="utf-8")
    proc = split_cli(state)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "new object type without decision: pliers" in proc.stderr.splitlines()
    assert "Traceback" not in proc.stderr


def test_extra_ca14_deferring_an_extended_type_is_refused(state: SimpleNamespace) -> None:
    before = snapshot(state.splits)
    proc = split_cli(state, "--defer-types", "pliers")
    assert proc.returncode == 2
    assert "object type is not new: pliers" in proc.stderr.splitlines()
    assert snapshot(state.splits) == before


def test_extra_ca14_any_earlier_version_counts(state: SimpleNamespace) -> None:
    """Extended in v2, v3 without lists, then v3's pieces excluded too: still not new in v4."""
    assert split_cli(state).returncode == 0
    exclude_type(state.dataset, "pliers")
    for n in range(7, 10):
        add_piece(state.dataset, f"T-00{n}", "pliers", "fair", n)
    refused = split_cli(state, "--extend-test-types", "pliers")
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "object type is not new: pliers" in refused.stderr.splitlines()
    assert not list(state.splits.glob("split_v4*"))
    plain = split_cli(state)
    assert plain.returncode == 0, plain.stdout + plain.stderr
    v4 = read_split(state.splits / "split_v4.csv")
    new = [p for p in v4 if any(f"T-00{n}__" in p for n in range(7, 10))]
    assert new
    assert all(v4[p] in ("train", "val") for p in new)


def test_extra_ca14_another_new_type_still_needs_a_decision(state: SimpleNamespace) -> None:
    for n in range(10, 13):
        add_piece(state.dataset, f"T-0{n}", "allen_key", "fair", n)
    proc = split_cli(state)
    assert proc.returncode == 2
    lines = proc.stderr.splitlines()
    assert "new object type without decision: allen_key" in lines
    assert "new object type without decision: pliers" not in lines
    assert split_cli(state, "--extend-test-types", "allen_key").returncode == 0
    meta = json.loads((state.splits / "split_v3.json").read_text(encoding="utf-8"))
    assert meta["test_extended_types"] == ["allen_key"]


def test_extra_ca14_public_signature_is_optional_and_by_name(state: SimpleNamespace) -> None:
    for function in (new_object_types, type_decision_problems):
        extra = [
            p
            for p in inspect.signature(function).parameters.values()
            if p.name == "extended_before"
        ]
        assert len(extra) == 1, function
        assert extra[0].kind is inspect.Parameter.KEYWORD_ONLY
        assert not extra[0].default
    frame = load_manifest(state.dataset)
    versions = [
        load_split(state.splits / "split_v1.csv"),
        load_split(state.splits / "split_v2.csv"),
    ]
    assert "pliers" in new_object_types(frame, versions)  # all its old images left the dataset
    assert "pliers" not in new_object_types(frame, versions, extended_before=["pliers"])


# --------------------------------------------------------------------------- CA-15


def code_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
        elif current is not None:
            current.append(line)
    return blocks


def continuation_problems(text: str) -> list[str]:
    """The rules of CA-15, also used by the control test below."""
    problems: list[str] = []
    for block in code_blocks(text):
        for i, line in enumerate(block):
            if "--defer-types" not in line and "--extend-test-types" not in line:
                continue
            j = i
            while j >= 0 and "python -m qc_ml.split" not in block[j]:
                j -= 1
            if j < 0:
                continue  # not a line of a split command
            starts = line.lstrip().startswith(("--defer-types", "--extend-test-types"))
            one_option = len(re.findall(r"--(?:defer-types|extend-test-types)", line)) == 1
            if not (starts and one_option and block[i - 1].endswith(" \\")):
                problems.append(line)
    for line in text.splitlines():
        if "python -m qc_ml.split" in line and "  " in line.lstrip():
            problems.append(line)
    return problems


def test_ca15_split_examples_have_line_continuations() -> None:
    text = README.read_text(encoding="utf-8")
    assert continuation_problems(text) == []
    occurrences = [
        line
        for block in code_blocks(text)
        for line in block
        if line.lstrip().startswith(("--defer-types", "--extend-test-types"))
    ]
    assert len(occurrences) >= 3  # the two examples: one --defer-types; both options


@pytest.mark.parametrize(
    "block",
    [
        "python -m qc_ml.split --seed 42  --defer-types x",
        "python -m qc_ml.split --seed 42 --defer-types x",
        "python -m qc_ml.split --seed 42\n    --defer-types x",
        "python -m qc_ml.split --seed 42 \\\n    --extend-test-types x --defer-types y\\",
        "python -m qc_ml.split --seed 42\\\n    --extend-test-types x",
    ],
)
def test_ca15_control_the_rules_detect_a_planted_example(block: str) -> None:
    assert continuation_problems(f"```bash\n{block}\n```\n"), block


def test_extra_ca15_the_two_examples_are_still_runnable_commands() -> None:
    """Joined by the continuation, each example has exactly the options the README describes."""
    text = README.read_text(encoding="utf-8")
    joined = re.sub(r" \\\n\s*", " ", text)
    commands = [ln for ln in joined.splitlines() if "python -m qc_ml.split" in ln and "--" in ln]
    deferred = [c for c in commands if "--defer-types" in c and "--extend-test-types" not in c]
    extended = [c for c in commands if "--extend-test-types" in c and "--defer-types" in c]
    assert deferred
    assert extended

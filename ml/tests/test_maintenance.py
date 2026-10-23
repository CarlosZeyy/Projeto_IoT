"""Author tests of SPEC-031 that need neither torch nor data: torch ceiling, export warnings
(static part), README flow and the single ``ITEM_ID_PATTERN``. No torch."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from qc_ml import data as data_mod
from qc_ml import split as split_mod

ROOT = Path(__file__).resolve().parents[2]
ML = ROOT / "ml"


def _calls(path: Path, name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            or (isinstance(node.func, ast.Name) and node.func.id == name)
        )
    ]


def test_torch_ceiling_in_train_extra_and_lock() -> None:
    project = tomllib.loads((ML / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    train = project["optional-dependencies"]["train"]
    assert [d for d in train if re.fullmatch(r"torch(?![a-z]).*", d)] == ["torch<2.15"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {p["name"]: p for p in lock["package"]}
    assert packages["torch"]["version"] == "2.14.1"
    torch_req = [r for r in packages["qc-ml"]["metadata"]["requires-dist"] if r["name"] == "torch"]
    assert torch_req == [{"name": "torch", "marker": "extra == 'train'", "specifier": "<2.15"}]


def test_export_does_not_ignore_warnings() -> None:
    export = ML / "src" / "qc_ml" / "export.py"
    for call in _calls(export, "simplefilter"):
        args = [a.value for a in call.args if isinstance(a, ast.Constant)]
        kwargs = [k.value.value for k in call.keywords if isinstance(k.value, ast.Constant)]
        assert "ignore" not in args + kwargs, ast.unparse(call)
    assert _calls(export, "catch_warnings")


def test_readme_colab_flow_starts_with_split_v1() -> None:
    lines = (ML / "README.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "Do Colab ao Release" in line)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(rf"#{{1,{level}}} ", lines[i])),
        len(lines),
    )
    section = lines[start:end]
    text = "\n".join(section)
    assert "python -m qc_ml.split" in text and "split_v1" in text
    first_split = next(i for i, line in enumerate(section) if "python -m qc_ml.split" in line)
    first_step = next(i for i, line in enumerate(section) if re.match(r"\s*1\. ", line))
    assert first_split < first_step
    assert "torch<2.15" in text and "make_tiny_fixture.py" in text


def test_item_id_pattern_is_defined_once() -> None:
    assert split_mod.ITEM_ID_PATTERN is data_mod.ITEM_ID_PATTERN
    for call in _calls(ML / "src" / "qc_ml" / "split.py", "compile"):
        assert "[SNOT]" not in ast.unparse(call), ast.unparse(call)
    # The file-name pattern of the collect mode still matches exactly as before.
    assert split_mod.IMAGE_FILE_PATTERN.pattern == (
        r"([SNOT]-[0-9]{3})__[0-4]__[0-9]{8}T[0-9]{6}Z\.jpg"
    )
    match = split_mod.IMAGE_FILE_PATTERN.fullmatch("S-012__3__20261020T101112Z.jpg")
    assert match and match.group(1) == "S-012"
    assert split_mod.IMAGE_FILE_PATTERN.fullmatch("X-012__3__20261020T101112Z.jpg") is None

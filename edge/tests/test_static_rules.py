"""Static checks of qc_edge sources: R-02 (no HTTP client) and SEC-04 (the flag is never set)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "qc_edge"
FORBIDDEN_IMPORTS = {"httpx", "requests", "urllib.request"}
# SPEC-009 creates the publisher, the only module allowed to talk to the cloud.
ALLOWED_PUBLISHER = "publisher.py"


def _modules() -> list[Path]:
    modules = sorted(SRC.rglob("*.py"))
    assert modules, "no qc_edge sources found"
    return modules


def _imported(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _forbidden(name: str) -> bool:
    return any(name == bad or name.startswith(f"{bad}.") for bad in FORBIDDEN_IMPORTS)


def test_no_http_client_outside_the_publisher() -> None:
    offenders = {}
    for path in _modules():
        if path.name == ALLOWED_PUBLISHER:
            continue
        bad = {name for name in _imported(ast.parse(path.read_text())) if _forbidden(name)}
        if bad:
            offenders[path.name] = bad
    assert offenders == {}


def test_truncated_images_flag_is_never_assigned() -> None:
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text())):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                assert name != "LOAD_TRUNCATED_IMAGES", path.name
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setattr":
                args = node.args
                assert not (
                    len(args) >= 2
                    and isinstance(args[1], ast.Constant)
                    and args[1].value == "LOAD_TRUNCATED_IMAGES"
                ), path.name

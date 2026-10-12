"""Runtime dependency closure over ``uv.lock`` (SPEC-001 §4.5, R-12).

The closure starts at a package of the lock (usually a workspace member) and follows only
runtime edges:

* ``dependencies`` of every reached package;
* ``optional-dependencies[<extra>]`` of a package **only** when the edge that reached it asked
  for that extra (e.g. ``{ name = "psycopg", extra = ["binary"] }``), or, for the root, when the
  caller passes ``extras``;
* ``dev-dependencies`` / dependency groups are never followed.

Environment markers are ignored on purpose: the check is conservative and treats a dependency
as present on every platform.

This module is not a test file; tests load it by path (``--import-mode=importlib`` does not put
``tests/`` on ``sys.path``).
"""

from __future__ import annotations

import re
import tomllib
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

FORBIDDEN_FOR_LIGHT_PACKAGES: frozenset[str] = frozenset(
    {"torch", "torchvision", "timm", "onnxruntime"}
)

_NODE = tuple[str, str | None]  # (package name, extra or None for the base package)


def normalize_name(name: str) -> str:
    """Normalize a distribution name as PEP 503 does (``Foo_Bar`` -> ``foo-bar``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_forbidden(name: str, forbidden: Iterable[str] = FORBIDDEN_FOR_LIGHT_PACKAGES) -> bool:
    """Return True for a forbidden name.

    When ``onnxruntime`` is forbidden, its variants (``onnxruntime-gpu``, ...) are too.
    """
    normalized = normalize_name(name)
    forbidden_names = {normalize_name(f) for f in forbidden}
    if normalized in forbidden_names:
        return True
    return "onnxruntime" in forbidden_names and normalized.startswith("onnxruntime-")


def load_lock(path: str | Path) -> dict[str, Any]:
    """Parse a ``uv.lock`` file."""
    with Path(path).open("rb") as fh:
        return tomllib.load(fh)


def _index_packages(lock: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for package in lock.get("package", []):
        index.setdefault(normalize_name(package["name"]), []).append(package)
    return index


def _select(
    candidates: list[Mapping[str, Any]], edge: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    """Pick the lock entries an edge points to (a name can be locked in several versions)."""
    if len(candidates) <= 1:
        return candidates
    version = edge.get("version")
    if version is None:
        return candidates
    matching = [c for c in candidates if c.get("version") == version]
    return matching or candidates


def dependency_closure(
    lock: Mapping[str, Any], root: str, extras: Iterable[str] = ()
) -> dict[str, list[str]]:
    """Return every package reachable from ``root`` with the shortest path that reaches it.

    The result maps a normalized package name to the list of names from ``root`` to it, e.g.
    ``{"qc-api": ["qc-api"], "pkg-x": ["qc-api", "pkg-x"], ...}``.

    Raises ``KeyError`` if ``root`` is not in the lock.
    """
    index = _index_packages(lock)
    root_name = normalize_name(root)
    if root_name not in index:
        raise KeyError(f"package {root!r} not found in lock")

    paths: dict[str, list[str]] = {root_name: [root_name]}
    seen: set[tuple[str, str | None, str | None]] = set()
    queue: deque[tuple[Mapping[str, Any], str | None, list[str]]] = deque()

    for package in index[root_name]:
        for extra in (None, *extras):
            queue.append((package, extra, [root_name]))

    while queue:
        package, extra, path = queue.popleft()
        key = (normalize_name(package["name"]), package.get("version"), extra)
        if key in seen:
            continue
        seen.add(key)

        if extra is None:
            edges = package.get("dependencies", [])
        else:
            edges = package.get("optional-dependencies", {}).get(extra, [])

        for edge in edges:
            name = normalize_name(edge["name"])
            child_path = [*path, name]
            paths.setdefault(name, child_path)
            for target in _select(index.get(name, []), edge):
                queue.append((target, None, child_path))
                for child_extra in edge.get("extra", []):
                    queue.append((target, child_extra, child_path))
    return paths


def find_forbidden(
    lock: Mapping[str, Any],
    root: str,
    forbidden: Iterable[str] = FORBIDDEN_FOR_LIGHT_PACKAGES,
    extras: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Return ``{forbidden package: path}`` for every forbidden package in the closure."""
    forbidden = tuple(forbidden)
    closure = dependency_closure(lock, root, extras)
    return {name: path for name, path in closure.items() if is_forbidden(name, forbidden)}


def format_path(path: Iterable[str]) -> str:
    """Render a dependency path as ``a → b → c``."""
    return " → ".join(path)

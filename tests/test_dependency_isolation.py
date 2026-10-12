"""R-12: qc-api and qc-dashboard never pull torch, torchvision, timm or onnxruntime.

SPEC-001 §4.5.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "uv.lock"


def _load_lockgraph() -> ModuleType:
    spec = importlib.util.spec_from_file_location("partqc_lockgraph", ROOT / "tests/lockgraph.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lockgraph = _load_lockgraph()


@pytest.fixture(scope="module")
def lock() -> dict:
    return lockgraph.load_lock(LOCK_PATH)


# ---------- lock real ----------


@pytest.mark.parametrize("package", ["qc-api", "qc-dashboard"])
def test_light_packages_have_no_ml_runtime(lock: dict, package: str) -> None:
    found = lockgraph.find_forbidden(lock, package)
    details = "; ".join(lockgraph.format_path(path) for path in found.values())
    assert not found, f"R-12 violated: {details}"


@pytest.mark.parametrize("package", ["qc-api", "qc-dashboard"])
def test_closure_actually_walks_the_graph(lock: dict, package: str) -> None:
    closure = lockgraph.dependency_closure(lock, package)
    assert "qc-contracts" in closure
    assert "pydantic" in closure  # transitive, through qc-contracts


def test_api_closure_follows_requested_extras(lock: dict) -> None:
    closure = lockgraph.dependency_closure(lock, "qc-api")
    # psycopg[binary,pool] -> psycopg-binary / psycopg-pool only exist through the extras
    assert closure["psycopg-binary"] == ["qc-api", "psycopg", "psycopg-binary"]
    assert "psycopg-pool" in closure


def test_ml_base_closure_has_no_torch_or_timm(lock: dict) -> None:
    found = lockgraph.find_forbidden(lock, "qc-ml", forbidden={"torch", "timm"})
    assert found == {}


def test_ml_train_extra_declares_training_stack(lock: dict) -> None:
    (qc_ml,) = [p for p in lock["package"] if p["name"] == "qc-ml"]
    train = {dep["name"] for dep in qc_ml["optional-dependencies"]["train"]}
    assert {"torch", "torchvision", "timm", "onnx", "coral-pytorch"} <= train

    pyproject = tomllib.loads((ROOT / "ml/pyproject.toml").read_text(encoding="utf-8"))
    declared = set(pyproject["project"]["optional-dependencies"]["train"])
    assert declared == {"torch", "torchvision", "timm", "onnx", "coral-pytorch"}


def test_ml_train_extra_reaches_torch_in_closure(lock: dict) -> None:
    found = lockgraph.find_forbidden(lock, "qc-ml", forbidden={"torch"}, extras=["train"])
    assert found["torch"] == ["qc-ml", "torch"]


# ---------- lock sintético (controle negativo) ----------


def _pkg(name: str, deps: list[dict] | None = None, **extra: object) -> dict:
    package: dict = {"name": name, "version": "1.0.0", "dependencies": deps or []}
    package.update(extra)
    return package


def test_synthetic_transitive_torch_is_reported_with_path() -> None:
    lock = {
        "package": [
            _pkg("qc-api", [{"name": "pkg-x"}]),
            _pkg("pkg-x", [{"name": "torch"}]),
            _pkg("torch"),
        ]
    }
    found = lockgraph.find_forbidden(lock, "qc-api")
    assert list(found) == ["torch"]
    assert lockgraph.format_path(found["torch"]) == "qc-api → pkg-x → torch"


def test_synthetic_onnxruntime_variant_is_forbidden() -> None:
    lock = {
        "package": [
            _pkg("qc-dashboard", [{"name": "onnxruntime-gpu"}]),
            _pkg("onnxruntime-gpu"),
        ]
    }
    assert lockgraph.find_forbidden(lock, "qc-dashboard") == {
        "onnxruntime-gpu": ["qc-dashboard", "onnxruntime-gpu"]
    }


def test_synthetic_requested_extra_is_followed() -> None:
    lock = {
        "package": [
            _pkg("qc-api", [{"name": "pkg-x", "extra": ["ml"]}]),
            _pkg("pkg-x", **{"optional-dependencies": {"ml": [{"name": "timm"}]}}),
            _pkg("timm"),
        ]
    }
    found = lockgraph.find_forbidden(lock, "qc-api")
    assert found == {"timm": ["qc-api", "pkg-x", "timm"]}


def test_synthetic_unrequested_extra_and_dev_deps_are_ignored() -> None:
    lock = {
        "package": [
            _pkg(
                "qc-api",
                [{"name": "pkg-x"}],
                **{
                    "optional-dependencies": {"heavy": [{"name": "torch"}]},
                    "dev-dependencies": {"dev": [{"name": "torchvision"}]},
                },
            ),
            _pkg("pkg-x", **{"optional-dependencies": {"ml": [{"name": "timm"}]}}),
            _pkg("torch"),
            _pkg("torchvision"),
            _pkg("timm"),
        ]
    }
    assert lockgraph.find_forbidden(lock, "qc-api") == {}
    # the same root extra, when requested, is followed
    assert lockgraph.find_forbidden(lock, "qc-api", extras=["heavy"]) == {
        "torch": ["qc-api", "torch"]
    }


def test_synthetic_cycle_terminates() -> None:
    lock = {"package": [_pkg("a", [{"name": "b"}]), _pkg("b", [{"name": "a"}])]}
    assert set(lockgraph.dependency_closure(lock, "a")) == {"a", "b"}


def test_unknown_root_raises() -> None:
    with pytest.raises(KeyError):
        lockgraph.dependency_closure({"package": []}, "qc-api")

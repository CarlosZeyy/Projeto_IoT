"""infra/tests/docker_support.py and the `docker` marker (SPEC-015 section 4.14), without Docker."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
support = sys.modules["partqc_docker_support"]  # loaded by infra/tests/conftest.py


def test_marker_is_declared() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert [m for m in markers if m.startswith("docker:")]


@pytest.mark.parametrize(
    ("environ", "enabled"),
    [
        ({}, False),
        ({"PARTQC_DOCKER_TESTS": "true"}, False),
        ({"PARTQC_DOCKER_TESTS": "0"}, False),
        ({"PARTQC_DOCKER_TESTS": " 1"}, False),
        ({"PARTQC_DOCKER_TESTS": "1"}, True),
    ],
)
def test_docker_tests_enabled(environ: dict[str, str], enabled: bool) -> None:
    assert support.docker_tests_enabled(environ) is enabled


def test_check_docker_names_the_failing_command() -> None:
    def run(cmd: list[str]) -> int:
        return 1 if cmd == ["docker", "compose", "version"] else 0

    with pytest.raises(support.DockerUnavailableError, match="compose"):
        support.check_docker(run=run)


def test_check_docker_missing_executable() -> None:
    def run(cmd: list[str]) -> int:
        raise FileNotFoundError(cmd[0])

    with pytest.raises(support.DockerUnavailableError, match="docker version"):
        support.check_docker(run=run)


def test_check_docker_all_ok() -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str]) -> int:
        calls.append(cmd)
        return 0

    support.check_docker(run=run)
    assert calls == [
        ["docker", "version"],
        ["docker", "compose", "version"],
        ["docker", "buildx", "version"],
    ]


def _porcelain() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def test_copy_tracked_tree(tmp_path: Path) -> None:
    before = _porcelain()
    ctx = support.copy_tracked_tree(tmp_path / "ctx", {"x/y.txt": b"z"})
    assert (ctx / "pyproject.toml").is_file()
    assert (ctx / "uv.lock").is_file()
    assert (ctx / "x" / "y.txt").read_bytes() == b"z"
    assert not (ctx / ".git").exists()
    assert _porcelain() == before


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "a/../../b", ""])
def test_copy_tracked_tree_refuses_paths_outside_the_copy(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        support.copy_tracked_tree(tmp_path / "ctx", {bad: b"x"})


def test_copy_tracked_tree_refuses_the_real_tree() -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        support.copy_tracked_tree(ROOT / "infra" / "tests" / "should-not-exist")
    assert not (ROOT / "infra" / "tests" / "should-not-exist").exists()


def test_build_network(monkeypatch: pytest.MonkeyPatch) -> None:
    assert support.build_network({}) == "default"
    assert support.build_network({"PARTQC_DOCKER_BUILD_NETWORK": "host"}) == "host"
    with pytest.raises(support.DockerUnavailableError):
        support.build_network({"PARTQC_DOCKER_BUILD_NETWORK": "bridge; rm"})


def test_docker_run_args_never_use_the_network() -> None:
    assert support.docker_run_args("img", "-c", "x", entrypoint="python") == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "python",
        "img",
        "-c",
        "x",
    ]


def _infra_conftest(config: pytest.Config) -> object:
    target = ROOT / "infra" / "tests" / "conftest.py"
    for plugin in config.pluginmanager.get_plugins():
        path = getattr(plugin, "__file__", None)
        if path and Path(path).resolve() == target:
            return plugin
    raise AssertionError("infra/tests/conftest.py is not loaded")


def test_docker_items_are_skipped_without_the_variable(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hook marks `docker` items as skip when PARTQC_DOCKER_TESTS is not "1"."""
    hook_module = _infra_conftest(request.config)

    class Item:
        def __init__(self, docker: bool) -> None:
            self.docker = docker
            self.markers: list[pytest.MarkDecorator] = []

        def get_closest_marker(self, name: str) -> object | None:
            return object() if (name == "docker" and self.docker) else None

        def add_marker(self, marker: pytest.MarkDecorator) -> None:
            self.markers.append(marker)

    monkeypatch.delenv("PARTQC_DOCKER_TESTS", raising=False)
    items = [Item(True), Item(False)]
    hook_module.pytest_collection_modifyitems(request.config, items)  # type: ignore[arg-type]
    assert [m.mark.kwargs.get("reason") for m in items[0].markers] == [
        "set PARTQC_DOCKER_TESTS=1 to run"
    ]
    assert items[1].markers == []

    monkeypatch.setenv("PARTQC_DOCKER_TESTS", "1")
    monkeypatch.setattr(
        support,
        "check_docker",
        lambda run=None: (_ for _ in ()).throw(support.DockerUnavailableError("`docker x`")),
    )
    with pytest.raises(pytest.UsageError, match="docker x"):
        hook_module.pytest_collection_modifyitems(request.config, [Item(True)])  # type: ignore[arg-type]

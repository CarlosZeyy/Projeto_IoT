"""Hooks and fixtures of the ``docker`` marker (SPEC-015 section 4.14).

* Without ``PARTQC_DOCKER_TESTS=1``, every item marked ``docker`` is skipped.
* With it, and with ``docker`` items selected, Docker, Compose v2 and Buildx must answer
  (``check_docker``); otherwise the session stops with ``pytest.UsageError``.
* ``build_image(dockerfile, extra_files={}) -> str`` (session): builds ``dockerfile`` from a
  temporary copy of the tracked tree (``copy_tracked_tree``) plus ``extra_files``, and returns
  the image tag. The same pair of arguments reuses the image; every image is removed at the end
  of the session.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import ModuleType

import pytest

SUPPORT_MODULE = "partqc_docker_support"


def _load_support() -> ModuleType:
    if SUPPORT_MODULE in sys.modules:
        return sys.modules[SUPPORT_MODULE]
    path = Path(__file__).resolve().parent / "docker_support.py"
    spec = importlib.util.spec_from_file_location(SUPPORT_MODULE, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[SUPPORT_MODULE] = module
    spec.loader.exec_module(module)
    return module


docker_support = _load_support()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_items = [item for item in items if item.get_closest_marker("docker") is not None]
    if not docker_items:
        return
    if not docker_support.docker_tests_enabled(os.environ):
        skip_docker = pytest.mark.skip(reason=docker_support.SKIP_REASON)
        for item in docker_items:
            item.add_marker(skip_docker)
        return
    try:
        docker_support.check_docker()
    except docker_support.DockerUnavailableError as exc:
        raise pytest.UsageError(f"PARTQC_DOCKER_TESTS=1 but Docker is not usable: {exc}") from None


BuildImage = Callable[..., str]


@pytest.fixture(scope="session")
def build_image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[BuildImage]:
    """Factory ``build_image(dockerfile, extra_files={}) -> tag`` (see the module docstring)."""
    built: dict[tuple[str, tuple[tuple[str, bytes], ...]], str] = {}

    def _build(
        dockerfile: str, extra_files: Mapping[str, bytes] = docker_support.NO_EXTRA_FILES
    ) -> str:
        key = (dockerfile, tuple(sorted(extra_files.items())))
        if key in built:
            return built[key]
        context = docker_support.copy_tracked_tree(
            tmp_path_factory.mktemp("docker-context"), extra_files
        )
        digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:12]
        name = Path(dockerfile).name.split(".")[0].lower()
        tag = f"partqc-test-{name}:{digest}-{uuid.uuid4().hex[:8]}"
        docker_support.docker_build(dockerfile, context, tag)
        built[key] = tag
        return tag

    yield _build
    docker_support.remove_images(list(built.values()))

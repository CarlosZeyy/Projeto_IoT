"""Support for the tests marked ``docker`` (SPEC-015 section 4.14).

* ``docker_tests_enabled(environ)``: the ``docker`` tests run only with ``PARTQC_DOCKER_TESTS=1``;
* ``check_docker(run)``: Docker Engine, Compose v2 and Buildx answer, or
  ``DockerUnavailableError`` names the command that failed;
* ``copy_tracked_tree(dest, extra_files)``: a copy of the files tracked by Git (plus test-only
  extra files) outside the real working tree, used as a build context or compose project. The
  real working tree is never written (no ``.env*`` is ever created there).

Helpers for the image tests (not in the SPEC signatures, shared by the author and tester tests):

* ``docker_build(dockerfile, context, tag)``: ``docker build -f <context>/<dockerfile>``;
* ``docker_run_args(image, *args, entrypoint=None)``: a ``docker run --rm --network none``
  command line. Containers never need the network in these tests, and ``none`` also works on a
  host whose bridge networking is broken.

``PARTQC_DOCKER_BUILD_NETWORK`` (optional, tests only): network of the ``RUN`` steps of a build
(``default`` when unset, or ``host``/``none``). ``host`` is a local workaround for a machine
whose bridge networking is broken; the CI never sets it.

Standard library only. Loaded by ``infra/tests/conftest.py`` with
``importlib.util.spec_from_file_location`` (the module name ``partqc_docker_support``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType

REPO_ROOT = Path(__file__).resolve().parents[2]

ENABLE_ENV = "PARTQC_DOCKER_TESTS"
BUILD_NETWORK_ENV = "PARTQC_DOCKER_BUILD_NETWORK"
BUILD_NETWORKS = frozenset({"default", "host", "none"})
SKIP_REASON = "set PARTQC_DOCKER_TESTS=1 to run"

DOCKER_CHECKS: tuple[tuple[str, ...], ...] = (
    ("docker", "version"),
    ("docker", "compose", "version"),
    ("docker", "buildx", "version"),
)
CHECK_TIMEOUT_S = 60
BUILD_TIMEOUT_S = 1500
# Label of every image built by the tests, so a leftover can be found and removed.
TEST_IMAGE_LABEL = "partqc.test=1"


class DockerUnavailableError(RuntimeError):
    """A Docker command needed by the ``docker`` tests failed or does not exist."""


def docker_tests_enabled(environ: Mapping[str, str]) -> bool:
    """``True`` if, and only if, ``PARTQC_DOCKER_TESTS`` is exactly ``"1"``."""
    return environ.get(ENABLE_ENV) == "1"


def _run_quiet(cmd: list[str]) -> int:
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=CHECK_TIMEOUT_S,
        check=False,
    ).returncode


def check_docker(run: Callable[[list[str]], int] | None = None) -> None:
    """Run ``docker version``, ``docker compose version`` and ``docker buildx version``.

    Raises ``DockerUnavailableError``, naming the command, when one returns a non-zero code or
    the executable does not exist.
    """
    runner = run if run is not None else _run_quiet
    for cmd in DOCKER_CHECKS:
        command = " ".join(cmd)
        try:
            code = runner(list(cmd))
        except (OSError, subprocess.SubprocessError) as exc:
            raise DockerUnavailableError(
                f"`{command}` could not run ({type(exc).__name__})"
            ) from None
        if code != 0:
            raise DockerUnavailableError(f"`{command}` failed with exit code {code}")


def tracked_files(root: Path = REPO_ROOT) -> list[str]:
    """Paths (POSIX, relative to ``root``) listed by ``git ls-files``."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=CHECK_TIMEOUT_S,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_relative(rel: str) -> PurePosixPath:
    pure = PurePosixPath(rel)
    if not rel or pure.is_absolute() or ".." in pure.parts or "\\" in rel:
        raise ValueError(f"extra file path must be relative and inside the tree: {rel!r}")
    return pure


# Immutable empty mapping: the default of ``extra_files``.
NO_EXTRA_FILES: Mapping[str, bytes] = MappingProxyType({})


def copy_tracked_tree(dest: Path, extra_files: Mapping[str, bytes] = NO_EXTRA_FILES) -> Path:
    """Copy the tracked files that exist to ``dest`` and write ``extra_files``; return ``dest``.

    ``extra_files`` maps relative POSIX paths to their bytes (e.g. ``{"infra/.env": b"..."}``).
    ``dest`` must be outside the real working tree, which is never written.
    """
    root = REPO_ROOT.resolve()
    target = Path(dest).resolve()
    if _is_within(target, root):
        raise ValueError("dest must be outside the repository working tree")
    extras = {rel: _safe_relative(rel) for rel in extra_files}
    target.mkdir(parents=True, exist_ok=True)
    for rel in tracked_files(root):
        source = root / rel
        if not source.is_file() or source.is_symlink():
            continue  # deleted in the working tree, or a symlink (none is tracked today)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for rel, pure in extras.items():
        destination = target.joinpath(*pure.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(extra_files[rel])
    return target


def build_network(environ: Mapping[str, str] | None = None) -> str:
    """Network of the build ``RUN`` steps (``PARTQC_DOCKER_BUILD_NETWORK``, ``default``)."""
    env = os.environ if environ is None else environ
    value = env.get(BUILD_NETWORK_ENV, "").strip() or "default"
    if value not in BUILD_NETWORKS:
        raise DockerUnavailableError(f"{BUILD_NETWORK_ENV} must be one of {sorted(BUILD_NETWORKS)}")
    return value


def docker_build(dockerfile: str, context: Path, tag: str) -> None:
    """``docker build -f <context>/<dockerfile> -t <tag> <context>`` with BuildKit.

    The Dockerfile path is taken inside ``context``, so its ``<name>.dockerignore`` (next to it)
    is the one BuildKit applies. Raises ``DockerUnavailableError`` with the end of the output.
    """
    cmd = [
        "docker",
        "build",
        "--file",
        str(Path(context) / dockerfile),
        "--tag",
        tag,
        "--label",
        TEST_IMAGE_LABEL,
        "--network",
        build_network(),
        str(context),
    ]
    env = {**os.environ, "DOCKER_BUILDKIT": "1"}
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S, env=env, check=False
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-40:])
        raise DockerUnavailableError(f"docker build of {dockerfile} failed:\n{tail}")


def docker_run_args(image: str, *args: str, entrypoint: str | None = None) -> list[str]:
    """``docker run --rm --network none [--entrypoint E] <image> <args...>``."""
    cmd = ["docker", "run", "--rm", "--network", "none"]
    if entrypoint is not None:
        cmd += ["--entrypoint", entrypoint]
    return [*cmd, image, *args]


def remove_images(tags: list[str]) -> None:
    """Best-effort ``docker image rm -f`` of the given tags."""
    if tags:
        subprocess.run(
            ["docker", "image", "rm", "-f", *tags],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=CHECK_TIMEOUT_S * 2,
            check=False,
        )

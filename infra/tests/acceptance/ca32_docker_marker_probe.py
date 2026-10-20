"""Probe for the ``docker`` marker hooks of SPEC-015 section 4.14 (not collected by the suite).

The file name does not match ``test_*.py``, so the normal session never collects it. The
acceptance test ``test_extra_docker_marker_hook_*`` runs it in a subprocess, by explicit path,
with a controlled environment. It runs no pytest itself and uses no database.
"""

from __future__ import annotations

import pytest


@pytest.mark.docker
def test_probe_docker_item() -> None:
    assert True

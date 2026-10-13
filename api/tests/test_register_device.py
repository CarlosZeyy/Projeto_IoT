"""``scripts/register_device.py`` (SPEC-004 section 4.6), run with ``subprocess``."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.main import create_app

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "register_device.py"
KEY_PREFIX = "DEVICE_API_KEY="


def _run(*args: str, database_url: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _key(result: subprocess.CompletedProcess[str]) -> str:
    lines = result.stdout.splitlines()
    assert len(lines) == 1, result.stdout
    assert lines[0].startswith(KEY_PREFIX)
    return lines[0].removeprefix(KEY_PREFIX)


@pytest.mark.parametrize("device_id", ["Edge_01", "edge-01\n", "ab", "x" * 33, ""])
def test_invalid_device_id_exits_2(device_id: str, no_db_url: str) -> None:
    result = _run("--device-id", device_id, database_url=no_db_url)
    assert result.returncode == 2
    assert KEY_PREFIX not in result.stdout


def test_missing_url_exits_2() -> None:
    result = _run("--device-id", "lab-02")
    assert result.returncode == 2
    assert KEY_PREFIX not in result.stdout


def test_missing_device_id_exits_2(no_db_url: str) -> None:
    assert _run(database_url=no_db_url).returncode == 2


def test_invalid_url_exits_2_without_echo(fake_password: str) -> None:
    result = _run("--device-id", "lab-02", "--database-url", f"host=x pass {fake_password} =")
    assert result.returncode == 2
    assert fake_password not in result.stdout + result.stderr


def test_unreachable_database_exits_1_without_leaking(no_db_url: str, fake_password: str) -> None:
    result = _run("--device-id", "lab-02", "--database-url", no_db_url)
    assert result.returncode == 1
    assert KEY_PREFIX not in result.stdout
    assert fake_password not in result.stdout + result.stderr


@pytest.mark.db
def test_register_then_use_then_rotate(clean_db: str, settings_for, make_payload) -> None:
    result = _run("--device-id", "lab-02", database_url=clean_db)
    assert result.returncode == 0, result.stderr
    key = _key(result)
    assert len(key) >= 43
    assert key not in result.stderr
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        row = conn.execute("select * from devices where device_id = 'lab-02'").fetchone()
    assert row[1] == hashlib.sha256(key.encode()).hexdigest()
    assert all(key not in str(value) for value in row)

    again = _run("--device-id", "lab-02", database_url=clean_db)
    assert again.returncode == 1
    assert KEY_PREFIX not in again.stdout

    rotated = _run("--device-id", "lab-02", "--rotate", "--database-url", clean_db)
    assert rotated.returncode == 0, rotated.stderr
    new_key = _key(rotated)
    assert new_key != key

    with TestClient(create_app(settings_for(clean_db))) as client:
        old = client.post(
            "/api/v1/inspections",
            json=make_payload(device_id="lab-02"),
            headers={"X-API-Key": key},
        )
        new = client.post(
            "/api/v1/inspections",
            json=make_payload(device_id="lab-02"),
            headers={"X-API-Key": new_key},
        )
    assert old.status_code == 401
    assert new.status_code == 201


@pytest.mark.db
def test_rotate_unknown_device_exits_1(clean_db: str) -> None:
    result = _run("--rotate", "--device-id", "ghost-01", database_url=clean_db)
    assert result.returncode == 1
    assert KEY_PREFIX not in result.stdout
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        assert conn.execute("select count(*) from devices").fetchone()[0] == 0

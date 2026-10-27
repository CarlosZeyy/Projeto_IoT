"""Support of the tests marked ``mqtt`` (SPEC-020 section 6): a real Mosquitto, local only.

* ``skip_reason(environ)``: ``None`` when the ``mqtt`` tests can run (``PARTQC_MQTT_TESTS`` is
  exactly ``"1"`` and ``mosquitto`` and ``mosquitto_passwd`` are on the ``PATH``), else the reason
  to skip. The CI never sets the variable, so these tests never run there.
* ``start_mosquitto(directory)``: a broker on a free port of ``127.0.0.1`` (``listener <port>
  127.0.0.1``, ``allow_anonymous false``) with a random user and password, written with
  ``mosquitto_passwd`` into ``directory`` (a ``tmp_path``, never the repository);
  ``MosquittoBroker.stop()`` and ``restart()`` (same port and credentials) simulate a fall of the
  broker. No public broker and no external network (SPEC-020 section 6).

Loaded by path by ``edge/tests/conftest.py`` (``load_mosquitto_support``); standard library only.
"""

from __future__ import annotations

import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENABLE_ENV = "PARTQC_MQTT_TESTS"
EXECUTABLES = ("mosquitto", "mosquitto_passwd")
HOST = "127.0.0.1"
START_TIMEOUT_S = 10.0
STOP_TIMEOUT_S = 10.0


def skip_reason(environ: Mapping[str, str]) -> str | None:
    """Why the ``mqtt`` tests are skipped, or ``None`` when they can run."""
    if environ.get(ENABLE_ENV) != "1":
        return f"set {ENABLE_ENV}=1 (and install mosquitto) to run"
    missing = [name for name in EXECUTABLES if shutil.which(name) is None]
    if missing:
        return f"{', '.join(missing)} not found on the PATH"
    return None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def write_config(directory: Path, port: int, password_file: Path) -> Path:
    config = directory / "mosquitto.conf"
    config.write_text(
        f"listener {port} {HOST}\n"
        "allow_anonymous false\n"
        f"password_file {password_file}\n"
        "persistence false\n",
        encoding="utf-8",
    )
    return config


def _spawn(config: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["mosquitto", "-c", str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@dataclass
class MosquittoBroker:
    process: subprocess.Popen[bytes]
    config: Path
    host: str
    port: int
    username: str
    password: str

    def restart(self) -> None:
        """Start the broker again with the same port, user and password (after ``stop``)."""
        self.stop()
        self.process = _spawn(self.config)
        _wait_listening(self.process, self.port)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(STOP_TIMEOUT_S)


def _wait_listening(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"mosquitto exited with code {process.returncode}")
        try:
            with socket.create_connection((HOST, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("mosquitto did not start listening in time")


def start_mosquitto(directory: Path) -> MosquittoBroker:
    """Start a broker with a random user and password; ``directory`` is created (``0700``)."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    username = "partqc-test-" + secrets.token_hex(4)
    password = secrets.token_urlsafe(18)
    password_file = directory / "passwd"
    subprocess.run(
        ["mosquitto_passwd", "-b", "-c", str(password_file), username, password],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    password_file.chmod(0o600)
    port = free_port()
    config = write_config(directory, port, password_file)
    process = _spawn(config)
    broker = MosquittoBroker(process, config, HOST, port, username, password)
    try:
        _wait_listening(process, port)
    except BaseException:
        broker.stop()
        raise
    return broker

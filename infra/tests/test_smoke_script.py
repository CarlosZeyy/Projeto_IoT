"""scripts/smoke_test.py with a fake API and dashboard (httpx.MockTransport), SPEC-015 section 4.5.

No network: every request goes to the in-process transport.
"""

from __future__ import annotations

import importlib.util
import json
import secrets
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

import qc_contracts

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"
API = "https://api.host-secreto-15.example"
DASH = "https://painel.host-secreto-15.example"
HOST_FRAGMENT = "host-secreto-15"
EXPECTED_ORDER = [
    "health",
    "write_requires_key",
    "write",
    "read_requires_key",
    "read",
    "cors_closed",
    "dashboard",
    "dashboard_health",
]


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("partqc_smoke_test_author", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values = {
        "READ_API_KEY": secrets.token_urlsafe(32),
        "SIM_DEVICE_ID": "sim-01",
        "SIM_DEVICE_API_KEY": secrets.token_urlsafe(32),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CLOUD_API_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    return values


class FakeCloud:
    """API + dashboard; ``faults`` switches a behaviour to the wrong one."""

    def __init__(self, keys: dict[str, str], faults: set[str] | None = None) -> None:
        self.keys = keys
        self.faults = faults or set()
        self.stored: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "connect_error" in self.faults:
            raise httpx.ConnectError(f"cannot reach {request.url.host}", request=request)
        path = request.url.path
        key = request.headers.get("x-api-key")
        if request.url.host.startswith("painel.") or request.url.port == 8501:
            return self._dashboard(path)
        headers = {}
        if "cors_open" in self.faults:
            headers["access-control-allow-origin"] = "*"
        if path == "/api/v1/health":
            body = {
                "status": "ok",
                "db": "error" if "db_error" in self.faults else "ok",
                "api_version": "0.1.0",
                "contract_version": "9.9.9"
                if "contract" in self.faults
                else qc_contracts.__version__,
            }
            return httpx.Response(200, json=body, headers=headers)
        if path == "/api/v1/inspections" and request.method == "POST":
            if key != self.keys["SIM_DEVICE_API_KEY"] and "write_open" not in self.faults:
                return httpx.Response(401, json={"detail": "Missing or invalid API key"})
            item = json.loads(request.content)
            assert item["source"] == "simulated"
            self.stored[item["inspection_id"]] = item
            return httpx.Response(
                201, json={"inspection_id": item["inspection_id"], "status": "created"}
            )
        if path == "/api/v1/inspections" and request.method == "GET":
            if key != self.keys["READ_API_KEY"] and "read_open" not in self.faults:
                return httpx.Response(401, json={"detail": "Missing or invalid API key"})
            lot = request.url.params.get("lot_id")
            items = [
                i
                for i in self.stored.values()
                if i["lot_id"] == lot and i["source"] == request.url.params.get("source")
            ]
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 50, "offset": 0}
            )
        return httpx.Response(404)

    def _dashboard(self, path: str) -> httpx.Response:
        if path == "/_stcore/health":
            if "dash_502" in self.faults:
                return httpx.Response(502)
            return httpx.Response(200, text="nope" if "dash_nope" in self.faults else "ok")
        return httpx.Response(200, text="<html></html>")


def _run(
    smoke: ModuleType,
    cloud: FakeCloud,
    capsys: pytest.CaptureFixture[str],
    argv: list[str] | None = None,
) -> tuple[int, list[str], str]:
    code = smoke.main(
        argv if argv is not None else ["--api-url", API, "--dashboard-url", DASH],
        transport=httpx.MockTransport(cloud.handler),
    )
    out, err = capsys.readouterr()
    return code, out.splitlines(), out + err


def test_all_checks_pass_in_order(smoke, keys, capsys) -> None:
    cloud = FakeCloud(keys)
    code, lines, _ = _run(smoke, cloud, capsys)
    assert code == 0
    assert lines == [f"PASS {name}" for name in EXPECTED_ORDER]
    (written,) = cloud.stored.values()
    assert written["source"] == "simulated"
    assert written["lot_id"].startswith("SMOKE-")
    assert written["model_version"] == "smoke-v0"
    assert written["model_sha256"] == "0" * 64


def test_urls_default_to_the_environment(smoke, keys, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CLOUD_API_URL", API)
    monkeypatch.setenv("DASHBOARD_URL", DASH + "/")
    code, lines, _ = _run(smoke, FakeCloud(keys), capsys, argv=[])
    assert code == 0
    assert len(lines) == 8


@pytest.mark.parametrize(
    ("fault", "failed"),
    [
        ("write_open", "write_requires_key"),
        ("read_open", "read_requires_key"),
        ("cors_open", "cors_closed"),
        ("db_error", "health"),
        ("contract", "health"),
        ("dash_nope", "dashboard_health"),
        ("dash_502", "dashboard_health"),
    ],
)
def test_a_wrong_behaviour_fails_its_check(smoke, keys, capsys, fault, failed) -> None:
    code, lines, _ = _run(smoke, FakeCloud(keys, {fault}), capsys)
    assert code == 1
    assert [line for line in lines if line.startswith("FAIL")][0].startswith(f"FAIL {failed}:")


@pytest.mark.parametrize(
    "argv",
    [
        ["--api-url", "http://api.exemplo.org", "--dashboard-url", DASH],
        ["--api-url", API, "--dashboard-url", "http://painel.exemplo.org"],
        ["--api-url", "https://u:p@api.exemplo.org", "--dashboard-url", DASH],
        ["--api-url", API + "?x=1", "--dashboard-url", DASH],
        ["--api-url", "", "--dashboard-url", DASH],
    ],
)
def test_invalid_url_is_usage_error_without_requests(smoke, keys, capsys, argv) -> None:
    cloud = FakeCloud(keys)
    code, _, output = _run(smoke, cloud, capsys, argv=argv)
    assert code == 2
    assert cloud.requests == []
    assert "exemplo.org" not in output and HOST_FRAGMENT not in output


@pytest.mark.parametrize("missing", ["READ_API_KEY", "SIM_DEVICE_ID", "SIM_DEVICE_API_KEY"])
def test_missing_variable_is_usage_error(smoke, keys, capsys, monkeypatch, missing) -> None:
    monkeypatch.delenv(missing)
    cloud = FakeCloud(keys)
    code, _, output = _run(smoke, cloud, capsys)
    assert code == 2
    assert cloud.requests == []
    assert missing in output


def test_http_is_accepted_only_on_loopback(smoke, keys, capsys) -> None:
    cloud = FakeCloud(keys)
    argv = ["--api-url", "http://127.0.0.1:8001", "--dashboard-url", "http://localhost:8501"]
    code, _, _ = _run(smoke, cloud, capsys, argv=argv)
    assert code == 0
    assert {(r.url.scheme, r.url.host) for r in cloud.requests} == {
        ("http", "127.0.0.1"),
        ("http", "localhost"),
    }


@pytest.mark.parametrize("faults", [set(), {"read_open", "cors_open"}, {"connect_error"}])
def test_output_never_has_keys_nor_host(smoke, keys, capsys, faults) -> None:
    code, lines, output = _run(smoke, FakeCloud(keys, faults), capsys)
    assert code == (0 if not faults else 1)
    for value in (keys["READ_API_KEY"], keys["SIM_DEVICE_API_KEY"], HOST_FRAGMENT):
        assert value not in output
    if "connect_error" in faults:
        assert lines[0] == "FAIL health: ConnectError"


def test_source_never_disables_tls_verification() -> None:
    assert "verify=False" not in SCRIPT.read_text(encoding="utf-8")


def test_check_names_are_the_spec_order(smoke) -> None:
    assert list(smoke.CHECK_NAMES) == EXPECTED_ORDER

"""POST /api/capture in collect mode, the capture page and the console coverage (SPEC-010)."""

from __future__ import annotations

import csv
import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from qc_edge import app as app_module
from qc_edge import netinfo
from qc_edge.app import create_app
from qc_edge.collect import MANIFEST_COLUMNS
from qc_edge.config import EdgeSettings
from qc_edge.inference import StubInferencer
from qc_edge.limits import CAPTURE_MAX_BYTES
from qc_edge.sink import InMemorySink

NOW = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
LOCAL = ("127.0.0.1", 50000)
FIELDS = {
    "mode": "collect",
    "item_id": "S-012",
    "object_type": "screw",
    "grade": "fair",
    "labeler": "a",
    "angle": "2",
    "notes": "dúvida fair/poor",
}


class _Clock:
    def __init__(self, step: timedelta = timedelta(0)) -> None:
        self.now = NOW
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


class Edge:
    def __init__(
        self,
        settings: EdgeSettings,
        inferencer: Any = None,
        clock: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        self.settings = settings
        self.sink = InMemorySink()
        self.app = create_app(settings, inferencer, self.sink, clock=clock or _Clock(), **kwargs)
        self.token: str = self.app.state.session_token
        self.client = TestClient(self.app)

    def post(
        self,
        image: bytes,
        token: str | None = "valid",
        headers: dict[str, str] | None = None,
        **changes: str | None,
    ) -> Any:
        data = {**FIELDS, **changes}
        data = {key: value for key, value in data.items() if value is not None}
        sent = dict(headers or {})
        if token == "valid":
            sent["X-Session-Token"] = self.token
        elif token is not None:
            sent["X-Session-Token"] = token
        files = {"image": ("photo.jpg", image, "image/jpeg")}
        return self.client.post("/api/capture", headers=sent, data=data, files=files)

    @property
    def root(self) -> Path:
        return self.settings.DATASET_DIR

    def files(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))

    def rows(self) -> list[dict[str, str]]:
        with (self.root / "manifest.csv").open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


@pytest.fixture
def edge(settings: EdgeSettings) -> Edge:
    return Edge(settings)


def test_collect_success_without_model(edge: Edge, jpeg_bytes: bytes) -> None:
    response = edge.post(jpeg_bytes, headers={"User-Agent": "M" * 80})
    assert response.status_code == 200
    assert response.json() == {
        "mode": "collect",
        "image_path": "raw/screw/fair/S-012__2__20261022T141503Z.jpg",
        "item_id": "S-012",
        "angle": 2,
        "item_images": 1,
    }
    assert (edge.root / "raw/screw/fair/S-012__2__20261022T141503Z.jpg").read_bytes() == jpeg_bytes
    header = (edge.root / "manifest.csv").read_text(encoding="utf-8").split("\n", 1)[0]
    assert header == ",".join(MANIFEST_COLUMNS)
    [row] = edge.rows()
    assert row["captured_at"] == "2026-10-22T14:15:03Z"
    assert row["capture_device"] == "M" * 60
    assert row["notes"] == "dúvida fair/poor"
    assert edge.sink.items == []
    # Nothing of the inspect mode is touched.
    assert not (edge.settings.EDGE_DATA_DIR / "captures").exists()


def test_collect_never_calls_the_inferencer_nor_the_sink(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    stub = StubInferencer()
    edge = Edge(settings, inferencer=stub, clock=_Clock(timedelta(seconds=1)))
    statuses = [edge.post(jpeg_bytes, angle=str(angle)).status_code for angle in range(3)]
    assert statuses == [200, 200, 200]
    assert stub.calls == 0
    assert edge.sink.items == []
    assert len(edge.rows()) == 3


def test_lot_id_is_ignored_in_collect_mode(edge: Edge, jpeg_bytes: bytes) -> None:
    assert edge.post(jpeg_bytes, lot_id="not a lot\n").status_code == 200
    assert edge.post(jpeg_bytes, angle="3").status_code == 200  # no lot_id at all
    assert "lot_id" not in edge.rows()[0]


def test_other_without_grade(edge: Edge, jpeg_bytes: bytes) -> None:
    response = edge.post(jpeg_bytes, item_id="O-004", object_type="other", grade="", angle="0")
    assert response.status_code == 200
    assert response.json()["image_path"] == "raw/other/_/O-004__0__20261022T141503Z.jpg"
    assert edge.rows()[0]["grade"] == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"item_id": "S-012\n"},
        {"angle": "2\n"},
        {"object_type": "screw\n"},
        {"item_id": "../S-001"},
        {"item_id": "N-001"},
        {"item_id": "T-001", "object_type": "other", "grade": ""},
        {"object_type": "unknown"},
        {"grade": None},
        {"grade": "excellent"},
        {"item_id": "O-004", "object_type": "other", "grade": "good"},
        {"labeler": "c"},
        {"angle": "5"},
        {"notes": "x" * 201},
        {"notes": "linha 1\nlinha 2"},
    ],
)
def test_invalid_fields_are_422_and_touch_nothing(
    edge: Edge, jpeg_bytes: bytes, changes: dict[str, str | None]
) -> None:
    response = edge.post(jpeg_bytes, **changes)
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert not edge.root.exists()  # not even DATASET_DIR is created


def test_token_size_and_image_errors_store_nothing(
    edge: Edge, jpeg_bytes: bytes, make_image: Callable[..., bytes]
) -> None:
    assert edge.post(jpeg_bytes, token=None).status_code == 401
    assert edge.post(jpeg_bytes, token="wrong").status_code == 401
    assert edge.post(b"\xff" * (CAPTURE_MAX_BYTES + 1)).status_code == 413
    assert edge.post(b"just text").status_code == 415
    assert edge.post(make_image((2001, 2000))).status_code == 415
    assert edge.files() == []


def test_png_is_saved_as_jpeg(edge: Edge, make_image: Callable[..., bytes]) -> None:
    response = edge.post(make_image(fmt="PNG"))
    assert response.status_code == 200
    saved = (edge.root / response.json()["image_path"]).read_bytes()
    assert saved.startswith(b"\xff\xd8\xff")


def test_conflicts_and_header_mismatch(edge: Edge, jpeg_bytes: bytes) -> None:
    assert edge.post(jpeg_bytes).status_code == 200
    again = edge.post(jpeg_bytes)
    assert again.status_code == 409
    assert again.json() == {"detail": "capture already exists, try again"}
    assert len(edge.rows()) == 1

    manifest = edge.root / "manifest.csv"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "raw/screw/good/O-007__0__20261001T000000Z.jpg,O-007,screw,good,a,0,"
        "2026-10-01T00:00:00Z,,\n",
        encoding="utf-8",
    )
    conflict = edge.post(jpeg_bytes, item_id="O-007", object_type="other", grade="")
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "item_id already registered with another object_type"}

    manifest.write_text("a,b,c\n", encoding="utf-8")
    mismatch = edge.post(jpeg_bytes, angle="4")
    assert mismatch.status_code == 500
    assert mismatch.json() == {"detail": "manifest header mismatch"}
    assert manifest.read_text(encoding="utf-8") == "a,b,c\n"
    assert len(list(edge.root.rglob("*.jpg"))) == 1


def test_write_failure_is_500_without_traceback(
    edge: Edge, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_jpeg(handle: Any, data: bytes, image: Image.Image) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("qc_edge.collect.write_capture_jpeg", failing_jpeg)
    response = edge.post(jpeg_bytes)
    assert response.status_code == 500
    assert response.json() == {"detail": "failed to write dataset"}
    assert list(edge.root.rglob("*.jpg")) == []


def test_collect_uses_the_decode_limiter(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    edge = Edge(settings, max_concurrent_decodes=1, decode_wait_s=0.2)
    inside = threading.Event()
    release = threading.Event()
    original = app_module.load_capture_image

    def slow_load(data: bytes) -> Image.Image:
        inside.set()
        release.wait(timeout=10)
        return original(data)

    monkeypatch.setattr(app_module, "load_capture_image", slow_load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(edge.post, jpeg_bytes)
        assert inside.wait(timeout=5)
        busy = edge.post(jpeg_bytes, angle="3")
        release.set()
        assert first.result(timeout=10).status_code == 200
    assert busy.status_code == 503
    assert busy.json() == {"detail": "server busy"}
    assert len(edge.rows()) == 1


def test_dataset_is_never_served(edge: Edge, jpeg_bytes: bytes) -> None:
    image_path = edge.post(jpeg_bytes).json()["image_path"]
    for url in (
        f"/{image_path}",
        "/ml/data/manifest.csv",
        "/manifest.csv",
        f"/static/../{image_path}",
        "/dataset/manifest.csv",
    ):
        assert edge.client.get(url).status_code == 404, url


def test_notes_are_not_logged(
    edge: Edge, jpeg_bytes: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert edge.post(jpeg_bytes, notes="segredo-da-nota").status_code == 200
    assert "segredo-da-nota" not in caplog.text
    assert edge.token not in caplog.text
    assert "raw/screw/fair/S-012__2__20261022T141503Z.jpg" in caplog.text


# ---------------------------------------------------------------------------------- capture page


def test_capture_page_has_the_collect_fields(edge: Edge) -> None:
    page = edge.client.get("/capture", params={"t": edge.token}).text
    assert '<option value="collect">coleta</option>' in page
    for name in ("item_id", "object_type", "grade", "labeler", "angle", "notes"):
        assert re.search(rf'id="{name}" name="{name}"', page), name
    # PT-BR labels: object types and the 5 grades of qc_contracts.labels.
    for value, label in (("screw", "parafuso"), ("nut", "porca"), ("other", "outro")):
        assert f'<option value="{value}">{label}</option>' in page
    for value, label in (
        ("perfect", "perfeito"),
        ("good", "bom"),
        ("fair", "mediano"),
        ("poor", "ruim"),
        ("unusable", "inutilizável"),
    ):
        assert f'<option value="{value}">{label}</option>' in page
    assert "Sem pessoas no quadro" in page
    assert "Peça completa — troque o item_id" in page
    assert "$" not in page  # every template placeholder was substituted


def test_capture_script_rules() -> None:
    script = (app_module.STATIC_DIR / "capture.js").read_text(encoding="utf-8")
    assert len(script.splitlines()) <= 200
    assert "/^[SNOT]-[0-9]{3}$/" in script
    assert "localStorage" in script
    assert "Salvo: " in script and "fotos desta peça: " in script
    assert "http://" not in script and "https://" not in script


# -------------------------------------------------------------------------------------- console


@pytest.fixture
def lan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])


def _coverage_table(page: str) -> str:
    match = re.search(r'<table id="coverage">.*?</table>', page, re.S)
    assert match, "no coverage table"
    return match.group(0)


def test_console_coverage_without_manifest(edge: Edge, lan: None) -> None:
    page = TestClient(edge.app, client=LOCAL).get("/").text
    table = _coverage_table(page)
    assert table.count("<tr><td>") == 11
    assert table.count("0/120") == 10 and table.count("0/12<") == 10
    assert "0/150" in table and "0/30" in table
    assert 'id="coverage-total">0<' in table


def test_console_coverage_after_collecting(
    settings: EdgeSettings, lan: None, jpeg_bytes: bytes
) -> None:
    edge = Edge(settings, clock=_Clock(timedelta(seconds=1)))
    for angle in range(5):
        assert edge.post(jpeg_bytes, angle=str(angle), grade="perfect").status_code == 200
    page = TestClient(edge.app, client=LOCAL).get("/").text
    table = _coverage_table(page)
    assert "<tr><td>parafuso</td><td>perfeito</td><td>5/120</td><td>1/12</td></tr>" in table
    assert 'id="coverage-total">5<' in table


def test_console_highlights_complete_cells(edge: Edge, lan: None) -> None:
    edge.root.mkdir()
    with (edge.root / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(MANIFEST_COLUMNS)
        for i in range(150):
            item_id = f"O-{i % 30:03d}"
            writer.writerow((f"raw/other/_/{item_id}__0__{i}.jpg", item_id, "other", "", "a"))
    table = _coverage_table(TestClient(edge.app, client=LOCAL).get("/").text)
    assert '<tr class="complete"><td>outro</td><td>—</td><td>150/150</td><td>30/30</td></tr>' in (
        table
    )


def test_console_survives_an_unreadable_manifest(edge: Edge, lan: None) -> None:
    edge.root.mkdir()
    (edge.root / "manifest.csv").write_bytes(b"\xff\xfe\x00broken")
    response = TestClient(edge.app, client=LOCAL).get("/")
    assert response.status_code == 200
    assert 'id="coverage-warning"' in response.text
    assert 'id="coverage-total">0<' in _coverage_table(response.text)

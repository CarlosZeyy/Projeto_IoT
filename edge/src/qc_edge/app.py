"""FastAPI app of the edge gateway (SPEC-007 sections 4.2 to 4.7, SPEC-010, docs/architecture.md
section 6).

Routes: ``GET /`` (operator console, loopback only), ``GET /capture`` (phone page, token in the
query), ``/static/*`` (page assets), ``POST /api/capture`` and ``GET /api/status`` (token in the
``X-Session-Token`` header).

Photos stay on this machine (R-02): inspections are written under ``EDGE_DATA_DIR/captures``,
collect-mode images and the manifest under ``DATASET_DIR``, and no route serves either directory.
Only the ``InspectionCreate`` of the inspect mode goes to the sink; the collect mode never calls
the inferencer nor the sink. The session token is never logged (R-03); the request log records
the route without the query string.
"""

# No ``from __future__ import annotations`` here: FastAPI resolves the ``Depends`` annotations of
# the route closures at runtime, and a string annotation could not see the local dependencies.
import contextlib
import csv
import html
import logging
import math
import re
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Annotated, Any
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageFile
from starlette.datastructures import UploadFile

from qc_contracts import (
    GRADE_LABELS_PT,
    GRADE_ORDER,
    LOT_ID_PATTERN,
    OBJECT_TYPE_LABELS_PT,
    CaptureMode,
    Grade,
    InspectionCreate,
    ObjectType,
    Source,
    is_defective,
)
from qc_contracts import __version__ as contract_version
from qc_edge import netinfo
from qc_edge.collect import (
    CAPTURE_DEVICE_MAX_LENGTH,
    GRADED_MIN_ITEMS,
    GRADED_TARGET_IMAGES,
    GRADED_TARGET_ITEMS,
    OTHER_TARGET_IMAGES,
    OTHER_TARGET_ITEMS,
    CollectError,
    CollectRequest,
    CoverageCell,
    DatasetObjectType,
    DatasetWriter,
    InvalidCollectFieldError,
    empty_coverage,
)
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceError, Inferencer
from qc_edge.jpeg import write_capture_jpeg
from qc_edge.limits import CAPTURE_MAX_BYTES, CAPTURE_MAX_REQUEST_BYTES, load_capture_image
from qc_edge.middleware import (
    BodySizeLimitMiddleware,
    RequestLogMiddleware,
    UnhandledErrorMiddleware,
)
from qc_edge.security import (
    SESSION_TOKEN_HEADER,
    SESSION_TOKEN_QUERY,
    resolve_session_token,
    token_matches,
)
from qc_edge.sink import BackgroundService, InspectionSink, SinkError
from qc_preprocess import InvalidImageError

logger = logging.getLogger("qc_edge")

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

RECENT_INSPECTIONS = 10
CAPTURES_SUBDIR = "captures"
# Collect-mode form fields (SPEC-010 section 4.1); lot_id is ignored in that mode.
COLLECT_FIELDS = ("item_id", "object_type", "grade", "labeler", "angle", "notes")
# lot_id, mode and the collect-mode fields of SPEC-010, with room to spare. A single file part
# (the image).
MAX_FORM_FIELDS = 16
MAX_FORM_FILES = 1

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "cf-connecting-ip")

DETAIL_INVALID_TOKEN = "invalid session token"
DETAIL_IMAGE_TOO_LARGE = "image too large"
DETAIL_SERVER_BUSY = "server busy"
DETAIL_MODEL_NOT_LOADED = "model not loaded"
DETAIL_INFERENCE_FAILED = "inference failed"
DETAIL_PERSIST_FAILED = "failed to persist inspection"
DETAIL_INTERNAL = "internal server error"

INVALID_SESSION_HTML = (
    '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
    "<title>PartQC</title></head><body>"
    "<p>Sessão inválida. Leia o QR code no console.</p></body></html>"
)
FORBIDDEN_HTML = (
    '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
    "<title>PartQC</title></head><body>"
    "<p>O console só abre no próprio notebook (http://127.0.0.1).</p></body></html>"
)
NO_LAN_WARNING_HTML = (
    '<p class="warning" id="no-lan-warning">Nenhum IP de rede local foi detectado: o QR code '
    "aponta para 127.0.0.1 e o celular não vai conseguir abrir. Conecte o notebook ao Wi-Fi ou "
    "ao hotspot do celular e espere o console recarregar.</p>"
)

CONNECTIVITY_LABELS_PT = {
    "online": "online",
    "offline": "offline",
    "auth_error": "erro de autenticação",
    "disabled": "desativada (nada é enviado à nuvem)",
}
VERDICT_APPROVED = "aprovada"
VERDICT_REJECTED = "reprovada"
VERDICT_UNKNOWN = "desconhecido"

# Classes of the collect mode in PT-BR. ``other`` is a model class, not a contract value, so it
# has no entry in ``qc_contracts.labels``.
DATASET_OBJECT_TYPE_LABELS_PT = {
    DatasetObjectType.SCREW: OBJECT_TYPE_LABELS_PT[ObjectType.SCREW],
    DatasetObjectType.NUT: OBJECT_TYPE_LABELS_PT[ObjectType.NUT],
    DatasetObjectType.OTHER: "outro",
}
COVERAGE_UNREADABLE_HTML = (
    '<p class="warning" id="coverage-warning">Não foi possível ler o manifest.csv do dataset: '
    "confira o arquivo no notebook. A tabela abaixo está zerada.</p>"
)

# Sensitive pages: never cached, and the token in the URL never leaks through a Referer.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def utc_now() -> datetime:
    """Current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class CaptureForm:
    """Validated fields of ``POST /api/capture``.

    ``lot_id`` is ``None`` in collect mode (ignored there); ``collect`` and ``capture_device``
    (the first 60 characters of ``User-Agent``) are only set in collect mode.
    """

    image: bytes
    lot_id: str | None
    mode: CaptureMode
    collect: CollectRequest | None = None
    capture_device: str = ""


@dataclass(frozen=True)
class RecentInspection:
    """One row of the console table."""

    inspection_id: uuid.UUID
    inspected_at: datetime
    lot_id: str
    object_type: ObjectType
    grade: Grade | None


def _verdict(grade: Grade | None) -> tuple[bool | None, str]:
    """``(approved, verdict label)``; the defect rule is only ``qc_contracts.is_defective``."""
    if grade is None:
        return None, VERDICT_UNKNOWN
    approved = not is_defective(grade)
    return approved, VERDICT_APPROVED if approved else VERDICT_REJECTED


def _qr_svg(text: str) -> str:
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage)
    return image.to_string(encoding="unicode")


def _validate_limiter(max_concurrent_decodes: int, decode_wait_s: float) -> None:
    if (
        isinstance(max_concurrent_decodes, bool)
        or not isinstance(max_concurrent_decodes, int)
        or max_concurrent_decodes < 1
    ):
        raise ValueError("max_concurrent_decodes must be an integer >= 1")
    if (
        isinstance(decode_wait_s, bool)
        or not isinstance(decode_wait_s, int | float)
        or not math.isfinite(decode_wait_s)
        or decode_wait_s <= 0
    ):
        raise ValueError("decode_wait_s must be a finite number > 0")


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


class _CaptureStore:
    """Writes and removes photos under ``EDGE_DATA_DIR/captures/<YYYY-MM-DD>/``.

    File names are always generated here (``<inspection_id>.jpg``); nothing from the client is
    used. The lock covers "create the day directory and the file" and "remove the file and the
    empty day directory", so a cleanup never removes a directory another request is writing to.
    """

    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / CAPTURES_SUBDIR
        self._lock = threading.Lock()

    def save(self, inspection: InspectionCreate, data: bytes, image: Image.Image) -> Path:
        day_dir = self._root / inspection.inspected_at.astimezone(UTC).strftime("%Y-%m-%d")
        path = day_dir / f"{inspection.inspection_id}.jpg"
        with self._lock:
            day_dir.mkdir(parents=True, exist_ok=True)
            handle = path.open("xb")
        try:
            with handle:
                write_capture_jpeg(handle, data, image)
        except BaseException:
            self.remove(path)
            raise
        return path

    def remove(self, path: Path) -> None:
        with self._lock:
            path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):  # only removed when the day directory is empty
                path.parent.rmdir()


def create_app(
    settings: EdgeSettings,
    inferencer: Inferencer | None,
    sink: InspectionSink,
    *,
    background: Sequence[BackgroundService] = (),
    clock: Callable[[], datetime] = utc_now,
    max_concurrent_decodes: int = 2,
    decode_wait_s: float = 10.0,
) -> FastAPI:
    """Build the edge gateway app.

    ``inferencer=None`` means no model is loaded: ``mode=inspect`` answers 503. The app refuses
    to start (``RuntimeError`` in the lifespan) when ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is
    enabled. ``background`` services are started in order at startup and stopped in reverse
    order at shutdown.

    Raises:
        ValueError: ``max_concurrent_decodes < 1`` or ``decode_wait_s <= 0``.
    """
    _validate_limiter(max_concurrent_decodes, decode_wait_s)

    session_token = resolve_session_token(settings)
    decode_slots = threading.BoundedSemaphore(max_concurrent_decodes)
    recent: deque[RecentInspection] = deque(maxlen=RECENT_INSPECTIONS)
    recent_lock = threading.Lock()
    store = _CaptureStore(settings.EDGE_DATA_DIR)
    dataset = DatasetWriter(settings.DATASET_DIR, clock=clock)
    console_template = Template((TEMPLATES_DIR / "console.html").read_text(encoding="utf-8"))
    capture_page = _render_capture_page()
    services = tuple(background)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # SEC-04: first thing, before any background service. No qc_edge module changes the
        # flag, so it cannot become true after this check.
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise RuntimeError(
                "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; the edge gateway refuses to "
                "start because truncated images would be accepted"
            )
        started: list[BackgroundService] = []
        try:
            for service in services:
                service.start()
                started.append(service)
            logger.info("qc-edge started (device_id=%s)", settings.DEVICE_ID)
            yield
        finally:
            for service in reversed(started):
                try:
                    service.stop()
                except Exception:
                    logger.exception("background service failed to stop")
            logger.info("qc-edge stopped")

    app = FastAPI(
        title="PartQC edge gateway",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.session_token = session_token

    # Added last = outermost: the request log sees every status, including 413 and 500.
    app.add_middleware(BodySizeLimitMiddleware, limit=CAPTURE_MAX_REQUEST_BYTES)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_header_token(request: Request) -> None:
        if not token_matches(request.headers.get(SESSION_TOKEN_HEADER), session_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_INVALID_TOKEN
            )

    async def read_capture_form(request: Request) -> CaptureForm:
        """Token (401), then the image size (413), then the fields (422).

        The token is checked before the body is parsed. The image is read at most up to
        ``CAPTURE_MAX_BYTES + 1`` bytes; the form (and its spooled file) is closed here. In
        collect mode ``lot_id`` is ignored and the fields of SPEC-010 section 4.1 are validated
        instead, before anything touches the disk.
        """
        require_header_token(request)
        form = await request.form(max_files=MAX_FORM_FILES, max_fields=MAX_FORM_FIELDS)
        try:
            upload = form.get("image")
            data: bytes | None = None
            if isinstance(upload, UploadFile):
                data = await upload.read(CAPTURE_MAX_BYTES + 1)
                if len(data) > CAPTURE_MAX_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=DETAIL_IMAGE_TOO_LARGE,
                    )
            lot_id = form.get("lot_id")
            mode = form.get("mode")
            collect_fields = {name: form.get(name) for name in COLLECT_FIELDS}
        finally:
            await form.close()

        if data is None:
            raise _unprocessable("image")
        try:
            capture_mode = CaptureMode(mode) if isinstance(mode, str) else None
        except ValueError:
            capture_mode = None
        if capture_mode is None:
            raise _unprocessable("mode")
        if capture_mode is CaptureMode.COLLECT:
            try:
                collect_request = CollectRequest.from_fields(collect_fields)
            except InvalidCollectFieldError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail
                ) from None
            return CaptureForm(
                image=data,
                lot_id=None,
                mode=capture_mode,
                collect=collect_request,
                capture_device=request.headers.get("user-agent", "")[:CAPTURE_DEVICE_MAX_LENGTH],
            )
        if not isinstance(lot_id, str) or re.fullmatch(LOT_ID_PATTERN, lot_id) is None:
            raise _unprocessable("lot_id")
        return CaptureForm(image=data, lot_id=lot_id, mode=capture_mode)

    def decode(data: bytes) -> Image.Image | JSONResponse:
        """``load_capture_image`` (415 or 500 as a response); called holding a decode slot."""
        try:
            return load_capture_image(data)
        except InvalidImageError as exc:
            logger.info("capture refused: invalid image (%s)", exc)
            return _error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"invalid image: {exc}")
        except RuntimeError as exc:
            # LOAD_TRUNCATED_IMAGES: a server configuration error, never an image defect.
            logger.error("capture refused: %s", exc)
            return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, DETAIL_INTERNAL)

    def collect(form: CaptureForm) -> JSONResponse:
        """SPEC-010 section 4.2; runs while holding a decode slot. No inferencer, no sink."""
        if form.collect is None:  # read_capture_form always sets it in collect mode
            return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, DETAIL_INTERNAL)
        image = decode(form.image)
        if isinstance(image, JSONResponse):
            return image
        try:
            result = dataset.write(form.collect, form.image, image, form.capture_device)
        except CollectError as exc:
            logger.warning("collect refused: %s", exc.detail)
            return _error(exc.status_code, exc.detail)
        return JSONResponse(
            content={
                "mode": CaptureMode.COLLECT.value,
                "image_path": result.image_path,
                "item_id": result.item_id,
                "angle": result.angle,
                "item_images": result.item_images,
            }
        )

    def inspect(form: CaptureForm) -> JSONResponse:
        """Steps 3 to 8 of section 4.5; runs while holding a decode slot."""
        image = decode(form.image)
        if isinstance(image, JSONResponse):
            return image

        if inferencer is None:
            return _error(status.HTTP_503_SERVICE_UNAVAILABLE, DETAIL_MODEL_NOT_LOADED)

        inspection_id = uuid.uuid4()
        inspected_at = clock()
        try:
            result = inferencer.infer(image)
        except InferenceError as exc:
            logger.warning("inference failed: %s", exc)
            return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, DETAIL_INFERENCE_FAILED)
        model = inferencer.model_info

        # Built (and validated by the contract) before the photo is written, so an invalid
        # result never leaves an orphan file behind.
        inspection = InspectionCreate(
            inspection_id=inspection_id,
            device_id=settings.DEVICE_ID,
            lot_id=form.lot_id,
            inspected_at=inspected_at,
            object_type=result.object_type,
            grade=result.grade,
            grade_score=result.grade_score,
            type_confidence=result.type_confidence,
            grade_confidence=result.grade_confidence,
            needs_review=result.needs_review,
            model_version=model.model_version,
            model_sha256=model.model_sha256,
            latency_ms=result.latency_ms,
            source=Source.LIVE,
        )

        path = store.save(inspection, form.image, image)
        try:
            sink.put(inspection)
        except SinkError as exc:
            store.remove(path)
            logger.error("capture not persisted: %s", exc)
            return _error(status.HTTP_503_SERVICE_UNAVAILABLE, DETAIL_PERSIST_FAILED)
        except BaseException:
            store.remove(path)
            raise

        with recent_lock:
            recent.appendleft(
                RecentInspection(
                    inspection_id=inspection.inspection_id,
                    inspected_at=inspection.inspected_at,
                    lot_id=inspection.lot_id,
                    object_type=inspection.object_type,
                    grade=inspection.grade,
                )
            )
        approved, verdict = _verdict(inspection.grade)
        logger.info(
            "capture accepted inspection_id=%s lot_id=%s object_type=%s grade=%s latency_ms=%d",
            inspection.inspection_id,
            inspection.lot_id,
            inspection.object_type.value,
            inspection.grade.value if inspection.grade is not None else "-",
            inspection.latency_ms,
        )
        return JSONResponse(
            content={
                "inspection": inspection.model_dump(mode="json"),
                "labels_pt": {
                    "object_type": OBJECT_TYPE_LABELS_PT[inspection.object_type],
                    "grade": (
                        GRADE_LABELS_PT[inspection.grade] if inspection.grade is not None else None
                    ),
                    "verdict": verdict,
                },
                "approved": approved,
            }
        )

    @app.post("/api/capture")
    def capture(form: Annotated[CaptureForm, Depends(read_capture_form)]) -> JSONResponse:
        """Synchronous on purpose: decoding, inference and file writes run in the threadpool."""
        # SEC-02: every decode of qc_edge (header probe included) holds one of these slots, in
        # both modes (SPEC-010 section 4.1).
        if not decode_slots.acquire(timeout=decode_wait_s):
            logger.warning("capture refused: no decode slot within %.1f s", decode_wait_s)
            return _error(status.HTTP_503_SERVICE_UNAVAILABLE, DETAIL_SERVER_BUSY)
        try:
            if form.mode is CaptureMode.COLLECT:
                return collect(form)
            return inspect(form)
        finally:
            decode_slots.release()

    @app.get("/api/status", dependencies=[Depends(require_header_token)])
    def api_status() -> dict[str, Any]:
        stats = sink.stats()
        model = inferencer.model_info if inferencer is not None else None
        return {
            "device_id": settings.DEVICE_ID,
            "contract_version": contract_version,
            "model": {
                "loaded": model is not None,
                "model_version": model.model_version if model is not None else None,
                "model_sha256": model.model_sha256 if model is not None else None,
            },
            "sink": {
                "pending": stats.pending,
                "dead": stats.dead,
                "last_success_at": (
                    stats.last_success_at.isoformat() if stats.last_success_at else None
                ),
                "connectivity": stats.connectivity,
            },
        }

    @app.get("/capture", response_class=HTMLResponse)
    def capture_page_route(request: Request) -> HTMLResponse:
        if not token_matches(request.query_params.get(SESSION_TOKEN_QUERY), session_token):
            return HTMLResponse(
                INVALID_SESSION_HTML, status_code=status.HTTP_401_UNAUTHORIZED, headers=PAGE_HEADERS
            )
        return HTMLResponse(capture_page, headers=PAGE_HEADERS)

    @app.get("/", response_class=HTMLResponse)
    def console(request: Request) -> HTMLResponse:
        if not _is_local_console_request(request):
            return HTMLResponse(
                FORBIDDEN_HTML, status_code=status.HTTP_403_FORBIDDEN, headers=PAGE_HEADERS
            )
        ips = netinfo.detect_lan_ips()  # recomputed on every render (hotspot switch)
        requested_ip = request.query_params.get("ip")
        ip = requested_ip if requested_ip in ips else ips[0]
        capture_url = _capture_url(ip, settings.EDGE_PORT, session_token)
        with recent_lock:
            rows = list(recent)
        page = console_template.substitute(
            device_id=html.escape(settings.DEVICE_ID),
            ip_warning=NO_LAN_WARNING_HTML if netinfo.is_fallback(ips) else "",
            qr_svg=_qr_svg(capture_url),
            capture_url=html.escape(capture_url),
            other_ips=_other_ips_html(ips, ip),
            model_state=html.escape(_model_state(inferencer)),
            **_sink_fields(sink),
            rows="\n".join(_row_html(row) for row in rows),
            dataset_dir=html.escape(str(settings.DATASET_DIR.absolute())),
            coverage=_coverage_html(dataset),
        )
        return HTMLResponse(page, headers=PAGE_HEADERS)

    return app


def _render_capture_page() -> str:
    """``capture.html`` with the collect-mode options; labels come from ``qc_contracts``."""
    template = Template((TEMPLATES_DIR / "capture.html").read_text(encoding="utf-8"))
    object_types = "\n".join(
        f'<option value="{member.value}">{html.escape(label)}</option>'
        for member, label in DATASET_OBJECT_TYPE_LABELS_PT.items()
    )
    grades = "\n".join(
        f'<option value="{grade.value}">{html.escape(GRADE_LABELS_PT[grade])}</option>'
        for grade in GRADE_ORDER
    )
    return template.substitute(object_type_options=object_types, grade_options=grades)


def _coverage_html(dataset: DatasetWriter) -> str:
    """Coverage table of the console (SPEC-010 section 4.4)."""
    warning = ""
    try:
        cells = dataset.coverage()
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        logger.warning("cannot read the dataset manifest (%s)", type(exc).__name__)
        cells, warning = empty_coverage(), COVERAGE_UNREADABLE_HTML
    rows = "\n".join(_coverage_row_html(cell) for cell in cells)
    total = sum(cell.images for cell in cells)
    targets = (
        f"<p>Meta por tipo e grau: {GRADED_TARGET_IMAGES} imagens e {GRADED_TARGET_ITEMS} peças "
        f"(mínimo {GRADED_MIN_ITEMS}). Outro: {OTHER_TARGET_IMAGES} imagens e "
        f"{OTHER_TARGET_ITEMS} objetos. Em verde, as células que atingiram as duas metas.</p>\n"
    )
    return (
        f'{targets}{warning}<table id="coverage">\n'
        "<thead><tr><th>Tipo</th><th>Grau</th><th>Imagens/meta</th><th>Peças/meta</th></tr>"
        f"</thead>\n<tbody>\n{rows}\n</tbody>\n"
        '<tfoot><tr><th colspan="2">Total de imagens</th>'
        f'<td colspan="2" id="coverage-total">{total}</td></tr></tfoot>\n</table>'
    )


def _coverage_row_html(cell: CoverageCell) -> str:
    object_type = DATASET_OBJECT_TYPE_LABELS_PT[DatasetObjectType(cell.object_type)]
    grade = GRADE_LABELS_PT[Grade(cell.grade)] if cell.grade is not None else "—"
    cells = (
        object_type,
        grade,
        f"{cell.images}/{cell.target_images}",
        f"{cell.items}/{cell.target_items}",
    )
    tds = "".join(f"<td>{html.escape(value)}</td>" for value in cells)
    css = ' class="complete"' if cell.complete else ""
    return f"<tr{css}>{tds}</tr>"


def _capture_url(ip: str, port: int, token: str) -> str:
    """URL of the phone page, encoded in the pairing QR code."""
    return f"http://{ip}:{port}/capture?{SESSION_TOKEN_QUERY}={quote(token, safe='')}"


def _unprocessable(field: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"missing or invalid {field}"
    )


def _is_local_console_request(request: Request) -> bool:
    """Loopback client and no proxy header (docs/architecture.md sections 8 and 9)."""
    client = request.client
    if client is None or client.host not in LOOPBACK_HOSTS:
        return False
    return not any(name in request.headers for name in PROXY_HEADERS)


def _model_state(inferencer: Inferencer | None) -> str:
    if inferencer is None:
        return "não carregado (o modo inspeção responde 503)"
    return f"carregado: {inferencer.model_info.model_version}"


def _sink_fields(sink: InspectionSink) -> dict[str, str]:
    stats = sink.stats()
    last = stats.last_success_at
    return {
        "sink_pending": str(stats.pending),
        "sink_dead": str(stats.dead),
        "connectivity": html.escape(CONNECTIVITY_LABELS_PT.get(stats.connectivity, "?")),
        "last_success_at": html.escape(
            last.astimezone().strftime("%d/%m %H:%M:%S") if last is not None else "—"
        ),
    }


def _other_ips_html(ips: list[str], current: str) -> str:
    others = [ip for ip in ips if ip != current]
    if not others:
        return ""
    links = " ".join(
        f'<a href="/?ip={html.escape(ip, quote=True)}">{html.escape(ip)}</a>' for ip in others
    )
    return f"<p>Outros IPs desta máquina: {links}</p>"


def _row_html(row: RecentInspection) -> str:
    grade = GRADE_LABELS_PT[row.grade] if row.grade is not None else "—"
    cells = (
        row.inspected_at.astimezone().strftime("%H:%M:%S"),
        row.lot_id,
        OBJECT_TYPE_LABELS_PT[row.object_type],
        grade,
    )
    tds = "".join(f"<td>{html.escape(cell)}</td>" for cell in cells)
    return f'<tr class="inspection" data-inspection-id="{row.inspection_id}">{tds}</tr>'

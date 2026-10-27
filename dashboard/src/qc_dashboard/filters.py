"""Global sidebar, simulated-data badge and error messages (SPEC-013 §4.1, §4.2; SPEC-028).

``render_sidebar()`` is called at the top of every page. Widget values are kept in
``st.session_state`` across pages: Streamlit gives a widget on another page a different
identity, so each widget starts from the last value remembered under ``_mem_<key>``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, NoReturn

import streamlit as st

from qc_contracts import LOT_ID_PATTERN, SOURCE_LABELS_PT, ObjectType, Source
from qc_dashboard import data
from qc_dashboard.api import ApiAuthError, ApiError, ApiUnavailable, Filters
from qc_dashboard.config import (
    CONFIG_MISSING_MESSAGE,
    INSECURE_API_URL_MESSAGE,
    ConfigError,
    InsecureApiUrlError,
)
from qc_dashboard.formatting import LOCAL_TZ, object_type_label

__all__ = [
    "Filters",
    "api_guard",
    "needs_simulated_badge",
    "period_to_utc",
    "render_api_error",
    "render_badge",
    "render_badge_or_error",
    "render_chart_badge",
    "render_sidebar",
    "source_caption",
    "spc_origin_caption",
]

# Widget keys of the sidebar (also used by the tests).
KEY_SOURCE = "flt_source"
KEY_PERIOD = "flt_period"
KEY_TYPE = "flt_type"
KEY_LOT = "flt_lot"
KEY_RETRY = "api_retry"

SOURCE_REAL = "Real"
SOURCE_SIMULATED = "Simulado"
SOURCE_ALL = "Todos"
SOURCE_OPTIONS: tuple[str, ...] = (SOURCE_REAL, SOURCE_SIMULATED, SOURCE_ALL)
SOURCE_BY_OPTION: dict[str, Source | None] = {
    SOURCE_REAL: Source.LIVE,
    SOURCE_SIMULATED: Source.SIMULATED,
    SOURCE_ALL: None,
}

ALL = "Todos"
TYPE_OPTIONS: tuple[str, ...] = (ALL, *(object_type_label(t) for t in ObjectType))
TYPE_BY_OPTION: dict[str, ObjectType | None] = {
    ALL: None,
    **{object_type_label(t): t for t in ObjectType},
}

# Types of the SPC filter (``Controle estatístico``): the members of the API's ``SpcObjectType``
# (SPEC-016 section 4.3), in its order. The dashboard does not import ``qc_api``; these are the
# grade-required and grade-optional types of the contract (ADR-021, decision 3), declared here,
# and a test pins them to the contract groups. The power tools (SPEC-021) are grade-forbidden:
# never in the SPC, so never here.
SPC_OBJECT_TYPES: tuple[ObjectType, ...] = (
    ObjectType.SCREW,
    ObjectType.NUT,
    ObjectType.PLIERS,
    ObjectType.ADJUSTABLE_WRENCH,
    ObjectType.ALLEN_KEY,
    ObjectType.FLAT_SCREWDRIVER,
    ObjectType.PHILLIPS_SCREWDRIVER,
)

DEFAULT_PERIOD_DAYS = 7

BADGE_TEXT = "Contém dados simulados"
INVALID_LOT_TEXT = "Lote inválido"
API_WAKING_TEXT = "API acordando (free tier), tente em ~1 min"
RETRY_LABEL = "Tentar novamente"
AUTH_ERROR_TEXT = "Chave de leitura inválida ou ausente (READ_API_KEY)."

# Errors the API pages turn into a PT-BR message (``api_guard``).
API_ERRORS: tuple[type[Exception], ...] = (ConfigError, ApiUnavailable, ApiAuthError, ApiError)

SOURCE_CAPTIONS: dict[Source | None, str] = {
    Source.LIVE: "Origem dos dados: real",
    Source.SIMULATED: "Origem dos dados: simulado",
    None: "Origem dos dados: todas (real + simulado)",
}


# ---------- state across pages ----------


def _mem(key: str) -> str:
    return f"_mem_{key}"


def recall(key: str, default: Any) -> Any:
    """Last value remembered for the widget ``key`` (``default`` in a new session)."""
    return st.session_state.get(_mem(key), default)


def remember(key: str, value: Any) -> None:
    st.session_state[_mem(key)] = value


def option_index(options: tuple[Any, ...], key: str, default: Any) -> int:
    """Index of the remembered option of ``key``; the default's index if it is not an option."""
    value = recall(key, default)
    return options.index(value) if value in options else options.index(default)


# ---------- period ----------


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def default_period() -> tuple[date, date]:
    """The last 7 local days, today included."""
    today = local_today()
    return today - timedelta(days=DEFAULT_PERIOD_DAYS - 1), today


def period_to_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """``from``/``to`` in UTC: start of the first local day, start of the day after the last.

    Days are local to ``America/Sao_Paulo``; the bounds are swapped if given in reverse.
    """
    if end < start:
        start, end = end, start
    from_ = datetime.combine(start, time.min, tzinfo=LOCAL_TZ).astimezone(UTC)
    to = datetime.combine(end + timedelta(days=1), time.min, tzinfo=LOCAL_TZ).astimezone(UTC)
    return from_, to


def _period_bounds(value: Any) -> tuple[date, date]:
    """``(start, end)`` of a ``date_input`` range, which has 0, 1 or 2 dates while editing."""
    if isinstance(value, date):
        return value, value
    dates = [d for d in (value or ()) if isinstance(d, date)]
    if not dates:
        return default_period()
    return dates[0], dates[-1]


# ---------- sidebar ----------


def valid_lot_id(text: str) -> bool:
    return re.fullmatch(LOT_ID_PATTERN, text) is not None


def render_sidebar() -> Filters:
    """Global filters: origin (default ``Real``), period (last 7 days), type and lot."""
    sidebar = st.sidebar
    sidebar.header("Filtros")
    source_option = sidebar.radio(
        "Origem",
        SOURCE_OPTIONS,
        index=option_index(SOURCE_OPTIONS, KEY_SOURCE, SOURCE_REAL),
        key=KEY_SOURCE,
    )
    remember(KEY_SOURCE, source_option)

    period = sidebar.date_input(
        "Período",
        value=recall(KEY_PERIOD, default_period()),
        format="DD/MM/YYYY",
        key=KEY_PERIOD,
    )
    remember(KEY_PERIOD, period)
    from_, to = period_to_utc(*_period_bounds(period))

    type_option = sidebar.selectbox(
        "Tipo",
        TYPE_OPTIONS,
        index=option_index(TYPE_OPTIONS, KEY_TYPE, ALL),
        key=KEY_TYPE,
    )
    remember(KEY_TYPE, type_option)

    lot_text = sidebar.text_input(
        "Lote", value=recall(KEY_LOT, ""), placeholder="ex.: L-001", key=KEY_LOT
    )
    remember(KEY_LOT, lot_text)
    lot_text = (lot_text or "").strip()
    lot_id: str | None = None
    if lot_text:
        if valid_lot_id(lot_text):
            lot_id = lot_text
        else:
            sidebar.error(INVALID_LOT_TEXT)

    return Filters(
        source=SOURCE_BY_OPTION[source_option],
        from_=from_,
        to=to,
        object_type=TYPE_BY_OPTION[type_option],
        lot_id=lot_id,
    )


def source_caption(filters: Filters) -> str:
    """Which origins the indicators include (R-06): always shown under the page title."""
    return SOURCE_CAPTIONS[filters.source]


# ---------- simulated badge (R-06) ----------


def needs_simulated_badge(filters: Filters) -> bool:
    """True for ``Simulado``, or for ``Todos`` when the same filters have simulated data.

    The check for ``Todos`` is one (cached) summary request with ``source=simulated``.
    """
    if filters.source is Source.SIMULATED:
        return True
    if filters.source is None:
        return data.fetch_summary(replace(filters, source=Source.SIMULATED)).total > 0
    return False


def show_badge() -> None:
    """The badge itself: a warning on the page and the legend in the sidebar."""
    st.warning(BADGE_TEXT)
    st.sidebar.caption(BADGE_TEXT)


def render_badge(filters: Filters, *, simulated: bool = False) -> bool:
    """Show the badge (page top and sidebar) when needed; ``simulated`` forces it."""
    show = simulated or needs_simulated_badge(filters)
    if show:
        show_badge()
    return show


def render_badge_or_error(filters: Filters) -> bool:
    """``render_badge`` for a page that does not need the API ("Sobre o modelo", SPEC-028 §4.4).

    When the badge check fails, the error message of ``api_guard`` is shown **and** the badge
    (conservative, R-06), and the page goes on: nothing here calls ``st.stop()``.
    """
    try:
        return render_badge(filters)
    except API_ERRORS as exc:
        show_error(exc)
        show_badge()
        return True


def render_chart_badge(chart_source: Source) -> bool:
    """Badge of the p chart page: if, and only if, the chart origin is ``simulated``.

    It does not depend on the sidebar and makes no request (SPEC-028 §4.3).
    """
    show = chart_source is Source.SIMULATED
    if show:
        show_badge()
    return show


def spc_origin_caption(chart_source: Source | str) -> str:
    """``Origem da carta: real`` or ``Origem da carta: simulado``, shown outside the figure."""
    return f"Origem da carta: {SOURCE_LABELS_PT[Source(chart_source)]}"


# ---------- errors ----------


def _retry() -> None:
    """Only a rerun (SPEC-028 §4.2): errors are not cached, so the new attempt reaches the API,
    and the successful reads of every session stay in the cache."""
    st.rerun()


def show_api_error(exc: Exception) -> None:
    """PT-BR message for an API error, without stack trace (the page goes on)."""
    if isinstance(exc, ApiUnavailable):
        st.warning(API_WAKING_TEXT)
        if st.button(RETRY_LABEL, key=KEY_RETRY):
            _retry()
    elif isinstance(exc, ApiAuthError):
        st.error(AUTH_ERROR_TEXT)
    elif isinstance(exc, ApiError):
        st.error(f"Erro da API (HTTP {exc.status}).")
    else:
        st.error("Erro inesperado ao ler a API.")


def render_api_error(exc: Exception) -> NoReturn:
    """``show_api_error``, then ``st.stop()``."""
    show_api_error(exc)
    st.stop()


def show_config_error(exc: ConfigError) -> None:
    """``Configuração inválida`` for an insecure ``API_BASE_URL``; ``Configuração ausente``
    otherwise. Neither names the value (R-03)."""
    if isinstance(exc, InsecureApiUrlError):
        st.error(INSECURE_API_URL_MESSAGE)
    else:
        st.error(CONFIG_MISSING_MESSAGE)


def render_config_error(exc: ConfigError) -> NoReturn:
    show_config_error(exc)
    st.stop()


def show_error(exc: Exception) -> None:
    """The message of ``api_guard`` for ``exc``, without stopping the page."""
    if isinstance(exc, ConfigError):
        show_config_error(exc)
    else:
        show_api_error(exc)


@contextmanager
def api_guard() -> Iterator[None]:
    """Turn a missing or invalid configuration or an API error into its message and stop."""
    try:
        yield
    except ConfigError as exc:
        render_config_error(exc)
    except (ApiUnavailable, ApiAuthError, ApiError) as exc:
        render_api_error(exc)

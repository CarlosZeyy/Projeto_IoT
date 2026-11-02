"""Acceptance tests for SPEC-043, the ``infra/`` and documentation part: CA-08, CA-09, CA-16, CA-17.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_extra_*`` tests are exploratory edge cases that no CA spells out.

No network and no database: ``psycopg.connect`` fails the test on the refused paths, and the
regression case uses a closed local port. Sentinels come from ``secrets.token_hex``, and URLs with
credentials are assembled at run time (``reviews/checklist.md`` section 4).

"§8, item 5" of the SPEC is step 5 of ``### 1. statement_timeout`` in ``docs/deployment-plan.md``
(SPEC section 4.5, item 7), not the ``### 5. Alertas no Telegram`` section; the dev report records
the same reading. "§8, item 4" is the ``### 4. Simulador em produção`` section.
"""

from __future__ import annotations

import logging
import re
import secrets
import socket
import traceback
from pathlib import Path
from typing import Any

import psycopg
import pytest
from migrate import (
    DatabaseConnectionError,
    UnsupportedConnectionError,
    _host_port,
    apply_migrations,
    main,
    pending_migrations,
)

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SCHEME = "postgresql" + "://"
NOT_6543 = ["slash", "numeric-slash", "at-colon"]
ALL_M = ["at-6543", *NOT_6543]
PORT_6543_MESSAGE = "transaction pooler (port 6543) is not supported for migrations"
EXAMPLE_LINE = "DATABASE_URL=" + SCHEME + "<user>:<password>@<host>:6543/postgres"


def malformed_urls(a: str, b: str) -> dict[str, str]:
    """The four malformed URLs (M) of SPEC-043 section 5."""
    return {
        "at-6543": f"{SCHEME}u:{a}@{b}@db.example.org:6543/postgres",
        "slash": f"{SCHEME}u:{a}/{b}@db.example.org:5432/postgres",
        "numeric-slash": f"{SCHEME}u:12/{b}@db.example.org:5432/postgres",
        "at-colon": f"{SCHEME}u:{a}@{b}:x@db.example.org:5432/postgres",
    }


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def sentinels() -> tuple[str, str]:
    return secrets.token_hex(8), secrets.token_hex(8)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "PGPORT", "PGHOST", "PGDATABASE", "PGSERVICE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def no_connect(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def refuse(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not run
        calls.append((args, kwargs))
        pytest.fail("psycopg.connect called with a malformed URL", pytrace=False)

    monkeypatch.setattr(psycopg, "connect", refuse)
    return calls


def run_main(
    argv: list[str], capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> tuple[int, str]:
    capsys.readouterr()
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        code = main(argv)
    captured = capsys.readouterr()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    return code, "\n".join((captured.out, captured.err, logged))


# --------------------------------------------------------------------------- CA-08


@pytest.mark.parametrize("label", NOT_6543)
@pytest.mark.parametrize("argv", [["--status"], []], ids=["status", "apply"])
def test_ca08_main_refuses_malformed_url_with_the_hint(
    label: str,
    argv: list[str],
    sentinels: tuple[str, str],
    no_connect: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, b = sentinels
    monkeypatch.setenv("DATABASE_URL", malformed_urls(a, b)[label])

    code, output = run_main(argv, capsys, caplog)

    assert code == 2
    assert "invalid database URL (not shown)" in output
    assert "percent-encode" in output
    assert PORT_6543_MESSAGE not in output
    assert no_connect == []
    assert a not in output
    assert b not in output


@pytest.mark.parametrize("argv", [["--status"], []], ids=["status", "apply"])
def test_ca08_main_keeps_the_port_6543_refusal(
    argv: list[str],
    sentinels: tuple[str, str],
    no_connect: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, b = sentinels
    monkeypatch.setenv("DATABASE_URL", malformed_urls(a, b)["at-6543"])

    code, output = run_main(argv, capsys, caplog)

    assert code == 2
    assert PORT_6543_MESSAGE in output
    assert "invalid database URL (not shown)" not in output
    assert no_connect == []
    assert a not in output
    assert b not in output


@pytest.mark.parametrize("label", NOT_6543)
def test_extra_main_refuses_through_the_argument_too(
    label: str,
    sentinels: tuple[str, str],
    no_connect: list[Any],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, b = sentinels

    code, output = run_main(["--database-url", malformed_urls(a, b)[label]], capsys, caplog)

    assert code == 2
    assert "invalid database URL (not shown)" in output
    assert no_connect == []
    assert a not in output
    assert b not in output


def test_extra_section_7_port_abc_is_refused_by_main(
    sentinels: tuple[str, str],
    no_connect: list[Any],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Section 7: ``port=abc`` is now refused in ``main``, with code 2, before connecting."""
    a, _ = sentinels
    url = f"host=db.example.org port=abc user=u {'pass' + 'word'}={a} dbname=x"

    code, output = run_main(["--database-url", url], capsys, caplog)

    assert code == 2
    assert "invalid database URL (not shown)" in output
    assert no_connect == []
    assert a not in output


# --------------------------------------------------------------------------- CA-09


@pytest.mark.parametrize("func", [apply_migrations, pending_migrations], ids=lambda f: f.__name__)
@pytest.mark.parametrize("label", NOT_6543)
def test_ca09_functions_raise_before_connecting(
    func: Any,
    label: str,
    sentinels: tuple[str, str],
    no_connect: list[Any],
) -> None:
    a, b = sentinels

    with pytest.raises(DatabaseConnectionError) as info:
        func(malformed_urls(a, b)[label])

    assert no_connect == []
    assert info.value.__cause__ is None
    text = "".join(traceback.format_exception(info.value)) + repr(info.value)
    assert a not in text
    assert b not in text


@pytest.mark.parametrize("func", [apply_migrations, pending_migrations], ids=lambda f: f.__name__)
def test_ca09_port_6543_raises_unsupported_before_connecting(
    func: Any, sentinels: tuple[str, str], no_connect: list[Any]
) -> None:
    a, b = sentinels

    with pytest.raises(UnsupportedConnectionError) as info:
        func(malformed_urls(a, b)["at-6543"])

    assert no_connect == []
    assert info.value.__cause__ is None
    text = "".join(traceback.format_exception(info.value)) + repr(info.value)
    assert a not in text
    assert b not in text


@pytest.mark.parametrize("label", ALL_M)
def test_ca09_host_port_is_unknown(label: str, sentinels: tuple[str, str]) -> None:
    a, b = sentinels
    assert _host_port(malformed_urls(a, b)[label]) == "unknown host"


@pytest.mark.parametrize("func", [apply_migrations, pending_migrations], ids=lambda f: f.__name__)
def test_ca09_closed_port_keeps_host_port_and_class(func: Any, sentinels: tuple[str, str]) -> None:
    a, _ = sentinels
    port = closed_port()
    # The CA writes port 1; a closed free port is the same case and never hits a real service.
    url = f"{SCHEME}u:{a}@127.0.0.1:{port}/x"

    with pytest.raises(DatabaseConnectionError) as info:
        func(url)

    text = "".join(traceback.format_exception(info.value)) + repr(info.value)
    assert f"127.0.0.1:{port}" in str(info.value)
    assert "OperationalError" in str(info.value)
    assert a not in text


@pytest.mark.parametrize("func", [apply_migrations, pending_migrations], ids=lambda f: f.__name__)
def test_ca09_literal_port_1_of_the_ca(func: Any, sentinels: tuple[str, str]) -> None:
    a, _ = sentinels

    with pytest.raises(DatabaseConnectionError) as info:
        func(f"{SCHEME}u:{a}@127.0.0.1:1/x")

    assert "127.0.0.1:1" in str(info.value)
    assert "OperationalError" in str(info.value)
    assert a not in "".join(traceback.format_exception(info.value))


def test_extra_message_of_the_connect_refusal_is_exact(
    sentinels: tuple[str, str], no_connect: list[Any]
) -> None:
    a, b = sentinels
    with pytest.raises(DatabaseConnectionError) as info:
        pending_migrations(malformed_urls(a, b)["slash"])
    assert str(info.value) == "could not connect to the database: malformed URL (not shown)"


def test_extra_host_port_of_a_well_formed_url_is_unchanged(sentinels: tuple[str, str]) -> None:
    a, _ = sentinels
    assert _host_port(f"{SCHEME}u:{a}@db.example.org:5432/x") == "db.example.org:5432"


# --------------------------------------------------------------------------- CA-16


def _section(text: str, start: str, end: str) -> str:
    head = text.index(start)
    tail = text.index(end, head + len(start))
    return text[head:tail]


@pytest.fixture(scope="module")
def plan() -> str:
    return PLAN.read_text(encoding="utf-8")


def _section_7_item(plan: str, number: int) -> str:
    section = _section(plan, "## 7. Riscos aceitos", "## 8. Operação do banco")
    return _section(section, f"\n{number}. **", f"\n{number + 1}. **")


def _statement_timeout_step_5(plan: str) -> str:
    block = _section(plan, "### 1. `statement_timeout`", "### 2. `READ_API_KEY`")
    return _section(block, "5. **Conferir pelo caminho", "6. Registrar na §9")


def test_ca16_step_1(plan: str) -> None:
    step = _section(plan, "### Passo 1", "### Passo 2")
    for needle in ("só letras e números", "56 linhas", "revoke", "SPEC-043 §4.6"):
        assert needle in step, needle


def test_ca16_step_5(plan: str) -> None:
    step = _section(plan, "### Passo 5", "### Passo 6")
    for needle in (
        "Build time",
        "Literal",
        "Preview deployments",
        "Loading value",
        "No build-time variables",
        "uma variável por vez",
    ):
        assert needle in step, needle


def test_ca16_step_6(plan: str) -> None:
    assert "www.<subdominio>" in _section(plan, "### Passo 6", "### Passo 7")


def test_ca16_section_7_item_2(plan: str) -> None:
    assert "SPEC-043" in _section_7_item(plan, 2)


def test_ca16_section_8_statement_timeout_step(plan: str) -> None:
    step = _statement_timeout_step_5(plan)
    for needle in ("conexões novas", "2min", "30 min"):
        assert needle in step, needle
    assert "SPEC_ISSUE" in step
    assert step.index("30 min") < step.index("SPEC_ISSUE")


def test_ca16_section_8_simulator(plan: str) -> None:
    block = _section(plan, "### 4. Simulador em produção", "### 5. Alertas no Telegram")
    assert "60 s" in block
    assert "mesma seed" in block


def test_ca16_section_7_item_10(plan: str) -> None:
    assert "4.5.3" in _section_7_item(plan, 10)


def test_ca16_ca20_line_of_section_9(plan: str) -> None:
    section = plan[plan.index("## 9. Registro dos CAs manuais") :]
    lines = [line for line in section.splitlines() if line.startswith("| SPEC-039 CA-20 ")]
    assert len(lines) == 1
    assert "true 2" in lines[0]
    assert "com 3 contêineres" not in lines[0]


def test_ca16_old_quote_advice_is_gone(plan: str) -> None:
    assert "aspas simples se tiver" not in plan
    assert "Se a senha tiver" not in plan


def test_ca16_earlier_spec_acceptance_files_still_exist() -> None:
    """The last clause of CA-16: those SPECs' tests run in the full suite (test report).

    This only guards the list: a removed file would silently drop the clause.
    """
    acceptance = REPO_ROOT / "infra" / "tests" / "acceptance"
    for number in ("015", "032", "038", "039", "040"):
        assert (acceptance / f"test_spec_{number}.py").is_file(), number


def test_extra_section_4_5_item_2_explains_the_revoke_order(plan: str) -> None:
    step = _section(plan, "### Passo 1", "### Passo 2")
    assert "4 tabelas × 7 privilégios × 2 papéis" in step
    assert "obrigatório em todo projeto novo" in step


def test_extra_section_4_5_item_6_step_11(plan: str) -> None:
    step = _section(plan, "### Passo 11", "### Passo 12")
    assert "sent=75" in step
    assert re.search(r"c[óo]digo 0", step), step


def test_extra_section_4_5_item_6_references(plan: str) -> None:
    block = _section(plan, "### 4. Simulador em produção", "### 5. Alertas no Telegram")
    assert "17 s" in block
    assert "90 s" in block
    assert "código 5" in block


def test_extra_section_4_5_item_5_warning_in_step_5(plan: str) -> None:
    step = _statement_timeout_step_5(plan)
    assert "um trecho da senha" in step


def test_extra_section_4_5_item_7_keeps_15s_and_cites_ca_26(plan: str) -> None:
    step = _statement_timeout_step_5(plan)
    assert "`15s`" in step
    assert "5 min" in step
    assert "CA-26 da SPEC-015" in step
    assert "alguns minutos" in step


def test_extra_section_4_5_item_9_history_line(plan: str) -> None:
    assert re.search(r"2026-[^\n]*SPEC-043, Parte B, pelo autor \(security-devops\)", plan)


def test_extra_section_4_7_ca20_result_column(plan: str) -> None:
    section = plan[plan.index("## 9. Registro dos CAs manuais") :]
    line = next(li for li in section.splitlines() if li.startswith("| SPEC-039 CA-20 "))
    assert "Texto corrigido pela SPEC-043" in line
    assert "Desvio" not in line


def test_extra_plan_has_no_real_identifiers(plan: str) -> None:
    """R-13: section 9 and the new text use placeholders; no IP outside documentation ranges."""
    uuids = re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", plan)
    assert uuids == []


# --------------------------------------------------------------------------- CA-17


def test_ca17_comment_right_above_the_example_line() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert lines.count(EXAMPLE_LINE) == 1
    above = lines[lines.index(EXAMPLE_LINE) - 1]
    assert above.startswith("#")
    assert "só letras e números" in above


def test_extra_ca17_comment_is_the_exact_one_of_section_4_5() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    above = lines[lines.index(EXAMPLE_LINE) - 1]
    assert above == (
        "# A senha tem só letras e números: @, / e : quebram a URL, e a API e as ferramentas a "
        "recusam (SPEC-043)."
    )

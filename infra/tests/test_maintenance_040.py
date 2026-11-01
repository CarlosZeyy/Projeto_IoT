"""Author tests of SPEC-040, Part C (security-devops): comments and deployment plan.

* Section 4.9 (RV-02 of SPEC-039): the top comments of the two Dockerfiles and of
  ``.streamlit/config.toml`` follow ADR-023.
* Section 4.10 (SEC-16-01, SEC-04 of SPEC-018, SEC-39-05, SEC-17-03, SEC-30-01, SEC-17-02):
  ``docs/deployment-plan.md``.

Static checks only: they read the files as text, with no Docker, VPS or network.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "deployment-plan.md"
DOCKERFILES = [ROOT / "infra" / "docker" / f"{name}.Dockerfile" for name in ("api", "dashboard")]
STREAMLIT_CONFIG = ROOT / ".streamlit" / "config.toml"
BLOCK_TITLE = "**Quando o merge traz migração nova ou contrato novo**"
COOLIFY_URL = "https://coolify.io/docs/knowledge-base/proxy/traefik/custom-middlewares"
TRAEFIK_URL = (
    "https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/compress/"
)


def _top_comments(path: Path) -> str:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def _plan() -> str:
    return PLAN.read_text(encoding="utf-8")


def _update_section() -> list[str]:
    lines = _plan().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### Atualização"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("#"))
    return lines[start:end]


def _block() -> list[str]:
    lines = _update_section()
    start = lines.index(BLOCK_TITLE) + 1
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("Depois de **atualizar"))
    return lines[start:end]


def _risk(number: int) -> str:
    lines = _plan().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{number}. **"))
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].startswith(("#", f"{number + 1}. **"))
    )
    return "\n".join(lines[start:end])


def _manual_ca() -> str:
    text = _plan()
    return text[text.index("### CA manual da SPEC-040") :]


@pytest.mark.parametrize("path", [*DOCKERFILES, STREAMLIT_CONFIG], ids=lambda path: path.name)
def test_top_comments_follow_adr_023(path: Path) -> None:
    comments = _top_comments(path)
    for gone in ("env_file", ".env.dashboard", ".env.api"):
        assert gone not in comments, gone
    assert "Coolify" in comments and "ADR-023" in comments


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda path: path.name)
def test_dockerfile_comments_keep_the_rule_and_the_new_path(path: Path) -> None:
    comments = _top_comments(path)
    assert "(R-03)" in comments
    assert "environment do compose" in comments


def test_streamlit_comment_names_only_the_web_resource() -> None:
    comments = _top_comments(STREAMLIT_CONFIG)
    assert "Environment Variables do recurso `partqc-web` no Coolify (VPS, ADR-023)" in comments
    assert "partqc-api" not in comments


def test_streamlit_settings_do_not_change() -> None:
    assert tomllib.loads(STREAMLIT_CONFIG.read_text(encoding="utf-8")) == {
        "browser": {"gatherUsageStats": False},
        "server": {"headless": True},
        "client": {"showErrorDetails": "none"},
    }


def test_block_has_the_order_of_the_spec() -> None:
    text = "\n".join(_block())
    order = [
        "merge (o webhook",
        "infra/migrate.py --status",
        "0 pending",
        "passo 1, item 4",
        "contract_version",
        "só então atualizar a borda",
        "qc_edge.requeue",
        "--yes",
    ]
    positions = [text.index(fragment) for fragment in order]
    assert positions == sorted(positions), order


def test_block_explains_the_window_and_the_additive_rule() -> None:
    text = "\n".join(_block())
    for fragment in ("500 ou 422", "por último", "colunas anuláveis", "decisão na SPEC dela"):
        assert fragment in text, fragment


def test_block_commands_never_take_a_secret_in_argv() -> None:
    lines = [line for line in _block() if "infra/migrate.py" in line]
    assert lines
    for line in lines:
        for command in re.findall(r"`(uv run [^`]*migrate\.py[^`]*)`", line):
            assert command.startswith("uv run --env-file .env.migrate --package qc-api ")
    assert "postgresql://" not in "\n".join(_block())


def test_block_steps_do_not_collide_with_the_update_steps() -> None:
    """The steps use ``1)``: other tests read the single line ``3. `` of this section."""
    update = _update_section()
    assert [line[:2] for line in update if re.match(r"\d\. ", line)] == [
        "1.",
        "2.",
        "3.",
        "4.",
        "5.",
    ]
    assert [line[:2] for line in _block() if re.match(r"\d\) ", line)] == [
        "1)",
        "2)",
        "3)",
        "4)",
        "5)",
        "6)",
    ]


def test_block_has_no_other_title_inside() -> None:
    assert not [line for line in _block() if line.startswith(("#", "**"))]


def test_update_repeats_the_manual_ca_after_a_coolify_update() -> None:
    (line,) = [item for item in _update_section() if item.startswith("Depois de **atualizar")]
    assert "CA-18 da SPEC-040 (passos 1 a 3)" in line
    assert "CA-20 da SPEC-039" in line


def test_risk_12_has_the_sources_the_date_and_both_refusals() -> None:
    risk = _risk(12)
    for fragment in (
        COOLIFY_URL,
        TRAEFIK_URL,
        "`gzip`",
        "Accept-Encoding: identity",
        "unsupported response encoding",
        "unsupported content encoding",
        "`pending`",
        "CA-18",
    ):
        assert fragment in risk, fragment
    assert len(re.findall(r"conferido em \d{4}-\d{2}-\d{2}", risk)) == 2


@pytest.mark.parametrize(
    "fragment",
    ["SEC-39-05", "CDN", "só DNS", "chave de leitura", "chave de dispositivo", "termina o TLS"],
)
def test_risk_13_describes_the_cdn(fragment: str) -> None:
    assert fragment in _risk(13)


def test_dns_step_points_to_the_cdn_note_outside_the_repository() -> None:
    lines = _plan().splitlines()
    start = lines.index("### Passo 3. DNS")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("#"))
    (step,) = [line for line in lines[start:end] if "CDN" in line]
    assert "**fora do repositório**" in step
    assert "sem proxy (só DNS)" in step
    assert "§7, item 13" in step


def test_alerts_item_tells_when_to_restart() -> None:
    (line,) = [item for item in _plan().splitlines() if item.startswith("- **Envio preso")]
    assert "abandoned_for_s" in line
    assert "**Restart** só do `partqc-api`" in line


def test_manual_ca_keeps_the_key_out_of_argv_and_history() -> None:
    text = _manual_ca()
    assert "k=$(docker exec <contêiner do dashboard> printenv READ_API_KEY)" in text
    assert text.count('-K <(printf \'header = "X-API-Key: %s"\\n\' "$k")') == 2
    assert "unset k" in text
    assert '-H "X-API-Key' not in text and "-H 'X-API-Key" not in text


def test_manual_ca_has_the_steps_the_stop_rule_and_the_row() -> None:
    text = _manual_ca()
    for fragment in (
        "-H 'Accept-Encoding: gzip'",
        "-H 'Accept-Encoding: identity'",
        "/api/v1/inspections?limit=100",
        "3 inspeções",
        "`online`",
        "`SPEC_ISSUE`",
        "<subdominio>",
        "a chave nunca é colada",
        "| SPEC-040 CA-18 |",
    ):
        assert fragment in text, fragment
    assert "CA manual da SPEC-040" in _plan()


def test_manual_ca_commands_use_only_placeholders() -> None:
    text = _manual_ca()
    urls = re.findall(r"https://[^\s'`]+", text)
    assert urls
    assert all(url.startswith("https://<subdominio>/") for url in urls), urls
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text)

"""``qc_api.conninfo.is_safe_conninfo`` (SPEC-043 section 4.2). No connection is ever opened.

The passwords are built at run time, so the secret scanner sees no credential (R-03).
"""

from __future__ import annotations

import ast
import secrets
from pathlib import Path

import pytest

from qc_api import conninfo as conninfo_module
from qc_api.conninfo import MALFORMED_CONNINFO_HINT, is_safe_conninfo

# Split so that the repository secret scanner sees no credential in a URL (R-03).
SCHEME = "postgresql" + "://"
PASSWORD = "pw" + "a1b2c3"


@pytest.mark.parametrize(
    "url",
    [
        f"{SCHEME}u:{PASSWORD}@db.example.org:6543/postgres",
        f"{SCHEME}u.ref:{PASSWORD}@pooler.example.org:5432/postgres?sslmode=require",
        f"{SCHEME}u:a%40b%2Fc@db.example.org:5432/x",
        "postgresql://postgres@127.0.0.1:55432/partqc_test",
        "postgresql://localhost/x",
        "postgresql:///x",
        "postgresql://u@h1:5432,h2:5433/x_test",
        "postgresql://u@[::1]:5432/x",
        "host=db.example.org port=6543 user=u " + "password=" + "a@b" + " dbname=x",
        "host=/var/run/postgresql dbname=x",
        # Empty pieces of a list mean "the default of this host".
        "host=h1,h2 port=5432, dbname=x",
        "host=,h2 dbname=x",
        "hostaddr=10.0.0.1,10.0.0.2 dbname=x",
        "dbname=x",
        "",
    ],
)
def test_safe(url: str) -> None:
    assert is_safe_conninfo(url) is True


@pytest.mark.parametrize(
    "template",
    [
        # "@" in the password: the rest of it becomes part of the host.
        SCHEME + "u:{a}@{b}@db.example.org:6543/postgres",
        # "/" in the password: the user becomes the host and the password the port.
        SCHEME + "u:{a}/{b}@db.example.org:5432/postgres",
        # The same, with a numeric start of the password: only the dbname gives it away.
        SCHEME + "u:12/{b}@db.example.org:5432/postgres",
        # "@" and ":" in the password: the rest of it becomes the port.
        SCHEME + "u:{a}@{b}:x@db.example.org:5432/postgres",
        "not a conninfo password={a}",
        "host=h1,bad@host dbname=x",
        "hostaddr=10.0.0.1@x dbname=x",
        "port=5432,abc dbname=x",
        "port=+5432 dbname=x",
        "dbname=a/b",
        "dbname=a:b",
        "dbname=a@b",
    ],
)
def test_unsafe(template: str) -> None:
    url = template.format(a=secrets.token_hex(8), b=secrets.token_hex(8))
    assert is_safe_conninfo(url) is False


@pytest.mark.parametrize("value", [None, 5])
def test_never_raises(value: object) -> None:
    assert is_safe_conninfo(value) is False  # type: ignore[arg-type]


def test_hint_tells_what_to_do() -> None:
    assert "percent-encode" in MALFORMED_CONNINFO_HINT


def test_module_does_not_import_the_rest_of_qc_api() -> None:
    """``infra/migrate.py`` imports it, and ``qc_api.conninfo`` must stay free of the app (§7)."""
    tree = ast.parse(Path(conninfo_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not {name for name in imported if name.split(".")[0] == "qc_api"}

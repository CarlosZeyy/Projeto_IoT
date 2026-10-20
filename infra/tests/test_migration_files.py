"""Migration file discovery and validation, without a database (SPEC-003 §4.2)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from migrate import (
    DEFAULT_DIR,
    FILENAME_PATTERN,
    DatabaseConnectionError,
    MigrationError,
    _host_port,
    apply_migrations,
    load_migrations,
    pending_migrations,
)

INFRA = Path(__file__).resolve().parents[1]


def _write(directory: Path, name: str, content: str = "select 1;\n") -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_default_dir_is_infra_migrations() -> None:
    assert DEFAULT_DIR == INFRA / "migrations"
    assert (DEFAULT_DIR / "001_init.sql").is_file()


def test_repository_migrations_are_valid() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations][:2] == ["001", "002"]
    assert migrations[0].filename == "001_init.sql"
    assert migrations[1].filename == "002_contract_checks.sql"


def test_ordered_by_number(tmp_path: Path) -> None:
    for name in ("010_ten.sql", "002_two.sql", "001_one.sql", "100_hundred.sql"):
        _write(tmp_path, name)
    assert [m.version for m in load_migrations(tmp_path)] == ["001", "002", "010", "100"]


def test_checksum_is_sha256_of_file_bytes(tmp_path: Path) -> None:
    content = "-- comentário com acento\ncreate table x(id int);\n"
    path = _write(tmp_path, "001_x.sql", content)
    (migration,) = load_migrations(tmp_path)
    assert migration.checksum == hashlib.sha256(path.read_bytes()).hexdigest()
    assert migration.read_sql() == content


def test_non_sql_files_and_directories_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "001_one.sql")
    _write(tmp_path, "README.md", "# notes")
    _write(tmp_path, "notes.txt", "x")
    (tmp_path / "002_dir.sql").mkdir()
    assert [m.version for m in load_migrations(tmp_path)] == ["001"]


@pytest.mark.parametrize(
    "bad_name",
    [
        "abc.sql",
        "1_init.sql",
        "0001_init.sql",
        "001-init.sql",
        "001_Init.sql",
        "001_.sql",
        "001_init.sql.sql",
        "001 init.sql",
        "001_init.SQL",
    ],
)
def test_invalid_sql_filename_rejected(tmp_path: Path, bad_name: str) -> None:
    _write(tmp_path, "001_ok.sql")
    _write(tmp_path, bad_name)
    with pytest.raises(MigrationError, match="invalid migration filename"):
        load_migrations(tmp_path)


def test_duplicate_number_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql")
    _write(tmp_path, "001_b.sql")
    with pytest.raises(MigrationError, match="duplicate migration number 001"):
        load_migrations(tmp_path)


def test_missing_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="migrations directory not found"):
        load_migrations(tmp_path / "nope")


def test_non_utf8_file_rejected_on_read(tmp_path: Path) -> None:
    (tmp_path / "001_bin.sql").write_bytes(b"\xff\xfe select 1;")
    (migration,) = load_migrations(tmp_path)
    with pytest.raises(MigrationError, match="not valid UTF-8"):
        migration.read_sql()


def test_filename_pattern_is_the_spec_regex() -> None:
    assert FILENAME_PATTERN.pattern == r"^[0-9]{3}_[a-z0-9_]+\.sql$"


@pytest.mark.parametrize(
    ("conninfo", "expected"),
    [
        ("postgresql://u:s3cr3t-pw@127.0.0.1:1/x", "127.0.0.1:1"),
        ("host=db.example port=6543 user=u password=s3cr3t-pw dbname=x", "db.example:6543"),
        ("postgresql:///x", "default host:default port"),
        ("not a conninfo password=s3cr3t-pw", "unknown host"),
    ],
)
def test_host_port_never_contains_secret(conninfo: str, expected: str) -> None:
    result = _host_port(conninfo)
    assert result == expected
    assert "s3cr3t-pw" not in result


@pytest.mark.parametrize("migration", load_migrations(), ids=lambda m: m.filename)
def test_sql_file_has_no_transaction_control(migration) -> None:
    sql = migration.read_sql()
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).lower()
    # The BEGIN of a PL/pgSQL block (inside $$ ... $$) is not transaction control; COMMIT and
    # ROLLBACK are refused everywhere.
    top_level = re.sub(r"\$\$.*?\$\$", "$$ $$", code, flags=re.DOTALL)
    assert re.search(r"\b(begin|commit|rollback)\b", top_level) is None
    assert re.search(r"\b(commit|rollback)\b", code) is None
    assert "force row level security" not in code
    assert "create policy" not in code


def test_contract_checks_message_has_only_counts() -> None:
    sql = (DEFAULT_DIR / "002_contract_checks.sql").read_text(encoding="utf-8")
    assert "raise exception 'migration 002: % row(s) of inspections violate the new checks '" in sql
    assert (
        "'(model_version=%, inspection_id=%, inspected_at=%, received_at=%); '\n"
        "            'fix or delete them before migrating',\n"
        "            bad_total, bad_model_version, bad_inspection_id, bad_inspected_at, "
        "bad_received_at;"
    ) in sql


@pytest.mark.parametrize("func", [apply_migrations, pending_migrations])
def test_connection_error_hides_conninfo(func) -> None:
    url = "postgresql://u:s3cr3t-pw@127.0.0.1:1/partqc_test"
    with pytest.raises(DatabaseConnectionError) as info:
        func(url)
    assert "s3cr3t-pw" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True
    assert "127.0.0.1:1" in str(info.value)

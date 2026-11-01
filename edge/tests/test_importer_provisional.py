"""``python -m qc_edge.importer --provisional-set`` (SPEC-041 section 4.9, ADR-024).

Every image is generated here by Pillow (R-14); the dataset, the inbox and the registry live in
``tmp_path``, outside any Git repository, unless a test creates a ``.git`` there.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from qc_edge import importer
from qc_edge.app import create_app
from qc_edge.collect import LABELERS, MANIFEST_COLUMNS
from qc_edge.config import EdgeSettings
from qc_edge.importer import AGENT_SUGGESTION_LABELER, PLAN_COLUMNS, SOURCES_COLUMNS
from qc_edge.inference import StubInferencer
from qc_edge.sink import InMemorySink

GIT_MESSAGE = "provisional set must be outside any git repository"
NOT_A_SET_MESSAGE = "dataset is not a provisional set"
REGISTRY_HEADER = (
    "source_id",
    "title",
    "url",
    "license",
    "license_url",
    "attribution",
    "retrieved_at",
)
REGISTRY_ROW = (
    "fonte-teste",
    "Fonte de teste",
    "https://example.org/fonte",
    "CC-BY-4.0",
    "https://creativecommons.org/licenses/by/4.0/",
    "Fonte de teste (example.org)",
    "2026-10-20",
)
EXTERNAL = {
    "item_id": "XS-0001",
    "object_type": "screw",
    "grade": "good",
    "labeler": AGENT_SUGGESTION_LABELER,
    "angle": "0",
    "origin": "external",
    "contributor": "",
    "source_id": "fonte-teste",
    "source_ref": "dataset/train/0001.png",
    "notes": "",
}


def write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(buffer.getvalue().encode("utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def jpeg(seed: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (seed * 40 % 256, 120, 150)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


class Env:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.inbox = root / "inbox"
        self.inbox.mkdir()
        self.dataset = root / "dataset"
        self.plan = root / "plan.csv"
        self.registry = root / "external_sources.csv"
        write_csv(self.registry, REGISTRY_HEADER, [list(REGISTRY_ROW)])
        self.instant = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
        self.seed = 0

    def clock(self) -> datetime:
        self.instant += timedelta(seconds=1)
        return self.instant

    def row(self, **changes: str) -> dict[str, str]:
        self.seed += 1
        name = f"recorte-{self.seed}.jpg"
        (self.inbox / name).write_bytes(jpeg(self.seed))
        return {"file": name, **EXTERNAL, **changes}

    def write_plan(self, rows: list[dict[str, str]]) -> None:
        write_csv(self.plan, PLAN_COLUMNS, [[row.get(c, "") for c in PLAN_COLUMNS] for row in rows])

    def seed_manifest(self, labeler: str) -> None:
        self.dataset.mkdir(exist_ok=True)
        row = {
            "image_path": "raw/screw/good/XS-0900__0__20261101T000000Z.jpg",
            "item_id": "XS-0900",
            "object_type": "screw",
            "grade": "good",
            "labeler": labeler,
            "angle": "0",
            "captured_at": "2026-11-01T00:00:00Z",
            "capture_device": "qc-edge-import",
            "notes": "",
        }
        write_csv(
            self.dataset / "manifest.csv", MANIFEST_COLUMNS, [[row[c] for c in MANIFEST_COLUMNS]]
        )

    def run(self, *extra: str, provisional: bool = True, **paths: Path) -> int:
        argv = [
            "--dataset-dir",
            str(paths.get("dataset", self.dataset)),
            "--inbox",
            str(paths.get("inbox", self.inbox)),
            "--plan",
            str(paths.get("plan", self.plan)),
            "--external-sources",
            str(self.registry),
            "--privacy-checked",
            *extra,
        ]
        if provisional:
            argv.append("--provisional-set")
        return importer.main(argv, clock=self.clock, sleep=lambda _: None)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_constant_is_not_a_collect_labeler() -> None:
    assert AGENT_SUGGESTION_LABELER == "agent-suggestion"
    assert AGENT_SUGGESTION_LABELER not in LABELERS


def test_collect_mode_refuses_the_labeler(settings: EdgeSettings, make_image: Any) -> None:
    app = create_app(settings, StubInferencer(), InMemorySink())

    response = TestClient(app).post(
        "/api/capture",
        headers={"X-Session-Token": app.state.session_token},
        data={
            "mode": "collect",
            "item_id": "S-001",
            "object_type": "screw",
            "grade": "good",
            "labeler": AGENT_SUGGESTION_LABELER,
            "angle": "0",
        },
        files={"image": ("a.jpg", make_image((640, 480)), "image/jpeg")},
    )

    assert response.status_code == 422
    assert not settings.DATASET_DIR.exists() or not list(settings.DATASET_DIR.rglob("*.jpg"))


# ------------------------------------------------------------------------------ without the option


def test_without_the_option_the_labeler_is_invalid(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.write_plan([env.row()])

    assert env.run(provisional=False) == 2

    assert "plan line 2: invalid_labeler (labeler)" in capsys.readouterr().err
    assert not env.dataset.exists()


def test_without_the_option_a_and_b_still_work(env: Env) -> None:
    env.write_plan([env.row(labeler="a"), env.row(labeler="b", item_id="XS-0002")])

    assert env.run(provisional=False) == 0

    assert [row["labeler"] for row in read_rows(env.dataset / "manifest.csv")] == ["a", "b"]


def test_without_the_option_a_dataset_inside_git_stays_accepted(tmp_path: Path) -> None:
    """SPEC-036 and SPEC-038 do not check ``--dataset-dir``: ``ml/data`` lives in the checkout."""
    env = Env(tmp_path / "fora")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    env.write_plan([env.row(labeler="a")])

    assert env.run(provisional=False, dataset=repo / "ml" / "data") == 0


def test_without_the_option_a_manifest_with_another_labeler_is_accepted(env: Env) -> None:
    env.seed_manifest("a")
    env.write_plan([env.row(labeler="b")])

    assert env.run(provisional=False) == 0


# ---------------------------------------------------------------------------- the Git repository


@pytest.mark.parametrize("subdir", [".", "ml/data"])
@pytest.mark.parametrize("entry", ["directory", "file"])
def test_dataset_inside_git_with_inbox_and_plan_outside(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], subdir: str, entry: str
) -> None:
    env = Env(tmp_path / "fora")
    repo = tmp_path / "repo"
    repo.mkdir()
    if entry == "directory":
        (repo / ".git").mkdir()
    else:  # a worktree
        (repo / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    env.write_plan([env.row()])
    before = snapshot(repo)

    assert env.run(dataset=repo / subdir) == 2

    assert capsys.readouterr().err.strip() == GIT_MESSAGE
    assert snapshot(repo) == before


def test_the_dataset_check_comes_before_the_inbox_and_plan_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Everything in the same repository: the message is the one of the dataset (SPEC_ISSUE-04)."""
    env = Env(tmp_path / "repo")
    (tmp_path / "repo" / ".git").mkdir()
    env.write_plan([env.row()])

    assert env.run(dataset=tmp_path / "repo" / "ml" / "data") == 2

    err = capsys.readouterr().err
    assert GIT_MESSAGE in err
    assert "inbox must be outside any git repository" not in err
    assert "plan must be outside any git repository" not in err
    assert not (tmp_path / "repo" / "ml").exists()


def test_the_dataset_check_comes_before_a_missing_inbox(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path / "fora")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    code = env.run(dataset=repo / "data", inbox=tmp_path / "missing", plan=tmp_path / "missing.csv")

    assert code == 2
    assert capsys.readouterr().err.strip() == GIT_MESSAGE


def test_symlink_into_a_repository_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path / "fora")
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "data").mkdir()
    link = tmp_path / "fora" / "link"
    link.symlink_to(tmp_path / "repo" / "data", target_is_directory=True)
    env.write_plan([env.row()])

    assert env.run(dataset=link) == 2

    assert capsys.readouterr().err.strip() == GIT_MESSAGE
    assert list((tmp_path / "repo" / "data").iterdir()) == []


def test_the_privacy_option_is_still_checked_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path / "fora")
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    code = importer.main(
        [
            "--dataset-dir",
            str(tmp_path / "repo" / "data"),
            "--inbox",
            str(env.inbox),
            "--plan",
            str(env.plan),
            "--provisional-set",
        ]
    )

    assert code == 2
    assert capsys.readouterr().err.strip() == importer.MISSING_PRIVACY_MESSAGE


# ------------------------------------------------------------------------------------- with the set


def test_a_valid_plan_is_imported_and_a_second_run_adds_to_it(env: Env) -> None:
    env.write_plan([env.row(), env.row(item_id="XN-0001", object_type="nut", grade="poor")])
    assert env.run() == 0

    other = {"item_id": "XO-0001", "object_type": "other", "grade": ""}
    env.write_plan([env.row(**other)])
    assert env.run() == 0

    manifest = read_rows(env.dataset / "manifest.csv")
    sources = read_rows(env.dataset / "sources.csv")
    assert [row["item_id"] for row in manifest] == ["XS-0001", "XN-0001", "XO-0001"]
    assert {row["labeler"] for row in manifest} == {AGENT_SUGGESTION_LABELER}
    assert {row["origin"] for row in sources} == {"external"}
    assert len(sources) == 3
    assert list(sources[0]) == list(SOURCES_COLUMNS)


def test_a_repeated_plan_is_skipped(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.write_plan([env.row()])
    assert env.run() == 0
    before = snapshot(env.dataset)

    assert env.run() == 0

    assert "skipped recorte-1.jpg: already imported" in capsys.readouterr().out
    assert snapshot(env.dataset) == before


def test_dry_run_writes_nothing(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.write_plan([env.row()])

    assert env.run("--dry-run") == 0

    assert "would import recorte-1.jpg" in capsys.readouterr().out
    assert not env.dataset.exists()


def test_a_manifest_with_only_the_header_is_a_provisional_set(env: Env) -> None:
    env.dataset.mkdir()
    write_csv(env.dataset / "manifest.csv", MANIFEST_COLUMNS, [])
    env.write_plan([env.row()])

    assert env.run() == 0


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"labeler": "a"}, "plan line 2: invalid_labeler (labeler)"),
        ({"labeler": "b"}, "plan line 2: invalid_labeler (labeler)"),
        ({"labeler": ""}, "plan line 2: invalid_labeler (labeler)"),
        (
            {
                "origin": "contributor",
                "item_id": "S-501",
                "contributor": "c01",
                "source_id": "",
                "source_ref": "",
            },
            "plan line 2: invalid_origin (origin)",
        ),
        ({"origin": "other"}, "plan line 2: invalid_origin (origin)"),
    ],
)
def test_rows_of_another_kind_are_refused(
    env: Env, capsys: pytest.CaptureFixture[str], changes: dict[str, str], expected: str
) -> None:
    env.seed_manifest(AGENT_SUGGESTION_LABELER)
    before = snapshot(env.dataset)
    env.write_plan([env.row(**changes)])

    assert env.run() == 2

    assert expected in capsys.readouterr().err
    assert snapshot(env.dataset) == before


@pytest.mark.parametrize("labeler", ["a", "b", ""])
def test_a_manifest_with_another_labeler_is_refused(
    env: Env, capsys: pytest.CaptureFixture[str], labeler: str
) -> None:
    env.seed_manifest(labeler)
    before = snapshot(env.dataset)
    env.write_plan([env.row()])

    assert env.run() == 2

    assert capsys.readouterr().err.strip() == NOT_A_SET_MESSAGE
    assert snapshot(env.dataset) == before


def test_one_row_of_another_labeler_among_others_is_enough(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.write_plan([env.row()])
    assert env.run() == 0
    manifest = env.dataset / "manifest.csv"
    first = read_rows(manifest)[0]
    with manifest.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerow(
            [{**first, "item_id": "XS-0002", "labeler": "a"}[c] for c in MANIFEST_COLUMNS]
        )
    before = snapshot(env.dataset)
    env.write_plan([env.row(item_id="XS-0003")])

    assert env.run() == 2

    assert capsys.readouterr().err.strip() == NOT_A_SET_MESSAGE
    assert snapshot(env.dataset) == before


def test_a_row_too_short_to_have_a_labeler_is_another_labeler(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.dataset.mkdir()
    write_csv(env.dataset / "manifest.csv", MANIFEST_COLUMNS, [["raw/a.jpg", "XS-0900", "screw"]])
    env.write_plan([env.row()])

    assert env.run() == 2

    assert capsys.readouterr().err.strip() == NOT_A_SET_MESSAGE


def test_a_blank_line_of_the_manifest_is_not_a_row(env: Env) -> None:
    env.seed_manifest(AGENT_SUGGESTION_LABELER)
    with (env.dataset / "manifest.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    env.write_plan([env.row()])

    assert env.run() == 0


def test_another_manifest_header_keeps_its_own_message(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.dataset.mkdir()
    (env.dataset / "manifest.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    env.write_plan([env.row()])

    assert env.run() == 2

    assert capsys.readouterr().err.strip() == importer.MANIFEST_MISMATCH_MESSAGE


def test_an_unreadable_manifest_is_a_usage_error(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env.seed_manifest(AGENT_SUGGESTION_LABELER)
    env.write_plan([env.row()])
    original = importer.read_csv_rows

    def fail_on_the_labeler_read(path: Path, columns: tuple[str, ...]) -> Any:
        # ``read_manifest_entries`` uses the name of ``qc_edge.collect``, so only the read of the
        # labelers comes through here.
        if columns == MANIFEST_COLUMNS:
            raise PermissionError(13, "denied")
        return original(path, columns)

    monkeypatch.setattr(importer, "read_csv_rows", fail_on_the_labeler_read)

    assert env.run() == 2

    assert importer.DATASET_UNREADABLE_MESSAGE in capsys.readouterr().err

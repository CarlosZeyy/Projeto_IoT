"""The Colab notebook is thin, saved without outputs and without credentials (CA-26, R-03)."""

from __future__ import annotations

import json
import re
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "train_colab.ipynb"
SECRET = re.compile(r"ghp_|github_pat_|token\s*=\s*[\"']", re.IGNORECASE)


def test_notebook_is_clean() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    sources = ["".join(c["source"]) for c in code]
    assert code and all(c["outputs"] == [] and c["execution_count"] is None for c in code)
    assert not any("def " in s or "class " in s for s in sources)
    assert any("python -m qc_ml.pipeline" in s for s in sources)
    assert any("python -m qc_ml.data validate" in s for s in sources)
    assert any("sys.version_info[:2] == (3, 12)" in s for s in sources)
    assert any("google.colab import userdata" in s for s in sources)
    every_cell = ["".join(c["source"]) for c in notebook["cells"]]
    assert not any(SECRET.search(s) for s in every_cell)


def _source(cell: dict) -> str:
    return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]


def test_notebook_checks_the_export_and_the_split_before_training() -> None:
    """SPEC-031 §4.3 item 3 and §4.5: export check and split_v1 condition before the pipeline."""
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    pipeline = next(
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and _source(c).lstrip().startswith("!python -m qc_ml.pipeline")
    )
    check = next(
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and "make_tiny_fixture.py --out" in _source(c)
    )
    assert check < pipeline
    assert "!python ml/scripts/make_tiny_fixture.py --out /tmp/export_check" in _source(
        cells[check]
    )
    assert "_exit_code == 0" in _source(cells[check])
    assert cells[check - 1]["cell_type"] == "markdown"
    assert "antes do treino" in _source(cells[check - 1])
    assert any(
        c["cell_type"] == "markdown"
        and "split_v1" in _source(c)
        and "python -m qc_ml.split" in _source(c)
        for c in cells[:pipeline]
    )

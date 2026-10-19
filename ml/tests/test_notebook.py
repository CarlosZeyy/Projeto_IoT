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

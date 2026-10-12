import ast
from pathlib import Path

import qc_contracts

ALLOWED_ROOTS = {
    "__future__",
    "annotated_types",
    "collections",
    "datetime",
    "enum",
    "math",
    "pydantic",
    "qc_contracts",
    "re",
    "types",
    "typing",
    "uuid",
}
SRC = Path(qc_contracts.__file__).parent


def _imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "use absolute imports (qc_contracts.*)"
            found.add(node.module or "")
    return found


def test_only_allowed_imports() -> None:
    files = sorted(SRC.glob("*.py"))
    assert files
    for path in files:
        modules = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        for module in modules:
            if module.startswith("collections"):
                assert module == "collections.abc", (path.name, module)
            assert module.split(".")[0] in ALLOWED_ROOTS, (path.name, module)

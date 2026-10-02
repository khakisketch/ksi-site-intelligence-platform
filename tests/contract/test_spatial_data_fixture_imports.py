"""A test fixture must have one module identity under broad CI and isolated replay runs."""

import ast
from pathlib import Path


def test_spatial_data_fixture_imports_use_existing_flat_test_convention() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module.rsplit(".", 1)[-1]
                if (root / "contract" / (module + ".py")).is_file() and module.startswith(
                    ("spatial_data_", "test_spatial_data_")
                ):
                    assert node.module == module, (path.relative_to(root), node.lineno, node.module)

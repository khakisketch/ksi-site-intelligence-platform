"""Focused tests for exact DJI PSDK header version pinning."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _ROOT / "tools/edge/fetch_psdk.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_psdk", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observed_header_version_is_exact(tmp_path: Path) -> None:
    header = tmp_path / "dji_version.h"
    header.write_text(
        "#define DJI_VERSION_MAJOR 3\n"
        "#define DJI_VERSION_MINOR 16\n"
        "#define DJI_VERSION_MODIFY 0\n",
        encoding="utf-8",
    )
    assert _tool()._observed_header_version(header) == "3.16.0"


@pytest.mark.parametrize(
    "body",
    [
        "#define DJI_VERSION_MAJOR 3\n#define DJI_VERSION_MINOR 16\n",
        (
            "#define DJI_VERSION_MAJOR 3\n#define DJI_VERSION_MAJOR 4\n"
            "#define DJI_VERSION_MINOR 16\n#define DJI_VERSION_MODIFY 0\n"
        ),
        (
            "#define DJI_VERSION_MAJOR x\n#define DJI_VERSION_MINOR 16\n"
            "#define DJI_VERSION_MODIFY 0\n"
        ),
    ],
)
def test_observed_header_version_rejects_missing_duplicate_or_non_numeric_macros(
    tmp_path: Path,
    body: str,
) -> None:
    header = tmp_path / "dji_version.h"
    header.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="DJI_VERSION_"):
        _tool()._observed_header_version(header)

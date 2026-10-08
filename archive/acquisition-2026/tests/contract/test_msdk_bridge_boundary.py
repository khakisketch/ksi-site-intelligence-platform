from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "edge" / "check_msdk_bridge_boundary.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_msdk_bridge_boundary", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_msdk_bridge_has_no_control_or_camera_write_surface() -> None:
    tool = _tool()
    assert tool.scan(_ROOT / "edge" / "msdk-field-bridge") == ()


@pytest.mark.parametrize(
    "token",
    [
        "VirtualStickManager",
        "startTakeOff",
        "startLanding",
        "startGoHome",
        "WaypointMissionExecute",
        "GimbalRotateCommand",
        "startShootPhoto",
        "deleteMediaFile",
        "formatStorageNow",
    ],
)
def test_forbidden_msdk_surfaces_fail_closed(tmp_path: Path, token: str) -> None:
    tool = _tool()
    source = tmp_path / "Unsafe.kt"
    source.write_text(f"class Unsafe {{ fun run() = {token}() }}\n", encoding="utf-8")
    violations = tool.scan(tmp_path)
    assert len(violations) == 1
    assert token in violations[0]


def test_missing_msdk_source_root_is_not_a_pass(tmp_path: Path) -> None:
    tool = _tool()
    violations = tool.scan(tmp_path / "missing")
    assert violations and "없다" in violations[0]

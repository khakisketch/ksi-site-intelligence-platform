"""Fail-closed assembly contract for unverified PSDK media offload.

The PSDK-independent conveyor is useful software, but it is not a production
camera source.  Until a real DJI adapter and a verified device-side
trigger/baseline provider exist, ``ksi_psdk_app`` must not turn a test fake into
an apparent zero-touch ingress path (INV-018/040/041/060, REQ-ACQ-103).
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CMAKE = (_ROOT / "edge/psdk-app/CMakeLists.txt").read_text(encoding="utf-8")
_MAIN = (_ROOT / "edge/psdk-app/src/main.cpp").read_text(encoding="utf-8")
_PORT = (_ROOT / "edge/manifold-runtime/include/ksi/edge/media_offload.hpp").read_text(
    encoding="utf-8"
)


def _cmake_if_block(condition: str) -> str:
    start = _CMAKE.index(f"if({condition})")
    return _CMAKE[start : _CMAKE.index("endif()", start)]


def test_media_offload_request_defaults_off_and_fails_configuration() -> None:
    option = re.search(
        r"option\(KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD\b.*?\bOFF\)",
        _CMAKE,
        flags=re.DOTALL,
    )
    assert option is not None

    gate = _cmake_if_block("KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD")
    assert "message(FATAL_ERROR" in gate
    assert "no real" in gate
    assert "device-side trigger/baseline provider" in gate
    assert "SD/PC/Web intake" in gate
    assert "KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED=1" not in _CMAKE


def test_packaged_app_contains_no_fake_or_automatic_media_worker() -> None:
    assert "FakeMediaSourcePort" not in _MAIN
    assert "ConfigureMediaOffload" not in _MAIN
    assert "DrainMediaOffload" not in _MAIN
    assert "media_offload_thread_" not in _MAIN
    assert "source-media stays " in _MAIN
    assert "on the aircraft SD card" in _MAIN


def test_test_double_remains_confined_to_psdk_independent_port() -> None:
    """Removing the false production path must not discard conveyor tests."""

    assert "class IMediaSourcePort" in _PORT
    assert "class FakeMediaSourcePort" in _PORT
    assert "MissionMediaSelectionContext" in _PORT
    assert "source_file_index" in _PORT
    assert "실기 미확인" in _PORT

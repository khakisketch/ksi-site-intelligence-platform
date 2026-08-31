"""Fail-closed assembly contract for the opt-in PSDK source-media tier.

The package now has a bounded DJI Camera Manager adapter and a local
operator-mediated control protocol.  That does not make it a verified device
capability: an ordinary DPK must stay OFF, and an enabled build must require
the complete deployment boundary rather than silently enabling a fake or a
global SD-card sweep (INV-018/040/041/051/060, REQ-ACQ-103).
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
_CONTROL = (_ROOT / "edge/manifold-runtime/include/ksi/edge/media_control.hpp").read_text(
    encoding="utf-8"
)


def _cmake_if_block(condition: str) -> str:
    start = _CMAKE.index(f"if({condition})")
    # The media gate deliberately contains nested configuration checks.  Its
    # following top-level capability branch is a stable sentinel; finding the
    # first ``endif()`` would inspect only the Manifold target check.
    return _CMAKE[start : _CMAKE.index("if(KSI_PSDK_APP_HAVE_LIBUSB)", start)]


def test_media_offload_defaults_off_and_requires_complete_production_provisioning() -> None:
    option = re.search(
        r"option\(KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD\b.*?\bOFF\)",
        _CMAKE,
        flags=re.DOTALL,
    )
    assert option is not None

    gate = _cmake_if_block("KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD")
    assert "message(FATAL_ERROR" in gate
    for required_gate in (
        "KSI_TARGET_MANIFOLD3=ON",
        "KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION",
        "KSI_PSDK_APP_ENABLE_CORE_SYNC",
        "KSI_PSDK_APP_MEDIA_CONTROL_STATE_DIR",
        "KSI_PSDK_APP_MEDIA_CAMERA_MOUNT_POSITION",
        "KSI_PSDK_APP_MEDIA_MAXIMUM_DOWNLOAD_BYTES",
        "MEDIA_CONTROL_STATE_DIR must differ",
        "536870912",
        "KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED=1",
    ):
        assert required_gate in gate
    assert "target_sources(ksi_psdk_app PRIVATE src/media/dji_camera_media_source.cpp)" in gate
    assert "KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED=0" in _CMAKE


def test_packaged_app_contains_only_operator_triggered_non_executable_media_path() -> None:
    assert "FakeMediaSourcePort" not in _MAIN
    assert "media_offload_thread_" not in _MAIN
    assert "DjiCameraManager_Init" in _MAIN
    assert "DjiCameraManager_DeInit" in _MAIN
    assert "DjiCameraManagerMediaSourcePort" in _MAIN
    assert "ConfigureMediaOffload" in _MAIN
    assert "CapturePreActivationMediaBaseline" in _MAIN
    assert "BuildOperatorMediaSelectionContext" in _MAIN
    assert "MediaSourceRightsGuard" in _MAIN
    assert "BASELINE_REQUIRED_BEFORE_ACTIVATION" in _MAIN
    assert "TRIGGER_" in _MAIN
    for forbidden in (
        "DjiCameraManager_StartShootPhoto",
        "DjiCameraManager_DeleteFile",
        "DjiCameraManager_FormatStorage",
        "DjiGimbalManager_Rotate",
        "DjiFlightController_Start",
    ):
        assert forbidden not in _MAIN
    assert "source-media stays " in _MAIN
    assert "on the aircraft SD card" in _MAIN


def test_test_double_remains_confined_to_psdk_independent_port() -> None:
    """The host double remains useful without being wired into the DPK."""

    assert "class IMediaSourcePort" in _PORT
    assert "class FakeMediaSourcePort" in _PORT
    assert "MissionMediaSelectionContext" in _PORT
    assert "source_file_index" in _PORT
    assert "실기 미확인" in _PORT


def test_control_protocol_requires_preactivation_baseline_and_one_shot_trigger() -> None:
    for required_boundary in (
        "kMediaBaselineRequestFilename",
        "kMediaBaselineFilename",
        "kMediaOperatorTriggerFilename",
        "kMaximumMediaControlTtlMs",
        "MediaBaselineRequest",
        "MediaBaselineRecord",
        "OperatorMediaOffloadTrigger",
        "BuildOperatorMediaSelectionContext",
        "MissionMediaSelectionContext",
    ):
        assert required_boundary in _CONTROL
    assert "executable flight-control channel" in _CONTROL

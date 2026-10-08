from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "edge/psdk-app/src/runtime/psdk_route_companion.cpp"
HEADER = ROOT / "edge/psdk-app/src/runtime/psdk_route_companion.hpp"
MAIN = ROOT / "edge/psdk-app/src/main.cpp"
PEER_SOURCE = ROOT / "edge/psdk-app/src/runtime/psdk_mop_peer_receiver.cpp"
PEER_HEADER = ROOT / "edge/psdk-app/src/runtime/psdk_mop_peer_receiver.hpp"
CMAKE = ROOT / "edge/psdk-app/CMakeLists.txt"


def test_hil1s_companion_uses_only_mop_dji_surface() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    includes = set(re.findall(r"#include <(dji_[^>]+)>", source))
    assert includes == {"dji_error.h", "dji_mop_channel.h"}

    calls = set(re.findall(r"\b(Dji[A-Za-z0-9_]+)\s*\(", source))
    assert calls == {
        "DjiAccept",
        "DjiBind",
        "DjiClose",
        "DjiCreateReliable",
        "DjiDestroy",
        "DjiInitialize",
        "DjiMopApi",
        "DjiMopChannel_Accept",
        "DjiMopChannel_Bind",
        "DjiMopChannel_Close",
        "DjiMopChannel_Create",
        "DjiMopChannel_Destroy",
        "DjiMopChannel_Init",
        "DjiMopChannel_RecvData",
        "DjiMopChannel_SendData",
        "DjiReceive",
        "DjiSend",
    }


def test_hil1s_operations_are_status_and_non_actuating_uplink_only() -> None:
    combined = SOURCE.read_text(encoding="utf-8") + HEADER.read_text(encoding="utf-8")
    assert '"ROUTE_STATUS_V1"' in combined
    assert '"EDGE_BUNDLE_UPLOAD"' in combined

    forbidden_operations = {
        "WAYLINE_DELIVERY",
        "WAYLINE_UPLOAD_NO_START",
        "SIGNED_CONTRACT_TRANSFER",
        "MEDIA_PULL",
        "MEDIA_READ_ONE",
        "MEDIA_UPLOAD_SYNTHETIC",
        "MISSION_START",
        "MOTOR_START",
    }
    assert forbidden_operations.isdisjoint(re.findall(r'"([A-Z][A-Z0-9_]+)"', combined))
    assert not re.search(
        r"\bDji(?:FlightController|Waypoint|InterestPoint|Fts|Gimbal|Camera|Payload)_[A-Za-z0-9_]+",
        combined,
    )


def test_hil1s_psdk_state_and_shutdown_are_owned_by_real_app_lifecycle() -> None:
    main = MAIN.read_text(encoding="utf-8")
    application_started = main.index("result = DjiCore_ApplicationStart();")
    companion_started = main.index("route_companion->Start(true, &companion_error)")
    companion_stopped = main.index("route_companion->Stop();")
    core_deinitialized = main.index("(void)DjiCore_DeInit();")

    assert application_started < companion_started
    assert companion_stopped < core_deinitialized


def test_hil1p_peer_receiver_is_connect_only_and_non_actuating() -> None:
    source = PEER_SOURCE.read_text(encoding="utf-8")
    combined = source + PEER_HEADER.read_text(encoding="utf-8")
    includes = set(re.findall(r"#include <(dji_[^>]+)>", source))
    assert includes == {"dji_error.h", "dji_mop_channel.h"}
    calls = set(re.findall(r"\b(Dji[A-Za-z0-9_]+)\s*\(", source))
    assert calls == {
        "DjiClose",
        "DjiConnect",
        "DjiCreateReliable",
        "DjiDestroy",
        "DjiInitialize",
        "DjiMopChannel_Close",
        "DjiMopChannel_Connect",
        "DjiMopChannel_Create",
        "DjiMopChannel_Destroy",
        "DjiMopChannel_Init",
        "DjiMopChannel_RecvData",
        "DjiMopPeerApi",
        "DjiReceive",
    }
    assert "DjiMopChannel_Accept" not in combined
    assert "DjiMopChannel_Bind" not in combined
    assert "DjiMopChannel_SendData" not in combined
    assert "kMasterRcApp" not in combined
    assert "kSlaveRcApp" not in combined
    assert "kCloudApi" not in combined
    assert "kPayloadPortNo1" in combined
    assert "kExtensionPort" in combined
    assert '"EDGE_BUNDLE_UPLOAD"' in combined
    assert not re.search(
        r"\bDji(?:FlightController|Waypoint|InterestPoint|Fts|Gimbal|Camera|Payload)_[A-Za-z0-9_]+",
        combined,
    )


def test_hil1p_peer_and_hil1s_accept_server_are_build_time_exclusive() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    assert "KSI_PSDK_APP_ENABLE_MOP_PEER_RECEIVER" in cmake
    assert "KSI_PSDK_APP_ENABLE_EDGE_UPLINK_COMPANION" in cmake
    assert "are mutually exclusive" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_ORGANIZATION_ID" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_SITE_ID" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_EDGE_DEVICE_ID" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_SUBJECT_PORT_ID" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_CHANNEL_ID" in cmake
    assert "KSI_PSDK_APP_MOP_PEER_ADDRESS" in cmake
    assert "PAYLOAD_PORT_NO1" in cmake
    assert "not RC or Cloud API" in cmake


def test_hil1p_peer_worker_starts_after_core_and_stops_before_core_deinit() -> None:
    main = MAIN.read_text(encoding="utf-8")
    application_started = main.index("result = DjiCore_ApplicationStart();")
    peer_started = main.index("mop_peer_receiver->Start(true, &peer_error)")
    peer_stopped = main.index("mop_peer_receiver->Stop();")
    core_deinitialized = main.index("(void)DjiCore_DeInit();")

    assert application_started < peer_started
    assert peer_stopped < core_deinitialized

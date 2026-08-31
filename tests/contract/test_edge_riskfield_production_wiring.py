"""Production assembly guard for the native RiskField evidence chain.

The native library tests exercise each runtime component dynamically.  This file
guards the separate product question that originally escaped those tests: the
packaged ``ksi_psdk_app`` executable must construct and continuously drive those
components together.  This is a source/build-contract check, not HIL evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CMAKE = (_ROOT / "edge/psdk-app/CMakeLists.txt").read_text(encoding="utf-8")
_MAIN = (_ROOT / "edge/psdk-app/src/main.cpp").read_text(encoding="utf-8")


def _section(start: str, end: str, *, source: str = _MAIN) -> str:
    start_offset = source.index(start)
    return source[start_offset : source.index(end, start_offset)]


def _option_defaults_off(name: str) -> bool:
    pattern = rf"option\({re.escape(name)}\b.*?\bOFF\)"
    return re.search(pattern, _CMAKE, flags=re.DOTALL) is not None


def test_ksi_psdk_app_is_the_packaged_native_runtime_host() -> None:
    """The product executable, not only the test tree, owns the native runtime."""

    assert "Manifold 3 production PSDK entry point" in _CMAKE
    assert "add_executable(ksi_psdk_app src/main.cpp)" in _CMAKE
    assert 'add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../manifold-runtime"' in _CMAKE
    assert re.search(
        r"target_link_libraries\(ksi_psdk_app\s+PRIVATE\s+"
        r"ksi_edge_runtime\s+ksi_psdk_static",
        _CMAKE,
    )


def test_product_host_assembles_one_durable_riskfield_delivery_chain() -> None:
    """Perception and Core sync share the same vault/journal and real adapters."""

    perception = _section("void ConfigurePerceptionPipeline", "void ClearNativeActivation")
    core_sync = _section("void ConfigureCoreSync", "void StartWorker()")

    for constructor in (
        "ConservativeRiskEngine",
        "ProfiledGroundPlaneProjector",
        "NativeCandidateEvidenceBuilder",
        "EdgePipeline",
    ):
        assert f"std::make_unique<ksi::edge::{constructor}>" in perception

    for constructor in (
        "CurlHttpsRequestExecutor",
        "CoreRestSyncTransport",
        "StoreForwardSyncDriver",
    ):
        assert f"std::make_unique<ksi::edge::{constructor}>" in core_sync

    assert "share_perception_journal" in core_sync
    assert "vault = perception_vault_.get();" in core_sync
    assert "store = perception_store_.get();" in core_sync
    assert "PERCEPTION_JOURNAL_UNAVAILABLE" in core_sync

    run_setup = _section(
        "#if KSI_PSDK_APP_PERCEPTION_CONFIGURED",
        "runtime.OpenIngress();",
    )
    assert run_setup.index("runtime.ConfigurePerception(") < run_setup.index(
        "runtime.ConfigureCoreSync("
    )


def test_product_workers_drive_and_shutdown_the_pipeline_and_sync_transport() -> None:
    worker = _section("void DrainWorker() noexcept", "void DrainCoreSync() noexcept")
    sync = _section("void DrainCoreSync() noexcept", "ksi::edge::BoundedFrameQueue frames_")
    start = _section("void StartWorker()", "void StopWorker()")
    stop = _section("void StopWorker()", "void OpenIngress()")

    assert "perception_pipeline_->ProcessOne(" in worker
    assert "perception_evidence_builder_.get()" in worker
    assert "core_sync_driver_->SynchronizeOnce(core_sync_transport_.get())" in sync

    assert "core_sync_configured_.load(std::memory_order_acquire)" in start
    assert "core_sync_driver_ != nullptr" in start
    assert "core_sync_transport_ != nullptr" in start
    assert "std::thread([this] { DrainWorker(); })" in start
    assert "std::thread([this] { DrainCoreSync(); })" in start

    assert "core_sync_worker_running_.store(false" in stop
    assert "worker_.join();" in stop
    assert "core_sync_worker_.join();" in stop


def test_deployment_configuration_fails_closed_without_shared_state_and_attestation() -> None:
    """No default build or partial deployment silently becomes an evidence producer."""

    for option in (
        "KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION",
        "KSI_PSDK_APP_ENABLE_PERCEPTION",
        "KSI_PSDK_APP_ENABLE_CORE_SYNC",
    ):
        assert _option_defaults_off(option), f"{option} must remain explicit opt-in"

    assert "KSI_ENABLE_CURL_EDGE_TRANSPORT ON" in _CMAKE
    assert "KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION ON" in _CMAKE
    assert (
        '"${KSI_PSDK_APP_SYNC_STATE_DIR}" STREQUAL "${KSI_PSDK_APP_PERCEPTION_STATE_DIR}"' in _CMAKE
    )
    assert (
        "SYNC_STATE_DIR must equal PERCEPTION_STATE_DIR when perception is enabled "
        "so the pipeline and sync worker share one durable journal"
    ) in _CMAKE
    assert "KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID" in _CMAKE
    assert "KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE" in _CMAKE
    assert "EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE must be an absolute external path" in _CMAKE
    assert "CORE_BEARER_TOKEN_FILE" in _CMAKE
    assert "CORE_TLS_PIN" in _CMAKE
    assert "STORAGE_TLS_PIN" in _CMAKE

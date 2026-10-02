"""Contract tests for the explicit local-only Analysis runtime configuration."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest
from ksi_core.composition import local_analysis_runtime_config
from ksi_core.composition.local_analysis_runtime_config import (
    LocalAnalysisRuntimeConfigBlockedCode,
    LocalAnalysisRuntimeConfigUnavailable,
    load_local_analysis_runtime_config,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sealed_policy(*, policy_id: str = "local-analysis-policy") -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id=policy_id,
        version=1,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("profile"),
        algorithm_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def sealed_envelope(*, max_queue_depth: int = 4) -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=10_000_000,
        max_bands=4,
        max_blocks=1_024,
        max_decompressed_bytes=2_000_000,
        max_sample_bytes=64_000,
        max_geometry_vertices=512,
        max_cpu_seconds=10.0,
        max_memory_bytes=64_000_000,
        max_workspace_bytes=64_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=max_queue_depth,
        max_deadline_seconds=20.0,
        lease_duration_seconds=30.0,
        max_retry_attempts=1,
    ).sealed()


def runtime_identity() -> AnalysisRuntimeIdentityV2:
    return AnalysisRuntimeIdentityV2(
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="local-analysis-v1",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    )


def valid_wire(
    *,
    policy: AnalysisPolicyV2 | None = None,
    envelope: ResourceEnvelopeV1 | None = None,
) -> dict[str, object]:
    runtime = runtime_identity()
    return {
        "version": "local-analysis-runtime.v1",
        "policy": (policy or sealed_policy()).model_dump(by_alias=True, mode="json"),
        "runtime": {
            "workerExecutableDigest": runtime.worker_executable_digest,
            "workerBuildDigest": runtime.worker_build_digest,
            "runtimeImageVersion": runtime.runtime_image_version,
            "runtimeImageOciDigest": runtime.runtime_image_oci_digest,
            "dependencyLockDigest": runtime.dependency_lock_digest,
        },
        "resourceEnvelope": (envelope or sealed_envelope()).model_dump(
            by_alias=True, mode="json"
        ),
    }


def write_private_config(path: Path, wire: object) -> Path:
    path.write_text(json.dumps(wire, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_loads_explicit_canonical_sealed_runtime_material_without_rewriting(
    tmp_path: Path,
) -> None:
    policy = sealed_policy()
    envelope = sealed_envelope()
    path = write_private_config(
        tmp_path / "local-analysis.json",
        valid_wire(policy=policy, envelope=envelope),
    )

    graph = load_local_analysis_runtime_config(path)

    assert graph.policy == policy
    assert graph.resource_envelope == envelope
    assert graph.runtime == runtime_identity()
    assert graph.policy.policy_digest == policy.canonical_digest()
    assert graph.resource_envelope.resource_envelope_digest == envelope.canonical_digest()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda wire: wire["policy"].pop("policyDigest"),
        lambda wire: wire["resourceEnvelope"].pop("resourceEnvelopeDigest"),
        lambda wire: wire.update({"unknown": "not accepted"}),
        lambda wire: wire.update({"version": "local-analysis-runtime.v0"}),
    ],
    ids=["unsealed-policy", "unsealed-envelope", "unknown-top-level", "wrong-version"],
)
def test_rejects_unsealed_or_noncanonical_operator_configuration(
    tmp_path: Path, mutate: object
) -> None:
    wire = valid_wire()
    assert callable(mutate)
    mutate(wire)
    path = write_private_config(tmp_path / "local-analysis.json", wire)

    with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
        load_local_analysis_runtime_config(path)

    assert raised.value.code in {
        LocalAnalysisRuntimeConfigBlockedCode.CONFIG_VALUE,
        LocalAnalysisRuntimeConfigBlockedCode.UNKNOWN_FIELD,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":"local-analysis-runtime.v1","version":"local-analysis-runtime.v1"}',
        b'{"version":NaN}',
        b'{"version":"local-analysis-runtime.v1","policy":{},"runtime":{},"resourceEnvelope":{},"unexpected":true}',
    ],
    ids=["duplicate-field", "nonfinite", "unknown-field"],
)
def test_rejects_ambiguous_or_invalid_json_before_graph_assembly(
    tmp_path: Path, raw: bytes
) -> None:
    path = tmp_path / "local-analysis.json"
    path.write_bytes(raw)
    path.chmod(0o600)

    with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
        load_local_analysis_runtime_config(path)

    assert raised.value.code in {
        LocalAnalysisRuntimeConfigBlockedCode.CONFIG_SYNTAX,
        LocalAnalysisRuntimeConfigBlockedCode.UNKNOWN_FIELD,
        LocalAnalysisRuntimeConfigBlockedCode.CONFIG_VALUE,
    }


def test_rejects_unsafe_or_oversized_config_file_before_parsing(tmp_path: Path) -> None:
    target = write_private_config(tmp_path / "target.json", valid_wire())
    symlink = tmp_path / "link.json"
    symlink.symlink_to(target)
    too_open = write_private_config(tmp_path / "too-open.json", valid_wire())
    too_open.chmod(0o644)
    too_large = tmp_path / "too-large.json"
    too_large.write_bytes(b"{" + (b"x" * (256 * 1024 + 1)))
    too_large.chmod(0o600)

    for path in (symlink, too_open, too_large, Path("relative.json")):
        with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
            load_local_analysis_runtime_config(path)
        assert raised.value.code is LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE


def test_rejects_private_config_below_non_private_writable_ancestor(tmp_path: Path) -> None:
    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir()
    unsafe_parent.chmod(0o777)
    path = write_private_config(unsafe_parent / "local-analysis.json", valid_wire())

    with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
        load_local_analysis_runtime_config(path)

    assert raised.value.code is LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE


def test_rejects_same_owner_in_place_mutation_during_bounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_private_config(tmp_path / "local-analysis.json", valid_wire())
    original_raw = path.read_bytes()
    replacement = valid_wire()
    runtime = replacement["runtime"]
    assert isinstance(runtime, dict)
    runtime["workerBuildDigest"] = _digest("replacement-build")
    replacement_raw = json.dumps(replacement, separators=(",", ":")).encode("utf-8")
    assert len(replacement_raw) == len(original_raw)

    original_read = local_analysis_runtime_config.os.read
    mutated = False

    def read_then_mutate(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if not mutated:
            mutated = True
            with path.open("r+b") as replacement_file:
                replacement_file.write(replacement_raw)
                replacement_file.truncate()
                replacement_file.flush()
                os.fsync(replacement_file.fileno())
        return chunk

    monkeypatch.setattr(local_analysis_runtime_config.os, "read", read_then_mutate)

    with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
        load_local_analysis_runtime_config(path)

    assert mutated
    assert raised.value.code is LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE


def _read_fifo_in_child(path: str, output: multiprocessing.Queue[str]) -> None:
    try:
        load_local_analysis_runtime_config(Path(path))
    except LocalAnalysisRuntimeConfigUnavailable as exc:
        output.put(exc.code.value)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO support")
def test_rejects_fifo_without_blocking_before_regular_file_validation(tmp_path: Path) -> None:
    fifo = tmp_path / "local-analysis.fifo"
    os.mkfifo(fifo, 0o600)
    output: multiprocessing.Queue[str] = multiprocessing.Queue()
    process = multiprocessing.Process(target=_read_fifo_in_child, args=(str(fifo), output))
    process.start()
    process.join(timeout=2)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        pytest.fail("loader blocked while opening a non-regular FIFO configuration")
    assert process.exitcode == 0
    assert output.get(timeout=1) == LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE.value


def test_rejects_deep_json_as_typed_configuration_syntax_failure(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_bytes(b'{"version":' + (b"[" * 5_000) + (b"]" * 5_000) + b"}")
    path.chmod(0o600)

    with pytest.raises(LocalAnalysisRuntimeConfigUnavailable) as raised:
        load_local_analysis_runtime_config(path)

    assert raised.value.code in {
        LocalAnalysisRuntimeConfigBlockedCode.CONFIG_SYNTAX,
        LocalAnalysisRuntimeConfigBlockedCode.CONFIG_VALUE,
    }

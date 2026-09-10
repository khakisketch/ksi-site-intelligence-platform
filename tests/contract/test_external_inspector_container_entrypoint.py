"""Direct conformance for the fixed in-image inspector entrypoint.

These local byte-stream tests exercise the owned entrypoint only.  They do not
claim that Docker, a UID mapping, cgroups, or a read-only bind has been proven
on this host.
"""

from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionHardCeilingsV1,
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
    InspectorImageIdentityV1,
    InspectorSecurityProfileV1,
)
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_container_entrypoint import (
    ContainerEntrypointError,
    ContainerEntrypointIncomplete,
    run_container_entrypoint,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
    build_execute_frame,
    build_prepare_frame,
    decode_inner_frame,
    encode_inner_frame,
)
from test_external_sanitized_raster import _digest, _write_rgba


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=20_000_000,
        max_streamed_bytes=20_000_000,
        max_tiff_directories=32,
        max_tiff_entries=2_048,
        max_pixels=2_000_000,
        max_bands=4,
        max_blocks=2_048,
        max_decompressed_bytes=40_000_000,
        max_sample_bytes=40_000_000,
        max_geometry_vertices=8,
        max_cpu_seconds=1.0,
        max_memory_bytes=40_000_000,
        max_workspace_bytes=40_000_000,
        max_output_bytes=20_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()


def _digest_marker(marker: str) -> str:
    return "sha256:" + sha256(marker.encode("ascii")).hexdigest()


def _manifest(envelope: ResourceEnvelopeV1) -> InspectorExecutionManifestV1:
    from ksi_processing_controller.external_inspector_container_protocol import (
        compiled_inner_protocol_digest_v1,
        compiled_security_profile_digest_v1,
    )

    assert envelope.resource_envelope_digest is not None
    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=_digest_marker("image-manifest"),
            oci_config_digest=_digest_marker("image-config"),
        ),
        source_tree_digest=_digest_marker("source"),
        build_provenance_digest=_digest_marker("provenance"),
        sbom_digest=_digest_marker("sbom"),
        inspector_protocol_digest=compiled_inner_protocol_digest_v1(),
        backend_profile_digest=external_geotiff_profile_digest_v1(),
        security_profile_digest=compiled_security_profile_digest_v1(),
        resource_envelope_digest=envelope.resource_envelope_digest,
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=10001,
        runtime_gid=10001,
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=20_000_000,
            max_memory_bytes=40_000_000,
            max_tmpfs_bytes=40_000_000,
            max_pids=16,
            cpu_period_micros=100_000,
            cpu_quota_micros=50_000,
            max_wall_time_millis=1_000,
            max_log_bytes=2_048,
            max_output_bytes=20_000_000,
        ),
    )
    return InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="synthetic-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode("ascii"),
        ),
    )


def _policy(
    manifest: InspectorExecutionManifestV1,
    envelope: ResourceEnvelopeV1,
) -> ExternalValidationPolicyV1:
    assert envelope.resource_envelope_digest is not None
    return ExternalValidationPolicyV1(
        policy_id="policy",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=manifest.parser_build_digest,
        grammar_digest=external_geotiff_profile_digest_v1(),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest_marker("authority"),
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
    ).sealed()


def _prepare(
    source: Path, *, operation: str
) -> tuple[dict[str, object], ContainerInnerFrameLimitsV1]:
    envelope = _envelope()
    manifest = _manifest(envelope)
    policy = _policy(manifest, envelope)
    limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=128_000, maximum_stderr_bytes=0)
    return (
        build_prepare_frame(
            attempt_nonce="attempt-1",
            outer_canonical_input_digest=_digest_marker("outer"),
            operation=operation,
            sealed_byte_binding={
                "artifactId": "ortho",
                "observedSha256": _digest(source),
                "observedSizeBytes": source.stat().st_size,
            },
            policy=policy,
            manifest=manifest,
            admitted_backend_profile_digest=manifest.body.backend_profile_digest,
            admitted_security_profile_digest=manifest.body.security_profile_digest,
            admitted_inner_protocol_digest=manifest.body.inspector_protocol_digest,
        ),
        limits,
    )


def _decode_output(
    stream: BytesIO,
    limits: ContainerInnerFrameLimitsV1,
) -> tuple[dict[str, object], dict[str, object], bytes]:
    raw = stream.getvalue()
    first_size = int.from_bytes(raw[:4], "big")
    first = decode_inner_frame(raw[: 4 + first_size], limits=limits)
    second_start = 4 + first_size
    second_size = int.from_bytes(raw[second_start : second_start + 4], "big")
    second_end = second_start + 4 + second_size
    second = decode_inner_frame(raw[second_start:second_end], limits=limits)
    return cast(dict[str, object], first), cast(dict[str, object], second), raw[second_end:]


def test_entrypoint_sanitize_is_closed_and_emits_only_the_verified_private_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_rgba(source)
    prepare, limits = _prepare(source, operation="SANITIZE")
    stdin = BytesIO(
        encode_inner_frame(prepare, limits=limits)
        + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
    )
    stdout = BytesIO()

    run_container_entrypoint(
        stdin=stdin,
        stdout=stdout,
        artifact_path=source,
        workspace=workspace,
        limits=limits,
    )

    mount, terminal, raw = _decode_output(stdout, limits)
    assert mount["frame"] == "MOUNT_VERIFIED"
    assert mount["actualSha256"] == _digest(source)
    assert terminal["frame"] == "COMPLETED"
    assert terminal["outcome"] == "SANITIZED"
    assert terminal["outputSizeBytes"] == len(raw)
    assert terminal["outputSha256"] == "sha256:" + sha256(raw).hexdigest()
    assert not list(workspace.iterdir())


def test_entrypoint_rejects_execute_before_mount_bound_prepare(tmp_path: Path) -> None:
    source = tmp_path / "input.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_rgba(source)
    prepare, limits = _prepare(source, operation="INSPECT")
    malformed = {**build_execute_frame(prepare=prepare), "operation": "SANITIZE"}

    with pytest.raises(ContainerEntrypointError, match="EXECUTE"):
        run_container_entrypoint(
            stdin=BytesIO(
                encode_inner_frame(prepare, limits=limits)
                + encode_inner_frame(malformed, limits=limits)
            ),
            stdout=BytesIO(),
            artifact_path=source,
            workspace=workspace,
            limits=limits,
        )


def test_entrypoint_cancellation_is_incomplete_and_never_publishes_a_terminal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_rgba(source)
    prepare, limits = _prepare(source, operation="INSPECT")
    stdout = BytesIO()

    with pytest.raises(ContainerEntrypointIncomplete, match="cancelled"):
        run_container_entrypoint(
            stdin=BytesIO(
                encode_inner_frame(prepare, limits=limits)
                + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
            ),
            stdout=stdout,
            artifact_path=source,
            workspace=workspace,
            limits=limits,
            is_cancelled=lambda: True,
        )

    assert stdout.getvalue() == b""


def test_entrypoint_inspect_returns_a_typed_artifact_rejection_for_unsupported_raw_model(
    tmp_path: Path,
) -> None:
    """A raw-model failure is examined artifact evidence, never a fake DSM/ORTHO result."""
    source = tmp_path / "input.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="uint8",
        crs="EPSG:3857",
        transform=rasterio.transform.from_origin(0.0, 32.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.zeros((1, 32, 32), dtype=np.uint8))
    prepare, limits = _prepare(source, operation="INSPECT")
    stdout = BytesIO()

    run_container_entrypoint(
        stdin=BytesIO(
            encode_inner_frame(prepare, limits=limits)
            + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
        ),
        stdout=stdout,
        artifact_path=source,
        workspace=workspace,
        limits=limits,
    )

    _, terminal, raw = _decode_output(stdout, limits)
    assert terminal["frame"] == "COMPLETED"
    outcome = cast(dict[str, object], terminal["outcome"])
    assert outcome["outcome"] == "REJECTED"
    assert outcome["reason"] == "UNSUPPORTED_RASTER"
    assert raw == b""

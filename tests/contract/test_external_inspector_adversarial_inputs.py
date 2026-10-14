"""Synthetic adversarial-input security tests for the external inspector parser lane.

Scope: the real parser entrypoint
``ksi_processing_controller.external_geotiff_inspector`` (in-process; the same
code the future container runs) and the fixed container-entrypoint protocol
(``run_container_entrypoint`` / ``decode_inner_frame``) where a case is
expressible without a daemon. Every hostile input is synthetic bytes generated
in ``tmp_path``. No test uses the network, the real Docker daemon, host
devices, or elevated privileges.

Fail-closed contract: every hostile byte stream must either be examined into a
typed ``ArtifactInspectionOutcomeV1`` (``MEASURED`` with finite measurements or
``REJECTED`` with a closed reason literal) or raise the product's own typed
terminal error (``SyntheticGeoTiffInspectionIncomplete``,
``ContainerEntrypointError``, ``ContainerInnerProtocolViolation``). Generic
exceptions escaping the lane fail the test.

Deliberately NOT covered here (host enforcement belongs to Task 5c
``test_host_*``): real cgroup-v2/no-network namespace proof, UID-map and
read-only bind proof, daemon socket identity, kill latency, and orphan
recovery. Those cases cannot be expressed through the public in-process
surfaces, so they are stated here instead of mocked. There is no unsandboxed
parser fallback expectation anywhere in this file.

All tests are deterministic and bounded (payloads of at most 64x64 pixels, no
sleeps, no retries, no timeouts): nothing here can block on I/O by
construction.
"""

from __future__ import annotations

import socket
import struct
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    NodataRepresentation,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_geotiff_inspector import (
    SyntheticGeoTiffInspectionIncomplete,
    inspect_synthetic_sealed_geotiff,
)
from ksi_processing_controller.external_inspector_container_entrypoint import (
    ContainerEntrypointError,
    run_container_entrypoint,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
    ContainerInnerProtocolViolation,
    build_execute_frame,
    decode_inner_frame,
    encode_inner_frame,
)
from ksi_processing_controller.external_tiff_structure import (
    TiffStructureError,
    parse_sealed_tiff_structure,
)
from pydantic import ValidationError
from rasterio.transform import from_origin
from test_external_inspector_container_entrypoint import (
    _decode_output,
)
from test_external_inspector_container_entrypoint import (
    _prepare as _entrypoint_prepare,
)
from test_external_sanitized_raster import _write_rgba

_CLOSED_REASONS = frozenset(
    {
        "UNSUPPORTED_RASTER",
        "MALFORMED_TIFF",
        "AMBIGUOUS_GEOREFERENCE",
        "UNSAFE_EXTERNAL_REFERENCE",
        "RESOURCE_LIMIT_EXCEEDED",
        "UNMASKED_NONFINITE_SAMPLE",
        "SANITIZER_FAILED",
    }
)

_FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
_FAKE_PASSWORD = "db_password=s3cr3t-canary-value-9f31"


def _envelope(**overrides: Any) -> ResourceEnvelopeV1:
    fields: dict[str, Any] = {
        "max_input_bytes": 1_000_000,
        "max_streamed_bytes": 1_000_000,
        "max_tiff_directories": 16,
        "max_tiff_entries": 512,
        "max_pixels": 1_000_000,
        "max_bands": 4,
        "max_blocks": 1_000,
        "max_decompressed_bytes": 10_000_000,
        "max_sample_bytes": 10_000_000,
        "max_geometry_vertices": 8,
        "max_cpu_seconds": 1.0,
        "max_memory_bytes": 10_000_000,
        "max_workspace_bytes": 10_000_000,
        "max_output_bytes": 1_000_000,
        "max_tenant_concurrency": 1,
        "max_queue_depth": 1,
        "max_deadline_seconds": 1.0,
        "lease_duration_seconds": 1.0,
        "max_retry_attempts": 1,
    }
    fields.update(overrides)
    return ResourceEnvelopeV1(**fields).sealed()


def _inspect(
    path: Path,
    kind: ProcessingArtifactKind,
    *,
    envelope: ResourceEnvelopeV1 | None = None,
) -> ArtifactInspectionOutcomeV1:
    payload = path.read_bytes()
    return inspect_synthetic_sealed_geotiff(
        path,
        artifact_id="adversarial",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=kind,
        envelope=envelope if envelope is not None else _envelope(),
    )


def _write_rgb(
    path: Path,
    *,
    width: int = 16,
    height: int = 16,
    compress: str = "DEFLATE",
) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, float(height), 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress=compress,
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.full((3, height, width), 17, dtype=np.uint8))
    return path


def _write_dsm_values(path: Path, values: np.ndarray) -> Path:
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, float(height), 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=3,
        interleave="pixel",
    ) as dataset:
        dataset.write(values[np.newaxis, ...])
    return path


def _forbid_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove preflight rejection: Rasterio must never see the hostile bytes."""
    import ksi_processing_controller.external_geotiff_inspector as inspector

    def _never_open(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("hostile TIFF reached the decoder")

    monkeypatch.setattr(inspector.rasterio, "open", _never_open)


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any dial attempt fails the test; the lane must be offline by construction."""

    def _denied(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("parser lane attempted network I/O")

    monkeypatch.setattr(socket.socket, "connect", _denied)
    monkeypatch.setattr(socket, "create_connection", _denied)


def _classic_entry_offset(payload: bytearray, directory_offset: int, tag: int) -> int:
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    for index in range(entry_count):
        entry_offset = directory_offset + 2 + 12 * index
        if struct.unpack_from("<H", payload, entry_offset)[0] == tag:
            return entry_offset
    raise AssertionError(f"classic TIFF tag {tag} is absent")


def _patch_declared_dimensions(payload: bytearray, width: int, height: int) -> None:
    """Rewrite inline SHORT ImageWidth/ImageLength without touching allocations."""
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    for tag, value in ((256, width), (257, height)):
        entry_offset = _classic_entry_offset(payload, directory_offset, tag)
        tag_id, field_type, count = struct.unpack_from("<HHI", payload, entry_offset)
        assert tag_id == tag and field_type == 3 and count == 1
        struct.pack_into("<H", payload, entry_offset + 8, value)


def _point_next_ifd_at_itself(path: Path) -> None:
    """Rewire the first directory's next-pointer into a self cycle."""
    payload = bytearray(path.read_bytes())
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    next_location = directory_offset + 2 + 12 * entry_count
    struct.pack_into("<I", payload, next_location, directory_offset)
    path.write_bytes(payload)


def _append_conflicting_model_transformation(path: Path) -> None:
    """Attach a ModelTransformation that contradicts the tiepoint/scale tags."""
    matrix = (
        2.0,
        0.0,
        0.0,
        1.0,
        0.0,
        -2.0,
        0.0,
        15.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )
    payload = bytearray(path.read_bytes())
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    entries_start = directory_offset + 2
    next_offset = struct.unpack_from("<I", payload, entries_start + entry_count * 12)[0]
    appended_offset = len(payload)
    if appended_offset % 2:
        payload.append(0)
        appended_offset += 1
    value_offset = appended_offset + 2 + (entry_count + 1) * 12 + 4
    payload.extend(struct.pack("<H", entry_count + 1))
    payload.extend(payload[entries_start : entries_start + entry_count * 12])
    payload.extend(struct.pack("<HHII", 34264, 12, 16, value_offset))
    payload.extend(struct.pack("<I", next_offset))
    payload.extend(struct.pack("<16d", *matrix))
    struct.pack_into("<I", payload, 4, appended_offset)
    path.write_bytes(payload)


def _gdal_metadata_span(payload: bytearray) -> tuple[int, int]:
    """Return (value_offset, byte_count) of the out-of-line GDAL_METADATA tag."""
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    entry_offset = _classic_entry_offset(payload, directory_offset, 42112)
    _, field_type, count, value_offset = struct.unpack_from("<HHII", payload, entry_offset)
    assert field_type == 2
    return value_offset, count


def _write_tagged_rgb(path: Path, tags: dict[str, str]) -> Path:
    _write_rgb(path)
    with rasterio.open(path, "r+") as dataset:
        dataset.update_tags(**tags)
    return path


def _assert_typed_rejection(
    outcome: ArtifactInspectionOutcomeV1, expected_reason: str
) -> None:
    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == expected_reason
    assert outcome.reason in _CLOSED_REASONS
    assert outcome.measurements is None


# --- Declared-dimension / band / block envelope attacks -----------------------


def test_oversized_declared_dimensions_fail_the_allocation_ledger_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 65535x65535 declaration on a one-tile payload fails block geometry first.

    The global allocation ledger rejects the inconsistent declaration as
    MALFORMED_TIFF before any cap comparison or decoder expansion runs.
    """
    target = _write_rgb(tmp_path / "declared-huge.tif")
    payload = bytearray(target.read_bytes())
    _patch_declared_dimensions(payload, 65_535, 65_535)
    target.write_bytes(payload)
    _forbid_decoder(monkeypatch)

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


def test_declared_band_count_beyond_envelope_is_resource_limited(tmp_path: Path) -> None:
    """Three sealed bands against a two-band envelope are capped before decode."""
    target = _write_rgb(tmp_path / "three-band.tif")

    outcome = _inspect(
        target, ProcessingArtifactKind.ORTHO, envelope=_envelope(max_bands=2)
    )

    _assert_typed_rejection(outcome, "RESOURCE_LIMIT_EXCEEDED")


def test_pixel_count_beyond_envelope_is_resource_limited(tmp_path: Path) -> None:
    """256 sealed pixels against a 100-pixel envelope are capped before decode."""
    target = _write_rgb(tmp_path / "pixels.tif")

    outcome = _inspect(
        target, ProcessingArtifactKind.ORTHO, envelope=_envelope(max_pixels=100)
    )

    _assert_typed_rejection(outcome, "RESOURCE_LIMIT_EXCEEDED")


def test_block_count_cap_rejects_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sixteen sealed tiles against a four-block envelope fail before expansion."""
    target = _write_rgb(tmp_path / "many-blocks.tif", width=64, height=64)
    _forbid_decoder(monkeypatch)

    outcome = _inspect(
        target, ProcessingArtifactKind.ORTHO, envelope=_envelope(max_blocks=4)
    )

    _assert_typed_rejection(outcome, "RESOURCE_LIMIT_EXCEEDED")


# --- Directory-chain attacks --------------------------------------------------


def test_cyclic_next_ifd_pointer_rejects_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A self-looping IFD chain is malformed, never an infinite preflight walk."""
    target = _write_rgb(tmp_path / "cyclic.tif")
    _point_next_ifd_at_itself(target)
    _forbid_decoder(monkeypatch)

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


def test_ifd_chain_beyond_directory_cap_is_resource_limited(tmp_path: Path) -> None:
    """A base-plus-overview chain against a one-directory envelope is capped."""
    source = _write_rgb(tmp_path / "overview.tif", width=64, height=64)
    with rasterio.open(source, "r+") as dataset:
        dataset.build_overviews([2], rasterio.enums.Resampling.nearest)
    structure = parse_sealed_tiff_structure(source, _envelope())
    assert len(structure.directories) == 2

    outcome = _inspect(
        source, ProcessingArtifactKind.ORTHO, envelope=_envelope(max_tiff_directories=1)
    )

    _assert_typed_rejection(outcome, "RESOURCE_LIMIT_EXCEEDED")


# --- Decompression / truncation attacks ---------------------------------------


def test_decompression_bomb_estimate_rejects_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A small DEFLATE payload against a tight decompressed cap is capped pre-decode.

    The 64x64 RGB estimate (12288 bytes) exceeds the 100-byte envelope budget
    while the sealed file stays small, so the rejection proves the estimate is
    enforced before the decoder can expand anything.
    """
    target = _write_rgb(
        tmp_path / "bomb.tif", width=64, height=64, compress="DEFLATE"
    )
    assert target.stat().st_size < 1_000_000
    _forbid_decoder(monkeypatch)

    outcome = _inspect(
        target,
        ProcessingArtifactKind.ORTHO,
        envelope=_envelope(max_decompressed_bytes=100),
    )

    _assert_typed_rejection(outcome, "RESOURCE_LIMIT_EXCEEDED")


def test_truncated_payload_rejects_as_malformed(tmp_path: Path) -> None:
    """A payload cut mid-tile is malformed; no generic exception may escape."""
    target = _write_rgb(tmp_path / "truncated.tif")
    payload = target.read_bytes()
    target.write_bytes(payload[: len(payload) // 2])

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


def test_empty_and_magic_only_payloads_reject_as_malformed(tmp_path: Path) -> None:
    """Zero-length and header-only inputs are typed rejections, never tracebacks."""
    empty = tmp_path / "empty.tif"
    empty.write_bytes(b"")
    assert _inspect(empty, ProcessingArtifactKind.ORTHO).reason == "MALFORMED_TIFF"

    magic_only = tmp_path / "magic.tif"
    magic_only.write_bytes(b"II*\x00")
    outcome = _inspect(magic_only, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


# --- Georeference / sample-value attacks --------------------------------------


def test_conflicting_model_transformation_rejects_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dual affine tags cannot let decoder precedence pick a silent winner."""
    target = _write_rgb(tmp_path / "dual-affine.tif")
    _append_conflicting_model_transformation(target)
    _forbid_decoder(monkeypatch)

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


def test_unmasked_infinity_rejects_as_nonfinite_sample(tmp_path: Path) -> None:
    """An unmasked +Inf DSM sample is evidence of hostility, not elevation."""
    values = np.ones((16, 16), dtype=np.float32)
    values[5, 5] = np.inf
    target = _write_dsm_values(tmp_path / "inf-dsm.tif", values)

    outcome = _inspect(target, ProcessingArtifactKind.DSM)

    _assert_typed_rejection(outcome, "UNMASKED_NONFINITE_SAMPLE")


def test_non_ascii_metadata_rejects_as_malformed(tmp_path: Path) -> None:
    """Non-ASCII bytes in GDAL_METADATA are malformed, never decoded loosely."""
    target = _write_tagged_rgb(tmp_path / "non-ascii.tif", {"HOSTILE": "plain"})
    payload = bytearray(target.read_bytes())
    value_offset, byte_count = _gdal_metadata_span(payload)
    hostile = b"\xff\xfe-not-text-\x80"
    payload[value_offset : value_offset + len(hostile)] = hostile
    target.write_bytes(payload)

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


def test_very_long_benign_metadata_stays_a_typed_outcome(tmp_path: Path) -> None:
    """A 4000-character tag value must not crash, hang, or leak into measurements."""
    target = _write_tagged_rgb(tmp_path / "long-tag.tif", {"NOTE": "x" * 4_000})

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.reason is None


# --- Sidecar / VSI / external-reference attacks --------------------------------


@pytest.mark.parametrize("suffix", [".aux.xml", ".msk"])
def test_external_sidecar_siblings_are_unsafe(
    tmp_path: Path, suffix: str
) -> None:
    """Sibling `.aux.xml`/`.msk` files are never consulted as trusted overviews."""
    target = _write_rgb(tmp_path / "sealed.tif")
    (tmp_path / ("sealed.tif" + suffix)).write_bytes(b"untrusted sibling bytes")

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "UNSAFE_EXTERNAL_REFERENCE")


def test_uppercase_vrt_suffix_is_unsafe(tmp_path: Path) -> None:
    """Suffix screening is case-insensitive: `.VRT` is not a sealed TIFF."""
    target = _write_rgb(tmp_path / "sealed.tif")
    renamed = tmp_path / "sealed.VRT"
    renamed.write_bytes(target.read_bytes())

    outcome = _inspect(renamed, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "UNSAFE_EXTERNAL_REFERENCE")


def test_vsicurl_metadata_rejects_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `/vsicurl/` URL in metadata is rejected and never dialed."""
    target = _write_tagged_rgb(tmp_path / "vsi.tif", {"SOURCE": "local-origin"})
    payload = bytearray(target.read_bytes())
    value_offset, byte_count = _gdal_metadata_span(payload)
    canary = b"/vsicurl/http://canary.invalid/x"
    assert len(canary) < byte_count
    payload[value_offset : value_offset + len(canary)] = canary
    target.write_bytes(payload)
    _forbid_network(monkeypatch)

    outcome = _inspect(target, ProcessingArtifactKind.ORTHO)

    _assert_typed_rejection(outcome, "MALFORMED_TIFF")


# --- Path / mount-identity attacks ----------------------------------------------


def test_symlink_input_is_not_a_sealed_stream(tmp_path: Path) -> None:
    """A symlink is never followed into the parser, even when the target is valid."""
    target = _write_rgb(tmp_path / "real.tif")
    link = tmp_path / "link.tif"
    link.symlink_to(target)
    payload = target.read_bytes()

    outcome = inspect_synthetic_sealed_geotiff(
        link,
        artifact_id="adversarial",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=_envelope(),
    )

    _assert_typed_rejection(outcome, "UNSUPPORTED_RASTER")


def test_absolute_and_traversal_paths_are_typed_rejections(tmp_path: Path) -> None:
    """Absolute non-TIFF bytes and absent traversal paths map to MALFORMED_TIFF."""
    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"definitely not a tiff payload")
    absolute = _inspect(plain.resolve(), ProcessingArtifactKind.ORTHO)
    _assert_typed_rejection(absolute, "MALFORMED_TIFF")

    # The absent traversal path never reaches the digest helper: lstat fails
    # first inside the parser lane, which maps OSError to a typed rejection.
    traversal = tmp_path / ".." / "definitely-absent-adversarial.tif"
    missing = inspect_synthetic_sealed_geotiff(
        traversal,
        artifact_id="adversarial",
        observed_sha256="sha256:" + "00" * 32,
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=_envelope(),
    )
    _assert_typed_rejection(missing, "MALFORMED_TIFF")


# --- Network-canary / environment attacks ----------------------------------------


def test_hostile_proxy_env_does_not_change_typed_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proxy env vars cannot reroute the offline parser lane or alter verdicts."""
    monkeypatch.setenv("HTTP_PROXY", "http://canary.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://canary.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://canary.invalid:8080")
    monkeypatch.setenv("GDAL_HTTP_PROXY", "canary.invalid:8080")
    _forbid_network(monkeypatch)

    benign = _write_rgb(tmp_path / "benign.tif")
    benign_outcome = _inspect(benign, ProcessingArtifactKind.ORTHO)
    assert benign_outcome.outcome is ArtifactOutcome.MEASURED

    target = _write_tagged_rgb(tmp_path / "vsi-env.tif", {"SOURCE": "local"})
    payload = bytearray(target.read_bytes())
    value_offset, byte_count = _gdal_metadata_span(payload)
    canary = b"https://canary.invalid/raster.tif"
    assert len(canary) < byte_count
    payload[value_offset : value_offset + len(canary)] = canary
    target.write_bytes(payload)
    hostile_outcome = _inspect(target, ProcessingArtifactKind.ORTHO)
    _assert_typed_rejection(hostile_outcome, "MALFORMED_TIFF")


def test_cancellation_stays_a_typed_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation is request-level and can never surface a partial measurement."""
    target = _write_rgb(tmp_path / "cancel.tif")
    _forbid_network(monkeypatch)
    payload = target.read_bytes()

    with pytest.raises(SyntheticGeoTiffInspectionIncomplete):
        inspect_synthetic_sealed_geotiff(
            target,
            artifact_id="adversarial",
            observed_sha256="sha256:" + sha256(payload).hexdigest(),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            envelope=_envelope(),
            is_cancelled=lambda: True,
        )


# --- Credential / secret-hygiene attacks ----------------------------------------


def test_credential_bytes_never_surface_in_outcome_json(tmp_path: Path) -> None:
    """Secrets smuggled in metadata must appear in no measurement, reason, or digest."""
    target = _write_tagged_rgb(
        tmp_path / "secret.tif",
        {"OPERATOR_NOTE": f"contact {_FAKE_AWS_KEY} {_FAKE_PASSWORD}"},
    )
    measured = _inspect(target, ProcessingArtifactKind.ORTHO)
    assert measured.outcome is ArtifactOutcome.MEASURED
    assert _FAKE_AWS_KEY not in measured.model_dump_json()
    assert _FAKE_PASSWORD not in measured.model_dump_json()

    payload = bytearray(target.read_bytes())
    struct.pack_into("<I", payload, 4, len(payload) + 4_096)
    corrupted = tmp_path / "secret-corrupt.tif"
    corrupted.write_bytes(payload)
    rejected = _inspect(corrupted, ProcessingArtifactKind.ORTHO)
    assert rejected.outcome is ArtifactOutcome.REJECTED
    assert _FAKE_AWS_KEY not in rejected.model_dump_json()
    assert _FAKE_PASSWORD not in rejected.model_dump_json()


# --- Docker-denial for the parser lane -------------------------------------------


def test_docker_config_is_ignored_by_the_parser_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docker env vars cannot reach, reroute, or fail the parser computation."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://canary.invalid:2375")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path))
    _forbid_network(monkeypatch)

    outcome = _inspect(_write_rgb(tmp_path / "benign.tif"), ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.MEASURED


def test_parser_lane_modules_have_no_docker_socket_or_subprocess_reach() -> None:
    """The parser and entrypoint modules must not import container/process I/O."""
    root = Path(__file__).parents[2] / (
        "services/processing-controller/src/ksi_processing_controller"
    )
    for module in ("external_geotiff_inspector.py", "external_inspector_container_entrypoint.py"):
        source = (root / module).read_text(encoding="utf-8")
        assert "import docker" not in source
        assert "from docker" not in source
        assert "DOCKER_HOST" not in source
        assert "subprocess" not in source
        assert "import socket" not in source


# --- Parser-output injection (contract-model fail-closure) ------------------------


def _valid_measurements(**overrides: Any) -> dict[str, Any]:
    digest = "sha256:" + "ab" * 32
    fields: dict[str, Any] = {
        "observed_crs_identifier": "EPSG:3857",
        "observed_crs_wkt": None,
        "observed_crs_digest": digest,
        "observed_vertical_reference": None,
        "transform": (2.0, 0.0, 100.0, 0.0, -2.0, 200.0),
        "footprint_wkt": "POLYGON ((100 200, 132 200, 132 168, 100 168, 100 200))",
        "footprint_digest": digest,
        "width": 16,
        "height": 16,
        "band_count": 3,
        "dtype": "uint8",
        "layout": "GEOTIFF_TILED_V1",
        "nodata_representation": NodataRepresentation.NONE,
        "nodata_value": None,
        "valid_pixel_count": 256,
    }
    fields.update(overrides)
    return fields


@pytest.mark.parametrize(
    "override",
    [
        {"transform": (float("nan"), 0.0, 100.0, 0.0, -2.0, 200.0)},
        {"transform": (float("inf"), 0.0, 100.0, 0.0, -2.0, 200.0)},
        {
            "nodata_representation": NodataRepresentation.FINITE,
            "nodata_value": float("nan"),
        },
        {
            "nodata_representation": NodataRepresentation.NONE,
            "nodata_value": 0.0,
        },
        {"valid_pixel_count": 257},
        {"width": 0},
        {"band_count": -1},
    ],
)
def test_raster_measurements_reject_nonfinite_and_impossible_geometry(
    override: dict[str, Any],
) -> None:
    """Non-finite transforms, stray nodata, and impossible geometry are invalid."""
    with pytest.raises(ValidationError):
        RasterMeasurementsV1(**_valid_measurements(**override))


def test_outcome_shape_violations_are_typed_validation_errors() -> None:
    """MEASURED-with-reason and REJECTED-with-measurements cannot be constructed."""
    digest = "sha256:" + "cd" * 32
    with pytest.raises(ValidationError):
        ArtifactInspectionOutcomeV1(
            artifact_id="adversarial",
            observed_sha256=digest,
            outcome=ArtifactOutcome.MEASURED,
            reason="MALFORMED_TIFF",
            measurements=RasterMeasurementsV1(**_valid_measurements()),
        )
    with pytest.raises(ValidationError):
        ArtifactInspectionOutcomeV1(
            artifact_id="adversarial",
            observed_sha256=digest,
            outcome=ArtifactOutcome.REJECTED,
            reason="MALFORMED_TIFF",
            measurements=RasterMeasurementsV1(**_valid_measurements()),
        )
    with pytest.raises(ValidationError):
        ArtifactInspectionOutcomeV1(
            artifact_id="adversarial",
            observed_sha256=digest,
            outcome=ArtifactOutcome.REJECTED,
            reason=None,
            measurements=None,
        )


# --- Container-entrypoint framing / mount attacks ---------------------------------


def _frame_limits() -> ContainerInnerFrameLimitsV1:
    return ContainerInnerFrameLimitsV1(maximum_frame_bytes=8_192, maximum_stderr_bytes=0)


def test_entrypoint_empty_control_stream_is_a_typed_error(tmp_path: Path) -> None:
    """An EOF before the first length prefix cannot hang or default to INSPECT."""
    with pytest.raises(ContainerEntrypointError, match="ended early"):
        run_container_entrypoint(
            stdin=BytesIO(b""),
            stdout=BytesIO(),
            artifact_path=tmp_path / "absent.tif",
            workspace=tmp_path,
            limits=_frame_limits(),
        )


def test_entrypoint_oversized_declared_frame_is_a_typed_error(tmp_path: Path) -> None:
    """A 4GiB declared control frame against an 8KiB cap fails before allocation."""
    limits = _frame_limits()
    declared = (limits.maximum_frame_bytes + 1).to_bytes(4, "big")
    with pytest.raises(ContainerEntrypointError, match="exceeds its cap"):
        run_container_entrypoint(
            stdin=BytesIO(declared),
            stdout=BytesIO(),
            artifact_path=tmp_path / "absent.tif",
            workspace=tmp_path,
            limits=limits,
        )


def test_entrypoint_garbage_frame_is_a_typed_error(tmp_path: Path) -> None:
    """Non-JSON control bytes are a closed protocol violation, never a partial run."""
    limits = _frame_limits()
    with pytest.raises(ContainerInnerProtocolViolation):
        decode_inner_frame(b"\x00\x00\x00\x04\xff\xfe\xfd\xfc", limits=limits)
    with pytest.raises(ContainerEntrypointError, match="invalid"):
        run_container_entrypoint(
            stdin=BytesIO(b"\x00\x00\x00\x04\xff\xfe\xfd\xfc"),
            stdout=BytesIO(),
            artifact_path=tmp_path / "absent.tif",
            workspace=tmp_path,
            limits=limits,
        )


def test_entrypoint_swapped_artifact_binding_fails_mount(tmp_path: Path) -> None:
    """PREPARE for file A with file B mounted is an identity error, not a parse."""
    source_a = _write_rgb(tmp_path / "a.tif")
    source_b = _write_rgb(tmp_path / "b.tif", width=32, height=32)
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    prepare, limits = _entrypoint_prepare(source_a, operation="INSPECT")

    with pytest.raises(ContainerEntrypointError, match="identity differs"):
        run_container_entrypoint(
            stdin=BytesIO(
                encode_inner_frame(prepare, limits=limits)
                + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
            ),
            stdout=BytesIO(),
            artifact_path=source_b,
            workspace=workspace,
            limits=limits,
        )


def test_entrypoint_symlink_artifact_fails_mount(tmp_path: Path) -> None:
    """A symlinked mount candidate fails identity even for byte-identical targets."""
    target = _write_rgb(tmp_path / "real.tif")
    link = tmp_path / "link.tif"
    link.symlink_to(target)
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    prepare, limits = _entrypoint_prepare(target, operation="INSPECT")

    with pytest.raises(ContainerEntrypointError, match="identity differs"):
        run_container_entrypoint(
            stdin=BytesIO(
                encode_inner_frame(prepare, limits=limits)
                + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
            ),
            stdout=BytesIO(),
            artifact_path=link,
            workspace=workspace,
            limits=limits,
        )


def test_entrypoint_nonempty_workspace_fails_closed(tmp_path: Path) -> None:
    """A workspace with pre-existing files cannot receive the private candidate.

    The empty-workspace fence lives on the SANITIZE path, which is the only
    path that streams a private output candidate.
    """
    source = tmp_path / "input.tif"
    _write_rgba(source, dimension=16)
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    (workspace / "planted.bin").write_bytes(b"pre-existing workspace content")
    prepare, limits = _entrypoint_prepare(source, operation="SANITIZE")

    with pytest.raises(ContainerEntrypointError):
        run_container_entrypoint(
            stdin=BytesIO(
                encode_inner_frame(prepare, limits=limits)
                + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
            ),
            stdout=BytesIO(),
            artifact_path=source,
            workspace=workspace,
            limits=limits,
        )


def test_entrypoint_hostile_bytes_yield_typed_rejection_outcome(tmp_path: Path) -> None:
    """A cyclic hostile input through the entrypoint is a REJECTED outcome.

    Parser-lane rejections travel inside a COMPLETED frame as a typed outcome
    (the existing entrypoint contract); the assertion pins that shape so a
    hostile rejection can never be mistaken for a measurement.
    """
    source = _write_rgb(tmp_path / "input.tif")
    _point_next_ifd_at_itself(source)
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    prepare, limits = _entrypoint_prepare(source, operation="INSPECT")
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
    assert outcome["reason"] in _CLOSED_REASONS
    assert raw == b""


def test_sealed_structure_parser_rejects_non_tiff_magic(tmp_path: Path) -> None:
    """Archive/zip masquerading bytes fail the structure preflight with a typed error."""
    fake_archive = tmp_path / "fake.tif"
    fake_archive.write_bytes(b"PK\x03\x04" + bytes(range(256))[:64])

    with pytest.raises(TiffStructureError):
        parse_sealed_tiff_structure(fake_archive, _envelope())

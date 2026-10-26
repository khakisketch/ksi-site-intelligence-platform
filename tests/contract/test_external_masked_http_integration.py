"""Generated HTTP proof: genuine mask ingress -> inspection -> V3 execution.

Synthetic bytes only (small generated GeoTIFFs, never field/customer data).
Every authority mechanism is the real Core lane, exposed through the new
optional HTTP seam (no store/adapter edits here):

- reconstruction/inspection/WorkArea/AP: real stores sharing one
  coordinator; the AP assessment reaches ADMIT_PROVISIONAL with empty
  evidence, so no V2 numeric result is ever required or created;
- mask ingress/bytes/V3: assembled by the new optional factory
  (``build_masked_quantitative_wiring``) from the actual common stores plus
  one explicit sealed config; activation is fresh synthetic Ed25519 keys plus
  a real purpose-separated ``MASKED_ANALYSIS_V3`` activation verified by the
  real loader on every check (explicitly not production authority);
- inspector + dispatch run worker-side in this test process (labelled as
  such): Core never decodes mask bytes and never runs the inspector;
- the full chain runs over HTTP: declare -> grant -> raw upload ->
  worker inspection lease -> worker bytes fetch -> worker inspect outside
  Core -> Core seal from the authenticated worker report -> bind+issue V3
  from source identity plus mask child -> lease/input/bytes/dispatch/report
  -> AVAILABLE with honest metre/cut/fill/provisional readouts -> journal
  replay.

Owner helpers below are adapted copies from
``test_external_mask_input_genuine_adapters.py`` (that file is not edited or
imported); the HTTP seam, factory, contracts, and schema are the delivery.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.composition.masked_quantitative_graph import (
    MaskedQuantitativeLocalConfig,
    build_masked_quantitative_wiring,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_evidence import ExternalEvidenceStore
from ksi_core.domains.external.ingress.external_evidence_validations import (
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_mask_input_api import (
    build_external_mask_input_router,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionStore,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    PolicyReceiptStatus,
    authorized_policy_body_digest,
)
from ksi_core.domains.external.quantity.external_masked_calculation_api import (
    build_external_masked_calculation_router,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisAssessmentRequestV2,
    AnalysisEpochSelectionV2,
    AnalysisPolicyV2,
    AnalysisRuntimeIdentityV2,
    ExternalRelativeVolumeAnalysisStore,
)
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore, WorkAreaVerdict
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.foundation.leasing import LeaseFence
from ksi_core.identity.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    PolicyStatus,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
)
from ksi_event_contracts.external_masked_api import MaskedDeltaSourceRefV1
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionRuntimeV3,
    masked_execution_runtime_digest,
)
from ksi_event_contracts.external_quantitative_extension_activation import (
    QuantitativeExtensionActivationV1,
)
from ksi_event_contracts.external_reconstruction import (
    ExternalArtifactDeclarationV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
    ExternalReconstructionSubmissionV2,
)
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.site_frame import SiteFrame
from ksi_processing_controller.external_mask_input_inspection import (
    inspect_mask_bytes_v1,
)
from ksi_processing_controller.external_masked_execution_dispatch import (
    MaskedDispatchInputsV3,
    dispatch_masked_execution_v3,
)
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementWatchdogV2,
)
from pyproj import CRS
from rasterio.transform import from_origin

NOW = datetime(2026, 10, 26, tzinfo=UTC)
ORIGIN_X = 200000.0
ORIGIN_Y = 550000.0
NATIVE_TRANSFORM = (1.0, 0.0, ORIGIN_X, 0.0, -1.0, ORIGIN_Y)
ORG = "org-a"
SITE_ID = "site-a"
WORK_AREA_ID = "wa-site-a-0001"
MASK_CHILD = "mask-child-1"
MASK_ARTIFACT = "mask-artifact-1"


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _hex_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _operator(org: str = ORG) -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, org)


def _scoped_operator() -> Principal:
    return Principal(
        "operator-scoped",
        PrincipalKind.OPERATOR,
        Role.ADMIN,
        None,
        ORG,
        allowed_site_ids=frozenset({"site-other"}),
        allowed_work_area_ids=frozenset({"wa-other"}),
    )


def _foreign_operator() -> Principal:
    return Principal("operator-foreign", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-b")


def _designated_worker() -> Principal:
    return Principal("masked-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, ORG)


def _wrong_worker() -> Principal:
    return Principal("masked-worker-2", PrincipalKind.ANALYSIS_WORKER, None, None, ORG)


def _processing_worker() -> Principal:
    return Principal("processing-worker-1", PrincipalKind.PROCESSING_WORKER, None, None, ORG)


def _mcp_client() -> Principal:
    return Principal(
        "mcp-1",
        PrincipalKind.ANALYSIS_MCP_CLIENT,
        None,
        None,
        ORG,
        allowed_site_ids=frozenset({SITE_ID}),
        allowed_work_area_ids=frozenset({WORK_AREA_ID}),
    )


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=8000000,
        max_streamed_bytes=8000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=8000000,
        max_geometry_vertices=64,
        max_cpu_seconds=60.0,
        max_memory_bytes=100000000,
        max_workspace_bytes=100000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=3600.0,
        lease_duration_seconds=600.0,
        max_retry_attempts=2,
    ).sealed()


def _polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [ORIGIN_X, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y],
            ]
        ],
    }


def _subject_for(revision: Any) -> SealedExternalSubjectV1:
    submission = revision.submission
    manifest = revision.manifest
    assert manifest is not None
    return SealedExternalSubjectV1(
        organization_id=submission.organization_id,
        site_id=submission.site_id,
        work_order_id=revision.work_order_id,
        submission_id=submission.submission_id,
        revision=submission.revision,
        submission_digest=submission.submission_digest,
        manifest_digest=manifest.manifest_digest,
    )


class _FsObservationPort:
    """Real filesystem observation port for sealed reconstruction bytes."""

    label = "genuine-fs-observation"

    def __init__(self, root: Path) -> None:
        self._root = root

    def observe_object(self, object_key: str) -> Any:
        from ksi_core.domains.artifacts.evidence import ObjectStorageObservation

        target = (self._root / object_key).resolve()
        root = self._root.resolve()
        if target != root and root not in target.parents:
            raise ValueError("object key escapes the observation root")
        if not target.is_file():
            return ObjectStorageObservation(
                object_key=object_key,
                exists=False,
                size_bytes=None,
                sha256=None,
                content_type=None,
            )
        data = target.read_bytes()
        return ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            content_type="application/octet-stream",
        )


class _TestPolicyAuthority(PolicyAuthorityPort):
    """Test-only DSM-lane policy authority (mirrors the repo fixture pattern)."""

    label = "synthetic-test-only-dsm-lane-authority"

    def __init__(self, *records: PolicyAuthorityRecord) -> None:
        self._records = {record.digest: record for record in records}
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _TestPolicyAuthority:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> Any | None:
        del now
        return self._records.get(authority_record_digest)

    def resolve_historical(self, authority_record_digest: str, at: datetime) -> Any | None:
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(at) else None

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return (
            authority.digest is not None
            and self._records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


def _inspection_policy(
    envelope: ResourceEnvelopeV1,
    permitted: tuple[SealedExternalSubjectV1, ...],
) -> tuple[ExternalValidationPolicyV1, _TestPolicyAuthority]:
    template = ExternalValidationPolicyV1(
        contract_version="external-validation-policy.v1",
        policy_id="dsm-inspection-test-v1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("dsm-inspector-build-test"),
        grammar_digest=_digest("dsm-grammar-test"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.canonical_digest(),
        authority_record_digest=_digest("placeholder-authority"),
        inspection_rule_ids=("INSPECT_DSM",),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=permitted,
        permitted_uses=("INSPECTION",),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=5),
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None},
        deep=True,
    ).sealed()
    return policy, _TestPolicyAuthority(authority)


def _write_dsm(path: Path, values: Any, *, nodata: float | None = None) -> bytes:
    transform = from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0)
    compound = CRS.from_user_input("EPSG:5186+5773")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=compound,
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)
    return path.read_bytes()


def _work_order(label: str, cycle: int) -> ObservationWorkOrder:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id as _epoch

    order = ObservationWorkOrder(
        work_order_id=f"order-{label}",
        organization_id=ORG,
        site_id=SITE_ID,
        name=f"order {label}",
        work_area_ids=[WORK_AREA_ID],
        status=ObservationWorkOrderStatus.COMPLETED,
        version=1,
        cycle_number=cycle,
        created_at="2026-09-18T00:00:00Z",
        updated_at="2026-09-18T00:00:00Z",
        created_by="operator-a",
    )
    assert _epoch(order).startswith("obs-epoch-")
    return order


def _submission(
    order: ObservationWorkOrder,
    submission_id: str,
    artifact_id: str,
    data: bytes,
    file_name: str,
    capture_start: datetime,
    capture_end: datetime,
) -> ExternalReconstructionSubmissionV2:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    return ExternalReconstructionSubmissionV2(
        submission_id=submission_id,
        revision=1,
        organization_id=ORG,
        site_id=SITE_ID,
        observation_epoch_id=observation_epoch_id(order),
        submitted_at=NOW,
        submitted_by="operator-a",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="test-producer",
            software_version="0.0.1",
            build_identifier=None,
            producer_run_identifier=None,
            configuration_digest=_digest("producer-config"),
            completed_at=capture_end,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=None,
            image_count=4,
            capture_started_at=capture_start,
            capture_ended_at=capture_end,
        ),
        artifacts=(
            ExternalArtifactDeclarationV1(
                artifact_id=artifact_id,
                kind=ProcessingArtifactKind.DSM,
                file_name=file_name,
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256=_hex_digest(data),
                declared_size_bytes=len(data),
                declared_crs="EPSG:5186",
                declared_vertical_reference=None,
                declared_gsd_m=1.0,
            ),
        ),
    ).sealed()


def _raster_measurements(path: Path) -> RasterMeasurementsV1:
    import math as _math

    with rasterio.open(path, "r", driver="GTiff") as dataset:
        transform = dataset.transform
        width, height = dataset.width, dataset.height
        dtype = dataset.dtypes[0]
        nodata = dataset.nodata
        embedded = CRS.from_user_input(dataset.crs.to_wkt())
        assert embedded.is_compound
        horizontal = next(c for c in embedded.sub_crs_list if c.is_projected or c.is_geographic)
        vertical = next(c for c in embedded.sub_crs_list if c.is_vertical)
        code = horizontal.to_epsg()
        assert code is not None
        resolved = CRS.from_epsg(code)
        assert horizontal.equals(resolved)
        wkt = resolved.to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
        vertical_name = CRS.from_epsg(int(str(vertical.to_epsg()))).name
    with rasterio.open(path, "r", driver="GTiff") as dataset:
        raw = dataset.read(1, masked=False)
        valid_count = int(np.count_nonzero(np.isfinite(raw)))
    corners = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    points = []
    for column, row in corners:
        x = transform.a * column + transform.b * row + transform.c
        y = transform.d * column + transform.e * row + transform.f
        assert _math.isfinite(x) and _math.isfinite(y)
        points.append(f"{x} {y}")
    footprint = "POLYGON ((" + ", ".join(points) + "))"
    if nodata is None:
        representation = NodataRepresentation.NONE
        nodata_value = None
    elif isinstance(nodata, float) and _math.isnan(nodata):
        representation = NodataRepresentation.NAN
        nodata_value = None
    else:
        representation = NodataRepresentation.FINITE
        nodata_value = float(nodata)
    return RasterMeasurementsV1(
        observed_crs_identifier=f"EPSG:{code}",
        observed_crs_wkt=wkt,
        observed_crs_digest="sha256:" + hashlib.sha256(wkt.encode()).hexdigest(),
        observed_vertical_reference=ObservedVerticalReferenceV1(
            identifier=f"EPSG:{vertical.to_epsg()}",
            basis=vertical_name,
        ),
        transform=(transform.a, transform.b, transform.c, transform.d, transform.e, transform.f),
        footprint_wkt=footprint,
        footprint_digest="sha256:" + hashlib.sha256(footprint.encode()).hexdigest(),
        width=width,
        height=height,
        band_count=1,
        dtype=dtype,
        layout="GEOTIFF_STRIPED_V1",
        nodata_representation=representation,
        nodata_value=nodata_value,
        valid_pixel_count=valid_count,
    )


def _seal_epoch(
    reconstruction: ExternalReconstructionStore,
    storage: _FsObservationPort,
    order: ObservationWorkOrder,
    submission: ExternalReconstructionSubmissionV2,
) -> Any:
    registered = reconstruction.register(
        submission, work_order=order, registered_by="operator-a", now=NOW
    )
    assert registered.verdict.value == "REGISTERED", registered.detail
    revision = registered.revision
    assert revision is not None
    for _artifact_id, object_key in revision.bindings:
        target = storage._root / object_key  # noqa: SLF001 - test places real bytes
        target.parent.mkdir(parents=True, exist_ok=True)
    return revision


def _masked_profile() -> Any:
    from ksi_event_contracts.external_masked_volume import (
        MaskedRelativeVolumeProfileV3,
    )

    return MaskedRelativeVolumeProfileV3(
        policy_id="masked-relative-volume-v3",
        version=3,
        profile_id="KSI-GIS-MASKED-RELATIVE-VOLUME-V3",
        profile_digest=_digest("masked-profile"),
        algorithm_digest=_digest("masked-algorithm"),
        config_digest=_digest("masked-config"),
        baseline_grid_rule="EXACT_BASELINE_GRID",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        exclusion_precedence="WORKAREA_HOLES_THEN_MASK",
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def _mask_inspection_profile(envelope: ResourceEnvelopeV1) -> MaskInspectionProfileV1:
    return MaskInspectionProfileV1(
        profile_id="KSI-MASK-INSPECTION-V1",
        version=1,
        contained_protocol="CONTAINED_MASK_INSPECTION_V1",
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("mask-oci"),
        worker_executable_digest=_digest("mask-exe"),
        worker_build_digest=_digest("mask-build"),
        dependency_lock_digest=_digest("mask-lock"),
        mask_grammar_digest=_digest("mask-grammar-v1"),
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        resource_envelope_digest=envelope.canonical_digest(),
    ).sealed()


def _execution_runtime() -> MaskedExecutionRuntimeV3:
    return MaskedExecutionRuntimeV3(
        contract_version="external-masked-execution-runtime.v3",
        worker_executable_digest=_digest("masked-worker-exe"),
        worker_build_digest=_digest("masked-worker-build"),
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("masked-worker-oci"),
        dependency_lock_digest=_digest("masked-worker-lock"),
    ).sealed()


def _mint_extension_activation(
    root: Path,
    *,
    organization_id: str,
    policy_digest: str,
    runtime_digest: str,
    envelope_digest: str,
    worker: Principal,
    now: datetime,
    valid_hours: float = 1.0,
) -> tuple[Path, Path]:
    """Temporary synthetic keys + real MASKED_ANALYSIS_V3 activation (test-only)."""

    signing_key = Ed25519PrivateKey.generate()
    unsigned = {
        "version": 1,
        "activationId": "activation-masked-1",
        "organizationId": organization_id,
        "purpose": "MASKED_ANALYSIS_V3",
        "policyDigest": policy_digest,
        "runtimeDigest": runtime_digest,
        "resourceEnvelopeDigest": envelope_digest,
        "workerPrincipalId": worker.principal_id,
        "issuedAt": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "validUntil": (now + timedelta(hours=valid_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keyId": "quantitative-extension-key-1",
    }
    model = QuantitativeExtensionActivationV1.model_validate(
        {**unsigned, "signature": base64.b64encode(b"x" * 64).decode("ascii")}
    )
    signature = base64.b64encode(signing_key.sign(model.signing_bytes())).decode("ascii")
    activation = QuantitativeExtensionActivationV1.model_validate(
        {**unsigned, "signature": signature}
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    activation_path = root / "quantitative-extension-activation.json"
    activation_path.write_text(json.dumps(activation.model_dump(by_alias=True, mode="json")))
    activation_path.chmod(0o600)
    public = signing_key.public_key()
    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path = root / "quantitative-extension-key-1.public.pem"
    public_path.write_bytes(public_pem)
    public_path.chmod(0o600)
    registry = {
        "version": "quantitative-extension-activation-key-registry.v1",
        "keys": [
            {
                "keyId": "quantitative-extension-key-1",
                "role": "QUANTITATIVE_EXTENSION_ACTIVATION_VERIFY",
                "algorithm": "Ed25519",
                "status": "ACTIVE",
                "publicKeyFile": "quantitative-extension-key-1.public.pem",
                "notBefore": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "notAfter": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ],
    }
    registry_path = root / "quantitative-extension-activation-keys.json"
    registry_path.write_text(json.dumps(registry))
    registry_path.chmod(0o600)
    return activation_path, registry_path


class _TestDsmByteReader:
    """Test DSM resolution: exact sealed files, never invented bytes."""

    def __init__(self) -> None:
        self._files: dict[str, Path] = {}

    def register(self, artifact_id: str, path: Path) -> None:
        self._files[artifact_id] = path

    def read_slice(
        self,
        *,
        organization_id: str,
        site_id: str,
        artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        offset: int,
        length: int,
    ) -> bytes | None:
        _ = (organization_id, site_id)
        path = self._files.get(artifact_id)
        if path is None or not path.is_file():
            return None
        data = path.read_bytes()
        if len(data) != observed_size_bytes or _digest(data) != observed_sha256:
            return None
        if offset < 0 or length <= 0 or offset + length > len(data):
            return None
        return data[offset : offset + length]


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _write_mask(path: Path, values: Any, *, nodata: Any = None) -> bytes:
    transform = from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0)
    extra: dict[str, Any] = {} if nodata is None else {"nodata": nodata}
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
        **extra,
    ) as dataset:
        dataset.write(values, 1)
    return path.read_bytes()


def _build_lane(
    tmp_path: Path, clock: _Clock, *, activation_valid_hours: float = 1.0
) -> dict[str, Any]:
    """Assemble the genuine Core stack plus the new optional masked lane."""
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    envelope = _envelope()
    storage_root = tmp_path / "objects"
    storage_root.mkdir(parents=True, exist_ok=True)
    storage = _FsObservationPort(storage_root)
    journals = lambda name: DurableJournal(tmp_path / name)  # noqa: E731

    sites = SiteStore(journals("sites.jsonl"), coordinator=coordinator)
    registered_site = sites.register(
        SITE_ID,
        "Site A",
        SiteFrame(
            crs="EPSG:5186",
            vertical_datum="EGM96 height",
            unit="meter",
            transform_version="c3-v1",
        ),
        organization_id=ORG,
        actor="operator-a",
        now=NOW,
    )
    assert registered_site.record is not None
    work_areas = WorkAreaStore(
        journals("work-areas.jsonl"),
        site_exists=lambda sid: sites.get(sid) is not None,
        coordinator=coordinator,
    )
    area_result = work_areas.register(
        SITE_ID,
        name="area-a",
        polygon=_polygon(),
        crs="EPSG:5186",
        supersedes=None,
        now=NOW,
        actor="operator-a",
    )
    assert area_result.verdict == WorkAreaVerdict.REGISTERED
    assert area_result.work_area is not None
    assert area_result.work_area.work_area_id == WORK_AREA_ID

    reconstruction = ExternalReconstructionStore(
        journals("reconstruction.jsonl"), coordinator=coordinator
    )
    baseline_values = np.full((4, 4), 100.0)
    diff = np.zeros((4, 4), dtype=np.float64)
    diff[0, 1] = 1.0
    diff[1, 0] = 1.0
    diff[1, 1] = 1.0
    diff[2, 2] = -2.0
    current_values = baseline_values + diff
    mask_values = np.zeros((4, 4), dtype=np.uint8)
    mask_values[0, 1] = 1
    baseline_bytes = _write_dsm(tmp_path / "baseline.tif", baseline_values)
    current_bytes = _write_dsm(tmp_path / "current.tif", current_values)
    mask_bytes = _write_mask(tmp_path / "mask.tif", mask_values)

    baseline_order, current_order = _work_order("baseline", 1), _work_order("current", 2)
    baseline_submission = _submission(
        baseline_order,
        "submission-baseline",
        "dsm-baseline",
        baseline_bytes,
        "baseline.tif",
        datetime(2026, 9, 19, tzinfo=UTC),
        datetime(2026, 9, 19, 1, tzinfo=UTC),
    )
    current_submission = _submission(
        current_order,
        "submission-current",
        "dsm-current",
        current_bytes,
        "current.tif",
        datetime(2026, 9, 20, tzinfo=UTC),
        datetime(2026, 9, 20, 1, tzinfo=UTC),
    )
    baseline_revision = _seal_epoch(reconstruction, storage, baseline_order, baseline_submission)
    current_revision = _seal_epoch(reconstruction, storage, current_order, current_submission)
    for revision, data in ((baseline_revision, baseline_bytes), (current_revision, current_bytes)):
        for _artifact_id, object_key in revision.bindings:
            target = storage_root / object_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    sealed_baseline = reconstruction.seal(
        baseline_order.work_order_id,
        "submission-baseline",
        1,
        organization_id=ORG,
        site_id=SITE_ID,
        storage=storage,
        now=NOW,
    )
    sealed_current = reconstruction.seal(
        current_order.work_order_id,
        "submission-current",
        1,
        organization_id=ORG,
        site_id=SITE_ID,
        storage=storage,
        now=NOW,
    )
    assert sealed_baseline.verdict.value == "SEALED"
    assert sealed_current.verdict.value == "SEALED"
    baseline_subject = _subject_for(sealed_baseline.revision)
    current_subject = _subject_for(sealed_current.revision)

    policy, policy_authority = _inspection_policy(envelope, (baseline_subject, current_subject))
    policy_registry = ExternalValidationPolicyRegistry(
        journals("policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    receipt = policy_registry.admit(policy, actor="authority", now=NOW)
    assert receipt.status == PolicyReceiptStatus.ADMITTED
    inspections = ExternalArtifactInspectionStore(
        journals("inspection.jsonl"),
        policy_registry=policy_registry,
        external_reconstruction=reconstruction,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    baseline_measurements = _raster_measurements(tmp_path / "baseline.tif")
    current_measurements = _raster_measurements(tmp_path / "current.tif")
    for subject, artifact_id, sha_hex, measurements in (
        (baseline_subject, "dsm-baseline", _hex_digest(baseline_bytes), baseline_measurements),
        (current_subject, "dsm-current", _hex_digest(current_bytes), current_measurements),
    ):
        issued = inspections.issue_after_seal(subject, NOW)
        assert issued.verdict.value == "ISSUED"
        assert issued.request is not None
        fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
        claimed = inspections.claim(issued.request.request_id, fence, NOW, organization_id=ORG)
        assert claimed.verdict.value == "LEASED"
        assert claimed.fence is not None
        payload = ExternalInspectionMeasurementPayloadV1(
            subject_digest=subject.canonical_digest(),
            sealed_manifest_digest=subject.manifest_digest,
            inspection_policy_digest=policy.canonical_digest(),
            inspector_build_digest=policy.parser_build_digest,
            artifact_bindings=(
                SealedArtifactBindingV1(
                    artifact_id=artifact_id, observed_sha256="sha256:" + sha_hex
                ),
            ),
            outcomes=(
                ArtifactInspectionOutcomeV1(
                    artifact_id=artifact_id,
                    observed_sha256="sha256:" + sha_hex,
                    outcome=ArtifactOutcome.MEASURED,
                    measurements=measurements,
                ),
            ),
        )
        report = ExternalArtifactInspectionReportV1(
            report_id=f"report-{artifact_id}",
            request_id=issued.request.request_id,
            subject=subject,
            subject_digest=subject.canonical_digest(),
            sealed_manifest_digest=subject.manifest_digest,
            inspection_policy_digest=policy.canonical_digest(),
            inspector_build_digest=policy.parser_build_digest,
            measurement_payload=payload,
            measurement_payload_digest=payload.canonical_digest(),
            worker_instance_id=claimed.fence.worker_instance_id,
            lease_acquisition_id=claimed.fence.lease_acquisition_id,
            lease_generation=claimed.fence.lease_generation,
            reported_at=NOW,
        ).sealed()
        recorded = inspections.record_report(
            issued.request.request_id, claimed.fence, report, NOW, organization_id=ORG
        )
        assert recorded.verdict.value == "REPORTED"

    evidence = ExternalEvidenceStore(
        journals("evidence.jsonl"), clock=lambda: NOW, coordinator=coordinator
    )
    validations = ExternalEvidenceValidationStore(
        journals("validations.jsonl"),
        evidence=evidence,
        policy_registry=ExternalValidationPolicyRegistry(
            journals("validation-policy.jsonl"), clock=lambda: NOW, coordinator=coordinator
        ),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    ap_policy = AnalysisPolicyV2(
        policy_id="relative-volume-v2",
        version=2,
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
    ap_runtime = AnalysisRuntimeIdentityV2(
        worker_executable_digest=_digest("ap-worker"),
        worker_build_digest=_digest("ap-build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("ap-oci"),
        dependency_lock_digest=_digest("ap-lock"),
    )
    assessments = ExternalRelativeVolumeAnalysisStore(
        journals("ap.jsonl"),
        reconstruction=reconstruction,
        inspections=inspections,
        work_areas=work_areas,
        evidence=evidence,
        validations=validations,
        policy=ap_policy,
        runtime=ap_runtime,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    ap_record = assessments.assess_and_record(
        principal=_operator(),
        request=AnalysisAssessmentRequestV2(
            request_id="ap-request-1",
            work_area_id=WORK_AREA_ID,
            baseline=AnalysisEpochSelectionV2(subject=baseline_subject),
            current=AnalysisEpochSelectionV2(subject=current_subject),
            idempotency_key="ap-idem-1",
        ),
        now=NOW,
    )
    assert ap_record.admission.disposition.value == "ADMIT_PROVISIONAL"
    source_digest = ap_record.admission.calculation_identity_digest
    assert source_digest is not None

    masked_profile = _masked_profile()
    execution_runtime = _execution_runtime()
    mask_profile = _mask_inspection_profile(envelope)
    lane_runtime_digest = masked_execution_runtime_digest(
        execution_runtime,
        masked_profile.canonical_digest(),
        envelope.canonical_digest(),
        mask_profile.canonical_digest(),
    )
    activation_paths = _mint_extension_activation(
        tmp_path / "activation",
        organization_id=ORG,
        policy_digest=masked_profile.canonical_digest(),
        runtime_digest=lane_runtime_digest,
        envelope_digest=envelope.canonical_digest(),
        worker=_designated_worker(),
        now=NOW,
        valid_hours=activation_valid_hours,
    )
    config = MaskedQuantitativeLocalConfig(
        masked_profile=masked_profile,
        inspection_profile=mask_profile,
        execution_runtime=execution_runtime,
        resource_envelope=envelope,
        worker_principal=_designated_worker(),
        activation_path=activation_paths[0],
        verification_keys_path=activation_paths[1],
        bytes_root=tmp_path / "mask-bytes",
        clock=clock,
    )
    wiring = build_masked_quantitative_wiring(
        journal=journals,
        config=config,
        assessments=assessments,
        sites=sites,
        reconstruction=reconstruction,
        inspections=inspections,
        work_areas=work_areas,
        coordinator=coordinator,
        dsm_byte_reader=_TestDsmByteReader(),
    )
    dsm_reader = wiring.dsm_byte_reader
    assert dsm_reader is not None
    dsm_reader.register("dsm-baseline", tmp_path / "baseline.tif")
    dsm_reader.register("dsm-current", tmp_path / "current.tif")
    return {
        "tmp_path": tmp_path,
        "clock": clock,
        "envelope": envelope,
        "coordinator": coordinator,
        "wiring": wiring,
        "dsm_reader": dsm_reader,
        "baseline_subject": baseline_subject,
        "current_subject": current_subject,
        "source_digest": source_digest,
        "masked_profile": masked_profile,
        "mask_profile": mask_profile,
        "execution_runtime": execution_runtime,
        "mask_bytes": mask_bytes,
        "baseline_bytes": baseline_bytes,
        "current_bytes": current_bytes,
        "journals": {
            "mask_child": tmp_path / "external-mask-child.jsonl",
            "masked_calc": tmp_path / "external-masked-calculations.jsonl",
            "inspection": tmp_path / "external-mask-inspection-jobs.jsonl",
        },
        "stores": {
            "reconstruction": reconstruction,
            "sites": sites,
            "work_areas": work_areas,
            "inspections": inspections,
            "assessments": assessments,
            "evidence": evidence,
            "validations": validations,
            "policy_registry": policy_registry,
            "ap_policy": ap_policy,
            "ap_runtime": ap_runtime,
        },
    }


def _journal_length(path: Path) -> int:
    return len(DurableJournal.open_read_only(path).replay()) if path.exists() else 0


def _tokens() -> dict[str, Principal]:
    return {
        "operator": _operator(),
        "scoped": _scoped_operator(),
        "foreign": _foreign_operator(),
        "worker": _designated_worker(),
        "wrong-worker": _wrong_worker(),
        "processing": _processing_worker(),
        "mcp": _mcp_client(),
    }


def _scoped_designated_worker() -> Principal:
    """Same designated identity, narrowed site/area grants (scope probe)."""
    return Principal(
        "masked-worker-1",
        PrincipalKind.ANALYSIS_WORKER,
        None,
        None,
        ORG,
        allowed_site_ids=frozenset({"site-other"}),
        allowed_work_area_ids=frozenset({"wa-other"}),
    )


def _client(
    lane: dict[str, Any],
    principals: dict[str, Principal] | None = None,
    queued: Any | None = None,
) -> TestClient:
    wiring = lane["wiring"]
    if principals is None:
        principals = _tokens()
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            tuple(
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(("synthetic-" + name).encode()).hexdigest(),
                    principal=principal,
                )
                for name, principal in principals.items()
            )
        ),
    )
    app.include_router(
        build_external_mask_input_router(
            ingress=wiring.ingress,
            byte_store=wiring.byte_store,
            inspection_journal=wiring.inspection_journal,
            resource_envelope=lane["envelope"],
            designated_worker=_designated_worker(),
            lane_source=wiring.source_context,
            clock=lane["clock"],
        )
    )
    app.include_router(
        build_external_masked_calculation_router(
            calculations=wiring.calculations,
            evidence=wiring.evidence,
            mask_bytes=wiring.mask_bytes,
            resource_envelope=lane["envelope"],
            designated_worker=_designated_worker(),
            dsm_byte_reader=wiring.dsm_byte_reader,
            queued=queued,
            clock=lane["clock"],
        )
    )
    return TestClient(app)


def _headers(role: str = "operator", **extra: str) -> dict[str, str]:
    return {"Authorization": "Bearer synthetic-" + role, **extra}


MASK_BASE = f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-children"
CALC_BASE = f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/masked-calculations"


def _declare_body(lane: dict[str, Any]) -> dict[str, Any]:
    return _declare_child_body(
        lane,
        child_id=MASK_CHILD,
        artifact_id=MASK_ARTIFACT,
        data=lane["mask_bytes"],
        declaration_id="decl-1",
    )


def _declare_child_body(
    lane: dict[str, Any],
    *,
    child_id: str,
    artifact_id: str,
    data: bytes,
    declaration_id: str,
) -> dict[str, Any]:
    declaration = MaskChildDeclarationV1(
        declaration_id=declaration_id,
        organization_id=ORG,
        site_id=SITE_ID,
        work_area_id=WORK_AREA_ID,
        child_kind="MASK_CHILD",
        mask_child_id=child_id,
        mask_artifact_id=artifact_id,
        parent_subject=lane["current_subject"],
        target_baseline_subject=lane["baseline_subject"],
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest(data),
        declared_size_bytes=len(data),
    ).sealed()
    return declaration.model_dump(by_alias=True, mode="json")


def _http_lease_and_inspect(
    client: TestClient,
    lane: dict[str, Any],
    tmp_path: Path,
    *,
    child: str = MASK_CHILD,
    artifact: str = MASK_ARTIFACT,
    instance: str = "masked-inspector-1",
    acquisition: str = "inspect-lease-1",
    report_id: str = "narrow-report-1",
    reported_at: datetime | None = None,
    data: bytes | None = None,
) -> tuple[str, dict[str, Any]]:
    """Worker lease -> bytes -> outside-Core inspect. Returns (lease_id, report)."""
    envelope = lane["envelope"]
    payload = lane["mask_bytes"] if data is None else data
    lease_body = {
        "siteId": SITE_ID,
        "workAreaId": WORK_AREA_ID,
        "maskArtifactId": artifact,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
        "baselineDsmArtifactId": "dsm-baseline",
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": instance,
        "leaseAcquisitionId": acquisition,
    }
    leased = client.post(
        f"/v1/internal/mask-children/{child}/inspection-lease",
        headers=_headers("worker"),
        json=lease_body,
    )
    assert leased.status_code == 200, leased.text
    lease_view = leased.json()
    fetched = bytearray()
    offset = 0
    total = len(payload)
    while offset < total:
        window = client.get(
            f"/v1/internal/mask-children/{child}/bytes",
            headers=_headers("worker"),
            params={
                "mask_artifact_id": artifact,
                "offset": offset,
                "length": min(1024 * 1024, total - offset),
                "lease_id": lease_view["leaseId"],
                "worker_instance_id": instance,
            },
        )
        assert window.status_code == 200, window.text
        chunk = base64.b64decode(window.json()["contentBase64"])
        fetched.extend(chunk)
        offset += len(chunk)
    assert bytes(fetched) == payload
    worker_mask_path = tmp_path / f"{child}-http.tif"
    worker_mask_path.write_bytes(bytes(fetched))
    narrow_report = inspect_mask_bytes_v1(
        path=worker_mask_path,
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        organization_id=ORG,
        site_id=SITE_ID,
        work_area_id=WORK_AREA_ID,
        mask_child_id=child,
        mask_artifact_id=artifact,
        subject=lane["current_subject"],
        inspection_profile=lane["mask_profile"],
        contained_runtime_digest=__import__(
            "ksi_core.domains.external.ingress.external_mask_input_core_adapters",
            fromlist=["masked_inspection_runtime_digest"],
        ).masked_inspection_runtime_digest(lane["mask_profile"]),
        inspector_build_digest=lane["mask_profile"].worker_build_digest,
        expected_crs_identifier=lease_view["expectedCrsIdentifier"],
        expected_crs_digest=lease_view["expectedCrsDigest"],
        expected_transform=tuple(lease_view["expectedTransform"]),
        expected_transform_digest=lease_view["expectedTransformDigest"],
        report_id=report_id,
        reported_at=lane["clock"]() if reported_at is None else reported_at,
    )
    return lease_view["leaseId"], narrow_report.model_dump(by_alias=True, mode="json")


def _http_seal_child(
    client: TestClient,
    lane: dict[str, Any],
    tmp_path: Path,
    *,
    child: str = MASK_CHILD,
    artifact: str = MASK_ARTIFACT,
    instance: str = "masked-inspector-1",
    acquisition: str = "inspect-lease-1",
    report_id: str = "narrow-report-1",
) -> dict[str, Any]:
    """Worker lease -> bytes -> outside-Core inspect -> Core seal. Returns manifest."""
    lease_id, report = _http_lease_and_inspect(
        client,
        lane,
        tmp_path,
        child=child,
        artifact=artifact,
        instance=instance,
        acquisition=acquisition,
        report_id=report_id,
    )
    sealed = client.post(
        f"/v1/internal/mask-children/{child}:report",
        headers=_headers("worker"),
        json={
            "leaseId": lease_id,
            "workerInstanceId": instance,
            "report": report,
            "inspectionProfile": lane["mask_profile"].model_dump(by_alias=True, mode="json"),
        },
    )
    assert sealed.status_code == 200, sealed.text
    return sealed.json()["manifest"]


def _http_create(
    client: TestClient,
    lane: dict[str, Any],
    *,
    masked_calculation_id: str,
    request_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    created = client.post(
        CALC_BASE,
        headers=_headers(),
        json={
            "maskedCalculationId": masked_calculation_id,
            "sourceCalculationIdentityDigest": lane["source_digest"],
            "maskChildId": MASK_CHILD,
            "requestId": request_id,
            "idempotencyKey": idempotency_key,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def test_masked_http_full_chain_proves_genuine(tmp_path: Path) -> None:
    """End-to-end HTTP proof over genuine stores, bytes, keys, and replay."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    envelope = lane["envelope"]
    mask_bytes = lane["mask_bytes"]

    declared = client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane))
    assert declared.status_code == 200, declared.text
    assert declared.json()["manifest"] is None
    assert "://" not in declared.text and "objectKey" not in declared.text

    seen = client.get(f"{MASK_BASE}/{MASK_CHILD}", headers=_headers())
    assert seen.status_code == 200 and seen.json()["manifest"] is None

    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(mask_bytes),
            "declaredSizeBytes": len(mask_bytes),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    grant_id = grant.json()["grantId"]
    assert "://" not in grant.text and "objectKey" not in grant.text
    assert "path" not in grant.text.lower()

    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant_id}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=mask_bytes,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["observedSha256"] == _digest(mask_bytes)

    manifest = _http_seal_child(client, lane, tmp_path)
    assert manifest["observedSha256"] == _digest(mask_bytes)
    assert (manifest["rows"], manifest["columns"]) == (4, 4)
    assert manifest["dtype"] == "UINT8" and manifest["nodataRepresentation"] == "NONE"

    created = _http_create(
        client,
        lane,
        masked_calculation_id="masked-calculation-1",
        request_id="masked-request-1",
        idempotency_key="masked-idem-1",
    )
    admission = created["admission"]
    assert admission["disposition"] == "ADMIT_PROVISIONAL"
    assert "MASK_ADMITTED" in admission["reasonCodes"]
    assert any(code.startswith("CHECKPOINT_") for code in admission["reasonCodes"])
    masked_digest = created["maskedCalculationIdentityDigest"]

    # An unresolvable source never binds: uniform 404, journal untouched.
    calc_len_before = _journal_length(lane["journals"]["masked_calc"])
    assert (
        client.post(
            CALC_BASE,
            headers=_headers(),
            json={
                "maskedCalculationId": "masked-calculation-9",
                "sourceCalculationIdentityDigest": _digest("unknown-source"),
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-9",
                "idempotencyKey": "masked-idem-9",
            },
        ).status_code
        == 404
    )
    assert _journal_length(lane["journals"]["masked_calc"]) == calc_len_before

    clock.now = NOW + timedelta(seconds=200)
    calc_leased = client.post(
        "/v1/internal/masked-calculations/masked-request-1:lease",
        headers=_headers("worker"),
        json={"workerInstanceId": "masked-worker-instance-1", "leaseAcquisitionId": "lease-1"},
    )
    assert calc_leased.status_code == 200, calc_leased.text
    attempt = calc_leased.json()["attempt"]
    fence_headers = _headers(
        "worker",
        **{
            "X-Masked-Attempt-Digest": attempt["executionAttemptDigest"],
            "X-Masked-Worker-Instance-Id": "masked-worker-instance-1",
        },
    )
    worker_input = client.get(
        "/v1/internal/masked-calculations/masked-request-1/input", headers=fence_headers
    )
    assert worker_input.status_code == 200, worker_input.text
    assert [item["role"] for item in worker_input.json()["inputs"]] == [
        "BASELINE_DSM",
        "CURRENT_DSM",
        "EXCLUSION_MASK",
    ]
    assert "downloadUrl" not in worker_input.text and "://" not in worker_input.text

    staged: dict[str, Path] = {}
    for role in ("BASELINE_DSM", "CURRENT_DSM", "EXCLUSION_MASK"):
        capability = next(item for item in worker_input.json()["inputs"] if item["role"] == role)
        window = client.get(
            f"/v1/internal/masked-calculations/masked-request-1/inputs/{role}/bytes",
            headers=fence_headers,
            params={"offset": 0, "length": capability["observedSizeBytes"]},
        )
        assert window.status_code == 200, (role, window.text)
        assert b"://" not in window.content
        target = tmp_path / f"worker-{role}.tif"
        target.write_bytes(base64.b64decode(window.json()["contentBase64"]))
        staged[role] = target
        assert _digest(target.read_bytes()) == capability["observedSha256"]

    # Worker side only (labelled): fenced dispatch outside Core.
    outcome = dispatch_masked_execution_v3(
        worker_input=__import__(
            "ksi_event_contracts.external_masked_execution", fromlist=["MaskedWorkerInputV3"]
        ).MaskedWorkerInputV3.model_validate(worker_input.json()),
        files=MaskedDispatchInputsV3(
            baseline_path=staged["BASELINE_DSM"],
            current_path=staged["CURRENT_DSM"],
            mask_path=staged["EXCLUSION_MASK"],
        ),
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        lease_expires_at=datetime.fromisoformat(attempt["leaseExpiresAt"].replace("Z", "+00:00")),
        report_id="report-1",
        computed_at=NOW + timedelta(seconds=260),
        reported_at=NOW + timedelta(seconds=320),
    )
    assert outcome.report is not None, outcome.failure
    numeric = outcome.report.numeric_result
    assert (numeric.metrics.fill_m3, numeric.metrics.cut_m3) == (2.0, 2.0)
    assert numeric.metrics.net_m3 == 0.0

    clock.now = NOW + timedelta(seconds=400)
    stored = client.post(
        "/v1/internal/masked-calculations/masked-request-1:report",
        headers=_headers("worker"),
        json={
            "attempt": attempt,
            "report": outcome.report.model_dump(by_alias=True, mode="json"),
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["status"] == "COMPLETED"

    detail = client.get(f"{CALC_BASE}/masked-request-1", headers=_headers())
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["disposition"] == "AVAILABLE"
    assert body["maskedCalculationIdentityDigest"] == masked_digest
    report = body["report"]
    metrics = report["numericResult"]["metrics"]
    assert (metrics["fillM3"], metrics["cutM3"]) == (2.0, 2.0)
    coverage = report["numericResult"]["coverage"]
    assert coverage["commonValidCellCount"] == coverage["effectiveSelectedCellCount"] == 15
    assert coverage["unavailableCellCount"] == 0
    assert coverage["maskExcludedCellCount"] == 1
    assert report["numericResult"]["impact"]["excludedCellCount"] == 1
    assert body["admission"]["disposition"] == "ADMIT_PROVISIONAL"
    assert "://" not in detail.text

    # A completed attempt never authorizes further raw bytes (no borrowing).
    stale_bytes = client.get(
        "/v1/internal/masked-calculations/masked-request-1/inputs/EXCLUSION_MASK/bytes",
        headers=fence_headers,
        params={"offset": 0, "length": 64},
    )
    assert stale_bytes.status_code == 409

    # Parent delta handoff: source identity plus mask child only; Core
    # resolves the sealed bytes behind no caller grid/profile truth.
    port = lane["wiring"].mask_bytes
    binding_window = port.read_slice_by_binding(
        organization_id=ORG,
        mask_artifact_id=MASK_ARTIFACT,
        observed_sha256=_digest(mask_bytes),
        observed_size_bytes=len(mask_bytes),
        offset=0,
        length=len(mask_bytes),
    )
    assert binding_window == mask_bytes
    with pytest.raises(ValueError):
        port.read_slice_by_binding(
            organization_id=ORG,
            mask_artifact_id=MASK_ARTIFACT,
            observed_sha256=_digest(b"other"),
            observed_size_bytes=len(mask_bytes),
            offset=0,
            length=64,
        )
    handoff = MaskedDeltaSourceRefV1(
        source_calculation_identity_digest=masked_digest,
        source_numeric_result_identity_digest=report["numericResult"][
            "numericResultIdentityDigest"
        ],
        source_coverage_witness_digest=report["numericResult"]["coverage"]["coverageWitnessDigest"],
        mask_child_id=MASK_CHILD,
    )
    assert handoff.mask_child_id == MASK_CHILD

    # Replay: close the masked lane journals, reopen only the masked lane
    # against the still-open common stores, and re-verify through new HTTP.
    lane["wiring"].close()
    second_wiring = build_masked_quantitative_wiring(
        journal=lambda name: DurableJournal(tmp_path / name),
        config=lane["wiring"].config,
        assessments=lane["stores"]["assessments"],
        sites=lane["stores"]["sites"],
        reconstruction=lane["stores"]["reconstruction"],
        inspections=lane["stores"]["inspections"],
        work_areas=lane["stores"]["work_areas"],
        coordinator=lane["coordinator"],
        dsm_byte_reader=lane["dsm_reader"],
    )
    lane["wiring"] = second_wiring
    replay_client = _client(lane)
    replayed_child = replay_client.get(f"{MASK_BASE}/{MASK_CHILD}", headers=_headers())
    assert replayed_child.status_code == 200
    replayed_manifest = replayed_child.json()["manifest"]
    assert replayed_manifest["observedSha256"] == _digest(mask_bytes)
    replayed_detail = replay_client.get(f"{CALC_BASE}/masked-request-1", headers=_headers())
    assert replayed_detail.status_code == 200, replayed_detail.text
    assert replayed_detail.json()["disposition"] == "AVAILABLE"
    assert replayed_detail.json()["report"]["reportDigest"] == report["reportDigest"]


def test_masked_operator_scope_helpers_bind_site_and_area() -> None:
    """Direct unit proof: optional allowlists deny outside grants, pass inside."""
    from ksi_core.domains.external.ingress.external_mask_input_api import operator_scope_allows
    from ksi_core.domains.external.quantity.external_masked_calculation_api import (
        masked_operator_scope_allows,
    )

    for allows in (operator_scope_allows, masked_operator_scope_allows):
        assert allows(_operator(), SITE_ID, WORK_AREA_ID) is True
        assert allows(_scoped_operator(), SITE_ID, WORK_AREA_ID) is False
        assert allows(_scoped_operator(), "site-other", "wa-other") is True
        assert allows(_scoped_operator(), "site-other", WORK_AREA_ID) is False
        assert allows(_scoped_operator(), SITE_ID, "wa-other") is False
        assert allows(_designated_worker(), SITE_ID, WORK_AREA_ID) is False
        assert allows(_mcp_client(), SITE_ID, WORK_AREA_ID) is False


def test_masked_wiring_rejects_substituted_participants(tmp_path: Path) -> None:
    """Mount verification is exact object identity, never digest comparison."""
    from ksi_core.domains.external.ingress.external_artifact_inspections import (
        ExternalArtifactInspectionStore as _Inspections,
    )
    from ksi_core.domains.external.ingress.external_reconstruction import (
        ExternalReconstructionStore as _Recon,
    )
    from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
        ExternalRelativeVolumeAnalysisStore as _Assess,
    )
    from ksi_core.domains.sites.sites import SiteStore as _Sites
    from ksi_core.domains.sites.work_areas import WorkAreaStore as _Areas

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    wiring = lane["wiring"]
    coordinator = lane["coordinator"]
    stores = lane["stores"]
    exact = dict(
        assessments=stores["assessments"],
        sites=stores["sites"],
        reconstruction=stores["reconstruction"],
        inspections=stores["inspections"],
        work_areas=stores["work_areas"],
        coordinator=coordinator,
        dsm_byte_reader=lane["dsm_reader"],
    )
    assert wiring.verify_participants(**exact) is None

    other_coordinator = ExternalAuthorityCurrentnessCoordinator()
    sub_journals: list[DurableJournal] = []

    def journals2(name: str) -> DurableJournal:  # noqa: E731
        handle = DurableJournal(tmp_path / ("sub-" + name))
        sub_journals.append(handle)
        return handle

    recon2 = _Recon(journals2("recon.jsonl"), coordinator=coordinator)
    sites2 = _Sites(journals2("sites.jsonl"), coordinator=coordinator)
    areas2 = _Areas(
        journals2("areas.jsonl"), site_exists=lambda _sid: True, coordinator=coordinator
    )
    insp2 = _Inspections(
        journals2("insp.jsonl"),
        policy_registry=stores["policy_registry"],
        external_reconstruction=stores["reconstruction"],
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    assess2 = _Assess(
        journals2("ap.jsonl"),
        reconstruction=stores["reconstruction"],
        inspections=stores["inspections"],
        work_areas=stores["work_areas"],
        evidence=stores["evidence"],
        validations=stores["validations"],
        policy=stores["ap_policy"],
        runtime=stores["ap_runtime"],
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    for field, other in (
        ("assessments", assess2),
        ("sites", sites2),
        ("reconstruction", recon2),
        ("inspections", insp2),
        ("work_areas", areas2),
    ):
        with pytest.raises(ValueError):
            wiring.verify_participants(**{**exact, field: other})
    with pytest.raises(ValueError):
        wiring.verify_participants(**{**exact, "coordinator": other_coordinator})
    with pytest.raises(ValueError):
        wiring.verify_participants(**{**exact, "dsm_byte_reader": object()})
    for journal in sub_journals:
        journal.close()


def test_masked_wiring_cleans_journals_on_factory_failure(tmp_path: Path) -> None:
    """A failing journal factory closes prior handles; common stores survive."""
    from ksi_core.foundation.durable_journal import JournalSealedError

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    created_names: list[str] = []
    created_objects: list[DurableJournal] = []

    def failing_journal(name: str) -> DurableJournal:
        created_names.append(name)
        if len(created_names) == 3:
            raise RuntimeError("boom-3")
        handle = DurableJournal(tmp_path / ("fail-" + name))
        created_objects.append(handle)
        return handle

    with pytest.raises(RuntimeError, match="boom-3"):
        build_masked_quantitative_wiring(
            journal=failing_journal,
            config=lane["wiring"].config,
            assessments=lane["stores"]["assessments"],
            sites=lane["stores"]["sites"],
            reconstruction=lane["stores"]["reconstruction"],
            inspections=lane["stores"]["inspections"],
            work_areas=lane["stores"]["work_areas"],
            coordinator=lane["coordinator"],
            dsm_byte_reader=lane["dsm_reader"],
        )
    assert created_names == [
        "external-mask-input-bytes.jsonl",
        "external-mask-child.jsonl",
        "external-masked-calculations.jsonl",
    ]
    assert len(created_objects) == 2
    for handle in created_objects:
        with pytest.raises(JournalSealedError):
            handle.append({"kind": "probe"})
    assert lane["stores"]["sites"].get_scoped(SITE_ID, ORG) is not None
    assert lane["stores"]["work_areas"].get(WORK_AREA_ID) is not None
    lane["wiring"].close()
    lane["wiring"].close()


def test_masked_source_context_resolves_sealed_anchor(tmp_path: Path) -> None:
    """Console declaration aid: sealed source copies + explicit caps, no V2 NX."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    child_journal = lane["journals"]["mask_child"]
    calc_journal = lane["journals"]["masked_calc"]
    before_child = _journal_length(child_journal)
    before_calc = _journal_length(calc_journal)

    params = {"source_calculation_identity_digest": lane["source_digest"]}
    context = client.get(
        f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
        headers=_headers(),
        params=params,
    )
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["sourceCalculationIdentityDigest"] == lane["source_digest"]
    assert body["baselineSubject"] == lane["baseline_subject"].model_dump(
        by_alias=True, mode="json"
    )
    assert body["currentSubject"] == lane["current_subject"].model_dump(by_alias=True, mode="json")
    assert body["baselineDsmArtifactId"] == "dsm-baseline"
    assert body["maskedProfileDigest"] == lane["masked_profile"].canonical_digest()
    assert body["inspectionProfileDigest"] == lane["mask_profile"].canonical_digest()
    assert body["maxMaskBytes"] == min(
        lane["envelope"].max_input_bytes, lane["envelope"].max_streamed_bytes
    )
    assert body["maxMaskPixels"] == lane["envelope"].max_pixels
    assert body["sourceDisposition"] == "ADMIT_PROVISIONAL"
    assert body["assessedAt"] is not None
    assert "://" not in context.text

    unknown = client.get(
        f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
        headers=_headers(),
        params={"source_calculation_identity_digest": _digest("unknown-source")},
    )
    assert unknown.status_code == 404
    foreign_path = client.get(
        "/v3/sites/site-other/work-areas/wa-other/mask-source-context",
        headers=_headers(),
        params=params,
    )
    assert foreign_path.status_code == 404
    malformed = client.get(
        f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
        headers=_headers(),
        params={"source_calculation_identity_digest": "not-a-digest"},
    )
    assert malformed.status_code == 422
    assert (
        client.get(
            f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
            headers=_headers("mcp"),
            params=params,
        ).status_code
        == 403
    )
    assert _journal_length(child_journal) == before_child
    assert _journal_length(calc_journal) == before_calc

    clock.now = NOW + timedelta(hours=2)
    expired = client.get(
        f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
        headers=_headers(),
        params=params,
    )
    assert expired.status_code == 404
    clock.now = NOW

    # Activation down while the AP witness is still current: 409, never an
    # invented admission.  A short-activation lane isolates the lane gate
    # from AP staleness (AP policy stays valid a full hour).  The subdir is
    # pre-created private: intermediate mkdir parents would otherwise inherit
    # group-writable modes under a 002 umask and trip the owner private-root
    # check (unrelated to the activation under test).
    short_root = tmp_path / "short-activation"
    short_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    short_clock = _Clock()
    short_lane = _build_lane(short_root, short_clock, activation_valid_hours=0.5)
    short_client = _client(short_lane)
    short_clock.now = NOW + timedelta(minutes=45)
    lane_down = short_client.get(
        f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-source-context",
        headers=_headers(),
        params={"source_calculation_identity_digest": short_lane["source_digest"]},
    )
    assert lane_down.status_code == 409
    assert "MASKED_ACTIVATION_UNAVAILABLE" in lane_down.text


def test_masked_worker_driven_inspection_discovery(tmp_path: Path) -> None:
    """Driver loop without out-of-band IDs: pending -> lease -> bytes -> inspect."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text

    assert (
        client.get("/v1/internal/mask-inspection-jobs/pending", headers=_headers()).status_code
        == 403
    )
    assert (
        client.get("/v1/internal/mask-inspection-jobs/pending", headers=_headers("mcp")).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/internal/mask-inspection-jobs/pending",
            headers=_headers("worker"),
            params={"limit": 51},
        ).status_code
        == 422
    )
    pending = client.get("/v1/internal/mask-inspection-jobs/pending", headers=_headers("worker"))
    assert pending.status_code == 200, pending.text
    items = pending.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["maskChildId"] == MASK_CHILD
    assert item["declaration"]["declaredSha256"] == _digest(lane["mask_bytes"])
    assert (
        item["declaration"]["targetBaselineSubject"]["manifestDigest"]
        == lane["baseline_subject"].manifest_digest
    )

    lease_body = {
        "siteId": item["siteId"],
        "workAreaId": item["workAreaId"],
        "maskArtifactId": MASK_ARTIFACT,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": item["declaration"]["targetBaselineSubject"],
        "baselineDsmArtifactId": item["declaration"]["targetBaselineDsmArtifactId"],
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": "masked-inspector-d",
        "leaseAcquisitionId": "inspect-lease-d",
    }
    leased = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json=lease_body,
    )
    assert leased.status_code == 200, leased.text
    window = client.get(
        f"/v1/internal/mask-children/{MASK_CHILD}/bytes",
        headers=_headers("worker"),
        params={
            "mask_artifact_id": MASK_ARTIFACT,
            "offset": 0,
            "length": len(lane["mask_bytes"]),
            "lease_id": leased.json()["leaseId"],
            "worker_instance_id": "masked-inspector-d",
        },
    )
    assert window.status_code == 200, window.text
    fetched = base64.b64decode(window.json()["contentBase64"])
    assert fetched == lane["mask_bytes"]

    # Worker side only (labelled): contained inspection outside Core.
    worker_path = tmp_path / "mask-driver.tif"
    worker_path.write_bytes(fetched)
    narrow = inspect_mask_bytes_v1(
        path=worker_path,
        envelope=lane["envelope"],
        watchdog=MeasurementWatchdogV2.from_envelope(lane["envelope"]),
        organization_id=ORG,
        site_id=SITE_ID,
        work_area_id=WORK_AREA_ID,
        mask_child_id=MASK_CHILD,
        mask_artifact_id=MASK_ARTIFACT,
        subject=lane["current_subject"],
        inspection_profile=lane["mask_profile"],
        contained_runtime_digest=__import__(
            "ksi_core.domains.external.ingress.external_mask_input_core_adapters",
            fromlist=["masked_inspection_runtime_digest"],
        ).masked_inspection_runtime_digest(lane["mask_profile"]),
        inspector_build_digest=lane["mask_profile"].worker_build_digest,
        expected_crs_identifier=leased.json()["expectedCrsIdentifier"],
        expected_crs_digest=leased.json()["expectedCrsDigest"],
        expected_transform=tuple(leased.json()["expectedTransform"]),
        expected_transform_digest=leased.json()["expectedTransformDigest"],
        report_id="narrow-report-d",
        reported_at=NOW,
    )
    assert narrow.report_digest == narrow.canonical_digest()
    assert narrow.subject_digest == lane["current_subject"].canonical_digest()
    assert narrow.observed_sha256 == _digest(lane["mask_bytes"])

    # Fixture-level seal (genuine operator pattern, not the HTTP worker path):
    # proves the pending filter excludes sealed manifests.
    lane["wiring"].ingress.seal_observed(
        principal=_operator(),
        organization_id=ORG,
        mask_child_id=MASK_CHILD,
        report=narrow,
        inspection_profile=lane["mask_profile"],
        now=NOW,
    )
    again = client.get("/v1/internal/mask-inspection-jobs/pending", headers=_headers("worker"))
    assert again.status_code == 200
    assert again.json()["items"] == []


def _resign_event(event: dict[str, Any]) -> dict[str, Any]:
    """Recompute a journal digest after mutation (reseal simulation)."""
    resealed = dict(event)
    resealed.pop("eventDigest", None)
    resealed["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(resealed)).hexdigest()
    return resealed


def _read_journal_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _craft_ledger(tmp_path: Path, name: str, events: list[dict[str, Any]]) -> Path:
    path = tmp_path / name
    journal = DurableJournal(path)
    try:
        for event in events:
            journal.append(event)
    finally:
        journal.close()
    return path


def _genuine_announce_and_lease(tmp_path: Path) -> dict[str, Any]:
    """One lane with a declared child plus one live lease, journals closed."""

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text
    leased = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json={
            "siteId": SITE_ID,
            "workAreaId": WORK_AREA_ID,
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
            "baselineDsmArtifactId": "dsm-baseline",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "workerInstanceId": "masked-inspector-1",
            "leaseAcquisitionId": "inspect-lease-1",
        },
    )
    assert leased.status_code == 200, leased.text
    lane["wiring"].close()
    return lane


def test_masked_inspection_fence_rejects_resealed_journals(tmp_path: Path) -> None:
    """Closed journal shape: resealed mutations fail even with a valid digest."""
    from ksi_core.domains.external.ingress.external_mask_input_api import (
        MaskInspectionJobLedger,
        MaskInspectionJobRecoveryError,
    )

    lane = _genuine_announce_and_lease(tmp_path)
    envelope = lane["envelope"]
    genuine = _read_journal_events(tmp_path / "external-mask-inspection-jobs.jsonl")
    assert len(genuine) == 2
    announce = next(e for e in genuine if e["kind"] == "masked-inspection-announced.v1")
    lease = next(e for e in genuine if e["kind"] == "masked-inspection-lease-issued.v1")
    counter = 0

    def replay(events: list[dict[str, Any]]) -> None:
        nonlocal counter
        counter += 1
        path = _craft_ledger(tmp_path, f"resealed-{counter}.jsonl", events)
        with pytest.raises(MaskInspectionJobRecoveryError):
            MaskInspectionJobLedger(DurableJournal(path), resource_envelope=envelope)

    # Unknown boolean version passes a naive `!=` check but is not an int.
    tampered = _resign_event({**lease, "version": True})
    replay([announce, tampered])
    # Unknown fields are rejected even when the digest is recomputed.
    tampered = _resign_event({**lease, "injected": True})
    replay([announce, tampered])
    tampered = _resign_event({**announce, "injected": "x"})
    replay([tampered, lease])
    # Resealed cross-scope lease: organization rewritten.
    tampered = _resign_event({**lease, "organizationId": "org-b"})
    replay([announce, tampered])
    # Resealed naive datetime: UTC awareness is mandatory.
    tampered = _resign_event({**lease, "issuedAt": "2026-10-26T00:00:00"})
    replay([announce, tampered])
    # Resealed overlong lease: expiry must equal issued + envelope duration.
    overlong = datetime.fromisoformat(lease["expiresAt"].replace("Z", "+00:00")) + timedelta(
        seconds=1
    )
    tampered = _resign_event({**lease, "expiresAt": overlong.strftime("%Y-%m-%dT%H:%M:%SZ")})
    replay([announce, tampered])
    # Resealed byte binding: subject rewritten.
    tampered = _resign_event({**lease, "subjectDigest": _digest("other-subject")})
    replay([announce, tampered])
    # URL-shaped worker identity is never opaque.
    tampered = _resign_event({**lease, "workerInstanceId": "https://x.invalid/w"})
    replay([announce, tampered])
    # Lease without a prior announcement is rejected.
    replay([lease])
    # Genuine events replay cleanly (control).
    control_path = _craft_ledger(tmp_path, "control.jsonl", genuine)
    control = MaskInspectionJobLedger(DurableJournal(control_path), resource_envelope=envelope)
    assert len(control.list_announced(organization_id=ORG)) == 1


def test_masked_inspection_fence_spent_acquisition_and_overlap(tmp_path: Path) -> None:
    """Spent acquisitions never renew; overlapping fences never replay."""
    from ksi_core.domains.external.ingress.external_mask_input_api import (
        MaskInspectionJobLedger,
        MaskInspectionJobRecoveryError,
    )

    lane = _genuine_announce_and_lease(tmp_path)
    envelope = lane["envelope"]
    # NOTE: the helper above closed its journals; reopen all masked state.
    lane["wiring"] = build_masked_quantitative_wiring(
        journal=lambda name: DurableJournal(tmp_path / name),
        config=lane["wiring"].config,
        assessments=lane["stores"]["assessments"],
        sites=lane["stores"]["sites"],
        reconstruction=lane["stores"]["reconstruction"],
        inspections=lane["stores"]["inspections"],
        work_areas=lane["stores"]["work_areas"],
        coordinator=lane["coordinator"],
        dsm_byte_reader=lane["dsm_reader"],
    )
    client = _client(lane)
    lane["clock"].now = NOW + timedelta(seconds=700)
    lease_body = {
        "siteId": SITE_ID,
        "workAreaId": WORK_AREA_ID,
        "maskArtifactId": MASK_ARTIFACT,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
        "baselineDsmArtifactId": "dsm-baseline",
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": "masked-inspector-1",
        "leaseAcquisitionId": "inspect-lease-1",
    }
    # The first lease expired; its acquisition id is spent and cannot renew.
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers("worker"),
            json=lease_body,
        ).status_code
        == 409
    )
    second = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json={**lease_body, "leaseAcquisitionId": "inspect-lease-2"},
    )
    assert second.status_code == 200, second.text

    genuine = _read_journal_events(tmp_path / "external-mask-inspection-jobs.jsonl")
    leases = [e for e in genuine if e["kind"] == "masked-inspection-lease-issued.v1"]
    assert len(leases) == 2
    announce = next(e for e in genuine if e["kind"] == "masked-inspection-announced.v1")
    # Craft an overlapping fence by backdating the second lease into the first.
    overlapping = _resign_event(
        {
            **leases[1],
            "issuedAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiresAt": (NOW + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "leaseAcquisitionId": "inspect-lease-2",
        }
    )
    overlap_path = _craft_ledger(tmp_path, "overlap.jsonl", [announce, leases[0], overlapping])
    with pytest.raises(MaskInspectionJobRecoveryError):
        MaskInspectionJobLedger(DurableJournal(overlap_path), resource_envelope=envelope)
    # Craft a spent-acquisition replay: same acquisition, fresh lease id.
    reacquired = _resign_event({**leases[1], "leaseId": "masked-inspection-lease-deadbeef"})
    reacquire_path = _craft_ledger(
        tmp_path, "reacquire.jsonl", [announce, leases[0], leases[1], reacquired]
    )
    with pytest.raises(MaskInspectionJobRecoveryError):
        MaskInspectionJobLedger(DurableJournal(reacquire_path), resource_envelope=envelope)


def test_masked_pending_scopes_narrowed_worker_grants(tmp_path: Path) -> None:
    """Discovery never leaks foreign site/area queue metadata to a grant."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    # The owner store hook landed: wire the real journal-backed listing, no
    # test double.  Structural port, fresh witness per item, bounded walk.
    queued = lane["wiring"].calculations
    open_client = _client(lane, queued=queued)
    scoped_client = _client(
        lane,
        principals={"operator": _operator(), "scoped-worker": _scoped_designated_worker()},
        queued=queued,
    )
    assert (
        open_client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    )
    grant = open_client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = open_client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text

    before_insp_poll = _journal_length(lane["journals"]["inspection"])
    scoped_pending_insp = scoped_client.get(
        "/v1/internal/mask-inspection-jobs/pending", headers=_headers("scoped-worker")
    )
    assert scoped_pending_insp.status_code == 200, scoped_pending_insp.text
    assert scoped_pending_insp.json()["items"] == []
    open_pending_insp = open_client.get(
        "/v1/internal/mask-inspection-jobs/pending", headers=_headers("worker")
    )
    assert open_pending_insp.status_code == 200, open_pending_insp.text
    assert [item["maskChildId"] for item in open_pending_insp.json()["items"]] == [MASK_CHILD]
    assert "://" not in scoped_pending_insp.text
    assert _journal_length(lane["journals"]["inspection"]) == before_insp_poll

    manifest = _http_seal_child(open_client, lane, tmp_path)
    assert manifest["observedSha256"] == _digest(lane["mask_bytes"])
    created = _http_create(
        open_client,
        lane,
        masked_calculation_id="masked-calculation-1",
        request_id="masked-request-1",
        idempotency_key="masked-idem-1",
    )
    assert created["admission"]["disposition"] == "ADMIT_PROVISIONAL"
    before_calc_poll = _journal_length(lane["journals"]["masked_calc"])

    scoped_pending_calc = scoped_client.get(
        "/v1/internal/masked-calculations/pending", headers=_headers("scoped-worker")
    )
    assert scoped_pending_calc.status_code == 200, scoped_pending_calc.text
    assert scoped_pending_calc.json()["items"] == []
    open_pending_calc = open_client.get(
        "/v1/internal/masked-calculations/pending", headers=_headers("worker")
    )
    assert open_pending_calc.status_code == 200, open_pending_calc.text
    calc_items = open_pending_calc.json()["items"]
    assert [item["requestId"] for item in calc_items] == ["masked-request-1"]
    assert "://" not in scoped_pending_calc.text
    assert _journal_length(lane["journals"]["masked_calc"]) == before_calc_poll


def test_masked_inspection_failure_journal_closed(tmp_path: Path) -> None:
    """Failure replay: closed shape, fence binding, no revival, idempotent."""
    from ksi_core.domains.external.ingress.external_mask_input_api import (
        MaskInspectionJobLedger,
        MaskInspectionJobRecoveryError,
    )

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text
    leased = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json={
            "siteId": SITE_ID,
            "workAreaId": WORK_AREA_ID,
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
            "baselineDsmArtifactId": "dsm-baseline",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "workerInstanceId": "masked-inspector-f",
            "leaseAcquisitionId": "inspect-lease-f",
        },
    )
    assert leased.status_code == 200, leased.text
    lease_id = leased.json()["leaseId"]
    failed = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}:inspection-failure",
        headers=_headers("worker"),
        json={
            "leaseId": lease_id,
            "workerInstanceId": "masked-inspector-f",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "reasonCode": "MASK_INSPECTION_FAILED",
        },
    )
    assert failed.status_code == 200, failed.text
    lane["wiring"].close()

    genuine = _read_journal_events(tmp_path / "external-mask-inspection-jobs.jsonl")
    assert {e["kind"] for e in genuine} == {
        "masked-inspection-announced.v1",
        "masked-inspection-lease-issued.v1",
        "masked-inspection-failed.v1",
    }
    announce = next(e for e in genuine if e["kind"] == "masked-inspection-announced.v1")
    lease = next(e for e in genuine if e["kind"] == "masked-inspection-lease-issued.v1")
    failure = next(e for e in genuine if e["kind"] == "masked-inspection-failed.v1")

    counter = 0

    def replay(events: list[dict[str, Any]]) -> MaskInspectionJobLedger:
        nonlocal counter
        counter += 1
        path = _craft_ledger(tmp_path, f"resealed-case-{counter}.jsonl", events)
        return MaskInspectionJobLedger(DurableJournal(path), resource_envelope=lane["envelope"])

    control = replay(genuine)
    stored = control.get_failure(organization_id=ORG, mask_child_id=MASK_CHILD)
    assert stored is not None and stored.reason_code == "MASK_INSPECTION_FAILED"

    def resealed_rejected(events: list[dict[str, Any]]) -> None:
        with pytest.raises(MaskInspectionJobRecoveryError):
            replay(events)

    # Unknown reason code, even resealed, is rejected.
    resealed_rejected([announce, lease, _resign_event({**failure, "reasonCode": "BOGUS"})])
    # Failure without its fence is rejected.
    resealed_rejected(
        [announce, _resign_event({**failure, "leaseId": "masked-inspection-lease-nope"})]
    )
    # Failure outside its fence window is rejected.
    late = datetime.fromisoformat(failure["failedAt"].replace("Z", "+00:00")) + timedelta(hours=2)
    late_event = _resign_event({**failure, "failedAt": late.strftime("%Y-%m-%dT%H:%M:%SZ")})
    resealed_rejected([announce, lease, late_event])
    # A conflicting second failure for the same child is rejected (no revival).
    rival = _resign_event(
        {
            **failure,
            "reasonCode": "MASK_NODATA_REJECTED",
            "leaseId": "masked-inspection-lease-rival00",
        }
    )
    resealed_rejected([announce, lease, failure, rival])
    # Unknown journal kind is rejected.
    resealed_rejected([announce, lease, _resign_event({**failure, "kind": "masked-x.v9"})])


def test_masked_calc_pending_requires_owner_hook(tmp_path: Path) -> None:
    """Queued calc discovery waits on the owner hook; no duplicate queue here."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    queued = client.get("/v1/internal/masked-calculations/pending", headers=_headers("worker"))
    assert queued.status_code == 503
    assert "list_queued_calculations" in queued.json()["detail"]
    assert (
        client.get("/v1/internal/masked-calculations/pending", headers=_headers()).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/internal/masked-calculations/pending",
            headers=_headers("worker"),
            params={"limit": 51},
        ).status_code
        == 422
    )


def test_masked_inspection_failure_rejects_and_surfaces(tmp_path: Path) -> None:
    """Deterministic rejections close the child; status names the reason."""
    from ksi_processing_controller.external_mask_input_inspection import MaskInspectionError

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    nodata_values = np.zeros((4, 4), dtype=np.uint8)
    nodata_values[0, 1] = 1
    nodata_bytes = _write_mask(tmp_path / "mask-nodata.tif", nodata_values, nodata=0)
    mask2, artifact2 = "mask-child-2", "mask-artifact-2"

    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    assert (
        client.post(
            MASK_BASE,
            headers=_headers(),
            json=_declare_child_body(
                lane,
                child_id=mask2,
                artifact_id=artifact2,
                data=nodata_bytes,
                declaration_id="decl-2",
            ),
        ).status_code
        == 200
    )
    status_pending = client.get(f"{MASK_BASE}/{mask2}/inspection-status", headers=_headers())
    assert status_pending.status_code == 200, status_pending.text
    assert status_pending.json()["status"] == "PENDING"
    assert status_pending.json()["reasonCode"] is None

    grant = client.post(
        f"{MASK_BASE}/{mask2}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": artifact2,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(nodata_bytes),
            "declaredSizeBytes": len(nodata_bytes),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{mask2}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=nodata_bytes,
    )
    assert upload.status_code == 200, upload.text

    lease_body = {
        "siteId": SITE_ID,
        "workAreaId": WORK_AREA_ID,
        "maskArtifactId": artifact2,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
        "baselineDsmArtifactId": "dsm-baseline",
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": "masked-inspector-2",
        "leaseAcquisitionId": "inspect-lease-2",
    }
    leased = client.post(
        f"/v1/internal/mask-children/{mask2}/inspection-lease",
        headers=_headers("worker"),
        json=lease_body,
    )
    assert leased.status_code == 200, leased.text
    running = client.get(f"{MASK_BASE}/{mask2}/inspection-status", headers=_headers())
    assert running.status_code == 200 and running.json()["status"] == "RUNNING"

    window = client.get(
        f"/v1/internal/mask-children/{mask2}/bytes",
        headers=_headers("worker"),
        params={
            "mask_artifact_id": artifact2,
            "offset": 0,
            "length": len(nodata_bytes),
            "lease_id": leased.json()["leaseId"],
            "worker_instance_id": "masked-inspector-2",
        },
    )
    assert window.status_code == 200, window.text
    worker_path = tmp_path / "mask-nodata-http.tif"
    worker_path.write_bytes(base64.b64decode(window.json()["contentBase64"]))
    with pytest.raises(MaskInspectionError) as native:
        inspect_mask_bytes_v1(
            path=worker_path,
            envelope=lane["envelope"],
            watchdog=MeasurementWatchdogV2.from_envelope(lane["envelope"]),
            organization_id=ORG,
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            mask_child_id=mask2,
            mask_artifact_id=artifact2,
            subject=lane["current_subject"],
            inspection_profile=lane["mask_profile"],
            contained_runtime_digest=__import__(
                "ksi_core.domains.external.ingress.external_mask_input_core_adapters",
                fromlist=["masked_inspection_runtime_digest"],
            ).masked_inspection_runtime_digest(lane["mask_profile"]),
            inspector_build_digest=lane["mask_profile"].worker_build_digest,
            expected_crs_identifier="EPSG:5186",
            expected_crs_digest=_digest(
                CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
            ),
            expected_transform=NATIVE_TRANSFORM,
            expected_transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
            report_id="narrow-report-2",
            reported_at=NOW,
        )
    assert native.value.reason in ("MASK_NODATA_REJECTED", "MASK_BYTES_MISMATCH")
    # Worker maps the caught native reason to the closed wire code.
    wire_reason = {
        "MASK_NODATA_REJECTED": "MASK_NODATA_REJECTED",
        "MASK_BYTES_MISMATCH": "MASK_BYTES_MISMATCH",
        "RESOURCE_LIMIT_EXCEEDED": "MASK_RESOURCE_EXCEEDED",
    }.get(native.value.reason, "MASK_INSPECTION_FAILED")

    # Worker posts the same closed body derived from the caught error.
    failed = client.post(
        f"/v1/internal/mask-children/{mask2}:inspection-failure",
        headers=_headers("worker"),
        json={
            "leaseId": leased.json()["leaseId"],
            "workerInstanceId": "masked-inspector-2",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "reasonCode": wire_reason,
        },
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "REJECTED"
    assert failed.json()["reasonCode"] == wire_reason

    rejected = client.get(f"{MASK_BASE}/{mask2}/inspection-status", headers=_headers())
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["reasonCode"] == wire_reason
    assert rejected.json()["manifestDigest"] is None
    assert "://" not in rejected.text

    pending = client.get("/v1/internal/mask-inspection-jobs/pending", headers=_headers("worker"))
    assert pending.status_code == 200
    assert all(item["maskChildId"] != mask2 for item in pending.json()["items"])

    # No revival: new leases, duplicate failures, and seals all fail closed.
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}/inspection-lease",
            headers=_headers("worker"),
            json={**lease_body, "leaseAcquisitionId": "inspect-lease-2b"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}:inspection-failure",
            headers=_headers("worker"),
            json={
                "leaseId": leased.json()["leaseId"],
                "workerInstanceId": "masked-inspector-2",
                "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
                "reasonCode": "MASK_RESOURCE_EXCEEDED",
            },
        ).status_code
        == 409
    )
    # Idempotent duplicate of the recorded failure is byte-identical and
    # harmless: same receipt, no new journal event.
    inspection_len_before = _journal_length(lane["journals"]["inspection"])
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}:inspection-failure",
            headers=_headers("worker"),
            json={
                "leaseId": leased.json()["leaseId"],
                "workerInstanceId": "masked-inspector-2",
                "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
                "reasonCode": wire_reason,
            },
        ).status_code
        == 200
    )
    assert _journal_length(lane["journals"]["inspection"]) == inspection_len_before
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}:report",
            headers=_headers("worker"),
            json={
                "leaseId": leased.json()["leaseId"],
                "workerInstanceId": "masked-inspector-2",
                "report": {},
                "inspectionProfile": lane["mask_profile"].model_dump(by_alias=True, mode="json"),
            },
        ).status_code
        == 409
    )
    # Auth and shape fences hold on the failure path too.
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}:inspection-failure",
            headers=_headers(),
            json={
                "leaseId": leased.json()["leaseId"],
                "workerInstanceId": "masked-inspector-2",
                "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
                "reasonCode": wire_reason,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{mask2}:inspection-failure",
            headers=_headers("worker"),
            json={
                "leaseId": leased.json()["leaseId"],
                "workerInstanceId": "masked-inspector-2",
                "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
                "reasonCode": "BOGUS_REASON",
            },
        ).status_code
        == 422
    )
    assert (
        client.get(f"{MASK_BASE}/{mask2}/inspection-status", headers=_headers("mcp")).status_code
        == 403
    )


def test_masked_inspection_failure_generic_io_and_calc_failure_read(tmp_path: Path) -> None:
    """Unexpected worker IO records FAILED; calc failures stay readable."""
    from ksi_event_contracts.external_masked_volume_result import (
        MaskedVolumeCalculationFailureV3,
    )

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    mask3, artifact3 = "mask-child-3", "mask-artifact-3"
    assert (
        client.post(
            MASK_BASE,
            headers=_headers(),
            json=_declare_child_body(
                lane,
                child_id=mask3,
                artifact_id=artifact3,
                data=lane["mask_bytes"],
                declaration_id="decl-3",
            ),
        ).status_code
        == 200
    )
    grant = client.post(
        f"{MASK_BASE}/{mask3}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": artifact3,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{mask3}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text
    leased = client.post(
        f"/v1/internal/mask-children/{mask3}/inspection-lease",
        headers=_headers("worker"),
        json={
            "siteId": SITE_ID,
            "workAreaId": WORK_AREA_ID,
            "maskArtifactId": artifact3,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
            "baselineDsmArtifactId": "dsm-baseline",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "workerInstanceId": "masked-inspector-3",
            "leaseAcquisitionId": "inspect-lease-3",
        },
    )
    assert leased.status_code == 200, leased.text
    # Worker-observed unexpected IO (valid bytes, failed read): generic FAILED.
    failed = client.post(
        f"/v1/internal/mask-children/{mask3}:inspection-failure",
        headers=_headers("worker"),
        json={
            "leaseId": leased.json()["leaseId"],
            "workerInstanceId": "masked-inspector-3",
            "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
            "reasonCode": "MASK_INSPECTION_FAILED",
        },
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "FAILED"
    status = client.get(f"{MASK_BASE}/{mask3}/inspection-status", headers=_headers())
    assert status.status_code == 200 and status.json()["status"] == "FAILED"
    assert status.json()["reasonCode"] == "MASK_INSPECTION_FAILED"

    # Sealed V3 numbers stay honest about worker failure too: the base child
    # needs its own declared, granted, and uploaded bytes first.
    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    base_grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert base_grant.status_code == 200, base_grant.text
    base_upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{base_grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert base_upload.status_code == 200, base_upload.text
    manifest = _http_seal_child(client, lane, tmp_path)
    assert manifest["observedSha256"] == _digest(lane["mask_bytes"])
    created = _http_create(
        client,
        lane,
        masked_calculation_id="masked-calculation-1",
        request_id="masked-request-1",
        idempotency_key="masked-idem-1",
    )
    assert created["admission"]["disposition"] == "ADMIT_PROVISIONAL"
    clock.now = NOW + timedelta(seconds=200)
    calc_leased = client.post(
        "/v1/internal/masked-calculations/masked-request-1:lease",
        headers=_headers("worker"),
        json={"workerInstanceId": "masked-worker-instance-1", "leaseAcquisitionId": "lease-1"},
    )
    assert calc_leased.status_code == 200, calc_leased.text
    attempt = calc_leased.json()["attempt"]
    clock.now = NOW + timedelta(seconds=300)
    failure = MaskedVolumeCalculationFailureV3(
        contract_version="external-masked-volume-calculation-failure.v3",
        failure_id="failure-1",
        masked_calculation_identity_digest=created["maskedCalculationIdentityDigest"],
        reason_code="WORKER_MEASUREMENT_REJECTED",
        failed_at=NOW + timedelta(seconds=260),
    ).sealed()
    stored = client.post(
        "/v1/internal/masked-calculations/masked-request-1:failure",
        headers=_headers("worker"),
        json={
            "attempt": attempt,
            "failure": failure.model_dump(by_alias=True, mode="json"),
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["status"] == "FAILED"
    detail = client.get(f"{CALC_BASE}/masked-request-1", headers=_headers())
    assert detail.status_code == 200
    assert detail.json()["disposition"] == "FAILED"
    assert detail.json()["report"] is None
    read_failure = client.get(f"{CALC_BASE}/masked-request-1/failure", headers=_headers())
    assert read_failure.status_code == 200, read_failure.text
    assert read_failure.json()["reasonCode"] == "WORKER_MEASUREMENT_REJECTED"
    assert (
        client.get(f"{CALC_BASE}/masked-request-9/failure", headers=_headers()).status_code == 404
    )


def test_masked_seal_report_time_window_and_idempotent_replay(tmp_path: Path) -> None:
    """Reports must sit inside the live fence; sealed success replays idempotently."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    child_journal = lane["journals"]["mask_child"]
    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text
    before_seal = _journal_length(child_journal)

    def post_report(lease_id: str, report: dict[str, Any]) -> Any:
        return client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}:report",
            headers=_headers("worker"),
            json={
                "leaseId": lease_id,
                "workerInstanceId": "masked-inspector-1",
                "report": report,
                "inspectionProfile": lane["mask_profile"].model_dump(by_alias=True, mode="json"),
            },
        )

    # One live lease shared by all three reports (idempotent reclaim);
    # old and future timestamps claim no run.
    old_lease, old_report = _http_lease_and_inspect(
        client,
        lane,
        tmp_path,
        report_id="narrow-report-old",
        reported_at=NOW - timedelta(seconds=60),
    )
    assert post_report(old_lease, old_report).status_code == 409
    _, future_report = _http_lease_and_inspect(
        client,
        lane,
        tmp_path,
        report_id="narrow-report-future",
        reported_at=NOW + timedelta(seconds=3600),
    )
    assert post_report(old_lease, future_report).status_code == 409
    assert _journal_length(child_journal) == before_seal

    # The valid report seals; replaying it after lease expiry returns the
    # existing receipt without a new journal event (no new run claimed).
    lease_id, report = _http_lease_and_inspect(
        client, lane, tmp_path, report_id="narrow-report-live"
    )
    sealed = post_report(lease_id, report)
    assert sealed.status_code == 200, sealed.text
    sealed_digest = sealed.json()["manifest"]["manifestDigest"]
    after_seal = _journal_length(child_journal)
    assert after_seal == before_seal + 1
    clock.now = NOW + timedelta(seconds=700)
    replayed = post_report(lease_id, report)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["manifest"]["manifestDigest"] == sealed_digest
    assert _journal_length(child_journal) == after_seal
    # A divergent report on the sealed child still fails closed.
    assert post_report(lease_id, future_report).status_code == 409


def test_masked_declare_accepts_unsealed_browser_intent(tmp_path: Path) -> None:
    """The Console sends intent (digest null); Core owns the canonical seal."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    child_journal = lane["journals"]["mask_child"]
    before = _journal_length(child_journal)

    intent = _declare_body(lane)
    assert intent["declarationDigest"] is not None
    intent["declarationDigest"] = None
    created = client.post(MASK_BASE, headers=_headers(), json=intent)
    assert created.status_code == 200, created.text
    sealed_digest = created.json()["declaration"]["declarationDigest"]
    assert sealed_digest is not None
    assert (
        sealed_digest
        == MaskChildDeclarationV1.model_validate(created.json()["declaration"]).canonical_digest()
    )
    assert _journal_length(child_journal) == before + 1

    tampered = _declare_body(lane)
    tampered["maskChildId"] = "mask-child-tampered"
    tampered["declarationId"] = "decl-tampered"
    tampered["declarationDigest"] = "sha256:" + "0" * 64
    assert client.post(MASK_BASE, headers=_headers(), json=tampered).status_code == 422
    assert _journal_length(child_journal) == before + 1


def test_masked_http_rejects_untrusted_inputs(tmp_path: Path) -> None:
    """Closed-shape, scope, worker, byte-identity, and fence negatives."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)
    mask_bytes = lane["mask_bytes"]
    child_journal = lane["journals"]["mask_child"]
    calc_journal = lane["journals"]["masked_calc"]
    before_child = _journal_length(child_journal)
    before_calc = _journal_length(calc_journal)

    bad_artifact = dict(_declare_body(lane))
    bad_artifact["maskArtifactId"] = "https://x.invalid/mask.tif"
    assert client.post(MASK_BASE, headers=_headers(), json=bad_artifact).status_code == 422

    mismatched_path = client.post(
        MASK_BASE.replace(SITE_ID, "site-other"), headers=_headers(), json=_declare_body(lane)
    )
    assert mismatched_path.status_code == 404
    foreign = client.post(MASK_BASE, headers=_headers("foreign"), json=_declare_body(lane))
    assert foreign.status_code == 404
    # A scoped operator outside its grants is denied.  The exact code depends
    # on the parent-owned auth allowlist (framework 403 today; router-level
    # uniform 404 once the new routes are allowlisted); either way no foreign
    # record is revealed or mutated.
    scoped = client.post(MASK_BASE, headers=_headers("scoped"), json=_declare_body(lane))
    assert scoped.status_code in (403, 404)
    denied = client.post(MASK_BASE, headers=_headers("mcp"), json=_declare_body(lane))
    assert denied.status_code == 403
    assert client.post(MASK_BASE, json=_declare_body(lane)).status_code == 401

    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    assert client.get(f"{MASK_BASE}/{MASK_CHILD}", headers=_headers("mcp")).status_code == 403
    scoped_read = client.get(f"{MASK_BASE}/{MASK_CHILD}", headers=_headers("scoped"))
    assert scoped_read.status_code in (403, 404)
    assert (
        client.get(
            MASK_BASE.replace(SITE_ID, "site-other") + f"/{MASK_CHILD}", headers=_headers()
        ).status_code
        == 404
    )

    # Malformed grant identity never reaches the byte store.
    assert (
        client.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
            headers=_headers(),
            json={
                "maskArtifactId": MASK_ARTIFACT,
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(b"other"),
                "declaredSizeBytes": len(mask_bytes),
                "ttlSeconds": 3600,
            },
        ).status_code
        == 409
    )

    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(mask_bytes),
            "declaredSizeBytes": len(mask_bytes),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    grant_id = grant.json()["grantId"]

    # Multipart spooling is refused before any byte mutation.
    assert (
        client.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant_id}/bytes",
            headers=_headers(**{"Content-Type": "multipart/form-data; boundary=x"}),
            content=b"junk",
        ).status_code
        == 415
    )
    cap = min(lane["envelope"].max_input_bytes, lane["envelope"].max_streamed_bytes)
    assert (
        client.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant_id}/bytes",
            headers=_headers(**{"Content-Type": "application/octet-stream"}),
            content=b"0" * (cap + 1),
        ).status_code
        == 413
    )
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant_id}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=mask_bytes,
    )
    assert upload.status_code == 200, upload.text

    # Humans and wrong workers cannot take inspection jobs or seal reports.
    lease_body = {
        "siteId": SITE_ID,
        "workAreaId": WORK_AREA_ID,
        "maskArtifactId": MASK_ARTIFACT,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
        "baselineDsmArtifactId": "dsm-baseline",
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": "masked-inspector-9",
        "leaseAcquisitionId": "inspect-lease-9",
    }
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers(),
            json=lease_body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers("mcp"),
            json=lease_body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers("processing"),
            json=lease_body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers("wrong-worker"),
            json=lease_body,
        ).status_code
        == 403
    )
    leased = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json=lease_body,
    )
    assert leased.status_code == 200, leased.text
    lease_id = leased.json()["leaseId"]

    # Stale acquisition on the same child fails closed without mutation.
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
            headers=_headers("worker"),
            json={**lease_body, "leaseAcquisitionId": "inspect-lease-other"},
        ).status_code
        == 409
    )

    # A report under a foreign profile digest fails the fence (caller hash
    # alone is untrusted); Core state is untouched.
    tampered_profile = (
        lane["mask_profile"]
        .model_copy(
            update={
                "mask_grammar_digest": _digest("other-grammar"),
                "inspection_profile_digest": None,
            }
        )
        .sealed()
    )
    assert (
        client.post(
            f"/v1/internal/mask-children/{MASK_CHILD}:report",
            headers=_headers("worker"),
            json={
                "leaseId": lease_id,
                "workerInstanceId": "masked-inspector-9",
                "report": inspect_mask_bytes_v1(
                    path=tmp_path / "mask.tif",
                    envelope=lane["envelope"],
                    watchdog=MeasurementWatchdogV2.from_envelope(lane["envelope"]),
                    organization_id=ORG,
                    site_id=SITE_ID,
                    work_area_id=WORK_AREA_ID,
                    mask_child_id=MASK_CHILD,
                    mask_artifact_id=MASK_ARTIFACT,
                    subject=lane["current_subject"],
                    inspection_profile=lane["mask_profile"],
                    contained_runtime_digest=__import__(
                        "ksi_core.domains.external.ingress.external_mask_input_core_adapters",
                        fromlist=["masked_inspection_runtime_digest"],
                    ).masked_inspection_runtime_digest(lane["mask_profile"]),
                    inspector_build_digest=lane["mask_profile"].worker_build_digest,
                    expected_crs_identifier="EPSG:5186",
                    expected_crs_digest=_digest(
                        CRS.from_epsg(5186).to_wkt(
                            version="WKT2_2019", pretty=False, output_axis_rule=True
                        )
                    ),
                    expected_transform=NATIVE_TRANSFORM,
                    expected_transform_digest=_canonical_digest(
                        {"transform": list(NATIVE_TRANSFORM)}
                    ),
                    report_id="narrow-report-9",
                    reported_at=NOW,
                ).model_dump(by_alias=True, mode="json"),
                "inspectionProfile": tampered_profile.model_dump(by_alias=True, mode="json"),
            },
        ).status_code
        == 409
    )
    assert _journal_length(child_journal) == before_child + 1  # declare sealed; fence held
    assert _journal_length(calc_journal) == before_calc

    # Creation requires the sealed Core manifest: an unsealed child (or an
    # unresolvable source) answers uniform 404 and mutates nothing.
    assert (
        client.post(
            CALC_BASE,
            headers=_headers(),
            json={
                "maskedCalculationId": "masked-calculation-9",
                "sourceCalculationIdentityDigest": _digest("unknown-source"),
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-9",
                "idempotencyKey": "masked-idem-9",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/internal/masked-calculations/masked-request-9:lease",
            headers=_headers("worker"),
            json={"workerInstanceId": "i", "leaseAcquisitionId": "a"},
        ).status_code
        == 409
    )
    assert _journal_length(calc_journal) == before_calc


def test_masked_http_revocation_budget_and_schema(tmp_path: Path) -> None:
    """Activation expiry revokes admission; lease budget is positive and capped."""
    import jsonschema

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    client = _client(lane)

    assert client.post(MASK_BASE, headers=_headers(), json=_declare_body(lane)).status_code == 200
    grant = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
        headers=_headers(),
        json={
            "maskArtifactId": MASK_ARTIFACT,
            "subjectDigest": lane["current_subject"].canonical_digest(),
            "declaredSha256": _digest(lane["mask_bytes"]),
            "declaredSizeBytes": len(lane["mask_bytes"]),
            "ttlSeconds": 3600,
        },
    )
    assert grant.status_code == 200, grant.text
    upload = client.post(
        f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
        headers=_headers(**{"Content-Type": "application/octet-stream"}),
        content=lane["mask_bytes"],
    )
    assert upload.status_code == 200, upload.text
    manifest = _http_seal_child(client, lane, tmp_path)
    assert manifest["observedSha256"] == _digest(lane["mask_bytes"])
    created = _http_create(
        client,
        lane,
        masked_calculation_id="masked-calculation-1",
        request_id="masked-request-1",
        idempotency_key="masked-idem-1",
    )
    assert created["admission"]["disposition"] == "ADMIT_PROVISIONAL"

    # Expire the purpose-bound activation: fresh admission is refused and the
    # existing record reassesses instead of promoting its provisional past.
    clock.now = NOW + timedelta(hours=2)
    assert client.post(
        CALC_BASE,
        headers=_headers(),
        json={
            "maskedCalculationId": "masked-calculation-2",
            "sourceCalculationIdentityDigest": lane["source_digest"],
            "maskChildId": MASK_CHILD,
            "requestId": "masked-request-2",
            "idempotencyKey": "masked-idem-2",
        },
    ).status_code in (404, 409)
    detail = client.get(f"{CALC_BASE}/masked-request-1", headers=_headers())
    assert detail.status_code == 200, detail.text
    assert detail.json()["disposition"] == "REASSESSMENT_REQUIRED"
    assert detail.json()["report"] is None
    clock.now = NOW

    # Inspection lease budget: positive, bounded by the sealed envelope.
    # The seal-chain lease is live again at exactly NOW, so budget probes
    # run past its expiry: +700s (first lease expired) then +1400s.
    clock.now = NOW + timedelta(seconds=700)
    lease_body = {
        "siteId": SITE_ID,
        "workAreaId": WORK_AREA_ID,
        "maskArtifactId": MASK_ARTIFACT,
        "subjectDigest": lane["current_subject"].canonical_digest(),
        "baselineSubject": lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
        "baselineDsmArtifactId": "dsm-baseline",
        "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
        "workerInstanceId": "masked-inspector-b",
        "leaseAcquisitionId": "inspect-lease-b1",
    }
    first = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json=lease_body,
    )
    assert first.status_code == 200, first.text
    clock.now = NOW + timedelta(seconds=1400)
    second = client.post(
        f"/v1/internal/mask-children/{MASK_CHILD}/inspection-lease",
        headers=_headers("worker"),
        json={**lease_body, "leaseAcquisitionId": "inspect-lease-b2"},
    )
    assert second.status_code == 409
    assert second.json() == {"detail": "MASK_INSPECTION_FENCE_REJECTED"}

    # The additive HTTP schema validates closed shapes only.
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts/schemas/external-masked-api.v1.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("external-masked-api.v1.json")
    assert "MaskedCalculationCreateRequestV1" in schema["$defs"]
    assert "MaskedDeltaSourceRefV1" in schema["$defs"]
    jsonschema.validate(
        instance={
            "maskedCalculationId": "masked-calculation-1",
            "sourceCalculationIdentityDigest": lane["source_digest"],
            "maskChildId": MASK_CHILD,
            "requestId": "masked-request-1",
            "idempotencyKey": "masked-idem-1",
        },
        schema=schema["$defs"]["MaskedCalculationCreateRequestV1"],
    )

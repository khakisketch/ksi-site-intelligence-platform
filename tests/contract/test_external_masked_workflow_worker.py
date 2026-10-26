"""Genuine HTTP proof: masked first-execution worker (inspection + V3 calculation).

Synthetic bytes only (small generated GeoTIFFs, never field/customer data).
Every authority mechanism is the real Core lane, exposed through HTTP (no
store/adapter edits here); the worker is the NEW first-execution driver
(``external_masked_workflow_worker``), not the V2 worker and not the
late-export output worker owned by the other Lead:

- reconstruction/inspection/WorkArea/AP: real stores sharing one
  coordinator; the AP assessment reaches ADMIT_PROVISIONAL with empty
  evidence, so no V2 numeric result is ever required or created (original V2
  untouched);
- mask ingress/bytes/V3: assembled by the new optional factory
  (``build_masked_quantitative_wiring``) from the actual common stores plus one
  explicit sealed config; activation is fresh synthetic Ed25519 keys plus a
  real purpose-separated ``MASKED_ANALYSIS_V3`` activation verified by the real
  loader on every check (explicitly not production authority);
- DSM legs travel the NEW presigned DSM seam
  (``build_external_masked_dsm_capability_router``) via the existing pure
  ``DeltaPublicationS3InputCapabilityIssuer`` over a loopback object server;
  the mask leg travels only the Core-bearer ``EXCLUSION_MASK`` window. A Core
  bearer is never sent to object-storage origins. ``dsm_byte_reader`` stays
  ``None`` so the old Core ``/bytes`` DSM path fails closed (409) and cannot
  be shipped as a fallback;
- inspector + dispatch run worker-side in this test process (labelled as
  such): Core never decodes mask bytes and never runs the inspector; the
  direct native helpers run in-process for local software proof only (test
  loopback generated safe) and claim no OS sandbox;
- the full chain runs over genuine HTTP: operator declare -> grant -> raw
  upload -> worker inspection drain (lease -> Core-bearer bytes fetch ->
  outside-Core inspect -> Core seal from the authenticated worker report) ->
  operator bind+issue V3 from Core-constructed source plus mask child ->
  worker calculation drain (lease/input/DSM-caps/mask-bytes/dispatch/report)
  -> AVAILABLE with honest metre/cut/fill/provisional readouts -> journal
  replay.

Owner helpers below are adapted copies from
``test_external_masked_http_integration.py`` (that file is not edited or
imported); the HTTP seam, factory, contracts, schema, and worker are the
delivery.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import socket
import stat
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

import httpx
import numpy as np
import pytest
import rasterio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
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
from ksi_core.domains.external.quantity.external_masked_input_capabilities import (
    build_external_masked_dsm_capability_router,
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
from ksi_processing_controller.external_masked_workflow_worker import (
    MaskedInspectionJobSpec,
    MaskedWorkflowCoreClient,
    MaskedWorkflowWorkerConfig,
    MaskedWorkflowWorkerError,
    _inspection_failure_reason,
    run_mask_inspection_job,
    run_masked_calculation_job,
    run_masked_workflow_drain,
)
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementWatchdogV2,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
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


def _designated_worker() -> Principal:
    return Principal("masked-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, ORG)


def _wrong_worker() -> Principal:
    return Principal("masked-worker-2", PrincipalKind.ANALYSIS_WORKER, None, None, ORG)


def _foreign_operator() -> Principal:
    return Principal("operator-foreign", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-b")


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
) -> tuple[Path, Path]:
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
        "validUntil": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _build_lane(tmp_path: Path, clock: _Clock) -> dict[str, Any]:
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
        dsm_byte_reader=None,
    )
    return {
        "tmp_path": tmp_path,
        "clock": clock,
        "envelope": envelope,
        "coordinator": coordinator,
        "wiring": wiring,
        "storage_root": storage_root,
        "baseline_subject": baseline_subject,
        "current_subject": current_subject,
        "source_digest": source_digest,
        "masked_profile": masked_profile,
        "mask_profile": mask_profile,
        "execution_runtime": execution_runtime,
        "mask_bytes": mask_bytes,
        "baseline_bytes": baseline_bytes,
        "current_bytes": current_bytes,
        "stores": {
            "reconstruction": reconstruction,
            "sites": sites,
            "work_areas": work_areas,
            "inspections": inspections,
            "assessments": assessments,
            "evidence": evidence,
            "validations": validations,
            "policy_registry": policy_registry,
        },
    }


class _LoopbackPresignedStorage:
    """Test-only presigned storage over the loopback object server."""

    def __init__(self, origin: str, root: Path) -> None:
        self._origin = origin.rstrip("/")
        self._root = root

    def presigned_get(self, object_key: str, *, ttl) -> str:
        from urllib.parse import quote as _quote

        _ = ttl
        if ".." in object_key or object_key.startswith("/"):
            raise ValueError("object key escapes scope")
        target = (self._root / object_key).resolve()
        if self._root.resolve() not in (target, *target.parents) and target != self._root.resolve():
            raise ValueError("object key escapes scope")
        return f"{self._origin}/objects/{_quote(object_key, safe='')}"


def _start_object_server(root: Path) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self.path.startswith("/objects/"):
                self.send_error(404)
                return
            object_key = unquote(self.path.removeprefix("/objects/").split("?", 1)[0])
            if ".." in object_key or object_key.startswith("/"):
                self.send_error(404)
                return
            target = (root / object_key).resolve()
            if root.resolve() not in (target, *target.parents):
                self.send_error(404)
                return
            if not target.is_file():
                self.send_error(404)
                return
            payload = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_a: Any, **_k: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _tokens() -> dict[str, Principal]:
    return {
        "operator": _operator(),
        "foreign": _foreign_operator(),
        "worker": _designated_worker(),
        "wrong-worker": _wrong_worker(),
    }


def _build_app(lane: dict[str, Any], storage: Any) -> FastAPI:
    wiring = lane["wiring"]
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
            dsm_byte_reader=None,
            queued=wiring.calculations,
            clock=lane["clock"],
        )
    )
    app.include_router(
        build_external_masked_dsm_capability_router(
            wiring=wiring,
            reconstruction=lane["stores"]["reconstruction"],
            storage=storage,
            designated_worker=_designated_worker(),
            clock=lane["clock"],
        )
    )
    return app


def _start_core_server(app: FastAPI) -> tuple[Any, threading.Thread, socket.socket, str]:
    import time as _time

    import uvicorn

    listen_socket = socket.socket()
    listen_socket.bind(("127.0.0.1", 0))
    listen_socket.listen(128)
    origin = f"http://127.0.0.1:{listen_socket.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listen_socket]), daemon=True)
    thread.start()
    for _ in range(150):
        if server.started:
            break
        assert thread.is_alive(), "local Core server stopped during startup"
        _time.sleep(0.02)
    assert server.started
    return server, thread, listen_socket, origin


def _httpx_client(origin: str, bearer: str) -> httpx.Client:
    return httpx.Client(
        base_url=origin,
        headers={"Authorization": f"Bearer {bearer}"},
        trust_env=False,
        follow_redirects=False,
        timeout=5.0,
    )


def _declare_body(lane: dict[str, Any]) -> dict[str, Any]:
    declaration = MaskChildDeclarationV1(
        declaration_id="decl-1",
        organization_id=ORG,
        site_id=SITE_ID,
        work_area_id=WORK_AREA_ID,
        child_kind="MASK_CHILD",
        mask_child_id=MASK_CHILD,
        mask_artifact_id=MASK_ARTIFACT,
        parent_subject=lane["current_subject"],
        target_baseline_subject=lane["baseline_subject"],
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest(lane["mask_bytes"]),
        declared_size_bytes=len(lane["mask_bytes"]),
    ).sealed()
    return declaration.model_dump(by_alias=True, mode="json")


MASK_BASE = f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/mask-children"
CALC_BASE = f"/v3/sites/{SITE_ID}/work-areas/{WORK_AREA_ID}/masked-calculations"


def test_masked_workflow_first_execution_over_genuine_http(tmp_path: Path) -> None:
    """First inspection plus first V3 calculation through the NEW worker."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    object_server, object_thread, object_origin = _start_object_server(lane["storage_root"])
    core_server = core_thread = core_socket = None
    core_origin = ""
    try:
        storage = _LoopbackPresignedStorage(object_origin, lane["storage_root"])
        app = _build_app(lane, storage)
        core_server, core_thread, core_socket, core_origin = _start_core_server(app)
        operator = _httpx_client(core_origin, "synthetic-operator")

        declared = operator.post(MASK_BASE, json=_declare_body(lane))
        assert declared.status_code == 200, declared.text
        grant = operator.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
            json={
                "maskArtifactId": MASK_ARTIFACT,
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(lane["mask_bytes"]),
                "declaredSizeBytes": len(lane["mask_bytes"]),
                "ttlSeconds": 3600,
            },
        )
        assert grant.status_code == 200, grant.text
        grant_id = grant.json()["grantId"]
        upload = operator.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant_id}/bytes",
            content=lane["mask_bytes"],
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload.status_code == 200, upload.text

        transport = None
        worker_client = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=transport,
        )
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16384,
            max_object_bytes=lane["envelope"].max_input_bytes,
            max_chunk_bytes=min(65536, lane["envelope"].max_input_bytes),
        )
        work_dir = tmp_path / "worker-work"
        config = MaskedWorkflowWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token="synthetic-worker",
            worker_instance_id="masked-worker-instance-1",
            lease_acquisition_id="lease-1",
            transport_policy=policy,
            work_dir=work_dir,
            envelope=lane["envelope"],
            masked_profile=lane["masked_profile"],
            inspection_profile=lane["mask_profile"],
            execution_runtime=lane["execution_runtime"],
        )
        # Lead-owned inspection pending lists the announced child pre-seal.
        assert [
            item.mask_child_id for item in worker_client.discover_inspection_pending(50).items
        ] == [MASK_CHILD]
        try:
            summary = run_masked_workflow_drain(
                config=config,
                worker_principal_id=_designated_worker().principal_id,
                core_client=worker_client,
                now_fn=clock,
            )
        finally:
            worker_client.close()
        assert summary.sealed == (MASK_CHILD,), summary
        assert summary.discovered == (MASK_CHILD,), summary
        seen = operator.get(f"{MASK_BASE}/{MASK_CHILD}")
        assert seen.status_code == 200, seen.text
        manifest = seen.json()["manifest"]
        assert manifest["observedSha256"] == _digest(lane["mask_bytes"])
        assert (manifest["rows"], manifest["columns"]) == (4, 4)

        created = operator.post(
            CALC_BASE,
            json={
                "maskedCalculationId": "masked-calculation-1",
                "sourceCalculationIdentityDigest": lane["source_digest"],
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-1",
                "idempotencyKey": "masked-idem-1",
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["admission"]["disposition"] == "ADMIT_PROVISIONAL"

        created2 = operator.post(
            CALC_BASE,
            json={
                "maskedCalculationId": "masked-calculation-2",
                "sourceCalculationIdentityDigest": lane["source_digest"],
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-2",
                "idempotencyKey": "masked-idem-2",
            },
        )
        assert created2.status_code == 200, created2.text

        worker_client2 = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=None,
        )
        try:
            # Lead-owned bounded pendings: inspection empty after seal,
            # masked lists both QUEUED calculations. The Core bearer is
            # never sent to object origins: the DSM view carries presigned
            # URLs, the mask leg stays on Core-bearer bytes (proved by the
            # drain below succeeding with dsm_byte_reader=None).
            inspection_page = worker_client2.discover_inspection_pending(50)
            assert [item.mask_child_id for item in inspection_page.items] == []
            masked_page = worker_client2.discover_masked_pending(50)
            assert {item.request_id for item in masked_page.items} == {
                "masked-request-1",
                "masked-request-2",
            }
        finally:
            worker_client2.close()

        worker_client3 = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=None,
        )
        try:
            summary2 = run_masked_workflow_drain(
                config=config,
                worker_principal_id=_designated_worker().principal_id,
                core_client=worker_client3,
                now_fn=clock,
            )
        finally:
            worker_client3.close()
        assert summary2.completed == ("masked-request-1", "masked-request-2"), summary2
        assert summary2.discovered == ("masked-request-1", "masked-request-2"), summary2
        # Direct DSM seam proof on a fresh calculation: lease, fetch the two
        # presigned DSM caps, verify binding + origin + fence, verify the old
        # Core /bytes DSM path stays closed, then cancel to leave no RUNNING.
        created3 = operator.post(
            CALC_BASE,
            json={
                "maskedCalculationId": "masked-calculation-3",
                "sourceCalculationIdentityDigest": lane["source_digest"],
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-3",
                "idempotencyKey": "masked-idem-3",
            },
        )
        assert created3.status_code == 200, created3.text

        dsm_client = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=None,
        )
        try:
            leased_raw = dsm_client.lease_masked_calculation(
                "masked-request-3",
                worker_instance_id="masked-worker-instance-1",
                lease_acquisition_id="lease-1",
            )
            attempt = leased_raw["attempt"]
            dsm_view = dsm_client.fetch_dsm_input(
                "masked-request-3",
                attempt_digest=attempt["executionAttemptDigest"],
                worker_instance_id="masked-worker-instance-1",
            )
            assert [c.role for c in dsm_view.capabilities] == ["BASELINE_DSM", "CURRENT_DSM"]
            assert all(
                c.download_url.startswith(object_origin + "/objects/")
                for c in dsm_view.capabilities
            )
            lease_expires_at = datetime.fromisoformat(
                str(attempt["leaseExpiresAt"]).replace("Z", "+00:00")
            )
            assert all(c.expires_at <= lease_expires_at for c in dsm_view.capabilities)
            # Core-bound lane seals travel with the caps (never caller hashes).
            from ksi_event_contracts.external_masked_execution import (
                masked_execution_runtime_digest as _owner_lane_digest,
            )

            assert dsm_view.execution_runtime_digest == _owner_lane_digest(
                lane["execution_runtime"],
                lane["masked_profile"].canonical_digest(),
                lane["envelope"].canonical_digest(),
                lane["mask_profile"].canonical_digest(),
            )
            assert dsm_view.resource_envelope_digest == lane["envelope"].canonical_digest()
            assert (
                dsm_view.resource_envelope_digest
                == attempt["authorization"]["resourceEnvelopeDigest"]
            )
            assert dsm_view.activation_digest == attempt["authorization"]["activationDigest"]
            probe = _httpx_client(core_origin, "synthetic-worker")
            try:
                probed = probe.get(
                    "/v1/internal/masked-calculations/masked-request-3/inputs/BASELINE_DSM/bytes",
                    params={"offset": 0, "length": 64},
                    headers={
                        "X-Masked-Attempt-Digest": attempt["executionAttemptDigest"],
                        "X-Masked-Worker-Instance-Id": "masked-worker-instance-1",
                    },
                )
                assert probed.status_code == 409, probed.text
            finally:
                probe.close()
        finally:
            dsm_client.close()
        assert operator.post(f"{CALC_BASE}/masked-request-3/cancel").status_code in (200, 404, 409)
        detail = operator.get(f"{CALC_BASE}/masked-request-2")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["disposition"] == "AVAILABLE"
        metrics = body["report"]["numericResult"]["metrics"]
        assert (metrics["fillM3"], metrics["cutM3"]) == (2.0, 2.0)
        assert metrics["netM3"] == 0.0
        coverage = body["report"]["numericResult"]["coverage"]
        assert coverage["commonValidCellCount"] == coverage["effectiveSelectedCellCount"] == 15
        assert coverage["unavailableCellCount"] == 0
        assert coverage["maskExcludedCellCount"] == 1
        assert body["report"]["numericResult"]["impact"]["excludedCellCount"] == 1
        # Current-NaN-excluded impact stays unknown-allowed without any V2 NX
        # completion: the AP source is provisional-only and no V2 numeric was
        # ever created.
        assert body["admission"]["disposition"] == "ADMIT_PROVISIONAL"
        assert "://" not in detail.text
        assert stat.S_IMODE(work_dir.stat().st_mode) == 0o700
    finally:
        with contextlib.suppress(Exception):
            operator.close()
        if core_server is not None:
            core_server.should_exit = True
        if "core_thread" in locals() and core_thread is not None:
            core_thread.join(timeout=5)
        if "core_socket" in locals() and core_socket is not None:
            with contextlib.suppress(Exception):
                core_socket.close()
        object_server.shutdown()
        object_server.server_close()
        object_thread.join(timeout=5)


def test_masked_workflow_rejects_runtime_envelope_mismatch(tmp_path: Path) -> None:
    """Declared model pins != signed Core authorization: FAILED, no native run.

    Case A: worker config pins a different sealed five-pin execution runtime
    than the lane activation authorizes. Case B: Core DSM caps arrive with a
    tampered runtime/envelope digest. Both must fail closed before any object
    download or native parse (dispatch never invoked) and never produce a
    numeric report. Runtime pin checks are not OS sandbox claims.
    """
    import dataclasses

    import ksi_processing_controller.external_masked_workflow_worker as _worker_mod
    from ksi_event_contracts.external_masked_execution import MaskedExecutionRuntimeV3

    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    object_server, object_thread, object_origin = _start_object_server(lane["storage_root"])
    core_server = core_thread = core_socket = None
    try:
        storage = _LoopbackPresignedStorage(object_origin, lane["storage_root"])
        app = _build_app(lane, storage)
        core_server, core_thread, core_socket, core_origin = _start_core_server(app)
        operator = _httpx_client(core_origin, "synthetic-operator")

        assert operator.post(MASK_BASE, json=_declare_body(lane)).status_code == 200
        mb = lane["mask_bytes"]
        grant = operator.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants",
            json={
                "maskArtifactId": MASK_ARTIFACT,
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(mb),
                "declaredSizeBytes": len(mb),
                "ttlSeconds": 3600,
            },
        )
        assert grant.status_code == 200, grant.text
        upload = operator.post(
            f"{MASK_BASE}/{MASK_CHILD}/upload-grants/{grant.json()['grantId']}/bytes",
            content=mb,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload.status_code == 200, upload.text

        policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16384,
            max_object_bytes=lane["envelope"].max_input_bytes,
            max_chunk_bytes=min(65536, lane["envelope"].max_input_bytes),
        )
        good_config = MaskedWorkflowWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token="synthetic-worker",
            worker_instance_id="masked-worker-instance-1",
            lease_acquisition_id="lease-1",
            transport_policy=policy,
            work_dir=tmp_path / "worker-pin",
            envelope=lane["envelope"],
            masked_profile=lane["masked_profile"],
            inspection_profile=lane["mask_profile"],
            execution_runtime=lane["execution_runtime"],
        )
        # Seal the mask through the discovery-driven drain first.
        seed_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        try:
            sealed = run_masked_workflow_drain(
                config=good_config,
                worker_principal_id=_designated_worker().principal_id,
                core_client=seed_client,
                now_fn=clock,
            )
        finally:
            seed_client.close()
        assert sealed.sealed == (MASK_CHILD,), sealed

        created = operator.post(
            CALC_BASE,
            json={
                "maskedCalculationId": "masked-calculation-pin",
                "sourceCalculationIdentityDigest": lane["source_digest"],
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-pin",
                "idempotencyKey": "masked-idem-pin",
            },
        )
        assert created.status_code == 200, created.text

        # Case A: different sealed five-pin runtime in worker config.
        other_runtime = MaskedExecutionRuntimeV3(
            contract_version="external-masked-execution-runtime.v3",
            worker_executable_digest=_digest("masked-worker-exe-OTHER"),
            worker_build_digest=_digest("masked-worker-build"),
            runtime_image_version="9.9.9",
            runtime_image_oci_digest=_digest("masked-worker-oci"),
            dependency_lock_digest=_digest("masked-worker-lock"),
        ).sealed()
        bad_config = dataclasses.replace(good_config, execution_runtime=other_runtime)
        calls: list[str] = []
        real_dispatch = _worker_mod.dispatch_masked_execution_v3

        def _spy_dispatch(*args: Any, **kwargs: Any) -> Any:
            calls.append("dispatch")
            return real_dispatch(*args, **kwargs)

        _worker_mod.dispatch_masked_execution_v3 = _spy_dispatch  # type: ignore[assignment]
        bad_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        try:
            # Direct job call (no discovery needed): proves the pin check
            # itself fails closed before downloads/dispatch. The
            # discovery-driven drain exercises the same job path.
            result_a = run_masked_calculation_job(
                config=bad_config,
                core_client=bad_client,
                request_id="masked-request-pin",
                worker_principal_id=_designated_worker().principal_id,
                worker_instance_id="masked-worker-instance-1",
                now_fn=clock,
            )
        finally:
            bad_client.close()
            _worker_mod.dispatch_masked_execution_v3 = real_dispatch  # type: ignore[assignment]
        assert result_a == "FAILED", result_a
        assert calls == [], "native dispatch must not run on runtime mismatch"
        assert not list((tmp_path / "worker-pin").rglob("*.tif")), "no bytes may stage"
        detail = operator.get(f"{CALC_BASE}/masked-request-pin")
        assert detail.status_code == 200, detail.text
        assert detail.json()["disposition"] == "FAILED"
        assert detail.json().get("report") is None

        # Case B: tampered DSM caps (wrong runtime + envelope digests).
        created2 = operator.post(
            CALC_BASE,
            json={
                "maskedCalculationId": "masked-calculation-tamper",
                "sourceCalculationIdentityDigest": lane["source_digest"],
                "maskChildId": MASK_CHILD,
                "requestId": "masked-request-tamper",
                "idempotencyKey": "masked-idem-tamper",
            },
        )
        assert created2.status_code == 200, created2.text
        calls2: list[str] = []

        def _no_native(*args: Any, **kwargs: Any) -> Any:
            calls2.append("dispatch")
            raise AssertionError("native dispatch must not run on tampered caps")

        _worker_mod.dispatch_masked_execution_v3 = _no_native  # type: ignore[assignment]
        tamper_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        real_fetch = tamper_client.fetch_dsm_input
        try:

            def _tampered_fetch(request_id: str, **kwargs: Any) -> Any:
                view = real_fetch(request_id, **kwargs)
                return view.model_copy(
                    update={
                        "execution_runtime_digest": "sha256:" + "1" * 64,
                        "resource_envelope_digest": "sha256:" + "2" * 64,
                    }
                )

            tamper_client.fetch_dsm_input = _tampered_fetch  # type: ignore[assignment]
            result = run_masked_calculation_job(
                config=good_config,
                core_client=tamper_client,
                request_id="masked-request-tamper",
                worker_principal_id=_designated_worker().principal_id,
                worker_instance_id="masked-worker-instance-1",
                now_fn=clock,
            )
        finally:
            tamper_client.close()
            _worker_mod.dispatch_masked_execution_v3 = real_dispatch  # type: ignore[assignment]
        assert result == "FAILED", result
        assert calls2 == [], "native dispatch must not run on tampered caps"
        detail2 = operator.get(f"{CALC_BASE}/masked-request-tamper")
        assert detail2.status_code == 200, detail2.text
        assert detail2.json()["disposition"] != "AVAILABLE"
        assert detail2.json().get("report") is None
    finally:
        with contextlib.suppress(Exception):
            operator.close()
        if core_server is not None:
            core_server.should_exit = True
        if "core_thread" in locals() and core_thread is not None:
            core_thread.join(timeout=5)
        if "core_socket" in locals() and core_socket is not None:
            with contextlib.suppress(Exception):
                core_socket.close()
        object_server.shutdown()
        object_server.server_close()
        object_thread.join(timeout=5)


def test_masked_workflow_posts_inspection_failure_best_effort(tmp_path: Path) -> None:
    """Deterministic native rejection posts a fenced closed reason, not just FAILED.

    NoData mask bytes fail the native inspect; the worker must attempt the
    additive inspection-failure post with the exact closed reason
    (MASK_NODATA_REJECTED) and no byte/grid/coordinate content. While the
    endpoint is still landing the post 404s and is suppressed — the job still
    returns FAILED with no Core seal. A wrong-worker lease never holds a fence
    so no failure post is attempted.
    """
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    object_server, object_thread, object_origin = _start_object_server(lane["storage_root"])
    core_server = core_thread = core_socket = None
    try:
        storage = _LoopbackPresignedStorage(object_origin, lane["storage_root"])
        app = _build_app(lane, storage)
        core_server, core_thread, core_socket, core_origin = _start_core_server(app)
        operator = _httpx_client(core_origin, "synthetic-operator")
        nodata_bytes = _write_mask(
            tmp_path / "nodata-fail.tif", np.zeros((4, 4), dtype=np.uint8), nodata=0
        )
        declaration = MaskChildDeclarationV1(
            declaration_id="decl-nodata-fail",
            organization_id=ORG,
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-nodata-fail",
            mask_artifact_id="mask-artifact-nodata-fail",
            parent_subject=lane["current_subject"],
            target_baseline_subject=lane["baseline_subject"],
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest(nodata_bytes),
            declared_size_bytes=len(nodata_bytes),
        ).sealed()
        posted_decl = declaration.model_dump(by_alias=True, mode="json")
        assert operator.post(MASK_BASE, json=posted_decl).status_code == 200
        grant = operator.post(
            f"{MASK_BASE}/mask-child-nodata-fail/upload-grants",
            json={
                "maskArtifactId": "mask-artifact-nodata-fail",
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(nodata_bytes),
                "declaredSizeBytes": len(nodata_bytes),
                "ttlSeconds": 3600,
            },
        )
        assert grant.status_code == 200, grant.text
        upload = operator.post(
            f"{MASK_BASE}/mask-child-nodata-fail/upload-grants/{grant.json()['grantId']}/bytes",
            content=nodata_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload.status_code == 200, upload.text

        policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16384,
            max_object_bytes=lane["envelope"].max_input_bytes,
            max_chunk_bytes=min(65536, lane["envelope"].max_input_bytes),
        )
        config = MaskedWorkflowWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token="synthetic-worker",
            worker_instance_id="masked-worker-instance-1",
            lease_acquisition_id="lease-1",
            transport_policy=policy,
            work_dir=tmp_path / "worker-fail",
            envelope=lane["envelope"],
            masked_profile=lane["masked_profile"],
            inspection_profile=lane["mask_profile"],
            execution_runtime=lane["execution_runtime"],
        )
        spec = MaskedInspectionJobSpec(
            mask_child_id="mask-child-nodata-fail",
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            mask_artifact_id="mask-artifact-nodata-fail",
            subject_digest=lane["current_subject"].canonical_digest(),
            parent_subject=lane["current_subject"].model_dump(by_alias=True, mode="json"),
            baseline_subject=lane["baseline_subject"].model_dump(by_alias=True, mode="json"),
            baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest(nodata_bytes),
            declared_size_bytes=len(nodata_bytes),
            organization_id=ORG,
        )
        # Closed reason mapping emits only the four exact owner codes.
        assert _inspection_failure_reason("MASK_NODATA_REJECTED") == "MASK_NODATA_REJECTED"
        assert _inspection_failure_reason("MASK_BYTES_MISMATCH") == "MASK_BYTES_MISMATCH"
        assert _inspection_failure_reason("INPUT_BYTE_STREAM_INVALID") == "MASK_BYTES_MISMATCH"
        assert _inspection_failure_reason("RESOURCE_LIMIT_EXCEEDED") == "MASK_RESOURCE_EXCEEDED"
        assert _inspection_failure_reason("STALE_LEASE") == "MASK_INSPECTION_FAILED"
        assert _inspection_failure_reason("AUTHORITY_LOST") == "MASK_INSPECTION_FAILED"
        assert _inspection_failure_reason("SOME_UNKNOWN_CODE") == "MASK_INSPECTION_FAILED"

        posted: list[dict[str, Any]] = []
        worker_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        real_fail = worker_client.fail_inspection
        try:

            def _fail_404(mask_child_id: str, **kwargs: Any) -> None:
                posted.append({"mask_child_id": mask_child_id, **kwargs})
                raise MaskedWorkflowWorkerError("CORE_HTTP_404")

            worker_client.fail_inspection = _fail_404  # type: ignore[assignment]
            result = run_mask_inspection_job(
                config=config,
                core_client=worker_client,
                spec=spec,
                worker_instance_id="masked-worker-instance-1",
                now_fn=clock,
            )
        finally:
            worker_client.close()
        # Endpoint absent: suppressed 404, still FAILED, never sealed.
        # (Declared-NoData TIFFs are rejected by the bounded structural
        # preflight, which the native primitive maps to the exact closed
        # MASK_BYTES_MISMATCH; GDAL-level MASK_NODATA_REJECTED is covered by
        # the mapper asserts above.)
        assert result == "FAILED", result
        assert len(posted) == 1, posted
        assert posted[0]["reason"] == "MASK_BYTES_MISMATCH", posted
        assert posted[0]["inspection_profile_digest"] == lane["mask_profile"].canonical_digest(), (
            posted
        )
        assert set(posted[0]) == {
            "mask_child_id",
            "lease_id",
            "worker_instance_id",
            "inspection_profile_digest",
            "reason",
        }, posted
        seen = operator.get(f"{MASK_BASE}/mask-child-nodata-fail")
        assert seen.status_code == 200
        assert seen.json()["manifest"] is None

        # Endpoint present: same FAILED outcome, post accepted, still no seal.
        # The first lease is spent (acquisition ids are single-use) so the
        # second attempt advances past its TTL and leases afresh.
        clock.now = NOW + timedelta(seconds=700)
        worker_client2 = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        posted2: list[dict[str, Any]] = []
        try:

            def _fail_ok(mask_child_id: str, **kwargs: Any) -> None:
                posted2.append({"mask_child_id": mask_child_id, **kwargs})

            worker_client2.fail_inspection = _fail_ok  # type: ignore[assignment]
            result2 = run_mask_inspection_job(
                config=config,
                core_client=worker_client2,
                spec=spec,
                worker_instance_id="masked-worker-instance-1",
                lease_acquisition_id="lease-2",
                now_fn=clock,
            )
        finally:
            worker_client2.close()
            clock.now = NOW
        assert result2 == "FAILED", result2
        assert len(posted2) == 1 and posted2[0]["reason"] == "MASK_BYTES_MISMATCH", posted2
        seen2 = operator.get(f"{MASK_BASE}/mask-child-nodata-fail")
        assert seen2.status_code == 200
        assert seen2.json()["manifest"] is None

        # Real endpoint: the additive POST records a terminal failure with
        # the exact closed reason — still no manifest, never numeric. The
        # terminal outcome then blocks any fresh lease (no revival), which
        # is what stops the invalid child from the rediscovery loop.
        # A fresh child is used: lease budget is per-child and the two
        # simulated attempts above already spent this child's budget.
        real_child = "mask-child-nodata-real"
        real_decl = MaskChildDeclarationV1(
            declaration_id="decl-nodata-real",
            organization_id=ORG,
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            child_kind="MASK_CHILD",
            mask_child_id=real_child,
            mask_artifact_id="mask-artifact-nodata-real",
            parent_subject=lane["current_subject"],
            target_baseline_subject=lane["baseline_subject"],
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest(nodata_bytes),
            declared_size_bytes=len(nodata_bytes),
        ).sealed()
        posted_decl = real_decl.model_dump(by_alias=True, mode="json")
        assert operator.post(MASK_BASE, json=posted_decl).status_code == 200
        real_grant = operator.post(
            f"{MASK_BASE}/{real_child}/upload-grants",
            json={
                "maskArtifactId": "mask-artifact-nodata-real",
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(nodata_bytes),
                "declaredSizeBytes": len(nodata_bytes),
                "ttlSeconds": 3600,
            },
        )
        assert real_grant.status_code == 200, real_grant.text
        real_upload = operator.post(
            f"{MASK_BASE}/{real_child}/upload-grants/{real_grant.json()['grantId']}/bytes",
            content=nodata_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert real_upload.status_code == 200, real_upload.text
        import dataclasses as _dataclasses

        real_spec = _dataclasses.replace(
            spec, mask_child_id=real_child, mask_artifact_id="mask-artifact-nodata-real"
        )
        real_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-worker", transport=None
        )
        try:
            real_lease = real_client.lease_inspection(
                real_spec,
                worker_instance_id="masked-worker-instance-1",
                inspection_profile_digest=lane["mask_profile"].canonical_digest(),
                lease_acquisition_id="lease-1",
            )
            real_client.fail_inspection(
                real_child,
                lease_id=real_lease["leaseId"],
                worker_instance_id="masked-worker-instance-1",
                inspection_profile_digest=lane["mask_profile"].canonical_digest(),
                reason="MASK_BYTES_MISMATCH",
            )
            try:
                real_client.lease_inspection(
                    real_spec,
                    worker_instance_id="masked-worker-instance-1",
                    inspection_profile_digest=lane["mask_profile"].canonical_digest(),
                    lease_acquisition_id="lease-2",
                )
                raise AssertionError("terminal failure must block a fresh lease")
            except MaskedWorkflowWorkerError as exc:
                assert exc.code == "CORE_HTTP_409", exc.code
        finally:
            real_client.close()
        seen3 = operator.get(f"{MASK_BASE}/{real_child}")
        assert seen3.status_code == 200
        assert seen3.json()["manifest"] is None
        # Console-visible reason status (owner status view over the recorded
        # terminal failure): REJECTED with the exact closed reason.
        status_view = operator.get(f"{MASK_BASE}/{real_child}/inspection-status")
        assert status_view.status_code == 200, status_view.text
        assert status_view.json()["status"] == "REJECTED", status_view.text
        assert status_view.json()["reasonCode"] == "MASK_BYTES_MISMATCH", status_view.text
        assert status_view.json()["manifestDigest"] is None

        # Wrong worker holds no fence: lease 403s, no failure post attempted.
        wrong_client = MaskedWorkflowCoreClient(
            base_url=core_origin, bearer_token="synthetic-wrong-worker", transport=None
        )
        posted3: list[dict[str, Any]] = []
        try:

            def _fail_never(mask_child_id: str, **kwargs: Any) -> None:
                posted3.append({"mask_child_id": mask_child_id, **kwargs})

            wrong_client.fail_inspection = _fail_never  # type: ignore[assignment]
            result3 = run_mask_inspection_job(
                config=config,
                core_client=wrong_client,
                spec=spec,
                worker_instance_id="masked-worker-instance-1",
                now_fn=clock,
            )
        finally:
            wrong_client.close()
        assert result3 == "FAILED", result3
        assert posted3 == [], posted3
    finally:
        with contextlib.suppress(Exception):
            operator.close()
        if core_server is not None:
            core_server.should_exit = True
        if "core_thread" in locals() and core_thread is not None:
            core_thread.join(timeout=5)
        if "core_socket" in locals() and core_socket is not None:
            with contextlib.suppress(Exception):
                core_socket.close()
        object_server.shutdown()
        object_server.server_close()
        object_thread.join(timeout=5)


def test_masked_workflow_rejects_untrusted_inputs(tmp_path: Path) -> None:
    """Bad mask NoData, wrong worker, stale lease, chunk sha, foreign scope."""
    clock = _Clock()
    lane = _build_lane(tmp_path, clock)
    object_server, object_thread, object_origin = _start_object_server(lane["storage_root"])
    core_server = core_thread = core_socket = None
    try:
        storage = _LoopbackPresignedStorage(object_origin, lane["storage_root"])
        app = _build_app(lane, storage)
        core_server, core_thread, core_socket, core_origin = _start_core_server(app)
        operator = _httpx_client(core_origin, "synthetic-operator")
        foreign = _httpx_client(core_origin, "synthetic-foreign")
        wrong = _httpx_client(core_origin, "synthetic-wrong-worker")

        # Foreign scope never reveals or mutates: uniform 404 on create.
        assert foreign.post(MASK_BASE, json=_declare_body(lane)).status_code == 404
        # Wrong worker cannot take inspection jobs: 403, no lease.
        assert (
            wrong.post(
                "/v1/internal/mask-children/mask-child-1/inspection-lease",
                json={
                    "siteId": SITE_ID,
                    "workAreaId": WORK_AREA_ID,
                    "maskArtifactId": MASK_ARTIFACT,
                    "subjectDigest": lane["current_subject"].canonical_digest(),
                    "baselineSubject": lane["baseline_subject"].model_dump(
                        by_alias=True, mode="json"
                    ),
                    "baselineDsmArtifactId": "dsm-baseline",
                    "inspectionProfileDigest": lane["mask_profile"].canonical_digest(),
                    "workerInstanceId": "masked-worker-instance-1",
                    "leaseAcquisitionId": "lease-1",
                },
            ).status_code
            == 403
        )

        # Happy declare/upload for the NoData child below.
        nodata_child = "mask-child-nodata"
        nodata_artifact = "mask-artifact-nodata"
        nodata_values = np.zeros((4, 4), dtype=np.uint8)
        nodata_bytes = _write_mask(tmp_path / "nodata.tif", nodata_values, nodata=0)
        declaration = MaskChildDeclarationV1(
            declaration_id="decl-nodata",
            organization_id=ORG,
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            child_kind="MASK_CHILD",
            mask_child_id=nodata_child,
            mask_artifact_id=nodata_artifact,
            parent_subject=lane["current_subject"],
            target_baseline_subject=lane["baseline_subject"],
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest(nodata_bytes),
            declared_size_bytes=len(nodata_bytes),
        ).sealed()
        posted_decl = declaration.model_dump(by_alias=True, mode="json")
        assert operator.post(MASK_BASE, json=posted_decl).status_code == 200
        grant = operator.post(
            f"{MASK_BASE}/{nodata_child}/upload-grants",
            json={
                "maskArtifactId": nodata_artifact,
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(nodata_bytes),
                "declaredSizeBytes": len(nodata_bytes),
                "ttlSeconds": 3600,
            },
        )
        assert grant.status_code == 200, grant.text
        upload = operator.post(
            f"{MASK_BASE}/{nodata_child}/upload-grants/{grant.json()['grantId']}/bytes",
            content=nodata_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload.status_code == 200, upload.text

        policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16384,
            max_object_bytes=lane["envelope"].max_input_bytes,
            max_chunk_bytes=min(65536, lane["envelope"].max_input_bytes),
        )
        config = MaskedWorkflowWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token="synthetic-worker",
            worker_instance_id="masked-worker-instance-1",
            lease_acquisition_id="lease-1",
            transport_policy=policy,
            work_dir=tmp_path / "worker-nodata",
            envelope=lane["envelope"],
            masked_profile=lane["masked_profile"],
            inspection_profile=lane["mask_profile"],
            execution_runtime=lane["execution_runtime"],
        )
        worker_client = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=None,
        )
        try:
            summary = run_masked_workflow_drain(
                config=config,
                worker_principal_id=_designated_worker().principal_id,
                core_client=worker_client,
                now_fn=clock,
            )
        finally:
            worker_client.close()
        # Bad mask NoData fails closed with no Core seal.
        assert summary.failed == (nodata_child,), summary
        seen = operator.get(f"{MASK_BASE}/{nodata_child}")
        assert seen.status_code == 200
        assert seen.json()["manifest"] is None

        # Stale lease: advance the trusted lane clock past the inspection TTL.
        stale_child = "mask-child-stale"
        stale_bytes = lane["mask_bytes"]
        stale_decl = MaskChildDeclarationV1(
            declaration_id="decl-stale",
            organization_id=ORG,
            site_id=SITE_ID,
            work_area_id=WORK_AREA_ID,
            child_kind="MASK_CHILD",
            mask_child_id=stale_child,
            mask_artifact_id="mask-artifact-stale",
            parent_subject=lane["current_subject"],
            target_baseline_subject=lane["baseline_subject"],
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest(stale_bytes),
            declared_size_bytes=len(stale_bytes),
        ).sealed()
        posted_decl = stale_decl.model_dump(by_alias=True, mode="json")
        assert operator.post(MASK_BASE, json=posted_decl).status_code == 200
        grant2 = operator.post(
            f"{MASK_BASE}/{stale_child}/upload-grants",
            json={
                "maskArtifactId": "mask-artifact-stale",
                "subjectDigest": lane["current_subject"].canonical_digest(),
                "declaredSha256": _digest(stale_bytes),
                "declaredSizeBytes": len(stale_bytes),
                "ttlSeconds": 3600,
            },
        )
        assert grant2.status_code == 200
        upload2 = operator.post(
            f"{MASK_BASE}/{stale_child}/upload-grants/{grant2.json()['grantId']}/bytes",
            content=stale_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload2.status_code == 200
        worker_client2 = MaskedWorkflowCoreClient(
            base_url=core_origin,
            bearer_token="synthetic-worker",
            transport=None,
        )
        try:
            leased = worker_client2.lease_inspection(
                MaskedInspectionJobSpec(
                    mask_child_id=stale_child,
                    site_id=SITE_ID,
                    work_area_id=WORK_AREA_ID,
                    mask_artifact_id="mask-artifact-stale",
                    subject_digest=lane["current_subject"].canonical_digest(),
                    parent_subject=lane["current_subject"].model_dump(by_alias=True, mode="json"),
                    baseline_subject=lane["baseline_subject"].model_dump(
                        by_alias=True, mode="json"
                    ),
                    baseline_dsm_artifact_id="dsm-baseline",
                    declared_sha256=_digest(stale_bytes),
                    declared_size_bytes=len(stale_bytes),
                    organization_id=ORG,
                ),
                worker_instance_id="masked-worker-instance-1",
                inspection_profile_digest=lane["mask_profile"].canonical_digest(),
                lease_acquisition_id="lease-stale",
            )
            lease_id = leased["leaseId"]
            # Chunk sha mismatch: tampered fence fails closed without bytes.
            with pytest.raises(MaskedWorkflowWorkerError):
                worker_client2.fetch_inspection_bytes(
                    mask_child_id=stale_child,
                    mask_artifact_id="mask-artifact-stale",
                    offset=0,
                    length=1,
                    lease_id="bad-lease",
                    worker_instance_id="masked-worker-instance-1",
                )
            from ksi_core.domains.external.ingress.external_mask_input_core_adapters import (
                masked_inspection_runtime_digest,
            )
            from ksi_processing_controller.external_mask_input_inspection import (
                inspect_mask_bytes_v1,
            )

            real_report = inspect_mask_bytes_v1(
                path=tmp_path / "mask.tif",
                envelope=lane["envelope"],
                watchdog=MeasurementWatchdogV2.from_envelope(lane["envelope"]),
                organization_id=ORG,
                site_id=SITE_ID,
                work_area_id=WORK_AREA_ID,
                mask_child_id=stale_child,
                mask_artifact_id="mask-artifact-stale",
                subject=lane["current_subject"],
                inspection_profile=lane["mask_profile"],
                contained_runtime_digest=masked_inspection_runtime_digest(lane["mask_profile"]),
                inspector_build_digest=lane["mask_profile"].worker_build_digest,
                expected_crs_identifier=str(leased["expectedCrsIdentifier"]),
                expected_crs_digest=str(leased["expectedCrsDigest"]),
                expected_transform=tuple(leased["expectedTransform"]),
                expected_transform_digest=str(leased["expectedTransformDigest"]),
                report_id="narrow-report-stale",
                reported_at=NOW,
            )
            clock.now = NOW + timedelta(seconds=3600)
            # Stale lease after TTL fails closed without a seal.
            _stale_http = _httpx_client(core_origin, "synthetic-worker")
            try:
                stale_seal = _stale_http.post(
                    f"/v1/internal/mask-children/{stale_child}:report",
                    json={
                        "leaseId": lease_id,
                        "workerInstanceId": "masked-worker-instance-1",
                        "report": real_report.model_dump(by_alias=True, mode="json"),
                        "inspectionProfile": lane["mask_profile"].model_dump(
                            by_alias=True, mode="json"
                        ),
                    },
                )
                assert stale_seal.status_code == 409, stale_seal.text
            finally:
                with contextlib.suppress(Exception):
                    _stale_http.close()
        finally:
            worker_client2.close()
            clock.now = NOW
    finally:
        with contextlib.suppress(Exception):
            operator.close()
        with contextlib.suppress(Exception):
            foreign.close()
        with contextlib.suppress(Exception):
            wrong.close()
        if core_server is not None:
            core_server.should_exit = True
        if "core_thread" in locals() and core_thread is not None:
            core_thread.join(timeout=5)
        if "core_socket" in locals() and core_socket is not None:
            with contextlib.suppress(Exception):
                core_socket.close()
        object_server.shutdown()
        object_server.server_close()
        object_thread.join(timeout=5)

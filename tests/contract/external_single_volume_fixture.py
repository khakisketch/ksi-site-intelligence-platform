"""Shared synthetic single-volume authority, store and report helpers.

Defaults reproduce the standalone single-volume ledger tests; keyword
overrides bind the same helpers into another durable Core graph (its
coordinator, organization, site, work order, work area and clock).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeVerdict,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeStore,
    SingleVolumeWorkerLaunchMaterialResolver,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.leasing import LeaseFence
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeMetricsV1,
)

_NOW = datetime(2026, 9, 17, tzinfo=UTC)
_POLYGON: dict[str, object] = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
}


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject(
    work_order_id: str = "work-current",
    *,
    organization_id: str = "org-a",
    site_id: str = "site-a",
) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id=organization_id,
        site_id=site_id,
        work_order_id=work_order_id,
        submission_id="submission-target",
        revision=1,
        submission_digest=_digest("submission-target"),
        manifest_digest=_digest("manifest-target"),
    )


def _binding(
    work_order_id: str = "work-current",
    *,
    organization_id: str = "org-a",
    site_id: str = "site-a",
    captured_to: datetime | None = None,
) -> ExternalVolumeInputBindingV1:
    end = captured_to if captured_to is not None else _NOW - timedelta(hours=1)
    return ExternalVolumeInputBindingV1(
        subject=_subject(work_order_id, organization_id=organization_id, site_id=site_id),
        inspection_report_digest=_digest("report-target"),
        dsm_artifact_id="dsm-target",
        observed_sha256=_digest("dsm-bytes-target"),
        observed_size_bytes=10,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=end - timedelta(hours=1),
        captured_to=end,
    )


def _execution_policy(
    *, resource_envelope_digest: str | None = None
) -> ExternalSingleVolumeExecutionPolicyV1:
    return ExternalSingleVolumeExecutionPolicyV1(
        policy_id="single-policy-a",
        version=1,
        algorithm_build_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        threshold_m=0.0,
        minimum_common_valid_fraction=0.8,
        minimum_boundary_valid_fraction=0.5,
        uncertainty_method="SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
        base_surface_method="BOUNDARY_LINEAR_INTERPOLATION_V1",
        resource_envelope_digest=resource_envelope_digest or _digest("resources"),
        authority_record_digest=_digest("policy-authority"),
        synthetic_test_only=True,
    ).sealed()


def _authority(
    *,
    work_order_id: str = "work-current",
    target_rmse_m: float | None = 0.05,
    evidence_digest: str | None = None,
    validation_policy_digest: str | None = None,
    execution_policy: ExternalSingleVolumeExecutionPolicyV1 | None = None,
    organization_id: str = "org-a",
    site_id: str = "site-a",
    work_area_id: str = "work-area-a",
    now: datetime = _NOW,
    captured_to: datetime | None = None,
) -> ExternalSingleVolumeExecutionAuthority:
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id=organization_id,
        site_id=site_id,
        work_area_id=work_area_id,
        polygon=_POLYGON,
        crs="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        analysis_vertical_reference_digest=_digest("vertical"),
    ).sealed()
    return ExternalSingleVolumeExecutionAuthority(
        organization_id=organization_id,
        site_id=site_id,
        current_work_order_id=work_order_id,
        decision_id="decision-a",
        decision_digest=_digest("decision-a"),
        compatibility_mapping_digest=_digest("single-mapping"),
        target=_binding(
            work_order_id,
            organization_id=organization_id,
            site_id=site_id,
            captured_to=captured_to,
        ),
        evidence_record_digests=(evidence_digest or _digest("evidence-target"),),
        validation_policy_digest=validation_policy_digest or _digest("validation-policy"),
        zone_snapshot=zone,
        execution_policy=execution_policy or _execution_policy(),
        authorized_actor_ids=frozenset({"operator-a", "worker-principal"}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=10),
        historical_authority_digest=_digest("single-historical-authority"),
        target_rmse_m=target_rmse_m,
        maximum_zone_cell_count=10_000,
        maximum_zone_area_m2=100_000.0,
        synthetic_test_only=True,
    )


class _AuthorityPort:
    def __init__(
        self,
        authority: ExternalSingleVolumeExecutionAuthority,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self.authority = authority
        self.currentness_coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self.revoked = False

    def resolve_for_issue(
        self, *, principal: Principal, current_work_order_id: str, decision_ref: str, now: datetime
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        a = self.authority
        if (
            self.revoked
            or principal.principal_id not in a.authorized_actor_ids
            or current_work_order_id != a.current_work_order_id
            or decision_ref != a.decision_id
            or not a.is_current_at(now)
        ):
            return None
        return a

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalSingleVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalSingleVolumeExecutionAuthority | None]:
        del principal
        yield (
            authority
            if not self.revoked and authority == self.authority and authority.is_current_at(now)
            else None
        )

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        del now
        a = self.authority
        if (
            a.historical_authority_digest != historical_authority_digest
            or a.decision_id != decision_id
            or a.decision_digest != decision_digest
            or not a.is_current_at(issued_at)
        ):
            return None
        return a


def _queue_policy() -> ExternalRelativeVolumeQueuePolicy:
    return ExternalRelativeVolumeQueuePolicy(
        lease_ttl=timedelta(minutes=5),
        deadline_after_issue=timedelta(hours=1),
        max_attempts=3,
        max_active_requests_per_organization=8,
    )


def _store(
    path: Path,
    port: _AuthorityPort,
    *,
    resolver: SingleVolumeWorkerLaunchMaterialResolver | None = None,
    now: datetime = _NOW,
) -> ExternalSingleVolumeStore:
    return ExternalSingleVolumeStore(
        DurableJournal(path / "external-single-volumes.jsonl"),
        authority_port=port,
        currentness_coordinator=port.currentness_coordinator,
        queue_policy=_queue_policy(),
        launch_material_resolver=resolver,
        clock=lambda: now,
    )


def _principal(organization_id: str = "org-a") -> Principal:
    return Principal(
        "operator-a", PrincipalKind.OPERATOR, Role.FIELD_OPERATOR, None, organization_id
    )


def _metrics(
    authority: ExternalSingleVolumeExecutionAuthority,
    *,
    base_roughness_m: float = 0.02,
    boundary_samples: int = 20,
    uncertainty_m3: float | None | str = "exact",
) -> ExternalSingleVolumeMetricsV1:
    measured_area = 40.0
    if uncertainty_m3 == "exact":
        uncertainty: float | None = (
            None
            if authority.target_rmse_m is None
            else measured_area * math.hypot(base_roughness_m, authority.target_rmse_m)
        )
    else:
        uncertainty = cast(float | None, uncertainty_m3)
    return ExternalSingleVolumeMetricsV1(
        zone_cell_count=40,
        common_valid_cell_count=40,
        zone_area_m2=40.0,
        measured_area_m2=measured_area,
        common_valid_fraction=1.0,
        cut_m3=0.0,
        fill_m3=12.0,
        net_m3=12.0,
        threshold_m=authority.execution_policy.threshold_m,
        uncertainty_m3=uncertainty,
        uncertainty_note="single epoch boundary base",
        base_roughness_m=base_roughness_m,
        boundary_cell_count=20,
        boundary_sample_count=boundary_samples,
        boundary_valid_fraction=boundary_samples / 20,
    )


def _payload(
    request_digest: str,
    authority: ExternalSingleVolumeExecutionAuthority,
    metrics: ExternalSingleVolumeMetricsV1 | None = None,
    *,
    target_dsm_digest: str | None = None,
) -> ExternalSingleVolumeMeasurementPayloadV1:
    policy = authority.execution_policy
    return ExternalSingleVolumeMeasurementPayloadV1(
        request_digest=request_digest,
        decision_digest=authority.decision_digest,
        target_dsm_digest=target_dsm_digest or authority.target.observed_sha256,
        zone_snapshot_digest=authority.zone_snapshot.canonical_digest(),
        execution_policy_digest=policy.canonical_digest(),
        algorithm_build_digest=policy.algorithm_build_digest,
        config_digest=policy.config_digest,
        metrics=metrics or _metrics(authority),
    )


def _issue_and_claim(
    store: ExternalSingleVolumeStore,
    key: str = "single-key",
    *,
    work_order_id: str = "work-current",
    organization_id: str = "org-a",
    now: datetime = _NOW,
) -> tuple[str, str, LeaseFence]:
    issued = store.issue(
        principal=_principal(organization_id),
        current_work_order_id=work_order_id,
        decision_ref="decision-a",
        idempotency_key=key,
        now=now,
    )
    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED, issued
    assert issued.record is not None and issued.record.request.request_digest is not None
    request = issued.record.request
    leased = store.claim(
        request.request_id,
        organization_id=organization_id,
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
        now=now,
    )
    assert leased.verdict is ExternalRelativeVolumeVerdict.LEASED and leased.fence is not None
    digest = request.request_digest
    assert digest is not None
    return request.request_id, digest, leased.fence

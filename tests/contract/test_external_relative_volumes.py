from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_relative_volume_authorities import (
    DefaultClosedExternalRelativeVolumeAuthorityPort,
    SyntheticExternalRelativeVolumeAuthorityPort,
)
from ksi_core.external_relative_volume_launch_material import (
    VolumeWorkerLaunchMaterialResolver,
)
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeInputCapability,
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeRecoveryError,
    ExternalRelativeVolumeStore,
    ExternalRelativeVolumeVerdict,
    build_external_relative_volume_router,
)
from ksi_core.external_validation_policy import PolicySelection, PolicySelectionStatus
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalRelativeVolumeReportV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
    external_relative_volume_report_wire_dict,
)

_NOW = datetime(2026, 9, 9, tzinfo=UTC)
_OPERATOR_TOKEN = "relative-volume-operator"  # noqa: S105 -- deterministic test token
_WORKER_TOKEN = "relative-volume-worker"  # noqa: S105 -- deterministic test token


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject(
    work_order_id: str,
    label: str,
    *,
    organization_id: str = "org-a",
    site_id: str = "site-a",
) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id=organization_id,
        site_id=site_id,
        work_order_id=work_order_id,
        submission_id=f"submission-{label}",
        revision=1,
        submission_digest=_digest(f"submission-{label}"),
        manifest_digest=_digest(f"manifest-{label}"),
    )


def _binding(
    work_order_id: str,
    label: str,
    hour: int,
    *,
    organization_id: str = "org-a",
    site_id: str = "site-a",
) -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(work_order_id, label, organization_id=organization_id, site_id=site_id),
        inspection_report_digest=_digest(f"report-{label}"),
        dsm_artifact_id=f"dsm-{label}",
        observed_sha256=_digest(f"dsm-bytes-{label}"),
        observed_size_bytes=10,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=_NOW + timedelta(hours=hour),
        captured_to=_NOW + timedelta(hours=hour + 1),
    )


def _authority(
    *,
    active: bool = True,
    organization_id: str = "org-a",
    site_id: str = "site-a",
    decision_id: str = "decision-a",
    baseline_rmse_m: float | None = 0.3,
    current_rmse_m: float | None = 0.4,
    maximum_zone_cell_count: int = 10_000_000,
    maximum_zone_area_m2: float = 1_000_000_000.0,
    synthetic_test_only: bool = True,
    valid_until: datetime | None = None,
) -> ExternalRelativeVolumeExecutionAuthority:
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id=organization_id,
        site_id=site_id,
        work_area_id="work-area-a",
        polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
        },
        crs="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        analysis_vertical_reference_digest=_digest("vertical"),
    ).sealed()
    policy = ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="volume-policy-a",
        version=1,
        algorithm_build_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_digest("resources"),
        authority_record_digest=_digest("policy-authority"),
        synthetic_test_only=True,
    ).sealed()
    return ExternalRelativeVolumeExecutionAuthority(
        organization_id=organization_id,
        site_id=site_id,
        current_work_order_id="work-current",
        decision_id=decision_id,
        decision_digest=_digest(decision_id),
        compatibility_mapping_digest=_digest("compatibility-mapping"),
        baseline=_binding(
            "work-baseline", "baseline", 0, organization_id=organization_id, site_id=site_id
        ),
        current=_binding(
            "work-current", "current", 2, organization_id=organization_id, site_id=site_id
        ),
        evidence_record_digests=(_digest("evidence-baseline"), _digest("evidence-current")),
        validation_policy_digest=_digest("validation-policy"),
        zone_snapshot=zone,
        execution_policy=policy,
        authorized_actor_ids=frozenset({"operator-a"}),
        valid_from=_NOW - timedelta(minutes=1),
        valid_until=(valid_until or _NOW + timedelta(minutes=1))
        if active
        else _NOW - timedelta(seconds=1),
        historical_authority_digest=_digest("historical-authority"),
        baseline_rmse_m=baseline_rmse_m,
        current_rmse_m=current_rmse_m,
        maximum_zone_cell_count=maximum_zone_cell_count,
        maximum_zone_area_m2=maximum_zone_area_m2,
        synthetic_test_only=synthetic_test_only,
    )


class _AuthorityPort:
    """Explicit test fixture authority; production assembly supplies the Core adapter."""

    def __init__(self, authority: ExternalRelativeVolumeExecutionAuthority) -> None:
        self.authority = authority
        self.historical_authority = authority
        self.currentness_coordinator = ExternalAuthorityCurrentnessCoordinator()

    def resolve_for_issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        if (
            principal.principal_id not in self.authority.authorized_actor_ids
            or current_work_order_id != self.authority.current_work_order_id
            or decision_ref != self.authority.decision_id
            or not self.authority.is_current_at(now)
        ):
            return None
        return self.authority

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalRelativeVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalRelativeVolumeExecutionAuthority | None]:
        del principal
        yield authority if authority == self.authority and authority.is_current_at(now) else None

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del now
        authority = self.historical_authority
        if (
            authority.historical_authority_digest != historical_authority_digest
            or authority.decision_id != decision_id
            or authority.decision_digest != decision_digest
            or not authority.is_current_at(issued_at)
        ):
            return None
        return authority


def _principal(*, organization_id: str = "org-a", principal_id: str = "operator-a") -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id=organization_id,
    )


def _store(
    tmp_path: Path,
    authority: ExternalRelativeVolumeExecutionAuthority,
    *,
    launch_material_resolver: VolumeWorkerLaunchMaterialResolver | None = None,
) -> ExternalRelativeVolumeStore:
    port = _AuthorityPort(authority)
    return ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "external-relative-volumes.jsonl"),
        authority_port=port,
        currentness_coordinator=port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        launch_material_resolver=launch_material_resolver,
        clock=lambda: _NOW,
    )


def _token_record(token: str, principal: Principal) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
    )


def _client(
    tmp_path: Path,
    authority: ExternalRelativeVolumeExecutionAuthority,
    *,
    launch_material_resolver: VolumeWorkerLaunchMaterialResolver | None = None,
) -> tuple[TestClient, str]:
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "relative-volume-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )
    work_order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Relative volume fixture",
        work_area_ids=["work-area-a"],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    current_binding = authority.current.model_copy(
        update={
            "subject": authority.current.subject.model_copy(
                update={"work_order_id": work_order.work_order_id}
            )
        }
    )
    store = _store(
        tmp_path,
        replace(
            authority,
            current_work_order_id=work_order.work_order_id,
            current=current_binding,
        ),
        launch_material_resolver=launch_material_resolver,
    )
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                _token_record(_OPERATOR_TOKEN, _principal()),
                _token_record(
                    _WORKER_TOKEN,
                    Principal(
                        principal_id="worker-principal",
                        kind=PrincipalKind.PROCESSING_WORKER,
                        role=None,
                        device_id=None,
                        organization_id="org-a",
                    ),
                ),
            ]
        ),
    )

    def capabilities(
        *_args: Any, **_kwargs: Any
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]:
        return (
            ExternalRelativeVolumeInputCapability(
                role="BASELINE_DSM",
                download_url="https://storage.invalid/baseline",
                required_headers={"x-bound": "baseline"},
                expires_at=_NOW + timedelta(minutes=5),
            ),
            ExternalRelativeVolumeInputCapability(
                role="CURRENT_DSM",
                download_url="https://storage.invalid/current",
                required_headers={"x-bound": "current"},
                expires_at=_NOW + timedelta(minutes=5),
            ),
        )

    app.include_router(
        build_external_relative_volume_router(
            store,
            input_capability_issuer=capabilities,
            work_orders=work_orders,
            clock=lambda: _NOW,
        )
    )
    return TestClient(app), work_order.work_order_id


def _headers(token: str, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _fence() -> LeaseFence:
    return LeaseFence(str(uuid4()), str(uuid4()), 1)


def _payload(
    request_digest: str, authority: ExternalRelativeVolumeExecutionAuthority
) -> ExternalRelativeVolumeMeasurementPayloadV1:
    metrics = ExternalVolumeMetricsV1(
        zone_cell_count=10,
        common_valid_cell_count=10,
        zone_area_m2=10.0,
        measured_area_m2=10.0,
        common_valid_fraction=1.0,
        cut_m3=1.0,
        fill_m3=5.0,
        net_m3=4.0,
        threshold_m=authority.execution_policy.threshold_m,
        uncertainty_m3=5.0,
        uncertainty_note="independent epoch RMSE bound",
    )
    return ExternalRelativeVolumeMeasurementPayloadV1(
        request_digest=request_digest,
        decision_digest=authority.decision_digest,
        baseline_dsm_digest=authority.baseline.observed_sha256,
        current_dsm_digest=authority.current.observed_sha256,
        zone_snapshot_digest=authority.zone_snapshot.canonical_digest(),
        execution_policy_digest=authority.execution_policy.canonical_digest(),
        algorithm_build_digest=authority.execution_policy.algorithm_build_digest,
        config_digest=authority.execution_policy.config_digest,
        metrics=metrics,
    )


def test_issue_is_durable_and_same_authorized_intent_never_duplicates_numeric_work(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)

    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-a",
        now=_NOW,
    )
    same_intent_other_key = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-b",
        now=_NOW,
    )

    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED
    assert issued.record is not None
    assert issued.record.request.request_digest is not None
    assert same_intent_other_key.record == issued.record
    assert same_intent_other_key.created is False
    assert [raw["kind"] for raw in store.journal_records()].count(
        "external-relative-volume-issued"
    ) == 1


def test_fenced_report_is_core_sealed_and_checks_policy_coverage_and_uncertainty(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-a",
        now=_NOW,
    )
    assert issued.record is not None
    fence = _fence()
    claimed = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        now=_NOW,
    )
    assert claimed.verdict is ExternalRelativeVolumeVerdict.LEASED
    report = store.record_observed_report(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            payload=_payload(issued.record.request.request_digest or "", authority),
            computed_at=_NOW,
        ),
        now=_NOW,
    )

    assert report.verdict is ExternalRelativeVolumeVerdict.REPORTED
    assert report.record is not None and report.record.report is not None
    assert report.record.report.report_digest is not None
    assert report.record.report.payload.metrics.cut_m3 == 1.0
    assert report.record.report.payload.metrics.fill_m3 == 5.0
    assert report.record.report.payload.metrics.net_m3 == 4.0
    assert report.record.report.payload.metrics.uncertainty_m3 == pytest.approx(5.0)
    assert math.isclose(
        report.record.report.payload.metrics.uncertainty_m3 or 0.0,
        10.0 * math.hypot(0.3, 0.4),
    )


def test_stale_authority_never_mints_a_request(tmp_path: Path) -> None:
    store = _store(tmp_path, _authority(active=False))

    denied = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-a",
        now=_NOW,
    )

    assert denied.verdict is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    assert denied.record is None
    assert store.journal_records() == ()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("baseline_rmse_m", 0),
        ("current_rmse_m", 0),
        ("maximum_zone_cell_count", 10_000_000.0),
        ("maximum_zone_area_m2", 1_000_000_000),
        ("synthetic_test_only", 1),
    ),
)
def test_execution_authority_constructor_rejects_noncanonical_snapshot_scalars(
    field: str, value: object
) -> None:
    """Live producers cannot create values strict replay would reject."""
    kwargs: dict[str, object] = {field: value}

    with pytest.raises(ValueError):
        _authority(**cast(Any, kwargs))


def test_execution_authority_requires_explicit_resource_caps() -> None:
    """A Core authority record cannot activate volume work with inherited numeric defaults."""
    authority = _authority()
    constructor_values = {
        field: getattr(authority, field)
        for field in authority.__dataclass_fields__
        if field not in {"maximum_zone_cell_count", "maximum_zone_area_m2"}
    }

    with pytest.raises(TypeError, match="maximum_zone"):
        ExternalRelativeVolumeExecutionAuthority(**constructor_values)


def test_execution_authority_requires_a_sha256_compatibility_mapping_identity() -> None:
    """A string policy label cannot stand in for the sealed mapping content identity."""
    with pytest.raises(ValueError, match="compatibility mapping"):
        replace(_authority(), compatibility_mapping_digest="synthetic-mapping-label")


def test_execution_authority_requires_a_sha256_historical_identity() -> None:
    """The independent history lookup key is an exact digest, never a label."""
    with pytest.raises(ValueError, match="historical authority"):
        replace(_authority(), historical_authority_digest="not-a-digest")


def test_issue_refuses_a_malformed_historical_identity_from_an_authority_port(
    tmp_path: Path,
) -> None:
    """A malformed port result cannot be canonicalized and journaled by a live issue."""
    authority = _authority()
    object.__setattr__(authority, "historical_authority_digest", "not-a-digest")
    store = _store(tmp_path, authority)

    result = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="malformed-history-key",
        now=_NOW,
    )

    assert result.verdict is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    assert store.journal_records() == ()


def test_historical_authority_lookup_is_scoped_by_its_owned_identity_and_issue_binding() -> None:
    """Replay must not use a request digest that did not exist when authority was recorded."""
    authority = _authority()
    port = _AuthorityPort(authority)

    assert (
        port.resolve_historical(
            historical_authority_digest=authority.historical_authority_digest,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
            issued_at=_NOW,
            now=_NOW,
        )
        == authority
    )
    assert (
        port.resolve_historical(
            historical_authority_digest=_digest("different-history"),
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
            issued_at=_NOW,
            now=_NOW,
        )
        is None
    )


def test_synthetic_relative_volume_authority_is_explicit_and_historical_identity_bound() -> None:
    """Only declared synthetic authority records may open the local volume seam."""
    authority = _authority()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    port = SyntheticExternalRelativeVolumeAuthorityPort(
        (authority,), currentness_coordinator=coordinator
    )

    assert (
        port.resolve_for_issue(
            principal=_principal(),
            current_work_order_id=authority.current_work_order_id,
            decision_ref=authority.decision_id,
            now=_NOW,
        )
        == authority
    )
    assert (
        port.resolve_historical(
            historical_authority_digest=authority.historical_authority_digest,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
            issued_at=_NOW,
            now=_NOW + timedelta(days=1),
        )
        == authority
    )
    assert (
        DefaultClosedExternalRelativeVolumeAuthorityPort(
            currentness_coordinator=coordinator
        ).resolve_for_issue(
            principal=_principal(),
            current_work_order_id=authority.current_work_order_id,
            decision_ref=authority.decision_id,
            now=_NOW,
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("baseline_rmse_m", 0),
        ("maximum_zone_cell_count", 10_000_000.0),
        ("maximum_zone_area_m2", 1_000_000_000),
    ),
)
def test_issue_rejects_mutated_noncanonical_authority_before_journal_append(
    tmp_path: Path, field: str, value: object
) -> None:
    """Unsafe in-memory mutation cannot poison durable replay before issue rejects it."""
    authority = _authority()
    object.__setattr__(authority, field, value)
    store = _store(tmp_path, authority)

    denied = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key=f"noncanonical-live-{field}",
        now=_NOW,
    )

    assert denied.verdict is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    assert denied.record is None
    assert store.journal_records() == ()
    store._journal.close()  # noqa: SLF001 -- reopen proves no invalid durable event was written
    restarted = _store(tmp_path, _authority())
    assert restarted.journal_records() == ()


def test_canonical_authority_with_float_int_and_none_restarts_after_issue(tmp_path: Path) -> None:
    """Canonical float RMSE, integer count and null RMSE remain durable and replayable."""
    authority = _authority(
        baseline_rmse_m=0.0,
        current_rmse_m=None,
        maximum_zone_cell_count=1,
        maximum_zone_area_m2=1.0,
    )
    store = _store(tmp_path, authority)

    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="canonical-authority-restart",
        now=_NOW,
    )

    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED
    assert issued.record is not None
    store._journal.close()  # noqa: SLF001 -- reopen same durable journal for replay assertion
    restarted = _store(tmp_path, authority)
    recovered = restarted.get(issued.record.request.request_id, organization_id="org-a")
    assert recovered == issued.record


def test_store_requires_an_explicit_core_owned_queue_policy(tmp_path: Path) -> None:
    authority = _authority()
    port = _AuthorityPort(authority)

    with pytest.raises(TypeError, match="queue_policy"):
        cast(Any, ExternalRelativeVolumeStore)(
            DurableJournal(tmp_path / "relative-volumes.jsonl"),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
        )


def test_revoked_authority_cannot_be_claimed_after_a_request_was_issued(tmp_path: Path) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-a",
        now=_NOW,
    )
    assert issued.record is not None
    # This is an explicit test-only authority adapter.  Its current binding is
    # changed after issuance to model a policy/evidence revocation.
    port = store._authority_port  # noqa: SLF001
    assert isinstance(port, _AuthorityPort)
    port.authority = _authority(active=False)

    denied = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=_fence(),
        now=_NOW,
    )

    assert denied.verdict is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    assert issued.record.request.request_id not in [
        raw.get("requestRef") for raw in store.journal_records() if raw["kind"].endswith("leased")
    ]


def test_replay_rejects_a_report_with_a_substituted_decision_binding(tmp_path: Path) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="request-key-a",
        now=_NOW,
    )
    assert issued.record is not None
    request_ref = issued.record.request.request_id
    fence = _fence()
    assert (
        store.claim(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.record_observed_report(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=_payload(issued.record.request.request_digest or "", authority),
                computed_at=_NOW,
            ),
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )

    tampered = list(store.journal_records())
    last = dict(tampered[-1])
    report = dict(last["report"])
    payload = dict(report["payload"])
    payload["decisionDigest"] = _digest("substituted-decision")
    report["payload"] = payload
    report["measurementPayloadDigest"] = ExternalRelativeVolumeMeasurementPayloadV1.model_validate(
        payload
    ).canonical_digest()
    report["reportDigest"] = None
    report = external_relative_volume_report_wire_dict(
        ExternalRelativeVolumeReportV1.model_validate(report).sealed()
    )
    last["report"] = report
    last["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in last.items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    tampered[-1] = last
    journal = DurableJournal(tmp_path / "tampered-relative-volumes.jsonl")
    for event in tampered:
        journal.append(event)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError, match="report"):
        ExternalRelativeVolumeStore(
            DurableJournal(tmp_path / "tampered-relative-volumes.jsonl"),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


def test_router_derives_scope_and_keeps_private_worker_input_out_of_human_view(
    tmp_path: Path,
) -> None:
    authority = _authority()
    client, work_order_id = _client(tmp_path, authority)
    issue_path = f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests"

    issued = client.post(
        issue_path,
        headers=_headers(_OPERATOR_TOKEN, idempotency_key="browser-key"),
        json={"decisionRef": "decision-a"},
    )
    assert issued.status_code == 201, issued.text
    public = issued.json()["request"]
    assert set(public) == {
        "requestRef",
        "status",
        "currentWorkOrderId",
        "decisionDigest",
        "issuedAt",
        "deadlineAt",
        "reportRef",
        "reportDigest",
    }
    assert "idempotencyKey" not in public and "baseline" not in public
    request_ref = public["requestRef"]
    assert client.get(issue_path, headers=_headers(_WORKER_TOKEN)).status_code == 403

    fence = _fence()
    lease_body = {
        "workerInstanceId": fence.worker_instance_id,
        "leaseAcquisitionId": fence.lease_acquisition_id,
        "leaseGeneration": fence.lease_generation,
    }
    leased = client.post(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/lease",
        headers=_headers(_WORKER_TOKEN),
        json=lease_body,
    )
    assert leased.status_code == 201, leased.text
    worker_headers = {
        **_headers(_WORKER_TOKEN),
        "X-KSI-Worker-Instance-Id": fence.worker_instance_id,
        "X-KSI-Lease-Acquisition-Id": fence.lease_acquisition_id,
        "X-KSI-Lease-Generation": str(fence.lease_generation),
    }
    worker_input = client.get(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/input",
        headers=worker_headers,
    )
    # A router with no policy/evidence resolver cannot mint a partial worker
    # launch.  Assembly must inject the Core-owned material resolver.
    assert worker_input.status_code == 422, worker_input.text
    assert worker_input.json()["verdict"] == ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    after_lease = client.get(
        f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests/{request_ref}",
        headers=_headers(_OPERATOR_TOKEN),
    )
    assert after_lease.status_code == 200
    assert set(after_lease.json()) == set(public)
    assert after_lease.json()["status"] == "RUNNING"

    invalid_time_report = client.post(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/report",
        headers=worker_headers,
        json={
            "payload": _payload(_digest("unknown-request"), authority).model_dump(
                by_alias=True, mode="json"
            ),
            "computedAt": "2026-09-09T09:00:00+09:00",
        },
    )
    assert invalid_time_report.status_code == 422


def test_pending_route_filters_before_limit_by_processing_worker_organization(
    tmp_path: Path,
) -> None:
    authority_a = _authority()
    store = _store(tmp_path, authority_a)
    issued_a = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="org-a-key",
        now=_NOW,
    )
    assert issued_a.record is not None
    port = store._authority_port  # noqa: SLF001
    assert isinstance(port, _AuthorityPort)
    authority_b = _authority(organization_id="org-b", decision_id="decision-b")
    port.authority = authority_b
    port.historical_authority = authority_b
    issued_b = store.issue(
        principal=_principal(organization_id="org-b"),
        current_work_order_id="work-current",
        decision_ref="decision-b",
        idempotency_key="org-b-key",
        now=_NOW,
    )
    assert issued_b.record is not None
    worker_b = Principal(
        principal_id="worker-b",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-b",
    )
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record("relative-volume-worker-b", worker_b)]))
    app.include_router(
        build_external_relative_volume_router(
            store, input_capability_issuer=lambda *_args, **_kwargs: None, clock=lambda: _NOW
        )
    )

    response = TestClient(app).get(
        "/v1/internal/external-validation/relative-volumes?limit=1",
        headers=_headers("relative-volume-worker-b"),
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"requestRef": issued_b.record.request.request_id, "issuedAt": "2026-09-09T00:00:00Z"}
    ]


def test_queue_capacity_is_tenant_scoped_and_exact_retries_do_not_consume_a_second_slot(
    tmp_path: Path,
) -> None:
    authority_a = _authority()
    port = _AuthorityPort(authority_a)
    store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "relative-volume-capacity.jsonl"),
        authority_port=port,
        currentness_coordinator=port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=1,
        ),
        clock=lambda: _NOW,
    )
    first = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="first-key",
        now=_NOW,
    )
    assert first.record is not None
    authority_b = _authority(decision_id="decision-b")
    port.authority = authority_b
    port.historical_authority = authority_b

    exact_retry = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="first-key",
        now=_NOW,
    )
    blocked = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-b",
        idempotency_key="second-key",
        now=_NOW,
    )

    assert exact_retry.verdict is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    assert exact_retry.record == first.record
    assert blocked.verdict is ExternalRelativeVolumeVerdict.QUEUE_FULL
    assert [raw["kind"] for raw in store.journal_records()].count(
        "external-relative-volume-issued"
    ) == 1


def test_terminal_states_never_issue_fresh_worker_inputs(tmp_path: Path) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="success-key",
        now=_NOW,
    )
    assert issued.record is not None
    request_ref = issued.record.request.request_id
    fence = _fence()
    assert (
        store.claim(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.record_observed_report(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                _payload(issued.record.request.request_digest or "", authority), _NOW
            ),
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )
    worker = Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )

    assert (
        store.worker_input(
            issued.record.request.request_id, principal=worker, fence=fence, now=_NOW
        ).verdict
        is ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE
    )

    failed_store = _store(tmp_path / "failed", authority)
    failed = failed_store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="failed-key",
        now=_NOW,
    )
    assert failed.record is not None
    failed_fence = _fence()
    assert (
        failed_store.claim(
            failed.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=failed_fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        failed_store.record_incomplete_failure(
            failed.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=failed_fence,
            reason="NO_COMMON_COVERAGE",
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.FAILED
    )
    assert (
        failed_store.worker_input(
            failed.record.request.request_id, principal=worker, fence=failed_fence, now=_NOW
        ).verdict
        is ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE
    )


def test_completed_report_retries_use_historical_authority_after_withdrawal(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="reported-retry-key",
        now=_NOW,
    )
    assert issued.record is not None
    request_ref = issued.record.request.request_id
    request_digest = issued.record.request.request_digest or ""
    fence = _fence()
    assert (
        store.claim(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    observed = ExternalRelativeVolumeObservedReportInput(_payload(request_digest, authority), _NOW)
    assert (
        store.record_observed_report(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=observed,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )
    port = store._authority_port  # noqa: SLF001
    assert isinstance(port, _AuthorityPort)
    port.authority = _authority(active=False)

    assert (
        store.record_observed_report(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=observed,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )
    assert (
        store.record_observed_report(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=_fence(),
            observed=observed,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORT_CONFLICT
    )

    worker = Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record(_WORKER_TOKEN, worker)]))
    app.include_router(
        build_external_relative_volume_router(
            store, input_capability_issuer=lambda *_args, **_kwargs: None, clock=lambda: _NOW
        )
    )
    report_path = f"/v1/internal/external-validation/relative-volumes/{request_ref}/report"
    report_body = {
        "payload": observed.payload.model_dump(by_alias=True, mode="json"),
        "computedAt": _NOW.isoformat().replace("+00:00", "Z"),
    }
    headers = {
        **_headers(_WORKER_TOKEN),
        "X-KSI-Worker-Instance-Id": fence.worker_instance_id,
        "X-KSI-Lease-Acquisition-Id": fence.lease_acquisition_id,
        "X-KSI-Lease-Generation": str(fence.lease_generation),
    }
    same = TestClient(app).post(report_path, headers=headers, json=report_body)
    assert same.status_code == 201, same.text
    assert same.json()["verdict"] == ExternalRelativeVolumeVerdict.REPORTED.value
    conflict = TestClient(app).post(
        report_path,
        headers={
            **headers,
            "X-KSI-Lease-Acquisition-Id": str(uuid4()),
        },
        json=report_body,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["verdict"] == ExternalRelativeVolumeVerdict.REPORT_CONFLICT.value


@pytest.mark.parametrize(
    "mutation", ("queued", "actor", "acquisition", "generation", "time", "duplicate")
)
def test_replay_rejects_terminal_failure_without_its_exact_leased_lineage(
    tmp_path: Path, mutation: str
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key=f"failure-{mutation}",
        now=_NOW,
    )
    assert issued.record is not None
    fence = _fence()
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.record_incomplete_failure(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            reason="NO_COMMON_COVERAGE",
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.FAILED
    )
    events = list(deepcopy(store.journal_records()))
    failure = events[-1]
    assert failure["kind"] == "external-relative-volume-failed"
    assert failure.get("authenticatedActorId") == "worker-principal"
    assert failure.get("workerInstanceId") == fence.worker_instance_id
    assert failure.get("leaseAcquisitionId") == fence.lease_acquisition_id
    assert failure.get("leaseGeneration") == fence.lease_generation
    assert failure.get("failedAt") == _NOW.isoformat()

    if mutation == "queued":
        events = [events[0], failure]
    elif mutation == "actor":
        failure["authenticatedActorId"] = "other-worker"
    elif mutation == "acquisition":
        failure["leaseAcquisitionId"] = str(uuid4())
    elif mutation == "generation":
        failure["leaseGeneration"] = fence.lease_generation + 1
    elif mutation == "time":
        failure["failedAt"] = (_NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    else:
        events.append(deepcopy(failure))
    failure["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in failure.items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    if mutation == "duplicate":
        events[-1]["eventDigest"] = failure["eventDigest"]

    journal_path = tmp_path / f"forged-failure-{mutation}.jsonl"
    journal = DurableJournal(journal_path)
    for event in events:
        journal.append(event)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError, match="failure"):
        ExternalRelativeVolumeStore(
            DurableJournal(journal_path),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


@pytest.mark.parametrize(
    ("event_index", "field", "substitution"),
    (
        (0, "version", True),
        (1, "leaseGeneration", True),
        (1, "workerInstanceId", 123),
        (1, "leaseAcquisitionId", 123),
        (1, "authenticatedActorId", 123),
        (2, "leaseGeneration", True),
        (2, "workerInstanceId", 123),
        (2, "leaseAcquisitionId", 123),
        (2, "authenticatedActorId", 123),
        (2, "reason", 123),
        (2, "reason", "_INVALID_PUBLIC_REASON"),
    ),
)
def test_replay_rejects_rehashed_noncanonical_authority_scalar_types(
    tmp_path: Path, event_index: int, field: str, substitution: object
) -> None:
    """A resealed JSON type substitution cannot manufacture replayable authority."""
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key=f"strict-replay-{event_index}-{field}",
        now=_NOW,
    )
    assert issued.record is not None
    fence = _fence()
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.record_incomplete_failure(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            reason="NO_COMMON_COVERAGE",
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.FAILED
    )
    events = deepcopy(store.journal_records())
    event = events[event_index]
    event[field] = substitution
    event["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in event.items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    journal_path = tmp_path / f"strict-replay-{event_index}-{field}.jsonl"
    journal = DurableJournal(journal_path)
    for raw in events:
        journal.append(raw)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError):
        ExternalRelativeVolumeStore(
            DurableJournal(journal_path),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


@pytest.mark.parametrize(
    ("path", "substitution"),
    (
        (("decisionId",), 123),
        (("evidenceRecordDigests", 0), 123),
        (("authorizedActorIds", 0), 123),
        (("baseline", "subject", "organizationId"), 123),
        (("baseline", "subject", "revision"), True),
        (("baseline", "observedSizeBytes"), True),
        (("zoneSnapshot", "revision"), True),
        (("executionPolicy", "thresholdM"), 1),
        (("executionPolicy", "minimumCommonValidFraction"), 1),
        (("executionPolicy", "syntheticTestOnly"), 1),
        (("baselineRmseM",), 0),
        (("currentRmseM",), 1),
        (("maximumZoneCellCount",), 10_000_000.0),
        (("maximumZoneAreaM2",), 1_000_000_000),
        (("syntheticTestOnly",), 1),
    ),
)
def test_replay_rejects_rehashed_noncanonical_issued_authority_snapshot_types(
    tmp_path: Path, path: tuple[str | int, ...], substitution: object
) -> None:
    """Rehashed nested snapshot coercions cannot recreate historical authority."""
    initial = _authority(decision_id="123", baseline_rmse_m=0.0, current_rmse_m=1.0)
    authority = replace(
        initial,
        authorized_actor_ids=frozenset({"123", "operator-a"}),
        execution_policy=initial.execution_policy.model_copy(
            update={
                "threshold_m": 1.0,
                "minimum_common_valid_fraction": 1.0,
                "policy_digest": None,
            }
        ).sealed(),
    )
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="123",
        idempotency_key="nested-snapshot-raw-types",
        now=_NOW,
    )
    assert issued.record is not None

    events = deepcopy(store.journal_records())
    snapshot: Any = events[0]["authority"]
    for segment in path[:-1]:
        snapshot = snapshot[segment]
    snapshot[path[-1]] = substitution
    events[0]["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in events[0].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    journal_path = tmp_path / "forged-nested-authority-types.jsonl"
    journal = DurableJournal(journal_path)
    for event in events:
        journal.append(event)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError):
        ExternalRelativeVolumeStore(
            DurableJournal(journal_path),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


def test_replay_rejects_rehashed_malformed_historical_authority_identity(tmp_path: Path) -> None:
    """A cooperating history port cannot make a non-digest snapshot replayable."""
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="malformed-history-replay",
        now=_NOW,
    )
    assert issued.record is not None

    events = deepcopy(store.journal_records())
    snapshot: Any = events[0]["authority"]
    snapshot["historicalAuthorityDigest"] = "not-a-digest"
    events[0]["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in events[0].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    journal_path = tmp_path / "forged-malformed-history-identity.jsonl"
    journal = DurableJournal(journal_path)
    for event in events:
        journal.append(event)
    journal.close()
    object.__setattr__(authority, "historical_authority_digest", "not-a-digest")
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError, match="malformed historical"):
        ExternalRelativeVolumeStore(
            DurableJournal(journal_path),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


def test_input_route_rechecks_terminal_transition_after_capability_issuance(tmp_path: Path) -> None:
    store, authority, _ = _launch_ready_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="input-race-key",
        now=_NOW,
    )
    assert issued.record is not None
    request_ref = issued.record.request.request_id
    fence = _fence()
    assert (
        store.claim(
            request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    worker = Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record(_WORKER_TOKEN, worker)]))

    def terminal_issuer(
        *_args: Any, **_kwargs: Any
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]:
        assert (
            store.record_incomplete_failure(
                request_ref,
                organization_id="org-a",
                principal_id="worker-principal",
                fence=fence,
                reason="NO_COMMON_COVERAGE",
                now=_NOW,
            ).verdict
            is ExternalRelativeVolumeVerdict.FAILED
        )
        return (
            ExternalRelativeVolumeInputCapability(
                role="BASELINE_DSM",
                download_url="https://storage.invalid/baseline",
                required_headers={},
                expires_at=_NOW + timedelta(minutes=5),
            ),
            ExternalRelativeVolumeInputCapability(
                role="CURRENT_DSM",
                download_url="https://storage.invalid/current",
                required_headers={},
                expires_at=_NOW + timedelta(minutes=5),
            ),
        )

    app.include_router(
        build_external_relative_volume_router(
            store, input_capability_issuer=terminal_issuer, clock=lambda: _NOW
        )
    )
    response = TestClient(app).get(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/input",
        headers={
            **_headers(_WORKER_TOKEN),
            "X-KSI-Worker-Instance-Id": fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(fence.lease_generation),
        },
    )

    assert response.status_code == 409
    assert response.json()["verdict"] == ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE


def test_queue_capacity_admits_at_most_one_concurrent_new_request_per_organization(
    tmp_path: Path,
) -> None:
    authority_a = _authority(decision_id="decision-a")
    authority_b = _authority(decision_id="decision-b")

    class MultiAuthorityPort(_AuthorityPort):
        def __init__(self) -> None:
            super().__init__(authority_a)
            self._authorities = {
                authority_a.decision_id: authority_a,
                authority_b.decision_id: authority_b,
            }
            self._local = threading.local()

        def resolve_for_issue(
            self,
            *,
            principal: Principal,
            current_work_order_id: str,
            decision_ref: str,
            now: datetime,
        ) -> ExternalRelativeVolumeExecutionAuthority | None:
            del principal, current_work_order_id, now
            authority = self._authorities.get(decision_ref)
            self._local.authority = authority
            return authority

        @contextmanager
        def guard_current(
            self,
            *,
            authority: ExternalRelativeVolumeExecutionAuthority,
            principal: Principal,
            now: datetime,
        ) -> Iterator[ExternalRelativeVolumeExecutionAuthority | None]:
            del principal
            yield authority if authority.is_current_at(now) else None

    port = MultiAuthorityPort()
    store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "relative-volume-concurrent-capacity.jsonl"),
        authority_port=port,
        currentness_coordinator=port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=1,
        ),
        clock=lambda: _NOW,
    )

    def issue(decision_ref: str) -> ExternalRelativeVolumeVerdict:
        return store.issue(
            principal=_principal(),
            current_work_order_id="work-current",
            decision_ref=decision_ref,
            idempotency_key=f"concurrent-{decision_ref}",
            now=_NOW,
        ).verdict

    with ThreadPoolExecutor(max_workers=2) as executor:
        verdicts = set(executor.map(issue, ("decision-a", "decision-b")))

    assert verdicts == {
        ExternalRelativeVolumeVerdict.ISSUED,
        ExternalRelativeVolumeVerdict.QUEUE_FULL,
    }


def test_exact_idempotency_retry_is_a_historical_read_after_current_authority_withdrawal(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="retry-key",
        now=_NOW,
    )
    assert issued.record is not None
    port = store._authority_port  # noqa: SLF001
    assert isinstance(port, _AuthorityPort)
    port.authority = _authority(active=False)

    exact = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="retry-key",
        now=_NOW,
    )
    changed = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-b",
        idempotency_key="retry-key",
        now=_NOW,
    )

    assert exact.verdict is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    assert exact.record == issued.record
    assert changed.verdict is ExternalRelativeVolumeVerdict.IDEMPOTENCY_CONFLICT
    assert [raw["kind"] for raw in store.journal_records()] == ["external-relative-volume-issued"]


def test_replay_recomputes_secondary_idempotency_natural_binding(tmp_path: Path) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    first = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="first-key",
        now=_NOW,
    )
    assert first.record is not None
    assert (
        store.issue(
            principal=_principal(),
            current_work_order_id="work-current",
            decision_ref="decision-a",
            idempotency_key="second-key",
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    )
    events = deepcopy(store.journal_records())
    assert events[-1]["kind"] == "external-relative-volume-idempotency-bound"
    events[-1]["idempotency"]["fingerprint"] = _digest("forged-natural")
    events[-1]["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in events[-1].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    journal_path = tmp_path / "forged-secondary-idempotency.jsonl"
    journal = DurableJournal(journal_path)
    for event in events:
        journal.append(event)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError, match="idempotency"):
        ExternalRelativeVolumeStore(
            DurableJournal(journal_path),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


@pytest.mark.parametrize(
    ("forged_baseline_rmse", "forged_current_rmse", "forged_uncertainty"),
    ((3.0, 4.0, 50.0), (None, None, None)),
)
def test_replay_requires_full_independent_historical_authority_for_uncertainty(
    tmp_path: Path,
    forged_baseline_rmse: float | None,
    forged_current_rmse: float | None,
    forged_uncertainty: float | None,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="history-key",
        now=_NOW,
    )
    assert issued.record is not None
    fence = _fence()
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.record_observed_report(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                _payload(issued.record.request.request_digest or "", authority), _NOW
            ),
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )

    events = deepcopy(store.journal_records())
    events[0]["authority"]["baselineRmseM"] = forged_baseline_rmse
    events[0]["authority"]["currentRmseM"] = forged_current_rmse
    events[0]["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in events[0].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    report = dict(events[-1]["report"])
    payload = deepcopy(report["payload"])
    payload["metrics"]["uncertaintyM3"] = forged_uncertainty
    report["payload"] = payload
    report["measurementPayloadDigest"] = ExternalRelativeVolumeMeasurementPayloadV1.model_validate(
        payload
    ).canonical_digest()
    report["reportDigest"] = None
    events[-1]["report"] = external_relative_volume_report_wire_dict(
        ExternalRelativeVolumeReportV1.model_validate(report).sealed()
    )
    events[-1]["eventDigest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in events[-1].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    journal = DurableJournal(tmp_path / f"forged-{forged_uncertainty}.jsonl")
    for event in events:
        journal.append(event)
    journal.close()
    port = _AuthorityPort(authority)

    with pytest.raises(ExternalRelativeVolumeRecoveryError, match="historical"):
        ExternalRelativeVolumeStore(
            DurableJournal(tmp_path / f"forged-{forged_uncertainty}.jsonl"),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            clock=lambda: _NOW,
        )


def test_generation_zero_claim_gets_core_fence_and_retries_without_second_append(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="core-issued-generation",
        now=_NOW,
    )
    assert issued.record is not None
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)

    first = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=initial,
        now=_NOW,
    )
    assert first.verdict is ExternalRelativeVolumeVerdict.LEASED
    assert first.record is not None and first.record.lease is not None
    assert first.record.lease.fence is not None
    granted = first.record.lease.fence
    assert granted.worker_instance_id == initial.worker_instance_id
    assert granted.lease_acquisition_id == initial.lease_acquisition_id
    assert granted.lease_generation == 1
    first_expiry = first.record.lease.expires_at

    retry = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=initial,
        now=_NOW,
    )
    assert retry.verdict is ExternalRelativeVolumeVerdict.LEASED
    assert retry.record is not None and retry.record.lease is not None
    assert retry.record.lease.fence == granted
    assert retry.record.lease.expires_at == first_expiry
    assert retry.record.attempts == 1
    assert [raw["kind"] for raw in store.journal_records()].count(
        "external-relative-volume-leased"
    ) == 1


@pytest.mark.parametrize("generation", (-1, True))
def test_generation_zero_is_the_only_new_volume_claim_sentinel(
    tmp_path: Path, generation: object
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key=f"invalid-generation-{generation!r}",
        now=_NOW,
    )
    assert issued.record is not None
    result = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), cast(Any, generation)),
        now=_NOW,
    )
    assert result.verdict is ExternalRelativeVolumeVerdict.INVALID_LEASE_FENCE


def test_relative_volume_lease_route_returns_core_issued_fence_for_generation_zero(
    tmp_path: Path,
) -> None:
    client, work_order_id = _client(tmp_path, _authority())
    issue = client.post(
        f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
        headers=_headers(_OPERATOR_TOKEN, idempotency_key="lease-route"),
        json={"decisionRef": "decision-a"},
    )
    assert issue.status_code == 201
    request_ref = issue.json()["request"]["requestRef"]
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    body = {
        "workerInstanceId": initial.worker_instance_id,
        "leaseAcquisitionId": initial.lease_acquisition_id,
        "leaseGeneration": 0,
    }
    first = client.post(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/lease",
        headers=_headers(_WORKER_TOKEN),
        json=body,
    )
    assert first.status_code == 201, first.text
    assert first.json()["fence"] == {
        "workerInstanceId": initial.worker_instance_id,
        "leaseAcquisitionId": initial.lease_acquisition_id,
        "leaseGeneration": 1,
    }
    assert first.json()["leaseExpiresAt"]
    retry = client.post(
        f"/v1/internal/external-validation/relative-volumes/{request_ref}/lease",
        headers=_headers(_WORKER_TOKEN),
        json=body,
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["fence"] == first.json()["fence"]
    assert retry.json()["leaseExpiresAt"] == first.json()["leaseExpiresAt"]


class _StaticVolumePolicyRegistry:
    def __init__(
        self,
        policy: ExternalValidationPolicyV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.policy = policy
        self.coordinator = coordinator
        self.locally_permitted_until: datetime | None = None
        self.subjects: tuple[SealedExternalSubjectV1, ...] = ()

    def select_for_use(
        self, use: str, subjects: tuple[SealedExternalSubjectV1, ...]
    ) -> PolicySelection:
        assert use == "RELATIVE_VOLUME"
        assert subjects == self.subjects
        return PolicySelection(PolicySelectionStatus.ACTIVE, self.policy, None)

    def resolve(self, digest: str) -> PolicySelection:
        if digest != self.policy.policy_digest:
            return PolicySelection(PolicySelectionStatus.POLICY_NOT_FOUND, None, "POLICY_NOT_FOUND")
        return PolicySelection(PolicySelectionStatus.ACTIVE, self.policy, None)

    def locally_current_use_permitted(
        self,
        digest: str,
        *,
        use: str,
        subjects: tuple[SealedExternalSubjectV1, ...],
        at: datetime,
    ) -> bool:
        return (
            digest == self.policy.policy_digest
            and use == "RELATIVE_VOLUME"
            and subjects == self.subjects
            and (self.locally_permitted_until is None or at < self.locally_permitted_until)
        )


class _StaticVolumeEvidence:
    def __init__(
        self,
        records: dict[str, tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]],
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.records = records
        self.coordinator = coordinator
        self.locally_current = True

    def record_for_current_use(
        self, digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        value = self.records.get(digest)
        if value is None or value[0].subject_digest != subject.canonical_digest():
            return None
        if value[0].policy_digest != policy_digest:
            return None
        return value

    def record_for_locally_current_use(
        self, digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        if not self.locally_current:
            return None
        return self.record_for_current_use(digest, subject=subject, policy_digest=policy_digest)


def _volume_launch_policy() -> ExternalValidationPolicyV1:
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1_024,
        max_streamed_bytes=1_024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8_192,
        max_sample_bytes=8_192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16_384,
        max_workspace_bytes=16_384,
        max_output_bytes=16_384,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=5.0,
        max_retry_attempts=1,
    ).sealed()
    return ExternalValidationPolicyV1(
        policy_id="validation-policy-a",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("policy-parser"),
        grammar_digest=_digest("policy-grammar"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("validation-policy-authority"),
        inspection_rule_ids=(),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _volume_evidence_material(
    authority: ExternalRelativeVolumeExecutionAuthority,
    policy: ExternalValidationPolicyV1,
) -> dict[str, tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]]:
    assert policy.policy_digest is not None
    result: dict[str, tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]] = {}
    for index, binding in enumerate((authority.baseline, authority.current)):
        payload = ExternalEvidenceMeasurementPayloadV1(
            validation_id=f"validation-{index}",
            evidence_manifest_digest=_digest(f"evidence-manifest-{index}"),
            target_dsm_observed_sha256=binding.observed_sha256,
            policy_digest=policy.policy_digest,
            measured_checkpoint_count=3,
            mean_error_m=0.1,
            mae_m=0.1,
            rmse_m=0.1,
            max_abs_error_m=0.1,
            measured_at=_NOW,
        )
        record = ExternalEvidenceRecordV1(
            evidence_record_id=f"record-{index}",
            validation_id=f"validation-{index}",
            subject_digest=binding.subject.canonical_digest(),
            evidence_manifest_digest=payload.evidence_manifest_digest,
            target_dsm_observed_sha256=binding.observed_sha256,
            policy_digest=policy.policy_digest,
            measurement_payload=payload,
            core_verdict=EvidenceCoreVerdict.VALIDATED,
            core_recorded_at=_NOW,
        ).sealed()
        # The test uses the request's authority-owned record digests.  Rebuild
        # the request authority from these sealed records below.
        context = ExternalEvidenceMeasurementContextV1(
            context_id=f"context-{index}",
            subject=binding.subject,
            evidence_manifest_digest=payload.evidence_manifest_digest,
            evidence_observed_sha256=_digest(f"evidence-bytes-{index}"),
            evidence_observed_size_bytes=10,
            target_dsm_artifact_id=binding.dsm_artifact_id,
            target_dsm_observed_sha256=binding.observed_sha256,
            policy_digest=policy.policy_digest,
            measurement_execution_manifest_digest=_digest(f"measurement-manifest-{index}"),
            rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
            csv_horizontal_crs="EPSG:5186",
            csv_vertical_reference_digest=_digest(f"csv-vertical-{index}"),
            minimum_checkpoint_count=3,
            maximum_checkpoint_count=10,
            maximum_rmse_m=0.5,
            maximum_abs_mean_error_m=0.2,
            maximum_abs_error_m=1.0,
            independent_attestation=None,
            authorized_actor_ids=("authority",),
            active_from=_NOW - timedelta(minutes=1),
            active_until=_NOW + timedelta(minutes=1),
            synthetic_test_only=True,
        ).sealed()
        assert record.evidence_record_digest is not None
        result[record.evidence_record_digest] = (record, context)
    return result


def _launch_ready_authority() -> tuple[
    ExternalRelativeVolumeExecutionAuthority,
    ExternalValidationPolicyV1,
    dict[str, tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]],
]:
    policy = _volume_launch_policy()
    base = _authority()
    initial_material = _volume_evidence_material(base, policy)
    evidence_digests = tuple(initial_material)
    execution = base.execution_policy.model_copy(
        update={
            "resource_envelope_digest": policy.resource_envelope_digest,
            "policy_digest": None,
        },
        deep=True,
    ).sealed()
    authority = replace(
        base,
        validation_policy_digest=policy.policy_digest or "",
        evidence_record_digests=cast(tuple[str, str], evidence_digests),
        execution_policy=execution,
    )
    return authority, policy, initial_material


def _launch_ready_store(
    tmp_path: Path,
) -> tuple[
    ExternalRelativeVolumeStore,
    ExternalRelativeVolumeExecutionAuthority,
    _StaticVolumeEvidence,
]:
    authority, policy, material = _launch_ready_authority()
    port = _AuthorityPort(authority)
    registry = _StaticVolumePolicyRegistry(policy, port.currentness_coordinator)
    registry.subjects = (authority.baseline.subject, authority.current.subject)
    evidence = _StaticVolumeEvidence(material, port.currentness_coordinator)
    resolver = VolumeWorkerLaunchMaterialResolver(
        policy_registry=cast(Any, registry),
        evidence_validations=cast(Any, evidence),
        currentness_coordinator=port.currentness_coordinator,
    )
    store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "launch-ready.jsonl"),
        authority_port=port,
        currentness_coordinator=port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        launch_material_resolver=resolver,
        clock=lambda: _NOW,
    )
    return store, authority, evidence


def _launch_client(
    store: ExternalRelativeVolumeStore,
    *,
    after_capability: Callable[[], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> TestClient:
    app = FastAPI()
    worker = Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    mount_auth(app, AuthRegistry([_token_record(_WORKER_TOKEN, worker)]))

    def capabilities(
        *_args: Any, **_kwargs: Any
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]:
        if after_capability is not None:
            after_capability()
        return (
            ExternalRelativeVolumeInputCapability(
                role="BASELINE_DSM",
                download_url="https://storage.invalid/baseline",
                required_headers={"x-bound": "baseline"},
                expires_at=_NOW + timedelta(minutes=5),
            ),
            ExternalRelativeVolumeInputCapability(
                role="CURRENT_DSM",
                download_url="https://storage.invalid/current",
                required_headers={"x-bound": "current"},
                expires_at=_NOW + timedelta(minutes=5),
            ),
        )

    app.include_router(
        build_external_relative_volume_router(
            store, input_capability_issuer=capabilities, clock=clock or (lambda: _NOW)
        )
    )
    return TestClient(app)


def test_relative_volume_input_contains_complete_ordered_material_for_actual_v2_launch(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_inspector_protocol import LocalLeaseFenceV1
    from ksi_processing_controller.external_measurement_protocol import (
        MeasurementInputV2,
        MeasurementLaunchRequestV2,
    )

    store, authority, _ = _launch_ready_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="v2-material",
        now=_NOW,
    )
    assert issued.record is not None
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=initial,
        now=_NOW,
    )
    assert leased.fence is not None
    response = _launch_client(store).get(
        f"/v1/internal/external-validation/relative-volumes/{issued.record.request.request_id}/input",
        headers={
            **_headers(_WORKER_TOKEN),
            "X-KSI-Worker-Instance-Id": leased.fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": leased.fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(leased.fence.lease_generation),
        },
    )
    assert response.status_code == 200, response.text
    private = response.json()["input"]
    assert private["validationPolicy"]["policyDigest"] == authority.validation_policy_digest
    assert [record["evidenceRecordDigest"] for record in private["volumeEvidenceRecords"]] == list(
        authority.evidence_record_digests
    )
    assert [binding["role"] for binding in private["inputs"]] == [
        "BASELINE_DSM",
        "CURRENT_DSM",
    ]

    launch = MeasurementLaunchRequestV2(
        operation="RELATIVE_VOLUME",
        inputs=(
            MeasurementInputV2(
                role="BASELINE_DSM",
                artifact_id=authority.baseline.dsm_artifact_id,
                observed_sha256=authority.baseline.observed_sha256,
                observed_size_bytes=authority.baseline.observed_size_bytes,
            ),
            MeasurementInputV2(
                role="CURRENT_DSM",
                artifact_id=authority.current.dsm_artifact_id,
                observed_sha256=authority.current.observed_sha256,
                observed_size_bytes=authority.current.observed_size_bytes,
            ),
        ),
        validation_policy=private["validationPolicy"],
        checkpoint_request=None,
        evidence_context=None,
        volume_request=private["request"],
        volume_execution_policy=private["executionPolicy"],
        volume_evidence_records=private["volumeEvidenceRecords"],
        fence=LocalLeaseFenceV1(
            worker_instance_id=leased.fence.worker_instance_id,
            lease_acquisition_id=leased.fence.lease_acquisition_id,
            lease_generation=leased.fence.lease_generation,
        ),
        attempt_nonce="attempt-v2-material",
    ).sealed()
    assert launch.volume_request is not None
    assert launch.volume_request.request_id == issued.record.request.request_id


def test_relative_volume_input_rechecks_material_after_capability_issuance(
    tmp_path: Path,
) -> None:
    store, _, evidence = _launch_ready_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="post-presign-loss",
        now=_NOW,
    )
    assert issued.record is not None
    lease = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
        now=_NOW,
    )
    assert lease.fence is not None
    response = _launch_client(
        store, after_capability=lambda: setattr(evidence, "locally_current", False)
    ).get(
        f"/v1/internal/external-validation/relative-volumes/{issued.record.request.request_id}/input",
        headers={
            **_headers(_WORKER_TOKEN),
            "X-KSI-Worker-Instance-Id": lease.fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": lease.fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(lease.fence.lease_generation),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["verdict"] == ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE


def test_relative_volume_input_denies_when_policy_permission_expires_after_presign(
    tmp_path: Path,
) -> None:
    store, _, _ = _launch_ready_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="post-presign-policy-expiry",
        now=_NOW,
    )
    assert issued.record is not None
    lease = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
        now=_NOW,
    )
    assert lease.fence is not None
    resolver = store.launch_material_resolver
    assert resolver is not None
    registry = resolver._policy_registry  # noqa: SLF001 - controlled expiry seam.
    assert isinstance(registry, _StaticVolumePolicyRegistry)
    registry.locally_permitted_until = _NOW + timedelta(seconds=1)
    current = {"now": _NOW}
    response = _launch_client(
        store,
        after_capability=lambda: current.__setitem__("now", _NOW + timedelta(seconds=2)),
        clock=lambda: current["now"],
    ).get(
        f"/v1/internal/external-validation/relative-volumes/{issued.record.request.request_id}/input",
        headers={
            **_headers(_WORKER_TOKEN),
            "X-KSI-Worker-Instance-Id": lease.fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": lease.fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(lease.fence.lease_generation),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["verdict"] == ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE


def test_report_ref_resolves_immutable_historical_bundle_and_current_guard(
    tmp_path: Path,
) -> None:
    authority = _authority()
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="report-source",
        now=_NOW,
    )
    assert issued.record is not None
    fence = _fence()
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    reported = store.record_observed_report(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            _payload(issued.record.request.request_digest or "", authority), _NOW
        ),
        now=_NOW,
    )
    assert reported.record is not None and reported.record.report is not None
    report_ref = reported.record.report.report_id

    historical = store.resolve_historical_report_ref(report_ref, organization_id="org-a", now=_NOW)
    assert historical is not None
    assert historical.request.request_id == issued.record.request.request_id
    assert historical.report.report_id == report_ref
    assert historical.execution_authority == authority
    assert (
        store.resolve_historical_report_ref(
            issued.record.request.request_id, organization_id="org-a", now=_NOW
        )
        is None
    )
    assert (
        store.resolve_historical_report_ref(report_ref, organization_id="org-b", now=_NOW) is None
    )
    store._journal.close()  # noqa: SLF001 - hand the exact durable history to recovery.
    recovered = _store(tmp_path, authority)
    recovered_bundle = recovered.resolve_historical_report_ref(
        report_ref, organization_id="org-a", now=_NOW
    )
    assert recovered_bundle is not None
    assert recovered_bundle.request == historical.request
    assert recovered_bundle.report == historical.report

    port = store._authority_port  # noqa: SLF001 - test-only authority withdrawal.
    assert isinstance(port, _AuthorityPort)
    port.authority = _authority(active=False)
    # Historical proof is independently retained and stays readable after live
    # withdrawal; downstream current use does not.
    assert store.resolve_historical_report_ref(report_ref, organization_id="org-a", now=_NOW)
    assert (
        store.preflight_current_report_ref(
            report_ref, organization_id="org-a", principal=_principal(), now=_NOW
        )
        is None
    )

    port.authority = authority
    assert (
        store.preflight_current_report_ref(
            report_ref,
            organization_id="org-a",
            principal=_principal(organization_id="org-b"),
            now=_NOW,
        )
        is None
    )
    witness = store.preflight_current_report_ref(
        report_ref, organization_id="org-a", principal=_principal(), now=_NOW
    )
    assert witness is not None
    port.authority = _authority(active=False)
    with store.guard_current_report_ref(
        report_ref,
        organization_id="org-a",
        principal=_principal(),
        witness=witness,
        now=_NOW,
    ) as guarded_after_withdrawal:
        assert guarded_after_withdrawal is None
    port.authority = authority
    with store.guard_current_report_ref(
        report_ref,
        organization_id="org-a",
        principal=_principal(),
        witness=witness,
        now=_NOW,
    ) as guarded:
        assert guarded == witness


def test_volume_launch_material_rejects_reordered_or_changed_evidence_before_worker_input(
    tmp_path: Path,
) -> None:
    store, authority, evidence = _launch_ready_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="material-order",
        now=_NOW,
    )
    assert issued.record is not None
    resolver = store.launch_material_resolver
    assert resolver is not None
    material = resolver.preflight(issued.record.request, authority, now=_NOW)
    assert material is not None
    with store.coordinator.guarded_read():
        assert not resolver.material_remains_current(
            issued.record.request,
            authority,
            replace(
                material,
                evidence_records=(material.evidence_records[1], material.evidence_records[0]),
            ),
            now=_NOW,
        )
    first_digest = authority.evidence_record_digests[0]
    record, context = evidence.records[first_digest]
    evidence.records[first_digest] = (
        record.model_copy(update={"target_dsm_observed_sha256": authority.current.observed_sha256}),
        context,
    )
    assert resolver.preflight(issued.record.request, authority, now=_NOW) is None
    lease = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
        now=_NOW,
    )
    assert lease.fence is not None
    capability_calls = {"count": 0}
    response = _launch_client(
        store,
        after_capability=lambda: capability_calls.__setitem__(
            "count", capability_calls["count"] + 1
        ),
    ).get(
        f"/v1/internal/external-validation/relative-volumes/{issued.record.request.request_id}/input",
        headers={
            **_headers(_WORKER_TOKEN),
            "X-KSI-Worker-Instance-Id": lease.fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": lease.fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(lease.fence.lease_generation),
        },
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    assert capability_calls["count"] == 0


def test_volume_generation_zero_retry_rejects_foreign_and_expired_acquisition(
    tmp_path: Path,
) -> None:
    authority = _authority(valid_until=_NOW + timedelta(hours=2))
    store = _store(tmp_path, authority)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="generation-zero-expiry",
        now=_NOW,
    )
    assert issued.record is not None
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=initial,
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASED
    )
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=LeaseFence(str(uuid4()), initial.lease_acquisition_id, 0),
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.LEASE_HELD_BY_ANOTHER
    )
    assert (
        store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=initial,
            now=_NOW + timedelta(minutes=6),
        ).verdict
        is ExternalRelativeVolumeVerdict.STALE_LEASE_ACQUISITION
    )

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.acquisition.coordination import AcquisitionCoordinationStore
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_atomicity import MissionIssuanceCommitter, MissionIssuanceRejected
from ksi_core.mission_records import IssuanceAuthorizationWitness, MissionStore
from ksi_core.observation_work_orders import (
    ExternalReobservationExecutionDenied,
    ObservationWorkOrderStore,
    ObservationWorkOrderStoreRecoveryError,
)
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.external_reobservation import (
    ExternalPlanningOnlyWorkOrderBindingV1,
    ExternalReobservationApprovalInputV1,
    ExternalReobservationProposalAuthorityV1,
    ExternalWorkAreaSnapshotV1,
)
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrderStatus,
    TemporalCoherencePolicy,
)
from ksi_mission_contracts.models import SiteFrame


def test_work_order_store_exposes_external_reobservation_approval_boundary(tmp_path) -> None:
    """Deleting the dedicated approval boundary would reopen the generic path."""

    store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )

    assert callable(getattr(store, "approve_external_reobservation", None))


class _AuthorityPort:
    """Fixture-only independent proposal history and separately revocable live view."""

    def __init__(
        self,
        authority: ExternalReobservationProposalAuthorityV1,
        *,
        live_authority: ExternalReobservationProposalAuthorityV1 | None | object = ...,
    ) -> None:
        self.authority = authority
        self.current_lock = threading.RLock()
        self.guard_held = False
        self.live_authority = authority if live_authority is ... else live_authority
        self._accepted_history = {
            (
                authority.organization_id,
                authority.proposal_id,
                authority.proposal_version,
            ): authority
        }

    def resolve(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
    ) -> ExternalReobservationProposalAuthorityV1 | None:
        if self.live_authority is None:
            return None
        assert isinstance(self.live_authority, ExternalReobservationProposalAuthorityV1)
        assert organization_id == self.live_authority.organization_id
        assert approval_input.proposal_id == self.live_authority.proposal_id
        return self.live_authority

    @contextmanager
    def guard_current(self, *, organization_id, approval_input, actor, evaluated_at):
        del actor, evaluated_at
        with self.current_lock:
            self.guard_held = True
            try:
                yield self.resolve(organization_id=organization_id, approval_input=approval_input)
            finally:
                self.guard_held = False

    def revoke(self):
        with self.current_lock:
            self.live_authority = None

    def resolve_historical(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        approved_at: datetime,
    ) -> ExternalReobservationProposalAuthorityV1 | None:
        del actor, approved_at
        return self._accepted_history.get(
            (
                organization_id,
                approval_input.proposal_id,
                approval_input.proposal_version,
            )
        )


def _digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def _authority(*, target_work_area_id: str = "area-1") -> ExternalReobservationProposalAuthorityV1:
    target = ExternalWorkAreaSnapshotV1(
        work_area_id=target_work_area_id,
        revision=1,
        polygon={
            "type": "Polygon",
            "coordinates": [[[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0]]],
        },
        crs="EPSG:5186",
    ).sealed()
    return ExternalReobservationProposalAuthorityV1(
        proposal_id="proposal-1",
        proposal_version=1,
        proposal_digest=_digest("a"),
        organization_id="org-1",
        site_id="site-1",
        source_work_order_id="obs-work-00000001",
        report_digest=_digest("b"),
        decision_digest=_digest("c"),
        zone_digest=_digest("d"),
        evidence_digests=(_digest("e"),),
        target_work_areas=(target,),
    ).sealed()


def _approval_input(
    authority: ExternalReobservationProposalAuthorityV1,
) -> ExternalReobservationApprovalInputV1:
    return ExternalReobservationApprovalInputV1(
        organization_id=authority.organization_id,
        site_id=authority.site_id,
        source_work_order_id=authority.source_work_order_id,
        proposal_id=authority.proposal_id,
        proposal_version=authority.proposal_version,
        proposal_digest=authority.proposal_digest,
        report_digest=authority.report_digest,
        decision_digest=authority.decision_digest,
        zone_digest=authority.zone_digest,
        evidence_digests=authority.evidence_digests,
    ).sealed()


def _store_with_source(
    tmp_path,
) -> tuple[
    DurableJournal,
    ObservationWorkOrderStore,
    ExternalReobservationProposalAuthorityV1,
]:
    authority = _authority()
    journal = DurableJournal(tmp_path / "work-orders.jsonl")
    store = ObservationWorkOrderStore(
        journal,
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=_AuthorityPort(authority),
    )
    store.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Source",
        work_area_ids=["area-1"],
        schedule_id=None,
        temporal_policy=TemporalCoherencePolicy(max_capture_span_seconds=600),
        actor="creator-1",
        now=datetime(2026, 9, 9, 1, tzinfo=UTC),
    )
    return journal, store, authority


def _approve(
    store: ObservationWorkOrderStore,
    authority: ExternalReobservationProposalAuthorityV1,
    *,
    idempotency_key: str = "approve-1",
):
    return store.approve_external_reobservation(
        _approval_input(authority),
        organization_id="org-1",
        actor="approver-1",
        now=datetime(2026, 9, 9, 2, tzinfo=UTC),
        idempotency_key=idempotency_key,
    )


def test_external_reobservation_approval_creates_one_planning_only_successor_and_preserves_source(
    tmp_path,
) -> None:
    """Removing the atomic event or reopening execution must fail this approval path."""

    authority = _authority()
    journal = DurableJournal(tmp_path / "work-orders.jsonl")
    store = ObservationWorkOrderStore(
        journal,
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=_AuthorityPort(authority),
    )
    source = store.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Source",
        work_area_ids=["area-1"],
        schedule_id=None,
        temporal_policy=TemporalCoherencePolicy(max_capture_span_seconds=600),
        actor="creator-1",
        now=datetime(2026, 9, 9, 1, tzinfo=UTC),
    )
    source_before = source.model_dump(by_alias=True, mode="json")
    notified: list[str] = []
    store.bind_status_listener(lambda order: notified.append(order.work_order_id))

    result = store.approve_external_reobservation(
        _approval_input(authority),
        organization_id="org-1",
        actor="approver-1",
        now=datetime(2026, 9, 9, 2, tzinfo=UTC),
        idempotency_key="approve-1",
    )

    successor = result.successor_work_order
    assert successor.work_order_id != source.work_order_id
    assert successor.organization_id == "org-1"
    assert successor.site_id == "site-1"
    assert successor.work_area_ids == ["area-1"]
    assert successor.temporal_policy == source.temporal_policy
    assert successor.cycle_number == 1
    assert successor.schedule_id is None
    assert successor.status.value == "APPROVED"
    assert successor.approved_by == "approver-1"
    assert successor.approved_at == "2026-09-09T02:00:00+00:00"
    assert source_before == store.get(source.work_order_id, organization_id="org-1").model_dump(
        by_alias=True, mode="json"
    )
    assert store.get(successor.work_order_id, organization_id="org-1") == successor
    assert [
        item.work_order_id for item in store.list_for_site("site-1", organization_id="org-1")
    ] == [
        source.work_order_id,
        successor.work_order_id,
    ]
    assert (
        store.get_external_reobservation_binding(successor.work_order_id, organization_id="org-1")
        == result.planning_binding
    )
    assert store.list_external_reobservation_bindings(organization_id="org-1") == [
        result.planning_binding
    ]
    assert store.list_external_reobservation_bindings(organization_id="other-org") == []
    assert result.planning_binding.acquisition_run_allowed is False
    assert result.planning_binding.mission_issuance_allowed is False
    assert result.planning_binding.approval_id == result.approval_receipt.approval_id
    assert result.planning_binding.approved_by == result.approval_receipt.approved_by
    assert result.planning_binding.approved_at == result.approval_receipt.approved_at
    assert notified == []
    assert set(journal.replay()[-1]) == {
        "kind",
        "ts",
        "actor",
        "approvalInput",
        "authoritySnapshot",
        "approvalReceipt",
        "planningBinding",
        "successorWorkOrder",
    }


def test_external_reobservation_successor_uses_approved_target_work_areas(tmp_path) -> None:
    """Requiring the source area list would discard the proposal's reviewed target selection."""

    authority = _authority(target_work_area_id="area-2")
    store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "target-work-areas.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=_AuthorityPort(authority),
    )
    source = store.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Source",
        work_area_ids=["area-1"],
        schedule_id=None,
        temporal_policy=TemporalCoherencePolicy(max_capture_span_seconds=600),
        actor="creator-1",
        now=datetime.now(UTC),
    )

    successor = _approve(store, authority).successor_work_order

    assert store.get(source.work_order_id, organization_id="org-1").work_area_ids == ["area-1"]
    assert successor.work_area_ids == ["area-2"]


def test_external_reobservation_wire_contracts_keep_execution_flags_closed(tmp_path) -> None:
    """A schema accepting executable flags would make a sealed planning binding unsafe."""

    _journal, store, authority = _store_with_source(tmp_path)
    result = _approve(store, authority)
    root = Path(__file__).resolve().parents[2]
    contracts = (
        (
            "external-reobservation-approval-input.v1.json",
            _approval_input(authority).model_dump(by_alias=True, mode="json"),
        ),
        (
            "external-planning-only-work-order-binding.v1.json",
            result.planning_binding.model_dump(by_alias=True, mode="json"),
        ),
        (
            "external-reobservation-approval-receipt.v1.json",
            result.approval_receipt.model_dump(by_alias=True, mode="json"),
        ),
    )
    for filename, wire in contracts:
        schema = json.loads((root / "contracts" / "schemas" / filename).read_text("utf-8"))
        Draft202012Validator(schema).validate(wire)

    unsafe_binding = result.planning_binding.model_dump(by_alias=True, mode="json")
    unsafe_binding["acquisitionRunAllowed"] = True
    schema = json.loads(
        (
            root / "contracts" / "schemas" / "external-planning-only-work-order-binding.v1.json"
        ).read_text("utf-8")
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 -- jsonschema validation type is incidental
        Draft202012Validator(schema).validate(unsafe_binding)


@pytest.mark.parametrize(
    ("polygon", "crs"),
    [
        ({"type": "Polygon", "coordinates": [[[127.0, 37.0]]]}, "EPSG:5186"),
        (
            {
                "type": "Polygon",
                "coordinates": [[[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.2, 37.1]]],
            },
            "EPSG:5186",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [[["west", 37.0], [127.1, 37.0], [127.1, 37.1], ["west", 37.0]]],
            },
            "EPSG:5186",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [[float("nan"), 37.0], [127.1, 37.0], [127.1, 37.1], [float("nan"), 37.0]]
                ],
            },
            "EPSG:5186",
        ),
        (
            {"type": "Polygon", "coordinates": [[[127.0, 37.0]] * 513]},
            "EPSG:5186",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [[[181.0, 37.0], [179.0, 37.0], [179.0, 38.0], [181.0, 37.0]]],
            },
            "EPSG:4326",
        ),
    ],
)
def test_external_work_area_snapshot_rejects_invalid_canonical_geometry(polygon, crs) -> None:
    """External target snapshots use the same usable-geometry floor as WorkArea."""

    with pytest.raises(ValueError):
        ExternalWorkAreaSnapshotV1(
            work_area_id="area-1",
            revision=1,
            polygon=polygon,
            crs=crs,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda wire: wire["targetWorkAreas"][0]["polygon"].update(
            {"coordinates": [[[127.0, 37.0]]]}
        ),
        lambda wire: wire["targetWorkAreas"][0]["polygon"].update(
            {"coordinates": [[["west", 37.0], [127.1, 37.0], [127.1, 37.1], ["west", 37.0]]]}
        ),
        lambda wire: wire["targetWorkAreas"][0]["polygon"].update(
            {"coordinates": [[[127.0, 37.0]] * 513]}
        ),
        lambda wire: (
            wire["targetWorkAreas"][0].update({"crs": "EPSG:4326"}),
            wire["targetWorkAreas"][0]["polygon"].update(
                {"coordinates": [[[181.0, 37.0], [179.0, 37.0], [179.0, 38.0], [181.0, 37.0]]]}
            ),
        ),
    ],
)
def test_external_planning_binding_schema_rejects_enforceable_geometry_bounds(
    tmp_path, mutation
) -> None:
    """The published wire schema rejects malformed bounded target geometry before Core parsing."""

    _journal, store, authority = _store_with_source(tmp_path)
    wire = _approve(store, authority).planning_binding.model_dump(by_alias=True, mode="json")
    mutation(wire)
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "schemas"
            / "external-planning-only-work-order-binding.v1.json"
        ).read_text("utf-8")
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 -- validator exception type is incidental
        Draft202012Validator(schema).validate(wire)


def test_external_planning_binding_model_rejects_open_target_ring(tmp_path) -> None:
    """Ring closure is semantic and remains enforced by the canonical Pydantic validator."""

    _journal, store, authority = _store_with_source(tmp_path)
    wire = _approve(store, authority).planning_binding.model_dump(by_alias=True, mode="json")
    wire["targetWorkAreas"][0]["polygon"]["coordinates"] = [
        [[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.2, 37.1]]
    ]
    with pytest.raises(ValueError):
        ExternalPlanningOnlyWorkOrderBindingV1.model_validate(wire)


def test_external_reobservation_binding_read_does_not_expose_mutable_store_snapshot(
    tmp_path,
) -> None:
    """Returning the stored nested polygon would let a read caller alter the sealed projection."""

    _journal, store, authority = _store_with_source(tmp_path)
    approved = _approve(store, authority)
    exposed = store.get_external_reobservation_binding(
        approved.successor_work_order.work_order_id, organization_id="org-1"
    )
    assert exposed is not None
    exposed.target_work_areas[0].polygon["type"] = "LineString"

    stored = store.get_external_reobservation_binding(
        approved.successor_work_order.work_order_id, organization_id="org-1"
    )
    assert stored is not None
    assert stored.target_work_areas[0].polygon["type"] == "Polygon"


def test_external_reobservation_approval_result_does_not_expose_store_snapshot(tmp_path) -> None:
    """An idempotent result cannot hand out the stored nested target geometry."""

    _journal, store, authority = _store_with_source(tmp_path)
    _approve(store, authority)
    retried = _approve(store, authority)
    retried.planning_binding.target_work_areas[0].polygon["type"] = "LineString"

    stored = store.get_external_reobservation_binding(
        retried.successor_work_order.work_order_id, organization_id="org-1"
    )
    assert stored is not None
    assert stored.target_work_areas[0].polygon["type"] == "Polygon"


def test_external_reobservation_retry_and_concurrent_approval_create_one_successor(
    tmp_path,
) -> None:
    """Dropping either idempotency map would create duplicate orders under retry or racing tabs."""

    journal, store, authority = _store_with_source(tmp_path)
    first = _approve(store, authority)
    retry = _approve(store, authority)
    assert retry == first

    concurrent_journal, concurrent_store, concurrent_authority = _store_with_source(
        tmp_path / "concurrent"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda key: _approve(concurrent_store, concurrent_authority, idempotency_key=key),
                ("approve-1", "approve-2"),
            )
        )

    assert results[0].successor_work_order == results[1].successor_work_order
    assert len(store.list_for_site("site-1", organization_id="org-1")) == 2
    assert (
        sum(
            item["kind"] == "external-reobservation-approved-and-next-order-created"
            for item in journal.replay()
        )
        == 1
    )
    assert len(concurrent_store.list_for_site("site-1", organization_id="org-1")) == 2
    assert (
        sum(
            item["kind"] == "external-reobservation-approved-and-next-order-created"
            for item in concurrent_journal.replay()
        )
        == 1
    )


def test_external_reobservation_rejects_divergent_idempotency_or_proposal_retry(tmp_path) -> None:
    """Allowing a changed digest through either retry key would sever receipt lineage."""

    _journal, store, authority = _store_with_source(tmp_path)
    _approve(store, authority)
    divergent = (
        _approval_input(authority)
        .model_copy(update={"report_digest": _digest("f"), "approval_input_digest": None})
        .sealed()
    )

    with pytest.raises(RuntimeError, match="EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT"):
        store.approve_external_reobservation(
            divergent,
            organization_id="org-1",
            actor="approver-1",
            now=datetime(2026, 9, 9, 2, tzinfo=UTC),
            idempotency_key="approve-1",
        )
    with pytest.raises(RuntimeError, match="EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT"):
        store.approve_external_reobservation(
            divergent,
            organization_id="org-1",
            actor="approver-1",
            now=datetime(2026, 9, 9, 2, tzinfo=UTC),
            idempotency_key="approve-2",
        )


def test_external_reobservation_journal_failure_leaves_no_successor(tmp_path, monkeypatch) -> None:
    """Applying the projection before durable append would leave a phantom successor on failure."""

    journal, store, authority = _store_with_source(tmp_path)
    source = store.get("obs-work-00000001", organization_id="org-1")
    assert source is not None

    def fail_append(_record) -> None:
        raise RuntimeError("journal write failed")

    monkeypatch.setattr(journal, "append", fail_append)
    with pytest.raises(RuntimeError, match="journal write failed"):
        _approve(store, authority)
    assert store.get("obs-work-00000001", organization_id="org-1") == source
    assert len(store.list_for_site("site-1", organization_id="org-1")) == 1
    assert not store._external_reobservation_authority_port.guard_held


def test_external_reobservation_replay_and_exact_retry_need_no_live_authority(tmp_path) -> None:
    """Replay needs accepted history but is unaffected by later live revocation."""

    journal, store, authority = _store_with_source(tmp_path)
    approved = _approve(store, authority)
    journal.close()

    with pytest.raises(ObservationWorkOrderStoreRecoveryError, match="historical"):
        ObservationWorkOrderStore(
            DurableJournal(tmp_path / "work-orders.jsonl"),
            site_exists=lambda _site_id, _organization_id: True,
            work_areas_exist=lambda _site_id, _work_area_ids: True,
        )

    replayed = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=_AuthorityPort(authority, live_authority=None),
    )
    assert (
        replayed.get_external_reobservation_binding(
            approved.successor_work_order.work_order_id, organization_id="org-1"
        )
        == approved.planning_binding
    )
    assert _approve(replayed, authority) == approved


def test_external_reobservation_default_port_and_scope_mismatch_fail_closed(tmp_path) -> None:
    """Missing authority or a different organization cannot be trusted from caller input."""

    authority = _authority()
    journal = DurableJournal(tmp_path / "closed.jsonl")
    store = ObservationWorkOrderStore(
        journal,
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )
    store.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Source",
        work_area_ids=["area-1"],
        schedule_id=None,
        actor="creator-1",
        now=datetime.now(UTC),
    )

    with pytest.raises(RuntimeError, match="AUTHORITY_UNAVAILABLE"):
        _approve(store, authority)
    with pytest.raises(LookupError, match="organization scope"):
        store.approve_external_reobservation(
            _approval_input(authority),
            organization_id="other-org",
            actor="approver-1",
            now=datetime.now(UTC),
            idempotency_key="approve-1",
        )
    assert len(store.list_for_site("site-1", organization_id="org-1")) == 1


def test_external_reobservation_live_approval_requires_same_historical_acceptance(tmp_path) -> None:
    """A current proposal view cannot append unless the independent history agrees exactly."""

    historical = _authority()
    live = historical.model_copy(
        update={"report_digest": _digest("f"), "authority_digest": None}
    ).sealed()
    store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "authority-mismatch.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=_AuthorityPort(historical, live_authority=live),
    )
    store.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Source",
        work_area_ids=["area-1"],
        schedule_id=None,
        actor="creator-1",
        now=datetime.now(UTC),
    )

    with pytest.raises(RuntimeError, match="AUTHORITY_CONFLICT"):
        store.approve_external_reobservation(
            _approval_input(live),
            organization_id="org-1",
            actor="approver-1",
            now=datetime.now(UTC),
            idempotency_key="approve-1",
        )
    assert len(store.list_for_site("site-1", organization_id="org-1")) == 1
    assert not store._external_reobservation_authority_port.guard_held


def test_external_reobservation_replay_rejects_rehashed_successor_tampering(tmp_path) -> None:
    """Rehashing binding and receipt content cannot change the deterministic proposal successor."""

    journal, store, authority = _store_with_source(tmp_path)
    result = _approve(store, authority)
    records = journal.replay()
    journal.close()

    # Local imports keep the shared fixture contracts focused on setup.
    from ksi_event_contracts.external_reobservation import (
        ExternalPlanningOnlyWorkOrderBindingV1,
        ExternalReobservationApprovalReceiptV1,
    )
    from ksi_event_contracts.observation_work_order import ObservationWorkOrder

    event = records[-1]
    tampered_successor_id = "obs-work-external-tampered"
    binding = ExternalPlanningOnlyWorkOrderBindingV1.model_validate(event["planningBinding"])
    tampered_binding = binding.model_copy(
        update={"successor_work_order_id": tampered_successor_id, "binding_digest": None}
    ).sealed()
    receipt = ExternalReobservationApprovalReceiptV1.model_validate(event["approvalReceipt"])
    tampered_receipt = receipt.model_copy(
        update={
            "successor_work_order_id": tampered_successor_id,
            "binding_digest": tampered_binding.binding_digest,
            "receipt_digest": None,
        }
    ).sealed()
    successor = ObservationWorkOrder.model_validate(event["successorWorkOrder"])
    tampered_successor = successor.model_copy(update={"work_order_id": tampered_successor_id})
    tampered_event = {
        **event,
        "planningBinding": tampered_binding.model_dump(by_alias=True, mode="json"),
        "approvalReceipt": tampered_receipt.model_dump(by_alias=True, mode="json"),
        "successorWorkOrder": tampered_successor.model_dump(by_alias=True, mode="json"),
    }

    tampered_journal = DurableJournal(tmp_path / "tampered.jsonl")
    for record in [*records[:-1], tampered_event]:
        tampered_journal.append(record)
    tampered_journal.close()
    with pytest.raises(ObservationWorkOrderStoreRecoveryError, match="deterministic"):
        ObservationWorkOrderStore(
            DurableJournal(tmp_path / "tampered.jsonl"),
            site_exists=lambda _site_id, _organization_id: True,
            external_reobservation_authority_port=_AuthorityPort(authority),
        )
    assert result.successor_work_order.work_order_id != tampered_successor_id


def test_external_reobservation_replay_rejects_fully_rehashed_unaccepted_authority(
    tmp_path,
) -> None:
    """A self-consistent WorkOrder event cannot manufacture accepted proposal history."""

    journal, store, authority = _store_with_source(tmp_path)
    _approve(store, authority)
    records = journal.replay()
    journal.close()

    from ksi_event_contracts.external_reobservation import (
        ExternalPlanningOnlyWorkOrderBindingV1,
        ExternalReobservationApprovalReceiptV1,
    )
    from ksi_event_contracts.observation_work_order import ObservationWorkOrder

    event = records[-1]
    target = (
        authority.target_work_areas[0]
        .model_copy(
            update={
                "polygon": {
                    "type": "Polygon",
                    "coordinates": [[[128.0, 38.0], [128.1, 38.0], [128.1, 38.1], [128.0, 38.0]]],
                },
                "snapshot_digest": None,
            }
        )
        .sealed()
    )
    forged_authority = authority.model_copy(
        update={
            "proposal_digest": _digest("f"),
            "report_digest": _digest("1"),
            "decision_digest": _digest("2"),
            "zone_digest": _digest("3"),
            "evidence_digests": (_digest("4"),),
            "target_work_areas": (target,),
            "authority_digest": None,
        }
    ).sealed()
    forged_input = _approval_input(forged_authority)
    receipt = ExternalReobservationApprovalReceiptV1.model_validate(event["approvalReceipt"])
    approval_id = ObservationWorkOrderStore._external_approval_id(  # noqa: SLF001
        forged_input, receipt.idempotency_key
    )
    successor = ObservationWorkOrder.model_validate(event["successorWorkOrder"])
    forged_successor_id = ObservationWorkOrderStore._external_successor_id(  # noqa: SLF001
        forged_authority
    )
    forged_successor = successor.model_copy(
        update={
            "work_order_id": forged_successor_id,
            "work_area_ids": [target.work_area_id],
        }
    )
    binding = ExternalPlanningOnlyWorkOrderBindingV1.model_validate(event["planningBinding"])
    forged_binding = binding.model_copy(
        update={
            "successor_work_order_id": forged_successor_id,
            "approval_id": approval_id,
            "proposal_digest": forged_authority.proposal_digest,
            "report_digest": forged_authority.report_digest,
            "decision_digest": forged_authority.decision_digest,
            "zone_digest": forged_authority.zone_digest,
            "evidence_digests": forged_authority.evidence_digests,
            "target_work_areas": forged_authority.target_work_areas,
            "binding_digest": None,
        }
    ).sealed()
    forged_receipt = receipt.model_copy(
        update={
            "approval_id": approval_id,
            "successor_work_order_id": forged_successor_id,
            "proposal_digest": forged_authority.proposal_digest,
            "approval_input_digest": forged_input.approval_input_digest,
            "binding_digest": forged_binding.binding_digest,
            "receipt_digest": None,
        }
    ).sealed()
    forged_event = {
        **event,
        "approvalInput": forged_input.model_dump(by_alias=True, mode="json"),
        "authoritySnapshot": forged_authority.model_dump(by_alias=True, mode="json"),
        "approvalReceipt": forged_receipt.model_dump(by_alias=True, mode="json"),
        "planningBinding": forged_binding.model_dump(by_alias=True, mode="json"),
        "successorWorkOrder": forged_successor.model_dump(by_alias=True, mode="json"),
    }

    forged_journal = DurableJournal(tmp_path / "fully-forged.jsonl")
    for record in [*records[:-1], forged_event]:
        forged_journal.append(record)
    forged_journal.close()

    with pytest.raises(ObservationWorkOrderStoreRecoveryError, match="historical"):
        ObservationWorkOrderStore(
            DurableJournal(tmp_path / "fully-forged.jsonl"),
            site_exists=lambda _site_id, _organization_id: True,
            work_areas_exist=lambda _site_id, _work_area_ids: True,
            external_reobservation_authority_port=_AuthorityPort(authority),
        )


def test_external_successor_execution_guard_rejects_cloned_order(tmp_path) -> None:
    """Checking only object identity would let a cloned planning-only order reach execution."""

    _journal, store, authority = _store_with_source(tmp_path)
    successor = _approve(store, authority).successor_work_order

    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        store.assert_execution_allowed(successor.model_copy(deep=True))


def test_external_successor_rejects_generic_approval_and_status_callbacks(tmp_path) -> None:
    """Generic WorkOrder paths cannot advance an external planning-only successor."""

    _journal, store, authority = _store_with_source(tmp_path)
    successor = _approve(store, authority).successor_work_order

    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        store.approve(
            successor.work_order_id,
            organization_id="org-1",
            expected_version=successor.version,
            actor="approver-2",
            now=datetime.now(UTC),
        )
    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        store.record_status(
            successor.work_order_id,
            organization_id="org-1",
            status=ObservationWorkOrderStatus.DISPATCHED,
            status_reason=None,
            mission_ids=None,
            processing_job_ids=None,
            report_refs=None,
            actor="worker-1",
            now=datetime.now(UTC),
        )
    assert store.get(successor.work_order_id, organization_id="org-1") == successor


def test_external_successor_cannot_create_or_link_acquisition_run(tmp_path) -> None:
    """Omitting the shared execution guard lets a later recovery create a real run."""

    _journal, work_orders, authority = _store_with_source(tmp_path)
    successor = _approve(work_orders, authority).successor_work_order
    coordination = AcquisitionCoordinationStore(
        DurableJournal(tmp_path / "acquisition-runs.jsonl"),
        work_order_execution_guard=work_orders.assert_execution_allowed,
    )

    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        coordination.ensure_run(
            successor.model_copy(deep=True), actor="operator-1", now=datetime.now(UTC)
        )
    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        coordination.link_mission(
            successor.model_copy(deep=True),
            "mission-forbidden",
            actor="operator-1",
            now=datetime.now(UTC),
        )
    assert (
        coordination.get_run(
            successor.work_order_id, organization_id="org-1", cycle_number=successor.cycle_number
        )
        is None
    )
    assert coordination._journal.replay() == []  # noqa: SLF001 -- durable no-mutation assertion


def test_external_successor_cannot_create_an_unguarded_acquisition_run(tmp_path) -> None:
    """A direct assembly denies external WorkOrders without relying on injected guards."""

    _journal, work_orders, authority = _store_with_source(tmp_path)
    successor = _approve(work_orders, authority).successor_work_order
    run_path = tmp_path / "preexisting-acquisition-runs.jsonl"
    run_journal = DurableJournal(run_path)
    unguarded = AcquisitionCoordinationStore(run_journal)
    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        unguarded.ensure_run(successor, actor="operator-1", now=datetime.now(UTC))
    before = run_journal.replay()
    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        unguarded.link_mission(
            successor,
            "mission-forbidden-existing-run",
            actor="operator-1",
            now=datetime.now(UTC),
        )
    assert run_journal.replay() == before == []


def test_external_successor_cannot_link_mission_or_enter_mission_issuance(tmp_path) -> None:
    """Checking only route approval status would permit a planning-only successor Mission."""

    _journal, work_orders, authority = _store_with_source(tmp_path)
    successor = _approve(work_orders, authority).successor_work_order
    with pytest.raises(ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        work_orders.link_mission(
            successor.work_order_id,
            organization_id="org-1",
            cycle_number=successor.cycle_number,
            mission_id="mission-forbidden",
            mission_site_id="site-1",
            actor="operator-1",
            now=datetime.now(UTC),
            require_approved=False,
        )

    committer = MissionIssuanceCommitter(
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
        work_order_store=work_orders,
    )
    witness = IssuanceAuthorizationWitness(
        organization_id="org-1",
        site_id="site-1",
        site_issuance_revision=1,
        site_status=SiteStatus.UNMAPPED,
        site_frame_digest=_digest("a"),
        request_digest=_digest("b"),
        captured_at=datetime.now(UTC),
    )
    with pytest.raises(MissionIssuanceRejected, match="EXTERNAL_RECONSTRUCTION_ONLY"):
        committer.attach_work_order(witness, work_order_id=successor.work_order_id)


def test_external_successor_mission_plan_route_returns_typed_conflict_without_mutation(
    tmp_path,
) -> None:
    """A route-local bypass could issue a Mission after planning-only approval."""

    _journal, work_orders, authority = _store_with_source(tmp_path)
    successor = _approve(work_orders, authority).successor_work_order
    site_store = SiteStore(DurableJournal(tmp_path / "sites-route.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186",
        vertical_datum="KNGeoid2018",
        unit="meter",
        transform_version="1.0.0",
    )
    assert (
        site_store.register(
            "site-1",
            "Site 1",
            frame,
            organization_id="org-1",
            actor="fixture",
            now=datetime.now(UTC),
        ).record
        is not None
    )
    token = "external-planning-operator-token"  # noqa: S105 -- test-only credential
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=Principal(
                    principal_id="operator-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-1",
                ),
            )
        ]
    )
    coordination = AcquisitionCoordinationStore(
        DurableJournal(tmp_path / "runs-route.jsonl"),
        work_order_execution_guard=work_orders.assert_execution_allowed,
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions-route.jsonl"))
    client = TestClient(
        create_app(
            auth_registry=registry,
            site_store=site_store,
            mission_store=mission_store,
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="route-key",
            observation_work_order_store=work_orders,
            acquisition_connectivity_store=AcquisitionConnectivityStore(
                DurableJournal(tmp_path / "connectivity-route.jsonl"),
                site_exists=lambda site_id, organization_id: (
                    site_store.get_scoped(site_id, organization_id) is not None
                ),
            ),
            acquisition_coordination_store=coordination,
        ),
        raise_server_exceptions=False,
    )
    generic_approval = client.post(
        f"/v1/observation-work-orders/{successor.work_order_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"expectedVersion": successor.version},
    )
    assert generic_approval.status_code == 409, generic_approval.text
    assert "EXTERNAL_RECONSTRUCTION_ONLY" in generic_approval.text
    response = client.post(
        "/v1/missions/plans",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workOrderId": successor.work_order_id,
            "contract": {
                "missionId": "mission-forbidden-route",
                "siteId": "site-1",
                "missionType": "BASELINE_MAPPING",
                "siteFrame": frame.model_dump(by_alias=True, mode="json"),
                "flightEnvelope": {
                    "allowedVolumes": ["volume-1"],
                    "excludedVolumes": [],
                    "minAltitudeM": 5,
                    "maxAltitudeM": 100,
                },
                "objectives": ["baseline"],
                "viewpointPolicyId": "vp-1",
                "riskPolicyPackId": "risk-1",
                "fallbackPolicyId": "fallback-1",
                "capturePolicyId": "capture-1",
            },
            "aoi": {
                "vertices": [
                    {"latDeg": 37.5, "lonDeg": 127.0},
                    {"latDeg": 37.5, "lonDeg": 127.001},
                    {"latDeg": 37.501, "lonDeg": 127.001},
                    {"latDeg": 37.501, "lonDeg": 127.0},
                ]
            },
            "route": {"altitudeM": 40, "spacingM": 20, "captureIntervalM": 15},
            "drone": {
                "droneEnumValue": 99,
                "droneSubEnumValue": 0,
                "payloadEnumValue": 65534,
            },
            "wayline": {
                "autoFlightSpeedMs": 5,
                "takeoffSecurityHeightM": 20,
                "globalTransitionalSpeedMs": 10,
            },
        },
    )

    assert response.status_code == 409, response.text
    assert "EXTERNAL_RECONSTRUCTION_ONLY" in response.text
    progress = client.get(
        f"/v1/observation-work-orders/{successor.work_order_id}/acquisition-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert progress.status_code == 409, progress.text
    assert "EXTERNAL_RECONSTRUCTION_ONLY" in progress.text
    assert mission_store.get("mission-forbidden-route") is None
    assert (
        coordination.get_run(successor.work_order_id, organization_id="org-1", cycle_number=1)
        is None
    )


@pytest.mark.parametrize("crs", ["epsg:4326", "EpSg:4326", " EPSG:4326 "])
def test_binding_schema_enforces_lonlat_bounds_for_normalized_crs(tmp_path, crs) -> None:
    _journal, store, authority = _store_with_source(tmp_path)
    wire = _approve(store, authority).planning_binding.model_dump(by_alias=True, mode="json")
    target = wire["targetWorkAreas"][0]
    target["crs"] = crs
    target["polygon"]["coordinates"] = [[[200, 100], [201, 100], [201, 101], [200, 100]]]
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "schemas"
            / "external-planning-only-work-order-binding.v1.json"
        ).read_text()
    )
    assert not Draft202012Validator(schema).is_valid(wire)
    target["polygon"]["coordinates"] = [[[127, 37], [128, 37], [128, 38], [127, 37]]]
    assert Draft202012Validator(schema).is_valid(wire)


def test_approval_rejects_revocation_during_historical_resolution(tmp_path, monkeypatch):
    journal, store, authority = _store_with_source(tmp_path)
    port = store._external_reobservation_authority_port
    original = port.resolve_historical
    before = (tmp_path / "work-orders.jsonl").read_bytes()

    def revoke_during_history(**kwargs):
        result = original(**kwargs)
        port.revoke()
        return result

    monkeypatch.setattr(port, "resolve_historical", revoke_during_history)
    with pytest.raises(RuntimeError, match="AUTHORITY_UNAVAILABLE"):
        _approve(store, authority)
    assert (tmp_path / "work-orders.jsonl").read_bytes() == before
    assert store.list_external_reobservation_bindings(organization_id="org-1") == []


def test_approval_holds_current_guard_through_append_without_scope_callbacks(tmp_path, monkeypatch):
    journal, store, authority = _store_with_source(tmp_path)
    port = store._external_reobservation_authority_port
    original_append = journal.append
    attempted = threading.Event()
    revoked = threading.Event()
    threads = []

    def revoke():
        attempted.set()
        port.revoke()
        revoked.set()

    def append_under_guard(record):
        assert port.guard_held
        thread = threading.Thread(target=revoke)
        threads.append(thread)
        thread.start()
        assert attempted.wait(1)
        assert not revoked.is_set()
        original_append(record)

    def forbidden_scope(**kwargs):
        raise AssertionError(
            "scope callbacks must be resolved inside authority guard, not order lock"
        )

    monkeypatch.setattr(journal, "append", append_under_guard)
    monkeypatch.setattr(store, "_validate_scope", forbidden_scope)
    try:
        result = _approve(store, authority)
    finally:
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()
    assert revoked.is_set()
    assert not port.guard_held
    assert _approve(store, authority) == result


@pytest.mark.parametrize("component", ["bad-z", True, None, float("nan"), float("inf"), 10**400])
def test_external_target_snapshot_rejects_invalid_later_coordinates(component):
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0, component], [1, 0, component], [1, 1, component], [0, 0, component]]
        ],
    }
    with pytest.raises(ValueError):
        ExternalWorkAreaSnapshotV1(
            work_area_id="area-1", revision=1, polygon=polygon, crs="EPSG:5186"
        ).sealed()


def test_external_target_preserves_valid_higher_coordinates():
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0, 2.5], [1, 0, 3.5], [1, 1, 4.5], [0, 0, 2.5]]],
    }
    snapshot = ExternalWorkAreaSnapshotV1(
        work_area_id="area-1", revision=1, polygon=polygon, crs="EPSG:5186"
    ).sealed()
    assert snapshot.polygon == polygon

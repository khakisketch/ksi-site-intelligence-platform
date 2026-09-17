"""Durable exact reviews for external single-volume results beside relative ones.

The actual durable Core review store, report ledgers and decision store are
used; only independent execution/use authority providers are synthetic.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import external_product_loop_fixture
import pytest
from external_product_loop_fixture import LoopGraph, build_graph, record_measurement, seed_original
from external_single_volume_fixture import _authority, _AuthorityPort, _payload, _store
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, mount_auth
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeVerdict,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeObservedReportInput,
    ExternalSingleVolumeStore,
)
from ksi_core.domains.external.workflow.external_result_reviews import (
    ExternalResultReviewRecoveryError,
    ExternalResultReviewSourceV1,
    ExternalResultReviewStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
from ksi_core.external_result_workflow_api import build_external_result_workflow_router
from ksi_core.external_use_decisions import ExternalDecisionIntent
from ksi_core.leasing import LeaseFence
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import DecisionVerdict
from ksi_event_contracts.external_result_review import ExternalResultReviewReceiptV1
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeReportV1,
)
from ksi_event_contracts.external_single_volume_result_review import (
    SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS,
    ExternalSingleVolumeResultReviewReceiptV1,
)
from test_external_result_review_proposals import _NOW, _TOKEN, _principal, _token_record

_ORG = "org-a"
_DECISION_ID = "decision-single"
_SINGLE_KIND = "external-single-volume-result-reviewed"
_RELATIVE_KIND = "external-result-reviewed"
_WORKER_A = "6f1c2d9e-0000-4000-8000-00000000000a"
_LEASE_A = "6f1c2d9e-0000-4000-8000-00000000000b"
_WORKER_R = "6f1c2d9e-0000-4000-8000-00000000000c"
_LEASE_R = "6f1c2d9e-0000-4000-8000-00000000000d"


class _SingleAuthority(_AuthorityPort):
    """Synthetic single execution authority that also answers historical use."""

    def __init__(self, authority: ExternalSingleVolumeExecutionAuthority) -> None:
        super().__init__(authority)
        self.use_revoked_at: datetime | None = None

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        if self.use_revoked_at is not None and evaluated_at >= self.use_revoked_at:
            return None
        return self.resolve_historical(
            historical_authority_digest=historical_authority_digest,
            decision_id=decision_id,
            decision_digest=decision_digest,
            issued_at=evaluated_at,
            now=evaluated_at,
        )


def _decision(authority: ExternalSingleVolumeExecutionAuthority) -> ExternalSingleVolumeDecisionV1:
    subject = authority.target.subject
    return ExternalSingleVolumeDecisionV1(
        decision_id=_DECISION_ID,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        policy_digest=authority.validation_policy_digest,
        inspection_report_digest=authority.target.inspection_report_digest,
        evidence_record_digests=authority.evidence_record_digests,
        zone=authority.zone_snapshot.to_zone_reference(),
        compatibility_mapping_digest=authority.compatibility_mapping_digest,
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("USE_ELIGIBLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",),
        decided_at=_NOW,
    ).sealed()


def _single_authority(source: ExternalResultReviewSourceV1) -> _SingleAuthority:
    authority = _authority(
        work_order_id=source.authority.current_work_order_id,
        work_area_id=source.authority.zone_snapshot.work_area_id,
        now=_NOW,
        captured_to=_NOW - timedelta(hours=1),
    )
    decision_digest = _decision(authority).decision_digest
    assert decision_digest is not None
    return _SingleAuthority(
        replace(authority, decision_id=_DECISION_ID, decision_digest=decision_digest)
    )


def _factory(
    path: Path, port: _SingleAuthority
) -> Callable[
    [ExternalAuthorityCurrentnessCoordinator], tuple[ExternalSingleVolumeStore, _SingleAuthority]
]:
    def build(
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> tuple[ExternalSingleVolumeStore, _SingleAuthority]:
        port.currentness_coordinator = coordinator
        return _store(path, port, now=_NOW), port

    return build


def _open(
    path: Path,
    source: ExternalResultReviewSourceV1,
    port: _SingleAuthority,
    *,
    configured: bool = True,
) -> tuple[LoopGraph, ExternalSingleVolumeStore]:
    """The loop graph plus a single store on its coordinator (reviewable if ``configured``)."""

    if configured:
        graph = build_graph(path, source, single=_factory(path, port))
        assert graph.single_volumes is not None
        return graph, graph.single_volumes
    graph = build_graph(path, source)
    port.currentness_coordinator = graph.service.coordinator
    store = _store(path, port, now=_NOW)
    graph.journals.append(store._journal)  # noqa: SLF001 - close with the graph.
    return graph, store


def _new(
    path: Path, *, configured: bool = True
) -> tuple[LoopGraph, ExternalSingleVolumeStore, _SingleAuthority]:
    source = seed_original(path)
    port = _single_authority(source)
    graph, store = _open(path, source, port, configured=configured)
    return graph, store, port


def _record_single(
    graph: LoopGraph,
    store: ExternalSingleVolumeStore,
    port: _SingleAuthority,
    *,
    stage_decision: bool = True,
) -> ExternalSingleVolumeReportV1:
    authority = port.authority
    if stage_decision:
        decision = _decision(authority)
        graph.decisions.stage_evaluated(
            decision,
            intent=ExternalDecisionIntent.from_candidate(decision),
            principal=_principal(),
            idempotency_key="single-decision",
        )
        graph.decisions.reconcile_pending()
    issued = store.issue(
        principal=_principal(),
        current_work_order_id=authority.current_work_order_id,
        decision_ref=_DECISION_ID,
        idempotency_key="single-volume",
        now=_NOW,
    )
    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED, issued.detail
    assert issued.record is not None and issued.record.request.request_digest is not None
    request = issued.record.request
    leased = store.claim(
        request.request_id,
        organization_id=_ORG,
        principal_id="worker-principal",
        fence=LeaseFence(_WORKER_A, _LEASE_A, 0),
        now=_NOW,
    )
    assert leased.fence is not None, leased.detail
    result = store.record_observed_report(
        request.request_id,
        organization_id=_ORG,
        principal_id="worker-principal",
        fence=leased.fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(request.request_digest or "", authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert result.verdict is ExternalRelativeVolumeVerdict.REPORTED, result.detail
    assert result.record is not None and result.record.report is not None
    return result.record.report


def _review(graph: LoopGraph, report_ref: str, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "organization_id": _ORG,
        "report_ref": report_ref,
        "principal": _principal(),
        "evaluated_at": _NOW,
    }
    arguments.update(overrides)
    return graph.service.reviews.review(**arguments)


def _journal_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_single_report_review_is_durable_and_idempotent(tmp_path: Path) -> None:
    graph, store, port = _new(tmp_path)
    try:
        report = _record_single(graph, store, port)
        receipt = _review(graph, report.report_id)
        assert isinstance(receipt, ExternalSingleVolumeResultReviewReceiptV1)
        assert receipt.review_ref.startswith("err-v1-")
        assert receipt.review_digest == receipt.canonical_digest()
        assert receipt.report == report
        assert receipt.decision.decision_id == _DECISION_ID
        assert receipt.authority.authority_digest == receipt.authority.canonical_digest()
        assert tuple(receipt.factual_limitations) == SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS
        assert receipt.reviewed_at == _NOW
        assert _review(graph, report.report_id) == receipt
        assert graph.service.reviews.get_scoped(receipt.review_ref, organization_id=_ORG) == (
            receipt
        )
        assert graph.service.reviews.get_scoped(receipt.review_ref, organization_id="org-b") is None
        lines = _journal_lines(tmp_path / "reviews.jsonl")
        assert [line["kind"] for line in lines] == [_SINGLE_KIND]
        assert lines[0]["review"]["contractVersion"] == (
            "external-single-volume-result-review-receipt.v1"
        )
        assert graph.single_volumes is store
        adapter = graph.service.reviews.source_port
        assert isinstance(adapter, CoreExternalResultReviewSourceAdapter)
        assert adapter.uses_single_volume_store(store)
        assert not adapter.uses_single_volume_store(graph.volumes)  # type: ignore[arg-type]
    finally:
        graph.close()


def test_relative_review_bytes_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        external_product_loop_fixture, "_fence", lambda: LeaseFence(_WORKER_R, _LEASE_R, 1)
    )
    seed = tmp_path / "seed"
    source = seed_original(seed)
    for name, configured in (("with-single", True), ("relative-only", False)):
        path = tmp_path / name
        shutil.copytree(seed, path)
        graph, _ = _open(path, source, _single_authority(source), configured=configured)
        try:
            report = record_measurement(graph)
            receipt = _review(graph, report.report_id)
            assert isinstance(receipt, ExternalResultReviewReceiptV1)
        finally:
            graph.close()
    with_single = (tmp_path / "with-single" / "reviews.jsonl").read_bytes()
    relative_only = (tmp_path / "relative-only" / "reviews.jsonl").read_bytes()
    assert with_single == relative_only
    kinds = [line["kind"] for line in _journal_lines(tmp_path / "with-single" / "reviews.jsonl")]
    assert kinds == [_RELATIVE_KIND]


def test_single_review_replays_and_verifies_historically(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    port = _single_authority(source)
    graph, store = _open(tmp_path, source, port)
    try:
        report = _record_single(graph, store, port)
        receipt = _review(graph, report.report_id)
    finally:
        graph.close()
    reopened, _ = _open(tmp_path, source, port)
    try:
        reviews = reopened.service.reviews
        assert reviews.get_for_report(report.report_id, organization_id=_ORG) == receipt
        assert reviews.list_scoped(organization_id=_ORG) == (receipt,)
        assert receipt.review_digest is not None
        assert (
            reviews.verify_historical(
                review_ref=receipt.review_ref,
                review_digest=receipt.review_digest,
                evaluated_at=receipt.reviewed_at,
            )
            == receipt
        )
        assert (
            reviews.resolve_historical(
                review_ref=receipt.review_ref,
                review_digest=receipt.review_digest,
                actor="operator-a",
                evaluated_at=receipt.reviewed_at,
            )
            == receipt
        )
        assert (
            reviews.resolve_historical(
                review_ref=receipt.review_ref,
                review_digest=receipt.review_digest,
                actor="operator-z",
                evaluated_at=receipt.reviewed_at,
            )
            is None
        )
        port.use_revoked_at = receipt.reviewed_at - timedelta(seconds=1)
        assert (
            reviews.verify_historical(
                review_ref=receipt.review_ref,
                review_digest=receipt.review_digest,
                evaluated_at=receipt.reviewed_at,
            )
            is None
        )
    finally:
        reopened.close()


def test_single_review_is_closed_without_authority(tmp_path: Path) -> None:
    unavailable = "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"
    graph, store, port = _new(tmp_path / "authority")
    try:
        report = _record_single(graph, store, port)
        with pytest.raises(RuntimeError, match=unavailable):
            _review(graph, report.report_id, principal=_principal(principal_id="operator-z"))
        with pytest.raises(RuntimeError, match=unavailable):
            _review(graph, report.report_id, evaluated_at=port.authority.valid_until)
        port.use_revoked_at = _NOW
        with pytest.raises(RuntimeError, match=unavailable):
            _review(graph, report.report_id)
        assert graph.service.reviews.get_for_report(report.report_id, organization_id=_ORG) is None
    finally:
        graph.close()
    graph, store, port = _new(tmp_path / "decision")
    try:
        report = _record_single(graph, store, port, stage_decision=False)
        with pytest.raises(RuntimeError, match=unavailable):
            _review(graph, report.report_id)
    finally:
        graph.close()
    graph, store, port = _new(tmp_path / "unconfigured", configured=False)
    try:
        report = _record_single(graph, store, port)
        with pytest.raises(RuntimeError, match=unavailable):
            _review(graph, report.report_id)
        assert graph.service.reviews.list_scoped(organization_id=_ORG) == ()
    finally:
        graph.close()


def _event(kind: str, review: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {"kind": kind, "version": 1, "review": review}
    raw["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
    return raw


def test_replay_rejects_kind_and_receipt_mismatch(tmp_path: Path) -> None:
    graph, store, port = _new(tmp_path / "graph")
    try:
        relative = record_measurement(graph)
        single = _record_single(graph, store, port)
        _review(graph, relative.report_id)
        _review(graph, single.report_id)
    finally:
        graph.close()
    lines = _journal_lines(tmp_path / "graph" / "reviews.jsonl")
    assert [line["kind"] for line in lines] == [_RELATIVE_KIND, _SINGLE_KIND]
    relative_wire, single_wire = lines[0]["review"], lines[1]["review"]
    for name, event in (
        ("single-as-relative", _event(_RELATIVE_KIND, single_wire)),
        ("relative-as-single", _event(_SINGLE_KIND, relative_wire)),
        ("unknown-kind", _event("external-other-reviewed", single_wire)),
    ):
        path = tmp_path / f"{name}.jsonl"
        journal = DurableJournal(path)
        journal.append(event)
        journal.close()
        with pytest.raises(ExternalResultReviewRecoveryError):
            ExternalResultReviewStore(
                DurableJournal(path), coordinator=ExternalAuthorityCurrentnessCoordinator()
            )
    # The unmodified mixed journal replays both families.
    ok = tmp_path / "ok.jsonl"
    journal = DurableJournal(ok)
    for event in (_event(_RELATIVE_KIND, relative_wire), _event(_SINGLE_KIND, single_wire)):
        journal.append(event)
    journal.close()
    replayed = ExternalResultReviewStore(
        DurableJournal(ok), coordinator=ExternalAuthorityCurrentnessCoordinator()
    )
    assert replayed.organization_ids() == frozenset({_ORG})
    assert len(replayed.list_scoped(organization_id=_ORG)) == 2


def test_adapter_requires_both_single_arguments(tmp_path: Path) -> None:
    graph, store, port = _new(tmp_path)
    try:
        common: dict[str, Any] = {
            "volume_store": graph.volumes,
            "decisions": graph.decisions,
            "historical_use_authority": graph.history,
            "coordinator": graph.service.coordinator,
        }
        with pytest.raises(ValueError):
            CoreExternalResultReviewSourceAdapter(**common, single_volume_store=store)
        with pytest.raises(ValueError):
            CoreExternalResultReviewSourceAdapter(**common, single_historical_use_authority=port)
        foreign_path = tmp_path / "foreign"
        foreign_path.mkdir()
        foreign_port = _SingleAuthority(port.authority)
        foreign = _store(foreign_path, foreign_port, now=_NOW)
        try:
            with pytest.raises(ValueError):
                CoreExternalResultReviewSourceAdapter(
                    **common,
                    single_volume_store=foreign,
                    single_historical_use_authority=foreign_port,
                )
        finally:
            foreign._journal.close()  # noqa: SLF001
        relative_only = CoreExternalResultReviewSourceAdapter(**common)
        assert not relative_only.uses_single_volume_store(store)
    finally:
        graph.close()


def test_relative_review_route_rejects_single_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned before SV-3b: this route answered 409 SOURCE_UNAVAILABLE for a single ref."""

    graph, store, port = _new(tmp_path)
    try:
        report = _record_single(graph, store, port)
        app = FastAPI()
        mount_auth(app, AuthRegistry([_token_record()]))
        app.include_router(
            build_external_result_workflow_router(
                graph.volumes, graph.service, single_volumes=store, clock=lambda: _NOW
            )
        )

        def unexpected(*_: object, **__: object) -> None:
            raise AssertionError("the relative review route must not reach the review store")

        monkeypatch.setattr(graph.service.reviews, "get_for_report", unexpected)
        monkeypatch.setattr(graph.service.reviews, "review", unexpected)
        with TestClient(app) as client:
            response = client.post(
                f"/v1/external-relative-volume-reports/{report.report_id}/reviews",
                headers={"Authorization": f"Bearer {_TOKEN}"},
                json={},
            )
        assert response.status_code == 409
        assert response.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        monkeypatch.undo()
        assert graph.service.reviews.get_for_report(report.report_id, organization_id=_ORG) is None
    finally:
        graph.close()

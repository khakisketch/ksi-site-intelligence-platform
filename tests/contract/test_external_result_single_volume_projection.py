"""Core's read-only projector shows single-volume results beside relative ones."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from external_product_loop_fixture import LoopGraph, build_graph, record_measurement, seed_original
from external_single_volume_fixture import (
    _authority,
    _AuthorityPort,
    _digest,
    _issue_and_claim,
    _payload,
    _store,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeVerdict,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeObservedReportInput,
    ExternalSingleVolumeStore,
)
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.foundation.api_base import iso_utc
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeReportV1
from test_external_relative_volumes import _fence
from test_external_relative_volumes import _payload as _relative_payload
from test_external_result_review_proposals import _NOW, _principal

_ORG = "org-a"
_SITE = "site-a"
_RELATIVE = frozenset({"EXTERNAL_RELATIVE_VOLUME"})


@dataclass
class _Harness:
    graph: LoopGraph
    port: _AuthorityPort
    single: ExternalSingleVolumeStore

    def projector(self, *, with_single: bool = True) -> ExternalResultReadProjector:
        return ExternalResultReadProjector(
            volumes=self.graph.volumes,
            workflow=self.graph.service,
            single_volumes=self.single if with_single else None,
            clock=lambda: _NOW,
        )


def _single_authority(
    graph: LoopGraph, *, captured_to: datetime, work_order_id: str | None = None
) -> ExternalSingleVolumeExecutionAuthority:
    source = graph.source.authority
    return _authority(
        work_order_id=work_order_id or source.current_work_order_id,
        organization_id=_ORG,
        site_id=_SITE,
        work_area_id=source.zone_snapshot.work_area_id,
        now=_NOW,
        captured_to=captured_to,
    )


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[_Harness]:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    port = _AuthorityPort(
        _single_authority(graph, captured_to=_NOW + timedelta(hours=4)),
        coordinator=graph.service.coordinator,
    )
    single = _store(tmp_path, port, now=_NOW)
    try:
        yield _Harness(graph, port, single)
    finally:
        single._journal.close()
        graph.close()


def _record_single(harness: _Harness, key: str = "single-key") -> ExternalSingleVolumeReportV1:
    authority = harness.port.authority
    request_id, request_digest, fence = _issue_and_claim(
        harness.single,
        key,
        work_order_id=authority.current_work_order_id,
        organization_id=_ORG,
        now=_NOW,
    )
    result = harness.single.record_observed_report(
        request_id,
        organization_id=_ORG,
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(request_digest, authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert result.verdict is ExternalRelativeVolumeVerdict.REPORTED, result.detail
    assert result.record is not None and result.record.report is not None
    return result.record.report


def _record_second_relative(harness: _Harness) -> ExternalRelativeVolumeReportV1:
    """A later relative report under a distinct authority that also resolves historically."""

    graph = harness.graph
    port = graph.authority_port
    first = port.authority
    current = first.current.model_copy(
        update={
            "observed_sha256": _digest("dsm-bytes-current-second"),
            "captured_from": _NOW + timedelta(hours=5),
            "captured_to": _NOW + timedelta(hours=6),
        }
    )
    second = replace(
        first,
        current=current,
        historical_authority_digest=_digest("historical-authority-second"),
    )
    port.authority = second
    by_digest = {a.historical_authority_digest: a for a in (first, second)}

    def resolve_historical(
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del now
        a = by_digest.get(historical_authority_digest)
        if (
            a is None
            or a.decision_id != decision_id
            or a.decision_digest != decision_digest
            or not a.is_current_at(issued_at)
        ):
            return None
        return a

    port.resolve_historical = resolve_historical  # type: ignore[method-assign]
    issued = graph.volumes.issue(
        principal=_principal(),
        current_work_order_id=second.current_work_order_id,
        decision_ref=second.decision_id,
        idempotency_key="second-relative",
        now=_NOW,
    )
    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED, issued.detail
    assert issued.record is not None and issued.record.request.request_digest is not None
    request = issued.record.request
    fence = _fence()
    graph.volumes.claim(
        request.request_id, organization_id=_ORG, principal_id="worker", fence=fence, now=_NOW
    )
    assert request.request_digest is not None
    result = graph.volumes.record_observed_report(
        request.request_id,
        organization_id=_ORG,
        principal_id="worker",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            payload=_relative_payload(request.request_digest, second), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert result.record is not None and result.record.report is not None, result.detail
    return result.record.report


def test_single_report_projects_as_single_kind(harness: _Harness) -> None:
    report = _record_single(harness)
    projection = harness.projector().report_for_site(_SITE, report.report_id, organization_id=_ORG)

    assert projection.state == "AVAILABLE"
    result = projection.result
    assert result is not None
    target = harness.port.authority.target
    assert result.kind == "EXTERNAL_SINGLE_VOLUME"
    assert result.report_ref == report.report_id
    assert result.report_digest == report.report_digest
    assert result.baseline_work_order_id is None
    assert result.baseline_captured_from is None
    assert result.baseline_captured_to is None
    assert result.current_captured_from == target.captured_from
    assert result.current_captured_to == target.captured_to
    assert result.current_work_order_id == harness.port.authority.current_work_order_id
    assert result.metrics is not None
    assert result.metrics.base_roughness_m == report.payload.metrics.base_roughness_m
    assert result.metrics.boundary_cell_count == report.payload.metrics.boundary_cell_count
    assert result.metrics.fill_m3 == report.payload.metrics.fill_m3
    assert result.execution_policy.policy_id == "single-policy-a"
    assert result.review_ref is None
    assert result.proposal_count == 0
    assert result.approved_proposal_count == 0


def test_relative_history_is_unchanged_by_single_reports(harness: _Harness) -> None:
    record_measurement(harness.graph)
    _record_single(harness)
    relative_only = harness.projector(with_single=False).history_for_site(
        _SITE, organization_id=_ORG, after=None, limit=10
    )
    filtered = harness.projector().history_for_site(
        _SITE, organization_id=_ORG, after=None, limit=10, kinds=_RELATIVE
    )

    assert len(filtered.items) == 1
    assert filtered.model_dump(mode="json") == relative_only.model_dump(mode="json")
    relative_row = relative_only.items[0].result
    assert relative_row is not None and relative_row.kind == "EXTERNAL_RELATIVE_VOLUME"
    assert relative_row.metrics is not None and relative_row.metrics.base_roughness_m is None


def test_merged_history_orders_both_families_newest_first_and_pages(
    harness: _Harness,
) -> None:
    older_relative = record_measurement(harness.graph)  # current captured_to = +3h
    single = _record_single(harness)  # target captured_to = +4h
    newer_relative = _record_second_relative(harness)  # current captured_to = +6h
    keys = [
        (_NOW + timedelta(hours=3), older_relative.reported_at, older_relative.report_id),
        (_NOW + timedelta(hours=4), single.reported_at, single.report_id),
        (_NOW + timedelta(hours=6), newer_relative.reported_at, newer_relative.report_id),
    ]
    expected = [key[2] for key in sorted(keys, reverse=True)]
    assert expected == [newer_relative.report_id, single.report_id, older_relative.report_id]
    projector = harness.projector()

    first = projector.history_for_site(_SITE, organization_id=_ORG, after=None, limit=2)
    assert [item.report_ref for item in first.items] == expected[:2]
    assert [item.state for item in first.items] == ["AVAILABLE", "AVAILABLE"]
    assert first.next_cursor == expected[1]
    second = projector.history_for_site(
        _SITE, organization_id=_ORG, after=first.next_cursor, limit=2
    )
    assert [item.report_ref for item in second.items] == expected[2:]
    assert second.next_cursor is None
    site = projector.for_site(_SITE, organization_id=_ORG)
    assert site.result is not None and site.result.report_ref == expected[0]
    with pytest.raises(LookupError):
        projector.history_for_site(_SITE, organization_id="org-b", after=single.report_id, limit=2)
    with pytest.raises(LookupError):
        projector.history_for_site(
            _SITE,
            organization_id=_ORG,
            after="external-single-volume-report-unknown",
            limit=2,
        )


def test_single_report_with_unavailable_authority_is_truthful(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = record_measurement(harness.graph)  # older: +3h
    single = _record_single(harness)  # newer: +4h
    monkeypatch.setattr(harness.port, "resolve_historical", lambda **_: None)
    projector = harness.projector()

    history = projector.history_for_site(_SITE, organization_id=_ORG, after=None, limit=10)
    assert [(item.report_ref, item.state) for item in history.items] == [
        (single.report_id, "HISTORICAL_SOURCE_UNAVAILABLE"),
        (relative.report_id, "AVAILABLE"),
    ]
    assert history.items[0].result is None
    site = projector.for_site(_SITE, organization_id=_ORG)
    assert site.state == "HISTORICAL_SOURCE_UNAVAILABLE"
    assert site.result is None
    exact = projector.report_for_site(_SITE, single.report_id, organization_id=_ORG)
    assert exact.state == "HISTORICAL_SOURCE_UNAVAILABLE"


def test_for_work_order_includes_single_results(harness: _Harness) -> None:
    graph = harness.graph
    area_id = graph.source.authority.zone_snapshot.work_area_id
    order = graph.service.work_orders.create_work_order(
        organization_id=_ORG,
        site_id=_SITE,
        name="Stockpile survey",
        work_area_ids=[area_id],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    harness.port.authority = _single_authority(
        graph, captured_to=_NOW + timedelta(hours=4), work_order_id=order.work_order_id
    )
    single = _record_single(harness)
    projector = harness.projector()

    projection = projector.for_work_order(order.work_order_id, organization_id=_ORG)
    assert projection.state == "AVAILABLE"
    assert projection.result is not None
    assert projection.result.report_ref == single.report_id
    assert projection.result.kind == "EXTERNAL_SINGLE_VOLUME"
    without_single = harness.projector(with_single=False).for_work_order(
        order.work_order_id, organization_id=_ORG
    )
    assert without_single.state == "NO_RESULT"


def test_single_report_newer_than_relative_wins_for_shared_work_order(
    harness: _Harness,
) -> None:
    relative = record_measurement(harness.graph)
    single = _record_single(harness)
    work_order_id = harness.graph.source.authority.current_work_order_id
    projection = harness.projector().for_work_order(work_order_id, organization_id=_ORG)
    assert projection.result is not None and projection.result.report_ref == single.report_id
    relative_only = harness.projector(with_single=False).for_work_order(
        work_order_id, organization_id=_ORG
    )
    assert relative_only.result is not None
    assert relative_only.result.report_ref == relative.report_id


def test_citation_for_single_result(harness: _Harness) -> None:
    single = _record_single(harness)
    projector = harness.projector()
    projection = projector.report_for_site(_SITE, single.report_id, organization_id=_ORG)
    citation = projector.citation_for(projection, site_name="Synthetic site")

    assert citation is not None
    target = harness.port.authority.target
    assert single.report_digest is not None
    assert citation.citation_id == (
        f"external-single-volume-report:{single.report_id}:"
        f"{single.report_digest.removeprefix('sha256:')}"
    )
    assert citation.object_type == "EXTERNAL_SINGLE_VOLUME_REPORT"
    assert citation.object_id == single.report_id
    assert citation.source_path == (
        "/v1/external-single-volume-reports/" + quote(single.report_id, safe="")
    )
    assert citation.captured_from == iso_utc(target.captured_from)
    assert citation.captured_to == iso_utc(target.captured_to)
    assert citation.label.endswith("외부 단일 시점 체적 결과")
    assert citation.model_version == "single-policy-a:1"


def test_projector_rejects_single_store_on_another_coordinator(
    harness: _Harness, tmp_path: Path
) -> None:
    foreign_path = tmp_path / "foreign"
    foreign_path.mkdir()
    foreign = _store(foreign_path, _AuthorityPort(harness.port.authority), now=_NOW)
    try:
        with pytest.raises(ValueError, match="exact durable volume graph"):
            ExternalResultReadProjector(
                volumes=harness.graph.volumes,
                workflow=harness.graph.service,
                single_volumes=foreign,
            )
        projector = harness.projector()
        assert projector.single_volumes is harness.single
        assert projector.uses_exact_graph(
            volumes=harness.graph.volumes,
            workflow=harness.graph.service,
            single_volumes=harness.single,
        )
        assert not projector.uses_exact_graph(
            volumes=harness.graph.volumes,
            workflow=harness.graph.service,
            single_volumes=foreign,
        )
        assert not projector.uses_exact_graph(
            volumes=harness.graph.volumes, workflow=harness.graph.service
        )
    finally:
        foreign._journal.close()

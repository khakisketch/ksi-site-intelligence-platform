"""External result briefings are deterministic, cited, idempotent and never block the mutation."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from external_product_loop_fixture import LoopGraph, build_graph, record_measurement, seed_original
from external_single_volume_fixture import _authority as _build_single_authority
from external_single_volume_fixture import _AuthorityPort as _SingleAuthorityPort
from external_single_volume_fixture import _digest
from external_single_volume_fixture import _issue_and_claim as _single_issue_and_claim
from external_single_volume_fixture import _payload as _single_payload
from external_single_volume_fixture import _store as _single_store
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
from ksi_core.domains.external.workflow import external_result_briefings as briefings_module
from ksi_core.domains.external.workflow.external_result_briefings import (
    ExternalResultBriefingProjector,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.site_workspace import SiteBriefingStore
from ksi_event_contracts.copilot import SiteBriefingStatus
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeMetricsV1,
    ExternalSingleVolumeReportV1,
)
from test_external_relative_volumes import _fence
from test_external_relative_volumes import _payload as _relative_payload
from test_external_result_review_proposals import _NOW, _principal
from test_external_single_volume_result_reviews import _new
from test_external_single_volume_result_reviews import _record_single as _record_reviewable_single
from test_external_single_volume_result_reviews import _review as _review_single

_MEASURED_AREA_M2 = 123.0


def _projector(
    tmp_path: Path, graph: LoopGraph
) -> tuple[SiteBriefingStore, ExternalResultBriefingProjector]:
    briefings = SiteBriefingStore(
        DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=graph.service.sites
    )
    read = ExternalResultReadProjector(
        volumes=graph.volumes, workflow=graph.service, clock=lambda: _NOW
    )
    projector = ExternalResultBriefingProjector(
        briefings=briefings, projector=read, work_areas=graph.service.work_areas, clock=lambda: _NOW
    )
    projector.bind(volumes=graph.volumes, reviews=graph.service.reviews, service=graph.service)
    return briefings, projector


def _single_harness(
    tmp_path: Path, graph: LoopGraph, *, target_rmse_m: float | None = 0.06
) -> tuple[ExternalSingleVolumeStore, ExternalSingleVolumeExecutionAuthority]:
    source = graph.source.authority
    authority = _build_single_authority(
        work_order_id=source.current_work_order_id,
        target_rmse_m=target_rmse_m,
        organization_id="org-a",
        site_id="site-a",
        work_area_id=source.zone_snapshot.work_area_id,
        now=_NOW,
        captured_to=_NOW + timedelta(hours=4),
    )
    port = _SingleAuthorityPort(authority, coordinator=graph.service.coordinator)
    single = _single_store(tmp_path, port, now=_NOW)
    return single, authority


def _record_single_report(
    single: ExternalSingleVolumeStore,
    authority: ExternalSingleVolumeExecutionAuthority,
    *,
    fill_m3: float,
    base_roughness_m: float,
    uncertainty_m3: float | None | str = "exact",
    key: str = "single-key",
) -> ExternalSingleVolumeReportV1:
    if uncertainty_m3 == "exact":
        uncertainty: float | None = (
            None
            if authority.target_rmse_m is None
            else _MEASURED_AREA_M2 * math.hypot(base_roughness_m, authority.target_rmse_m)
        )
    else:
        uncertainty = cast("float | None", uncertainty_m3)
    metrics = ExternalSingleVolumeMetricsV1(
        zone_cell_count=400,
        common_valid_cell_count=400,
        zone_area_m2=_MEASURED_AREA_M2,
        measured_area_m2=_MEASURED_AREA_M2,
        common_valid_fraction=1.0,
        cut_m3=0.0,
        fill_m3=fill_m3,
        net_m3=fill_m3,
        threshold_m=authority.execution_policy.threshold_m,
        uncertainty_m3=uncertainty,
        uncertainty_note="single epoch boundary base",
        base_roughness_m=base_roughness_m,
        boundary_cell_count=20,
        boundary_sample_count=20,
        boundary_valid_fraction=1.0,
    )
    request_id, request_digest, fence = _single_issue_and_claim(
        single,
        key,
        work_order_id=authority.current_work_order_id,
        organization_id="org-a",
        now=_NOW,
    )
    payload = _single_payload(request_digest, authority, metrics)
    result = single.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(payload=payload, computed_at=_NOW),
        now=_NOW,
    )
    assert result.verdict is ExternalRelativeVolumeVerdict.REPORTED, result.detail
    assert result.record is not None and result.record.report is not None
    return result.record.report


def _projector_with_single(
    tmp_path: Path, graph: LoopGraph, *, target_rmse_m: float | None = 0.06
) -> tuple[
    SiteBriefingStore,
    ExternalResultBriefingProjector,
    ExternalSingleVolumeStore,
    ExternalSingleVolumeExecutionAuthority,
]:
    single, authority = _single_harness(tmp_path, graph, target_rmse_m=target_rmse_m)
    briefings = SiteBriefingStore(
        DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=graph.service.sites
    )
    read = ExternalResultReadProjector(
        volumes=graph.volumes, workflow=graph.service, single_volumes=single, clock=lambda: _NOW
    )
    projector = ExternalResultBriefingProjector(
        briefings=briefings, projector=read, work_areas=graph.service.work_areas, clock=lambda: _NOW
    )
    projector.bind(
        volumes=graph.volumes,
        reviews=graph.service.reviews,
        service=graph.service,
        single_volumes=single,
    )
    return briefings, projector, single, authority


def test_report_review_and_approval_each_record_one_cited_briefing(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector = _projector(tmp_path, graph)
    report = record_measurement(graph)
    assert projector.flush()

    first = briefings.latest("site-a", organization_id="org-a")
    assert first is not None and first.status is SiteBriefingStatus.READY
    assert first.source_watermark == f"external-report:{report.report_digest}:REPORTED"
    assert "순변화 4.0 m³" in first.what_changed
    assert "-0.0" not in first.what_changed
    assert "첫 결과" in first.why_it_matters
    assert first.decision_prompt == "결과와 근거를 검토하세요."
    assert {citation.source_path for citation in first.citations} == {
        f"/v1/external-relative-volume-reports/{report.report_id}",
        f"/v1/sites/site-a/observations/{report.report_id}",
    }

    principal = _principal()
    graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    assert projector.flush()
    reviewed = briefings.latest("site-a", organization_id="org-a")
    assert reviewed is not None and reviewed.source_watermark.endswith(":REVIEWED")
    assert reviewed.decision_prompt == "재관측이 필요하면 제안을 만들고 승인하세요."

    created = graph.service.create(
        organization_id="org-a",
        report_ref=report.report_id,
        target_work_area_ids=(source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
        idempotency_key="proposal-1",
    )
    approved = graph.service.approve(
        organization_id="org-a",
        proposal_ref=created.proposal_ref,
        expected_version=1,
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
        idempotency_key="approve-1",
    )
    assert projector.flush()
    done = briefings.latest("site-a", organization_id="org-a")
    assert done is not None and done.source_watermark.endswith(":APPROVED")
    assert approved.approval_receipt.successor_work_order_id in done.decision_prompt
    assert [item.briefing_id for item in briefings.latest_for_organization("org-a")] == [
        done.briefing_id
    ]
    assert briefings.latest_for_organization("org-b") == []
    graph.close()


def test_same_watermark_is_not_recorded_twice(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector = _projector(tmp_path, graph)
    report = record_measurement(graph)
    record = graph.volumes.get(report.request_id, organization_id="org-a")
    assert record is not None
    projector.on_report(record)  # duplicate delivery
    assert projector.flush()
    journal = (tmp_path / "site-briefings.jsonl").read_text().strip().splitlines()
    assert len(journal) == 1
    assert briefings.latest("site-a", organization_id="org-a") is not None
    graph.close()


def test_single_volume_report_briefing_sentence(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector, single, authority = _projector_with_single(tmp_path, graph)
    report = _record_single_report(single, authority, fill_m3=1234.5, base_roughness_m=0.08)
    assert projector.flush()

    zone = graph.service.work_areas.get(source.authority.zone_snapshot.work_area_id)
    assert zone is not None
    latest = briefings.latest("site-a", organization_id="org-a")
    assert latest is not None and latest.status is SiteBriefingStatus.READY
    assert latest.what_changed == (
        f"{zone.name} 적치물 체적 1,234.5 m³ (±12.3 m³, 기저면 거칠기 0.08 m)."
    )
    assert latest.why_it_matters == (
        "단일 시점 측정입니다. 같은 구역의 다음 측정과 비교할 수 있습니다."
    )
    assert latest.decision_prompt == "결과와 근거를 검토하세요."
    citation = latest.citations[0]
    assert citation.object_type == "external-single-volume-report"
    assert citation.source_path == f"/v1/external-single-volume-reports/{report.report_id}"
    assert citation.captured_from == authority.target.captured_from.isoformat()
    assert latest.source_watermark == f"external-report:{report.report_digest}:REPORTED"
    single._journal.close()
    graph.close()


def test_single_volume_unknown_uncertainty_sentence(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector, single, authority = _projector_with_single(
        tmp_path, graph, target_rmse_m=None
    )
    _record_single_report(single, authority, fill_m3=50.0, base_roughness_m=0.08)
    assert projector.flush()

    latest = briefings.latest("site-a", organization_id="org-a")
    assert latest is not None
    assert "(불확도 미산정, 기저면 거칠기 0.08 m)" in latest.what_changed
    single._journal.close()
    graph.close()


def test_single_results_do_not_feed_relative_delta(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector, single, authority = _projector_with_single(tmp_path, graph)
    _record_single_report(single, authority, fill_m3=10.0, base_roughness_m=0.02)
    assert projector.flush()

    record_measurement(graph)
    assert projector.flush()

    latest = briefings.latest("site-a", organization_id="org-a")
    assert latest is not None
    assert "첫 결과" in latest.why_it_matters
    single._journal.close()
    graph.close()


def _record_later_relative(graph: LoopGraph, *, now: datetime) -> ExternalRelativeVolumeReportV1:
    """A second relative report, reported strictly after the fixture report."""

    port = graph.authority_port
    first = port.authority
    current = first.current.model_copy(
        update={
            "observed_sha256": _digest("dsm-bytes-current-later"),
            "captured_from": _NOW + timedelta(hours=5),
            "captured_to": _NOW + timedelta(hours=6),
        }
    )
    second = replace(
        first,
        current=current,
        historical_authority_digest=_digest("historical-authority-later"),
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
        idempotency_key="later-relative",
        now=_NOW,
    )
    assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED, issued.detail
    assert issued.record is not None and issued.record.request.request_digest is not None
    request = issued.record.request
    assert request.request_digest is not None
    fence = _fence()
    graph.volumes.claim(
        request.request_id, organization_id="org-a", principal_id="worker", fence=fence, now=now
    )
    result = graph.volumes.record_observed_report(
        request.request_id,
        organization_id="org-a",
        principal_id="worker",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            payload=_relative_payload(request.request_digest, second), computed_at=now
        ),
        now=now,
    )
    assert result.record is not None and result.record.report is not None, result.detail
    return result.record.report


def test_single_rows_do_not_push_previous_relative_out_of_delta_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The window holds the current report plus one more row: a merged window
    # would be [B, single] and lose A; a relative-only window is [B, A].
    monkeypatch.setattr(briefings_module, "_HISTORY_WINDOW", 2)
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector, single, authority = _projector_with_single(tmp_path, graph)
    record_measurement(graph)  # relative A, current captured_to = +3h
    assert projector.flush()
    _record_single_report(single, authority, fill_m3=10.0, base_roughness_m=0.02)  # +4h
    assert projector.flush()
    later = _record_later_relative(graph, now=_NOW + timedelta(seconds=1))  # relative B, +6h
    assert projector.flush()

    latest = briefings.latest("site-a", organization_id="org-a")
    assert latest is not None
    assert latest.source_watermark == f"external-report:{later.report_digest}:REPORTED"
    assert "첫 결과" not in latest.why_it_matters
    assert latest.why_it_matters.startswith("직전 결과(4.0 m³)보다 순변화가 ")
    single._journal.close()
    graph.close()


def test_single_volume_review_records_reviewed_briefing(tmp_path: Path) -> None:
    graph, single, port = _new(tmp_path)
    try:
        briefings = SiteBriefingStore(
            DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=graph.service.sites
        )
        graph.journals.append(briefings._journal)  # noqa: SLF001 - close with the graph.
        read = ExternalResultReadProjector(
            volumes=graph.volumes, workflow=graph.service, single_volumes=single, clock=lambda: _NOW
        )
        projector = ExternalResultBriefingProjector(
            briefings=briefings,
            projector=read,
            work_areas=graph.service.work_areas,
            clock=lambda: _NOW,
        )
        projector.bind(
            volumes=graph.volumes,
            reviews=graph.service.reviews,
            service=graph.service,
            single_volumes=single,
        )
        report = _record_reviewable_single(graph, single, port)
        assert projector.flush()
        _review_single(graph, report.report_id)
        assert projector.flush()

        latest = briefings.latest("site-a", organization_id="org-a")
        assert latest is not None and latest.status is SiteBriefingStatus.READY
        assert latest.source_watermark == f"external-report:{report.report_digest}:REVIEWED"
        assert latest.decision_prompt == "재관측이 필요하면 제안을 만들고 승인하세요."
        first = latest.citations[0]
        assert first.object_type == "external-single-volume-report"
        assert first.object_id == report.report_id
        assert first.source_path == f"/v1/external-single-volume-reports/{report.report_id}"
    finally:
        graph.close()

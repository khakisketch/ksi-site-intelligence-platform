"""Core's read-only projector shows single-volume results beside relative ones."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
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
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
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
from ksi_core.external_result_workflow_api import (
    ExternalResultReadProjector,
    build_external_result_workflow_router,
)
from ksi_core.foundation.api_base import iso_utc
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeReportV1
from test_external_relative_volumes import _fence
from test_external_relative_volumes import _payload as _relative_payload
from test_external_result_review_proposals import _NOW, _TOKEN, _principal, _token_record
from test_external_single_volume_result_reviews import _new, _single_lifecycle

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


def _http_client(harness: _Harness) -> TestClient:
    other = PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"other-org-fixture").hexdigest(),
        principal=_principal(organization_id="org-b", principal_id="operator-b"),
    )
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record(), other]))
    app.include_router(
        build_external_result_workflow_router(
            harness.graph.volumes,
            harness.graph.service,
            single_volumes=harness.single,
            clock=lambda: _NOW,
        )
    )
    return TestClient(app)


def test_http_routes_serve_single_reports_and_merged_history(harness: _Harness) -> None:
    relative = record_measurement(harness.graph)
    single = _record_single(harness)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    other = {"Authorization": "Bearer other-org-fixture"}
    with _http_client(harness) as client:
        merged = client.get(f"/v1/sites/{_SITE}/external-volume-reports", headers=headers)
        assert merged.status_code == 200, merged.text
        rows = [(i["reportRef"], i["result"]["kind"]) for i in merged.json()["items"]]
        assert rows == [
            (single.report_id, "EXTERNAL_SINGLE_VOLUME"),
            (relative.report_id, "EXTERNAL_RELATIVE_VOLUME"),
        ]
        paged = client.get(
            f"/v1/sites/{_SITE}/external-volume-reports?limit=1", headers=headers
        ).json()
        assert paged["nextCursor"] == single.report_id
        unknown = client.get(
            f"/v1/sites/{_SITE}/external-volume-reports?after=unknown-report", headers=headers
        )
        assert unknown.status_code == 404
        assert unknown.json()["detail"] == "EXTERNAL_VOLUME_REPORT_NOT_FOUND"

        relative_only = client.get(
            f"/v1/sites/{_SITE}/external-relative-volume-reports", headers=headers
        )
        assert relative_only.status_code == 200, relative_only.text
        assert [i["reportRef"] for i in relative_only.json()["items"]] == [relative.report_id]

        exact = client.get(f"/v1/sites/{_SITE}/observations/{single.report_id}", headers=headers)
        assert exact.status_code == 200, exact.text
        assert exact.json()["result"]["kind"] == "EXTERNAL_SINGLE_VOLUME"

        path = f"/v1/external-single-volume-reports/{single.report_id}"
        assert client.get(path).status_code == 401
        shown = client.get(path, headers=headers)
        assert shown.status_code == 200, shown.text
        body = shown.json()
        assert set(body) == {"request", "report", "executionPolicy", "review", "proposals"}
        assert body["review"] is None and body["proposals"] == []
        assert body["report"] == single.model_dump(by_alias=True, mode="json")
        assert body["request"]["requestId"] == single.request_id
        assert body["request"]["requestDigest"] == single.request_digest
        assert body["executionPolicy"] == harness.port.authority.execution_policy.model_dump(
            by_alias=True, mode="json"
        )
        for denied in (
            client.get(path, headers=other),
            client.get(f"/v1/external-single-volume-reports/{relative.report_id}", headers=headers),
            client.get("/v1/external-single-volume-reports/unknown", headers=headers),
        ):
            assert denied.status_code == 404
            assert denied.json()["detail"] == "EXTERNAL_SINGLE_VOLUME_REPORT_NOT_FOUND"
        foreign_history = client.get(f"/v1/sites/{_SITE}/external-volume-reports", headers=other)
        assert foreign_history.status_code == 404
        assert foreign_history.json()["detail"] == "EXTERNAL_VOLUME_REPORT_NOT_FOUND"


def test_single_report_route_is_absent_without_single_store(harness: _Harness) -> None:
    router = build_external_result_workflow_router(harness.graph.volumes, harness.graph.service)
    paths = {getattr(route, "path", None) for route in router.routes}
    assert "/v1/external-single-volume-reports/{report_ref}" not in paths
    assert "/v1/sites/{site_id}/external-volume-reports" in paths


def test_router_rejects_single_store_on_another_coordinator(
    harness: _Harness, tmp_path: Path
) -> None:
    foreign_path = tmp_path / "foreign-router"
    foreign_path.mkdir()
    foreign = _store(foreign_path, _AuthorityPort(harness.port.authority), now=_NOW)
    try:
        with pytest.raises(ValueError, match="share one coordinator"):
            build_external_result_workflow_router(
                harness.graph.volumes, harness.graph.service, single_volumes=foreign
            )
    finally:
        foreign._journal.close()


def test_single_summary_joins_review_proposals_and_successor(tmp_path: Path) -> None:
    graph, store, port = _new(tmp_path)
    try:
        report, receipt, _, approved = _single_lifecycle(graph, store, port)
        projector = ExternalResultReadProjector(
            volumes=graph.volumes, workflow=graph.service, single_volumes=store, clock=lambda: _NOW
        )
        projection = projector.report_for_site(_SITE, report.report_id, organization_id=_ORG)
        assert projection.state == "AVAILABLE"
        result = projection.result
        assert result is not None and result.kind == "EXTERNAL_SINGLE_VOLUME"
        assert result.review_ref == receipt.review_ref
        assert result.review_digest == receipt.review_digest
        assert result.reviewed_at == receipt.reviewed_at
        assert result.proposal_count == 1
        assert result.approved_proposal_count == 1
        successor = approved.successor_work_order.work_order_id
        through_binding = projector.for_work_order(successor, organization_id=_ORG)
        assert through_binding.state == "AVAILABLE"
        assert through_binding.result is not None
        assert through_binding.result.report_ref == report.report_id
        assert through_binding.result.kind == "EXTERNAL_SINGLE_VOLUME"
        assert through_binding.result.approved_proposal_count == 1
    finally:
        graph.close()


def test_exact_report_routes_hide_broken_retained_provenance(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = record_measurement(harness.graph)
    single = _record_single(harness)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    routes = (
        (
            f"/v1/external-relative-volume-reports/{relative.report_id}",
            "EXTERNAL_RELATIVE_VOLUME_REPORT_NOT_FOUND",
        ),
        (
            f"/v1/external-single-volume-reports/{single.report_id}",
            "EXTERNAL_SINGLE_VOLUME_REPORT_NOT_FOUND",
        ),
    )
    with _http_client(harness) as client:
        for path, _ in routes:
            assert client.get(path, headers=headers).status_code == 200
    for store in (harness.graph.volumes, harness.single):
        original = store.resolve_historical_report_ref

        def tampered(
            report_ref: str,
            *,
            organization_id: str,
            now: datetime | None = None,
            _original: Any = original,
        ) -> Any:
            resolved = _original(report_ref, organization_id=organization_id, now=now)
            if resolved is None:
                return None
            report = resolved.report.model_copy(
                update={"request_digest": _digest("tampered-request")}
            )
            return replace(resolved, report=report)

        monkeypatch.setattr(store, "resolve_historical_report_ref", tampered)
    with _http_client(harness) as client:
        for path, detail in routes:
            response = client.get(path, headers=headers)
            assert response.status_code == 404, response.text
            assert response.json() == {"detail": detail}

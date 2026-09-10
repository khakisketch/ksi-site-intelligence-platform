"""Scoped retained result views and human review intent for external measurements."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_event_contracts.copilot import CopilotCitation
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
)
from ksi_event_contracts.external_result_review import ExternalResultReviewReceiptV1

from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import JournalSealedError
from ksi_core.external_relative_volumes import ExternalRelativeVolumeStore
from ksi_core.external_reobservation_proposals import (
    ExternalReobservationProposalService,
    ExternalReobservationProposalView,
)
from ksi_core.external_result_projection_models import (
    ExternalResultExecutionPolicyView,
    ExternalResultMetricsView,
    ExternalResultProjectionState,
    ExternalResultProjectionView,
    ExternalResultSummaryView,
)
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter


class ExternalResultReviewView(CamelModel):
    review: ExternalResultReviewReceiptV1


class ExternalResultReportView(CamelModel):
    """Recorded provenance, never an assertion of present usage eligibility."""

    request: ExternalRelativeVolumeRequestV1
    report: ExternalRelativeVolumeReportV1
    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    review: ExternalResultReviewReceiptV1 | None = None
    proposals: list[ExternalReobservationProposalView]


class ExternalResultReviewIntent(CamelModel):
    """The path identifies the report; the caller supplies no authority facts."""


class ExternalResultHistoryItem(CamelModel):
    """One retained site history row, including a truthful unavailable state."""

    report_ref: str
    state: Literal["AVAILABLE", "HISTORICAL_SOURCE_UNAVAILABLE"]
    result: ExternalResultSummaryView | None = None


class ExternalResultHistoryView(CamelModel):
    items: list[ExternalResultHistoryItem]
    next_cursor: str | None = None


class ExternalResultReadProjector:
    """Read-only external report projection with exact retained provenance.

    This has no journal and does not ask whether the live authority still
    permits a historical report. New mutations retain their separate live
    guards; a displayed result must independently resolve historical authority.
    """

    def __init__(
        self,
        *,
        volumes: ExternalRelativeVolumeStore,
        workflow: ExternalReobservationProposalService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        source_port = workflow.reviews.source_port
        if (
            volumes.coordinator is not workflow.coordinator
            or not isinstance(source_port, CoreExternalResultReviewSourceAdapter)
            or not source_port.uses_volume_store(volumes)
        ):
            raise ValueError("external result projection requires the exact durable volume graph")
        self._volumes = volumes
        self._workflow = workflow
        self._clock = clock or (lambda: datetime.now(UTC))

    def uses_exact_graph(
        self,
        *,
        volumes: ExternalRelativeVolumeStore,
        workflow: ExternalReobservationProposalService,
    ) -> bool:
        return self._volumes is volumes and self._workflow is workflow

    def for_work_order(
        self, work_order_id: str, *, organization_id: str
    ) -> ExternalResultProjectionView:
        order = self._workflow.work_orders.get(work_order_id, organization_id=organization_id)
        if order is None:
            raise LookupError("관측 작업을 찾을 수 없다")
        binding = self._workflow.work_orders.get_external_reobservation_binding(
            work_order_id, organization_id=organization_id
        )
        if binding is not None:
            proposal = self._workflow.proposals.get_scoped(
                binding.proposal_id, organization_id=organization_id
            )
            if not self._binding_matches_proposal(binding, proposal):
                return ExternalResultProjectionView(
                    state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
                )
            assert proposal is not None
            return self._for_report_ref(proposal.report_ref, organization_id=organization_id)

        candidates = tuple(
            record
            for record in self._volumes.list_for_work_order(
                work_order_id, organization_id=organization_id
            )
            if record.report is not None
        )
        if not candidates:
            return ExternalResultProjectionView(state=ExternalResultProjectionState.NO_RESULT)
        latest = max(
            candidates,
            key=lambda record: (
                record.request.current.captured_to,
                record.report.reported_at if record.report is not None else record.issued_at,
                record.report.report_id if record.report is not None else "",
            ),
        )
        assert latest.report is not None
        return self._for_report_ref(latest.report.report_id, organization_id=organization_id)

    def for_site(self, site_id: str, *, organization_id: str) -> ExternalResultProjectionView:
        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        report_refs = self._volumes.report_refs_for_site(site_id, organization_id=organization_id)
        if not report_refs:
            return ExternalResultProjectionView(state=ExternalResultProjectionState.NO_RESULT)
        # The retained latest is selected before historical resolution. If it is
        # unavailable, never silently select an older report instead.
        return self._for_report_ref(report_refs[0], organization_id=organization_id)

    def history_for_site(
        self,
        site_id: str,
        *,
        organization_id: str,
        after: str | None,
        limit: int,
    ) -> ExternalResultHistoryView:
        """Resolve a bounded retained history without falling back across rows."""

        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        report_refs = self._volumes.report_refs_for_site(site_id, organization_id=organization_id)
        start = 0
        if after is not None:
            try:
                start = report_refs.index(after) + 1
            except ValueError as exc:
                # This covers missing, foreign-organization and other-site cursors
                # alike, without disclosing which one exists.
                raise LookupError("external relative volume report cursor was not found") from exc
        page = report_refs[start : start + limit]
        items: list[ExternalResultHistoryItem] = []
        for report_ref in page:
            projection = self._for_report_ref(report_ref, organization_id=organization_id)
            if projection.state is ExternalResultProjectionState.AVAILABLE:
                if projection.result is None:
                    raise RuntimeError("available external result projection has no result")
                items.append(
                    ExternalResultHistoryItem(
                        report_ref=report_ref,
                        state="AVAILABLE",
                        result=projection.result,
                    )
                )
            else:
                items.append(
                    ExternalResultHistoryItem(
                        report_ref=report_ref,
                        state="HISTORICAL_SOURCE_UNAVAILABLE",
                    )
                )
        next_cursor = page[-1] if start + len(page) < len(report_refs) and page else None
        return ExternalResultHistoryView(items=items, next_cursor=next_cursor)

    def report_for_site(
        self, site_id: str, report_ref: str, *, organization_id: str
    ) -> ExternalResultProjectionView:
        """Return an exact report only after site and retained zone ownership match."""

        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        refs = self._volumes.report_refs_for_site(site_id, organization_id=organization_id)
        if report_ref not in refs:
            raise LookupError("external relative volume report was not found")
        projection = self._for_report_ref(report_ref, organization_id=organization_id)
        if projection.state is ExternalResultProjectionState.AVAILABLE:
            result = projection.result
            if result is None or result.work_area_id == "":
                raise LookupError("external relative volume report was not found")
        return projection

    def citation_for(
        self, projection: ExternalResultProjectionView, *, site_name: str
    ) -> CopilotCitation | None:
        result = projection.result
        if (
            projection.state is not ExternalResultProjectionState.AVAILABLE
            or result is None
            or result.measurement_status != "SUCCEEDED"
            or result.metrics is None
        ):
            return None
        uncertainty = result.metrics.uncertainty_m3
        uncertainty_value = "UNKNOWN" if uncertainty is None else f"{uncertainty:.12g}"
        return CopilotCitation(
            citation_id=(
                "external-relative-volume-report:"
                f"{result.report_ref}:{result.report_digest.removeprefix('sha256:')}"
            ),
            object_type="EXTERNAL_RELATIVE_VOLUME_REPORT",
            object_id=result.report_ref,
            label=f"{site_name} 외부 상대 물량 결과",
            source_path=(
                "/v1/external-relative-volume-reports/"
                f"{quote(result.report_ref, safe='')}"
            ),
            captured_from=iso_utc(result.baseline_captured_from),
            captured_to=iso_utc(result.current_captured_to),
            model_version=(
                f"{result.execution_policy.policy_id}:{result.execution_policy.version}"
            ),
            geometry_ref=result.zone_definition_digest,
            uncertainty_summary=(
                f"{result.execution_policy.uncertainty_method}; uncertaintyM3={uncertainty_value}"
            ),
        )

    def _for_report_ref(
        self, report_ref: str, *, organization_id: str
    ) -> ExternalResultProjectionView:
        resolved = self._volumes.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=self._clock()
        )
        if resolved is None:
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        request, report, authority = (
            resolved.request,
            resolved.report,
            resolved.execution_authority,
        )
        if (
            request.request_digest is None
            or report.report_digest is None
            or authority.zone_snapshot.definition_digest is None
            or authority.execution_policy.policy_digest is None
            or authority.organization_id != organization_id
            or request.current_work_order_id != authority.current_work_order_id
            or report.request_id != request.request_id
            or report.request_digest != request.request_digest
        ):
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        review = self._workflow.reviews.get_for_report(report_ref, organization_id=organization_id)
        if review is not None and (
            review.report != report
            or review.request != request
            or review.report.report_digest != report.report_digest
        ):
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        proposals = tuple(
            proposal
            for proposal in self._workflow.proposals.list_scoped(organization_id=organization_id)
            if proposal.report_ref == report_ref
            and proposal.report_digest == report.report_digest
            and proposal.decision_digest == request.decision_digest
            and proposal.zone_digest == authority.zone_snapshot.definition_digest
        )
        approved = sum(
            self._workflow.approval_receipt(
                organization_id=organization_id,
                proposal_ref=proposal.proposal_ref,
                expected_version=proposal.version,
            )
            is not None
            for proposal in proposals
        )
        metrics = report.payload.metrics
        return ExternalResultProjectionView(
            state=ExternalResultProjectionState.AVAILABLE,
            result=ExternalResultSummaryView(
                report_ref=report.report_id,
                report_digest=report.report_digest,
                request_ref=request.request_id,
                request_digest=request.request_digest,
                source_work_order_id=request.current_work_order_id,
                current_work_order_id=request.current_work_order_id,
                baseline_work_order_id=request.baseline.subject.work_order_id,
                decision_id=request.decision_id,
                decision_digest=request.decision_digest,
                work_area_id=authority.zone_snapshot.work_area_id,
                zone_definition_digest=authority.zone_snapshot.definition_digest,
                crs=authority.zone_snapshot.crs,
                observed_crs_digest=authority.zone_snapshot.observed_crs_digest,
                vertical_reference_digest=authority.zone_snapshot.analysis_vertical_reference_digest,
                baseline_captured_from=request.baseline.captured_from,
                baseline_captured_to=request.baseline.captured_to,
                current_captured_from=request.current.captured_from,
                current_captured_to=request.current.captured_to,
                reported_at=report.reported_at,
                measurement_status="SUCCEEDED",
                measurement_reason=None,
                metrics=ExternalResultMetricsView.model_validate(
                    metrics.model_dump(by_alias=True, mode="json")
                ),
                execution_policy=ExternalResultExecutionPolicyView(
                    policy_id=authority.execution_policy.policy_id,
                    version=authority.execution_policy.version,
                    policy_digest=authority.execution_policy.policy_digest,
                    algorithm_build_digest=authority.execution_policy.algorithm_build_digest,
                    config_digest=authority.execution_policy.config_digest,
                    uncertainty_method=authority.execution_policy.uncertainty_method,
                ),
                review_ref=review.review_ref if review is not None else None,
                review_digest=review.review_digest if review is not None else None,
                reviewed_at=review.reviewed_at if review is not None else None,
                proposal_count=len(proposals),
                approved_proposal_count=approved,
            ),
        )

    @staticmethod
    def _binding_matches_proposal(binding: Any, proposal: Any) -> bool:
        return bool(
            proposal is not None
            and binding.organization_id == proposal.organization_id
            and binding.site_id == proposal.site_id
            and binding.source_work_order_id == proposal.source_work_order_id
            and binding.proposal_id == proposal.proposal_ref
            and binding.proposal_version == proposal.version
            and binding.proposal_digest == proposal.proposal_digest
            and binding.report_digest == proposal.report_digest
            and binding.decision_digest == proposal.decision_digest
            and binding.zone_digest == proposal.zone_digest
            and binding.evidence_digests == proposal.evidence_digests
            and binding.target_work_areas == proposal.target_work_areas
        )


def build_external_result_workflow_router(
    volumes: ExternalRelativeVolumeStore,
    service: ExternalReobservationProposalService,
    *,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    if volumes.coordinator is not service.coordinator:
        raise ValueError("result workflow participants must share one coordinator")
    source = service.reviews.source_port
    if not isinstance(
        source, CoreExternalResultReviewSourceAdapter
    ) or not source.uses_volume_store(volumes):
        raise ValueError("result workflow review source must use the exact volume store")

    now = clock or (lambda: datetime.now(UTC))
    projector = ExternalResultReadProjector(volumes=volumes, workflow=service, clock=now)
    router = APIRouter(tags=["external-result-workflow"])
    read = require_permission(Permission.SITES_READ)
    write = require_permission(Permission.WORK_ORDERS_WRITE)
    read_dependency = Depends(read)
    write_dependency = Depends(write)

    def proposal_view(proposal_ref: str, principal: Principal) -> ExternalReobservationProposalView:
        proposal = service.proposals.get_scoped(
            proposal_ref, organization_id=principal.organization_id
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="EXTERNAL_REOBSERVATION_PROPOSAL_NOT_FOUND")
        return ExternalReobservationProposalView(
            proposal=proposal,
            approval_receipt=service.approval_receipt(
                organization_id=principal.organization_id,
                proposal_ref=proposal_ref,
                expected_version=proposal.version,
            ),
        )

    @router.get(
        "/v1/sites/{site_id}/external-relative-volume-reports",
        response_model=ExternalResultHistoryView,
    )
    def site_report_history(
        site_id: str,
        after: str | None = None,
        limit: int = Query(default=20, ge=1, le=50),
        principal: Principal = read_dependency,
    ) -> ExternalResultHistoryView:
        try:
            return projector.history_for_site(
                site_id,
                organization_id=principal.organization_id,
                after=after,
                limit=limit,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="EXTERNAL_RELATIVE_VOLUME_REPORT_NOT_FOUND"
            ) from exc

    @router.get(
        "/v1/sites/{site_id}/observations/{report_ref}",
        response_model=ExternalResultProjectionView,
    )
    def site_report_view(
        site_id: str,
        report_ref: str,
        principal: Principal = read_dependency,
    ) -> ExternalResultProjectionView:
        try:
            return projector.report_for_site(
                site_id, report_ref, organization_id=principal.organization_id
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="EXTERNAL_RELATIVE_VOLUME_REPORT_NOT_FOUND"
            ) from exc

    @router.get(
        "/v1/external-relative-volume-reports/{report_ref}", response_model=ExternalResultReportView
    )
    def report_view(
        report_ref: str, principal: Principal = read_dependency
    ) -> ExternalResultReportView:
        resolved = volumes.resolve_historical_report_ref(
            report_ref, organization_id=principal.organization_id, now=now()
        )
        if resolved is None:
            raise HTTPException(status_code=404, detail="EXTERNAL_RELATIVE_VOLUME_REPORT_NOT_FOUND")
        proposals = [
            proposal_view(item.proposal_ref, principal)
            for item in service.proposals.list_scoped(organization_id=principal.organization_id)
            if item.report_ref == report_ref and item.report_digest == resolved.report.report_digest
        ]
        review = service.reviews.get_for_report(
            report_ref, organization_id=principal.organization_id
        )
        if review is not None and (
            review.report.report_digest != resolved.report.report_digest
            or review.report != resolved.report
        ):
            raise HTTPException(status_code=503, detail="EXTERNAL_RESULT_REVIEW_INCONSISTENT")
        return ExternalResultReportView(
            request=resolved.request,
            report=resolved.report,
            execution_policy=resolved.execution_authority.execution_policy,
            review=review,
            proposals=proposals,
        )

    @router.post(
        "/v1/external-relative-volume-reports/{report_ref}/reviews",
        response_model=ExternalResultReviewView,
        status_code=201,
    )
    def review_report(
        report_ref: str,
        request: ExternalResultReviewIntent | None = None,
        principal: Principal = write_dependency,
    ) -> ExternalResultReviewView:
        del request
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="HUMAN_REVIEW_REQUIRED")
        try:
            existing = service.reviews.get_for_report(
                report_ref, organization_id=principal.organization_id
            )
            if existing is not None and service.work_orders.is_external_workflow_closed(
                existing.source_work_order_id, organization_id=principal.organization_id
            ):
                return ExternalResultReviewView(review=existing)
            resolved = volumes.resolve_historical_report_ref(
                report_ref,
                organization_id=principal.organization_id,
                now=now(),
            )
            if resolved is None:
                receipt = service.reviews.review(
                    organization_id=principal.organization_id,
                    report_ref=report_ref,
                    principal=principal,
                    evaluated_at=now(),
                )
            else:
                with service.work_orders.guard_new_external_intent(
                    resolved.request.current_work_order_id,
                    organization_id=principal.organization_id,
                ):
                    receipt = service.reviews.review(
                        organization_id=principal.organization_id,
                        report_ref=report_ref,
                        principal=principal,
                        evaluated_at=now(),
                    )
        except JournalSealedError as exc:
            raise HTTPException(
                status_code=503, detail="EXTERNAL_RESULT_REVIEW_STORAGE_UNAVAILABLE"
            ) from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(
                status_code=409, detail="EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="INVALID_EXTERNAL_RESULT_REVIEW_INTENT"
            ) from exc
        return ExternalResultReviewView(review=receipt)

    @router.get("/v1/external-result-reviews/{review_ref}", response_model=ExternalResultReviewView)
    def review_view(
        review_ref: str, principal: Principal = read_dependency
    ) -> ExternalResultReviewView:
        receipt = service.reviews.get_scoped(review_ref, organization_id=principal.organization_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="EXTERNAL_RESULT_REVIEW_NOT_FOUND")
        return ExternalResultReviewView(review=receipt)

    @router.get(
        "/v1/external-reobservation-proposals/{proposal_ref}",
        response_model=ExternalReobservationProposalView,
    )
    def read_proposal(
        proposal_ref: str, principal: Principal = read_dependency
    ) -> ExternalReobservationProposalView:
        return proposal_view(proposal_ref, principal)

    return router

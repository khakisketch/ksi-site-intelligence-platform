"""Scoped retained result views and human review intent for external measurements."""

from collections.abc import Callable
from dataclasses import dataclass
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
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
)
from ksi_event_contracts.external_single_volume_result_review import (
    ExternalResultReviewReceipt,
    ExternalSingleVolumeResultReviewReceiptV1,
)
from pydantic import Field

from ksi_core.domains.external.quantity.external_relative_volumes import ExternalRelativeVolumeStore
from ksi_core.domains.external.quantity.external_single_volumes import ExternalSingleVolumeStore
from ksi_core.domains.external.workflow.external_reobservation_proposals import (
    ExternalReobservationProposalService,
    ExternalReobservationProposalView,
)
from ksi_core.domains.external.workflow.external_result_projection_models import (
    ExternalPendingDecisionItem,
    ExternalPendingDecisionsView,
    ExternalResultExecutionPolicyView,
    ExternalResultKind,
    ExternalResultMetricsView,
    ExternalResultProjectionState,
    ExternalResultProjectionView,
    ExternalResultSummaryView,
)
from ksi_core.domains.external.workflow.external_result_review_sources import (
    CoreExternalResultReviewSourceAdapter,
)
from ksi_core.foundation.api_base import CamelModel, iso_utc
from ksi_core.foundation.durable_journal import JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission


class ExternalResultReviewView(CamelModel):
    """One review receipt of either family, discriminated on ``contractVersion``."""

    review: ExternalResultReviewReceipt


class ExternalResultReportView(CamelModel):
    """Recorded provenance, never an assertion of present usage eligibility."""

    request: ExternalRelativeVolumeRequestV1
    report: ExternalRelativeVolumeReportV1
    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    review: ExternalResultReviewReceiptV1 | None = None
    proposals: list[ExternalReobservationProposalView]


class ExternalSingleVolumeReportView(CamelModel):
    """Recorded single-epoch provenance, never an assertion of present usage eligibility."""

    request: ExternalSingleVolumeRequestV1
    report: ExternalSingleVolumeReportV1
    execution_policy: ExternalSingleVolumeExecutionPolicyV1
    review: ExternalSingleVolumeResultReviewReceiptV1 | None = None
    proposals: list[ExternalReobservationProposalView] = Field(default_factory=list)


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


_SINGLE_REPORT_PREFIX = "external-single-volume-report-"
_RELATIVE_KIND: ExternalResultKind = "EXTERNAL_RELATIVE_VOLUME"
_SINGLE_KIND: ExternalResultKind = "EXTERNAL_SINGLE_VOLUME"


@dataclass(frozen=True, slots=True)
class _ReviewJoin:
    """The retained review and proposal counts joined to one report of either family."""

    review_ref: str | None
    review_digest: str | None
    reviewed_at: datetime | None
    proposal_count: int
    approved_proposal_count: int


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
        single_volumes: ExternalSingleVolumeStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        source_port = workflow.reviews.source_port
        if (
            volumes.coordinator is not workflow.coordinator
            or not isinstance(source_port, CoreExternalResultReviewSourceAdapter)
            or not source_port.uses_volume_store(volumes)
            or (
                single_volumes is not None
                and single_volumes.coordinator is not workflow.coordinator
            )
        ):
            raise ValueError("external result projection requires the exact durable volume graph")
        self._volumes = volumes
        self._single_volumes = single_volumes
        self._workflow = workflow
        self._clock = clock or (lambda: datetime.now(UTC))

    def uses_exact_graph(
        self,
        *,
        volumes: ExternalRelativeVolumeStore,
        workflow: ExternalReobservationProposalService,
        single_volumes: ExternalSingleVolumeStore | None = None,
    ) -> bool:
        return (
            self._volumes is volumes
            and self._workflow is workflow
            and self._single_volumes is single_volumes
        )

    @property
    def single_volumes(self) -> ExternalSingleVolumeStore | None:
        """The exact single-volume store this projection reads, if configured (read-only)."""
        return self._single_volumes

    @property
    def workflow(self) -> ExternalReobservationProposalService:
        """The exact durable workflow graph this projection reads (read-only access)."""
        return self._workflow

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

        candidates: list[tuple[datetime, datetime, str]] = [
            (record.request.current.captured_to, record.report.reported_at, record.report.report_id)
            for record in self._volumes.list_for_work_order(
                work_order_id, organization_id=organization_id
            )
            if record.report is not None
        ]
        if self._single_volumes is not None:
            candidates.extend(
                (
                    record.request.target.captured_to,
                    record.report.reported_at,
                    record.report.report_id,
                )
                for record in self._single_volumes.list_for_work_order(
                    work_order_id, organization_id=organization_id
                )
                if record.report is not None
            )
        if not candidates:
            return ExternalResultProjectionView(state=ExternalResultProjectionState.NO_RESULT)
        latest = max(candidates)
        return self._for_report_ref(latest[2], organization_id=organization_id)

    def for_site(self, site_id: str, *, organization_id: str) -> ExternalResultProjectionView:
        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        report_refs = self._report_index(site_id, organization_id=organization_id)
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
        kinds: frozenset[str] | None = None,
        principal: Principal | None = None,
    ) -> ExternalResultHistoryView:
        """Resolve a bounded retained history without falling back across rows.

        ``kinds`` restricts the merged history to the named result families;
        ``None`` merges every configured family in one newest-first order.
        """

        if principal is not None and (
            principal.organization_id != organization_id
            or principal.allowed_site_ids is not None
            and site_id not in principal.allowed_site_ids
        ):
            raise LookupError("현장을 찾을 수 없다")
        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        report_refs = self._report_index(site_id, organization_id=organization_id, kinds=kinds)
        if principal is not None and (
            principal.allowed_site_ids is not None or principal.allowed_work_area_ids is not None
        ):
            return self._scoped_history(
                site_id, report_refs, principal=principal, after=after, limit=limit
            )
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

    def _scoped_history(
        self, site_id: str, refs: tuple[str, ...], *, principal: Principal,
        after: str | None, limit: int,
    ) -> ExternalResultHistoryView:
        # Validate the exact cursor in the caller's visible sequence, then skip
        # preceding entries without resolving them. Stop after one visible
        # lookahead; a page must not preflight/project the entire site's history.
        start = 0
        if after is not None:
            try:
                start = refs.index(after) + 1
            except ValueError:
                raise LookupError("external relative volume report cursor was not found") from None
            if self._scoped_history_item(site_id, after, principal) is None:
                raise LookupError("external relative volume report cursor was not found")
        items = []
        for ref in refs[start:]:
            item = self._scoped_history_item(site_id, ref, principal)
            if item is not None:
                items.append(item)
                if len(items) > limit:
                    break
        page = items[:limit]
        return ExternalResultHistoryView(
            items=page, next_cursor=page[-1].report_ref if len(items) > limit else None
        )

    def _scoped_history_item(
        self, site_id: str, ref: str, principal: Principal
    ) -> ExternalResultHistoryItem | None:
        # Independent authority/provider resolution must remain OUTSIDE the
        # coordinator. Hold it only for one row's local ownership/projection.
        store: ExternalRelativeVolumeStore | ExternalSingleVolumeStore = self._volumes
        if self._single_volumes is not None and ref.startswith(_SINGLE_REPORT_PREFIX):
            store = self._single_volumes
        resolved = store.resolve_historical_report_ref(
            ref, organization_id=principal.organization_id, now=self._clock()
        )
        if resolved is None:
            return None
        with self._workflow.coordinator.guarded_read():
            if self._workflow.sites.get_scoped(site_id, principal.organization_id) is None:
                raise LookupError("현장을 찾을 수 없다")
            if not self._history_source_in_scope(site_id, resolved, principal):
                return None
            # Render from the EXACT witness that passed scope, never a second
            # provider lookup whose source could differ. Joins are local reads.
            projector = (
                self._project_single_resolved
                if ref.startswith(_SINGLE_REPORT_PREFIX) else self._project_relative_resolved
            )
            view = projector(ref, resolved, organization_id=principal.organization_id)
            if view.state is not ExternalResultProjectionState.AVAILABLE:
                return None
            return ExternalResultHistoryItem(report_ref=ref, state="AVAILABLE", result=view.result)

    def _history_source_in_scope(self, site_id: str, resolved: Any, principal: Principal) -> bool:
        request, report, authority = resolved.request, resolved.report, resolved.execution_authority
        zone = authority.zone_snapshot
        if (
            not self._provenance_intact(request, report, authority, principal.organization_id)
            or authority.site_id != site_id or zone.site_id != site_id
            or zone.organization_id != principal.organization_id
            or principal.allowed_work_area_ids is not None
            and zone.work_area_id not in principal.allowed_work_area_ids
        ):
            return False
        subjects = [
            request.current.subject if hasattr(request, "current") else request.target.subject
        ]
        if hasattr(request, "baseline"):
            subjects.append(request.baseline.subject)
        for subject in subjects:
            order = self._workflow.work_orders.get(
                subject.work_order_id, organization_id=principal.organization_id
            )
            if (
                subject.organization_id != principal.organization_id or subject.site_id != site_id
                or order is None or order.site_id != site_id or not order.work_area_ids
                or zone.work_area_id not in order.work_area_ids
                or principal.allowed_work_area_ids is not None
                and not set(order.work_area_ids).issubset(principal.allowed_work_area_ids)
            ):
                return False
        return True

    def report_for_site(
        self, site_id: str, report_ref: str, *, organization_id: str
    ) -> ExternalResultProjectionView:
        """Return an exact report only after site and retained zone ownership match."""

        if self._workflow.sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        refs = self._report_index(site_id, organization_id=organization_id)
        if report_ref not in refs:
            raise LookupError("external relative volume report was not found")
        projection = self._for_report_ref(report_ref, organization_id=organization_id)
        if projection.state is ExternalResultProjectionState.AVAILABLE:
            result = projection.result
            if result is None or result.work_area_id == "":
                raise LookupError("external relative volume report was not found")
        return projection

    def pending_decisions(self, *, organization_id: str) -> ExternalPendingDecisionsView:
        """External results that wait for a person, one per site (AX-4, ADR-KSI-025 D1).

        Pending is read from retained ledgers only: a succeeded measurement
        without a review waits for review; a proposal without an approval
        receipt waits for approval. A row whose historical source cannot be
        resolved is skipped rather than guessed.
        """

        chosen: list[tuple[int, datetime, str, ExternalPendingDecisionItem]] = []
        for site in self._workflow.sites.list_scoped(organization_id):
            best: tuple[int, datetime, str, ExternalPendingDecisionItem] | None = None
            for report_ref in self._report_index(site.site_id, organization_id=organization_id):
                projection = self._for_report_ref(report_ref, organization_id=organization_id)
                result = projection.result
                if (
                    projection.state is not ExternalResultProjectionState.AVAILABLE
                    or result is None
                    or result.metrics is None
                ):
                    continue
                stage: Literal["AWAITING_REVIEW", "AWAITING_APPROVAL"]
                if result.measurement_status == "SUCCEEDED" and result.review_ref is None:
                    rank, stage = 0, "AWAITING_REVIEW"
                elif result.proposal_count > result.approved_proposal_count:
                    rank, stage = 1, "AWAITING_APPROVAL"
                else:
                    continue
                if best is not None and (rank, result.reported_at, report_ref) >= best[:3]:
                    continue
                best = (
                    rank,
                    result.reported_at,
                    report_ref,
                    ExternalPendingDecisionItem(
                        site_id=site.site_id,
                        report_ref=report_ref,
                        kind=result.kind,
                        stage=stage,
                        reported_at=result.reported_at,
                        net_m3=result.metrics.net_m3,
                        uncertainty_m3=result.metrics.uncertainty_m3,
                        work_area_id=result.work_area_id,
                    ),
                )
            if best is not None:
                chosen.append(best)
        chosen.sort(key=lambda entry: entry[:3])
        return ExternalPendingDecisionsView(items=[entry[3] for entry in chosen])

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
        if result.kind == _SINGLE_KIND:
            return CopilotCitation(
                citation_id=(
                    "external-single-volume-report:"
                    f"{result.report_ref}:{result.report_digest.removeprefix('sha256:')}"
                ),
                object_type="EXTERNAL_SINGLE_VOLUME_REPORT",
                object_id=result.report_ref,
                label=f"{site_name} 외부 단일 시점 체적 결과",
                source_path=(
                    f"/v1/external-single-volume-reports/{quote(result.report_ref, safe='')}"
                ),
                captured_from=iso_utc(result.current_captured_from),
                captured_to=iso_utc(result.current_captured_to),
                model_version=(
                    f"{result.execution_policy.policy_id}:{result.execution_policy.version}"
                ),
                geometry_ref=result.zone_definition_digest,
                uncertainty_summary=(
                    f"{result.execution_policy.uncertainty_method}; "
                    f"uncertaintyM3={uncertainty_value}"
                ),
            )
        if result.baseline_captured_from is None:
            return None
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

    def _report_index(
        self,
        site_id: str,
        *,
        organization_id: str,
        kinds: frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        """Merge retained family indexes into one deterministic newest-first order."""

        include_relative = kinds is None or _RELATIVE_KIND in kinds
        single_volumes = self._single_volumes
        if single_volumes is None or (kinds is not None and _SINGLE_KIND not in kinds):
            # Relative-only reads keep the exact pre-existing retained index path.
            if not include_relative:
                return ()
            return self._volumes.report_refs_for_site(site_id, organization_id=organization_id)
        entries = list(
            single_volumes.report_index_for_site(site_id, organization_id=organization_id)
        )
        if include_relative:
            entries.extend(
                self._volumes.report_index_for_site(site_id, organization_id=organization_id)
            )
        return tuple(entry[2] for entry in sorted(entries, reverse=True))

    def _for_report_ref(
        self, report_ref: str, *, organization_id: str
    ) -> ExternalResultProjectionView:
        if self._single_volumes is not None and report_ref.startswith(_SINGLE_REPORT_PREFIX):
            return self._for_single_report_ref(
                self._single_volumes, report_ref, organization_id=organization_id
            )
        resolved = self._volumes.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=self._clock()
        )
        if resolved is None:
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        return self._project_relative_resolved(
            report_ref, resolved, organization_id=organization_id
        )

    def _project_relative_resolved(
        self, report_ref: str, resolved: Any, *, organization_id: str
    ) -> ExternalResultProjectionView:
        request, report, authority = (
            resolved.request,
            resolved.report,
            resolved.execution_authority,
        )
        # The shared gate decides; the trailing ``is None`` terms only narrow types.
        if (
            not self._provenance_intact(request, report, authority, organization_id)
            or request.request_digest is None
            or report.report_digest is None
            or authority.zone_snapshot.definition_digest is None
            or authority.execution_policy.policy_digest is None
        ):
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        join = self._review_join(report_ref, request, report, authority, organization_id)
        if join is None:
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
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
                execution_policy=self._policy_view(authority.execution_policy),
                review_ref=join.review_ref,
                review_digest=join.review_digest,
                reviewed_at=join.reviewed_at,
                proposal_count=join.proposal_count,
                approved_proposal_count=join.approved_proposal_count,
            ),
        )

    def _for_single_report_ref(
        self,
        single_volumes: ExternalSingleVolumeStore,
        report_ref: str,
        *,
        organization_id: str,
    ) -> ExternalResultProjectionView:
        """Project one single-epoch report with the same review/proposal join."""

        resolved = single_volumes.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=self._clock()
        )
        if resolved is None:
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        return self._project_single_resolved(report_ref, resolved, organization_id=organization_id)

    def _project_single_resolved(
        self, report_ref: str, resolved: Any, *, organization_id: str
    ) -> ExternalResultProjectionView:
        request, report, authority = (
            resolved.request,
            resolved.report,
            resolved.execution_authority,
        )
        # The shared gate decides; the trailing ``is None`` terms only narrow types.
        if (
            not self._provenance_intact(request, report, authority, organization_id)
            or request.request_digest is None
            or report.report_digest is None
            or authority.zone_snapshot.definition_digest is None
            or authority.execution_policy.policy_digest is None
        ):
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        join = self._review_join(report_ref, request, report, authority, organization_id)
        if join is None:
            return ExternalResultProjectionView(
                state=ExternalResultProjectionState.HISTORICAL_SOURCE_UNAVAILABLE
            )
        return ExternalResultProjectionView(
            state=ExternalResultProjectionState.AVAILABLE,
            result=ExternalResultSummaryView(
                kind=_SINGLE_KIND,
                report_ref=report.report_id,
                report_digest=report.report_digest,
                request_ref=request.request_id,
                request_digest=request.request_digest,
                source_work_order_id=request.current_work_order_id,
                current_work_order_id=request.current_work_order_id,
                baseline_work_order_id=None,
                decision_id=request.decision_id,
                decision_digest=request.decision_digest,
                work_area_id=authority.zone_snapshot.work_area_id,
                zone_definition_digest=authority.zone_snapshot.definition_digest,
                crs=authority.zone_snapshot.crs,
                observed_crs_digest=authority.zone_snapshot.observed_crs_digest,
                vertical_reference_digest=authority.zone_snapshot.analysis_vertical_reference_digest,
                baseline_captured_from=None,
                baseline_captured_to=None,
                current_captured_from=request.target.captured_from,
                current_captured_to=request.target.captured_to,
                reported_at=report.reported_at,
                measurement_status="SUCCEEDED",
                measurement_reason=None,
                metrics=ExternalResultMetricsView.model_validate(
                    report.payload.metrics.model_dump(by_alias=True, mode="json")
                ),
                execution_policy=self._policy_view(authority.execution_policy),
                review_ref=join.review_ref,
                review_digest=join.review_digest,
                reviewed_at=join.reviewed_at,
                proposal_count=join.proposal_count,
                approved_proposal_count=join.approved_proposal_count,
            ),
        )

    def _review_join(
        self,
        report_ref: str,
        request: Any,
        report: Any,
        authority: Any,
        organization_id: str,
    ) -> _ReviewJoin | None:
        """Join the retained review and proposals of one report of either family.

        ``None`` means a retained review no longer matches the resolved report,
        which the caller shows as an unavailable historical source.
        """

        review = self._workflow.reviews.get_for_report(report_ref, organization_id=organization_id)
        if review is not None and (
            review.report != report
            or review.request != request
            or review.report.report_digest != report.report_digest
        ):
            return None
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
        return _ReviewJoin(
            review_ref=review.review_ref if review is not None else None,
            review_digest=review.review_digest if review is not None else None,
            reviewed_at=review.reviewed_at if review is not None else None,
            proposal_count=len(proposals),
            approved_proposal_count=approved,
        )

    @staticmethod
    def _provenance_intact(request: Any, report: Any, authority: Any, organization_id: str) -> bool:
        """The historical provenance gate shared by every external volume family."""
        return bool(
            request.request_digest is not None
            and report.report_digest is not None
            and authority.zone_snapshot.definition_digest is not None
            and authority.execution_policy.policy_digest is not None
            and authority.organization_id == organization_id
            and request.current_work_order_id == authority.current_work_order_id
            and report.request_id == request.request_id
            and report.request_digest == request.request_digest
        )

    @staticmethod
    def _policy_view(policy: Any) -> ExternalResultExecutionPolicyView:
        return ExternalResultExecutionPolicyView(
            policy_id=policy.policy_id,
            version=policy.version,
            policy_digest=policy.policy_digest,
            algorithm_build_digest=policy.algorithm_build_digest,
            config_digest=policy.config_digest,
            uncertainty_method=policy.uncertainty_method,
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
    single_volumes: ExternalSingleVolumeStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    if volumes.coordinator is not service.coordinator or (
        single_volumes is not None and single_volumes.coordinator is not service.coordinator
    ):
        raise ValueError("result workflow participants must share one coordinator")
    source = service.reviews.source_port
    if not isinstance(
        source, CoreExternalResultReviewSourceAdapter
    ) or not source.uses_volume_store(volumes):
        raise ValueError("result workflow review source must use the exact volume store")

    now = clock or (lambda: datetime.now(UTC))
    projector = ExternalResultReadProjector(
        volumes=volumes, workflow=service, single_volumes=single_volumes, clock=now
    )
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

    @router.get("/v1/external-decisions/pending", response_model=ExternalPendingDecisionsView)
    def pending_external_decisions(
        principal: Principal = read_dependency,
    ) -> ExternalPendingDecisionsView:
        """External results waiting for a person, one per site (AX-4, ADR-KSI-025 D1)."""
        return projector.pending_decisions(organization_id=principal.organization_id)

    @router.get(
        "/v1/sites/{site_id}/external-volume-reports",
        response_model=ExternalResultHistoryView,
    )
    def site_volume_report_history(
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
                principal=principal,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="EXTERNAL_VOLUME_REPORT_NOT_FOUND") from exc

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
                kinds=frozenset({_RELATIVE_KIND}),
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

    def report_join(
        report_ref: str, resolved: Any, principal: Principal, review_type: type[Any]
    ) -> tuple[Any, list[ExternalReobservationProposalView]]:
        """The exact report's retained review and proposals, shared by both families."""

        if not projector._provenance_intact(  # noqa: SLF001 - the shared provenance gate
            resolved.request,
            resolved.report,
            resolved.execution_authority,
            principal.organization_id,
        ):
            raise LookupError(report_ref)
        proposals = [
            proposal_view(item.proposal_ref, principal)
            for item in service.proposals.list_scoped(organization_id=principal.organization_id)
            if item.report_ref == report_ref and item.report_digest == resolved.report.report_digest
        ]
        review = service.reviews.get_for_report(
            report_ref, organization_id=principal.organization_id
        )
        if review is not None and (
            not isinstance(review, review_type)
            or review.report.report_digest != resolved.report.report_digest
            or review.report != resolved.report
        ):
            raise HTTPException(status_code=503, detail="EXTERNAL_RESULT_REVIEW_INCONSISTENT")
        return review, proposals

    @router.get(
        "/v1/external-relative-volume-reports/{report_ref}", response_model=ExternalResultReportView
    )
    def report_view(
        report_ref: str, principal: Principal = read_dependency
    ) -> ExternalResultReportView:
        resolved = volumes.resolve_historical_report_ref(
            report_ref, organization_id=principal.organization_id, now=now()
        )
        try:
            if resolved is None:
                raise LookupError(report_ref)
            review, proposals = report_join(
                report_ref, resolved, principal, ExternalResultReviewReceiptV1
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="EXTERNAL_RELATIVE_VOLUME_REPORT_NOT_FOUND"
            ) from exc
        return ExternalResultReportView(
            request=resolved.request,
            report=resolved.report,
            execution_policy=resolved.execution_authority.execution_policy,
            review=review,
            proposals=proposals,
        )

    def _review_report(
        report_ref: str,
        principal: Principal,
        resolver: Callable[..., Any],
        *,
        owns_ref: Callable[[str], bool],
        review_type: type[Any],
    ) -> ExternalResultReviewView:
        """Record one human review through the family route that owns ``report_ref``."""

        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="HUMAN_REVIEW_REQUIRED")
        if not owns_ref(report_ref):
            # A ref of the other family never reaches the review store through
            # this route; the relative route answered this way before SV-3b.
            raise HTTPException(status_code=409, detail="EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")
        try:
            existing = service.reviews.get_for_report(
                report_ref, organization_id=principal.organization_id
            )
            if isinstance(
                existing, review_type
            ) and service.work_orders.is_external_workflow_closed(
                existing.source_work_order_id, organization_id=principal.organization_id
            ):
                return ExternalResultReviewView(review=existing)
            resolved = resolver(
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
        if not isinstance(receipt, review_type):
            # Unreachable: ``owns_ref`` keeps each family on its own route.
            raise HTTPException(status_code=409, detail="EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")
        return ExternalResultReviewView(review=receipt)

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
        return _review_report(
            report_ref,
            principal,
            volumes.resolve_historical_report_ref,
            owns_ref=lambda ref: not ref.startswith(_SINGLE_REPORT_PREFIX),
            review_type=ExternalResultReviewReceiptV1,
        )

    if single_volumes is not None:
        single_store = single_volumes

        @router.get(
            "/v1/external-single-volume-reports/{report_ref}",
            response_model=ExternalSingleVolumeReportView,
        )
        def single_report_view(
            report_ref: str, principal: Principal = read_dependency
        ) -> ExternalSingleVolumeReportView:
            resolved = single_store.resolve_historical_report_ref(
                report_ref, organization_id=principal.organization_id, now=now()
            )
            try:
                if resolved is None:
                    raise LookupError(report_ref)
                review, proposals = report_join(
                    report_ref, resolved, principal, ExternalSingleVolumeResultReviewReceiptV1
                )
            except LookupError as exc:
                raise HTTPException(
                    status_code=404, detail="EXTERNAL_SINGLE_VOLUME_REPORT_NOT_FOUND"
                ) from exc
            return ExternalSingleVolumeReportView(
                request=resolved.request,
                report=resolved.report,
                execution_policy=resolved.execution_authority.execution_policy,
                review=review,
                proposals=proposals,
            )

        @router.post(
            "/v1/external-single-volume-reports/{report_ref}/reviews",
            response_model=ExternalResultReviewView,
            status_code=201,
        )
        def review_single_report(
            report_ref: str,
            request: ExternalResultReviewIntent | None = None,
            principal: Principal = write_dependency,
        ) -> ExternalResultReviewView:
            del request
            return _review_report(
                report_ref,
                principal,
                single_store.resolve_historical_report_ref,
                owns_ref=lambda ref: ref.startswith(_SINGLE_REPORT_PREFIX),
                review_type=ExternalSingleVolumeResultReviewReceiptV1,
            )

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

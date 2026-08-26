"""Organization-scoped Site workspace and durable grounded briefing projection."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from ksi_domain.enums import EventStatus, TriageStatus
from ksi_event_contracts.copilot import (
    CopilotAnswerStatus,
    CopilotCitation,
    SiteBriefing,
    SiteBriefingStatus,
)
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
)
from ksi_event_contracts.processing_job import ProcessingJobStatus
from pydantic import Field, ValidationError

from ksi_core.api_base import CamelModel
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.copilot import CopilotQueryRequest, CopilotService, ToolResult
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.events import EventStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from ksi_core.processing_jobs import ProcessingJobRecord, ProcessingJobStore
    from ksi_core.sites import SiteRecord, SiteStore

_FINAL_TRIAGE_STATES = frozenset({TriageStatus.RESOLVED, TriageStatus.CLOSED})
_EVENT_PAGE_SIZE = 500
_LOGGER = logging.getLogger(__name__)
_ACTIVE_WORK_STATES = frozenset(
    {
        ObservationWorkOrderStatus.APPROVED,
        ObservationWorkOrderStatus.DISPATCHED,
        ObservationWorkOrderStatus.START_REPORTED,
        ObservationWorkOrderStatus.MEDIA_RECEIVING,
        ObservationWorkOrderStatus.PROCESSING,
    }
)


class WorkspaceNextAction(CamelModel):
    kind: str
    label: str
    href: str | None
    reason: str


class WorkspaceWorkOrderSummary(CamelModel):
    work_order_id: str
    name: str
    status: str
    updated_at: str
    mission_count: int


class WorkspaceAnalysisSummary(CamelModel):
    status: str
    processing_job_id: str | None
    captured_from: str | None
    captured_to: str | None
    available_result_kinds: list[str]
    source_watermark: str | None


class SiteWorkspaceView(CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    site_id: str
    site_name: str
    site_status: str
    latest_observation_at: str | None
    review_item_count: int = Field(ge=0)
    active_work_order_count: int = Field(ge=0)
    latest_work_order: WorkspaceWorkOrderSummary | None
    latest_analysis: WorkspaceAnalysisSummary
    next_action: WorkspaceNextAction


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp는 tz-aware여야 한다")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_optional(value: datetime | None) -> str | None:
    return None if value is None else _iso(value)


class SiteWorkspaceProjector:
    """Projects existing ledgers; it never invents a processing or device fact."""

    def __init__(
        self,
        *,
        site_store: SiteStore,
        work_order_store: ObservationWorkOrderStore,
        processing_job_store: ProcessingJobStore | None,
        event_store: EventStore | None,
    ) -> None:
        self._sites = site_store
        self._work_orders = work_order_store
        self._processing_jobs = processing_job_store
        self._events = event_store

    def project(self, site_id: str, *, organization_id: str) -> SiteWorkspaceView:
        site = self._sites.get_scoped(site_id, organization_id)
        if site is None:
            raise LookupError("현장을 찾을 수 없다")
        orders = self._work_orders.list_for_site(site_id, organization_id=organization_id)
        latest_order = max(
            orders,
            key=lambda item: (item.updated_at, item.work_order_id),
            default=None,
        )
        jobs = (
            self._processing_jobs.list_for_site(
                site_id, organization_id=organization_id
            )
            if self._processing_jobs
            else []
        )
        latest_job = jobs[0] if jobs else None
        latest_observation = next(
            (
                job.capture_window.captured_to
                for job in jobs
                if job.capture_window.captured_to is not None
            ),
            None,
        )
        review_count = 0
        if self._events is not None:
            offset = 0
            while True:
                page = self._events.list(
                    organization_id=organization_id,
                    site_id=site_id,
                    limit=_EVENT_PAGE_SIZE,
                    offset=offset,
                )
                review_count += sum(
                    1
                    for event in page
                    if event.status is not EventStatus.DISMISSED
                    and event.triage not in _FINAL_TRIAGE_STATES
                )
                if len(page) < _EVENT_PAGE_SIZE:
                    break
                offset += len(page)
        active_count = sum(1 for item in orders if item.status in _ACTIVE_WORK_STATES)
        return SiteWorkspaceView(
            site_id=site.site_id,
            site_name=site.name,
            site_status=site.status.value,
            latest_observation_at=_iso_optional(latest_observation),
            review_item_count=review_count,
            active_work_order_count=active_count,
            latest_work_order=self._work_order_summary(latest_order),
            latest_analysis=self._analysis_summary(latest_job),
            next_action=self._next_action(site, orders, review_count),
        )

    @staticmethod
    def _work_order_summary(
        order: ObservationWorkOrder | None,
    ) -> WorkspaceWorkOrderSummary | None:
        if order is None:
            return None
        return WorkspaceWorkOrderSummary(
            work_order_id=order.work_order_id,
            name=order.name,
            status=order.status.value,
            updated_at=order.updated_at,
            mission_count=len(order.mission_ids),
        )

    @staticmethod
    def _analysis_summary(job: ProcessingJobRecord | None) -> WorkspaceAnalysisSummary:
        if job is None:
            return WorkspaceAnalysisSummary(
                status="UNAVAILABLE",
                processing_job_id=None,
                captured_from=None,
                captured_to=None,
                available_result_kinds=[],
                source_watermark=None,
            )
        available = (
            sorted({item.kind.value for item in job.artifacts})
            if job.status is ProcessingJobStatus.SUCCEEDED
            else []
        )
        return WorkspaceAnalysisSummary(
            status=job.status.value,
            processing_job_id=job.job_id,
            captured_from=_iso_optional(job.capture_window.captured_from),
            captured_to=_iso_optional(job.capture_window.captured_to),
            available_result_kinds=available,
            source_watermark=job.input.source_bundle_digest,
        )

    @staticmethod
    def _next_action(
        site: SiteRecord,
        orders: list[ObservationWorkOrder],
        review_count: int,
    ) -> WorkspaceNextAction:
        encoded_site = quote(site.site_id, safe="")
        if review_count:
            return WorkspaceNextAction(
                kind="REVIEW_ITEMS",
                label=f"확인 항목 {review_count}건 검토",
                href=f"/sites/{encoded_site}?section=review-items",
                reason="사람의 판단을 기다리는 관측이 있습니다.",
            )
        priority = (
            (ObservationWorkOrderStatus.BLOCKED, "BLOCKED_WORK", "막힌 작업 확인"),
            (ObservationWorkOrderStatus.AWAITING_APPROVAL, "DECISION_REQUIRED", "작업 승인 검토"),
            (
                ObservationWorkOrderStatus.REOBSERVATION_PENDING,
                "DECISION_REQUIRED",
                "재관측 제안 검토",
            ),
            (ObservationWorkOrderStatus.REVIEW_READY, "REVIEW_RESULTS", "결과와 근거 검토"),
        )
        for status, kind, label in priority:
            candidate = next((item for item in reversed(orders) if item.status is status), None)
            if candidate is not None:
                return WorkspaceNextAction(
                    kind=kind,
                    label=label,
                    href=f"/field/work-orders/{quote(candidate.work_order_id, safe='')}",
                    reason=f"{candidate.name} 작업이 사용자의 판단을 기다립니다.",
                )
        active = next(
            (item for item in reversed(orders) if item.status in _ACTIVE_WORK_STATES),
            None,
        )
        if active is not None:
            return WorkspaceNextAction(
                kind="ACTIVE_WORK",
                label="진행 상태 보기",
                href=f"/field/work-orders/{quote(active.work_order_id, safe='')}",
                reason=f"{active.name} 작업이 진행 중입니다.",
            )
        if site.aoi is None:
            return WorkspaceNextAction(
                kind="SET_AOI",
                label="현장 범위 설정",
                href=f"/sites/{encoded_site}?section=work#site-aoi",
                reason="조사 계획 전에 지도에서 조사할 공사 구역을 정해야 합니다.",
            )
        if not orders:
            return WorkspaceNextAction(
                kind="PLAN_BASELINE",
                label="베이스라인 조사 계획하기",
                href=f"/sites/{encoded_site}?section=work",
                reason="AOI가 준비되어 첫 현장 관측을 계획할 수 있습니다.",
            )
        return WorkspaceNextAction(
            kind="NONE",
            label="현재 결정 필요 없음",
            href=None,
            reason="검토 대기나 진행 중인 작업이 없습니다.",
        )


def build_workspace_copilot_handlers(
    projector: SiteWorkspaceProjector,
    work_order_store: ObservationWorkOrderStore,
) -> dict[str, Any]:
    """Build the exact read-only handler allowlist consumed by ``CoreCopilotToolBackend``."""

    def site_snapshot(
        organization_id: str,
        site_id: str,
        _work_order_id: str | None,
        _arguments: dict[str, Any],
    ) -> ToolResult:
        workspace = projector.project(site_id, organization_id=organization_id)
        citation = CopilotCitation(
            citation_id=f"site-workspace:{site_id}",
            object_type="SITE_WORKSPACE",
            object_id=site_id,
            label=f"{workspace.site_name} 현장 최신 상태",
            source_path=f"/v1/sites/{quote(site_id, safe='')}/workspace",
            captured_to=workspace.latest_observation_at,
            uncertainty_summary=(
                "최신 검증 결과 없음"
                if workspace.latest_analysis.status == "UNAVAILABLE"
                else None
            ),
        )
        return ToolResult(
            data=workspace.model_dump(by_alias=True, mode="json"),
            citations=(citation,),
        )

    def latest_progress(
        organization_id: str,
        site_id: str,
        _work_order_id: str | None,
        _arguments: dict[str, Any],
    ) -> ToolResult:
        workspace = projector.project(site_id, organization_id=organization_id)
        analysis = workspace.latest_analysis
        citations: tuple[CopilotCitation, ...] = ()
        if analysis.processing_job_id is not None:
            citations = (
                CopilotCitation(
                    citation_id=f"processing-job:{analysis.processing_job_id}",
                    object_type="PROCESSING_JOB",
                    object_id=analysis.processing_job_id,
                    label=f"{workspace.site_name} 최신 처리 결과",
                    source_path=(
                        f"/v1/processing-jobs/{quote(analysis.processing_job_id, safe='')}"
                    ),
                    captured_from=analysis.captured_from,
                    captured_to=analysis.captured_to,
                    uncertainty_summary=(
                        "처리가 완료되지 않아 결과 수치를 사용할 수 없음"
                        if analysis.status != ProcessingJobStatus.SUCCEEDED.value
                        else None
                    ),
                ),
            )
        return ToolResult(
            data=analysis.model_dump(by_alias=True, mode="json"),
            citations=citations,
        )

    def evidence_index(
        organization_id: str,
        site_id: str,
        _work_order_id: str | None,
        arguments: dict[str, Any],
    ) -> ToolResult:
        workspace = projector.project(site_id, organization_id=organization_id)
        orders = work_order_store.list_for_site(site_id, organization_id=organization_id)
        allowed: dict[str, CopilotCitation] = {
            site_id: CopilotCitation(
                citation_id=f"site-workspace:{site_id}",
                object_type="SITE_WORKSPACE",
                object_id=site_id,
                label=f"{workspace.site_name} 현장 최신 상태",
                source_path=f"/v1/sites/{quote(site_id, safe='')}/workspace",
                captured_to=workspace.latest_observation_at,
            )
        }
        for order in orders:
            allowed[order.work_order_id] = CopilotCitation(
                citation_id=f"work-order:{order.work_order_id}",
                object_type="OBSERVATION_WORK_ORDER",
                object_id=order.work_order_id,
                label=order.name,
                source_path=(
                    f"/v1/observation-work-orders/{quote(order.work_order_id, safe='')}"
                ),
            )
        job_id = workspace.latest_analysis.processing_job_id
        if job_id is not None:
            allowed[job_id] = CopilotCitation(
                citation_id=f"processing-job:{job_id}",
                object_type="PROCESSING_JOB",
                object_id=job_id,
                label=f"{workspace.site_name} 최신 처리 결과",
                source_path=f"/v1/processing-jobs/{quote(job_id, safe='')}",
                captured_from=workspace.latest_analysis.captured_from,
                captured_to=workspace.latest_analysis.captured_to,
            )
        requested = arguments.get("objectIds", [])
        selected = tuple(allowed[item] for item in requested if item in allowed)
        return ToolResult(
            data={
                "evidence": [
                    item.model_dump(by_alias=True, mode="json") for item in selected
                ],
                "missingObjectIds": [item for item in requested if item not in allowed],
            },
            citations=selected,
        )

    return {
        "site_snapshot": site_snapshot,
        "latest_progress": latest_progress,
        "evidence_index": evidence_index,
    }


class SiteBriefingStore:
    def __init__(self, journal: DurableJournal, *, site_store: SiteStore) -> None:
        self._journal = journal
        self._sites = site_store
        self._lock = threading.Lock()
        self._briefings: dict[str, SiteBriefing] = {}
        self._latest: dict[tuple[str, str], str] = {}
        self._sequence = 0
        try:
            for raw in journal.replay():
                if raw.get("kind") != "site-briefing-recorded":
                    raise ValueError(f"알 수 없는 briefing journal kind: {raw.get('kind')!r}")
                briefing = SiteBriefing.model_validate(raw["briefing"])
                if self._sites.get_scoped(
                    briefing.site_id, briefing.organization_id
                ) is None:
                    raise ValueError("존재하지 않는 조직-scoped Site briefing")
                if briefing.briefing_id in self._briefings:
                    raise ValueError("중복 briefingId")
                self._briefings[briefing.briefing_id] = briefing
                self._latest[(briefing.organization_id, briefing.site_id)] = briefing.briefing_id
                self._sequence = max(
                    self._sequence, int(briefing.briefing_id.rsplit("-", 1)[-1])
                )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            journal.close()
            raise RuntimeError(f"site briefing journal 재생 실패: {exc}") from exc

    def latest(self, site_id: str, *, organization_id: str) -> SiteBriefing | None:
        if self._sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        with self._lock:
            briefing_id = self._latest.get((organization_id, site_id))
            return self._briefings.get(briefing_id) if briefing_id is not None else None

    def record(
        self,
        *,
        organization_id: str,
        site_id: str,
        status: SiteBriefingStatus,
        what_changed: str,
        why_it_matters: str,
        decision_prompt: str,
        citations: list[Any],
        uncertainty: str,
        source_watermark: str,
        missing_data: list[str],
        actor: str,
        now: datetime,
    ) -> SiteBriefing:
        if self._sites.get_scoped(site_id, organization_id) is None:
            raise LookupError("현장을 찾을 수 없다")
        with self._lock:
            briefing_id = f"site-briefing-{self._sequence + 1:08d}"
            briefing = SiteBriefing(
                briefing_id=briefing_id,
                organization_id=organization_id,
                site_id=site_id,
                status=status,
                what_changed=what_changed,
                why_it_matters=why_it_matters,
                decision_prompt=decision_prompt,
                citations=citations,
                uncertainty=uncertainty,
                source_watermark=source_watermark,
                missing_data=missing_data,
                generated_at=_iso(now),
            )
            self._journal.append(
                {
                    "kind": "site-briefing-recorded",
                    "ts": briefing.generated_at,
                    "actor": actor,
                    "briefing": briefing.model_dump(by_alias=True, mode="json"),
                }
            )
            self._briefings[briefing_id] = briefing
            self._latest[(organization_id, site_id)] = briefing_id
            self._sequence += 1
            return briefing


class SiteBriefingService:
    def __init__(
        self,
        *,
        store: SiteBriefingStore,
        copilot: CopilotService,
        workspace: SiteWorkspaceProjector,
    ) -> None:
        self._store = store
        self._copilot = copilot
        self._workspace = workspace

    @property
    def store(self) -> SiteBriefingStore:
        return self._store

    def refresh(self, site_id: str, *, principal: Principal) -> SiteBriefing:
        workspace = self._workspace.project(
            site_id, organization_id=principal.organization_id
        )
        source_watermark = "sha256:" + hashlib.sha256(
            json.dumps(
                workspace.model_dump(by_alias=True, mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        latest = self._store.latest(site_id, organization_id=principal.organization_id)
        if (
            latest is not None
            and latest.status is SiteBriefingStatus.READY
            and latest.source_watermark == source_watermark
        ):
            return latest
        try:
            answer = self._copilot.query(
                CopilotQueryRequest(
                    site_id=site_id,
                    question=(
                        "최신 검증 결과로 현장 브리핑을 작성하세요. answer에는 "
                        "whatChanged, whyItMatters, decisionPrompt, uncertainty 네 문자열만 "
                        "가진 JSON object를 넣으세요. 근거가 부족하면 추측하지 마세요."
                    ),
                ),
                principal=principal,
            )
        except Exception:  # provider/network/parser errors must become a durable blocked fact
            _LOGGER.exception(
                "site briefing provider failed",
                extra={
                    "site_id": site_id,
                    "organization_id": principal.organization_id,
                },
            )
            answer = None
        parsed: dict[str, str] | None = None
        if answer is not None and answer.status is CopilotAnswerStatus.ANSWERED:
            try:
                candidate = json.loads(answer.answer)
                required = {"whatChanged", "whyItMatters", "decisionPrompt", "uncertainty"}
                if isinstance(candidate, dict) and set(candidate) == required and all(
                    isinstance(candidate[key], str) and candidate[key].strip()
                    for key in required
                ):
                    parsed = candidate
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
        if parsed is None:
            status = SiteBriefingStatus.BLOCKED
            parsed = {
                "whatChanged": "검증된 변화 근거가 아직 충분하지 않습니다.",
                "whyItMatters": "근거가 부족한 상태에서 중요도를 추정하지 않습니다.",
                "decisionPrompt": "최신 관측과 처리 상태를 확인해 주세요.",
                "uncertainty": "브리핑 생성에 필요한 검증 결과가 부족합니다.",
            }
            missing = (
                answer.missing_data or ["BRIEFING_SHAPE_INVALID"]
                if answer is not None
                else ["PROVIDER_UNAVAILABLE"]
            )
            citations: list[Any] = []
        else:
            assert answer is not None
            status = SiteBriefingStatus.READY
            missing = []
            citations = list(answer.citations)
        return self._store.record(
            organization_id=principal.organization_id,
            site_id=site_id,
            status=status,
            what_changed=parsed["whatChanged"],
            why_it_matters=parsed["whyItMatters"],
            decision_prompt=parsed["decisionPrompt"],
            citations=citations,
            uncertainty=parsed["uncertainty"],
            source_watermark=source_watermark,
            missing_data=missing,
            actor=f"copilot:{principal.principal_id}",
            now=datetime.now(UTC),
        )


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalSealedError):
        return HTTPException(status_code=503, detail="현장 브리핑 원장을 사용할 수 없다")
    return HTTPException(status_code=422, detail=str(exc))


def build_site_workspace_router(
    projector: SiteWorkspaceProjector,
    briefing_service: SiteBriefingService | None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["site-workspace"])

    @router.get("/{site_id}/workspace", response_model=SiteWorkspaceView)
    def get_workspace(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> SiteWorkspaceView:
        try:
            return projector.project(site_id, organization_id=principal.organization_id)
        except Exception as exc:
            raise _error(exc) from exc

    if briefing_service is not None:

        @router.get("/{site_id}/briefings/latest", response_model=SiteBriefing)
        def get_latest_briefing(
            site_id: str,
            principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
        ) -> SiteBriefing:
            try:
                briefing = briefing_service.store.latest(
                    site_id, organization_id=principal.organization_id
                )
            except Exception as exc:
                raise _error(exc) from exc
            if briefing is None:
                raise HTTPException(status_code=404, detail="생성된 현장 브리핑이 없다")
            return briefing

        @router.post("/{site_id}/briefings/refresh", response_model=SiteBriefing)
        def refresh_briefing(
            site_id: str,
            principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
        ) -> SiteBriefing:
            try:
                return briefing_service.refresh(site_id, principal=principal)
            except Exception as exc:
                raise _error(exc) from exc

    return router


def mount_site_workspace(
    app: FastAPI,
    *,
    projector: SiteWorkspaceProjector,
    briefing_service: SiteBriefingService | None,
) -> None:
    app.state.site_workspace_projector = projector
    app.include_router(build_site_workspace_router(projector, briefing_service))


__all__ = [
    "SiteBriefingService",
    "SiteBriefingStore",
    "SiteWorkspaceProjector",
    "SiteWorkspaceView",
    "build_workspace_copilot_handlers",
    "mount_site_workspace",
]

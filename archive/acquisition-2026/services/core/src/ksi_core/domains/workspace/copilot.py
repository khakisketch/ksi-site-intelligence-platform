"""Provider-neutral grounded Copilot와 typed-tool allowlist (REQ-COP-101/102)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from ksi_event_contracts.copilot import CopilotAnswer, CopilotAnswerStatus, CopilotCitation
from pydantic import Field, ValidationError

from ksi_core.foundation.api_base import CamelModel
from ksi_core.identity.auth import Permission, Principal, principal_permissions, require_permission

if TYPE_CHECKING:
    from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
    from ksi_core.domains.sites.sites import SiteStore

_MAX_TOOL_ROUNDS = 4
_MAX_TOOL_CALLS = 8
_MAX_TOOL_RESULT_BYTES = 64 * 1024


class CopilotError(RuntimeError):
    pass


class ToolRejectedError(CopilotError):
    pass


class CopilotQueryRequest(CamelModel):
    site_id: str = Field(min_length=1)
    work_order_id: str | None = None
    question: str = Field(min_length=1, max_length=4000)


class SiteSnapshotArgs(CamelModel):
    pass


class LatestProgressArgs(CamelModel):
    work_area_ids: list[str] = Field(default_factory=list, max_length=64)


class EvidenceIndexArgs(CamelModel):
    object_ids: list[str] = Field(min_length=1, max_length=32)


class DraftReobservationArgs(CamelModel):
    reason_citation_ids: list[str] = Field(min_length=1, max_length=32)
    target_region_refs: list[str] = Field(min_length=1, max_length=64)
    proposed_effort: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelTurn:
    answer: str | None = None
    citation_ids: tuple[str, ...] = ()
    tool_calls: tuple[ModelToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResult:
    data: dict[str, Any]
    citations: tuple[CopilotCitation, ...]
    reobservation_draft_id: str | None = None


class CopilotModelAdapter(Protocol):
    @property
    def external(self) -> bool: ...

    def complete(
        self,
        *,
        messages: tuple[dict[str, Any], ...],
        tools: tuple[dict[str, Any], ...],
    ) -> ModelTurn: ...


class CopilotToolBackend(Protocol):
    def site_exists(self, organization_id: str, site_id: str) -> bool: ...

    def ai_egress_allowed(self, organization_id: str, site_id: str) -> bool: ...

    def query(
        self,
        *,
        tool_name: str,
        organization_id: str,
        site_id: str,
        work_order_id: str | None,
        arguments: dict[str, Any],
    ) -> ToolResult: ...

    def create_reobservation_draft(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_order_id: str,
        reason_refs: list[str],
        target_region_refs: list[str],
        proposed_effort: str,
        planner_version: str,
        expires_at: datetime,
        actor: str,
    ) -> ToolResult: ...


class CoreCopilotToolBackend:
    """Core 저장소와 결정적 Intelligence 조회기를 typed tools에 연결한다.

    ``query_handlers``는 raw SQL이나 object key를 받지 않고 이미 조직/현장 범위가
    고정된 인자만 받는다. AI 반출 허용은 별도 서버 정책 callback이 명시돼야 한다.
    """

    def __init__(
        self,
        *,
        site_store: SiteStore,
        observation_work_order_store: ObservationWorkOrderStore,
        query_handlers: dict[
            str, Callable[[str, str, str | None, dict[str, Any]], ToolResult]
        ],
        ai_egress_policy: Callable[[str, str], bool],
        capture_policy_for_work_order: Callable[[str, str], str | None],
    ) -> None:
        unexpected = set(query_handlers) - {
            "site_snapshot",
            "latest_progress",
            "evidence_index",
        }
        if unexpected:
            raise ValueError(f"허용되지 않은 query handler: {sorted(unexpected)}")
        self._site_store = site_store
        self._work_orders = observation_work_order_store
        self._query_handlers = dict(query_handlers)
        self._ai_egress_policy = ai_egress_policy
        self._capture_policy_for_work_order = capture_policy_for_work_order

    def site_exists(self, organization_id: str, site_id: str) -> bool:
        return self._site_store.get_scoped(site_id, organization_id) is not None

    def ai_egress_allowed(self, organization_id: str, site_id: str) -> bool:
        return self.site_exists(organization_id, site_id) and self._ai_egress_policy(
            organization_id, site_id
        )

    def query(
        self,
        *,
        tool_name: str,
        organization_id: str,
        site_id: str,
        work_order_id: str | None,
        arguments: dict[str, Any],
    ) -> ToolResult:
        if not self.site_exists(organization_id, site_id):
            raise LookupError("현장을 찾을 수 없다")
        handler = self._query_handlers.get(tool_name)
        if handler is None:
            raise ToolRejectedError(f"구성되지 않은 tool: {tool_name}")
        return handler(organization_id, site_id, work_order_id, arguments)

    def create_reobservation_draft(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_order_id: str,
        reason_refs: list[str],
        target_region_refs: list[str],
        proposed_effort: str,
        planner_version: str,
        expires_at: datetime,
        actor: str,
    ) -> ToolResult:
        work_order = self._work_orders.get(work_order_id, organization_id=organization_id)
        if work_order is None or work_order.site_id != site_id:
            raise LookupError("관측 작업을 찾을 수 없다")
        policy_version = self._capture_policy_for_work_order(
            organization_id, work_order_id
        )
        if policy_version is None:
            raise ToolRejectedError("승인된 Capture Policy가 없어 재관측 초안을 만들 수 없다")
        draft = self._work_orders.create_reobservation_draft(
            work_order_id,
            organization_id=organization_id,
            reason_refs=reason_refs,
            target_region_refs=target_region_refs,
            proposed_effort=proposed_effort,
            planner_version=planner_version,
            policy_version=policy_version,
            expires_at=expires_at,
            actor=actor,
            now=datetime.now(UTC),
        )
        return ToolResult(
            data={
                "status": "PENDING_HUMAN_APPROVAL",
                "draftId": draft.draft_id,
                "expiresAt": draft.expires_at,
            },
            citations=(),
            reobservation_draft_id=draft.draft_id,
        )

_TOOL_MODELS: dict[str, type[CamelModel]] = {
    "site_snapshot": SiteSnapshotArgs,
    "latest_progress": LatestProgressArgs,
    "evidence_index": EvidenceIndexArgs,
    "draft_reobservation": DraftReobservationArgs,
}

_TOOL_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        "name": name,
        "description": {
            "site_snapshot": "현재 현장과 공간모델의 검증된 요약을 조회한다",
            "latest_progress": "시점 간 공정·상대 물량과 불확실성을 조회한다",
            "evidence_index": "이미 조회된 객체의 근거 사진·지도 링크를 조회한다",
            "draft_reobservation": "근거가 연결된 재관측 초안만 만든다. 승인하지 않는다",
        }[name],
        "inputSchema": model.model_json_schema(by_alias=True),
    }
    for name, model in _TOOL_MODELS.items()
)


class CopilotService:
    def __init__(
        self,
        *,
        model: CopilotModelAdapter,
        backend: CopilotToolBackend,
        planner_version: str,
        draft_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        if not planner_version.strip():
            raise ValueError("planner_version은 비어 있을 수 없다")
        if draft_ttl <= timedelta(0) or draft_ttl > timedelta(days=7):
            raise ValueError("draft_ttl은 0초 초과 7일 이하여야 한다")
        self._model = model
        self._backend = backend
        self._planner_version = planner_version
        self._draft_ttl = draft_ttl

    def query(self, request: CopilotQueryRequest, *, principal: Principal) -> CopilotAnswer:
        organization_id = principal.organization_id
        if not self._backend.site_exists(organization_id, request.site_id):
            raise LookupError("현장을 찾을 수 없다")
        if self._model.external and not self._backend.ai_egress_allowed(
            organization_id, request.site_id
        ):
            return CopilotAnswer(
                status=CopilotAnswerStatus.BLOCKED,
                answer=(
                    "이 현장은 외부 AI 데이터 반출이 허용되지 않아 Copilot을 실행할 수 없습니다."
                ),
                missing_data=["AI_EGRESS_NOT_ALLOWED"],
            )

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "KSI의 검증된 도구 결과만 사용한다. 수치를 직접 계산하지 않고, "
                    "비행 좌표·안전 명령·승인을 만들지 않는다. 근거가 부족하면 BLOCKED로 답한다."
                    " 최종 답변은 answer 문자열과 citationIds 문자열 배열만 가진 JSON object로 "
                    "반환한다. citationIds에는 이번 대화에서 도구가 반환한 ID만 사용한다."
                ),
            },
            {"role": "user", "content": request.question},
        ]
        citations: dict[str, CopilotCitation] = {}
        seen_call_ids: set[str] = set()
        call_count = 0
        draft_id: str | None = None

        for _round in range(_MAX_TOOL_ROUNDS):
            turn = self._model.complete(messages=tuple(messages), tools=_TOOL_SPECS)
            if turn.tool_calls:
                # OpenAI-compatible providers require the assistant tool-call frame
                # immediately before the matching tool messages. Keeping this in the
                # provider-neutral transcript also makes replay/debugging deterministic.
                messages.append(
                    {
                        "role": "assistant",
                        "toolCalls": [
                            {
                                "id": call.call_id,
                                "name": call.name,
                                "arguments": call.arguments,
                            }
                            for call in turn.tool_calls
                        ],
                    }
                )
                for call in turn.tool_calls:
                    call_count += 1
                    if call_count > _MAX_TOOL_CALLS:
                        return _blocked("TOOL_CALL_LIMIT", draft_id=draft_id)
                    if not call.call_id or call.call_id in seen_call_ids:
                        return _blocked("INVALID_TOOL_CALL_ID", draft_id=draft_id)
                    seen_call_ids.add(call.call_id)
                    try:
                        result = self._execute_tool(
                            call,
                            request=request,
                            principal=principal,
                            known_citations=citations,
                        )
                    except (LookupError, ToolRejectedError, ValidationError, ValueError) as exc:
                        messages.append(
                            {
                                "role": "tool",
                                "toolCallId": call.call_id,
                                "name": call.name,
                                "content": {"status": "BLOCKED", "reason": str(exc)},
                            }
                        )
                        continue
                    for citation in result.citations:
                        citations[citation.citation_id] = citation
                    draft_id = result.reobservation_draft_id or draft_id
                    messages.append(
                        {
                            "role": "tool",
                            "toolCallId": call.call_id,
                            "name": call.name,
                            "content": result.data,
                            "citationIds": [item.citation_id for item in result.citations],
                        }
                    )
                continue

            if not turn.answer:
                return _blocked("MODEL_RETURNED_NO_ANSWER", draft_id=draft_id)
            selected: list[CopilotCitation] = []
            for citation_id in turn.citation_ids:
                selected_citation = citations.get(citation_id)
                if selected_citation is None:
                    return _blocked("MODEL_CITED_UNKNOWN_SOURCE", draft_id=draft_id)
                if selected_citation not in selected:
                    selected.append(selected_citation)
            if not selected:
                return _blocked("GROUNDING_UNAVAILABLE", draft_id=draft_id)
            return CopilotAnswer(
                status=CopilotAnswerStatus.ANSWERED,
                answer=turn.answer,
                citations=selected,
                reobservation_draft_id=draft_id,
            )
        return _blocked("TOOL_ROUND_LIMIT", draft_id=draft_id)

    def _execute_tool(
        self,
        call: ModelToolCall,
        *,
        request: CopilotQueryRequest,
        principal: Principal,
        known_citations: dict[str, CopilotCitation],
    ) -> ToolResult:
        model = _TOOL_MODELS.get(call.name)
        if model is None:
            raise ToolRejectedError(f"허용되지 않은 tool: {call.name}")
        arguments = model.model_validate(call.arguments)
        if call.name == "draft_reobservation":
            if Permission.WORK_ORDERS_WRITE not in principal_permissions(principal):
                raise ToolRejectedError("재관측 초안 작성 권한이 필요하다")
            if request.work_order_id is None:
                raise ToolRejectedError("재관측 초안에는 workOrderId가 필요하다")
            assert isinstance(arguments, DraftReobservationArgs)
            unknown = set(arguments.reason_citation_ids) - set(known_citations)
            if unknown:
                raise ToolRejectedError("조회되지 않은 citation을 재관측 근거로 사용할 수 없다")
            reason_refs = [
                f"{known_citations[item].object_type}:{known_citations[item].object_id}"
                for item in arguments.reason_citation_ids
            ]
            result = self._backend.create_reobservation_draft(
                organization_id=principal.organization_id,
                site_id=request.site_id,
                work_order_id=request.work_order_id,
                reason_refs=reason_refs,
                target_region_refs=arguments.target_region_refs,
                proposed_effort=arguments.proposed_effort,
                planner_version=self._planner_version,
                expires_at=datetime.now(UTC) + self._draft_ttl,
                actor=f"copilot:{principal.principal_id}",
            )
        else:
            result = self._backend.query(
                tool_name=call.name,
                organization_id=principal.organization_id,
                site_id=request.site_id,
                work_order_id=request.work_order_id,
                arguments=arguments.model_dump(by_alias=True, mode="json"),
            )
        if len(json.dumps(result.data, ensure_ascii=False, allow_nan=False).encode()) > (
            _MAX_TOOL_RESULT_BYTES
        ):
            raise ToolRejectedError("tool 결과 크기 상한을 초과했다")
        return result


def _blocked(reason: str, *, draft_id: str | None = None) -> CopilotAnswer:
    return CopilotAnswer(
        status=CopilotAnswerStatus.BLOCKED,
        answer="검증된 근거만으로 답을 만들 수 없습니다.",
        missing_data=[reason],
        reobservation_draft_id=draft_id,
    )


def build_copilot_router(service: CopilotService) -> APIRouter:
    router = APIRouter(tags=["copilot"])

    @router.post("/v1/copilot/query", response_model=CopilotAnswer)
    def query(
        request: CopilotQueryRequest,
        principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
    ) -> CopilotAnswer:
        try:
            return service.query(request, principal=principal)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def mount_copilot(app: Any, service: CopilotService) -> None:
    app.state.copilot_service = service
    app.include_router(build_copilot_router(service))


__all__ = [
    "CopilotModelAdapter",
    "CopilotService",
    "CopilotToolBackend",
    "CoreCopilotToolBackend",
    "ModelToolCall",
    "ModelTurn",
    "ToolResult",
    "mount_copilot",
]

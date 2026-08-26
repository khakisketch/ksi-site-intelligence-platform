"""근거형 KSI Copilot 응답 계약(REQ-COP-101/102, INV-061)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel


class CopilotAnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    BLOCKED = "BLOCKED"


class CopilotConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CopilotMessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class CopilotCitation(_CamelModel):
    citation_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)
    source_path: str = Field(min_length=1)
    captured_from: str | None = None
    captured_to: str | None = None
    model_version: str | None = None
    geometry_ref: str | None = None
    uncertainty_summary: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _source_is_scoped_api_path(self) -> CopilotCitation:
        if not self.source_path.startswith("/v1/") or "?" in self.source_path:
            raise ValueError("sourcePath는 query가 없는 /v1/ API 경로여야 한다")
        return self


class CopilotAnswer(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    status: CopilotAnswerStatus
    answer: str = Field(min_length=1, max_length=10000)
    citations: list[CopilotCitation] = Field(default_factory=list, max_length=64)
    missing_data: list[str] = Field(default_factory=list, max_length=32)
    reobservation_draft_id: str | None = None

    @model_validator(mode="after")
    def _answered_requires_grounding(self) -> CopilotAnswer:
        if self.status is CopilotAnswerStatus.ANSWERED and not self.citations:
            raise ValueError("ANSWERED 응답은 최소 한 개의 citation이 필요하다")
        if len({item.citation_id for item in self.citations}) != len(self.citations):
            raise ValueError("citationId가 중복됐다")
        return self


class CopilotConversation(_CamelModel):
    """한 조직의 한 현장에 고정된 저장형 대화 계약(INV-060/061)."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    conversation_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    work_order_id: str | None = None
    status: CopilotConversationStatus
    created_by: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class CopilotMessage(_CamelModel):
    """질문 또는 citation 검증이 끝난 최종 답변.

    provider 원문 응답이나 검증 전 스트리밍 토큰은 이 계약에 들어오지 않는다.
    """

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    message_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    role: CopilotMessageRole
    content: str = Field(min_length=1, max_length=10000)
    client_message_id: str | None = Field(min_length=1, max_length=200)
    answer_status: CopilotAnswerStatus | None
    citations: list[CopilotCitation] = Field(max_length=64)
    missing_data: list[str] = Field(max_length=32)
    reobservation_draft_id: str | None
    provider: str | None = Field(max_length=200)
    model: str | None = Field(max_length=300)
    planner_version: str | None = Field(max_length=200)
    created_by: str = Field(min_length=1)
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _role_shape_is_consistent(self) -> CopilotMessage:
        if self.role is CopilotMessageRole.USER:
            if self.client_message_id is None:
                raise ValueError("USER message에는 clientMessageId가 필요하다")
            if self.answer_status is not None or self.citations or self.missing_data:
                raise ValueError("USER message는 assistant 결과 필드를 가질 수 없다")
            if any((self.provider, self.model, self.planner_version)):
                raise ValueError("USER message는 provider metadata를 가질 수 없다")
        else:
            if self.client_message_id is not None:
                raise ValueError("ASSISTANT message는 clientMessageId를 가질 수 없다")
            if self.answer_status is None:
                raise ValueError("ASSISTANT message에는 answerStatus가 필요하다")
            if self.answer_status is CopilotAnswerStatus.ANSWERED and not self.citations:
                raise ValueError("ANSWERED assistant message는 citation이 필요하다")
            if not all((self.provider, self.model, self.planner_version)):
                raise ValueError("ASSISTANT message에는 provider/model/plannerVersion이 필요하다")
        return self


class SiteBriefingStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class SiteBriefing(_CamelModel):
    """검증된 현장 결과에서 만들어진 근거형 브리핑 계약."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    briefing_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    status: SiteBriefingStatus
    what_changed: str = Field(min_length=1, max_length=5000)
    why_it_matters: str = Field(min_length=1, max_length=5000)
    decision_prompt: str = Field(min_length=1, max_length=2000)
    citations: list[CopilotCitation] = Field(max_length=64)
    uncertainty: str = Field(min_length=1, max_length=1000)
    source_watermark: str = Field(min_length=1, max_length=500)
    missing_data: list[str] = Field(max_length=32)
    generated_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ready_requires_citations(self) -> SiteBriefing:
        if self.status is SiteBriefingStatus.READY and not self.citations:
            raise ValueError("READY briefing은 최소 한 개의 citation이 필요하다")
        return self


__all__ = [
    "CopilotAnswer",
    "CopilotAnswerStatus",
    "CopilotCitation",
    "CopilotConversation",
    "CopilotConversationStatus",
    "CopilotMessage",
    "CopilotMessageRole",
    "SiteBriefing",
    "SiteBriefingStatus",
]

"""근거형 KSI Copilot 응답 계약(REQ-COP-101/102, INV-061)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel


class CopilotAnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    BLOCKED = "BLOCKED"


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


__all__ = ["CopilotAnswer", "CopilotAnswerStatus", "CopilotCitation"]

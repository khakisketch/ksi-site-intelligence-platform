"""Grounded Copilot allowlist, egress, tenant, human-approval boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.copilot import (
    CopilotQueryRequest,
    CopilotService,
    ModelToolCall,
    ModelTurn,
    ToolResult,
)
from ksi_event_contracts.copilot import CopilotCitation

_ROOT = Path(__file__).parents[2]
_TOKEN_A = "copilot-org-a-token"  # noqa: S105
_TOKEN_B = "copilot-org-b-token"  # noqa: S105


class ScriptedModel:
    def __init__(self, turns: list[ModelTurn], *, external: bool = True) -> None:
        self.external = external
        self.turns = turns
        self.calls: list[tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]] = []

    def complete(
        self,
        *,
        messages: tuple[dict[str, Any], ...],
        tools: tuple[dict[str, Any], ...],
    ) -> ModelTurn:
        self.calls.append((messages, tools))
        return self.turns.pop(0)


class RecordingBackend:
    def __init__(self, *, egress_allowed: bool = True) -> None:
        self.egress_allowed = egress_allowed
        self.query_calls: list[dict[str, Any]] = []
        self.draft_calls: list[dict[str, Any]] = []

    def site_exists(self, organization_id: str, site_id: str) -> bool:
        return organization_id == "org-a" and site_id == "site-a"

    def ai_egress_allowed(self, organization_id: str, site_id: str) -> bool:
        return self.egress_allowed and self.site_exists(organization_id, site_id)

    def query(self, **kwargs: Any) -> ToolResult:
        self.query_calls.append(kwargs)
        return ToolResult(
            data={
                "status": "COMPLETE",
                "capturedTo": "2026-08-20T01:00:00+00:00",
                "netVolumeChangeM3": 123.4,
                "uncertaintyM3": 4.2,
            },
            citations=(
                CopilotCitation(
                    citation_id="citation-volume-1",
                    object_type="VOLUME_REPORT",
                    object_id="volume-report-1",
                    label="A구역 8월 20일 상대 물량",
                    source_path="/v1/volume-changes/volume-report-1",
                    captured_from="2026-08-13T01:00:00+00:00",
                    captured_to="2026-08-20T01:00:00+00:00",
                    model_version="odm-3.5",
                    geometry_ref="wa-site-a-0001",
                    uncertainty_summary="±4.2 m³",
                ),
            ),
        )

    def create_reobservation_draft(self, **kwargs: Any) -> ToolResult:
        self.draft_calls.append(kwargs)
        return ToolResult(
            data={"status": "PENDING_HUMAN_APPROVAL", "draftId": "draft-1"},
            citations=(),
            reobservation_draft_id="draft-1",
        )


def _principal(
    organization_id: str = "org-a", *, principal_id: str = "field-operator"
) -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id=organization_id,
    )


def _service(model: ScriptedModel, backend: RecordingBackend) -> CopilotService:
    return CopilotService(model=model, backend=backend, planner_version="copilot-planner-1")


def test_external_model_is_not_called_without_explicit_site_egress() -> None:
    model = ScriptedModel([ModelTurn(answer="호출되면 안 됨")], external=True)
    backend = RecordingBackend(egress_allowed=False)
    answer = _service(model, backend).query(
        _request(question="이번 주 물량은?"), principal=_principal()
    )
    assert answer.status == "BLOCKED"
    assert answer.missing_data == ["AI_EGRESS_NOT_ALLOWED"]
    assert model.calls == []
    assert backend.query_calls == []


def test_answer_must_cite_a_typed_tool_result_and_schema_matches() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=(ModelToolCall("call-1", "latest_progress", {"workAreaIds": []}),)
            ),
            ModelTurn(
                answer="A구역 순변화량은 123.4 m³입니다.", citation_ids=("citation-volume-1",)
            ),
        ]
    )
    backend = RecordingBackend()
    answer = _service(model, backend).query(
        _request(question="이번 주 물량은?"), principal=_principal()
    )
    assert answer.status == "ANSWERED"
    assert [item.object_id for item in answer.citations] == ["volume-report-1"]
    assert backend.query_calls[0]["organization_id"] == "org-a"
    tool_names = {item["name"] for item in model.calls[0][1]}
    assert tool_names == {
        "site_snapshot",
        "latest_progress",
        "evidence_index",
        "draft_reobservation",
    }
    schema = json.loads(
        (_ROOT / "contracts/schemas/copilot-answer.v1.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(answer.model_dump(by_alias=True, mode="json"))


def test_unknown_or_invented_citation_fails_closed() -> None:
    model = ScriptedModel(
        [
            ModelTurn(tool_calls=(ModelToolCall("call-1", "raw_sql", {"sql": "select *"}),)),
            ModelTurn(answer="근거 없는 답", citation_ids=("invented",)),
        ]
    )
    answer = _service(model, RecordingBackend()).query(
        _request(question="전부 보여줘"), principal=_principal()
    )
    assert answer.status == "BLOCKED"
    assert answer.missing_data == ["MODEL_CITED_UNKNOWN_SOURCE"]


def test_reobservation_tool_creates_only_a_grounded_draft() -> None:
    model = ScriptedModel(
        [
            ModelTurn(tool_calls=(ModelToolCall("read-1", "site_snapshot", {}),)),
            ModelTurn(
                tool_calls=(
                    ModelToolCall(
                        "draft-1",
                        "draft_reobservation",
                        {
                            "reasonCitationIds": ["citation-volume-1"],
                            "targetRegionRefs": ["wa-site-a-0001"],
                            "proposedEffort": "동측 구역 추가 촬영",
                        },
                    ),
                )
            ),
            ModelTurn(
                answer="재관측 초안을 만들었습니다. 승인이 필요합니다.",
                citation_ids=("citation-volume-1",),
            ),
        ]
    )
    backend = RecordingBackend()
    answer = _service(model, backend).query(
        _request(question="부족한 곳 다시 찍게 준비해줘", work_order_id="work-1"),
        principal=_principal(),
    )
    assert answer.status == "ANSWERED"
    assert answer.reobservation_draft_id == "draft-1"
    assert len(backend.draft_calls) == 1
    draft = backend.draft_calls[0]
    assert draft["reason_refs"] == ["VOLUME_REPORT:volume-report-1"]
    assert draft["actor"] == "copilot:field-operator"
    assert isinstance(draft["expires_at"], datetime)
    assert "approve" not in draft
    assert "mission" not in draft


def test_viewer_copilot_cannot_create_a_reobservation_draft() -> None:
    model = ScriptedModel(
        [
            ModelTurn(tool_calls=(ModelToolCall("read-1", "site_snapshot", {}),)),
            ModelTurn(
                tool_calls=(
                    ModelToolCall(
                        "draft-1",
                        "draft_reobservation",
                        {
                            "reasonCitationIds": ["citation-volume-1"],
                            "targetRegionRefs": ["wa-site-a-0001"],
                            "proposedEffort": "동측 구역 추가 촬영",
                        },
                    ),
                )
            ),
            ModelTurn(
                answer="재관측 초안을 만들 권한이 없습니다.",
                citation_ids=("citation-volume-1",),
            ),
        ]
    )
    backend = RecordingBackend()
    viewer = Principal(
        principal_id="viewer-a",
        kind=PrincipalKind.OPERATOR,
        role=Role.VIEWER,
        device_id=None,
        organization_id="org-a",
    )

    answer = _service(model, backend).query(
        _request(question="부족한 곳 다시 찍게 준비해줘", work_order_id="work-1"),
        principal=viewer,
    )

    assert answer.status == "ANSWERED"
    assert answer.reobservation_draft_id is None
    assert backend.draft_calls == []
    tool_messages = [
        item for messages, _tools in model.calls for item in messages if item["role"] == "tool"
    ]
    assert any(
        item["name"] == "draft_reobservation"
        and item["content"] == {
            "status": "BLOCKED",
            "reason": "재관측 초안 작성 권한이 필요하다",
        }
        for item in tool_messages
    )


def test_api_hides_cross_organization_site_before_model_call() -> None:
    model = ScriptedModel([ModelTurn(answer="호출 금지")])
    backend = RecordingBackend()
    service = _service(model, backend)
    records = []
    for token, organization_id in ((_TOKEN_A, "org-a"), (_TOKEN_B, "org-b")):
        records.append(
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=_principal(organization_id, principal_id=f"operator-{organization_id}"),
            )
        )
    client = TestClient(create_app(auth_registry=AuthRegistry(records), copilot_service=service))
    response = client.post(
        "/v1/copilot/query",
        headers={"Authorization": f"Bearer {_TOKEN_B}"},
        json={"siteId": "site-a", "question": "물량은?"},
    )
    assert response.status_code == 404
    assert model.calls == []


def _request(*, question: str, work_order_id: str | None = None) -> CopilotQueryRequest:
    return CopilotQueryRequest(site_id="site-a", work_order_id=work_order_id, question=question)

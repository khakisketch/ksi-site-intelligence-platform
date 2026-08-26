"""Durable Site Copilot conversations, workspace projection, and provider adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.copilot import CopilotService, ModelToolCall, ModelTurn, ToolResult
from ksi_core.copilot_conversations import (
    CopilotConversationService,
    CopilotConversationStore,
)
from ksi_core.copilot_openai import CopilotProviderError, OpenAiCompatibleModelAdapter
from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.site_workspace import SiteBriefingService, SiteBriefingStore, SiteWorkspaceProjector
from ksi_core.sites import SiteStore
from ksi_domain.enums import EventStatus, TriageStatus
from ksi_event_contracts.copilot import CopilotCitation
from ksi_mission_contracts.models import SiteFrame

_TOKEN_A = "conversation-a-token"  # noqa: S105
_TOKEN_B = "conversation-b-token"  # noqa: S105


class _Model:
    external = False

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def complete(self, **_kwargs: Any) -> ModelTurn:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider exploded")
        if self.calls % 2:
            return ModelTurn(tool_calls=(ModelToolCall("call-1", "site_snapshot", {}),))
        return ModelTurn(answer="현장 변화가 확인되었습니다.", citation_ids=("site-1",))


class _BriefingModel:
    external = False

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_kwargs: Any) -> ModelTurn:
        self.calls += 1
        if self.calls % 2:
            return ModelTurn(tool_calls=(ModelToolCall("call-1", "site_snapshot", {}),))
        return ModelTurn(
            answer=json.dumps(
                {
                    "whatChanged": "최신 현장 상태가 갱신되었습니다.",
                    "whyItMatters": "다음 조사 전 현재 상태 확인이 필요합니다.",
                    "decisionPrompt": "현재 AOI를 기준으로 조사 계획을 검토하시겠습니까?",
                    "uncertainty": "검증된 Site 상태만 반영했습니다.",
                }
            ),
            citation_ids=("site-1",),
        )


class _Backend:
    def site_exists(self, organization_id: str, site_id: str) -> bool:
        return organization_id == "org-a" and site_id == "site-a"

    def ai_egress_allowed(self, _organization_id: str, _site_id: str) -> bool:
        return False

    def query(self, **_kwargs: Any) -> ToolResult:
        return ToolResult(
            data={"siteStatus": "UNMAPPED"},
            citations=(
                CopilotCitation(
                    citation_id="site-1",
                    object_type="SITE_WORKSPACE",
                    object_id="site-a",
                    label="현장 A 최신 상태",
                    source_path="/v1/sites/site-a/workspace",
                ),
            ),
        )

    def create_reobservation_draft(self, **_kwargs: Any) -> ToolResult:
        raise AssertionError("draft tool은 이 테스트에서 호출되면 안 된다")


def _principal(organization_id: str, role: Role = Role.FIELD_OPERATOR) -> Principal:
    return Principal(
        principal_id=f"operator-{organization_id}",
        kind=PrincipalKind.OPERATOR,
        role=role,
        device_id=None,
        organization_id=organization_id,
    )


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=_principal(organization_id),
            )
            for token, organization_id in ((_TOKEN_A, "org-a"), (_TOKEN_B, "org-b"))
        ]
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _conversation_service(
    path: Path, *, model: _Model | None = None
) -> tuple[CopilotConversationService, DurableJournal, _Model]:
    journal = DurableJournal(path)
    store = CopilotConversationStore(
        journal,
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
        work_order_matches=lambda _work, _org, _site: False,
    )
    selected = model or _Model()
    service = CopilotConversationService(
        store=store,
        copilot=CopilotService(
            model=selected,
            backend=_Backend(),
            planner_version="planner-1",
        ),
        provider="test-provider",
        model="test-model",
        planner_version="planner-1",
    )
    return service, journal, selected


def test_message_is_durable_idempotent_and_replays(tmp_path: Path) -> None:
    path = tmp_path / "conversations.jsonl"
    service, journal, model = _conversation_service(path)
    conversation = service.store.create(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=None,
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    from ksi_core.copilot_conversations import CopilotMessageCreateRequest

    request = CopilotMessageCreateRequest(client_message_id="client-1", question="무엇이 달라졌나?")
    first = service.submit(conversation.conversation_id, request, principal=_principal("org-a"))
    duplicate = service.submit(
        conversation.conversation_id, request, principal=_principal("org-a")
    )
    assert duplicate == first
    assert model.calls == 2
    journal.close()

    replayed_store = CopilotConversationStore(
        DurableJournal(path),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
        work_order_matches=lambda _work, _org, _site: False,
    )
    messages = replayed_store.messages(
        conversation.conversation_id, organization_id="org-a"
    )
    assert [item.role.value for item in messages] == ["USER", "ASSISTANT"]
    assert messages[-1].citations[0].object_id == "site-a"


def test_reusing_client_message_id_with_different_question_is_rejected(tmp_path: Path) -> None:
    service, _journal, _model = _conversation_service(tmp_path / "conflict.jsonl")
    conversation = service.store.create(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=None,
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    from ksi_core.copilot_conversations import CopilotMessageCreateRequest

    service.submit(
        conversation.conversation_id,
        CopilotMessageCreateRequest(client_message_id="same", question="첫 질문"),
        principal=_principal("org-a"),
    )
    with pytest.raises(RuntimeError, match="IDEMPOTENCY_KEY_REUSE"):
        service.submit(
            conversation.conversation_id,
            CopilotMessageCreateRequest(client_message_id="same", question="다른 질문"),
            principal=_principal("org-a"),
        )


def test_provider_failure_is_saved_as_blocked_and_cross_org_is_404(tmp_path: Path) -> None:
    service, _journal, model = _conversation_service(
        tmp_path / "blocked.jsonl", model=_Model(fail=True)
    )
    conversation = service.store.create(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=None,
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    site_store = SiteStore(DurableJournal(tmp_path / "api-sites.jsonl"))
    site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    client = TestClient(
        create_app(
            auth_registry=_registry(),
            copilot_service=service._copilot,  # noqa: SLF001 -- exact mounted service pair
            copilot_conversation_service=service,
            site_store=site_store,
        )
    )
    response = client.post(
        f"/v1/copilot/conversations/{conversation.conversation_id}/messages",
        headers=_headers(_TOKEN_A),
        json={"clientMessageId": "blocked-1", "question": "현장 상태는?"},
    )
    assert response.status_code == 200
    assert response.json()["assistantMessage"]["answerStatus"] == "BLOCKED"
    assert response.json()["assistantMessage"]["missingData"] == ["PROVIDER_UNAVAILABLE"]
    assert model.calls == 1
    assert (
        client.get(
            f"/v1/copilot/conversations/{conversation.conversation_id}",
            headers=_headers(_TOKEN_B),
        ).status_code
        == 404
    )


def test_openai_adapter_accepts_only_strict_tool_and_final_shapes(tmp_path: Path) -> None:
    key_file = tmp_path / "api.key"
    key_file.write_text("test-key", encoding="utf-8")
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "site_snapshot",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {"answer": "검증 답변", "citationIds": ["site-1"]}
                        ),
                    }
                }
            ]
        },
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    adapter = OpenAiCompatibleModelAdapter(
        base_url="https://provider.example",
        model="model-1",
        api_key_file=key_file,
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tool_turn = adapter.complete(
        messages=({"role": "user", "content": "질문"},),
        tools=(
            {
                "name": "site_snapshot",
                "description": "현장",
                "inputSchema": {"type": "object"},
            },
        ),
    )
    assert tool_turn.tool_calls[0].name == "site_snapshot"
    final_turn = adapter.complete(
        messages=({"role": "user", "content": "질문"},),
        tools=(),
    )
    assert final_turn.answer == "검증 답변"
    with pytest.raises(CopilotProviderError, match="반출 금지"):
        adapter.complete(
            messages=({"role": "tool", "toolCallId": "x", "content": {"downloadUrl": "x"}},),
            tools=(),
        )


def test_workspace_uses_site_and_work_order_facts_without_inventing_analysis(
    tmp_path: Path,
) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    result = site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    assert result.record is not None
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )

    class _ProcessingFacts:
        def list_for_site(
            self, site_id: str, *, organization_id: str
        ) -> list[Any]:
            assert site_id == "site-a"
            assert organization_id == "org-a"
            return []

    workspace = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=cast(Any, _ProcessingFacts()),
        event_store=None,
    ).project("site-a", organization_id="org-a")
    assert workspace.latest_analysis.status == "UNAVAILABLE"
    assert workspace.latest_observation_at is None
    assert workspace.next_action.kind == "SET_AOI"
    assert workspace.next_action.label == "현장 범위 설정"
    assert workspace.next_action.href == "/sites/site-a?section=work#site-aoi"
    assert "AOI" not in workspace.next_action.reason
    with pytest.raises(LookupError, match="현장을 찾을 수 없다"):
        SiteWorkspaceProjector(
            site_store=site_store,
            work_order_store=work_orders,
            processing_job_store=None,
            event_store=None,
        ).project("site-a", organization_id="org-b")


def test_workspace_review_count_tracks_open_human_decisions(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "review-sites.jsonl"))
    site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "review-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )

    class _EventFacts:
        def list(self, **kwargs: Any) -> list[SimpleNamespace]:
            assert kwargs["organization_id"] == "org-a"
            return [
                SimpleNamespace(status=EventStatus.CANDIDATE, triage=TriageStatus.NONE),
                # 사실 확정 뒤에도 후속 사람 처리가 남아 있으면 확인 항목이다.
                SimpleNamespace(status=EventStatus.CONFIRMED_EVENT, triage=TriageStatus.ASSIGNED),
                SimpleNamespace(status=EventStatus.CANDIDATE, triage=TriageStatus.RESOLVED),
                SimpleNamespace(status=EventStatus.DISMISSED, triage=TriageStatus.NONE),
            ]

    workspace = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=None,
        event_store=cast(Any, _EventFacts()),
    ).project("site-a", organization_id="org-a")

    assert workspace.review_item_count == 2
    assert workspace.next_action.kind == "REVIEW_ITEMS"
    assert workspace.next_action.label == "확인 항목 2건 검토"


def test_workspace_review_count_reads_every_event_page(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "paged-review-sites.jsonl"))
    site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "paged-review-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    events = [
        SimpleNamespace(status=EventStatus.CANDIDATE, triage=TriageStatus.NONE)
        for _ in range(501)
    ]

    class _PagedEventFacts:
        def list(self, **kwargs: Any) -> list[SimpleNamespace]:
            assert kwargs["organization_id"] == "org-a"
            offset = kwargs["offset"]
            limit = kwargs["limit"]
            return events[offset : offset + limit]

    workspace = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=None,
        event_store=cast(Any, _PagedEventFacts()),
    ).project("site-a", organization_id="org-a")

    assert workspace.review_item_count == 501
    assert workspace.next_action.label == "확인 항목 501건 검토"


def test_briefing_provider_failure_is_recorded_as_blocked(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "briefing-sites.jsonl"))
    site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "briefing-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=None,
        event_store=None,
    )
    journal_path = tmp_path / "briefings.jsonl"
    journal = DurableJournal(journal_path)
    service = SiteBriefingService(
        store=SiteBriefingStore(journal, site_store=site_store),
        copilot=CopilotService(
            model=_Model(fail=True),
            backend=_Backend(),
            planner_version="planner-1",
        ),
        workspace=projector,
    )
    briefing = service.refresh("site-a", principal=_principal("org-a"))
    assert briefing.status.value == "BLOCKED"
    assert briefing.missing_data == ["PROVIDER_UNAVAILABLE"]
    assert briefing.citations == []
    journal.close()

    replayed = SiteBriefingStore(
        DurableJournal(journal_path),
        site_store=site_store,
    ).latest("site-a", organization_id="org-a")
    assert replayed == briefing


def test_ready_briefing_is_idempotent_for_same_workspace_watermark(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "ready-briefing-sites.jsonl"))
    site_store.register(
        "site-a",
        "현장 A",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        organization_id="org-a",
        actor="operator-org-a",
        now=datetime.now(UTC),
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "ready-briefing-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=None,
        event_store=None,
    )
    model = _BriefingModel()
    service = SiteBriefingService(
        store=SiteBriefingStore(
            DurableJournal(tmp_path / "ready-briefings.jsonl"), site_store=site_store
        ),
        copilot=CopilotService(
            model=model,
            backend=_Backend(),
            planner_version="planner-1",
        ),
        workspace=projector,
    )

    first = service.refresh("site-a", principal=_principal("org-a"))
    second = service.refresh("site-a", principal=_principal("org-a"))

    assert first.status.value == "READY"
    assert second.briefing_id == first.briefing_id
    assert model.calls == 2

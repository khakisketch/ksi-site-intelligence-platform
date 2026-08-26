"""Durable, organization-scoped Site Copilot conversations (REQ-COP-101/102).

The model is never the system of record. A user message is journaled before the
provider is called and only a citation-validated ``CopilotAnswer`` is appended as
the assistant message. Provider failures become durable ``BLOCKED`` answers so a
refresh does not make the failure disappear or replace a previous valid answer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from ksi_event_contracts.copilot import (
    CopilotAnswer,
    CopilotAnswerStatus,
    CopilotConversation,
    CopilotConversationStatus,
    CopilotMessage,
    CopilotMessageRole,
)
from pydantic import Field, ValidationError

from ksi_core.api_base import CamelModel
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.copilot import CopilotQueryRequest, CopilotService
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class CopilotConversationRecoveryError(RuntimeError):
    """Conversation journal cannot be replayed without breaking its lineage."""


class ConversationCreateRequest(CamelModel):
    work_order_id: str | None = None


class ConversationListResponse(CamelModel):
    conversations: list[CopilotConversation]


class ConversationDetailView(CamelModel):
    conversation: CopilotConversation
    messages: list[CopilotMessage]


class CopilotMessageCreateRequest(CamelModel):
    client_message_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)


class CopilotExchangeResponse(CamelModel):
    conversation: CopilotConversation
    user_message: CopilotMessage
    assistant_message: CopilotMessage


@dataclass(frozen=True, slots=True)
class _Exchange:
    user: CopilotMessage
    assistant: CopilotMessage | None


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp는 tz-aware여야 한다")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CopilotConversationStore:
    """Append-only conversation projection with client-message idempotency."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_exists: Callable[[str, str], bool],
        work_order_matches: Callable[[str, str, str], bool],
    ) -> None:
        self._journal = journal
        self._site_exists = site_exists
        self._work_order_matches = work_order_matches
        self._lock = threading.Lock()
        self._conversations: dict[str, CopilotConversation] = {}
        self._messages: dict[str, list[CopilotMessage]] = {}
        self._exchanges: dict[tuple[str, str], _Exchange] = {}
        self._conversation_sequence = 0
        self._message_sequence = 0
        try:
            self._replay()
        except CopilotConversationRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise CopilotConversationRecoveryError(
                f"copilot conversation journal 재생 실패: {exc}"
            ) from exc

    def _replay(self) -> None:
        for raw in self._journal.replay():
            try:
                kind = raw["kind"]
                if kind == "copilot-conversation-created":
                    conversation = CopilotConversation.model_validate(raw["conversation"])
                    if conversation.conversation_id in self._conversations:
                        raise ValueError("중복 conversationId")
                    if not self._site_exists(
                        conversation.site_id, conversation.organization_id
                    ):
                        raise ValueError("존재하지 않는 조직-scoped Site 대화")
                    if conversation.work_order_id is not None and not self._work_order_matches(
                        conversation.work_order_id,
                        conversation.organization_id,
                        conversation.site_id,
                    ):
                        raise ValueError("Site와 일치하지 않는 WorkOrder 대화")
                    self._conversations[conversation.conversation_id] = conversation
                    self._messages[conversation.conversation_id] = []
                    self._conversation_sequence = max(
                        self._conversation_sequence,
                        int(conversation.conversation_id.rsplit("-", 1)[-1]),
                    )
                elif kind == "copilot-message-started":
                    message = CopilotMessage.model_validate(raw["message"])
                    self._apply_started(message)
                elif kind == "copilot-message-completed":
                    message = CopilotMessage.model_validate(raw["message"])
                    client_message_id = raw["clientMessageId"]
                    self._apply_completed(message, client_message_id=client_message_id)
                else:
                    raise ValueError(f"알 수 없는 kind: {kind!r}")
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                raise CopilotConversationRecoveryError(
                    f"copilot conversation journal 레코드가 유효하지 않다: {exc}"
                ) from exc

    def _apply_started(self, message: CopilotMessage) -> None:
        conversation = self._conversations.get(message.conversation_id)
        if conversation is None:
            raise ValueError("미지 conversation message")
        if message.role is not CopilotMessageRole.USER or message.client_message_id is None:
            raise ValueError("started record는 USER message여야 한다")
        key = (message.conversation_id, message.client_message_id)
        if key in self._exchanges:
            raise ValueError("중복 clientMessageId")
        if self._has_message_id(message.message_id):
            raise ValueError("중복 messageId")
        self._messages[message.conversation_id].append(message)
        self._exchanges[key] = _Exchange(user=message, assistant=None)
        self._message_sequence = max(
            self._message_sequence, int(message.message_id.rsplit("-", 1)[-1])
        )
        self._conversations[message.conversation_id] = conversation.model_copy(
            update={"updated_at": message.created_at}
        )

    def _apply_completed(self, message: CopilotMessage, *, client_message_id: str) -> None:
        if message.role is not CopilotMessageRole.ASSISTANT:
            raise ValueError("completed record는 ASSISTANT message여야 한다")
        key = (message.conversation_id, client_message_id)
        exchange = self._exchanges.get(key)
        if exchange is None or exchange.assistant is not None:
            raise ValueError("pending user message가 없는 completed record")
        if self._has_message_id(message.message_id):
            raise ValueError("중복 messageId")
        self._messages[message.conversation_id].append(message)
        self._exchanges[key] = _Exchange(user=exchange.user, assistant=message)
        self._message_sequence = max(
            self._message_sequence, int(message.message_id.rsplit("-", 1)[-1])
        )
        conversation = self._conversations[message.conversation_id]
        self._conversations[message.conversation_id] = conversation.model_copy(
            update={"updated_at": message.created_at}
        )

    def _has_message_id(self, message_id: str) -> bool:
        return any(
            message.message_id == message_id
            for messages in self._messages.values()
            for message in messages
        )

    def create(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_order_id: str | None,
        actor: str,
        now: datetime,
    ) -> CopilotConversation:
        if not is_path_safe_identifier(organization_id) or not is_path_safe_identifier(site_id):
            raise ValueError("organizationId/siteId는 경로-안전 식별자여야 한다")
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        if work_order_id is not None and not self._work_order_matches(
            work_order_id, organization_id, site_id
        ):
            raise LookupError("관측 작업을 찾을 수 없다")
        with self._lock:
            conversation_id = f"copilot-conversation-{self._conversation_sequence + 1:08d}"
            created_at = _iso(now)
            conversation = CopilotConversation(
                conversation_id=conversation_id,
                organization_id=organization_id,
                site_id=site_id,
                work_order_id=work_order_id,
                status=CopilotConversationStatus.ACTIVE,
                created_by=actor,
                created_at=created_at,
                updated_at=created_at,
            )
            self._journal.append(
                {
                    "kind": "copilot-conversation-created",
                    "ts": created_at,
                    "actor": actor,
                    "conversation": conversation.model_dump(by_alias=True, mode="json"),
                }
            )
            self._conversations[conversation_id] = conversation
            self._messages[conversation_id] = []
            self._conversation_sequence += 1
            return conversation

    def get(
        self, conversation_id: str, *, organization_id: str
    ) -> CopilotConversation | None:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.organization_id != organization_id:
                return None
            return conversation

    def list_for_site(
        self, site_id: str, *, organization_id: str
    ) -> list[CopilotConversation]:
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        with self._lock:
            return sorted(
                (
                    item
                    for item in self._conversations.values()
                    if item.site_id == site_id and item.organization_id == organization_id
                ),
                key=lambda item: (item.updated_at, item.conversation_id),
                reverse=True,
            )

    def messages(self, conversation_id: str, *, organization_id: str) -> list[CopilotMessage]:
        if self.get(conversation_id, organization_id=organization_id) is None:
            raise LookupError("대화를 찾을 수 없다")
        with self._lock:
            return list(self._messages[conversation_id])

    def begin_exchange(
        self,
        conversation_id: str,
        *,
        organization_id: str,
        client_message_id: str,
        question: str,
        actor: str,
        now: datetime,
    ) -> _Exchange:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.organization_id != organization_id:
                raise LookupError("대화를 찾을 수 없다")
            key = (conversation_id, client_message_id)
            existing = self._exchanges.get(key)
            if existing is not None:
                if existing.user.content != question:
                    raise RuntimeError("IDEMPOTENCY_KEY_REUSE")
                return existing
            message_id = f"copilot-message-{self._message_sequence + 1:08d}"
            user = CopilotMessage(
                message_id=message_id,
                conversation_id=conversation_id,
                role=CopilotMessageRole.USER,
                content=question,
                client_message_id=client_message_id,
                answer_status=None,
                citations=[],
                missing_data=[],
                reobservation_draft_id=None,
                provider=None,
                model=None,
                planner_version=None,
                created_by=actor,
                created_at=_iso(now),
            )
            self._journal.append(
                {
                    "kind": "copilot-message-started",
                    "ts": user.created_at,
                    "actor": actor,
                    "message": user.model_dump(by_alias=True, mode="json"),
                }
            )
            self._apply_started(user)
            return self._exchanges[key]

    def complete_exchange(
        self,
        conversation_id: str,
        *,
        organization_id: str,
        client_message_id: str,
        answer: CopilotAnswer,
        provider: str,
        model: str,
        planner_version: str,
        now: datetime,
    ) -> _Exchange:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.organization_id != organization_id:
                raise LookupError("대화를 찾을 수 없다")
            key = (conversation_id, client_message_id)
            exchange = self._exchanges.get(key)
            if exchange is None:
                raise RuntimeError("MESSAGE_NOT_STARTED")
            if exchange.assistant is not None:
                return exchange
            message_id = f"copilot-message-{self._message_sequence + 1:08d}"
            assistant = CopilotMessage(
                message_id=message_id,
                conversation_id=conversation_id,
                role=CopilotMessageRole.ASSISTANT,
                content=answer.answer,
                client_message_id=None,
                answer_status=answer.status,
                citations=answer.citations,
                missing_data=answer.missing_data,
                reobservation_draft_id=answer.reobservation_draft_id,
                provider=provider,
                model=model,
                planner_version=planner_version,
                created_by=f"copilot:{provider}",
                created_at=_iso(now),
            )
            self._journal.append(
                {
                    "kind": "copilot-message-completed",
                    "ts": assistant.created_at,
                    "actor": assistant.created_by,
                    "clientMessageId": client_message_id,
                    "message": assistant.model_dump(by_alias=True, mode="json"),
                }
            )
            self._apply_completed(assistant, client_message_id=client_message_id)
            return self._exchanges[key]


class CopilotConversationService:
    """Serializes duplicate message submissions around the model call."""

    def __init__(
        self,
        *,
        store: CopilotConversationStore,
        copilot: CopilotService,
        provider: str,
        model: str,
        planner_version: str,
    ) -> None:
        if not all(value.strip() for value in (provider, model, planner_version)):
            raise ValueError("provider/model/planner_version은 비어 있을 수 없다")
        self._store = store
        self._copilot = copilot
        self._provider = provider
        self._model = model
        self._planner_version = planner_version
        self._lock = threading.Lock()

    @property
    def store(self) -> CopilotConversationStore:
        return self._store

    def submit(
        self,
        conversation_id: str,
        request: CopilotMessageCreateRequest,
        *,
        principal: Principal,
    ) -> CopilotExchangeResponse:
        with self._lock:
            conversation = self._store.get(
                conversation_id, organization_id=principal.organization_id
            )
            if conversation is None:
                raise LookupError("대화를 찾을 수 없다")
            exchange = self._store.begin_exchange(
                conversation_id,
                organization_id=principal.organization_id,
                client_message_id=request.client_message_id,
                question=request.question,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
            if exchange.assistant is None:
                try:
                    answer = self._copilot.query(
                        CopilotQueryRequest(
                            site_id=conversation.site_id,
                            work_order_id=conversation.work_order_id,
                            question=request.question,
                        ),
                        principal=principal,
                    )
                except Exception:
                    logger.exception(
                        "Copilot provider failed; storing BLOCKED answer conversation=%s",
                        conversation_id,
                    )
                    answer = CopilotAnswer(
                        status=CopilotAnswerStatus.BLOCKED,
                        answer=(
                            "현재 KSI AI가 검증된 답변을 만들지 못했습니다. "
                            "기존 현장 결과는 그대로 유지되며 잠시 후 다시 질문할 수 있습니다."
                        ),
                        missing_data=["PROVIDER_UNAVAILABLE"],
                    )
                exchange = self._store.complete_exchange(
                    conversation_id,
                    organization_id=principal.organization_id,
                    client_message_id=request.client_message_id,
                    answer=answer,
                    provider=self._provider,
                    model=self._model,
                    planner_version=self._planner_version,
                    now=datetime.now(UTC),
                )
            assert exchange.assistant is not None  # noqa: S101 -- completed branch postcondition
            current = self._store.get(
                conversation_id, organization_id=principal.organization_id
            )
            assert current is not None  # noqa: S101 -- checked before begin_exchange
            return CopilotExchangeResponse(
                conversation=current,
                user_message=exchange.user,
                assistant_message=exchange.assistant,
            )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalSealedError):
        return HTTPException(status_code=503, detail="Copilot 대화 원장을 사용할 수 없다")
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def build_copilot_conversation_router(
    service: CopilotConversationService,
) -> APIRouter:
    router = APIRouter(tags=["copilot-conversations"])
    store = service.store

    @router.get(
        "/v1/sites/{site_id}/copilot/conversations",
        response_model=ConversationListResponse,
    )
    def list_conversations(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
    ) -> ConversationListResponse:
        try:
            return ConversationListResponse(
                conversations=store.list_for_site(
                    site_id, organization_id=principal.organization_id
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/v1/sites/{site_id}/copilot/conversations",
        response_model=CopilotConversation,
        status_code=201,
    )
    def create_conversation(
        site_id: str,
        request: ConversationCreateRequest,
        principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
    ) -> CopilotConversation:
        try:
            return store.create(
                organization_id=principal.organization_id,
                site_id=site_id,
                work_order_id=request.work_order_id,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/v1/copilot/conversations/{conversation_id}",
        response_model=ConversationDetailView,
    )
    def get_conversation(
        conversation_id: str,
        principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
    ) -> ConversationDetailView:
        conversation = store.get(
            conversation_id, organization_id=principal.organization_id
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없다")
        return ConversationDetailView(
            conversation=conversation,
            messages=store.messages(
                conversation_id, organization_id=principal.organization_id
            ),
        )

    @router.post(
        "/v1/copilot/conversations/{conversation_id}/messages",
        response_model=CopilotExchangeResponse,
    )
    def create_message(
        conversation_id: str,
        request: CopilotMessageCreateRequest,
        principal: Principal = Depends(require_permission(Permission.COPILOT_QUERY)),  # noqa: B008
    ) -> CopilotExchangeResponse:
        try:
            return service.submit(conversation_id, request, principal=principal)
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def mount_copilot_conversations(app: FastAPI, service: CopilotConversationService) -> None:
    app.state.copilot_conversation_service = service
    app.include_router(build_copilot_conversation_router(service))


__all__ = [
    "ConversationCreateRequest",
    "ConversationDetailView",
    "ConversationListResponse",
    "CopilotConversationService",
    "CopilotConversationStore",
    "CopilotExchangeResponse",
    "CopilotMessageCreateRequest",
    "mount_copilot_conversations",
]

"""ActionIntent 계약 + 참조 검증기 (Stage C-4, contracts/schemas/action-intent.v1.json SSOT).

Python Intelligence Plane과 C++ Control Plane 사이의 **언어 중립 계약**이다. 같은
JSON 계약을 두 언어가 동일하게 해석해야 하며, 그 동치성은
``contracts/conformance/action-intent-verdicts.v1.json`` 공유 벡터를 양쪽이 각자
실행해 확인한다(Python: tests/contract/test_action_intent_conformance.py,
C++: edge/manifold-runtime/tests/conformance_tests.cpp).

여기 :func:`verify_action_intent` 는 C++ ``VerifyActionIntent`` 와 **같은 판정 순서**를
갖는 참조 구현이다 — 순서가 어긋나면 같은 입력이 다른 사유를 내므로 공유 벡터가
그 불일치를 잡는다.

범위 제약: 이 모듈은 명령의 **유효성만** 판정한다. 실제 비행 명령 발행 경로는
Stage C 범위 밖이며(실기/HIL 증거 전까지 금지), Python은 어떤 경우에도 DJI Flight
Command를 직접 호출하지 않는다(INV-001·INV-002).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ActionIntentKind(StrEnum):
    """고수준 의도만 존재한다 — 저수준 조종 동사는 계약에 없다(INV-001)."""

    HOLD = "HOLD"
    RETURN_TO_HOME = "RETURN_TO_HOME"
    GOTO_VIEWPOINT = "GOTO_VIEWPOINT"
    CAPTURE_IMAGE = "CAPTURE_IMAGE"


class CommandVerdict(StrEnum):
    """명령 판정. ``ACCEPTED``가 아니면 어떤 행동도 개시하지 않는다(fail-closed).

    C++ ``ksi::control_plane::CommandVerdict`` 와 값이 1:1 대응해야 한다 —
    ``SUPERVISOR_NOT_READY`` 는 Supervisor 상태 게이트 전용이라 이 순수 검증기는
    반환하지 않지만, 계약 열거값으로는 공유한다.
    """

    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    NOT_YET_VALID = "NOT_YET_VALID"
    MISSING_AUTHORIZATION = "MISSING_AUTHORIZATION"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    MALFORMED = "MALFORMED"
    SUPERVISOR_NOT_READY = "SUPERVISOR_NOT_READY"


class ActionIntent(BaseModel):
    """action-intent.v1.json 대응 모델."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    schema_version: Literal["1.0"] = "1.0"
    command_id: str = Field(min_length=1)
    kind: ActionIntentKind
    authorization_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    issued_at_utc_ms: int
    ttl_ms: int = Field(gt=0)
    target_viewpoint_id: str | None = None


def verify_action_intent(
    intent_data: dict[str, object],
    active_digest: str,
    now_utc_ms: int,
) -> CommandVerdict:
    """C++ ``VerifyActionIntent`` 와 동일한 순서로 판정한다.

    판정 순서(양쪽 동일): 형식 → 인가 존재 → 인가 일치 → 미래 발행 → TTL 만료.
    dict를 받는 이유는 형식 위반(빈 command_id·비양수 ttl 등)까지 ``MALFORMED``로
    판정해야 하는데, Pydantic 모델은 그런 입력을 애초에 거부하기 때문이다 —
    C++ 쪽이 구조체 필드로 받아 런타임 검사하는 것과 대칭을 맞춘다.

    예외를 던지지 않는다(fail-closed — 판정 불가는 거부로 귀결).
    """
    command_id = intent_data.get("commandId")
    ttl_ms = intent_data.get("ttlMs")
    issued_at = intent_data.get("issuedAtUtcMs")
    digest = intent_data.get("authorizationDigest")

    if not isinstance(command_id, str) or not command_id:
        return CommandVerdict.MALFORMED
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms <= 0:
        return CommandVerdict.MALFORMED
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        return CommandVerdict.MALFORMED

    if not isinstance(digest, str) or not digest:
        return CommandVerdict.MISSING_AUTHORIZATION
    if not active_digest or digest != active_digest:
        return CommandVerdict.AUTHORIZATION_MISMATCH

    if issued_at > now_utc_ms:
        return CommandVerdict.NOT_YET_VALID
    # TTL 경계는 배타적 — 정확히 issued_at + ttl 시점에 이미 만료다(C++와 동일).
    if now_utc_ms - issued_at >= ttl_ms:
        return CommandVerdict.EXPIRED
    return CommandVerdict.ACCEPTED

"""ActionIntent 계약 + 참조 검증기 (Stage C-4, contracts/schemas/action-intent.v1.json SSOT).

Python Intelligence Plane과 C++ Control Plane 사이의 **언어 중립 계약**이다. 같은
JSON 계약을 두 언어가 동일하게 해석해야 하며, 그 동치성은
``contracts/conformance/action-intent-verdicts.v1.json`` 공유 벡터를 양쪽이 각자
실행해 확인한다(Python: tests/contract/test_action_intent_conformance.py,
C++: edge/manifold-runtime/tests/conformance_tests.cpp).

여기 :func:`verify_action_intent` 는 C++ ``VerifyActionIntent`` 와 **같은 판정 순서**를
갖는 참조 구현이다 — 순서가 어긋나면 같은 입력이 다른 사유를 내므로 공유 벡터가
그 불일치를 잡는다.

## 형식 게이트가 '무엇을 하라는 명령인가'까지 본다 (감사 #7·#16~#18 폐쇄)

초판 검증기는 command_id·ttl·시각만 봤다 — kind·schemaVersion 을 보지 않아 계약에
없는 저수준 동사나 미지 스키마 버전이 ACCEPTED 로 통과할 수 있었다(INV-001/002
접점의 fail-open). 현재 형식 게이트: schemaVersion 정확 일치 · kind 등록 여부 ·
미지 키 거부 · TTL 상한(:data:`MAX_TTL_MS`) · 시각 도메인(:data:`MAX_UTC_MS` —
C++ int64 뺄셈 오버플로 방지의 근거이기도 하다) · GOTO_VIEWPOINT 의 목적지 필수.

범위 제약: 이 모듈은 명령의 **유효성만** 판정한다. 실제 비행 명령 발행 경로는
Stage C 범위 밖이며(실기/HIL 증거 전까지 금지), Python은 어떤 경우에도 DJI Flight
Command를 직접 호출하지 않는다(INV-001·INV-002).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# TTL 상한 — 무기한 유효한 명령(사실상 replay 가능한 인가 토큰)을 계약이 금지한다.
# 값 5분은 관측점 이동·재관찰 의도의 신선도 상한으로 둔 **권고 기본값**이며,
# 운영 지연 허용치는 대표자 결정 사항이다(변경 시 이 상수 + JSON 스키마 maximum +
# C++ kMaxTtlMs + conformance 벡터를 함께 갱신 — 값이 갈리면 벡터가 잡는다).
MAX_TTL_MS = 300_000

# 시각 도메인 상한 — 2100-01-01T00:00:00Z (UTC epoch ms). 이 밖의 issued_at/now 는
# 판정 불가로 MALFORMED 다. C++ 쪽에서는 이 범위 선검사가 int64 뺄셈 오버플로
# (감사 #14 — signed overflow UB 로 fail-open)를 구조적으로 막는 근거가 된다.
MAX_UTC_MS = 4_102_444_800_000

_ALLOWED_KEYS = frozenset(
    {
        "schemaVersion",
        "commandId",
        "kind",
        "authorizationDigest",
        "issuedAtUtcMs",
        "ttlMs",
        "targetViewpointId",
    }
)


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
    """action-intent.v1.json 대응 모델 — 참조 검증기와 같은 제약을 모델 계층에도 건다."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    schema_version: Literal["1.0"] = "1.0"
    command_id: str = Field(min_length=1)
    kind: ActionIntentKind
    authorization_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    issued_at_utc_ms: int = Field(ge=0, le=MAX_UTC_MS)
    ttl_ms: int = Field(gt=0, le=MAX_TTL_MS)
    target_viewpoint_id: str | None = None

    @model_validator(mode="after")
    def _goto_requires_target(self) -> ActionIntent:
        if self.kind is ActionIntentKind.GOTO_VIEWPOINT and not self.target_viewpoint_id:
            raise ValueError(
                "GOTO_VIEWPOINT 는 targetViewpointId 가 필수다 — 목적지 없는 이동 "
                "의도는 하류가 기본값을 지어내게 만든다(fail-open 유혹)"
            )
        return self


def verify_action_intent(
    intent_data: dict[str, object],
    active_digest: str,
    now_utc_ms: int,
) -> CommandVerdict:
    """C++ ``VerifyActionIntent`` 와 동일한 순서로 판정한다.

    판정 순서(양쪽 동일): 형식 → 인가 존재 → 인가 일치 → 미래 발행 → TTL 만료.
    형식 단계 내부 순서도 C++ 와 맞춘다: schemaVersion → command_id → ttl →
    issued_at → now 도메인 → kind 별 필수 필드. (미지 키·미지 kind 거부는 dict 를
    받는 Python 쪽에만 있는 검사다 — C++ 는 struct 라 그 계층이 wire 파서의 몫이며,
    이 차이는 벡터로 표현할 수 없어 Python 전용 테스트가 고정한다.)

    dict를 받는 이유는 형식 위반(빈 command_id·비양수 ttl 등)까지 ``MALFORMED``로
    판정해야 하는데, Pydantic 모델은 그런 입력을 애초에 거부하기 때문이다 —
    C++ 쪽이 구조체 필드로 받아 런타임 검사하는 것과 대칭을 맞춘다.

    예외를 던지지 않는다(fail-closed — 판정 불가는 거부로 귀결).
    """
    if set(intent_data) - _ALLOWED_KEYS:
        return CommandVerdict.MALFORMED

    schema_version = intent_data.get("schemaVersion")
    command_id = intent_data.get("commandId")
    kind = intent_data.get("kind")
    ttl_ms = intent_data.get("ttlMs")
    issued_at = intent_data.get("issuedAtUtcMs")
    digest = intent_data.get("authorizationDigest")

    if schema_version != "1.0":
        return CommandVerdict.MALFORMED
    if not isinstance(command_id, str) or not command_id:
        return CommandVerdict.MALFORMED
    if not isinstance(kind, str) or kind not in {k.value for k in ActionIntentKind}:
        return CommandVerdict.MALFORMED
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or not (0 < ttl_ms <= MAX_TTL_MS):
        return CommandVerdict.MALFORMED
    if (
        not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not (0 <= issued_at <= MAX_UTC_MS)
    ):
        return CommandVerdict.MALFORMED
    if not (0 <= now_utc_ms <= MAX_UTC_MS):
        # 판정 기준 시각 자체가 도메인 밖 — 시간 판정을 신뢰할 수 없으므로 거부.
        return CommandVerdict.MALFORMED
    if kind == ActionIntentKind.GOTO_VIEWPOINT.value:
        target = intent_data.get("targetViewpointId")
        if not isinstance(target, str) or not target:
            return CommandVerdict.MALFORMED

    if not isinstance(digest, str) or not digest:
        return CommandVerdict.MISSING_AUTHORIZATION
    if not active_digest or digest != active_digest:
        return CommandVerdict.AUTHORIZATION_MISMATCH

    if issued_at > now_utc_ms:
        return CommandVerdict.NOT_YET_VALID
    # TTL 경계는 배타적 — 정확히 issued_at + ttl 시점에 이미 만료다(C++와 동일).
    # 위 도메인 선검사로 now-issued 는 [-MAX_UTC_MS, MAX_UTC_MS] 안이라 C++ int64
    # 뺄셈도 오버플로하지 않는다.
    if now_utc_ms - issued_at >= ttl_ms:
        return CommandVerdict.EXPIRED
    return CommandVerdict.ACCEPTED

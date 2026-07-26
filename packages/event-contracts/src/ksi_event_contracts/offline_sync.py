"""Edge Store-and-Forward / 멱등 재동기화 계약 (P1-3).

근거: EDGE-004("Store-and-Forward와 멱등 동기화를 제공한다"), MASTER_PRD §21.2
("Edge Event Journal은 서버 복구 후 순서와 계보를 보존해 동기화", "재동기화는 멱등성
보장"), §19.3(Idempotency Key), INV-012.

## 문제

서버 연결이 끊긴 동안 Edge는 이벤트를 로컬 journal에 쌓는다. 연결이 복구되면 쌓인
항목을 보낸다. 이때 반드시 성립해야 하는 것:

1. **멱등성** — 같은 항목을 두 번 보내도 결과가 한 번 보낸 것과 같아야 한다. ACK가
   유실되면 Edge는 재전송할 수밖에 없으므로, 재전송이 중복을 만들면 이벤트 수가
   부풀려진다(안전 판단이 왜곡된다).
2. **순서·계보 보존** — Edge가 관측한 순서가 서버에서도 유지돼야 한다. 순서가 섞이면
   "무엇이 먼저 일어났나"가 흔들려 사후 조사가 불가능해진다.
3. **손실 없음** — ACK를 받기 전에는 로컬에서 지우지 않는다(PRD §19.3 "Core가 durable
   persistence를 ACK한 뒤 Edge가 로컬 데이터를 삭제한다").

## 이 모듈의 범위

전송 계층(MQTT/HTTP)이 아니라 **계약과 판정 규칙**이다. 실제 네트워크 전송·영속
저장은 이후 단계이며, 여기서는 그 구현들이 지켜야 할 불변식을 코드로 고정한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class JournalEntry(BaseModel):
    """Edge journal 항목 1건 — 하나의 EventBundle(또는 다른 산출물)의 전송 단위.

    Attributes:
        idempotency_key: 재전송 판정의 유일한 기준(PRD §19.3). Edge가 항목 생성 시점에
            결정하며, 재전송해도 **같은 값**이어야 한다 — 매번 새로 만들면 멱등성이
            성립하지 않는다.
        device_sequence: 같은 Edge 장비 안에서 단조 증가하는 순번. 순서 보존과 누락
            탐지(빈 구간)의 근거다.
        edge_device_id: 어느 장비의 순번인지 — 여러 장비의 순번은 서로 독립이다.
        payload_digest: 본문의 ``sha256:<hex>``. 같은 키로 **다른 내용**이 오면 조용히
            받아들이지 않고 충돌로 판정하기 위한 값이다.
        payload: 실제 내용(EventBundle 등). 계약상 자유 dict이며 상위에서 타입이 정해진다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    idempotency_key: str = Field(min_length=1)
    device_sequence: int = Field(ge=0)
    edge_device_id: str = Field(min_length=1)
    payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload: dict[str, Any] = Field(default_factory=dict)


class PayloadCanonicalizationError(ValueError):
    """본문을 정규 JSON으로 표현할 수 없음 — NaN/Infinity 또는 비JSON 타입."""


def payload_digest(payload: dict[str, Any]) -> str:
    """본문의 정규화 digest — ADR-KSI-002와 같은 정규화 규약을 재사용한다.

    key 정렬·최소 구분자·``ensure_ascii=False`` UTF-8. 계약 서명과 같은 규약을 쓰는
    이유는 두 곳에서 서로 다른 정규화를 쓰면 "같은 내용"의 정의가 갈리기 때문이다.

    ``allow_nan=False`` 를 쓰는 이유(2차 반증 리뷰): 기본값은 NaN/Infinity를 ``NaN``·
    ``Infinity`` 같은 **비표준 JSON 토큰**으로 직렬화한다. 그러면 표준 파서로 다시 읽을
    수 없는 digest가 만들어지고, 서버·Edge가 서로 다른 파서를 쓸 때 "같은 내용"의 정의가
    갈린다. 비JSON 타입(set·bytes 등)도 여기서 typed 예외로 바꿔 호출자가
    :class:`IngestVerdict.MALFORMED_PAYLOAD` 로 변환할 수 있게 한다.

    Raises:
        PayloadCanonicalizationError: NaN/Infinity 또는 JSON 직렬화 불가 타입 포함.
    """
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        # ValueError: allow_nan=False 하에서 NaN/Infinity
        # TypeError: set·bytes·임의 객체 등 JSON 도메인 밖 타입
        raise PayloadCanonicalizationError(f"본문을 정규 JSON으로 표현할 수 없다: {exc}") from exc
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class IngestVerdict(StrEnum):
    """수신 판정. ``ACCEPTED``와 ``DUPLICATE_IGNORED``만 정상 경로다."""

    ACCEPTED = "ACCEPTED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"  # 동일 identity 재전송 — 멱등 무시
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"  # 같은 키, 다른 identity(장비·순번·내용)
    DIGEST_MISMATCH = "DIGEST_MISMATCH"  # 선언한 digest와 실제 본문이 불일치
    MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"  # NaN/Infinity·비JSON 타입 — 정규화 불가
    SEQUENCE_REGRESSION = "SEQUENCE_REGRESSION"  # 이미 지난 순번의 새 항목
    SEQUENCE_DUPLICATE = "SEQUENCE_DUPLICATE"  # 같은 순번에 다른 키


@dataclass(frozen=True, slots=True)
class IngestResult:
    verdict: IngestVerdict
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        """새로 반영됐는지. 멱등 무시는 "정상이지만 새로 반영되지 않음"이다."""
        return self.verdict is IngestVerdict.ACCEPTED


@dataclass(frozen=True, slots=True)
class EntryIdentity:
    """멱등 판정의 완전한 신원 — 키 하나가 아니라 네 값의 조합이다.

    키만으로 판정하면(2차 반증 리뷰) 다른 장비가 우연히 같은 키·같은 내용을 보낸
    **별개의 journal 항목**이 조용히 사라진다. 재전송은 네 값이 전부 같을 때뿐이며,
    하나라도 다르면 그것은 재전송이 아니라 충돌이다.
    """

    edge_device_id: str
    device_sequence: int
    payload_digest: str


@dataclass
class SyncLedger:
    """서버 측 수신 원장 — 멱등성·순서 보존을 판정하는 참조 구현.

    실제 Core는 이 판정을 PostgreSQL 제약(unique idempotency_key 등)으로 구현하겠지만,
    규칙 자체는 여기 고정된 것과 같아야 한다. 계약 테스트가 이 구현을 대상으로 규칙을
    검증하므로, DB 구현이 이 규칙에서 벗어나면 계약 위반이다.
    """

    # idempotency_key → EntryIdentity (키 + 장비 + 순번 + digest 4중 결합)
    _seen: dict[str, EntryIdentity] = field(default_factory=dict)
    # edge_device_id → 마지막으로 수락한 device_sequence
    _last_sequence: dict[str, int] = field(default_factory=dict)
    # 수락된 항목을 수신 순서대로 보관(순서 보존 검증용)
    _accepted: list[JournalEntry] = field(default_factory=list)
    # edge_device_id → 그 장비에서 사용된 (sequence → key)
    _sequence_keys: dict[str, dict[int, str]] = field(default_factory=dict)

    def ingest(self, entry: JournalEntry) -> IngestResult:
        """항목 1건을 수신 판정한다. 예외를 던지지 않는다(fail-closed).

        판정 순서: 본문 정규화 → digest 정합 → 멱등 신원 일치(재전송/충돌) → 순번
        중복 → 순번 역행. 순서가 중요한 이유는 "이미 본 항목의 재전송"을 순번 규칙보다
        먼저 처리해야 하기 때문이다 — 재전송은 당연히 순번이 역행한다.
        """
        try:
            actual_digest = payload_digest(entry.payload)
        except PayloadCanonicalizationError as exc:
            # 정규화 실패를 예외로 흘리면 "예외를 던지지 않는다"는 계약이 깨진다.
            return IngestResult(IngestVerdict.MALFORMED_PAYLOAD, detail=str(exc))
        if actual_digest != entry.payload_digest:
            return IngestResult(
                IngestVerdict.DIGEST_MISMATCH,
                detail=f"선언 {entry.payload_digest} != 실제 {actual_digest}",
            )

        identity = EntryIdentity(
            edge_device_id=entry.edge_device_id,
            device_sequence=entry.device_sequence,
            payload_digest=entry.payload_digest,
        )
        previous = self._seen.get(entry.idempotency_key)
        if previous is not None:
            if previous == identity:
                # 정상 재전송(ACK 유실 등) — 중복 생성 없이 무시한다.
                return IngestResult(IngestVerdict.DUPLICATE_IGNORED)
            return IngestResult(
                IngestVerdict.IDEMPOTENCY_CONFLICT,
                detail=(
                    f"같은 idempotency_key({entry.idempotency_key})에 다른 신원 — "
                    f"기존 {previous} != 신규 {identity}"
                ),
            )

        device_sequences = self._sequence_keys.setdefault(entry.edge_device_id, {})
        existing_key = device_sequences.get(entry.device_sequence)
        if existing_key is not None:
            return IngestResult(
                IngestVerdict.SEQUENCE_DUPLICATE,
                detail=(
                    f"{entry.edge_device_id} 순번 {entry.device_sequence} 이 이미 "
                    f"다른 키({existing_key})로 사용됨"
                ),
            )

        last = self._last_sequence.get(entry.edge_device_id)
        if last is not None and entry.device_sequence < last:
            # 새 키인데 순번이 과거 — 순서 보존이 깨졌다는 신호다. 조용히 받으면
            # 서버 측 순서가 Edge 관측 순서와 달라진다.
            return IngestResult(
                IngestVerdict.SEQUENCE_REGRESSION,
                detail=f"{entry.edge_device_id} 순번 {entry.device_sequence} < 최종 {last}",
            )

        self._seen[entry.idempotency_key] = identity
        device_sequences[entry.device_sequence] = entry.idempotency_key
        self._last_sequence[entry.edge_device_id] = entry.device_sequence
        self._accepted.append(entry)
        return IngestResult(IngestVerdict.ACCEPTED)

    def accepted_count(self) -> int:
        return len(self._accepted)

    def accepted_sequences(self, edge_device_id: str) -> list[int]:
        """수락된 순번을 **수신 순서대로** 반환 — 순서 보존 검증용."""
        return [e.device_sequence for e in self._accepted if e.edge_device_id == edge_device_id]

    def missing_sequences(self, edge_device_id: str) -> list[int]:
        """수락된 순번 사이의 빈 구간 — 아직 도착하지 않은(또는 유실된) 항목.

        Edge가 로컬에서 항목을 지워도 되는지 판단하는 근거가 아니다(그건 ACK의 역할).
        서버가 "무엇을 더 기다려야 하는지" 아는 데 쓴다.
        """
        sequences = sorted(
            e.device_sequence for e in self._accepted if e.edge_device_id == edge_device_id
        )
        if not sequences:
            return []
        return [n for n in range(sequences[0], sequences[-1]) if n not in set(sequences)]

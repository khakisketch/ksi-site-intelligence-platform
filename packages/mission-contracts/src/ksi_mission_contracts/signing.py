"""ADR-KSI-002 Mission Contract 서명 정책 구현 (INV-011 강제 지점).

정규화(canonicalization): 계약 dict에서 ``signature`` 블록을 제거한 뒤
UTF-8·key 정렬·최소 구분자(``,``/``:``)·``ensure_ascii=False``로 직렬화한 바이트열
(RFC 8785 JCS 실용 부분집합). digest는 그 바이트열의 SHA-256(``sha256:<hex>``) —
서명은 digest가 아니라 **정규화 바이트열 자체**에 대해 수행한다(ADR-KSI-002 §2·§3).

검증 실패는 예외가 아니라 typed :class:`SignatureVerdict` 로 반환한다
(fail-closed — ``VALID``가 아니면 계약은 실행 불가, ADR-KSI-002 §6).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from ksi_domain.canonical_json import canonical_json_bytes


def canonical_payload_bytes(contract: Mapping[str, Any]) -> bytes:
    """계약 dict의 서명대상 정규화 바이트열 (``signature`` 블록 제외, ADR-KSI-002 §2).

    정규화 규약 자체(key 정렬·최소 구분자·``allow_nan=False`` 등, 감사 #10 근거)는
    ``ksi_domain.canonical_json_bytes`` 가 소유한다 — event-contracts 의
    ``offline_sync.payload_digest`` 와 같은 규약을 공유해야 하기 때문이다(같은
    "정규화"의 정의가 두 패키지에서 갈리면 안 된다). 이 함수는 그 위에 "signature
    블록은 서명 대상에서 뺀다"는 이 도메인 고유 규칙만 얹는다.

    Raises:
        ValueError: NaN/Infinity 또는 JSON 도메인 밖 타입 포함 — 발행(sign) 시점의
            typed 실패다. verify 경로에서는 외곽 가드가 MALFORMED_CONTRACT 로 강등.
    """
    payload = {key: value for key, value in contract.items() if key != "signature"}
    try:
        return canonical_json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"계약을 정규 JSON 으로 표현할 수 없다: {exc}") from exc


def sha256_digest(payload: bytes) -> str:
    """정규화 바이트열의 SHA-256 digest, ``sha256:<hex>`` 형식 (ADR-KSI-002 §3)."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def build_signature_block(
    contract: Mapping[str, Any], private_key: Ed25519PrivateKey, key_id: str
) -> dict[str, str]:
    """``contract``(signature 제외 필드 전체)에 대한 v1.2 signature 블록을 만든다."""
    payload = canonical_payload_bytes(contract)
    digest = sha256_digest(payload)
    signature = private_key.sign(payload)
    return {
        "algorithm": "Ed25519",
        "keyId": key_id,
        "digest": digest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def sign_contract(
    contract: Mapping[str, Any], private_key: Ed25519PrivateKey, key_id: str
) -> dict[str, Any]:
    """``signature`` 필드를 제외한 계약에 v1.2 signature 블록을 부착한 새 dict를 반환."""
    unsigned = {key: value for key, value in contract.items() if key != "signature"}
    return {**unsigned, "signature": build_signature_block(unsigned, private_key, key_id)}


class KeyStatus(StrEnum):
    """Key Registry 항목 상태 (ADR-KSI-002 §5)."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class KeyRecord:
    public_key: Ed25519PublicKey
    status: KeyStatus = KeyStatus.ACTIVE
    not_after: datetime | None = None


class KeyRegistry:
    """``keyId → {public_key, status, not_after}`` (ADR-KSI-002 §5).

    검증기(:func:`verify_contract`)는 이 registry를 주입받는다 — unknown keyId·
    REVOKED·만료 키는 검증 실패다.
    """

    def __init__(self) -> None:
        self._records: dict[str, KeyRecord] = {}

    def register(
        self,
        key_id: str,
        public_key: Ed25519PublicKey,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        not_after: datetime | None = None,
    ) -> None:
        """신규 keyId 만 등록한다 — 중복 등록은 거부(감사 #9).

        설정·DB 재적재 패턴에서 같은 keyId 를 조용히 덮어쓰면 REVOKED 가 ACTIVE 로
        부활한다(유출 키 재유효화, INV-011 우회). 상태 변경은 :meth:`revoke` 의
        단조 방향뿐이며, ACTIVE 로의 복귀 API 는 의도적으로 없다 — 회전은 새
        keyId 발급으로 한다(ADR-KSI-002 회전 ADR 전까지의 fail-closed 기본값).
        """
        if key_id in self._records:
            raise ValueError(
                f"keyId {key_id!r} 는 이미 등록돼 있다 — 덮어쓰기 금지(REVOKED 부활 차단). "
                "폐기는 revoke(), 회전은 새 keyId 로"
            )
        # 같은 공개키의 다른 keyId 등록도 거부한다(자율 재검토 B-1): keyId 는 서명
        # 대상이 아니라서(canonical 은 signature 블록 전체 제외) 쌍둥이 keyId 가
        # 있으면 계약의 signature.keyId 만 바꿔 재서명 없이 revoke·만료를 우회할 수
        # 있다 — 폐기의 진짜 단위는 키 재료다.
        from cryptography.hazmat.primitives import serialization

        new_bytes = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        for existing_id, record in self._records.items():
            existing_bytes = record.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            if existing_bytes == new_bytes:
                raise ValueError(
                    f"동일 공개키가 keyId {existing_id!r} 로 이미 등록돼 있다 — "
                    "쌍둥이 keyId 는 revoke/만료 우회 경로다(회전은 새 키 재료로)"
                )
        if not_after is not None and not_after.tzinfo is None:
            raise ValueError(
                "not_after는 tz-aware(UTC)여야 한다 — naive datetime은 검증 시점 비교에서 "
                "TypeError를 유발해 fail-closed 보장을 깨뜨린다"
            )
        self._records[key_id] = KeyRecord(public_key=public_key, status=status, not_after=not_after)

    def revoke(self, key_id: str) -> None:
        """keyId 를 REVOKED 로 전이한다 — 단조 방향(되돌림 없음, 멱등)."""
        record = self._records.get(key_id)
        if record is None:
            raise ValueError(f"unknown keyId: {key_id!r} — 미등록 키는 폐기할 수 없다")
        self._records[key_id] = KeyRecord(
            public_key=record.public_key, status=KeyStatus.REVOKED, not_after=record.not_after
        )

    def get(self, key_id: str) -> KeyRecord | None:
        return self._records.get(key_id)


class SignatureVerdict(StrEnum):
    """서명 검증 결과 (ADR-KSI-002 §6). ``VALID`` 아니면 계약은 실행 불가(fail-closed).

    ``KEY_EXPIRED``(서명 키 만료)와 ``EXPIRED_CONTRACT``(계약 validity 창 위반)는
    별개 실패다 — 리뷰 반증에서 키 만료가 계약 만료로 오인되던 명명을 분리했다.
    """

    VALID = "VALID"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    REVOKED_KEY = "REVOKED_KEY"
    KEY_EXPIRED = "KEY_EXPIRED"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    EXPIRED_CONTRACT = "EXPIRED_CONTRACT"
    MALFORMED_CONTRACT = "MALFORMED_CONTRACT"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """:func:`verify_contract` 의 typed 결과. 예외를 던지지 않는다(fail-closed)."""

    verdict: SignatureVerdict
    detail: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.verdict is SignatureVerdict.VALID


def _parse_rfc3339(value: Any) -> datetime | None:
    """RFC 3339 date-time을 tz-aware datetime으로 파싱. 실패·naive는 None (fail-closed)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def verify_contract(
    contract: Mapping[str, Any],
    registry: KeyRegistry,
    expected_schema_version: str,
    *,
    now: datetime | None = None,
) -> VerificationResult:
    """계약을 검증해 typed :class:`VerificationResult` 를 반환한다 (ADR-KSI-002 §6).

    실패는 예외가 아니라 verdict로 반환한다 — 호출자는 ``verdict is SignatureVerdict.VALID``
    가 아니면 계약을 실행하지 않는다(fail-closed, INV-011). 예상 밖 예외도 verdict로
    강등된다(외곽 가드). 이 함수는 서명·TTL만 본다 — 구조·범위 적합성은 JSON Schema와
    Pydantic 모델 검증을 **반드시 함께** 실행해야 한다(ADR-KSI-002 §7).

    검증 순서: schemaVersion → signature 블록·필드 → algorithm → 키(존재·폐기·만료)
    → 계약 validity 창 → digest → Ed25519 서명.
    """
    try:
        return _verify_contract_inner(contract, registry, expected_schema_version, now=now)
    except Exception as exc:  # noqa: BLE001 — 어떤 입력도 예외로 fail-open되지 않게 강등
        return VerificationResult(
            SignatureVerdict.MALFORMED_CONTRACT, detail=f"검증 중 예외(fail-closed 강등): {exc!r}"
        )


def _verify_contract_inner(
    contract: Mapping[str, Any],
    registry: KeyRegistry,
    expected_schema_version: str,
    *,
    now: datetime | None = None,
) -> VerificationResult:
    schema_version = contract.get("schemaVersion")
    if schema_version != expected_schema_version:
        return VerificationResult(
            SignatureVerdict.SCHEMA_VERSION_MISMATCH,
            detail=f"expected schemaVersion={expected_schema_version!r}, got {schema_version!r}",
        )

    signature_block = contract.get("signature")
    if not isinstance(signature_block, Mapping):
        return VerificationResult(SignatureVerdict.INVALID_SIGNATURE, detail="signature 블록 없음")

    key_id = signature_block.get("keyId")
    signature_b64 = signature_block.get("signature")
    stated_digest = signature_block.get("digest")
    if not key_id or not signature_b64:
        return VerificationResult(
            SignatureVerdict.INVALID_SIGNATURE, detail="keyId 또는 signature 필드 누락"
        )

    algorithm = signature_block.get("algorithm")
    if algorithm != "Ed25519":
        return VerificationResult(
            SignatureVerdict.INVALID_SIGNATURE,
            detail=f"지원하지 않는 algorithm: {algorithm!r} (Ed25519만 허용)",
        )

    record = registry.get(key_id)
    if record is None:
        return VerificationResult(SignatureVerdict.UNKNOWN_KEY, detail=f"unknown keyId: {key_id}")

    if record.status is KeyStatus.REVOKED:
        return VerificationResult(SignatureVerdict.REVOKED_KEY, detail=f"revoked keyId: {key_id}")

    check_time = now if now is not None else datetime.now(UTC)
    if check_time.tzinfo is None:
        return VerificationResult(
            SignatureVerdict.MALFORMED_CONTRACT, detail="now는 tz-aware여야 한다"
        )
    if record.not_after is not None and check_time > record.not_after:
        return VerificationResult(
            SignatureVerdict.KEY_EXPIRED,
            detail=f"key expired: not_after={record.not_after.isoformat()}",
        )

    # 계약 자체의 TTL(validity 창) 검증 — INV-011 "TTL 만료 계약 거부" (리뷰 P0 반영)
    validity = contract.get("validity")
    if not isinstance(validity, Mapping):
        return VerificationResult(
            SignatureVerdict.MALFORMED_CONTRACT, detail="validity 블록 없음"
        )
    not_before = _parse_rfc3339(validity.get("notBefore"))
    not_after = _parse_rfc3339(validity.get("notAfter"))
    if not_before is None or not_after is None:
        return VerificationResult(
            SignatureVerdict.MALFORMED_CONTRACT,
            detail="validity.notBefore/notAfter가 tz-aware RFC3339가 아님",
        )
    if check_time < not_before or check_time > not_after:
        return VerificationResult(
            SignatureVerdict.EXPIRED_CONTRACT,
            detail=(
                f"계약 validity 창 밖: now={check_time.isoformat()}, "
                f"notBefore={not_before.isoformat()}, notAfter={not_after.isoformat()}"
            ),
        )

    payload = canonical_payload_bytes(contract)
    computed_digest = sha256_digest(payload)
    if stated_digest != computed_digest:
        return VerificationResult(
            SignatureVerdict.DIGEST_MISMATCH,
            detail=f"expected digest={computed_digest!r}, got {stated_digest!r}",
        )

    try:
        signature_bytes = base64.b64decode(signature_b64)
        record.public_key.verify(signature_bytes, payload)
    except (InvalidSignature, ValueError) as exc:
        return VerificationResult(SignatureVerdict.INVALID_SIGNATURE, detail=str(exc))

    return VerificationResult(SignatureVerdict.VALID)


@dataclass(frozen=True, slots=True)
class LoadedContract:
    """:func:`load_verified_contract` 의 typed 결과 — VALID 일 때만 model 이 있다."""

    verdict: SignatureVerdict
    model: Any | None = None
    detail: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.verdict is SignatureVerdict.VALID and self.model is not None


def load_verified_contract(
    data: Mapping[str, Any],
    registry: KeyRegistry,
    *,
    now: datetime | None = None,
) -> LoadedContract:
    """구조(Pydantic v1.2/v1.3) + 서명·TTL을 **한 번에** 검증하는 유일한
    공개 진입점 (감사 #12, ADR-KSI-002 §7).

    verify_contract 는 서명·TTL 만 본다 — 소비 측이 그것만 호출하면(자연스러운
    오용) '유효하게 서명된 부적합 계약'이 정책 하한(INV-010/013)을 서명의 권위를
    입은 채 통과한다. 이 함수는 구조 검증(모델 계층 — Pydantic↔JSON Schema 정합은
    mission-contract 왕복 테스트가 상시 고정)과 서명 검증을 묶어, fail-closed 가
    호출자의 기억이 아니라 진입점 자체에 있게 한다. 예외를 던지지 않는다.
    """
    from ksi_mission_contracts.models import parse_mission_contract

    try:
        version = data.get("schemaVersion")
        if version not in ("1.2", "1.3"):
            return LoadedContract(
                SignatureVerdict.SCHEMA_VERSION_MISMATCH,
                detail=f"실행 가능한 Mission Contract 버전이 아니다: {version!r}",
            )
        model = parse_mission_contract(dict(data))
    except Exception as exc:  # noqa: BLE001 — 구조 위반은 typed 로 강등(fail-closed)
        return LoadedContract(
            SignatureVerdict.MALFORMED_CONTRACT, detail=f"구조 검증 실패: {exc}"
        )
    verification = verify_contract(data, registry, version, now=now)
    if not verification.is_valid:
        return LoadedContract(verification.verdict, detail=verification.detail)
    return LoadedContract(SignatureVerdict.VALID, model=model)

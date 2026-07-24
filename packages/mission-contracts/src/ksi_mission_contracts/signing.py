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
import json
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


def canonical_payload_bytes(contract: Mapping[str, Any]) -> bytes:
    """계약 dict의 서명대상 정규화 바이트열 (``signature`` 블록 제외, ADR-KSI-002 §2)."""
    payload = {key: value for key, value in contract.items() if key != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


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
        if not_after is not None and not_after.tzinfo is None:
            raise ValueError(
                "not_after는 tz-aware(UTC)여야 한다 — naive datetime은 검증 시점 비교에서 "
                "TypeError를 유발해 fail-closed 보장을 깨뜨린다"
            )
        self._records[key_id] = KeyRecord(public_key=public_key, status=status, not_after=not_after)

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

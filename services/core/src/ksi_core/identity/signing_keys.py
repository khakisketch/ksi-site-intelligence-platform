"""Mission Contract 서명키 공급 (ADR-KSI-010 §2, ADR-KSI-002 가 비범위로 남긴 자리).

키는 **로컬 파일에서 공급한다** — KMS 는 서명마다 네트워크 왕복이 필요해
오프라인 현장에서 임무를 발급할 수 없게 되고, 그건 제품 전제를 깬다
(ADR-KSI-005 "오프라인이 정상 동작").

## 왜 키 하나가 아니라 키 **세트**인가

회전이 성립하려면 발급용 활성 키 하나와, 이미 발급된 계약을 검증할 이전 키들이
함께 있어야 한다. 서버가 사라져도 로컬에서 유효한 계약이 살아있는 게 이 제품의
설계라(server loss must not invalidate a locally valid Mission Contract), 회전
직후에 이전 키로 서명된 계약이 기체에 남아 있는 것은 정상 상태다.

**발급은 항상 활성 키 하나로만 한다.** 여러 키로 동시에 발급하면 어느 것이
정본인지 잃는다.

## 디렉터리 배치

    <keys-dir>/
      keys.json                 # 매니페스트(아래 형식)
      <keyId>.private.pem       # 활성 키만 필요
      <keyId>.public.pem        # 전부

    {
      "active": "core-2026-08",
      "keys": [
        {"keyId": "core-2026-08", "status": "ACTIVE"},
        {"keyId": "core-2026-02", "status": "ACTIVE", "notAfter": "2026-09-01T00:00:00Z"},
        {"keyId": "core-2025-11", "status": "REVOKED"}
      ]
    }

폐기(REVOKED)는 발급 중단이 아니라 **검증 거부**다 — 이미 발급된 계약을 무효로
만드는 유일한 장치이므로, 그 의미를 여기서 흐리지 않는다.
"""

from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from ksi_mission_contracts.signing import KeyRegistry, KeyStatus

# 개인키 파일에 이 비트가 하나라도 서 있으면 거부한다 — 그룹·타인 읽기 권한.
_TOO_OPEN = stat.S_IRWXG | stat.S_IRWXO


class SigningKeyError(Exception):
    """키 세트를 신뢰할 수 없다 — 조립을 거부한다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class SigningKeySet:
    """발급용 활성 키 + 검증용 registry.

    ``registry`` 에는 활성 키와 이전 키가 **모두** 들어 있다 — 검증은 과거를
    포함해야 하고, 발급은 ``active_key_id`` 하나만 쓴다.
    """

    active_key_id: str
    active_private_key: Ed25519PrivateKey
    registry: KeyRegistry


def _load_public(path: Path, raw: bytes | None = None) -> Ed25519PublicKey:
    try:
        loaded = serialization.load_pem_public_key(path.read_bytes() if raw is None else raw)
    except (OSError, ValueError) as exc:
        raise SigningKeyError(f"{path}: 공개키를 읽을 수 없다 — {type(exc).__name__}") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise SigningKeyError(f"{path}: Ed25519 공개키가 아니다 — {type(loaded).__name__}")
    return loaded


def _load_private(path: Path, raw: bytes | None = None) -> Ed25519PrivateKey:
    try:
        # A supplied immutable snapshot was already checked by its filesystem owner.
        mode = path.stat().st_mode if raw is None else 0o600
    except OSError as exc:
        raise SigningKeyError(
            f"{path}: 개인키 파일에 접근할 수 없다 — {type(exc).__name__}"
        ) from exc
    if mode & _TOO_OPEN:
        # 파일 공급을 택한 이상 파일 권한이 유일한 보호막이다 — 느슨하면 거부한다.
        # 여기서 조용히 넘어가면 "키는 파일에 있고 아무나 읽을 수 있다"가 된다.
        raise SigningKeyError(
            f"{path}: 개인키 권한이 너무 열려 있다(mode {mode & 0o777:o}) — 0600 이어야 한다"
        )
    try:
        loaded = serialization.load_pem_private_key(
            path.read_bytes() if raw is None else raw, password=None
        )
    except (OSError, ValueError, TypeError) as exc:
        raise SigningKeyError(f"{path}: 개인키를 읽을 수 없다 — {type(exc).__name__}") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise SigningKeyError(f"{path}: Ed25519 개인키가 아니다 — {type(loaded).__name__}")
    return loaded


def load_signing_keys(
    keys_dir: Path, *, verified_files: Mapping[str, bytes] | None = None
) -> SigningKeySet:
    """매니페스트를 읽어 키 세트를 만든다 — 신뢰할 수 없으면 기동을 거부한다.

    거부 사유는 전부 "조용히 넘어가면 서명 신뢰가 무너지는" 것들이다:
    활성 키가 REVOKED / 활성 키가 매니페스트에 없음 / 개인키 권한 노출 /
    공개키와 개인키 불일치(다른 키로 서명하고 다른 키로 검증하게 된다).

    ``verified_files`` consumes only already permission-checked immutable bytes.
    The caller owns filesystem/identity validation; no path is reopened in this
    mode. Ordinary production loading retains its existing permission checks.
    """
    if verified_files is not None:
        verified_files = dict(verified_files)
        if any(
            not isinstance(name, str) or not isinstance(raw, bytes)
            for name, raw in verified_files.items()
        ):
            raise SigningKeyError("verified signing snapshot requires string names and bytes")
    manifest_path = keys_dir / "keys.json"
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
            if verified_files is None else verified_files["keys.json"].decode("utf-8")
        )
    except (OSError, ValueError, KeyError) as exc:
        raise SigningKeyError(
            f"{manifest_path}: 키 매니페스트를 읽을 수 없다 — {type(exc).__name__}"
        ) from exc
    if not isinstance(manifest, dict):
        raise SigningKeyError(f"{manifest_path}: 매니페스트는 object 여야 한다")

    active_id = manifest.get("active")
    entries = manifest.get("keys")
    if not isinstance(active_id, str) or not active_id:
        raise SigningKeyError(f"{manifest_path}: active 키 id 가 없다")
    if not isinstance(entries, list) or not entries:
        raise SigningKeyError(f"{manifest_path}: keys 배열이 비어 있다")

    registry = KeyRegistry()
    active_public: Ed25519PublicKey | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise SigningKeyError(f"{manifest_path}: keys 항목은 object 여야 한다")
        key_id = entry.get("keyId")
        if not isinstance(key_id, str) or not key_id:
            raise SigningKeyError(f"{manifest_path}: keyId 가 없는 항목이 있다")
        raw_status = entry.get("status", KeyStatus.ACTIVE.value)
        try:
            status = KeyStatus(raw_status)
        except ValueError as exc:
            raise SigningKeyError(f"{manifest_path}: 알 수 없는 status — {raw_status!r}") from exc
        not_after_raw = entry.get("notAfter")
        not_after: datetime | None = None
        if not_after_raw is not None:
            if not isinstance(not_after_raw, str):
                raise SigningKeyError(f"{manifest_path}: notAfter 는 ISO 문자열이어야 한다")
            try:
                not_after = datetime.fromisoformat(not_after_raw)
            except ValueError as exc:
                raise SigningKeyError(
                    f"{manifest_path}: notAfter 를 파싱할 수 없다 — {not_after_raw!r}"
                ) from exc
            if not_after.tzinfo is None:
                raise SigningKeyError(f"{manifest_path}: notAfter 는 tz-aware 여야 한다")

        public_name = f"{key_id}.public.pem"
        if verified_files is not None and public_name not in verified_files:
            raise SigningKeyError("verified signing snapshot omits a public key")
        public_key = _load_public(
            keys_dir / public_name,
            None if verified_files is None else verified_files[public_name],
        )
        # KeyRegistry.register 가 중복 keyId·중복 키재료를 이미 거부한다(감사 #9·B-1).
        registry.register(key_id, public_key, status=status, not_after=not_after)
        if key_id == active_id:
            if status is KeyStatus.REVOKED:
                raise SigningKeyError(
                    f"활성 키 {active_id!r} 가 REVOKED 다 — 폐기된 키로 발급하지 않는다"
                )
            active_public = public_key

    if active_public is None:
        raise SigningKeyError(f"{manifest_path}: active 키 {active_id!r} 가 keys 에 없다")

    private_name = f"{active_id}.private.pem"
    if verified_files is not None and private_name not in verified_files:
        raise SigningKeyError("verified signing snapshot omits the active private key")
    private_key = _load_private(
        keys_dir / private_name,
        None if verified_files is None else verified_files[private_name],
    )
    derived = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    declared = active_public.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if derived != declared:
        # 이걸 놓치면 서명은 A 키로 하고 검증은 B 키로 하게 된다 — 발급한 계약이
        # 전부 검증 실패하는데, 그 사실이 발급 시점에는 드러나지 않는다.
        raise SigningKeyError(
            f"활성 키 {active_id!r} 의 개인키와 매니페스트 공개키가 일치하지 않는다"
        )

    return SigningKeySet(
        active_key_id=active_id, active_private_key=private_key, registry=registry
    )


__all__ = ["SigningKeyError", "SigningKeySet", "load_signing_keys"]

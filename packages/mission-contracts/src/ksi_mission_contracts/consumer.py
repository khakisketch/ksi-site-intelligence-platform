"""Mission Contract 실행 소비자 경계 (INV-011).

Core 발급기가 서명했다는 사실만으로 Edge 실행을 허용하지 않는다. 이 모듈은
후보 계약을 구조(Pydantic v1.2)·Ed25519 서명·키 상태·TTL까지
:func:`load_verified_contract` 하나로 검증한 뒤, ``VALID``인 경우에만 로컬 활성
계약을 원자적으로 교체한다.

검증 실패 후보는 기존 활성 계약을 건드리지 않는다. 서버 단절이나 잘못된 후행
배포가 로컬에서 아직 유효한 Mission Contract를 무효화하지 않아야 한다는 제어
경계를 파일 교체 규칙 자체로 강제한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ksi_mission_contracts.signing import (
    KeyRegistry,
    KeyStatus,
    LoadedContract,
    SignatureVerdict,
    canonical_payload_bytes,
    load_verified_contract,
    sha256_digest,
)

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_CONTRACT_BYTES = 1024 * 1024
_ACTIVE_FILENAME = "active-contract.json"


class VerificationKeyError(RuntimeError):
    """공개키 레지스트리를 신뢰할 수 없어 소비자 기동을 거부한다."""


class ContractInputError(RuntimeError):
    """후보·활성 계약 파일이 안전하게 읽을 수 있는 JSON object가 아니다."""


@dataclass(frozen=True, slots=True)
class ActivationReceipt:
    """후보 활성화 판정. ``activated=False``면 활성 파일은 변경되지 않았다."""

    verdict: SignatureVerdict
    activated: bool
    mission_id: str | None = None
    contract_digest: str | None = None
    active_path: Path | None = None
    detail: str | None = None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복 JSON key: {key!r}")
        result[key] = value
    return result


def _read_bounded(path: Path, *, limit: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
        if size <= 0 or size > limit:
            raise ContractInputError(f"{label} 크기가 1..{limit} bytes 범위 밖이다")
        raw = path.read_bytes()
        # stat과 read 사이에 파일이 교체·증가해도 상한을 우회하지 못한다.
        if not raw or len(raw) > limit:
            raise ContractInputError(f"{label} 크기가 1..{limit} bytes 범위 밖이다")
        return raw
    except ContractInputError:
        raise
    except OSError as exc:
        raise ContractInputError(f"{label}을 읽을 수 없다: {type(exc).__name__}") from exc


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContractInputError(f"{label}이 유효한 중복 없는 UTF-8 JSON이 아니다") from exc
    if not isinstance(decoded, dict):
        raise ContractInputError(f"{label} 최상위 값은 JSON object여야 한다")
    return decoded


def _parse_not_after(raw: Any, *, manifest_path: Path) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise VerificationKeyError(f"{manifest_path}: notAfter는 문자열이어야 한다")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationKeyError(f"{manifest_path}: notAfter를 파싱할 수 없다") from exc
    if parsed.tzinfo is None:
        raise VerificationKeyError(f"{manifest_path}: notAfter는 tz-aware여야 한다")
    return parsed


def load_verification_keys(keys_dir: Path) -> KeyRegistry:
    """``keys.json``과 공개키만 읽어 Edge 검증 레지스트리를 만든다.

    개인키는 읽지도 요구하지도 않는다. Edge 소비자에 발급 권한이 섞이면 장비
    침해가 Core 서명권 침해로 곧바로 확대되기 때문이다.
    """
    manifest_path = keys_dir / "keys.json"
    try:
        raw = _read_bounded(
            manifest_path,
            limit=_MAX_MANIFEST_BYTES,
            label="검증키 매니페스트",
        )
        manifest = _parse_json_object(raw, label="검증키 매니페스트")
    except ContractInputError as exc:
        raise VerificationKeyError(f"{manifest_path}: {exc}") from exc
    entries = manifest.get("keys")
    if not isinstance(entries, list) or not entries:
        raise VerificationKeyError(f"{manifest_path}: keys 배열이 비어 있다")

    registry = KeyRegistry()
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerificationKeyError(f"{manifest_path}: keys 항목은 object여야 한다")
        key_id = entry.get("keyId")
        if not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None:
            raise VerificationKeyError(f"{manifest_path}: 경로-안전하지 않은 keyId {key_id!r}")
        try:
            status = KeyStatus(entry.get("status", KeyStatus.ACTIVE.value))
        except ValueError as exc:
            raise VerificationKeyError(f"{manifest_path}: 알 수 없는 key status") from exc
        public_path = keys_dir / f"{key_id}.public.pem"
        try:
            loaded = serialization.load_pem_public_key(public_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise VerificationKeyError(
                f"{public_path}: 공개키를 읽을 수 없다 — {type(exc).__name__}"
            ) from exc
        if not isinstance(loaded, Ed25519PublicKey):
            raise VerificationKeyError(f"{public_path}: Ed25519 공개키가 아니다")
        try:
            registry.register(
                key_id,
                loaded,
                status=status,
                not_after=_parse_not_after(entry.get("notAfter"), manifest_path=manifest_path),
            )
        except ValueError as exc:
            raise VerificationKeyError(f"{manifest_path}: {exc}") from exc
    return registry


class MissionContractConsumer:
    """검증된 계약만 로컬 실행 상태로 활성화하는 생산 소비자."""

    def __init__(self, *, registry: KeyRegistry, state_dir: Path) -> None:
        self._registry = registry
        self._state_dir = state_dir
        self._active_path = state_dir / _ACTIVE_FILENAME

    @property
    def active_path(self) -> Path:
        return self._active_path

    def activate_file(
        self,
        candidate_path: Path,
        *,
        now: datetime | None = None,
    ) -> ActivationReceipt:
        """후보를 검증하고 VALID일 때만 활성 계약 파일을 원자적으로 교체한다."""
        raw = _read_bounded(
            candidate_path,
            limit=_MAX_CONTRACT_BYTES,
            label="Mission Contract 후보",
        )
        data = _parse_json_object(raw, label="Mission Contract 후보")
        loaded = load_verified_contract(data, self._registry, now=now)
        if not loaded.is_valid:
            return ActivationReceipt(
                verdict=loaded.verdict,
                activated=False,
                detail=loaded.detail,
            )

        model = loaded.model
        assert model is not None  # noqa: S101 -- is_valid가 model 존재까지 보장한다.
        mission_id = model.mission_id
        digest = sha256_digest(canonical_payload_bytes(data))
        self._write_active_atomically(raw)
        return ActivationReceipt(
            verdict=SignatureVerdict.VALID,
            activated=True,
            mission_id=mission_id,
            contract_digest=digest,
            active_path=self._active_path,
        )

    def load_active(self, *, now: datetime | None = None) -> LoadedContract:
        """활성 계약도 매 사용 시점에 키 상태·TTL까지 다시 검증한다."""
        # 상태 디렉터리 신뢰 실패는 계약 내용 판정이 아니라 소비자 구성/I/O
        # 오류다. CLI가 이를 exit 3으로 구분할 수 있도록 예외를 보존한다.
        self._ensure_trusted_state_dir(create=False)
        try:
            raw = _read_bounded(
                self._active_path,
                limit=_MAX_CONTRACT_BYTES,
                label="활성 Mission Contract",
            )
            data = _parse_json_object(raw, label="활성 Mission Contract")
        except ContractInputError as exc:
            return LoadedContract(SignatureVerdict.MALFORMED_CONTRACT, detail=str(exc))
        return load_verified_contract(data, self._registry, now=now)

    def _ensure_trusted_state_dir(self, *, create: bool) -> None:
        """로컬 활성 상태가 현재 사용자만 쓸 수 있는 디렉터리에 있음을 보장한다."""
        if create:
            try:
                self._state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                raise ContractInputError(
                    f"Mission Contract 상태 디렉터리를 만들 수 없다: {type(exc).__name__}"
                ) from exc

        try:
            directory_stat = self._state_dir.lstat()
        except OSError as exc:
            raise ContractInputError(
                f"Mission Contract 상태 디렉터리를 검사할 수 없다: {type(exc).__name__}"
            ) from exc

        if stat.S_ISLNK(directory_stat.st_mode):
            raise ContractInputError("Mission Contract 상태 디렉터리가 symlink라 사용을 거부한다")
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ContractInputError("Mission Contract 상태 경로가 디렉터리가 아니다")
        if directory_stat.st_uid != os.geteuid():
            raise ContractInputError("Mission Contract 상태 디렉터리 소유자가 현재 사용자와 다르다")
        if stat.S_IMODE(directory_stat.st_mode) & 0o077:
            raise ContractInputError(
                "Mission Contract 상태 디렉터리 권한은 group/other 접근이 없어야 한다"
            )

    def _write_active_atomically(self, raw: bytes) -> None:
        self._ensure_trusted_state_dir(create=True)
        if self._active_path.is_symlink():
            raise ContractInputError("활성 Mission Contract 경로가 symlink라 교체를 거부한다")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._state_dir,
                prefix=".active-contract.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                os.chmod(stream.name, 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self._active_path)
            directory_fd = os.open(self._state_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise ContractInputError(
                f"활성 Mission Contract를 원자적으로 저장할 수 없다: {type(exc).__name__}"
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def _parse_cli_time(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now는 tz-aware RFC3339여야 한다")
    return parsed


def _receipt_wire(receipt: ActivationReceipt) -> dict[str, Any]:
    return {
        "verdict": receipt.verdict.value,
        "activated": receipt.activated,
        "missionId": receipt.mission_id,
        "contractDigest": receipt.contract_digest,
        "activePath": str(receipt.active_path) if receipt.active_path is not None else None,
        "detail": receipt.detail,
    }


def main(argv: list[str] | None = None) -> int:
    """``ksi-mission-contract-consumer`` 생산 CLI."""
    parser = argparse.ArgumentParser(description="Verify and activate Mission Contract v1.2")
    parser.add_argument("--keys-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--now", help="검증 시각(RFC3339, 테스트/HIL 재현용)")
    commands = parser.add_subparsers(dest="command", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("contract", type=Path)
    commands.add_parser("status")
    args = parser.parse_args(argv)

    try:
        now = _parse_cli_time(args.now)
        registry = load_verification_keys(args.keys_dir)
        consumer = MissionContractConsumer(registry=registry, state_dir=args.state_dir)
        if args.command == "activate":
            receipt = consumer.activate_file(args.contract, now=now)
            print(json.dumps(_receipt_wire(receipt), ensure_ascii=False, sort_keys=True))
            return 0 if receipt.activated else 2
        loaded = consumer.load_active(now=now)
        model = loaded.model
        payload = {
            "verdict": loaded.verdict.value,
            "missionId": model.mission_id if loaded.is_valid and model is not None else None,
            "detail": loaded.detail,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if loaded.is_valid else 2
    except (ContractInputError, VerificationKeyError, ValueError) as exc:
        print(
            json.dumps(
                {"verdict": "CONSUMER_ERROR", "detail": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ActivationReceipt",
    "ContractInputError",
    "MissionContractConsumer",
    "VerificationKeyError",
    "load_verification_keys",
    "main",
]

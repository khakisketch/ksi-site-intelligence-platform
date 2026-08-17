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
from enum import StrEnum
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


class ActivationRefusal(StrEnum):
    """서명은 유효하지만 **소비자 계층**이 활성화를 거부한 이유.

    :class:`SignatureVerdict` 와 섞지 않는다 — 저쪽은 "이 계약이 Core가 서명한
    진짜인가"의 답이고, 이쪽은 "진짜이긴 한데 지금 이 기체에 실어도 되는가"의
    답이다. 서명 검증기는 후자를 알 수 없다(자기보다 나중에 발급된 계약의 존재를
    모른다).
    """

    SUPERSEDED_CONTRACT = "SUPERSEDED_CONTRACT"


ActivationVerdict = SignatureVerdict | ActivationRefusal


@dataclass(frozen=True, slots=True)
class ActivationReceipt:
    """후보 활성화 판정. ``activated=False``면 활성 파일은 변경되지 않았다."""

    verdict: ActivationVerdict
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
    except RecursionError as exc:
        # CPython 의 json 디코더는 재귀식이라 깊게 중첩된 배열/객체는 크기 상한
        # 안에서도 RecursionError 를 던진다. RuntimeError 계열이라 위 except 에
        # 걸리지 않아, 잡지 않으면 "typed 판정으로 거부한다"는 이 모듈의 계약을
        # 깨고 프로세스가 통째로 죽는다(후보 파일 하나로 크래시 루프 가능).
        raise ContractInputError(f"{label} JSON 중첩이 너무 깊다") from exc
    if not isinstance(decoded, dict):
        raise ContractInputError(f"{label} 최상위 값은 JSON object여야 한다")
    return decoded


def _parse_contract_instant(raw: Any) -> datetime | None:
    """계약 validity 타임스탬프를 tz-aware datetime 으로. 못 읽으면 ``None``.

    모델의 ``field_validator`` 가 이미 tz-aware RFC3339 임을 보장하므로 여기서
    실패하면 비교를 포기한다 — 순서를 모를 때 후보를 막지는 않는다(이 판정은
    서명·TTL 검증을 이미 통과한 계약에만 얹는 추가 방어다).
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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

        superseded = self._superseded_detail(model, digest, now=now)
        if superseded is not None:
            return ActivationReceipt(
                verdict=ActivationRefusal.SUPERSEDED_CONTRACT,
                activated=False,
                mission_id=mission_id,
                contract_digest=digest,
                detail=superseded,
            )

        self._write_active_atomically(raw)
        return ActivationReceipt(
            verdict=SignatureVerdict.VALID,
            activated=True,
            mission_id=mission_id,
            contract_digest=digest,
            active_path=self._active_path,
        )

    def _superseded_detail(
        self,
        candidate: Any,
        candidate_digest: str,
        *,
        now: datetime | None,
    ) -> str | None:
        """이미 활성인 계약을 **순서 근거 없이 교체하려는** 후보면 거부 사유, 아니면 ``None``.

        서명이 유효하고 TTL 안이어도 그것만으로 "지금 실을 계약"이 되지는 않는다.
        Core 가 임무 중 정책을 조여 계약을 재발급하면 이전 계약은 자기 validity 창이
        끝나기 전까지 **여전히 암호학적으로 유효**하다. 그 이전 계약을 다시 밀어넣어
        배터리 예비량·고도 상한 같은 안전 항목을 조용히 되돌리는 rollback 이 실측으로
        재현됐다(2026-08-14 독립 반증: 예비량 40%→10%, 고도 60m→120m 로 무저항 교체).

        계약 스키마(v1.2)에는 발급 순서를 담는 필드(``issuedAt``·``revision``·
        ``supersedes``)가 **없다**. 그래서 여기서는 스키마 변경 없이 쓸 수 있는 유일한
        순서 근거인 ``validity.notBefore`` 의 단조성으로 막는다.

        판정 순서가 중요하다 — **digest 동일성을 먼저** 본다. 같은 계약의 재활성화는
        순서 판정 대상이 아니라 멱등 연산이므로, 순서 비교보다 앞에서 통과시킨다.
        그 다음에야 ``notBefore`` 를 **엄격 부등호**로 비교한다: 후보가 활성 계약보다
        확실히 더 뒤(``>``)일 때만 통과다.

        즉 ``notBefore`` 가 **같은데 내용이 다른** 후보는 거부한다(2026-08-18).
        같으면 어느 쪽이 나중 발급본인지 가릴 근거가 아예 없으니, 통과가 아니라
        거부한다 — 이건 이 커밋의 판단이지 기존 ADR 이 정해 둔 규칙이 아니다.
        이전에는 ``>=`` 라 그 경우가 무저항 통과였다.

        **이 가드의 실제 사정거리(과대평가 금지)**: 현 Core 는 "같은 missionId·다른
        내용" 계약을 애초에 만들지 않는다 — 두 발급 경로 모두 ``record_issuance`` 를
        지나고 같은 ``missionId`` 재사용은 ``MISSION_ID_CONFLICT``(409)로 막힌다. 실제
        정책 조임은 **새 missionId** 로 나가는데, 그 경우 위 ``mission_id`` 불일치
        분기에서 이 함수가 아예 ``None`` 을 반환한다. 그래서 이 규칙이 지금 막는 것은
        "Core 밖에서 조립된 옛 계약 재생"뿐이고, 정상 파이프라인에는 걸리는 트래픽이
        없다. 게다가 활성 계약 파일이 없거나 TTL 이 만료됐으면 위에서 이미 ``None``
        으로 빠져나간다(fail-open 세 곳) — 이 가드만으로 rollback 이 닫혔다고 말할 수
        없다. risk ``mission-contract-no-issuance-ordering-field`` 는 계속 열려 있다.

        **알아둘 것**: 서명키 로테이션은 이 규칙에 걸리지 **않는다** —
        ``canonical_payload_bytes`` 가 ``signature`` 블록을 통째로 제외하므로
        ``keyId`` 가 바뀌어도 digest 는 같고, 위 digest 단축에서 먼저 통과한다.
        "같은 notBefore·다른 digest" 를 실제로 만드는 트리거는 따로 있다:
        ``mission_plans.py`` 의 멱등 재발급(``_regenerate_pair_artifact``)이 원
        ``issued_at`` 을 재사용해 재서명하는 상태에서 서버 고정 안전상수·경로
        생성기가 드리프트하는 경우다(risk ``kmz-regeneration-determinism-timebomb``
        와 같은 사고 클래스). 현재 Edge 배포 경로는 저장된 계약을 그대로 싣고
        재생성본을 쓰지 않아 무해하다.
        """
        if self._active_path.is_symlink() or not self._active_path.exists():
            return None
        try:
            active_raw = _read_bounded(
                self._active_path,
                limit=_MAX_CONTRACT_BYTES,
                label="활성 Mission Contract",
            )
            active_data = _parse_json_object(active_raw, label="활성 Mission Contract")
        except ContractInputError:
            # 활성 계약을 읽을 수 없다 — 되돌릴 대상이 없으니 후보를 막지 않는다.
            return None

        active = load_verified_contract(active_data, self._registry, now=now)
        if not active.is_valid or active.model is None:
            # 활성 계약이 이미 무효(TTL 만료·키 폐기 등)면 되돌림이 아니라 정상 교체다.
            return None
        if active.model.mission_id != candidate.mission_id:
            # 다른 임무의 계약이다 — 순서를 비교할 공통 축이 없다.
            return None

        # 동일 계약 재활성화는 순서 판정 대상이 아니다 — 순서 비교보다 먼저 통과시킨다.
        active_digest = sha256_digest(canonical_payload_bytes(active_data))
        if active_digest == candidate_digest:
            return None

        active_not_before = _parse_contract_instant(active.model.validity.not_before)
        candidate_not_before = _parse_contract_instant(candidate.validity.not_before)
        if active_not_before is None or candidate_not_before is None:
            return None
        # 엄격 부등호 — 확실히 더 뒤인 발급본만 통과한다. 같으면 순서 근거가 없다.
        if candidate_not_before > active_not_before:
            return None

        return (
            "이미 활성인 계약과 같거나 이른 validity.notBefore를 가진 후보다 — "
            "이전 발급본으로 되돌리거나 순서 근거 없이 교체하는 활성화를 거부한다"
        )

    def load_active(self, *, now: datetime | None = None) -> LoadedContract:
        """활성 계약도 매 사용 시점에 키 상태·TTL까지 다시 검증한다."""
        # 상태 디렉터리 신뢰 실패는 계약 내용 판정이 아니라 소비자 구성/I/O
        # 오류다. CLI가 이를 exit 3으로 구분할 수 있도록 예외를 보존한다.
        self._ensure_trusted_state_dir(create=False)
        if self._active_path.is_symlink():
            # 쓰기 경로는 symlink 를 이미 거부한다(_write_active_atomically).
            # 읽기만 따라가면 방어가 비대칭이라 같은 규칙을 적용한다.
            return LoadedContract(
                SignatureVerdict.MALFORMED_CONTRACT,
                detail="활성 Mission Contract 경로가 symlink라 읽기를 거부한다",
            )
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
    "ActivationRefusal",
    "ActivationVerdict",
    "ContractInputError",
    "MissionContractConsumer",
    "VerificationKeyError",
    "load_verification_keys",
    "main",
]

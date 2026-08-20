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
from datetime import UTC, datetime
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
_HIGHWATER_FILENAME = "activation-highwater.json"
_HIGHWATER_SCHEMA_VERSION = "1.0"
_MAX_HIGHWATER_BYTES = 256 * 1024


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


@dataclass(frozen=True, slots=True)
class ContractHighWaterMark:
    """이 임무에 대해 **이미 실었던** 가장 나중 계약."""

    not_before: datetime
    digest: str


@dataclass(frozen=True, slots=True)
class DispatchHighWaterMark:
    """이 기체에 **이미 실었던** 가장 나중 dispatch 봉투."""

    not_before: datetime
    dispatch_id: str
    mission_contract_digest: str
    risk_policy_pack_digest: str
    edge_runtime_profile_digest: str


@dataclass(frozen=True, slots=True)
class IssuanceHighWaterMark:
    """v1.3 ``(issuerId, siteId)`` 축에서 이미 활성화한 가장 큰 순서."""

    site_sequence: int
    digest: str


def _require_instant(raw: Any, *, field: str) -> datetime:
    parsed = _parse_contract_instant(raw)
    if parsed is None:
        raise ContractInputError(f"활성화 고수위 {field}가 tz-aware RFC3339 시각이 아니다")
    return parsed


def _require_text(raw: Any, *, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ContractInputError(f"활성화 고수위 {field}가 비어있지 않은 문자열이 아니다")
    return raw


def _instant_wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_private_atomically(
    path: Path, raw: bytes, *, state_dir: Path, prefix: str, label: str
) -> None:
    if path.is_symlink():
        raise ContractInputError(f"{label} 경로가 symlink라 교체를 거부한다")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=state_dir, prefix=prefix, suffix=".tmp", delete=False
        ) as stream:
            temp_path = Path(stream.name)
            os.chmod(stream.name, 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ContractInputError(
            f"{label} 파일을 원자적으로 저장할 수 없다: {type(exc).__name__}"
        ) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


class ActivationHighWater:
    """활성화된 적 있는 세대를 **활성 파일 바깥에** 남기는 durable 표식.

    ## 왜 별도 파일인가

    rollback 방어(:meth:`MissionContractConsumer._superseded_detail` 와 dispatch
    쪽의 같은 계열 판정)는 지금까지 **활성 파일 자체**를 순서 근거로 썼다. 그래서
    세 갈래로 뚫렸다(2026-08-18 적대적 검증 실측, risk
    ``rollback-guard-fail-open-and-mission-id-laundering``).

    1. 활성 계약의 TTL 이 지나면 비교 없이 통과한다 — 공격자는 **기다리기만** 하면 된다.
    2. 활성 계약 파일을 지우면 비교 대상이 없어 통과한다.
    3. dispatch 스냅샷 파일이 없으면 정책 순서 판정을 통째로 건너뛴다.

    셋 다 원인이 하나다: 순서 근거를 **수명이 짧은 활성 파일이 들고 있었다.** 이
    클래스는 그 근거를 활성 파일의 수명과 분리해 상태 디렉터리에 남긴다. 활성
    계약이 만료돼도, 지워져도, 고수위는 남는다.

    ## 두 축을 따로 기억한다

    계약 축은 **임무별**이다. 계약의 ``validity.notBefore`` 가 서버 발급 시각이라는
    보장이 없기 때문이다(예약 임무면 창의 시작일 수 있다) — 서로 다른 임무 사이의
    순서 근거로 쓰면 정상 임무를 거부할 수 있다.

    봉투 축은 **기체 전체 하나**다. dispatch 봉투의 ``validity.notBefore`` 는
    서버가 dispatch 를 내보내는 순간 각인한다(``edge_dispatch.py``). 그래서 임무가
    달라도 순서를 비교할 수 있고, 바로 그 점이 "새 missionId 로 세탁하면 가드가
    아예 안 돈다"는 구멍을 닫는다.

    ## 막지 못하는 것 (과대평가 금지)

    고수위 파일 **자체를 지우면** 다시 뚫린다. 상태 디렉터리에 쓸 수 있는 침입자를
    로컬 파일 하나로 막을 수는 없다 — 그건 TPM 같은 단조 카운터의 일이다. 여기서
    실제로 닫히는 것은 **권한이 필요 없는 경로**(TTL 만료를 기다리기)이고, 나머지
    두 갈래는 "파일을 하나 더 지워야 한다"로 비용이 오른다.

    파일이 **읽히지만 망가져 있으면** 활성화를 거부한다(fail-closed). 조용히 빈
    고수위로 되돌아가면 "망가뜨리기"가 그대로 우회 수단이 되기 때문이다.
    """

    def __init__(self, *, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._path = state_dir / _HIGHWATER_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def contract_mark(self, mission_id: str) -> ContractHighWaterMark | None:
        record = self._load().get("contracts", {}).get(mission_id)
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ContractInputError("활성화 고수위 contracts 항목이 object가 아니다")
        return ContractHighWaterMark(
            not_before=_require_instant(record.get("notBefore"), field="contracts[].notBefore"),
            digest=_require_text(record.get("digest"), field="contracts[].digest"),
        )

    def issuance_mark(self, *, issuer_id: str, site_id: str) -> IssuanceHighWaterMark | None:
        issuers = self._load().get("issuance", {})
        issuer = issuers.get(issuer_id)
        if issuer is None:
            return None
        if not isinstance(issuer, dict):
            raise ContractInputError("활성화 고수위 issuance issuer 항목이 object가 아니다")
        record = issuer.get(site_id)
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ContractInputError("활성화 고수위 issuance site 항목이 object가 아니다")
        sequence = record.get("siteSequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ContractInputError("활성화 고수위 issuance.siteSequence가 양의 정수가 아니다")
        return IssuanceHighWaterMark(
            site_sequence=sequence,
            digest=_require_text(record.get("digest"), field="issuance[].digest"),
        )

    def has_issuance_for_site(self, site_id: str) -> bool:
        """issuer를 표현할 수 없는 v1.2 downgrade 판정용 보수적 site 조회."""
        issuers = self._load().get("issuance", {})
        for issuer in issuers.values():
            if not isinstance(issuer, dict):
                raise ContractInputError("활성화 고수위 issuance issuer 항목이 object가 아니다")
            if site_id in issuer:
                return True
        return False

    def dispatch_mark(self) -> DispatchHighWaterMark | None:
        record = self._load().get("dispatch")
        if record is None:
            return None
        return DispatchHighWaterMark(
            not_before=_require_instant(record.get("notBefore"), field="dispatch.notBefore"),
            dispatch_id=_require_text(record.get("dispatchId"), field="dispatch.dispatchId"),
            mission_contract_digest=_require_text(
                record.get("missionContractDigest"), field="dispatch.missionContractDigest"
            ),
            risk_policy_pack_digest=_require_text(
                record.get("riskPolicyPackDigest"), field="dispatch.riskPolicyPackDigest"
            ),
            edge_runtime_profile_digest=_require_text(
                record.get("edgeRuntimeProfileDigest"),
                field="dispatch.edgeRuntimeProfileDigest",
            ),
        )

    def record_contract(self, *, mission_id: str, not_before: datetime, digest: str) -> None:
        """이 임무의 고수위를 올린다 — **내리지는 않는다.**"""
        state = self._load()
        contracts = dict(state.get("contracts", {}))
        existing = contracts.get(mission_id)
        if isinstance(existing, dict):
            previous = _require_instant(existing.get("notBefore"), field="contracts[].notBefore")
            if previous > not_before:
                return
        contracts[mission_id] = {"notBefore": _instant_wire(not_before), "digest": digest}
        state["contracts"] = contracts
        self._store(state)

    def record_issuance(
        self,
        *,
        issuer_id: str,
        site_id: str,
        site_sequence: int,
        digest: str,
    ) -> None:
        """v1.3 순서 고수위를 올린다. 낮은 순서나 같은 순서의 변조는 쓰지 않는다."""
        if site_sequence <= 0:
            raise ContractInputError("siteSequence는 양의 정수여야 한다")
        state = self._load()
        issuers = dict(state.get("issuance", {}))
        sites = dict(issuers.get(issuer_id, {}))
        existing = sites.get(site_id)
        if isinstance(existing, dict):
            previous = existing.get("siteSequence")
            previous_digest = existing.get("digest")
            if not isinstance(previous, int) or isinstance(previous, bool) or previous <= 0:
                raise ContractInputError("활성화 고수위 issuance.siteSequence가 양의 정수가 아니다")
            if site_sequence < previous:
                return
            if site_sequence == previous:
                if previous_digest != digest:
                    raise ContractInputError(
                        "같은 v1.3 siteSequence에 다른 계약 digest를 기록할 수 없다"
                    )
                return
        sites[site_id] = {"siteSequence": site_sequence, "digest": digest}
        issuers[issuer_id] = sites
        state["issuance"] = issuers
        self._store(state)

    def record_dispatch(
        self,
        *,
        not_before: datetime,
        dispatch_id: str,
        mission_contract_digest: str,
        risk_policy_pack_digest: str,
        edge_runtime_profile_digest: str,
    ) -> None:
        """기체 전체 봉투 고수위를 올린다 — **내리지는 않는다.**"""
        state = self._load()
        existing = state.get("dispatch")
        if isinstance(existing, dict):
            previous = _require_instant(existing.get("notBefore"), field="dispatch.notBefore")
            if previous > not_before:
                return
        state["dispatch"] = {
            "notBefore": _instant_wire(not_before),
            "dispatchId": dispatch_id,
            "missionContractDigest": mission_contract_digest,
            "riskPolicyPackDigest": risk_policy_pack_digest,
            "edgeRuntimeProfileDigest": edge_runtime_profile_digest,
        }
        self._store(state)

    def _load(self) -> dict[str, Any]:
        if self._path.is_symlink():
            raise ContractInputError("활성화 고수위 파일 경로가 symlink라 사용을 거부한다")
        if not self._path.exists():
            return {"schemaVersion": _HIGHWATER_SCHEMA_VERSION}
        raw = _read_bounded(self._path, limit=_MAX_HIGHWATER_BYTES, label="활성화 고수위")
        state = _parse_json_object(raw, label="활성화 고수위")
        if state.get("schemaVersion") != _HIGHWATER_SCHEMA_VERSION:
            raise ContractInputError("활성화 고수위 파일의 schemaVersion을 모른다")
        if not isinstance(state.get("contracts", {}), dict):
            raise ContractInputError("활성화 고수위 contracts가 object가 아니다")
        issuance = state.get("issuance", {})
        if not isinstance(issuance, dict):
            raise ContractInputError("활성화 고수위 issuance가 object가 아니다")
        dispatch = state.get("dispatch")
        if dispatch is not None and not isinstance(dispatch, dict):
            raise ContractInputError("활성화 고수위 dispatch가 object가 아니다")
        return state

    def _store(self, state: dict[str, Any]) -> None:
        state["schemaVersion"] = _HIGHWATER_SCHEMA_VERSION
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        _write_private_atomically(
            self._path,
            raw,
            state_dir=self._state_dir,
            prefix=".activation-highwater.",
            label="활성화 고수위",
        )


class MissionContractConsumer:
    """검증된 계약만 로컬 실행 상태로 활성화하는 생산 소비자."""

    def __init__(self, *, registry: KeyRegistry, state_dir: Path) -> None:
        self._registry = registry
        self._state_dir = state_dir
        self._active_path = state_dir / _ACTIVE_FILENAME
        self._highwater = ActivationHighWater(state_dir=state_dir)

    @property
    def active_path(self) -> Path:
        return self._active_path

    @property
    def highwater(self) -> ActivationHighWater:
        """활성 파일 수명과 분리된 순서 근거 — dispatch 계층도 같은 표식을 쓴다."""
        return self._highwater

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

        # 고수위를 **먼저** 올린다. 여기서 죽으면 표식만 앞서는데, 같은 계약을
        # 다시 실으면 digest 가 같아 멱등 통과다 — 반대 순서(활성 파일 먼저)로
        # 죽으면 실은 적 있는 계약이 표식에 안 남아 되돌림에 다시 뚫린다.
        self._ensure_trusted_state_dir(create=True)
        if model.schema_version == "1.3":
            self._highwater.record_issuance(
                issuer_id=model.issuance.issuer_id,
                site_id=model.site_id,
                site_sequence=model.issuance.site_sequence,
                digest=digest,
            )
        not_before = _parse_contract_instant(model.validity.not_before)
        if not_before is not None:
            self._highwater.record_contract(
                mission_id=mission_id, not_before=not_before, digest=digest
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
        분기에서 이 함수가 아예 ``None`` 을 반환한다. 그래서 **이 활성 파일 비교**가
        막는 것은 "Core 밖에서 조립된 옛 계약 재생"뿐이다.

        2026-08-18 에 축이 더 붙었다. 활성 파일이 없거나 TTL 이 지나 이 비교가
        통째로 건너뛰던 fail-open 은 :meth:`_durable_superseded_detail` 의 고수위
        표식이 닫는다(활성 파일 수명과 분리된 순서 근거). 임무를 갈아 끼우는 세탁은
        이 계층이 아니라 봉투 계층이 기체 전체 고수위로 막는다(``edge_activation``).
        계약 스키마에 발급 순서 필드를 넣는 근본 해법(risk
        ``mission-contract-no-issuance-ordering-field``)은 여전히 열려 있다.

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
        if candidate.schema_version == "1.3":
            mark = self._highwater.issuance_mark(
                issuer_id=candidate.issuance.issuer_id,
                site_id=candidate.site_id,
            )
            if mark is None:
                # 첫 v1.3은 legacy notBefore 축보다 강한 순서 근거를 도입하는 upgrade다.
                return None
            sequence = candidate.issuance.site_sequence
            if sequence == mark.site_sequence and candidate_digest == mark.digest:
                return None
            if sequence > mark.site_sequence:
                return None
            return (
                "이 issuer/site에 이미 같거나 큰 v1.3 siteSequence를 활성화했다 — "
                "낮은 순서 또는 같은 순서의 다른 계약 replay를 거부한다"
            )

        # v1.2에는 issuerId가 없어 어느 issuer의 후속인지 증명할 수 없다. 같은 site에
        # v1.3 고수위가 하나라도 생겼다면 안전 상태를 낮출 수 없도록 보수적으로 막는다.
        if self._highwater.has_issuance_for_site(candidate.site_id):
            return (
                "이 site에 v1.3 발급 순서 고수위가 이미 있다 — issuer 순서를 표현하지 "
                "못하는 v1.2 downgrade 활성화를 거부한다"
            )

        durable = self._durable_superseded_detail(candidate, candidate_digest)
        if durable is not None:
            return durable

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

    def _durable_superseded_detail(self, candidate: Any, candidate_digest: str) -> str | None:
        """활성 파일이 **없거나 만료돼도** 남는 순서 근거로 같은 판정을 한다.

        위 :meth:`_superseded_detail` 의 활성 파일 비교는 두 갈래로 우회됐다(risk
        ``rollback-guard-fail-open-and-mission-id-laundering``): 활성 계약의 TTL 이
        지나기를 **기다리거나**, 활성 파일을 **지우면** 판정 자체가 돌지 않았다.
        고수위 표식은 둘 다에서 살아남는다(:class:`ActivationHighWater`).

        판정 축은 여전히 **임무별**이다 — 계약의 ``notBefore`` 는 서버 발급 시각이라는
        보장이 없어 임무 사이의 순서 근거로 쓸 수 없다. 임무를 갈아 끼우는 세탁은
        봉투 축(``edge_activation``)이 기체 전체 고수위로 막는다.
        """
        mark = self._highwater.contract_mark(candidate.mission_id)
        if mark is None:
            return None
        if mark.digest == candidate_digest:
            # 같은 계약의 재활성화 — 순서 판정 대상이 아니라 멱등 연산이다.
            return None
        candidate_not_before = _parse_contract_instant(candidate.validity.not_before)
        if candidate_not_before is not None and candidate_not_before > mark.not_before:
            return None
        return (
            "이 임무에 이미 실었던 계약과 같거나 이른 validity.notBefore를 가진 후보다 — "
            "활성 계약이 만료되거나 지워져도 되돌림은 거부한다"
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
        _write_private_atomically(
            self._active_path,
            raw,
            state_dir=self._state_dir,
            prefix=".active-contract.",
            label="활성 Mission Contract",
        )


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
    "ActivationHighWater",
    "ActivationReceipt",
    "ActivationRefusal",
    "ActivationVerdict",
    "ContractHighWaterMark",
    "ContractInputError",
    "DispatchHighWaterMark",
    "IssuanceHighWaterMark",
    "MissionContractConsumer",
    "VerificationKeyError",
    "load_verification_keys",
    "main",
]

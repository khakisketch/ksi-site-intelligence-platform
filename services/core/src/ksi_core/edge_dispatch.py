"""Core의 Edge Mission dispatch·activation receipt·장비 소유 evidence 경계.

이 모듈은 기존 Mission Contract v1.2·EventBundle v1.2의 형식을 바꾸지 않는다.
대신 Core가 서명한 ``MissionDispatchEnvelope v1.0``을 durable하게 발급하고,
Edge가 activation 사실을 기록하도록 한다. Edge는 여기서 ``CONFIRMED_EVENT``를
만들 수 없으며, evidence도 자기 장비가 projection한 event에만 붙일 수 있다.
"""

from __future__ import annotations

import copy
import logging
import threading
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from ksi_domain.enums import MissionExecutionStatus, Severity
from ksi_mission_contracts.dispatch import (
    ActivationReceiptV1,
    DispatchValidity,
    MissionDispatchEnvelopeV1,
    build_mission_dispatch_envelope,
)
from ksi_mission_contracts.models import (
    MissionContractV1_2,
    MissionContractV1_3,
    parse_mission_contract,
)
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_wire_dict
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_wire_dict,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.device_attestation import (
    DeviceAttestationRegistry,
    DeviceEvidenceAttestation,
    evidence_attestation_payload,
    verify_device_evidence_attestation,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.events import EventStore
from ksi_core.evidence import (
    DEFAULT_UPLOAD_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorage,
    EvidenceStorageError,
    EvidenceVerdict,
    expires_at,
)
from ksi_core.mission_execution import advance_site_for_dispatch
from ksi_core.mission_records import MissionStore

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.spatial_model import SpatialModelLifecycle

logger = logging.getLogger(__name__)

_NOT_FOUND = "요청한 Edge 리소스를 찾을 수 없다"
_DISPATCH_TTL = timedelta(minutes=5)
# ksi_mission_contracts.dispatch._PATH_SAFE_ID 와 동일 패턴(그 상수는 private라
# 모듈 경계를 넘지 않는다 — 이 파일은 services/core 안에서만 일한다는 작업
# 경계를 지킨다).
_PATH_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


class _BoundDispatchReceipt(Protocol):
    """dispatch envelope에 binding되는 receipt 공통 필드 — activation·flight-start 공용.

    ``ActivationReceiptV1``(ksi_mission_contracts.dispatch)과 이 모듈의
    ``FlightStartReceiptV1``이 구조적으로 이 Protocol을 만족한다.
    ``EdgeDispatchStore._receipt_matches_dispatch``가 두 receipt 종류에 대해
    같은 binding 검증 로직을 재사용하기 위한 것뿐이다 — 새 추상화가 아니다.
    """

    dispatch_id: str
    edge_device_id: str
    mission_id: str
    mission_contract_digest: str
    risk_policy_pack_digest: str


class EdgeDispatchRecoveryError(RuntimeError):
    """dispatch journal이 설명할 수 없는 상태면 Core를 fail-closed로 멈춘다."""


class EdgeDispatchVerdict(StrEnum):
    ISSUED = "ISSUED"
    EXISTING = "EXISTING"
    NO_MISSION = "NO_MISSION"
    NO_RUNTIME_PROFILE = "NO_RUNTIME_PROFILE"
    ACTIVATED = "ACTIVATED"
    ALREADY_ACTIVATED = "ALREADY_ACTIVATED"
    NOT_FOUND = "NOT_FOUND"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    # flight-start-receipts 전용(ADR-KSI-021 §9). activation-receipts의
    # ISSUED/EXISTING·ACTIVATED/ALREADY_ACTIVATED 짝과 같은 자리다 — 이름만
    # 다르다. NOT_ACTIVATED는 그 짝에 없는 새 검사다: activation 사실이 없는
    # 기체가 무엇을 START 했다는 것인지 Core는 설명할 수 없다.
    FLIGHT_START_RECORDED = "FLIGHT_START_RECORDED"
    FLIGHT_START_ALREADY_RECORDED = "FLIGHT_START_ALREADY_RECORDED"
    NOT_ACTIVATED = "NOT_ACTIVATED"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    verdict: EdgeDispatchVerdict
    envelope: dict[str, Any] | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ActivationResult:
    verdict: EdgeDispatchVerdict
    receipt: ActivationReceiptV1 | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class FlightStartResult:
    """flight-start-receipts 접수 판정. ``outcome``은 durable하게 저장된 값과 동일하다."""

    verdict: EdgeDispatchVerdict
    outcome: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ActivatedDispatchEvidenceContext:
    """Signed dispatch lineage captured with a device-attested artifact."""

    dispatch_id: str
    risk_policy_pack_id: str
    risk_policy_pack_digest: str
    calibration_profile_id: str


class FlightStartVerdict(StrEnum):
    """Edge가 ``Action(START)`` 시도 결과로 보고하는 원인(ADR-KSI-021 §5 [0]~[10]).

    ``STARTED``만 ``Action(START)`` 호출까지 실제로 도달했다는 뜻이다. 나머지는
    전부 그 호출 **이전** 관문에서 fail-closed로 멈췄다는 뜻이며(§5의 순서 그대로
    나열했다), Core에 저장되는 ``outcome``에는 ``REFUSED_`` 접두어가 붙는다
    (:func:`_flight_start_outcome`) — §9 "아무도 시도 안 했다와 게이트가 막았다가
    구분되지 않는다"를 막기 위해서다.
    """

    STARTED = "STARTED"
    STAGE_INSUFFICIENT = "STAGE_INSUFFICIENT"
    ACTIVATION_SNAPSHOT_INVALID = "ACTIVATION_SNAPSHOT_INVALID"
    FLIGHT_AUTHORIZATION_INVALID = "FLIGHT_AUTHORIZATION_INVALID"
    ARMING_TOKEN_INVALID = "ARMING_TOKEN_INVALID"
    KMZ_DIGEST_MISMATCH = "KMZ_DIGEST_MISMATCH"
    ENVELOPE_REVALIDATION_FAILED = "ENVELOPE_REVALIDATION_FAILED"
    CONSERVATIVE_CEILING_GUARD = "CONSERVATIVE_CEILING_GUARD"
    SUPERVISOR_NOT_READY = "SUPERVISOR_NOT_READY"
    VEHICLE_PRECONDITION_FAILED = "VEHICLE_PRECONDITION_FAILED"


def _flight_start_outcome(verdict: FlightStartVerdict) -> str:
    """저장·응답에 쓰는 ``outcome`` 문자열 — 거부도 성공과 같은 형식으로 남긴다(§9)."""
    if verdict is FlightStartVerdict.STARTED:
        return verdict.value
    return f"REFUSED_{verdict.value}"


class RiskPolicyPackRegistry:
    """조립 시 주입되는 immutable risk-policy pack 집합.

    policy pack을 mission 요청이 제공하게 두지 않는다. 이 registry에 없는 ID는
    dispatch 대상이 아니며, runtime은 장비별 형상/불확실성 기본값을 추정하지 않는다.
    """

    def __init__(self, packs: Iterable[RiskPolicyPackV1 | Mapping[str, Any]]) -> None:
        self._by_id: dict[str, RiskPolicyPackV1] = {}
        for raw in packs:
            pack = (
                raw if isinstance(raw, RiskPolicyPackV1) else RiskPolicyPackV1.model_validate(raw)
            )
            if pack.risk_policy_pack_id in self._by_id:
                raise ValueError(f"중복 riskPolicyPackId: {pack.risk_policy_pack_id!r}")
            self._by_id[pack.risk_policy_pack_id] = pack

    def get(self, risk_policy_pack_id: str) -> RiskPolicyPackV1 | None:
        return self._by_id.get(risk_policy_pack_id)


class EdgeRuntimeProfileRegistry:
    """조립 시 주입되는 immutable, signed-dispatch 대상 runtime profile 집합.

    Mission Contract v1.2는 model/calibration 식별자만 가진다. Core는 이 registry
    에서 site/model/calibration/site-frame가 하나로 일치하는 profile을 찾아서만
    dispatch에 포함한다. 0개 또는 2개 이상은 선택을 추정하지 않고 fail-closed다.
    """

    def __init__(self, profiles: Iterable[EdgeRuntimeProfileV1 | Mapping[str, Any]]) -> None:
        self._by_id: dict[str, EdgeRuntimeProfileV1] = {}
        for raw in profiles:
            profile = (
                raw
                if isinstance(raw, EdgeRuntimeProfileV1)
                else EdgeRuntimeProfileV1.model_validate(raw)
            )
            if profile.edge_runtime_profile_id in self._by_id:
                raise ValueError(
                    f"중복 edgeRuntimeProfileId: {profile.edge_runtime_profile_id!r}"
                )
            self._by_id[profile.edge_runtime_profile_id] = profile

    def select_for_contract(
        self, contract: MissionContractV1_2 | MissionContractV1_3
    ) -> EdgeRuntimeProfileV1 | None:
        matches = [
            profile
            for profile in self._by_id.values()
            if profile.site_id == contract.site_id
            and profile.model.model_pack_id == contract.artifacts.model_pack_id
            and profile.calibration.calibration_profile_id
            == contract.artifacts.calibration_profile_id
            and profile.calibration.site_frame == contract.site_frame
        ]
        return matches[0] if len(matches) == 1 else None


class EdgeDispatchStore:
    """dispatch/activation append-only projection.

    journal에는 완결된 envelope와 receipt만 남긴다. ``GET next``가 다시 호출돼도
    아직 activation되지 않고 만료되지 않은 동일 envelope를 되돌려 ACK 유실·재시작
    후에도 dispatch ID가 바뀌지 않게 한다.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        risk_policy_packs: RiskPolicyPackRegistry,
        edge_runtime_profiles: EdgeRuntimeProfileRegistry,
        private_key: Ed25519PrivateKey,
        key_id: str,
        dispatch_ttl: timedelta = _DISPATCH_TTL,
    ) -> None:
        if dispatch_ttl <= timedelta(0):
            raise ValueError("dispatch_ttl은 양수여야 한다")
        self._journal = journal
        self._mission_store = mission_store
        self._risk_policy_packs = risk_policy_packs
        self._edge_runtime_profiles = edge_runtime_profiles
        self._private_key = private_key
        self._key_id = key_id
        self._dispatch_ttl = dispatch_ttl
        self._lock = threading.Lock()
        self._dispatches: dict[str, dict[str, Any]] = {}
        self._dispatch_order: list[str] = []
        self._activations: dict[str, dict[str, Any]] = {}
        self._flight_start_receipts: dict[str, dict[str, Any]] = {}
        try:
            self._replay()
        except BaseException:
            journal.close()
            raise

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self) -> None:
        for raw in self._journal.replay():
            try:
                kind = raw["kind"]
                if kind == "dispatch-issued":
                    stored = raw["envelope"]
                    if not isinstance(stored, Mapping):
                        raise ValueError("dispatch journal envelope는 object여야 한다")
                    envelope = MissionDispatchEnvelopeV1.model_validate(stored)
                    dispatch_id = envelope.dispatch_id
                    if dispatch_id in self._dispatches:
                        raise ValueError(f"중복 dispatchId: {dispatch_id!r}")
                    # 모델은 **검증**에 쓰고 보관은 저널에 적힌 원문 그대로 한다.
                    # 모델을 거쳐 다시 덤프하면 그 시점 스키마의 optional 필드가
                    # 새로 생겨(예: v1.0 봉투에 kmzSha256=null) 서명 대상 바이트열이
                    # 바뀌고, 그 봉투는 장비에서 INVALID_DISPATCH_SIGNATURE 가 된다
                    # (dispatch.py 모듈 docstring — missionContract 원문 보존과 같은
                    # 이유). 저널은 append-only 라 이 경로는 과거 발행분 전부를 탄다.
                    self._dispatches[dispatch_id] = copy.deepcopy(dict(stored))
                    self._dispatch_order.append(dispatch_id)
                elif kind == "dispatch-activated":
                    dispatch_id = raw["dispatchId"]
                    if dispatch_id not in self._dispatches:
                        raise ValueError(f"존재하지 않는 dispatch activation: {dispatch_id!r}")
                    if dispatch_id in self._activations:
                        raise ValueError(f"중복 dispatch activation: {dispatch_id!r}")
                    receipt = ActivationReceiptV1.model_validate(raw["receipt"])
                    envelope_raw = self._dispatches[dispatch_id]
                    if not self._receipt_matches_dispatch(receipt, envelope_raw):
                        raise ValueError(f"dispatch activation binding 불일치: {dispatch_id!r}")
                    recorded_at = self._aware_timestamp(
                        raw["ts"], field="dispatch activation journal ts"
                    )
                    if receipt.activated_at > recorded_at:
                        raise ValueError(f"미래 activation receipt: {dispatch_id!r}")
                    receipt_is_valid = self._inside_validity(receipt.activated_at, envelope_raw)
                    recorded_at_is_valid = self._inside_validity(recorded_at, envelope_raw)
                    if not receipt_is_valid or not recorded_at_is_valid:
                        raise ValueError(f"dispatch activation TTL 불일치: {dispatch_id!r}")
                    self._activations[dispatch_id] = receipt.model_dump(by_alias=True, mode="json")
                elif kind == "dispatch-flight-start-reported":
                    dispatch_id = raw["dispatchId"]
                    if dispatch_id not in self._dispatches:
                        raise ValueError(
                            f"존재하지 않는 dispatch flight-start 보고: {dispatch_id!r}"
                        )
                    # activation-receipts 가 먼저 성립해야 한다 — Edge 가 활성화했다고
                    # 보고한 적 없는 계약으로 무엇을 START 했다는 것인지 Core 는 설명할
                    # 수 없다(§9, live 경로 record_flight_start 와 같은 전제).
                    if dispatch_id not in self._activations:
                        raise ValueError(f"activation 이전의 flight-start 보고: {dispatch_id!r}")
                    if dispatch_id in self._flight_start_receipts:
                        raise ValueError(f"중복 dispatch flight-start 보고: {dispatch_id!r}")
                    flight_start_receipt = FlightStartReceiptV1.model_validate(raw["receipt"])
                    envelope_raw = self._dispatches[dispatch_id]
                    if not self._receipt_matches_dispatch(flight_start_receipt, envelope_raw):
                        raise ValueError(f"dispatch flight-start binding 불일치: {dispatch_id!r}")
                    recorded_at = self._aware_timestamp(
                        raw["ts"], field="dispatch flight-start journal ts"
                    )
                    if flight_start_receipt.reported_at > recorded_at:
                        raise ValueError(f"미래 flight-start 보고: {dispatch_id!r}")
                    outcome = _flight_start_outcome(flight_start_receipt.verdict)
                    if raw.get("outcome") != outcome:
                        raise ValueError(f"flight-start outcome 불일치: {dispatch_id!r}")
                    self._flight_start_receipts[dispatch_id] = {
                        "receipt": flight_start_receipt.model_dump(by_alias=True, mode="json"),
                        "outcome": outcome,
                    }
                else:
                    raise ValueError(f"알 수 없는 dispatch journal kind: {kind!r}")
            except (KeyError, TypeError, ValueError) as exc:
                raise EdgeDispatchRecoveryError(f"dispatch journal 재생 실패: {exc}") from exc

    @staticmethod
    def _aware_contract_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Mission Contract validity는 tz-aware여야 한다")
        return parsed

    @staticmethod
    def _aware_timestamp(value: object, *, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field}는 RFC3339 문자열이어야 한다")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"{field}는 tz-aware여야 한다")
        return parsed

    @staticmethod
    def _wire_envelope(envelope: MissionDispatchEnvelopeV1) -> dict[str, Any]:
        return envelope.model_dump(by_alias=True, mode="json")

    @staticmethod
    def _receipt_matches_dispatch(
        receipt: _BoundDispatchReceipt, envelope_raw: Mapping[str, Any]
    ) -> bool:
        return (
            receipt.dispatch_id == envelope_raw.get("dispatchId")
            and receipt.edge_device_id == envelope_raw.get("edgeDeviceId")
            and receipt.mission_id == envelope_raw.get("missionId")
            and receipt.mission_contract_digest == envelope_raw.get("missionContractDigest")
            and receipt.risk_policy_pack_digest == envelope_raw.get("riskPolicyPackDigest")
        )

    @staticmethod
    def _inside_validity(value: datetime, envelope_raw: Mapping[str, Any]) -> bool:
        validity = envelope_raw.get("validity")
        if not isinstance(validity, Mapping):
            return False
        try:
            not_before = datetime.fromisoformat(str(validity["notBefore"]).replace("Z", "+00:00"))
            not_after = datetime.fromisoformat(str(validity["notAfter"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return False
        return (
            not_before.tzinfo is not None
            and not_after.tzinfo is not None
            and not_before <= value <= not_after
        )

    def _existing_unactivated(self, device_id: str, now: datetime) -> dict[str, Any] | None:
        for dispatch_id in self._dispatch_order:
            envelope = self._dispatches[dispatch_id]
            if dispatch_id in self._activations or envelope["edgeDeviceId"] != device_id:
                continue
            if self._inside_validity(now, envelope):
                return copy.deepcopy(envelope)
        return None

    def next_for_device(self, device_id: str, *, now: datetime) -> DispatchResult:
        """해당 장비에 배정된 다음 mission을 durable envelope로 발급한다.

        ``assignedDeviceId=None``은 과거 coverage 경로와 달리 여기서는 dispatch
        권한을 의미하지 않는다. Edge dispatch는 명시적인 1:1 binding 없이는 열지
        않는다(INV-011/012).
        """
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DispatchResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
            existing = self._existing_unactivated(device_id, now)
            if existing is not None:
                return DispatchResult(EdgeDispatchVerdict.EXISTING, envelope=existing)

            for mission in self._mission_store.list():
                if mission.assigned_device_id != device_id:
                    continue
                if any(
                    issued["missionId"] == mission.mission_id and issued_id in self._activations
                    for issued_id, issued in self._dispatches.items()
                ):
                    continue
                try:
                    parsed = parse_mission_contract(mission.contract)
                    if not isinstance(parsed, (MissionContractV1_2, MissionContractV1_3)):
                        raise ValueError("dispatch 불가 Mission Contract 버전")
                    contract = parsed
                    contract_not_before = self._aware_contract_time(contract.validity.not_before)
                    contract_not_after = self._aware_contract_time(contract.validity.not_after)
                except (TypeError, ValueError):
                    logger.error(
                        "mission dispatch 제외: 서명된 계약 구조가 유효하지 않음",
                        exc_info=True,
                    )
                    continue
                pack = self._risk_policy_packs.get(contract.policies.risk_policy_pack_id)
                if pack is None:
                    logger.warning("mission dispatch 제외: 등록되지 않은 risk policy pack")
                    continue
                profile = self._edge_runtime_profiles.select_for_contract(contract)
                if profile is None:
                    # An absent or ambiguous deployment profile must not turn
                    # into a capture/analysis default.  The device observes no
                    # mission from this endpoint until Core configuration is
                    # made explicit and unique.
                    logger.warning("mission dispatch 제외: 일치하는 Edge runtime profile이 없음")
                    continue
                if not (contract_not_before <= now <= contract_not_after):
                    continue
                if not (pack.validity.not_before <= now <= pack.validity.not_after):
                    continue
                if not (profile.validity.not_before <= now <= profile.validity.not_after):
                    continue
                not_after = min(
                    now + self._dispatch_ttl,
                    contract_not_after,
                    pack.validity.not_after,
                    profile.validity.not_after,
                )
                if not_after <= now:
                    continue
                try:
                    envelope = build_mission_dispatch_envelope(
                        dispatch_id=f"dispatch-{uuid.uuid4().hex}",
                        edge_device_id=device_id,
                        mission_contract=mission.contract,
                        risk_policy_pack=risk_policy_pack_wire_dict(pack),
                        edge_runtime_profile=edge_runtime_profile_wire_dict(profile),
                        validity=DispatchValidity(not_before=now, not_after=not_after),
                        private_key=self._private_key,
                        key_id=self._key_id,
                        # 발급 원장의 값을 그대로 싣는다 — 여기서 KMZ 를 다시
                        # 만들거나 해싱하지 않는다(그러면 "발급된 그 파일"이
                        # 아니라 "지금 만들면 나오는 파일"을 보증하게 된다).
                        # 계약 단독 발급이면 None 이고, 그건 "이 임무엔 KMZ 가
                        # 없다"는 확정 사실로 서명 안에 실린다(장비는 그때 남아
                        # 있던 이전 임무의 KMZ 를 지운다).
                        kmz_sha256=mission.kmz_sha256,
                    )
                except (TypeError, ValueError):
                    logger.error(
                        "mission dispatch 제외: 계약·정책 binding이 유효하지 않음",
                        exc_info=True,
                    )
                    continue
                raw_envelope = self._wire_envelope(envelope)
                try:
                    self._journal.append(
                        {
                            "kind": "dispatch-issued",
                            "ts": now.isoformat(),
                            "envelope": raw_envelope,
                        }
                    )
                except JournalSealedError:
                    return DispatchResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
                self._dispatches[envelope.dispatch_id] = raw_envelope
                self._dispatch_order.append(envelope.dispatch_id)
                return DispatchResult(
                    EdgeDispatchVerdict.ISSUED, envelope=copy.deepcopy(raw_envelope)
                )
            return DispatchResult(EdgeDispatchVerdict.NO_MISSION)

    def record_activation(
        self, *, device_id: str, receipt: ActivationReceiptV1, now: datetime
    ) -> ActivationResult:
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ActivationResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
            envelope = self._dispatches.get(receipt.dispatch_id)
            if envelope is None or envelope.get("edgeDeviceId") != device_id:
                return ActivationResult(EdgeDispatchVerdict.NOT_FOUND)
            if receipt.edge_device_id != device_id or not self._receipt_matches_dispatch(
                receipt, envelope
            ):
                return ActivationResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            # `activatedAt` is an auditable assertion by the device, not a
            # scheduling request.  Even an otherwise valid receipt must not
            # let a device durably claim an activation the Core has not yet
            # observed.  Keep the public verdict generic so this does not
            # create a new cross-device or timing oracle.
            if receipt.activated_at > now:
                return ActivationResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            if not self._inside_validity(now, envelope) or not self._inside_validity(
                receipt.activated_at, envelope
            ):
                return ActivationResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            prior = self._activations.get(receipt.dispatch_id)
            receipt_wire = receipt.model_dump(by_alias=True, mode="json")
            if prior is not None:
                if prior == receipt_wire:
                    return ActivationResult(EdgeDispatchVerdict.ALREADY_ACTIVATED, receipt=receipt)
                return ActivationResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            try:
                self._journal.append(
                    {
                        "kind": "dispatch-activated",
                        "ts": now.isoformat(),
                        "dispatchId": receipt.dispatch_id,
                        "receipt": receipt_wire,
                    }
                )
            except JournalSealedError:
                return ActivationResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
            self._activations[receipt.dispatch_id] = receipt_wire
            return ActivationResult(EdgeDispatchVerdict.ACTIVATED, receipt=receipt)

    def flight_start_receipt_of(self, dispatch_id: str) -> dict[str, Any] | None:
        """그 dispatch 의 flight-start 보고 원문(``receipt``·``outcome``) — 없으면 ``None``.

        상태가 아니라 영수증이다(ADR-KSI-021 §9) — ``MissionExecutionStore`` 를
        옮기지 않으므로, 이 접수 사실을 조회할 수 있는 유일한 표면이 이것이다.
        """
        with self._lock:
            stored = self._flight_start_receipts.get(dispatch_id)
            return copy.deepcopy(stored) if stored is not None else None

    def activated_evidence_context(
        self,
        *,
        device_id: str,
        mission_id: str,
        occurred_at: datetime,
    ) -> ActivatedDispatchEvidenceContext | None:
        """Return the activated dispatch that authorized an event occurrence.

        Store-forward may upload after the five-minute dispatch TTL, and the
        activated mission may legitimately run beyond that delivery window.
        The event occurrence is therefore compared to the inner Mission
        Contract validity, not the short dispatch transport validity.
        """

        if occurred_at.tzinfo is None:
            return None
        with self._lock:
            for dispatch_id in reversed(self._dispatch_order):
                if dispatch_id not in self._activations:
                    continue
                envelope = self._dispatches[dispatch_id]
                if (
                    envelope.get("edgeDeviceId") != device_id
                    or envelope.get("missionId") != mission_id
                ):
                    continue
                contract = envelope.get("missionContract")
                contract_validity = (
                    contract.get("validity") if isinstance(contract, Mapping) else None
                )
                if not isinstance(contract_validity, Mapping):
                    return None
                try:
                    contract_not_before = self._aware_contract_time(
                        str(contract_validity["notBefore"])
                    )
                    contract_not_after = self._aware_contract_time(
                        str(contract_validity["notAfter"])
                    )
                except (KeyError, ValueError):
                    return None
                if not (contract_not_before <= occurred_at <= contract_not_after):
                    continue
                pack = envelope.get("riskPolicyPack")
                profile = envelope.get("edgeRuntimeProfile")
                if not isinstance(pack, Mapping) or not isinstance(profile, Mapping):
                    return None
                calibration = profile.get("calibration")
                if not isinstance(calibration, Mapping):
                    return None
                pack_id = pack.get("riskPolicyPackId")
                pack_digest = envelope.get("riskPolicyPackDigest")
                calibration_id = calibration.get("calibrationProfileId")
                if (
                    not isinstance(pack_id, str)
                    or not pack_id
                    or not isinstance(pack_digest, str)
                    or not pack_digest
                    or not isinstance(calibration_id, str)
                    or not calibration_id
                ):
                    return None
                return ActivatedDispatchEvidenceContext(
                    dispatch_id=dispatch_id,
                    risk_policy_pack_id=pack_id,
                    risk_policy_pack_digest=pack_digest,
                    calibration_profile_id=calibration_id,
                )
        return None

    def record_flight_start(
        self, *, device_id: str, receipt: FlightStartReceiptV1, now: datetime
    ) -> FlightStartResult:
        """``POST .../flight-start-receipts`` 의 durable 접수 — ``record_activation`` 과 같은 모양.

        ``MissionExecutionStatus`` 를 전이하지 않는다(ADR-KSI-021 §9) — "Edge 가
        START 를 시도했다고 서명해 보고했다"는 사실에 대응하는 기존 상태가 없고,
        이 receipt 가 그 상태를 새로 만들지 않는다(``IN_FLIGHT`` 는 존재하지
        않는다). 거부(``verdict != STARTED``)도 성공과 **정확히 같은 저장 경로**를
        타므로 "아무도 시도 안 했다"와 "게이트가 막았다"가 저널에서 구분된다.
        """
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return FlightStartResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
            envelope = self._dispatches.get(receipt.dispatch_id)
            if envelope is None or envelope.get("edgeDeviceId") != device_id:
                return FlightStartResult(EdgeDispatchVerdict.NOT_FOUND)
            # activation 사실이 없는 기체가 무엇을 START 했다는 것인지 Core 는
            # 설명할 수 없다 — 순서를 지어내지 않는다(모듈 전역 "값을 지어내지
            # 마라" 원칙의 이 엔드포인트 버전).
            if receipt.dispatch_id not in self._activations:
                return FlightStartResult(EdgeDispatchVerdict.NOT_ACTIVATED)
            if receipt.edge_device_id != device_id or not self._receipt_matches_dispatch(
                receipt, envelope
            ):
                return FlightStartResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            # activation-receipts 와 같은 이유로 미래 시각 주장을 거부한다
            # (record_activation 의 같은 주석 참조) — 새 cross-device·timing
            # oracle 을 만들지 않도록 verdict 는 일반형으로 유지한다.
            if receipt.reported_at > now:
                return FlightStartResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            outcome = _flight_start_outcome(receipt.verdict)
            prior = self._flight_start_receipts.get(receipt.dispatch_id)
            receipt_wire = receipt.model_dump(by_alias=True, mode="json")
            if prior is not None:
                if prior["receipt"] == receipt_wire and prior["outcome"] == outcome:
                    return FlightStartResult(
                        EdgeDispatchVerdict.FLIGHT_START_ALREADY_RECORDED, outcome=outcome
                    )
                return FlightStartResult(EdgeDispatchVerdict.RECEIPT_MISMATCH)
            try:
                self._journal.append(
                    {
                        "kind": "dispatch-flight-start-reported",
                        "ts": now.isoformat(),
                        "dispatchId": receipt.dispatch_id,
                        "outcome": outcome,
                        "receipt": receipt_wire,
                    }
                )
            except JournalSealedError:
                return FlightStartResult(EdgeDispatchVerdict.STORE_UNAVAILABLE)
            self._flight_start_receipts[receipt.dispatch_id] = {
                "receipt": receipt_wire,
                "outcome": outcome,
            }
            return FlightStartResult(EdgeDispatchVerdict.FLIGHT_START_RECORDED, outcome=outcome)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class EdgeEvidenceUploadRequest(CamelModel):
    artifact_id: str
    content_type: str
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attestation: DeviceEvidenceAttestation | None = None


class EdgeEvidenceUploadResponse(CamelModel):
    artifact_id: str
    object_key: str
    upload_url: str
    expires_at: datetime
    reused_registration: bool
    content_digest: str
    # These headers are part of the short-lived capability, not optional client
    # metadata.  The Edge must pass them verbatim to its direct storage PUT.
    required_upload_headers: dict[str, str]
    device_attested: bool
    attestation_key_id: str | None


class ActivationReceiptResponse(CamelModel):
    verdict: EdgeDispatchVerdict
    dispatch_id: str


class FlightStartReceiptV1(CamelModel):
    """Edge가 Core에 기록을 요청하는 ``Action(START)`` 시도 사실 — 확정 event가 아니다.

    ``ActivationReceiptV1``(ksi_mission_contracts.dispatch)과 같은 층위다: "기체가
    날고 있다"는 상태가 아니라 "Edge가 START를 시도했다고 서명해 보고했다"는
    사실이다(ADR-KSI-021 §9). ``verdict``가 ``STARTED``가 아니면
    ``Action(START)`` 호출 자체에 도달하지 못했다는 뜻이고, 그때는
    ``actionReturnCode``를 실을 수 없다 — 아직 부르지 않은 호출의 반환값은
    존재하지 않는다.
    """

    schema_version: Literal["1.0"] = "1.0"
    dispatch_id: str = Field(pattern=_PATH_SAFE_ID)
    edge_device_id: str = Field(pattern=_PATH_SAFE_ID)
    mission_id: str = Field(min_length=1)
    mission_contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_policy_pack_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reported_at: AwareDatetime
    runtime_version: str = Field(min_length=1)
    verdict: FlightStartVerdict
    # ADR §5 [10] "UploadKmzFile → Action(START), 반환값을 기록한다" — 그 호출까지
    # 도달했을 때만(``verdict == STARTED``) 존재하는 원문 반환코드.
    action_return_code: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _return_code_only_when_started(self) -> FlightStartReceiptV1:
        if self.verdict is not FlightStartVerdict.STARTED and self.action_return_code is not None:
            raise ValueError(
                "Action(START) 호출 전 거부(verdict != STARTED)에는 "
                "actionReturnCode가 있을 수 없다"
            )
        return self


class FlightStartReceiptResponse(CamelModel):
    verdict: EdgeDispatchVerdict
    dispatch_id: str
    # 접수(RECORDED/ALREADY_RECORDED)에만 채워진다 — 거부 응답(404/409/422/503)은
    # HTTPException 이라 이 모델을 거치지 않는다.
    outcome: str | None = None


def _edge_principal(principal: Principal) -> Principal:
    """고정 permission 집합 외에 principal 종류도 명시 확인한다."""
    if principal.kind is not PrincipalKind.EDGE_DEVICE or principal.device_id is None:
        raise HTTPException(status_code=403, detail="권한이 없다")
    return principal


def build_edge_dispatch_router(
    store: EdgeDispatchStore,
    *,
    event_store: EventStore | None = None,
    evidence_storage: EvidenceStorage | None = None,
    mission_execution_store: MissionExecutionStore | None = None,
    site_lifecycle: SpatialModelLifecycle | None = None,
    device_attestation_registry: DeviceAttestationRegistry | None = None,
) -> APIRouter:
    """별도 Edge sync router — 기존 operator evidence 권한을 약화하지 않는다.

    ``mission_execution_store`` 를 주면 dispatch·activation 이 임무 실행 상태를
    자동으로 옮긴다(ADR-KSI-019 G2). **그 결과는 이 라우터의 응답을 절대 바꾸지
    않는다** — 투영 원장의 가용성이 장비의 임무 수신을 막으면 안 된다.
    """
    router = APIRouter(prefix="/v1/edge-sync", tags=["edge-sync"])

    @router.get("/missions/next", response_model=MissionDispatchEnvelopeV1)
    def next_mission(
        principal: Principal = Depends(require_permission(Permission.EDGE_MISSION_PULL)),  # noqa: B008
    ) -> MissionDispatchEnvelopeV1 | Response:
        edge = _edge_principal(principal)
        assert edge.device_id is not None  # noqa: S101 -- _edge_principal 보장
        result = store.next_for_device(edge.device_id, now=datetime.now(UTC))
        if result.verdict is EdgeDispatchVerdict.NO_MISSION:
            return Response(status_code=204)
        if result.verdict is EdgeDispatchVerdict.STORE_UNAVAILABLE:
            raise HTTPException(status_code=503, detail="EDGE_DISPATCH_STORE_UNAVAILABLE")
        assert result.envelope is not None  # noqa: S101 -- ISSUED/EXISTING만 이 경로
        if mission_execution_store is not None:
            # 임무가 기체 쪽으로 넘어갔다 → DISPATCHED. **반환값을 의도적으로
            # 무시한다**: 이미 CANCELLED 인 임무의 재 pull 은 전이표가 막고, 그
            # 거부가 장비의 임무 수신 응답을 바꾸면 안 된다(ADR-KSI-019 G2 —
            # 이 축은 게이트가 아니라 관측 기록이다).
            mission_execution_store.transition(
                str(result.envelope.get("missionId", "")),
                MissionExecutionStatus.DISPATCHED,
                detail=f"edge pull dispatchId={result.envelope.get('dispatchId')}",
                actor=f"system:edge-dispatch:{edge.device_id}",
                now=datetime.now(UTC),
            )
            # 매핑 계열 임무의 배포는 그 현장의 매핑 시작이기도 하다(ADR-KSI-019 G1).
            # 운영자 수동 선언 경로(mission_execution 라우터)와 같은 헬퍼를 공유한다.
            advance_site_for_dispatch(
                str(result.envelope.get("missionId", "")),
                mission_store=store._mission_store,  # noqa: SLF001 -- 같은 조립의 발급 원장
                site_lifecycle=site_lifecycle,
            )
        # 서명된 봉투는 **발행 시점의 바이트 그대로** 나간다 — response_model 을
        # 거쳐 재직렬화하면 그 사이 스키마에 생긴 optional 필드가 붙어 서명 대상이
        # 바뀐다(store._replay 의 같은 주석 참조). response_model 선언은 그대로 두어
        # OpenAPI 문서·계약 대조 게이트가 이 응답의 정본을 계속 가리키게 한다.
        return JSONResponse(content=result.envelope)

    @router.post(
        "/missions/{dispatch_id}/activation-receipts",
        response_model=ActivationReceiptResponse,
        status_code=201,
    )
    def record_activation(
        dispatch_id: str,
        receipt: ActivationReceiptV1,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.EDGE_MISSION_PULL)),  # noqa: B008
    ) -> ActivationReceiptResponse:
        edge = _edge_principal(principal)
        assert edge.device_id is not None  # noqa: S101
        if receipt.dispatch_id != dispatch_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        result = store.record_activation(
            device_id=edge.device_id, receipt=receipt, now=datetime.now(UTC)
        )
        if result.verdict is EdgeDispatchVerdict.NOT_FOUND:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        if result.verdict is EdgeDispatchVerdict.RECEIPT_MISMATCH:
            raise HTTPException(status_code=422, detail=EdgeDispatchVerdict.RECEIPT_MISMATCH.value)
        if result.verdict is EdgeDispatchVerdict.STORE_UNAVAILABLE:
            raise HTTPException(status_code=503, detail="EDGE_DISPATCH_STORE_UNAVAILABLE")
        if result.verdict is EdgeDispatchVerdict.ALREADY_ACTIVATED:
            response.status_code = 200
        if mission_execution_store is not None:
            # 기체가 계약을 활성화했다고 서명해 보고했다 → ACTIVATED. 재수신
            # (ALREADY_ACTIVATED)에도 같은 전이를 시도하지만 자기 자신으로의 전이는
            # 전이표에 없으므로 원장에 빈 레코드가 쌓이지 않는다.
            mission_execution_store.transition(
                receipt.mission_id,
                MissionExecutionStatus.ACTIVATED,
                detail=f"activation receipt dispatchId={dispatch_id}",
                actor=f"system:edge-activation:{edge.device_id}",
                now=datetime.now(UTC),
            )
        return ActivationReceiptResponse(verdict=result.verdict, dispatch_id=dispatch_id)

    @router.post(
        "/missions/{dispatch_id}/flight-start-receipts",
        response_model=FlightStartReceiptResponse,
        status_code=201,
    )
    def record_flight_start(
        dispatch_id: str,
        receipt: FlightStartReceiptV1,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.EDGE_MISSION_PULL)),  # noqa: B008
    ) -> FlightStartReceiptResponse:
        """ADR-KSI-021 §9 접수 — ``record_activation`` 과 정확히 같은 모양.

        ``MissionExecutionStore`` 를 전이하지 않는다: 이 receipt 에 대응하는 실행
        상태가 없고(``IN_FLIGHT`` 는 만들지 않는다), 없는 상태를 지어내느니 이 축을
        아예 건드리지 않는 편이 정직하다.
        """
        edge = _edge_principal(principal)
        assert edge.device_id is not None  # noqa: S101
        if receipt.dispatch_id != dispatch_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        result = store.record_flight_start(
            device_id=edge.device_id, receipt=receipt, now=datetime.now(UTC)
        )
        if result.verdict is EdgeDispatchVerdict.NOT_FOUND:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        if result.verdict is EdgeDispatchVerdict.NOT_ACTIVATED:
            raise HTTPException(status_code=409, detail=EdgeDispatchVerdict.NOT_ACTIVATED.value)
        if result.verdict is EdgeDispatchVerdict.RECEIPT_MISMATCH:
            raise HTTPException(status_code=422, detail=EdgeDispatchVerdict.RECEIPT_MISMATCH.value)
        if result.verdict is EdgeDispatchVerdict.STORE_UNAVAILABLE:
            raise HTTPException(status_code=503, detail="EDGE_DISPATCH_STORE_UNAVAILABLE")
        if result.verdict is EdgeDispatchVerdict.FLIGHT_START_ALREADY_RECORDED:
            response.status_code = 200
        return FlightStartReceiptResponse(
            verdict=result.verdict, dispatch_id=dispatch_id, outcome=result.outcome
        )

    if event_store is not None and evidence_storage is not None:
        _mount_edge_evidence_route(
            router,
            store,
            event_store,
            evidence_storage,
            device_attestation_registry or DeviceAttestationRegistry(),
        )
    return router


def _mount_edge_evidence_route(
    router: APIRouter,
    dispatch_store: EdgeDispatchStore,
    event_store: EventStore,
    storage: EvidenceStorage,
    attestation_registry: DeviceAttestationRegistry,
) -> None:
    @router.post(
        "/events/{event_key}/evidence",
        response_model=EdgeEvidenceUploadResponse,
        status_code=201,
    )
    def register_edge_evidence(
        event_key: str,
        request: EdgeEvidenceUploadRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.EDGE_EVIDENCE_WRITE)),  # noqa: B008
    ) -> EdgeEvidenceUploadResponse:
        edge = _edge_principal(principal)
        assert edge.device_id is not None  # noqa: S101
        event = event_store.get(event_key)
        # 다른 장비 event와 존재하지 않는 event를 같은 일반 404로 접는다.
        if event is None or event.edge_device_id != edge.device_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        # A durable sha256 claim without a storage-enforced body checksum is a
        # false integrity guarantee.  Do this before registering anything so a
        # deployment that has only the legacy evidence storage port fails
        # closed without creating an uploadable Edge artifact record.
        if not isinstance(storage, DigestBoundEvidenceStorage):
            raise HTTPException(status_code=503, detail="EVIDENCE_DIGEST_BINDING_UNAVAILABLE")

        now = datetime.now(UTC)
        attested = False
        attestation_key_id: str | None = None
        dispatch_context: ActivatedDispatchEvidenceContext | None = None
        if event.severity is Severity.CRITICAL and request.attestation is None:
            raise HTTPException(status_code=422, detail="ATTESTATION_REQUIRED")
        if request.attestation is not None:
            dispatch_context = dispatch_store.activated_evidence_context(
                device_id=edge.device_id,
                mission_id=event.mission_id,
                occurred_at=event.occurred_at,
            )
            if dispatch_context is None:
                raise HTTPException(status_code=409, detail="ACTIVE_DISPATCH_LINEAGE_MISMATCH")
            signed_payload = evidence_attestation_payload(
                device_id=edge.device_id,
                site_id=event.site_id,
                mission_id=event.mission_id,
                event_key=event_key,
                artifact_id=request.artifact_id,
                content_type=request.content_type,
                content_digest=request.content_digest,
            )
            verification = verify_device_evidence_attestation(
                request.attestation,
                attestation_registry,
                payload=signed_payload,
                device_id=edge.device_id,
                now=now,
            )
            if not verification.is_valid:
                raise HTTPException(
                    status_code=422,
                    detail=f"ATTESTATION_{verification.verdict.value}",
                )
            attested = True
            attestation_key_id = verification.key_id
        reused = False
        try:
            registered = event_store.register_evidence(
                event_key=event_key,
                artifact_id=request.artifact_id,
                content_type=request.content_type,
                registered_by=edge.principal_id,
                now=now,
                content_digest=request.content_digest,
                # 이 라우트만 진입 시점에 이미 event.edge_device_id == edge.device_id
                # 를 확인했다(위) — 그래서 여기서만 device_bound=True 다.
                device_bound=True,
                device_attested=attested,
                attestation_key_id=attestation_key_id,
                attestation_signature=(
                    request.attestation.signature if request.attestation is not None else None
                ),
                attested_dispatch_id=(
                    dispatch_context.dispatch_id if dispatch_context is not None else None
                ),
                attested_risk_policy_pack_id=(
                    dispatch_context.risk_policy_pack_id if dispatch_context is not None else None
                ),
                attested_risk_policy_pack_digest=(
                    dispatch_context.risk_policy_pack_digest
                    if dispatch_context is not None
                    else None
                ),
                attested_calibration_profile_id=(
                    dispatch_context.calibration_profile_id
                    if dispatch_context is not None
                    else None
                ),
            )
        except JournalSealedError as exc:
            raise HTTPException(status_code=503, detail="EVENT_STORE_UNAVAILABLE") from exc
        if registered.verdict is EvidenceVerdict.DUPLICATE_ARTIFACT:
            artifact = event_store.get_evidence(event_key, request.artifact_id)
            if (
                artifact is None
                or artifact.is_tombstoned
                or artifact.content_type != request.content_type
                or artifact.content_digest != request.content_digest
                or artifact.device_attested != attested
                or artifact.attestation_key_id != attestation_key_id
                or artifact.attestation_signature
                != (request.attestation.signature if request.attestation is not None else None)
            ):
                raise HTTPException(
                    status_code=409, detail=EvidenceVerdict.DUPLICATE_ARTIFACT.value
                )
            reused = True
            response.status_code = 200
        elif registered.verdict is EvidenceVerdict.REGISTERED and registered.artifact is not None:
            artifact = registered.artifact
        else:
            status = {
                EvidenceVerdict.UNKNOWN_EVENT: 404,
                EvidenceVerdict.INVALID_ARTIFACT_ID: 422,
                EvidenceVerdict.UNSUPPORTED_CONTENT_TYPE: 415,
                EvidenceVerdict.ALREADY_TOMBSTONED: 410,
            }.get(registered.verdict, 422)
            raise HTTPException(status_code=status, detail=registered.verdict.value)
        try:
            capability = storage.presigned_put_bound_digest(
                artifact.object_key,
                content_type=artifact.content_type,
                content_digest=request.content_digest,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE") from exc
        if not capability.upload_url or not capability.required_headers:
            # Do not fall back to a bare URL: a missing signed header lets an
            # Edge transport silently drop the checksum binding.
            raise HTTPException(status_code=503, detail="EVIDENCE_DIGEST_BINDING_UNAVAILABLE")
        return EdgeEvidenceUploadResponse(
            artifact_id=artifact.artifact_id,
            object_key=artifact.object_key,
            upload_url=capability.upload_url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
            reused_registration=reused,
            content_digest=request.content_digest,
            required_upload_headers=capability.required_headers,
            device_attested=artifact.device_attested,
            attestation_key_id=artifact.attestation_key_id,
        )


def mount_edge_dispatch(
    app: FastAPI,
    store: EdgeDispatchStore,
    *,
    event_store: EventStore | None = None,
    evidence_storage: EvidenceStorage | None = None,
    mission_execution_store: MissionExecutionStore | None = None,
    site_lifecycle: SpatialModelLifecycle | None = None,
    device_attestation_registry: DeviceAttestationRegistry | None = None,
) -> None:
    app.state.edge_dispatch_store = store
    app.include_router(
        build_edge_dispatch_router(
            store,
            event_store=event_store,
            evidence_storage=evidence_storage,
            device_attestation_registry=device_attestation_registry,
            mission_execution_store=mission_execution_store,
            site_lifecycle=site_lifecycle,
        )
    )


__all__ = [
    "ActivationResult",
    "DispatchResult",
    "EdgeDispatchRecoveryError",
    "EdgeDispatchStore",
    "EdgeDispatchVerdict",
    "EdgeRuntimeProfileRegistry",
    "FlightStartReceiptV1",
    "FlightStartResult",
    "FlightStartVerdict",
    "RiskPolicyPackRegistry",
    "build_edge_dispatch_router",
    "mount_edge_dispatch",
]

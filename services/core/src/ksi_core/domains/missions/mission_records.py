"""Mission 발급 영속·목록/이력 조회 (ADR-KSI-008 §1/§3, ADR-KSI-007 짝 무결성).

발급(``mission_plans.py``/``mission_issuance.py``)이 만든 산출물을
:class:`DurableJournal` 위에 영속하고, 그 결과를 조회하는 GET 표면을 이 모듈이
소유한다. ADR-KSI-008 §3 의 "발급 레코드가 durable 기록되기 전에는 201 을
반환하지 않는다" 를 만족시키는 유일한 관문이 :meth:`MissionStore.record_issuance`
다 — 두 발급 라우터(계약 단독/짝) 모두 이 메서드를 거쳐야 201 을 낼 수 있다.

## 서명 전 사전 게이트 (site_exists·siteFrame 일치·mission_id 충돌·임무타입×현장상태(INV-052))

:func:`precheck_issuance` 는 서명(및 짝 발급의 경우 KMZ 생성)을 하기 **전에**
호출한다 — 이미 실패가 확정된 요청에 서명 비용을 치르지 않기 위해서다. 다만
이 사전 체크는 낙관적이다: 사전 체크 통과 후 실제 conditional commit 사이에
prerequisite가 바뀌거나 경쟁 요청이 같은 mission_id 를 선점할 수 있다. 최종
인가 판정은 :class:`~ksi_core.mission_atomicity.MissionIssuanceCommitter`가
prerequisite store guard를 정해진 순서로 보유한 채 witness를 다시 대조하고,
마지막에 이 store의 :meth:`MissionStore.record_issuance`를 호출해 durable append할
때 내려진다. 사전 체크는 비용 절감용 낙관적 단축 경로일 뿐 정합성의 근원이 아니다.

mission_id 충돌 검사가 임무타입×현장상태 게이트보다 **먼저**인 이유(독립
재검토 D1): 인가 결정은 이미 발급 시점에 내려져 원장에 기록됐다 — 그 재반환
(``mission_plans.py`` 의 멱등 재발급, "같은 missionId + 동일 요청 digest")이
나중에 바뀐 현장 상태에 좌우되면 안 된다. 순서가 뒤집혀 있으면(게이트가
먼저) 발급 당시엔 허용됐던 조합이 그 사이 현장이 전이해 더는 허용되지
않을 때, 201 응답 유실 후 재시도가 멱등 200 대신 게이트 거부(409
``MISSION_TYPE_SITE_STATUS_MISMATCH``)를 받는다 — 이미 발급·기록된 임무에
사실과 다른 사유를 주는 것과 같다. mission_id 가 아직 없으면(진짜 신규
발급) 이 순서 변경은 결과에 영향이 없다 — 게이트는 여전히 신규 발급을
막는다.

## contract 필드는 무변형 보존 (INV-011)

:class:`MissionRecord.contract` 는 발급 시점에 서명까지 끝난 계약 전문 dict
그대로다 — 이 모듈은 재계산·재정규화하지 않는다. journal 을 통한 JSON 왕복
(``dumps``→``loads``)은 값을 보존하므로 조회 응답은 발급 응답과 정확히
일치해야 한다(재검토·재서명 없음).

## 재생(replay)은 fail-closed (재검토 P2)

기동 시 journal 을 재생해 projection 을 재구성한다. 중복 ``missionId``·부정
``artifactKind``·``contract`` 가 dict 가 아닌 레코드 등 오염이 발견되면
:class:`MissionStoreRecoveryError` 로 기동을 거부한다(``sites.py`` 의
``SiteStoreRecoveryError`` 와 대칭 — 조용히 덮어쓰며 기동하지 않는다).

## 발급 경계의 typed 거부 두 가지 (재검토 P2)

:func:`validate_mission_identifiers` 는 ``missionId``/``siteId`` 에 URL 경로
안전 문자만 허용한다 — 위반이면 그 문자를 포함한 채 201 로 기록된 뒤 상세·계약
조회(``/v1/missions/{mission_id}``)가 영구 404 가 되는 트랩을 서명 전에 막는다.
:func:`find_lone_surrogate_path`/:func:`reject_lone_surrogates` 는 요청 문자열에
JSON escape 로만 존재 가능한 lone surrogate(예: ``\\ud800``)를 탐지한다 — 이
문자는 서명 정규화(``canonical_payload_bytes`` 의 UTF-8 strict 인코딩)에서
``UnicodeEncodeError``→500 을 일으키므로 발급 경계에서 선제 422 로 거부한다.
"""

from __future__ import annotations

import builtins
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_domain.enums import MissionType, SiteStatus
from ksi_domain.mission_gating import is_mission_type_allowed_at_site_status
from ksi_event_contracts.coverage_report import CompletionState
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.missions.coverage_reports import CoverageReportStore

# 조회 응답에 노출하지 않는 404 일반 문구 — 열거 오라클 방지 관습(auth.py 대칭).
# public(밑줄 없음) — mission_plans.py 의 KMZ 다운로드 라우트가 같은 문구를
# 재사용한다(레코드 부재를 두 라우터가 다른 말로 알리면 사용자 혼란).
MISSION_NOT_FOUND_DETAIL = "해당 임무 레코드를 찾을 수 없다"

ArtifactKind = Literal["pair", "contract"]


class MissionRecordVerdict(StrEnum):
    """발급 영속 판정. ``RECORDED`` 만 durable 기록 성공(201 자격)이다."""

    RECORDED = "RECORDED"
    MISSION_ID_CONFLICT = "MISSION_ID_CONFLICT"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    SITE_FRAME_MISMATCH = "SITE_FRAME_MISMATCH"
    # INV-052 — "먼저 매핑, 그 다음 사전지도 기반 자율" 강제 지점. 예) UNMAPPED
    # 현장에 AUTONOMOUS_PATROL 발급 시도 (ksi_domain.mission_gating SSOT).
    MISSION_TYPE_SITE_STATUS_MISMATCH = "MISSION_TYPE_SITE_STATUS_MISMATCH"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    INVALID_MISSION_IDENTITY = "INVALID_MISSION_IDENTITY"
    INVALID_TEXT_ENCODING = "INVALID_TEXT_ENCODING"


class IssuanceConflictSubreason(StrEnum):
    """원자 commit에서 stale authorization witness를 설명하는 typed 사유."""

    SITE_ISSUANCE_REVISION_CONFLICT = "SITE_ISSUANCE_REVISION_CONFLICT"
    WORK_ORDER_REVISION_CONFLICT = "WORK_ORDER_REVISION_CONFLICT"
    ACQUISITION_WITNESS_STALE = "ACQUISITION_WITNESS_STALE"


class IssuancePreconditionChangedError(RuntimeError):
    """서명 후 prerequisite witness가 더 이상 current가 아닐 때의 fail-closed 충돌."""

    def __init__(self, subreason: IssuanceConflictSubreason) -> None:
        self.subreason = subreason
        super().__init__(f"ISSUANCE_PRECONDITION_CHANGED — {subreason.value}")


# verdict → HTTP status (edge_sync.py:321 관습). RECORDED 는 라우터가 201 로 직접
# 응답하므로 이 표는 거부 판정들의 상태 코드 조회용이다. MISSION_TYPE_SITE_STATUS_
# MISMATCH 는 409 다 — 요청 자체는 구조적으로 유효하고(422 류와 다름) 현재 자원
# 상태(site.status)와 충돌하는 것이므로, 이 저장소의 "현재 상태가 막는다" 클래스
# (ILLEGAL_TRANSITION·AOI_LOCKED·MISSION_ID_CONFLICT)와 같은 상태코드를 쓴다.
MISSION_RECORD_HTTP_STATUS: dict[MissionRecordVerdict, int] = {
    MissionRecordVerdict.RECORDED: 201,
    MissionRecordVerdict.MISSION_ID_CONFLICT: 409,
    MissionRecordVerdict.UNKNOWN_SITE: 422,
    MissionRecordVerdict.SITE_FRAME_MISMATCH: 422,
    MissionRecordVerdict.MISSION_TYPE_SITE_STATUS_MISMATCH: 409,
    MissionRecordVerdict.STORE_UNAVAILABLE: 503,
    MissionRecordVerdict.INVALID_MISSION_IDENTITY: 422,
    MissionRecordVerdict.INVALID_TEXT_ENCODING: 422,
}


class MissionStoreRecoveryError(RuntimeError):
    """journal 재생 중 오염 발견 — 오염된 projection 으로 기동하지 않는다(fail-closed).

    중복 ``missionId``·부정 ``artifactKind``·``contract`` 가 dict 가 아닌 레코드가
    대상이다(``sites.py`` 의 ``SiteStoreRecoveryError`` 와 대칭, 재검토 P2 item①).
    """


class MissionSequenceRecoveryError(RuntimeError):
    """v1.3 site sequence journal 오염 — 순서를 추정하지 않고 기동을 거부한다."""


class MissionIssuanceSequenceStore:
    """``(issuerId, siteId)``별 v1.3 양의 단조 sequence를 먼저 내구화한다.

    예약 append가 성공한 뒤 서명이나 MissionRecord 기록이 실패하면 gap이 남는다.
    gap은 허용하지만 이미 예약한 숫자는 절대 재사용하지 않는다.
    """

    _KIND = "MISSION_SITE_SEQUENCE_RESERVED"

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._lock = threading.Lock()
        self._high_water: dict[tuple[str, str], int] = {}
        try:
            self._replay(journal)
        except BaseException:
            journal.close()
            raise

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                if raw.get("kind") != self._KIND:
                    raise ValueError(f"알 수 없는 sequence record kind: {raw.get('kind')!r}")
                issuer_id = raw["issuerId"]
                site_id = raw["siteId"]
                sequence = raw["siteSequence"]
                reserved_at = datetime.fromisoformat(raw["reservedAt"])
                if not isinstance(issuer_id, str) or not is_path_safe_identifier(issuer_id):
                    raise ValueError("issuerId가 경로-안전 식별자가 아니다")
                if not isinstance(site_id, str) or not is_path_safe_identifier(site_id):
                    raise ValueError("siteId가 경로-안전 식별자가 아니다")
                if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
                    raise ValueError("siteSequence가 양의 정수가 아니다")
                if reserved_at.tzinfo is None:
                    raise ValueError("reservedAt이 tz-aware가 아니다")
                key = (issuer_id, site_id)
                previous = self._high_water.get(key, 0)
                if sequence <= previous:
                    raise ValueError(
                        f"sequence가 단조 증가하지 않는다: previous={previous}, got={sequence}"
                    )
                self._high_water[key] = sequence
            except (KeyError, TypeError, ValueError) as exc:
                raise MissionSequenceRecoveryError(
                    f"mission sequence journal 재생 실패 — 오염된 레코드: {exc}"
                ) from exc

    def reserve(self, *, issuer_id: str, site_id: str, reserved_at: datetime) -> int:
        if not is_path_safe_identifier(issuer_id) or not is_path_safe_identifier(site_id):
            raise ValueError("issuerId/siteId는 경로-안전 식별자여야 한다")
        if reserved_at.tzinfo is None:
            raise ValueError("reserved_at은 tz-aware여야 한다")
        key = (issuer_id, site_id)
        with self._lock:
            sequence = self._high_water.get(key, 0) + 1
            self._journal.append(
                {
                    "kind": self._KIND,
                    "issuerId": issuer_id,
                    "siteId": site_id,
                    "siteSequence": sequence,
                    "reservedAt": reserved_at.isoformat(),
                }
            )
            self._high_water[key] = sequence
            return sequence

    def high_water(self, *, issuer_id: str, site_id: str) -> int:
        with self._lock:
            return self._high_water.get((issuer_id, site_id), 0)


def validate_mission_identifiers(*, mission_id: str, site_id: str) -> MissionRecordVerdict | None:
    """``mission_id``/``site_id`` 에 URL 경로 안전 문자만 허용한다(재검토 P2 item②).

    위반이면 ``INVALID_MISSION_IDENTITY``, 통과하면 ``None``. 검증 없이 기록되면
    '/'·공백·제어문자를 포함한 id 가 201 로 기록된 뒤 상세·계약 조회
    (``/v1/missions/{mission_id}``)가 그 문자를 경로 세그먼트로 태울 수 없어
    영구 404 가 되는 트랩이 만들어진다.
    """
    if not is_path_safe_identifier(mission_id):
        return MissionRecordVerdict.INVALID_MISSION_IDENTITY
    if not is_path_safe_identifier(site_id):
        return MissionRecordVerdict.INVALID_MISSION_IDENTITY
    return None


def find_lone_surrogate_path(value: object, *, _path: str = "$") -> str | None:
    """JSON 유사 구조(dict/list/str/기타 스칼라)를 재귀 순회해 lone surrogate 를
    포함한 첫 문자열의 경로를 반환한다(없으면 ``None``).

    JSON 텍스트에는 ``\\ud800`` 류 미짝(unpaired) surrogate escape 가 문법적으로
    유효하다(RFC 8259 는 이를 금지하지 않는다) — ``json.loads`` 는 이를 그대로
    파이썬 str 안의 lone surrogate 코드포인트로 복원한다. 이런 문자열은 UTF-8
    strict 인코딩이 불가능해(``str.encode("utf-8", errors="strict")`` 가
    ``UnicodeEncodeError``) 서명 정규화(``canonical_payload_bytes``)에서
    500 을 일으킨다(재검토 P2 item④) — 발급 경계에서 선제 탐지해 422 로 거부한다.
    """
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return _path
        return None
    if isinstance(value, Mapping):
        for key, sub in value.items():
            # **키도 검사한다**(2026-08-18). 값만 보면 ``{"w\\ud801eights": "v"}`` 처럼
            # 키에 실린 lone surrogate 가 통과하고, pydantic 의 json-mode dump 가 그
            # 키를 U+FFFD 로 바꿔 원장에 적는다 — 생산자가 보낸 것과 **다른 키**가
            # durable 하게 남는 조용한 오염이다(재조사 실측).
            if isinstance(key, str):
                found = find_lone_surrogate_path(key, _path=f"{_path}.<key>")
                if found is not None:
                    return found
            found = find_lone_surrogate_path(sub, _path=f"{_path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for idx, sub in enumerate(value):
            found = find_lone_surrogate_path(sub, _path=f"{_path}[{idx}]")
            if found is not None:
                return found
        return None
    return None


def reject_lone_surrogates(payload: Mapping[str, Any]) -> None:
    """``payload`` 에 lone surrogate 문자열이 있으면 422 ``INVALID_TEXT_ENCODING``.

    발급 라우터가 서명·KMZ 생성을 시도하기 **전**(가장 값싼 시점)에 호출한다.
    """
    if find_lone_surrogate_path(payload) is not None:
        raise HTTPException(
            status_code=MISSION_RECORD_HTTP_STATUS[MissionRecordVerdict.INVALID_TEXT_ENCODING],
            detail=MissionRecordVerdict.INVALID_TEXT_ENCODING.value,
        )


@dataclass(frozen=True, slots=True)
class SiteLookupResult:
    """:func:`precheck_issuance` 가 site 등록 대조에 필요로 하는 최소 정보.

    ``site_frame``·``status`` 를 하나의 lookup 이 함께 반환한다 — 둘을 별개
    콜백으로 나누면 동시 site 전이 경합 시 site_frame 은 A 시점, status 는 B
    시점 값이 섞여 들어올 수 있다(:class:`~ksi_core.sites.SiteStore` 는 두 값을
    같은 잠금 구간에서 갱신한다). ``SiteStore.get()`` 한 번의 스냅샷을 그대로
    묶어 넘기는 것이 유일한 정합 보장이다.
    """

    site_frame: dict[str, Any]
    status: SiteStatus
    issuance_revision: int = 1


@dataclass(frozen=True, slots=True)
class WorkOrderAuthorizationWitness:
    work_order_id: str
    version: int
    cycle_number: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workOrderId": self.work_order_id,
            "version": self.version,
            "cycleNumber": self.cycle_number,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: object) -> WorkOrderAuthorizationWitness:
        if not isinstance(raw, dict):
            raise ValueError("authorizationWitness.workOrder가 object가 아니다")
        work_order_id = raw.get("workOrderId")
        version = raw.get("version")
        cycle_number = raw.get("cycleNumber")
        status = raw.get("status")
        if not isinstance(work_order_id, str) or not is_path_safe_identifier(work_order_id):
            raise ValueError("authorizationWitness.workOrderId가 유효하지 않다")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("authorizationWitness.workOrder.version이 양의 정수가 아니다")
        if not isinstance(cycle_number, int) or isinstance(cycle_number, bool) or cycle_number < 1:
            raise ValueError("authorizationWitness.workOrder.cycleNumber가 양의 정수가 아니다")
        if status != "APPROVED":
            raise ValueError("authorizationWitness.workOrder.status는 APPROVED여야 한다")
        return cls(work_order_id, version, cycle_number, status)


@dataclass(frozen=True, slots=True)
class AcquisitionAuthorizationWitness:
    profile_digest: str
    snapshot_id: str
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "profileDigest": self.profile_digest,
            "snapshotId": self.snapshot_id,
            "expiresAt": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: object) -> AcquisitionAuthorizationWitness:
        if not isinstance(raw, dict):
            raise ValueError("authorizationWitness.acquisition이 object가 아니다")
        profile_digest = raw.get("profileDigest")
        snapshot_id = raw.get("snapshotId")
        expires_raw = raw.get("expiresAt")
        if not _is_sha256_digest(profile_digest):
            raise ValueError("authorizationWitness.acquisition.profileDigest가 유효하지 않다")
        if not isinstance(snapshot_id, str) or not is_path_safe_identifier(snapshot_id):
            raise ValueError("authorizationWitness.acquisition.snapshotId가 유효하지 않다")
        if not isinstance(expires_raw, str):
            raise ValueError("authorizationWitness.acquisition.expiresAt이 문자열이 아니다")
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            raise ValueError("authorizationWitness.acquisition.expiresAt이 tz-aware가 아니다")
        return cls(str(profile_digest), snapshot_id, expires_at)


def _is_sha256_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(char in "0123456789abcdef" for char in value[7:])


def _is_bare_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


@dataclass(frozen=True, slots=True)
class IssuanceAuthorizationWitness:
    """Core projection에서만 만든 Mission 발급 OCC witness."""

    organization_id: str
    site_id: str
    site_issuance_revision: int
    site_status: SiteStatus
    site_frame_digest: str
    request_digest: str
    captured_at: datetime
    work_order: WorkOrderAuthorizationWitness | None = None
    acquisition: AcquisitionAuthorizationWitness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "siteIssuanceRevision": self.site_issuance_revision,
            "siteStatus": self.site_status.value,
            "siteFrameDigest": self.site_frame_digest,
            "requestDigest": self.request_digest,
            "capturedAt": self.captured_at.isoformat(),
            "workOrder": None if self.work_order is None else self.work_order.to_dict(),
            "acquisition": None if self.acquisition is None else self.acquisition.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: object) -> IssuanceAuthorizationWitness:
        if not isinstance(raw, dict):
            raise ValueError("authorizationWitness가 object가 아니다")
        organization_id = raw.get("organizationId")
        site_id = raw.get("siteId")
        revision = raw.get("siteIssuanceRevision")
        site_status_raw = raw.get("siteStatus")
        site_frame_digest = raw.get("siteFrameDigest")
        request_digest = raw.get("requestDigest")
        captured_at_raw = raw.get("capturedAt")
        if not isinstance(organization_id, str) or not is_path_safe_identifier(organization_id):
            raise ValueError("authorizationWitness.organizationId가 유효하지 않다")
        if not isinstance(site_id, str) or not is_path_safe_identifier(site_id):
            raise ValueError("authorizationWitness.siteId가 유효하지 않다")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("authorizationWitness.siteIssuanceRevision이 양의 정수가 아니다")
        if not isinstance(site_status_raw, str):
            raise ValueError("authorizationWitness.siteStatus가 문자열이 아니다")
        try:
            site_status = SiteStatus(site_status_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("authorizationWitness.siteStatus가 유효하지 않다") from exc
        if not _is_sha256_digest(site_frame_digest):
            raise ValueError("authorizationWitness.siteFrameDigest가 유효하지 않다")
        if not _is_sha256_digest(request_digest):
            raise ValueError("authorizationWitness.requestDigest가 유효하지 않다")
        if not isinstance(captured_at_raw, str):
            raise ValueError("authorizationWitness.capturedAt이 문자열이 아니다")
        captured_at = datetime.fromisoformat(captured_at_raw)
        if captured_at.tzinfo is None:
            raise ValueError("authorizationWitness.capturedAt이 tz-aware가 아니다")
        work_order_raw = raw.get("workOrder")
        acquisition_raw = raw.get("acquisition")
        return cls(
            organization_id=organization_id,
            site_id=site_id,
            site_issuance_revision=revision,
            site_status=site_status,
            site_frame_digest=str(site_frame_digest),
            request_digest=str(request_digest),
            captured_at=captured_at,
            work_order=(
                None
                if work_order_raw is None
                else WorkOrderAuthorizationWitness.from_dict(work_order_raw)
            ),
            acquisition=(
                None
                if acquisition_raw is None
                else AcquisitionAuthorizationWitness.from_dict(acquisition_raw)
            ),
        )


@dataclass(frozen=True, slots=True)
class MissionRecord:
    """발급 1건의 영속 레코드 — ``contract`` 는 서명 포함 발급 전문 그대로(INV-011)."""

    mission_id: str
    site_id: str
    mission_type: str
    artifact_kind: ArtifactKind
    contract: dict[str, Any]
    kmz_sha256: str | None
    route_pattern: str | None
    waypoint_count: int | None
    planned_coverage_ratio: float | None
    issued_at: datetime
    issued_by: str
    # 신규 발급은 인증 Principal의 조직에 귀속한다(INV-060). 기존 journal에는 이
    # 필드가 없으므로 replay 시 ``legacy``로 읽어 하위 호환한다.
    organization_id: str = "legacy"
    # 짝(pair) 발급 재현용 — KMZ 바이트 자체는 저장하지 않고(용량), 같은
    # missionId+동일 요청 digest 재요청을 멱등 재반환하기 위해 재생성 입력만
    # 영속한다(재검토 P2 item③). contract-only 발급은 항상 None.
    plan_request: dict[str, Any] | None = None
    plan_request_digest: str | None = None
    # 이 임무를 수행할 것으로 신고된 장비(INV-010 무결성 — coverage_reports.py
    # 모듈 docstring의 "알려진 공백"을 닫는 필드). **서명된 계약의 일부가
    # 아니다** — kmz_sha256·route_pattern 과 같은 지위로, Core 가 완료 판정
    # 게이트에 쓰는 운영 메타데이터일 뿐 Manifold 로 가는 신뢰 경계 밖이다.
    # None 이면 배정을 신고하지 않은 것이고, 그 임무는 예전과 같이(하위호환)
    # 인증된 어느 EDGE_DEVICE 든 커버리지를 보고할 수 있다 — "배정 안 함"과
    # "아무나 허용"을 다른 정직으로 구분하지 않는다: 배정 개념 자체가 아직
    # 선택적이라(1:1 대일 배치 전제, Fleet·Edge 이전) 강제할 근거가 없다.
    assigned_device_id: str | None = None
    # ``None``은 OCC 도입 이전의 genuine legacy record다. Production 발급 writer는
    # 항상 "1.0" + request digest + authorization witness를 함께 기록한다.
    issuance_schema_version: Literal["1.0"] | None = None
    issuance_request_digest: str | None = None
    authorization_witness: IssuanceAuthorizationWitness | None = None


_VALID_ARTIFACT_KINDS = frozenset({"pair", "contract"})


def _record_to_dict(record: MissionRecord) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "missionId": record.mission_id,
        "siteId": record.site_id,
        "missionType": record.mission_type,
        "artifactKind": record.artifact_kind,
        "contract": record.contract,
        "kmzSha256": record.kmz_sha256,
        "routePattern": record.route_pattern,
        "waypointCount": record.waypoint_count,
        "plannedCoverageRatio": record.planned_coverage_ratio,
        "issuedAt": record.issued_at.isoformat(),
        "issuedBy": record.issued_by,
        "organizationId": record.organization_id,
        "planRequest": record.plan_request,
        "planRequestDigest": record.plan_request_digest,
        "assignedDeviceId": record.assigned_device_id,
    }
    if record.issuance_schema_version is not None:
        raw.update(
            {
                "issuanceSchemaVersion": record.issuance_schema_version,
                "issuanceRequestDigest": record.issuance_request_digest,
                "authorizationWitness": (
                    None
                    if record.authorization_witness is None
                    else record.authorization_witness.to_dict()
                ),
            }
        )
    return raw


def _record_from_dict(raw: dict[str, Any]) -> MissionRecord:
    issued_at = datetime.fromisoformat(raw["issuedAt"])
    if issued_at.tzinfo is None:
        raise ValueError(f"{raw.get('missionId')!r}: issuedAt 은 tz-aware 여야 한다")
    artifact_kind = raw["artifactKind"]
    if artifact_kind not in _VALID_ARTIFACT_KINDS:
        raise ValueError(
            f"{raw.get('missionId')!r}: 알 수 없는 artifactKind: {artifact_kind!r}"
        )
    contract = raw["contract"]
    if not isinstance(contract, dict):
        raise ValueError(
            f"{raw.get('missionId')!r}: contract 가 dict 가 아니다({type(contract).__name__})"
        )
    organization_id = raw.get("organizationId", "legacy")
    if not isinstance(organization_id, str) or not is_path_safe_identifier(organization_id):
        raise ValueError(
            f"{raw.get('missionId')!r}: organizationId 가 경로-안전 비공백 문자열이 아니다"
        )
    plan_request = raw.get("planRequest")
    if plan_request is not None and not isinstance(plan_request, dict):
        raise ValueError(
            f"{raw.get('missionId')!r}: planRequest 가 dict 가 아니다"
            f"({type(plan_request).__name__})"
        )
    plan_request_digest = raw.get("planRequestDigest")
    # 재생 경로에서도 요청 digest ↔ 저장된 요청의 정합을 재검증한다
    # (s2-residual-hardening #3). 이 대조가 live 경로에만 있으면, 원장이 조작되어
    # digest 와 planRequest 가 어긋난 레코드가 남았을 때 재시도가 "같은 요청"으로
    # 판정되고 **다른** 입력으로 KMZ 를 재생성해 돌려준다 — 클라이언트는 자기가
    # 보낸 적 없는 경로를 자기 요청의 멱등 응답으로 받는다.
    if plan_request is not None and plan_request_digest is not None:
        actual = sha256_digest(canonical_payload_bytes(plan_request))
        if actual != plan_request_digest:
            raise ValueError(
                f"{raw.get('missionId')!r}: planRequestDigest 가 planRequest 와 "
                f"불일치(선언 {plan_request_digest} != 실제 {actual})"
            )
    if artifact_kind == "pair" and plan_request is None:
        # 짝 레코드는 KMZ 재생성 입력을 반드시 들고 있어야 한다.
        #
        # 근거 정정(독립 재검토 P1-2): 처음 적었던 "없으면 멱등 재발급이 assert 로
        # 죽는다"는 **틀렸다** — planRequestDigest 가 None 이면 재발급 분기 조건
        # (digest 일치)에 애초 도달하지 않아 그냥 409 다. 진짜 근거는 하위호환이
        # 아니라 **불변식의 나이**다: planRequest 영속과 artifactKind="pair" 는
        # 같은 커밋(bd9d7f9)에서 함께 도입됐으므로 이 조합의 레코드는 정상적으로
        # 존재할 수 없다. 있다면 원장이 조작됐거나 쓰기 경로가 깨진 것이고,
        # 그 상태로 조용히 기동하면 재발급이 영구 409 인 짝을 사람이 원인 없이
        # 만나게 된다.
        raise ValueError(
            f"{raw.get('missionId')!r}: artifactKind=pair 인데 planRequest 가 없다"
        )
    issuance_schema_version = raw.get("issuanceSchemaVersion")
    issuance_request_digest_raw = raw.get("issuanceRequestDigest")
    authorization_witness_raw = raw.get("authorizationWitness")
    if issuance_schema_version is None:
        if "issuanceRequestDigest" in raw or "authorizationWitness" in raw:
            raise ValueError(
                f"{raw.get('missionId')!r}: issuance schema discriminator 없이 OCC 필드가 있다"
            )
        issuance_request_digest = None
        authorization_witness = None
    else:
        if issuance_schema_version != "1.0":
            raise ValueError(
                f"{raw.get('missionId')!r}: 미지원 issuanceSchemaVersion="
                f"{issuance_schema_version!r}"
            )
        if not _is_sha256_digest(issuance_request_digest_raw):
            raise ValueError(
                f"{raw.get('missionId')!r}: issuanceRequestDigest가 유효하지 않다"
            )
        issuance_request_digest = str(issuance_request_digest_raw)
        authorization_witness = IssuanceAuthorizationWitness.from_dict(
            authorization_witness_raw
        )
        if authorization_witness.request_digest != issuance_request_digest:
            raise ValueError(
                f"{raw.get('missionId')!r}: witness requestDigest가 issuanceRequestDigest와 다르다"
            )
        if authorization_witness.captured_at != issued_at:
            raise ValueError(
                f"{raw.get('missionId')!r}: witness capturedAt이 Mission issuedAt과 다르다"
            )
        if authorization_witness.organization_id != organization_id:
            raise ValueError(
                f"{raw.get('missionId')!r}: witness organizationId가 Mission과 다르다"
            )
        if authorization_witness.site_id != raw.get("siteId"):
            raise ValueError(f"{raw.get('missionId')!r}: witness siteId가 Mission과 다르다")
        if contract.get("missionId") != raw.get("missionId"):
            raise ValueError(f"{raw.get('missionId')!r}: contract missionId가 record와 다르다")
        if contract.get("siteId") != raw.get("siteId"):
            raise ValueError(f"{raw.get('missionId')!r}: contract siteId가 record와 다르다")
        if contract.get("missionType") != raw.get("missionType"):
            raise ValueError(f"{raw.get('missionId')!r}: contract missionType이 record와 다르다")
        mission_type_raw = raw.get("missionType")
        if not isinstance(mission_type_raw, str):
            raise ValueError(f"{raw.get('missionId')!r}: missionType이 문자열이 아니다")
        try:
            recorded_mission_type = MissionType(mission_type_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{raw.get('missionId')!r}: missionType이 유효하지 않다") from exc
        if not is_mission_type_allowed_at_site_status(
            recorded_mission_type, authorization_witness.site_status
        ):
            raise ValueError(
                f"{raw.get('missionId')!r}: witness Site 상태가 Mission type을 인가하지 않는다"
            )
        contract_site_frame = contract.get("siteFrame")
        if not isinstance(contract_site_frame, dict):
            raise ValueError(f"{raw.get('missionId')!r}: 신규 Mission contract에 siteFrame이 없다")
        actual_frame_digest = sha256_digest(canonical_payload_bytes(contract_site_frame))
        if authorization_witness.site_frame_digest != actual_frame_digest:
            raise ValueError(
                f"{raw.get('missionId')!r}: witness siteFrameDigest가 contract와 다르다"
            )
        if artifact_kind == "pair":
            if not _is_bare_sha256(raw.get("kmzSha256")):
                raise ValueError(
                    f"{raw.get('missionId')!r}: 신규 pair Mission의 kmzSha256이 유효하지 않다"
                )
            if plan_request_digest != issuance_request_digest:
                raise ValueError(
                    f"{raw.get('missionId')!r}: pair request digest 두 필드가 다르다"
                )
            requested_work_order = (
                plan_request.get("workOrderId") if plan_request is not None else None
            )
            witnessed_work_order = (
                None
                if authorization_witness.work_order is None
                else authorization_witness.work_order.work_order_id
            )
            if requested_work_order != witnessed_work_order:
                raise ValueError(
                    f"{raw.get('missionId')!r}: WorkOrder request/witness 계보가 다르다"
                )
        else:
            if raw.get("kmzSha256") is not None:
                raise ValueError(
                    f"{raw.get('missionId')!r}: contract-only Mission에 kmzSha256이 있다"
                )
            if authorization_witness.work_order is not None:
                raise ValueError(
                    f"{raw.get('missionId')!r}: contract-only Mission에 WorkOrder witness가 있다"
                )
        if (
            authorization_witness.acquisition is not None
            and authorization_witness.acquisition.expires_at <= authorization_witness.captured_at
        ):
            raise ValueError(
                f"{raw.get('missionId')!r}: acquisition witness가 capture 시점에 이미 만료됐다"
            )
    return MissionRecord(
        mission_id=raw["missionId"],
        site_id=raw["siteId"],
        mission_type=raw["missionType"],
        artifact_kind=artifact_kind,
        contract=contract,
        kmz_sha256=raw.get("kmzSha256"),
        route_pattern=raw.get("routePattern"),
        waypoint_count=raw.get("waypointCount"),
        planned_coverage_ratio=raw.get("plannedCoverageRatio"),
        issued_at=issued_at,
        issued_by=raw["issuedBy"],
        organization_id=organization_id,
        plan_request=plan_request,
        plan_request_digest=plan_request_digest,
        assigned_device_id=raw.get("assignedDeviceId"),
        issuance_schema_version=issuance_schema_version,
        issuance_request_digest=issuance_request_digest,
        authorization_witness=authorization_witness,
    )


class MissionStore:
    """:class:`DurableJournal` 위의 발급 이력 저장소 — 등록/조회 표면만 공개한다.

    공개 표면을 좁게 유지해(ADR-KSI-008 §1) 향후 PostgreSQL 전환 시 교체 경계가
    이 클래스 하나가 되게 한다. 기동 시 journal 을 재생해 인메모리 projection
    (``mission_id`` → :class:`MissionRecord`)을 채운다 — 재적재 실패는
    :class:`~ksi_core.durable_journal.JournalRecoveryError` 로 기동 자체가
    거부된다(DurableJournal fail-closed 재생 그대로 상속).
    """

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._lock = threading.Lock()
        self._by_id: dict[str, MissionRecord] = {}
        try:
            self._replay(journal)
        except BaseException:
            # __init__ 실패 시 journal 이 flock 을 쥔 채 버려지면 프로세스
            # 수명 내내 잔존한다(2차 독립 재검토 P2, sites.py 대칭 조치).
            journal.close()
            raise

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                record = _record_from_dict(raw)
                if record.mission_id in self._by_id:
                    raise ValueError(f"중복 missionId 재생: {record.mission_id!r}")
            except (KeyError, ValueError, TypeError) as exc:
                raise MissionStoreRecoveryError(
                    f"mission journal 재생 실패 — 오염된 레코드: {exc}"
                ) from exc
            self._by_id[record.mission_id] = record

    @property
    def sealed_reason(self) -> str | None:
        """journal 봉인 사유 — precheck 이 서명·KMZ 비용을 치르기 전에 조회한다."""
        return self._journal.sealed_reason

    def record_issuance(self, record: MissionRecord) -> MissionRecordVerdict:
        """durable 기록을 시도한다 — mission_id 중복은 기존 레코드를 덮지 않는다.

        체크(중복 여부)와 append 를 한 잠금 구간에 묶어, 동시 요청이 같은
        mission_id 를 동시에 통과시키는 경합을 막는다(:func:`precheck_issuance`
        의 사전 체크는 낙관적 단축일 뿐이다). 신규 writer에서는 prerequisite
        witness 비교와 이 append를 한 critical section으로 묶는
        :class:`~ksi_core.mission_atomicity.MissionIssuanceCommitter`가 발급 권위다.
        """
        if not is_path_safe_identifier(record.organization_id):
            raise ValueError("MissionRecord.organization_id 는 경로-안전 비공백 식별자여야 한다")
        with self._lock:
            if record.mission_id in self._by_id:
                return MissionRecordVerdict.MISSION_ID_CONFLICT
            # 신규 OCC writer는 live에서도 replay와 같은 schema/witness 검증을
            # 통과한다. legacy fixture/import path는 과거와 같이 기록할 수 있지만
            # 거기에 존재하지 않았던 provenance를 추정하지 않는다.
            if record.issuance_schema_version is not None:
                _record_from_dict(_record_to_dict(record))
            try:
                self._journal.append(_record_to_dict(record))
            except JournalSealedError:
                return MissionRecordVerdict.STORE_UNAVAILABLE
            self._by_id[record.mission_id] = record
            return MissionRecordVerdict.RECORDED

    def get(self, mission_id: str) -> MissionRecord | None:
        with self._lock:
            record = self._by_id.get(mission_id)
        organization_id = current_request_organization_id()
        if organization_id is not None and (
            record is None or record.organization_id != organization_id
        ):
            return None
        return record

    def get_scoped(self, mission_id: str, *, organization_id: str) -> MissionRecord | None:
        """명시적 조직 경계 조회. 부재·다른 조직은 같은 ``None``이다(INV-060)."""

        if not is_path_safe_identifier(organization_id):
            return None
        with self._lock:
            record = self._by_id.get(mission_id)
        if record is None or record.organization_id != organization_id:
            return None
        return record

    def list(self, site_id: str | None = None) -> list[MissionRecord]:
        """조직 문맥과 선택적 ``site_id``로 좁힌 결정적 목록.

        HTTP 요청 안에서는 인증 dependency가 제공한 organizationId만 보인다. 요청
        밖의 신뢰된 내부 작업은 문맥이 없으므로 기존처럼 전체 projection을 읽고,
        그런 호출이 조직 경계가 필요하면 :meth:`list_scoped`를 사용한다.
        """
        with self._lock:
            records = list(self._by_id.values())
        organization_id = current_request_organization_id()
        if organization_id is not None:
            records = [r for r in records if r.organization_id == organization_id]
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        records.sort(key=lambda r: (r.issued_at, r.mission_id))
        return records

    def list_scoped(
        self, *, organization_id: str, site_id: str | None = None
    ) -> builtins.list[MissionRecord]:
        """요청 문맥에 의존하지 않는 명시적 조직 범위 목록."""

        if not is_path_safe_identifier(organization_id):
            return []
        with self._lock:
            records = [
                record
                for record in self._by_id.values()
                if record.organization_id == organization_id
                and (site_id is None or record.site_id == site_id)
            ]
        records.sort(key=lambda r: (r.issued_at, r.mission_id))
        return records


def precheck_issuance(
    *,
    mission_store: MissionStore,
    site_lookup: Callable[[str, str], SiteLookupResult | None],
    organization_id: str,
    site_id: str,
    mission_id: str,
    mission_type: MissionType,
    requested_site_frame: dict[str, Any],
    request_digest: str,
    captured_at: datetime,
) -> MissionRecordVerdict | IssuanceAuthorizationWitness:
    """서명 전 게이트 — 통과하면 immutable Site authorization witness를 반환한다.

    검사 순서(비용이 싼 순): journal 봉인 여부(재검토 P2 item⑤ — 서명·KMZ 비용을
    치르기 전에 조기 반환) → mission_id/site_id 문자 제약(item②) → site 등록 대조
    (``site_lookup``) → siteFrame 일치 → **mission_id 충돌** →
    임무타입×현장상태 게이트(INV-052).

    mission_id 충돌이 게이트보다 먼저인 이유(독립 재검토 D1, 모듈 docstring
    참조): 이미 기록된 mission_id 재사용 시도는 그 재반환이 멱등인지(같은 요청
    digest — 호출부인 ``mission_plans.py`` 가 판정) 아니면 진짜 충돌인지와
    무관하게, **현재** site 상태로 다시 심사받으면 안 된다 — 인가는 발급
    시점에 이미 끝났다. 게이트는 mission_id 가 아직 비어 있는(진짜 신규 발급)
    경우에만 의미가 있으므로, 충돌 검사를 먼저 해도 신규 발급 거부 능력은
    그대로다.

    ``site_lookup`` 은 등록된 site 의 :class:`SiteLookupResult`(canonical
    siteFrame + 현재 :class:`~ksi_domain.enums.SiteStatus`)를 반환하고
    미등록이면 ``None`` 이다.

    - 요청의 siteFrame 이 등록본과 정확히 일치하지 않으면 ``SITE_FRAME_
      MISMATCH`` — 계약·KMZ 짝이 현장 등록 좌표계와 어긋난 채 발급되는
      drift(ADR-KSI-007 짝 무결성의 site 등록 대조판, INV-020)를 서명 전에
      차단한다.
    - mission_id 가 이미 기록돼 있으면 ``MISSION_ID_CONFLICT`` — 호출부
      (``mission_plans.py`` 짝 발급 라우터)가 동일 요청 digest 인지 판별해
      멱등 200 재반환(모듈 docstring "멱등 재발급" 참조) 또는 409 로 나뉜다.
    - ``mission_type`` 이 site 의 현재 상태에서 허용되지 않으면
      ``MISSION_TYPE_SITE_STATUS_MISMATCH`` — "먼저 매핑, 그 다음 사전지도
      기반 자율" 독트린(MASTER_PRD §6.1/§6.3)의 실제 강제 지점(INV-052,
      :mod:`ksi_domain.mission_gating` SSOT). 예: ``UNMAPPED`` 현장에
      ``AUTONOMOUS_PATROL`` 발급 시도.

    낙관적 사전 체크다(모듈 docstring 참조). 통과 시 반환한 witness는 route/KMZ
    생성과 서명 뒤 :class:`~ksi_core.mission_atomicity.MissionIssuanceCommitter`의
    짧은 conditional commit에서 다시 검증되며, 그 검증과 Mission durable append가
    한 잠금 경계에 있을 때만 신규 발급 권위가 생긴다.
    """
    if mission_store.sealed_reason is not None:
        return MissionRecordVerdict.STORE_UNAVAILABLE
    identity_verdict = validate_mission_identifiers(mission_id=mission_id, site_id=site_id)
    if identity_verdict is not None:
        return identity_verdict
    if not is_path_safe_identifier(organization_id):
        return MissionRecordVerdict.UNKNOWN_SITE
    site = site_lookup(site_id, organization_id)
    if site is None:
        return MissionRecordVerdict.UNKNOWN_SITE
    if requested_site_frame != site.site_frame:
        return MissionRecordVerdict.SITE_FRAME_MISMATCH
    # mission_id 충돌을 게이트보다 먼저 본다(독립 재검토 D1) — 이미 기록된
    # mission_id 의 재반환(멱등이든 진짜 충돌이든)은 발급 시점에 이미 내려진
    # 인가 결정에 속하고, 그 사이 바뀐 현재 site 상태로 다시 심사하면 안 된다.
    if mission_store.get_scoped(mission_id, organization_id=organization_id) is not None:
        return MissionRecordVerdict.MISSION_ID_CONFLICT
    if not is_mission_type_allowed_at_site_status(mission_type, site.status):
        return MissionRecordVerdict.MISSION_TYPE_SITE_STATUS_MISMATCH
    if site.issuance_revision < 1:
        raise RuntimeError("Site issuance revision은 양의 정수여야 한다")
    if not _is_sha256_digest(request_digest):
        raise ValueError("request_digest는 sha256 digest여야 한다")
    if captured_at.tzinfo is None:
        raise ValueError("captured_at은 tz-aware여야 한다")
    return IssuanceAuthorizationWitness(
        organization_id=organization_id,
        site_id=site_id,
        site_issuance_revision=site.issuance_revision,
        site_status=site.status,
        site_frame_digest=sha256_digest(canonical_payload_bytes(requested_site_frame)),
        request_digest=request_digest,
        captured_at=captured_at,
    )


def raise_for_mission_record_verdict(verdict: MissionRecordVerdict) -> None:
    """``RECORDED`` 가 아니면 typed HTTPException 을 던진다(``RECORDED`` 는 무동작)."""
    if verdict is MissionRecordVerdict.RECORDED:
        return
    raise HTTPException(status_code=MISSION_RECORD_HTTP_STATUS[verdict], detail=verdict.value)


class MissionRecordResponse(BaseModel):
    """조회 응답 — ``contract`` 는 별도 엔드포인트(``/contract``)에서만 반환한다."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    mission_id: str
    site_id: str
    mission_type: str
    artifact_kind: str
    kmz_sha256: str | None
    route_pattern: str | None
    waypoint_count: int | None
    planned_coverage_ratio: float | None
    issued_at: datetime
    issued_by: str
    organization_id: str
    # None 이면 배정을 신고하지 않은 임무다(MissionRecord.assigned_device_id 문서 참조).
    assigned_device_id: str | None
    # 파생 필드다 — journal 에 적힌 상태가 아니라 조회 시점에 CoverageReportStore 를
    # 조회해 계산한다(완료 판정의 권위는 CoverageReport 하나뿐이다, INV-010). 이 임무에
    # 대해 접수된 보고가 없으면 null — "아직 안 날았다"와 "날았는데 보고가 없다"를
    # 이 필드 하나로는 구분하지 못한다는 사실 자체가 상세 화면이 보여줘야 할 정보다.
    coverage_completion_state: CompletionState | None
    # 이 임무가 어느 분석 결과에서 나왔는가(ADR-KSI-019 G5) — plan_request 에 실려
    # 영속되는 운영 메타데이터를 그대로 노출한다. 최초 매핑 임무·contract 단독
    # 발급은 null. 기본값을 두지 않는다 — assignedDeviceId·coverageCompletionState
    # 와 같은 관용구(필드는 항상 있고 값이 nullable)를 그대로 따른다.
    derived_from: dict[str, Any] | None


def _derivation_of(record: MissionRecord) -> dict[str, Any] | None:
    """발급 요청에 실려 영속된 계보 — 계약이 아니라 요청에서 읽는다(``plan_request``).

    ``plan_request`` 는 짝 발급에만 있다 — 계약 단독 발급·최초 매핑 임무는
    ``None`` 이다.
    """
    plan_request = record.plan_request
    if not isinstance(plan_request, dict):
        return None
    derived = plan_request.get("derivedFrom")
    return derived if isinstance(derived, dict) else None


def _to_response(
    record: MissionRecord, *, coverage_report_store: CoverageReportStore | None
) -> MissionRecordResponse:
    latest_report = (
        coverage_report_store.latest(record.mission_id)
        if coverage_report_store is not None
        else None
    )
    return MissionRecordResponse(
        mission_id=record.mission_id,
        site_id=record.site_id,
        mission_type=record.mission_type,
        artifact_kind=record.artifact_kind,
        kmz_sha256=record.kmz_sha256,
        route_pattern=record.route_pattern,
        waypoint_count=record.waypoint_count,
        planned_coverage_ratio=record.planned_coverage_ratio,
        issued_at=record.issued_at,
        issued_by=record.issued_by,
        organization_id=record.organization_id,
        assigned_device_id=record.assigned_device_id,
        coverage_completion_state=(
            latest_report.summary.completion_state if latest_report is not None else None
        ),
        derived_from=_derivation_of(record),
    )


def build_mission_records_router(
    *, mission_store: MissionStore, coverage_report_store: CoverageReportStore | None = None
) -> APIRouter:
    """``coverage_report_store`` 는 선택이다 — 주어지면 목록·상세 응답에 최신 커버리지
    판정을 실어 내린다(메모리 조회 1회, 임무 수만큼 Core API 를 추가로 부르지 않는다).
    """
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.get("", response_model=list[MissionRecordResponse])
    def list_missions(
        site_id: str | None = Query(default=None, alias="siteId"),
        derived_from_region: str | None = Query(default=None, alias="derivedFromRegion"),
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> list[MissionRecordResponse]:
        """``derivedFromRegion`` 은 그 변화 영역에서 나온 재관측 임무만 걸러 낸다.

        ``derived_from.regionId`` 는 리포트 재계산마다 값이 바뀔 수 있는
        일반 문자열이라 원장이 인덱스를 두지 않는다 — 목록이 임무 수 규모라
        선형 스캔 비용이 낮다.
        """
        del principal  # 인가만 필요 — 조회 결과에 신원을 싣지 않는다.
        records = [
            _to_response(r, coverage_report_store=coverage_report_store)
            for r in mission_store.list(site_id=site_id)
        ]
        if derived_from_region is not None:
            records = [
                r
                for r in records
                if r.derived_from is not None
                and r.derived_from.get("regionId") == derived_from_region
            ]
        return records

    @router.get("/{mission_id}", response_model=MissionRecordResponse)
    def get_mission(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> MissionRecordResponse:
        del principal
        record = mission_store.get(mission_id)
        if record is None:
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        return _to_response(record, coverage_report_store=coverage_report_store)

    @router.get("/{mission_id}/contract")
    def get_mission_contract(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> dict[str, Any]:
        """저장된 계약 전문을 무변형 반환한다(INV-011 — 재계산·재서명 없음)."""
        del principal
        record = mission_store.get(mission_id)
        if record is None:
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        return record.contract

    return router


def mount_mission_records(
    app: FastAPI,
    *,
    mission_store: MissionStore,
    coverage_report_store: CoverageReportStore | None = None,
) -> None:
    """앱에 임무 발급 이력 조회 라우터를 장착한다."""
    app.state.mission_store = mission_store
    app.include_router(
        build_mission_records_router(
            mission_store=mission_store, coverage_report_store=coverage_report_store
        )
    )


__all__ = [
    "MISSION_NOT_FOUND_DETAIL",
    "MISSION_RECORD_HTTP_STATUS",
    "ArtifactKind",
    "MissionRecord",
    "MissionRecordResponse",
    "MissionRecordVerdict",
    "MissionIssuanceSequenceStore",
    "MissionSequenceRecoveryError",
    "MissionStore",
    "MissionStoreRecoveryError",
    "SiteLookupResult",
    "build_mission_records_router",
    "find_lone_surrogate_path",
    "mount_mission_records",
    "precheck_issuance",
    "raise_for_mission_record_verdict",
    "reject_lone_surrogates",
    "validate_mission_identifiers",
]

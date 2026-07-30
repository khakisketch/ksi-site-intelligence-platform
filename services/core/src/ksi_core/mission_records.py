"""Mission 발급 영속·목록/이력 조회 (ADR-KSI-008 §1/§3, ADR-KSI-007 짝 무결성).

발급(``mission_plans.py``/``mission_issuance.py``)이 만든 산출물을
:class:`DurableJournal` 위에 영속하고, 그 결과를 조회하는 GET 표면을 이 모듈이
소유한다. ADR-KSI-008 §3 의 "발급 레코드가 durable 기록되기 전에는 201 을
반환하지 않는다" 를 만족시키는 유일한 관문이 :meth:`MissionStore.record_issuance`
다 — 두 발급 라우터(계약 단독/짝) 모두 이 메서드를 거쳐야 201 을 낼 수 있다.

## 서명 전 사전 게이트 (site_exists·mission_id 충돌)

:func:`precheck_issuance` 는 서명(및 짝 발급의 경우 KMZ 생성)을 하기 **전에**
호출한다 — 이미 실패가 확정된 요청에 서명 비용을 치르지 않기 위해서다. 다만
이 사전 체크는 낙관적이다: 사전 체크 통과 후 실제 :meth:`~MissionStore.
record_issuance` 호출 사이에 경쟁 요청이 같은 mission_id 를 선점할 수 있으므로,
최종 판정은 항상 ``record_issuance`` 내부의 잠금 보호 구간이 한다(사전 체크는
비용 절감용 낙관적 단축 경로일 뿐, 정합성의 근원이 아니다).

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

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI

# 조회 응답에 노출하지 않는 404 일반 문구 — 열거 오라클 방지 관습(auth.py 대칭).
_MISSION_NOT_FOUND_DETAIL = "해당 임무 레코드를 찾을 수 없다"

ArtifactKind = Literal["pair", "contract"]


class MissionRecordVerdict(StrEnum):
    """발급 영속 판정. ``RECORDED`` 만 durable 기록 성공(201 자격)이다."""

    RECORDED = "RECORDED"
    MISSION_ID_CONFLICT = "MISSION_ID_CONFLICT"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    SITE_FRAME_MISMATCH = "SITE_FRAME_MISMATCH"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    INVALID_MISSION_IDENTITY = "INVALID_MISSION_IDENTITY"
    INVALID_TEXT_ENCODING = "INVALID_TEXT_ENCODING"


# verdict → HTTP status (edge_sync.py:321 관습). RECORDED 는 라우터가 201 로 직접
# 응답하므로 이 표는 거부 판정들의 상태 코드 조회용이다.
MISSION_RECORD_HTTP_STATUS: dict[MissionRecordVerdict, int] = {
    MissionRecordVerdict.RECORDED: 201,
    MissionRecordVerdict.MISSION_ID_CONFLICT: 409,
    MissionRecordVerdict.UNKNOWN_SITE: 422,
    MissionRecordVerdict.SITE_FRAME_MISMATCH: 422,
    MissionRecordVerdict.STORE_UNAVAILABLE: 503,
    MissionRecordVerdict.INVALID_MISSION_IDENTITY: 422,
    MissionRecordVerdict.INVALID_TEXT_ENCODING: 422,
}


class MissionStoreRecoveryError(RuntimeError):
    """journal 재생 중 오염 발견 — 오염된 projection 으로 기동하지 않는다(fail-closed).

    중복 ``missionId``·부정 ``artifactKind``·``contract`` 가 dict 가 아닌 레코드가
    대상이다(``sites.py`` 의 ``SiteStoreRecoveryError`` 와 대칭, 재검토 P2 item①).
    """


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
    coverage_ratio: float | None
    issued_at: datetime
    issued_by: str
    # 짝(pair) 발급 재현용 — KMZ 바이트 자체는 저장하지 않고(용량), 같은
    # missionId+동일 요청 digest 재요청을 멱등 재반환하기 위해 재생성 입력만
    # 영속한다(재검토 P2 item③). contract-only 발급은 항상 None.
    plan_request: dict[str, Any] | None = None
    plan_request_digest: str | None = None


_VALID_ARTIFACT_KINDS = frozenset({"pair", "contract"})


def _record_to_dict(record: MissionRecord) -> dict[str, Any]:
    return {
        "missionId": record.mission_id,
        "siteId": record.site_id,
        "missionType": record.mission_type,
        "artifactKind": record.artifact_kind,
        "contract": record.contract,
        "kmzSha256": record.kmz_sha256,
        "routePattern": record.route_pattern,
        "waypointCount": record.waypoint_count,
        "coverageRatio": record.coverage_ratio,
        "issuedAt": record.issued_at.isoformat(),
        "issuedBy": record.issued_by,
        "planRequest": record.plan_request,
        "planRequestDigest": record.plan_request_digest,
    }


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
    plan_request = raw.get("planRequest")
    if plan_request is not None and not isinstance(plan_request, dict):
        raise ValueError(
            f"{raw.get('missionId')!r}: planRequest 가 dict 가 아니다"
            f"({type(plan_request).__name__})"
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
        coverage_ratio=raw.get("coverageRatio"),
        issued_at=issued_at,
        issued_by=raw["issuedBy"],
        plan_request=plan_request,
        plan_request_digest=raw.get("planRequestDigest"),
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
        의 사전 체크는 낙관적 단축일 뿐 — 여기가 최종 권위다).
        """
        with self._lock:
            if record.mission_id in self._by_id:
                return MissionRecordVerdict.MISSION_ID_CONFLICT
            try:
                self._journal.append(_record_to_dict(record))
            except JournalSealedError:
                return MissionRecordVerdict.STORE_UNAVAILABLE
            self._by_id[record.mission_id] = record
            return MissionRecordVerdict.RECORDED

    def get(self, mission_id: str) -> MissionRecord | None:
        with self._lock:
            return self._by_id.get(mission_id)

    def list(self, site_id: str | None = None) -> list[MissionRecord]:
        """``(issued_at, mission_id)`` 결정적 정렬 목록(선택적 ``site_id`` 필터)."""
        with self._lock:
            records = list(self._by_id.values())
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        records.sort(key=lambda r: (r.issued_at, r.mission_id))
        return records


def precheck_issuance(
    *,
    mission_store: MissionStore,
    site_frame_lookup: Callable[[str], dict[str, Any] | None],
    site_id: str,
    mission_id: str,
    requested_site_frame: dict[str, Any],
) -> MissionRecordVerdict | None:
    """서명 전 게이트 — 통과하면 ``None``, 거부면 typed verdict.

    검사 순서(비용이 싼 순): journal 봉인 여부(재검토 P2 item⑤ — 서명·KMZ 비용을
    치르기 전에 조기 반환) → mission_id/site_id 문자 제약(item②) → site 등록 대조
    (``site_frame_lookup``) → siteFrame 일치 → mission_id 충돌.

    ``site_frame_lookup`` 은 등록된 site 의 canonical siteFrame dict(camelCase,
    ``exclude_none``)를 반환하고 미등록이면 ``None`` 이다. 요청의 siteFrame 이
    등록본과 정확히 일치하지 않으면 ``SITE_FRAME_MISMATCH`` — 계약·KMZ 짝이
    현장 등록 좌표계와 어긋난 채 발급되는 drift(ADR-KSI-007 짝 무결성의 site
    등록 대조판, INV-020)를 서명 전에 차단한다.

    낙관적 사전 체크다(모듈 docstring 참조) — 최종 권위는
    :meth:`MissionStore.record_issuance`.
    """
    if mission_store.sealed_reason is not None:
        return MissionRecordVerdict.STORE_UNAVAILABLE
    identity_verdict = validate_mission_identifiers(mission_id=mission_id, site_id=site_id)
    if identity_verdict is not None:
        return identity_verdict
    registered_frame = site_frame_lookup(site_id)
    if registered_frame is None:
        return MissionRecordVerdict.UNKNOWN_SITE
    if requested_site_frame != registered_frame:
        return MissionRecordVerdict.SITE_FRAME_MISMATCH
    if mission_store.get(mission_id) is not None:
        return MissionRecordVerdict.MISSION_ID_CONFLICT
    return None


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
    coverage_ratio: float | None
    issued_at: datetime
    issued_by: str


def _to_response(record: MissionRecord) -> MissionRecordResponse:
    return MissionRecordResponse(
        mission_id=record.mission_id,
        site_id=record.site_id,
        mission_type=record.mission_type,
        artifact_kind=record.artifact_kind,
        kmz_sha256=record.kmz_sha256,
        route_pattern=record.route_pattern,
        waypoint_count=record.waypoint_count,
        coverage_ratio=record.coverage_ratio,
        issued_at=record.issued_at,
        issued_by=record.issued_by,
    )


def build_mission_records_router(*, mission_store: MissionStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.get("", response_model=list[MissionRecordResponse])
    def list_missions(
        site_id: str | None = Query(default=None, alias="siteId"),
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> list[MissionRecordResponse]:
        del principal  # 인가만 필요 — 조회 결과에 신원을 싣지 않는다.
        return [_to_response(r) for r in mission_store.list(site_id=site_id)]

    @router.get("/{mission_id}", response_model=MissionRecordResponse)
    def get_mission(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> MissionRecordResponse:
        del principal
        record = mission_store.get(mission_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_MISSION_NOT_FOUND_DETAIL)
        return _to_response(record)

    @router.get("/{mission_id}/contract")
    def get_mission_contract(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> dict[str, Any]:
        """저장된 계약 전문을 무변형 반환한다(INV-011 — 재계산·재서명 없음)."""
        del principal
        record = mission_store.get(mission_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_MISSION_NOT_FOUND_DETAIL)
        return record.contract

    return router


def mount_mission_records(app: FastAPI, *, mission_store: MissionStore) -> None:
    """앱에 임무 발급 이력 조회 라우터를 장착한다."""
    app.state.mission_store = mission_store
    app.include_router(build_mission_records_router(mission_store=mission_store))


__all__ = [
    "MISSION_RECORD_HTTP_STATUS",
    "ArtifactKind",
    "MissionRecord",
    "MissionRecordResponse",
    "MissionRecordVerdict",
    "MissionStore",
    "MissionStoreRecoveryError",
    "build_mission_records_router",
    "find_lone_surrogate_path",
    "mount_mission_records",
    "precheck_issuance",
    "raise_for_mission_record_verdict",
    "reject_lone_surrogates",
    "validate_mission_identifiers",
]

"""Site 등록·상태머신 영속·조회·전이 (ADR-KSI-008 §1/§4).

:class:`SiteStore` 는 :mod:`ksi_core.durable_journal` 의 ``DurableJournal`` 위에
조립된 저장소다 — journal 자체의 잠금·fsync·복구 경로는 재구현하지 않는다.
조회는 재생(replay)으로 만든 인메모리 projection(``dict[site_id, SiteRecord]``)이
담당한다(ADR-KSI-008 §1).

## 감사(audit) 필드는 도메인 journal 레코드에 내장

별도 audit 저장소를 두지 않는다(ADR-KSI-008 §3) — 각 journal 레코드가 이미
``kind``·``ts``·``actor``·``before``·``after``·``evidence``·``reason`` 을 갖는
append-only 감사 원장이다. 이 store 를 끄는 경로는 어떤 역할에도 없다.

## 상태전이는 :func:`assert_site_transition` 을 통해서만

``SiteStatus``·전이표·SUSPENDED resume 규칙(저장소가 기억한 직전 상태로만
복귀)은 :mod:`ksi_domain.enums` 가 SSOT다. 이 모듈은 그 규칙을 다시 구현하지
않고 위임만 한다.

## 재생(replay) 은 fail-closed

기동 시 journal 을 재생해 projection 을 재구성한다. 오염된 레코드(미지
``kind``·참조 무결성 위반·기록된 ``before`` 와 현재 projection 상태 불일치)나
불법 전이가 재생되면 :class:`SiteStoreRecoveryError` 로 기동을 거부한다 —
``DurableJournal`` 이 이미 잡는 "JSON 파싱 실패"보다 한 단계 위의 도메인
불변식 위반을 이 계층이 잡는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import IllegalSiteTransitionError, SiteStatus, assert_site_transition
from ksi_mission_contracts.models import SiteFrame
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI


class SiteVerdict(StrEnum):
    """Site 등록/전이 판정 — verdict→HTTP 매핑은 ``_STATUS`` 가 SSOT(edge_sync.py:321 관습)."""

    REGISTERED = "REGISTERED"
    DUPLICATE_SITE_ID = "DUPLICATE_SITE_ID"
    INVALID_SITE = "INVALID_SITE"
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[SiteVerdict, int] = {
    SiteVerdict.REGISTERED: 201,
    SiteVerdict.DUPLICATE_SITE_ID: 409,
    SiteVerdict.INVALID_SITE: 422,
    SiteVerdict.TRANSITIONED: 200,
    SiteVerdict.ILLEGAL_TRANSITION: 409,
    SiteVerdict.UNKNOWN_SITE: 404,
    SiteVerdict.STORE_UNAVAILABLE: 503,
}

_SITE_NOT_FOUND_DETAIL = "현장을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = "journal 봉인됨 — 재시작 필요"


class SiteStoreRecoveryError(RuntimeError):
    """journal 재생 중 오염·불법 전이 발견 — 오염된 projection 으로 기동하지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class SiteRecord:
    """Site projection 레코드 1건. 시각 필드는 tz-aware 만 입력받고 UTC 로 정규화해 저장한다."""

    site_id: str
    name: str
    site_frame: dict[str, Any]
    status: SiteStatus
    resume_target: SiteStatus | None
    registered_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.registered_at.tzinfo is None:
            raise ValueError("registered_at 은 tz-aware 여야 한다 — naive datetime 거부")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at 은 tz-aware 여야 한다 — naive datetime 거부")
        # docstring 의 "UTC 만 허용" 주장을 실제로 강제한다(events.py `_iso` 관습
        # 대칭) — tz-aware 이기만 하면 통과시키던 이전 동작은 다른 오프셋(예:
        # +09:00)이 그대로 저장돼 문서 주장과 어긋났다. frozen dataclass 라
        # object.__setattr__ 로 정규화한다.
        object.__setattr__(self, "registered_at", self.registered_at.astimezone(UTC))
        object.__setattr__(self, "updated_at", self.updated_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class SiteResult:
    """register/transition 의 typed 결과 — verdict + (성공 시) record + (실패 시) detail."""

    verdict: SiteVerdict
    record: SiteRecord | None = None
    detail: str | None = None


def _parse_ts(value: str) -> datetime:
    """journal 레코드의 ``ts`` 를 tz-aware datetime 으로 파싱한다. naive 는 거부(fail-closed)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"ts 가 naive datetime: {value!r}")
    return parsed


def _has_lone_surrogate(value: str) -> bool:
    """UTF-8 로 인코딩 불가능한 lone surrogate 코드포인트 포함 여부.

    이런 문자열은 journal 자체 기록(``ensure_ascii=True`` 라 통과)은 깨지지
    않지만, 이후 응답 렌더링(Starlette ``JSONResponse`` 의 UTF-8 인코딩, Pydantic
    ``model_dump_json``)이 ``UnicodeEncodeError`` 로 500 붕괴한다 — 등록·전이
    경계에서 미리 typed 422(``INVALID_SITE``)로 거부한다.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


_FRAME_FIELDS: tuple[str, ...] = ("crs", "vertical_datum", "transform_version")
_FRAME_FIELD_ALIASES: dict[str, str] = {
    "crs": "crs",
    "vertical_datum": "verticalDatum",
    "transform_version": "transformVersion",
}


class SiteStore:
    """Site 상태머신 영속·조회·전이. ``DurableJournal`` 위의 인메모리 projection.

    동시성: 프로세스 내 여러 스레드가 공유할 수 있으므로(FastAPI sync 라우트는
    스레드풀에서 돈다) 중복 체크·전이 검증·append·projection 갱신을 한 임계구역으로
    묶는다(edge_sync.py ``EdgeSyncStore`` 관습 대칭).
    """

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._sites: dict[str, SiteRecord] = {}
        self._lock = threading.Lock()
        try:
            self._replay(journal)
        except BaseException:
            # __init__ 이 예외로 끝나면 이 인스턴스는 존재하지 않는다 — 하지만
            # journal 은 flock 을 이미 쥔 채다. close() 없이는 그 flock 이
            # 프로세스 수명 내내 잔존해(2차 독립 재검토 P2) 재시도 재조립조차
            # "다른 프로세스가 소유 중" 으로 오도한다.
            journal.close()
            raise

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                kind = raw["kind"]
                if kind == "site-registered":
                    self._apply_registered(raw)
                elif kind == "site-transitioned":
                    self._apply_transitioned(raw)
                else:
                    raise ValueError(f"알 수 없는 kind: {kind!r}")
            except (KeyError, ValueError, TypeError) as exc:
                raise SiteStoreRecoveryError(
                    f"site journal 재생 실패 — 오염되거나 불법 전이가 기록됨: {exc}"
                ) from exc

    # ── projection 갱신(재생·실전이 공용) ──────────────────────────────
    def _apply_registered(self, raw: dict[str, Any]) -> None:
        """등록 레코드를 projection 에 반영한다.

        재생 경로에서도 API 경계(:meth:`register`)와 같은 강도로 검증한다 —
        journal 이 버그·직접 조작으로 INV-020 비공백 규칙을 위반한 레코드를
        담고 있다면(예: 과거 register() 검증을 우회한 레코드가 어떻게든
        기록됨) 조용히 재생하지 않는다(재검토 지적 #2/#3).
        """
        site_id = raw["siteId"]
        name = raw["name"]
        site_frame = raw["siteFrame"]
        if site_id in self._sites:
            raise ValueError(f"중복 등록 레코드: siteId={site_id}")
        if not isinstance(site_id, str) or not site_id.strip():
            raise ValueError(f"재생: siteId 가 비공백 문자열이 아니다: {site_id!r}")
        if not is_path_safe_identifier(site_id):
            raise ValueError(f"재생: siteId 가 경로-안전 문자가 아니다: {site_id!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"재생: name 이 비공백 문자열이 아니다: {name!r}")
        if _has_lone_surrogate(site_id) or _has_lone_surrogate(name):
            raise ValueError(
                f"재생: siteId·name 에 처리할 수 없는 문자가 포함됨: siteId={site_id!r}"
            )
        if not isinstance(site_frame, dict):
            raise ValueError(f"재생: siteFrame 이 object 가 아니다: siteId={site_id}")
        for alias in _FRAME_FIELD_ALIASES.values():
            value = site_frame.get(alias)
            if not isinstance(value, str) or not value.strip() or _has_lone_surrogate(value):
                raise ValueError(
                    f"재생: siteFrame.{alias} 가 INV-020 비공백 요건을 위반: siteId={site_id}"
                )
        ts = _parse_ts(raw["ts"])
        self._sites[site_id] = SiteRecord(
            site_id=site_id,
            name=name,
            site_frame=site_frame,
            status=SiteStatus.UNMAPPED,
            resume_target=None,
            registered_at=ts,
            updated_at=ts,
        )

    def _apply_transitioned(self, raw: dict[str, Any]) -> None:
        """전이 레코드를 projection 에 반영한다.

        재생 경로에서도 evidence·reason 비공백을 재검증한다(재검토 지적 #3) —
        API 경계(:meth:`transition`)만 지키던 게이트를 재생에서도 강제한다.
        """
        site_id = raw["siteId"]
        current = self._sites.get(site_id)
        if current is None:
            raise ValueError(f"미지 siteId 전이 레코드: {site_id}")
        evidence = raw.get("evidence")
        reason = raw.get("reason")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"재생: evidence 가 비공백 문자열이 아니다: siteId={site_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"재생: reason 이 비공백 문자열이 아니다: siteId={site_id}")
        before = SiteStatus(raw["before"])
        if before is not current.status:
            raise ValueError(
                f"재생 상태 불일치: siteId={site_id} before={before.value} "
                f"projection={current.status.value}"
            )
        after = SiteStatus(raw["after"])
        # 재생 시에도 전이 적법성을 다시 검증한다 — 과거에 불법 전이가 어떻게든
        # journal 에 기록됐다면(버그·직접 조작) 조용히 재생하지 않는다.
        assert_site_transition(current.status, after, resume_target=current.resume_target)
        ts = _parse_ts(raw["ts"])
        resume_target = current.status if after is SiteStatus.SUSPENDED else None
        self._sites[site_id] = replace(
            current, status=after, resume_target=resume_target, updated_at=ts
        )

    # ── 공개 API ────────────────────────────────────────────────────
    def register(
        self,
        site_id: str,
        name: str,
        site_frame: SiteFrame,
        *,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """신규 Site 를 등록한다. 초기 상태는 항상 ``UNMAPPED``(최종상태 직접 등록 금지)."""
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            if not site_id.strip():
                return SiteResult(SiteVerdict.INVALID_SITE, detail="siteId 는 비공백이어야 한다")
            if not is_path_safe_identifier(site_id):
                # siteId 는 그대로 /v1/sites/{site_id} 의 경로 세그먼트가 된다
                # (2차 독립 재검토 P2) — '/'·공백을 허용하면 durable 등록은
                # 성공하고 이후 상세 조회·전이 라우트에 영구히 도달할 수 없는
                # site 가 만들어진다(mission_records.py 의 동일 클래스 방어와
                # 대칭 — ksi_core.identifiers 가 SSOT).
                return SiteResult(
                    SiteVerdict.INVALID_SITE, detail="siteId 는 경로-안전 문자만 허용한다"
                )
            if not name.strip():
                return SiteResult(SiteVerdict.INVALID_SITE, detail="name 은 비공백이어야 한다")
            if _has_lone_surrogate(site_id) or _has_lone_surrogate(name):
                # journal 자체 기록(ensure_ascii=True)은 통과하지만 이후 응답
                # 렌더링(UTF-8 인코딩)이 500 으로 붕괴한다 — 등록 경계에서 거부.
                return SiteResult(
                    SiteVerdict.INVALID_SITE,
                    detail="siteId·name 에 처리할 수 없는 문자가 포함됨",
                )
            # INV-020 — CRS·수직기준·변환버전이 공백이면 좌표계 식별이 불가능한
            # 무의미한 frame 이다. 공유 SiteFrame 모델은 타입만 강제하므로(다른
            # 소비자 호환) 등록 경계에서 비공백을 추가로 강제한다.
            for frame_field in _FRAME_FIELDS:
                value = getattr(site_frame, frame_field)
                if not value.strip() or _has_lone_surrogate(value):
                    return SiteResult(
                        SiteVerdict.INVALID_SITE,
                        detail=(
                            "siteFrame 의 crs·verticalDatum·transformVersion 은 "
                            "비공백·유효 문자여야 한다"
                        ),
                    )
            if site_id in self._sites:
                return SiteResult(SiteVerdict.DUPLICATE_SITE_ID, detail="이미 등록된 siteId")

            raw: dict[str, Any] = {
                "kind": "site-registered",
                "ts": now.isoformat(),
                "actor": actor,
                "before": None,
                "after": SiteStatus.UNMAPPED.value,
                "evidence": None,
                "reason": None,
                "siteId": site_id,
                "name": name,
                "siteFrame": site_frame.model_dump(by_alias=True, mode="json", exclude_none=True),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            self._apply_registered(raw)
            return SiteResult(SiteVerdict.REGISTERED, record=self._sites[site_id])

    def transition(
        self,
        site_id: str,
        target: SiteStatus,
        *,
        evidence: str,
        reason: str,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """Site 상태를 전이한다. evidence·reason 은 비공백 필수.

        ``SUSPENDED`` 진입 시 저장소가 진입 직전 상태를 ``resume_target`` 으로
        기억한다. ``SUSPENDED`` 이탈은 그 기억과 대조해서만 허용된다
        (:func:`~ksi_domain.enums.assert_site_transition` 위임).
        """
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            if not evidence.strip():
                return SiteResult(SiteVerdict.INVALID_SITE, detail="evidence 는 비공백이어야 한다")
            if not reason.strip():
                return SiteResult(SiteVerdict.INVALID_SITE, detail="reason 은 비공백이어야 한다")

            current = self._sites.get(site_id)
            if current is None:
                return SiteResult(SiteVerdict.UNKNOWN_SITE, detail=_SITE_NOT_FOUND_DETAIL)

            try:
                assert_site_transition(current.status, target, resume_target=current.resume_target)
            except IllegalSiteTransitionError as exc:
                return SiteResult(SiteVerdict.ILLEGAL_TRANSITION, detail=str(exc))

            raw: dict[str, Any] = {
                "kind": "site-transitioned",
                "ts": now.isoformat(),
                "actor": actor,
                "before": current.status.value,
                "after": target.value,
                "evidence": evidence,
                "reason": reason,
                "siteId": site_id,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            self._apply_transitioned(raw)
            return SiteResult(SiteVerdict.TRANSITIONED, record=self._sites[site_id])

    def get(self, site_id: str) -> SiteRecord | None:
        with self._lock:
            return self._sites.get(site_id)

    def list(self) -> list[SiteRecord]:
        """site_id 정렬 결정적 목록."""
        with self._lock:
            return [self._sites[key] for key in sorted(self._sites)]


# ── FastAPI 장착부 ────────────────────────────────────────────────────


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SiteRegistrationRequest(_CamelModel):
    site_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    site_frame: SiteFrame


class SiteTransitionRequest(_CamelModel):
    """전이 요청 — ``actor`` 는 의도적으로 필드가 없다(인증 Principal 에서만 취득,

    ``extra="forbid"`` 가 body 에 ``actor`` 를 실어도 위조를 거부한다).
    """

    target_status: SiteStatus
    evidence: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SiteView(_CamelModel):
    site_id: str
    name: str
    site_frame: dict[str, Any]
    status: str
    resume_target: str | None
    registered_at: str
    updated_at: str


class SiteListResponse(_CamelModel):
    sites: list[SiteView]


class SiteMutationResponse(_CamelModel):
    """등록/전이 응답 — 성공은 ``site`` 를, 실패는 ``detail`` 을 채운다(verdict 로 구분)."""

    verdict: str
    site: SiteView | None = None
    detail: str | None = None


def _to_view(record: SiteRecord) -> SiteView:
    return SiteView(
        site_id=record.site_id,
        name=record.name,
        site_frame=record.site_frame,
        status=record.status.value,
        resume_target=record.resume_target.value if record.resume_target is not None else None,
        registered_at=record.registered_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def build_sites_router(store: SiteStore) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["sites"])

    @router.post("", response_model=SiteMutationResponse)
    def register_site(
        request: SiteRegistrationRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        result = store.register(
            request.site_id,
            request.name,
            request.site_frame,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        return SiteMutationResponse(
            verdict=result.verdict.value,
            site=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get("", response_model=SiteListResponse)
    def list_sites(
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> SiteListResponse:
        return SiteListResponse(sites=[_to_view(r) for r in store.list()])

    @router.get("/{site_id}", response_model=SiteView)
    def get_site(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> SiteView:
        record = store.get(site_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_SITE_NOT_FOUND_DETAIL)
        return _to_view(record)

    @router.post("/{site_id}/transitions", response_model=SiteMutationResponse)
    def transition_site(
        site_id: str,
        request: SiteTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        result = store.transition(
            site_id,
            request.target_status,
            evidence=request.evidence,
            reason=request.reason,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        return SiteMutationResponse(
            verdict=result.verdict.value,
            site=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    return router


def mount_sites(app: FastAPI, store: SiteStore) -> None:
    """앱에 Site 라우터를 장착한다 — store 없이는 엔드포인트가 존재하지 않는다."""
    app.state.site_store = store
    app.include_router(build_sites_router(store))

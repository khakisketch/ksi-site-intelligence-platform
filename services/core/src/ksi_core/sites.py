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

## AOI(Area of Interest) 는 site 에 영속되고 UNMAPPED 에서만 바뀐다

AOI 표현은 :mod:`ksi_mission_planning.geometry` 의 :class:`AreaOfInterest` 를
그대로 재사용한다(닫힌 단순 폴리곤 검증이 이미 그쪽 fail-closed 게이트에
있다 — 여기서 재구현하지 않는다). 등록 시 선택적으로 함께 줄 수 있고
(:meth:`register`), 이미 등록된 site 는 :meth:`set_aoi` 로 나중에 설정·교체한다.

AOI 교체는 ``SiteStatus.UNMAPPED`` 에서만 허용한다(막는 쪽이 기본) — 매핑이
한 번이라도 시작되면(``BASELINE_MAPPING`` 이후) 조용히 외곽을 바꾸지 못하게
잠근다. ``REMAP_REQUIRED`` 도 예외를 두지 않는다 — 재매핑 전 외곽을 다시
그리고 싶다면 이 버전의 범위 밖(새 site 로 재등록)이다.

**주의(독립 재검토 D4, 문구 정정)**: 이 잠금은 "이미 발급된 임무·누적 중인
커버리지와의 대조가 무너진다"를 막는 게 **아니다** — 그런 대조 자체가
코드에 없다. :func:`~ksi_core.mission_records.precheck_issuance` 는
``site.aoi`` 를 전혀 보지 않고, 짝 발급(``mission_plans.py``)은 매 요청이
실어 보내는 ``request.aoi`` 를 그대로 쓴다 — **임무 AOI 와 현장 AOI 는
현재 대조되지 않는다.** 이 잠금의 실질 효과는 UI 초기값(``SurveyWizard``가
현장 AOI 를 새 임무의 기본 구역으로 채우는 지점)을 고정하는 것뿐이다. 임무
AOI 를 현장 AOI 에 실제로 대조할지는 별도 제품 결정 대상이다(이 모듈이
임의로 게이트를 추가하지 않는다).

## 데이터 반출 허용은 현장의 속성이다 (INV-050)

``data_residency`` 는 등록 시점에만 선언되고 이후 바뀌지 않는다. 이 값을
처리 작업 발급 요청이 실어 보내지 않는 것이 요점이다 — 요청이 자기 반출
허가서를 쓰면 INV-050 은 게이트가 아니라 장식이 된다(``processing_jobs.py``
가 이 필드를 읽는 유일한 소비자다). 선언하지 않은 현장은 ``None`` 이고,
``None`` 은 "아직 모른다"가 아니라 **반출 불가**로 읽힌다 — 이 필드 도입
이전에 기록된 journal 레코드가 전부 ``None`` 으로 재생되기 때문에, 기본을
허용 쪽에 두면 기존 현장 전체가 조용히 반출 가능해진다.

``set_aoi`` 는 호출자가 재확인하는 ``site_frame`` 이 등록본과 정확히
일치해야 한다(``SITE_FRAME_MISMATCH``) — 다른 좌표계를 전제로 그려진 AOI 가
섞여 들어오는 것을 막는다(:func:`~ksi_core.mission_records.precheck_issuance`
의 동일 관용구 재사용, ADR-KSI-007).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import (
    IllegalSiteTransitionError,
    SiteStatus,
    assert_site_transition,
    requires_autonomy_approval,
)
from ksi_event_contracts.processing_job import DataResidency
from ksi_mission_contracts.models import SiteFrame
from ksi_mission_planning import AreaOfInterest
from pydantic import Field

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, principal_permissions, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI


class SiteVerdict(StrEnum):
    """Site 등록/전이/AOI 판정 — verdict→HTTP 매핑은 ``_STATUS`` 가 SSOT(edge_sync.py:321 관습)."""

    REGISTERED = "REGISTERED"
    DUPLICATE_SITE_ID = "DUPLICATE_SITE_ID"
    INVALID_SITE = "INVALID_SITE"
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    AOI_SET = "AOI_SET"
    SITE_FRAME_MISMATCH = "SITE_FRAME_MISMATCH"
    AOI_LOCKED = "AOI_LOCKED"
    MODEL_AGE_POLICY_SET = "MODEL_AGE_POLICY_SET"


_STATUS: dict[SiteVerdict, int] = {
    SiteVerdict.REGISTERED: 201,
    SiteVerdict.DUPLICATE_SITE_ID: 409,
    SiteVerdict.INVALID_SITE: 422,
    SiteVerdict.TRANSITIONED: 200,
    SiteVerdict.ILLEGAL_TRANSITION: 409,
    SiteVerdict.UNKNOWN_SITE: 404,
    SiteVerdict.STORE_UNAVAILABLE: 503,
    SiteVerdict.AOI_SET: 200,
    SiteVerdict.SITE_FRAME_MISMATCH: 422,
    SiteVerdict.AOI_LOCKED: 409,
    SiteVerdict.MODEL_AGE_POLICY_SET: 200,
}

_SITE_NOT_FOUND_DETAIL = "현장을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = JOURNAL_SEALED_DETAIL


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
    # AreaOfInterest.model_dump(by_alias=True, mode="json", exclude_none=True) —
    # site_frame 과 동일 관습으로 파싱된 모델이 아니라 검증-후 dict 로 보관한다.
    # 아직 AOI 를 설정하지 않은 site(또는 구버전 journal 레코드)는 None.
    aoi: dict[str, Any] | None = None
    # INV-050 이 읽는 데이터 절반 — 이 현장의 반출 허용 여부·관할.
    # None 은 "선언되지 않았다"이고 **반출 불가로 읽힌다**(fail-closed). 구버전
    # journal 레코드가 이 값을 가질 수 없으므로 기본을 허용 쪽에 둘 수 없다.
    data_residency: dict[str, Any] | None = None
    # 이 현장의 공간모델 노후 판정 기준(일). ``None`` 은 **미선언**이고, 미선언은
    # "최신"이 아니라 "판정하지 않음"으로 읽힌다
    # (:mod:`ksi_core.spatial_model` 의 ``AGE_POLICY_UNDECLARED``).
    # MASTER_PRD §6.3 은 ``MODEL_STALE`` 이라는 상태만 정의하고 며칠이면 낡은
    # 것인지는 정하지 않았다 — 서버가 기본값을 박으면 근거 없는 숫자가 현장의
    # 자율운영 가능 여부를 가른다(ADR-KSI-019 G1). ``data_residency`` 와 같은
    # 이유로 구버전 journal 레코드는 전부 ``None`` 으로 재생된다.
    model_max_age_days: int | None = None

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
    """journal 레코드의 ``ts`` 를 tz-aware datetime 으로 파싱한다. naive 는 거부(fail-closed).

    UTC 로 정규화해 돌려준다 — 정규화 도입 이전에 기록된 오프셋 표기 레코드도
    재생 후에는 같은 표현이 되어, projection 이 기록 시점에 따라 달라지지 않는다.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"ts 가 naive datetime: {value!r}")
    return parsed.astimezone(UTC)


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
                elif kind == "site-aoi-set":
                    self._apply_aoi_set(raw)
                elif kind == "site-model-age-policy-set":
                    self._apply_model_age_policy_set(raw)
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
        # aoi 는 선택 필드다 — 키 자체가 없는 구버전 레코드(이 필드 도입 이전에
        # 기록됨)도 raw.get 이 None 을 주므로 그대로 통과한다(회귀 없음).
        aoi_payload = raw.get("aoi")
        if aoi_payload is not None:
            if not isinstance(aoi_payload, dict):
                raise ValueError(f"재생: aoi 가 object 가 아니다: siteId={site_id}")
            AreaOfInterest.model_validate(aoi_payload)  # fail-closed 재검증(API 경계와 동일 강도)
        # aoi 와 같은 선택 필드 관습 — 키가 없는 구버전 레코드는 None 으로 재생되고,
        # None 은 반출 미선언(= 불가)이라 게이트가 느슨해지지 않는다.
        residency_payload = raw.get("dataResidency")
        if residency_payload is not None:
            if not isinstance(residency_payload, dict):
                raise ValueError(f"재생: dataResidency 가 object 가 아니다: siteId={site_id}")
            DataResidency.model_validate(residency_payload)  # fail-closed 재검증
        ts = _parse_ts(raw["ts"])
        self._sites[site_id] = SiteRecord(
            site_id=site_id,
            name=name,
            site_frame=site_frame,
            status=SiteStatus.UNMAPPED,
            resume_target=None,
            registered_at=ts,
            updated_at=ts,
            aoi=aoi_payload,
            data_residency=residency_payload,
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

    def _apply_aoi_set(self, raw: dict[str, Any]) -> None:
        """AOI 설정/교체 레코드를 projection 에 반영한다.

        재생 경로에서도 UNMAPPED 게이트를 재검증한다(``_apply_transitioned`` 와
        동일 원칙 — API 경계만 지키던 불변식을 재생이 조용히 우회하지 않는다).
        ``site_frame`` 일치 여부는 여기서 다시 보지 않는다 — 그 값 자체는
        journal 레코드에 싣지 않으며(불변이라 site 등록본과 항상 같다), 저장된
        건 "이 site 의 AOI 가 이제 이 값이다"라는 사실뿐이다.

        ``ts`` 는 형제 레코드(``site-registered``·``site-transitioned``)와 같은
        강도로 검증한다(독립 재검토 D2) — naive datetime 을 fail-closed 거부하고,
        그 값으로 ``updated_at`` 을 갱신한다. 이전에는 이 레코드가 ``ts`` 를 읽지도
        않아 ``PUT /v1/sites/{id}/aoi`` 로 외곽을 바꿔도 "최근 갱신"이 등록 시각
        그대로 멎어 있었다.
        """
        site_id = raw["siteId"]
        current = self._sites.get(site_id)
        if current is None:
            raise ValueError(f"미지 siteId AOI 설정 레코드: {site_id}")
        if current.status is not SiteStatus.UNMAPPED:
            raise ValueError(
                f"재생: UNMAPPED 가 아닌 상태({current.status.value})에서 AOI 설정 레코드가 "
                f"발견됨 — 재검증 위반: siteId={site_id}"
            )
        aoi_payload = raw["aoi"]
        if not isinstance(aoi_payload, dict):
            raise ValueError(f"재생: aoi 가 object 가 아니다: siteId={site_id}")
        AreaOfInterest.model_validate(aoi_payload)  # fail-closed 재검증
        ts = _parse_ts(raw["ts"])
        self._sites[site_id] = replace(current, aoi=aoi_payload, updated_at=ts)

    def _apply_model_age_policy_set(self, raw: dict[str, Any]) -> None:
        """공간모델 노후 기준 선언·철회 레코드를 projection 에 반영한다.

        ``_apply_aoi_set`` 과 같은 강도로 재검증한다 — 미지 site 면 재생을 거부하고
        (fail-closed), 값은 ``None``(철회) 또는 1 이상 정수만 허용한다. 손으로 고친
        원장이 0 일·음수 기준을 되살릴 수 없다.

        AOI 와 달리 **현장 상태 게이트는 없다** — 이 값은 매핑 시작 이후에도 바뀌는
        것이 정상이다(:meth:`set_model_age_policy` docstring).
        """
        site_id = raw["siteId"]
        current = self._sites.get(site_id)
        if current is None:
            raise ValueError(f"미지 siteId 노후 기준 선언 레코드: {site_id}")
        max_age_days = raw["maxAgeDays"]
        if max_age_days is not None and (
            not isinstance(max_age_days, int)
            or isinstance(max_age_days, bool)
            or max_age_days < 1
        ):
            raise ValueError(
                f"재생: maxAgeDays 는 null 이거나 1 이상 정수여야 한다: "
                f"siteId={site_id} value={max_age_days!r}"
            )
        ts = _parse_ts(raw["ts"])
        self._sites[site_id] = replace(
            current, model_max_age_days=max_age_days, updated_at=ts
        )

    # ── 공개 API ────────────────────────────────────────────────────
    def register(
        self,
        site_id: str,
        name: str,
        site_frame: SiteFrame,
        *,
        aoi: AreaOfInterest | None = None,
        data_residency: DataResidency | None = None,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """신규 Site 를 등록한다. 초기 상태는 항상 ``UNMAPPED``(최종상태 직접 등록 금지).

        ``aoi`` 는 선택이다 — 등록 시점에 함께 주지 않아도 되고, 나중에
        :meth:`set_aoi` 로 설정할 수 있다(모듈 docstring "AOI 는 site 에
        영속되고 UNMAPPED 에서만 바뀐다" 참조). 구조 검증(닫힌 단순 폴리곤 등)은
        :class:`~ksi_mission_planning.geometry.AreaOfInterest` 파싱 시점(FastAPI
        요청 본문 검증)에 이미 끝나 있다 — 여기서 재검증하지 않는다.
        """
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
                "ts": iso_utc(now),
                "actor": actor,
                "before": None,
                "after": SiteStatus.UNMAPPED.value,
                "evidence": None,
                "reason": None,
                "siteId": site_id,
                "name": name,
                "siteFrame": site_frame.model_dump(by_alias=True, mode="json", exclude_none=True),
                "aoi": (
                    None
                    if aoi is None
                    else aoi.model_dump(by_alias=True, mode="json", exclude_none=True)
                ),
                "dataResidency": (
                    None
                    if data_residency is None
                    else data_residency.model_dump(by_alias=True, mode="json")
                ),
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
                "ts": iso_utc(now),
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

    def set_aoi(
        self,
        site_id: str,
        aoi: AreaOfInterest,
        *,
        site_frame: SiteFrame,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """Site 의 AOI 를 설정하거나 교체한다.

        검사 순서(독립 재검토 D7 — 상태 게이트가 형식 검사보다 먼저): ``UNMAPPED``
        가 아닌 상태에서는 ``site_frame`` 이 맞고 틀리고와 무관하게 ``AOI_LOCKED``
        다 — 이미 잠긴 현장에 좌표계까지 틀린 요청을 보내면, 좌표계를 고쳐 재시도한
        뒤에야 "애초에 잠겼다"는 사실을 듣는 순서를 피한다. ``UNMAPPED`` 를 통과한
        뒤에만 ``site_frame`` 을 등록본과 대조한다(``SITE_FRAME_MISMATCH`` — 다른
        좌표계를 전제로 그려진 AOI 를 수락하지 않는다, ``mission_records.
        precheck_issuance`` 와 동일 관용구).

        **주의(독립 재검토 D4)**: ``AOI_LOCKED`` 는 "이미 발급된 임무·누적 중인
        커버리지와의 대조가 무너진다"를 막는 게 아니다 — 그런 대조 자체가 코드에
        없다(모듈 docstring "AOI 는 site 에 영속되고 UNMAPPED 에서만 바뀐다" 참조).
        실질 효과는 UI 초기값을 고정하는 것뿐이다.
        """
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)

            current = self._sites.get(site_id)
            if current is None:
                return SiteResult(SiteVerdict.UNKNOWN_SITE, detail=_SITE_NOT_FOUND_DETAIL)

            if current.status is not SiteStatus.UNMAPPED:
                return SiteResult(
                    SiteVerdict.AOI_LOCKED,
                    detail=(
                        f"AOI 는 UNMAPPED 상태에서만 설정·교체할 수 있다(현재 "
                        f"{current.status.value}) — 매핑이 시작된 뒤에는 잠근다(임무 AOI 와 "
                        "현장 AOI 는 현재 대조되지 않는다 — 이 잠금은 UI 초기값을 고정하는 "
                        "효과뿐이다)"
                    ),
                )

            requested_frame = site_frame.model_dump(by_alias=True, mode="json", exclude_none=True)
            if requested_frame != current.site_frame:
                return SiteResult(
                    SiteVerdict.SITE_FRAME_MISMATCH,
                    detail=(
                        "siteFrame 이 등록된 현장과 다르다 — 다른 좌표계를 전제로 그려진 "
                        "AOI 는 수락하지 않는다"
                    ),
                )

            raw: dict[str, Any] = {
                "kind": "site-aoi-set",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "aoi": aoi.model_dump(by_alias=True, mode="json", exclude_none=True),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            self._apply_aoi_set(raw)
            return SiteResult(SiteVerdict.AOI_SET, record=self._sites[site_id])

    def set_model_age_policy(
        self,
        site_id: str,
        *,
        max_age_days: int | None,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """이 현장의 공간모델 노후 판정 기준(일)을 선언·교체·철회한다(ADR-KSI-019 G1).

        ``max_age_days=None`` 은 **철회**다 — 되돌릴 수 없는 정책은 정책이 아니다.
        철회하면 :func:`~ksi_core.spatial_model.evaluate_spatial_model` 이 노후를
        판정하지 않고 ``AGE_POLICY_UNDECLARED`` 를 낸다.

        AOI 와 달리 **현장 상태로 잠그지 않는다**. 현장의 변화 속도는 매핑이 시작된
        뒤에 알게 되는 사실이고, 그때 기준을 못 고치면 정책이 첫 추측에 갇힌다.
        AOI 잠금의 근거(UI 초기값 고정)는 여기에 해당하지 않는다.

        0 일·음수는 거부한다 — "매 순간 낡음"은 정책이 아니라 사고이고, 그 값이
        기록되면 그 현장은 자율운영에서 영구히 끊긴다.
        """
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        if max_age_days is not None and max_age_days < 1:
            return SiteResult(
                SiteVerdict.INVALID_SITE,
                detail=(
                    "maxAgeDays 는 1 이상이어야 한다 — 0·음수는 '매 순간 낡음'이라 "
                    "정책이 아니라 사고다"
                ),
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)

            current = self._sites.get(site_id)
            if current is None:
                return SiteResult(SiteVerdict.UNKNOWN_SITE, detail=_SITE_NOT_FOUND_DETAIL)

            raw: dict[str, Any] = {
                "kind": "site-model-age-policy-set",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "before": current.model_max_age_days,
                "maxAgeDays": max_age_days,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            self._apply_model_age_policy_set(raw)
            return SiteResult(
                SiteVerdict.MODEL_AGE_POLICY_SET, record=self._sites[site_id]
            )

    def get(self, site_id: str) -> SiteRecord | None:
        with self._lock:
            return self._sites.get(site_id)

    def list(self) -> list[SiteRecord]:
        """site_id 정렬 결정적 목록."""
        with self._lock:
            return [self._sites[key] for key in sorted(self._sites)]


# ── FastAPI 장착부 ────────────────────────────────────────────────────


class SiteRegistrationRequest(CamelModel):
    site_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    site_frame: SiteFrame
    # 선택 필드 — 필수로 하면 이미 등록된 site·기존 위저드 흐름이 깨진다. 나중에
    # 설정·교체하려면 PUT /v1/sites/{site_id}/aoi (AoiSetRequest 참조).
    aoi: AreaOfInterest | None = None
    # 선택 필드지만 미지정은 "반출 불가"로 확정된다 — 생략이 관대한 기본값을
    # 뜻하지 않는다(INV-050). 등록 이후 변경 경로는 의도적으로 없다: 반출 허용
    # 토글은 법적 판단이라 SITES_WRITE 로 조용히 바꿀 수 있는 값이 아니다.
    # 변경이 필요해지면 그때 권한과 승인 절차를 별도로 정한다.
    data_residency: DataResidency | None = None


class SiteTransitionRequest(CamelModel):
    """전이 요청 — ``actor`` 는 의도적으로 필드가 없다(인증 Principal 에서만 취득,

    ``extra="forbid"`` 가 body 에 ``actor`` 를 실어도 위조를 거부한다).
    """

    target_status: SiteStatus
    evidence: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AoiSetRequest(CamelModel):
    """PUT /v1/sites/{site_id}/aoi 요청 — 등록/교체 공용.

    ``site_frame`` 은 필수다 — 호출자가 등록본과 같은 좌표계를 전제로 그렸음을
    재확인시킨다(SITE_FRAME_MISMATCH 게이트, ``SiteStore.set_aoi`` 참조).
    """

    aoi: AreaOfInterest
    site_frame: SiteFrame


class ModelAgePolicyRequest(CamelModel):
    """PUT /v1/sites/{site_id}/model-age-policy 요청 — 선언·교체·철회 공용.

    ``max_age_days`` 는 **필수 필드이고 null 을 허용**한다. 생략 가능하게 두면
    "필드를 안 보냄"과 "철회"가 같은 요청이 되어, 부분 갱신 의도로 보낸 요청이
    조용히 기준을 지운다.
    """

    max_age_days: int | None = Field(
        description="공간모델 노후 판정 기준(일). null 이면 철회 — 노후를 판정하지 않는다."
    )


class SiteView(CamelModel):
    site_id: str
    name: str
    site_frame: dict[str, Any]
    status: str
    resume_target: str | None
    registered_at: str
    updated_at: str
    # 설정된 적 없으면 null — "AOI 가 없다"와 "아직 조회 안 됐다"를 응답 자체가
    # 구분한다(대시보드가 이 값 하나로 지도/빈 상태를 분기한다).
    aoi: dict[str, Any] | None
    # 미선언이면 null 을 그대로 노출한다 — 화면이 "반출 허용"을 기본값처럼
    # 보여주지 않게. null 의 뜻은 "반출 불가"다(SiteRecord.data_residency).
    data_residency: dict[str, Any] | None
    # 미선언이면 null. null 의 뜻은 "노후를 판정하지 않는다"이지 "최신"이 아니다
    # (SiteRecord.model_max_age_days, ADR-KSI-019 G1).
    model_max_age_days: int | None = None


class SiteListResponse(CamelModel):
    sites: list[SiteView]


class SiteMutationResponse(CamelModel):
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
        aoi=record.aoi,
        data_residency=record.data_residency,
        model_max_age_days=record.model_max_age_days,
    )


def build_sites_router(store: SiteStore) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["sites"])

    # status_code 는 **실제 주 성공 경로**를 선언한다(런타임 실측 201).
    # response.status_code 로 동적 지정만 하면 FastAPI 가 OpenAPI 에 200 을 남겨,
    # 생성된 계약이 실제와 다른 코드를 말하게 된다(2026-08-04 확인).
    @router.post("", response_model=SiteMutationResponse, status_code=201)
    def register_site(
        request: SiteRegistrationRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        result = store.register(
            request.site_id,
            request.name,
            request.site_frame,
            aoi=request.aoi,
            data_residency=request.data_residency,
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
        # 2차 게이트(ADR-KSI-015 D2) — SITES_WRITE 는 기본 하한이고, blast radius
        # 큰 간선(자율 시작 승인·정식 순찰 승인·SUSPENDED 진입/복귀)은 추가로
        # SITES_AUTONOMY_APPROVE 를 요구한다. 간선 쌍(현재 상태 → 요청 상태)
        # 기준 판정이다 — 대상 site 가 없으면(current is None) 판정할 "현재
        # 상태"가 없으므로 건너뛰고 아래 store.transition() 이 UNKNOWN_SITE 로
        # 응답한다.
        current = store.get(site_id)
        if (
            current is not None
            and requires_autonomy_approval(current.status, request.target_status)
            and Permission.SITES_AUTONOMY_APPROVE not in principal_permissions(principal)
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{current.status.value} → {request.target_status.value} 전이는 "
                    "자율운영 승인 권한이 필요하다"
                ),
            )
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

    @router.put("/{site_id}/aoi", response_model=SiteMutationResponse)
    def set_site_aoi(
        site_id: str,
        request: AoiSetRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        result = store.set_aoi(
            site_id,
            request.aoi,
            site_frame=request.site_frame,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        return SiteMutationResponse(
            verdict=result.verdict.value,
            site=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.put("/{site_id}/model-age-policy", response_model=SiteMutationResponse)
    def set_site_model_age_policy(
        site_id: str,
        request: ModelAgePolicyRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        """공간모델 노후 판정 기준을 선언·교체·철회한다(ADR-KSI-019 G1).

        ``SITES_AUTONOMY_APPROVE`` 를 요구하지 않는다 — 이 값은 전이를 직접 일으키지
        않고 판정 입력일 뿐이며, 실제 ``MODEL_STALE`` 전이는 별도 스윕 표면이
        일으킨다(자율 개시·정식 순찰 승인만 2차 게이트 대상, ADR-KSI-015 D2).
        """
        result = store.set_model_age_policy(
            site_id,
            max_age_days=request.max_age_days,
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

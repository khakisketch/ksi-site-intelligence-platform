"""작업구역(WorkArea) 등록·조회·보관 — 현장에 영구적으로 사는 비교 구역 (M4-C).

:class:`WorkAreaStore` 는 :mod:`ksi_core.durable_journal` 위에 조립된 저장소다
(``sites.SiteStore`` 와 동일 구조 — journal 의 잠금·fsync·복구 경로를 재구현하지
않고, 조회는 재생으로 만든 인메모리 projection 이 담당한다).

## 이 저장소가 "값이 아니라 참조"를 만드는 것이 아니다

``comparison_requests``·``design_conformance_requests`` 의 **zones 는 여전히 값**이다.
이미 낸 리포트가 "그때 어느 범위로 쟀는지"를 스스로 답해야 한다는 규율은 그대로다
(대표자 확정 2026-08-10). 이 저장소가 바꾸는 것은 그 값의 **출처**뿐이다 — 매번 새로
그린 그림 대신 등록된 자산에서 복사한다. 요청 레코드에는 복사된 폴리곤과 함께
어느 작업구역에서 왔는지(``workAreaRefs``)를 남기지만, 계산은 복사본만 본다.

## 기하 불변 — 왜 제자리 수정을 막는가

폴리곤을 고칠 수 있게 하면, 이미 그 ``workAreaId`` 로 낸 리포트들이 가리키는 범위가
사후에 바뀐다. 리포트 본문의 숫자는 그대로인데 그 숫자가 "무엇을 잰 것인지"가
달라지는 것이라, 어느 화면에서도 이상해 보이지 않는다. 그래서 수정은 **새 구역 등록 +
``supersedes``** 이고, 이때 이전 구역은 자동으로 ARCHIVED 된다(사람이 두 벌을 동시에
고를 수 있게 두면 다음 주에 둘 다 골라 두 배로 집계된다).

## 재생(replay) 은 fail-closed

오염된 레코드·미지 ``kind``·중복 id·존재하지 않는 ``supersedes`` 대상이 재생되면
:class:`WorkAreaStoreRecoveryError` 로 기동을 거부한다(``SiteStore`` 와 동일 강도).
계약 검증도 API 경계와 같은 강도로 재실행한다 — journal 이 어떤 경로로든 계약을
위반한 레코드를 담고 있다면 조용히 재생하지 않는다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_event_contracts.work_area import WorkArea, WorkAreaStatus
from pydantic import Field, ValidationError

from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from fastapi import FastAPI

#: 현장 하나에 등록할 수 있는 ACTIVE 작업구역 수 상한. 비교 요청 하나가 이 전부를
#: 고를 수 있고 구역마다 래스터 마스킹이 한 번씩 도므로, 상한 없이 두면 요청 하나가
#: 워커를 임의로 오래 붙잡는다.
MAX_ACTIVE_WORK_AREAS = 64


class WorkAreaVerdict(StrEnum):
    """등록/보관 판정 — verdict→HTTP 매핑은 ``_STATUS`` 가 SSOT(sites.py 관습)."""

    REGISTERED = "REGISTERED"
    ARCHIVED = "ARCHIVED"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    UNKNOWN_WORK_AREA = "UNKNOWN_WORK_AREA"
    INVALID_WORK_AREA = "INVALID_WORK_AREA"
    SUPERSEDES_NOT_FOUND = "SUPERSEDES_NOT_FOUND"
    SUPERSEDES_OTHER_SITE = "SUPERSEDES_OTHER_SITE"
    SUPERSEDES_NOT_ACTIVE = "SUPERSEDES_NOT_ACTIVE"
    ALREADY_ARCHIVED = "ALREADY_ARCHIVED"
    TOO_MANY_ACTIVE = "TOO_MANY_ACTIVE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[WorkAreaVerdict, int] = {
    WorkAreaVerdict.REGISTERED: 201,
    WorkAreaVerdict.ARCHIVED: 200,
    WorkAreaVerdict.UNKNOWN_SITE: 404,
    WorkAreaVerdict.UNKNOWN_WORK_AREA: 404,
    WorkAreaVerdict.INVALID_WORK_AREA: 422,
    WorkAreaVerdict.SUPERSEDES_NOT_FOUND: 404,
    WorkAreaVerdict.SUPERSEDES_OTHER_SITE: 409,
    WorkAreaVerdict.SUPERSEDES_NOT_ACTIVE: 409,
    WorkAreaVerdict.ALREADY_ARCHIVED: 409,
    WorkAreaVerdict.TOO_MANY_ACTIVE: 409,
    WorkAreaVerdict.STORE_UNAVAILABLE: 503,
}


class WorkAreaStoreRecoveryError(RuntimeError):
    """journal 재생 실패 — 기동을 거부한다."""


@dataclass(frozen=True, slots=True)
class WorkAreaResult:
    verdict: WorkAreaVerdict
    work_area: WorkArea | None = None
    detail: str | None = None


def build_work_area_id(site_id: str, sequence: int) -> str:
    """``wa-<siteId>-<0패딩 일련번호>`` — 현장 안에서만 유일하면 되고 사람이 읽을 수 있다.

    해시가 아닌 이유: 이 id 는 리포트의 ``zoneId`` 로 그대로 실려 화면과 CSV 에
    노출된다. ``design_conformance_id`` 처럼 내부에서만 도는 값이 아니다.
    """
    return f"wa-{site_id}-{sequence:04d}"


class WorkAreaStore:
    """작업구역 영속·조회. ``DurableJournal`` 위의 인메모리 projection.

    동시성: FastAPI sync 라우트가 스레드풀에서 도므로 검증·append·projection 갱신을
    한 임계구역으로 묶는다(``SiteStore`` 관습 대칭).
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_exists: Any = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        """``site_exists`` 는 ``site_id -> bool`` 콜러블(보통 ``SiteStore.get`` 래퍼).

        ``None`` 이면 현장 존재 검사를 하지 않는다 — 조립 표(``_ASSEMBLY_REQUIREMENTS``)가
        ``site_store`` 동반을 이미 강제하므로 프로덕션 경로에서는 항상 주어진다.
        테스트가 site 저장소 없이 이 저장소만 세울 수 있게 열어 둔다.
        """
        self._journal = journal
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._areas: dict[str, WorkArea] = {}
        self._by_site: dict[str, list[str]] = {}
        self._site_exists = site_exists
        self._lock = threading.Lock()
        try:
            self._replay(journal)
        except BaseException:
            # __init__ 이 예외로 끝나면 인스턴스는 없는데 journal 은 flock 을 쥔 채다
            # (SiteStore 와 같은 사유) — close() 없이는 재조립조차 오도된다.
            journal.close()
            raise

    # ── 재생 ────────────────────────────────────────────────────────────
    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                kind = raw["kind"]
                if kind == "work-area-registered":
                    self._apply_registered(raw)
                elif kind == "work-area-archived":
                    self._apply_archived(raw)
                else:
                    raise ValueError(f"알 수 없는 kind: {kind!r}")
            except (KeyError, ValueError, TypeError, ValidationError) as exc:
                raise WorkAreaStoreRecoveryError(
                    f"work-area journal 재생 실패 — 오염된 레코드: {exc}"
                ) from exc

    def _apply_registered(self, raw: dict[str, Any]) -> None:
        """등록 레코드를 projection 에 반영 — API 경계와 같은 강도로 재검증한다."""
        area = WorkArea.model_validate(raw["workArea"])
        if area.work_area_id in self._areas:
            raise ValueError(f"중복 등록 레코드: workAreaId={area.work_area_id}")
        if area.supersedes is not None:
            previous = self._areas.get(area.supersedes)
            if previous is None:
                raise ValueError(
                    f"supersedes 대상이 없다: {area.supersedes!r} (workAreaId={area.work_area_id})"
                )
            if previous.site_id != area.site_id:
                raise ValueError(
                    f"supersedes 대상이 다른 현장이다: {previous.site_id!r} != {area.site_id!r}"
                )
            if previous.status is not WorkAreaStatus.ACTIVE:
                # register() 가 이미 ACTIVE 아닌 대상의 supersedes 를 거부하므로
                # (SUPERSEDES_NOT_ACTIVE) 정상 기록이라면 여기 도달할 수 없다 —
                # 도달했다면 journal 이 상한 우회를 낳던 옛 결함의 흔적이거나
                # 변조된 레코드다. fail-closed 로 기동을 거부한다.
                raise ValueError(
                    f"supersedes 대상이 이미 ACTIVE 가 아니다: {area.supersedes!r} "
                    f"(status={previous.status.value}, workAreaId={area.work_area_id})"
                )
            # 대체는 이전 것을 반드시 보관 상태로 만든다(모듈 docstring) — 재생에서도
            # 같은 부수효과를 재현하지 않으면 projection 이 기록과 갈라진다.
            self._areas[area.supersedes] = previous.model_copy(
                update={"status": WorkAreaStatus.ARCHIVED}
            )
        self._areas[area.work_area_id] = area
        self._by_site.setdefault(area.site_id, []).append(area.work_area_id)

    def _apply_archived(self, raw: dict[str, Any]) -> None:
        work_area_id = raw["workAreaId"]
        current = self._areas.get(work_area_id)
        if current is None:
            raise ValueError(f"보관 레코드의 대상이 없다: workAreaId={work_area_id}")
        self._areas[work_area_id] = current.model_copy(update={"status": WorkAreaStatus.ARCHIVED})

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def site_is_visible(self, site_id: str) -> bool:
        """요청 문맥에서 부모 현장이 보이는지 확인한다(INV-060).

        production 조립은 ``SiteStore.get``을 주입하므로 API 요청에서 교차 조직
        현장은 존재하지 않는 것으로 접힌다. 독립 unit test나 trusted batch가
        ``site_exists=None``으로 이 store를 만들 때만 기존 전체 원장 동작을 유지한다.
        """

        return self._site_exists is None or bool(self._site_exists(site_id))

    @contextmanager
    def _mutation_for_site(self, site_id: str) -> Iterator[bool]:
        """Hold the shared coordinator while resolving Site before WorkArea.

        The injected Site lookup may acquire its own lock.  Resolving it before
        this store's lock avoids a Site/WorkArea inversion while the coordinator
        prevents a participating Site mutation from interleaving before append.
        """
        with self._coordinator.mutation():
            visible = self.site_is_visible(site_id)
            with self._lock:
                yield visible

    def get(self, work_area_id: str) -> WorkArea | None:
        with self._lock:
            area = self._areas.get(work_area_id)
        if area is None or not self.site_is_visible(area.site_id):
            return None
        return area

    def historical_active(
        self,
        work_area_id: str,
        *,
        site_id: str,
        at: datetime,
    ) -> WorkArea | None:
        """Replay actual timestamped WorkArea events and return an ACTIVE snapshot.

        This is intentionally separate from ``get``: a currently archived or
        replacement WorkArea cannot be silently treated as active at proposal
        creation time, and the current projection cannot prove historical
        geometry/CRS.  Journal records are re-applied with the normal strict
        replay validators before the snapshot is returned.
        """

        if at.tzinfo is None or at.utcoffset() != UTC.utcoffset(at):
            raise ValueError("at must be UTC-aware")
        snapshot = object.__new__(type(self))
        snapshot._areas = {}
        snapshot._by_site = {}
        for raw in self._journal.replay():
            if type(raw) is not dict:
                raise WorkAreaStoreRecoveryError(
                    "historical WorkArea journal event is not an object"
                )
            try:
                raw_at = raw["ts"]
                if type(raw_at) is not str:
                    raise ValueError("timestamp is not a string")
                event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                if event_at.tzinfo is None or event_at.utcoffset() != UTC.utcoffset(event_at):
                    raise ValueError("timestamp is not UTC-aware")
                if event_at > at:
                    continue
                kind = raw["kind"]
                if kind == "work-area-registered":
                    snapshot._apply_registered(raw)
                elif kind == "work-area-archived":
                    snapshot._apply_archived(raw)
                else:
                    raise ValueError(f"알 수 없는 kind: {kind!r}")
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                raise WorkAreaStoreRecoveryError(
                    f"historical WorkArea replay failed for retained target: {exc}"
                ) from exc
        area = snapshot._areas.get(work_area_id)
        if area is None or area.site_id != site_id or area.status is not WorkAreaStatus.ACTIVE:
            return None
        return area

    def list_for_site(self, site_id: str, *, include_archived: bool = False) -> list[WorkArea]:
        """등록 순서대로. 기본은 ACTIVE 만 — 화면의 '고를 수 있는 것' 목록이다."""
        if not self.site_is_visible(site_id):
            return []
        with self._lock:
            ids = list(self._by_site.get(site_id, ()))
            areas = [self._areas[wid] for wid in ids]
        if include_archived:
            return areas
        return [area for area in areas if area.status is WorkAreaStatus.ACTIVE]

    def resolve_zones(
        self, work_area_ids: list[str], *, site_id: str | None
    ) -> tuple[dict[str, dict[str, Any]], str] | str:
        """작업구역 id 목록 → ``(zones, zoneCrs)`` **값**. 실패 시 사람이 읽는 사유 문자열.

        요청이 참조 대신 값을 싣는 지점이 여기다 — 이 함수를 통과한 뒤로는 어느
        코드도 작업구역을 다시 보지 않는다(리포트가 등록 시점의 범위를 영구히 들고
        가야 하므로).

        ``site_id`` 가 ``None`` 이면 소속 현장을 검사하지 않는다. 호출자가 아직
        현장을 모르는 순간이 있어서다 — 설계 대비 요청은 처리 작업에서 현장을 얻는데,
        그 작업의 유효성 판정은 구역이 이미 있어야 시작된다. 그 경우 호출자가
        :meth:`site_of` 로 나중에 대조한다(``design_conformance_requests.create``).
        """
        if not work_area_ids:
            return "workAreaIds 가 비어 있다"
        if len(set(work_area_ids)) != len(work_area_ids):
            return f"workAreaIds 에 중복이 있다: {work_area_ids}"
        zones: dict[str, dict[str, Any]] = {}
        crs_values: set[str] = set()
        with self._lock:
            areas = [
                (work_area_id, self._areas.get(work_area_id)) for work_area_id in work_area_ids
            ]
        for work_area_id, area in areas:
            if area is None or not self.site_is_visible(area.site_id):
                return f"등록된 적 없는 작업구역이다: {work_area_id!r}"
            if site_id is not None and area.site_id != site_id:
                return (
                    f"작업구역 {work_area_id!r} 은 현장 {area.site_id!r} 소속인데 "
                    f"이 비교는 현장 {site_id!r} 다"
                )
            if area.status is not WorkAreaStatus.ACTIVE:
                return (
                    f"작업구역 {work_area_id!r} 은 보관됨(ARCHIVED) 상태다 — "
                    "새 비교에는 고를 수 없다(이미 낸 리포트는 그대로 남는다)"
                )
            zones[work_area_id] = area.polygon
            crs_values.add(area.crs)
        if len(crs_values) > 1:
            return (
                f"고른 작업구역들의 좌표계가 서로 다르다: {sorted(crs_values)} — "
                "한 비교의 구역들은 같은 좌표계여야 한다"
            )
        return zones, crs_values.pop()

    def site_of(self, work_area_ids: list[str]) -> set[str]:
        """고른 구역들이 속한 현장 집합 — 둘 이상이면 호출자가 거부한다."""
        with self._lock:
            site_ids = {self._areas[wid].site_id for wid in work_area_ids if wid in self._areas}
        return {site_id for site_id in site_ids if self.site_is_visible(site_id)}

    def names_of(self, work_area_ids: list[str]) -> dict[str, str]:
        """id → 이름. 진척 화면이 ``zoneId`` 옆에 사람 이름을 붙일 때 쓴다."""
        with self._lock:
            areas = [(wid, self._areas[wid]) for wid in work_area_ids if wid in self._areas]
        return {wid: area.name for wid, area in areas if self.site_is_visible(area.site_id)}

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def register(
        self,
        site_id: str,
        *,
        name: str,
        polygon: dict[str, Any],
        crs: str,
        supersedes: str | None,
        now: datetime,
        actor: str,
    ) -> WorkAreaResult:
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        if not is_path_safe_identifier(site_id):
            return WorkAreaResult(
                WorkAreaVerdict.INVALID_WORK_AREA,
                detail=f"siteId 가 경로 안전 식별자가 아니다: {site_id!r}",
            )
        with self._mutation_for_site(site_id) as site_visible:
            if not site_visible:
                return WorkAreaResult(
                    WorkAreaVerdict.UNKNOWN_SITE,
                    detail=(
                        f"등록된 적 없는 현장이다: {site_id!r} — 작업구역은 '어느 현장의 "
                        "어디인가'로만 의미를 갖는다"
                    ),
                )
            if self._journal.sealed_reason is not None:
                return WorkAreaResult(
                    WorkAreaVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if supersedes is not None:
                previous = self._areas.get(supersedes)
                if previous is None:
                    return WorkAreaResult(
                        WorkAreaVerdict.SUPERSEDES_NOT_FOUND,
                        detail=f"대체하려는 작업구역이 없다: {supersedes!r}",
                    )
                if previous.site_id != site_id:
                    return WorkAreaResult(
                        WorkAreaVerdict.SUPERSEDES_OTHER_SITE,
                        detail=(
                            f"대체 대상은 현장 {previous.site_id!r} 소속인데 요청은 "
                            f"현장 {site_id!r} 다"
                        ),
                    )
                if previous.status is not WorkAreaStatus.ACTIVE:
                    # 상한 우회 통로 — supersedes 는 "이전 ACTIVE 하나를 이 ACTIVE
                    # 하나로 순증 없이 교체"할 때만 상한 검사를 면제한다. 이미
                    # ARCHIVED 인 대상을 다시 "대체"하게 두면 그 재보관은 무보수
                    # no-op 이고 새 등록만 순증으로 남아, 이 경로를 반복 호출해
                    # 상한을 무제한으로 넘길 수 있다.
                    return WorkAreaResult(
                        WorkAreaVerdict.SUPERSEDES_NOT_ACTIVE,
                        detail=(
                            f"대체하려는 작업구역 {supersedes!r} 은 이미 ACTIVE 가 "
                            f"아니다(status={previous.status.value}) — 보관된 구역은 "
                            "다시 대체할 수 없다"
                        ),
                    )
            active_count = sum(
                1
                for wid in self._by_site.get(site_id, ())
                if self._areas[wid].status is WorkAreaStatus.ACTIVE
            )
            # 대체 등록은 순증이 아니다(이전 것이 곧 보관된다) — 상한 판정에서 뺀다.
            if supersedes is None and active_count >= MAX_ACTIVE_WORK_AREAS:
                return WorkAreaResult(
                    WorkAreaVerdict.TOO_MANY_ACTIVE,
                    detail=(
                        f"현장의 ACTIVE 작업구역이 상한 {MAX_ACTIVE_WORK_AREAS}개다 — "
                        "쓰지 않는 구역을 보관(archive)한 뒤 등록한다"
                    ),
                )
            sequence = len(self._by_site.get(site_id, ())) + 1
            try:
                area = WorkArea(
                    work_area_id=build_work_area_id(site_id, sequence),
                    site_id=site_id,
                    name=name,
                    polygon=polygon,
                    crs=crs,
                    status=WorkAreaStatus.ACTIVE,
                    supersedes=supersedes,
                    created_at=iso_utc(now),
                )
            except ValidationError as exc:
                return WorkAreaResult(WorkAreaVerdict.INVALID_WORK_AREA, detail=_first_error(exc))
            raw: dict[str, Any] = {
                "kind": "work-area-registered",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "workAreaId": area.work_area_id,
                "workArea": area.model_dump(by_alias=True, mode="json"),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return WorkAreaResult(
                    WorkAreaVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            self._apply_registered(raw)
            return WorkAreaResult(WorkAreaVerdict.REGISTERED, work_area=area)

    def archive(
        self, work_area_id: str, *, site_id: str, now: datetime, actor: str
    ) -> WorkAreaResult:
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._mutation_for_site(site_id) as site_visible:
            if not site_visible:
                return WorkAreaResult(
                    WorkAreaVerdict.UNKNOWN_WORK_AREA,
                    detail=f"현장 {site_id!r} 에 작업구역 {work_area_id!r} 이 없다",
                )
            if self._journal.sealed_reason is not None:
                return WorkAreaResult(
                    WorkAreaVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            current = self._areas.get(work_area_id)
            if current is None or current.site_id != site_id:
                return WorkAreaResult(
                    WorkAreaVerdict.UNKNOWN_WORK_AREA,
                    detail=f"현장 {site_id!r} 에 작업구역 {work_area_id!r} 이 없다",
                )
            if current.status is WorkAreaStatus.ARCHIVED:
                return WorkAreaResult(
                    WorkAreaVerdict.ALREADY_ARCHIVED,
                    detail=f"작업구역 {work_area_id!r} 은 이미 보관됨 상태다",
                    work_area=current,
                )
            raw: dict[str, Any] = {
                "kind": "work-area-archived",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "workAreaId": work_area_id,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return WorkAreaResult(
                    WorkAreaVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            self._apply_archived(raw)
            return WorkAreaResult(WorkAreaVerdict.ARCHIVED, work_area=self._areas[work_area_id])


def _first_error(exc: ValidationError) -> str:
    """pydantic 오류 중 첫 건을 사람이 읽는 한 줄로 — 계약 검증 문구를 그대로 살린다."""
    errors = exc.errors()
    if not errors:  # pragma: no cover -- ValidationError 는 항상 하나 이상이다
        return str(exc)
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "(root)"
    return f"{location}: {first.get('msg', '검증 실패')}"


# ── API ────────────────────────────────────────────────────────────────
class WorkAreaRegisterRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    polygon: dict[str, Any]
    crs: str = Field(min_length=1)
    #: 기하를 고칠 때 이전 구역의 id. 주면 그 구역은 자동으로 보관된다.
    supersedes: str | None = None


class WorkAreaResponse(CamelModel):
    verdict: str
    detail: str | None = None
    work_area: WorkArea | None = None


class WorkAreaListResponse(CamelModel):
    work_areas: list[WorkArea]


def build_work_area_router(store: WorkAreaStore, *, site_store: Any = None) -> APIRouter:
    router = APIRouter(tags=["work-areas"])

    def require_site_scope(principal: Principal, site_id: str) -> None:
        if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
            raise HTTPException(status_code=404, detail="현장을 찾을 수 없다")
        if site_store is not None:
            visible = site_store.get_scoped(site_id, principal.organization_id) is not None
        elif principal.allowed_site_ids is not None:
            # Mapped OIDC grants must resolve through the organization-owned Site projection.
            visible = False
        else:
            visible = store.site_is_visible(site_id)
        if not visible:
            raise HTTPException(status_code=404, detail="현장을 찾을 수 없다")

    def require_work_area_grant(principal: Principal, work_area_id: str) -> None:
        if (
            principal.allowed_work_area_ids is not None
            and work_area_id not in principal.allowed_work_area_ids
        ):
            raise HTTPException(status_code=404, detail="작업구역을 찾을 수 없다")

    @router.post(
        "/v1/sites/{site_id}/work-areas",
        response_model=WorkAreaResponse,
        status_code=201,
    )
    def register_work_area(
        site_id: str,
        request: WorkAreaRegisterRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> WorkAreaResponse:
        """작업구역을 등록한다 — 기하는 이 순간 굳는다.

        고치려면 ``supersedes`` 로 새 구역을 만든다(모듈 docstring). 201 은 "이
        범위로 앞으로 계속 잴 수 있다"는 뜻이다.
        """
        require_site_scope(principal, site_id)
        if request.supersedes is not None:
            require_work_area_grant(principal, request.supersedes)
        result = store.register(
            site_id,
            name=request.name,
            polygon=request.polygon,
            crs=request.crs,
            supersedes=request.supersedes,
            now=datetime.now(UTC),
            actor=principal.principal_id,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is WorkAreaVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return WorkAreaResponse(
            verdict=result.verdict.value, detail=result.detail, work_area=result.work_area
        )

    @router.get("/v1/sites/{site_id}/work-areas", response_model=WorkAreaListResponse)
    def list_work_areas(
        site_id: str,
        include_archived: bool = False,  # noqa: FBT001, FBT002 -- 쿼리 파라미터다
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> WorkAreaListResponse:
        """현장의 작업구역 목록. 기본은 고를 수 있는 것(ACTIVE)만."""
        require_site_scope(principal, site_id)
        work_areas = store.list_for_site(site_id, include_archived=include_archived)
        if principal.allowed_work_area_ids is not None:
            work_areas = [
                area
                for area in work_areas
                if area.work_area_id in principal.allowed_work_area_ids
            ]
        return WorkAreaListResponse(
            work_areas=work_areas
        )

    @router.post(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/archive",
        response_model=WorkAreaResponse,
    )
    def archive_work_area(
        site_id: str,
        work_area_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> WorkAreaResponse:
        """더 이상 고를 수 없게 한다 — **삭제가 아니다.**

        이 구역으로 낸 리포트들이 ``zoneId`` 로 이 id 를 들고 있어, 지우면 그
        리포트들이 무슨 범위였는지를 잃는다.
        """
        require_site_scope(principal, site_id)
        require_work_area_grant(principal, work_area_id)
        result = store.archive(
            work_area_id,
            site_id=site_id,
            now=datetime.now(UTC),
            actor=principal.principal_id,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is WorkAreaVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return WorkAreaResponse(
            verdict=result.verdict.value, detail=result.detail, work_area=result.work_area
        )

    return router


def mount_work_areas(app: FastAPI, store: WorkAreaStore, *, site_store: Any = None) -> None:
    """앱에 작업구역 라우터를 장착한다."""
    app.state.work_area_store = store
    app.include_router(build_work_area_router(store, site_store=site_store))


__all__ = [
    "MAX_ACTIVE_WORK_AREAS",
    "WorkAreaListResponse",
    "WorkAreaRegisterRequest",
    "WorkAreaResponse",
    "WorkAreaResult",
    "WorkAreaStore",
    "WorkAreaStoreRecoveryError",
    "WorkAreaVerdict",
    "build_work_area_id",
    "build_work_area_router",
    "mount_work_areas",
]

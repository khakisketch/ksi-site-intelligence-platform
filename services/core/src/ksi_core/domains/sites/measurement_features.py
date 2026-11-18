"""저장한 측정 대상(선) — 영역에 속한 불변 revision 원장 (표면 측정 v1, C1).

선 하나를 고치면 **새 revision**이다. 이미 그 revision으로 읽은 단면 결과가 가리키는 선이
사후에 달라지지 않게 하려는 것이며, 이는 ``work_areas`` 의 "기하 불변" 규율과 같다.

이 저장소는 위치만 기억한다. 측정 대상은 새 권한 범위가 아니다 — 부모 영역과 현장의
**현재** 접근 범위가 읽기·쓰기 모두의 상한이다. 영역이 보관되면 새 쓰기는 거부하지만
이미 쓴 revision은 읽을 수 있다(결과의 근거를 잃지 않는다).

## 멱등과 재생

- 쓰기는 ``Idempotency-Key`` 를 요구한다. 같은 (조직·주체·현장·영역·키)가 같은 본문이면 원래
  revision을 돌려주고, 다른 본문이면 409다. 원문 키는 남기지 않고 해시만 원장에 둔다.
- 새 feature id 는 멱등 신원에서 결정적으로 만든다 — 응답이 유실돼 같은 키로 다시 와도
  같은 id 로 수렴한다.
- 원장 재생은 fail-closed 다. 서명(digest)이 맞지 않는 revision, 건너뛴 revision 번호,
  다른 영역·조직의 revision 이어붙이기는 기동을 거부한다.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.measurement_feature import (
    CreateMeasurementFeatureV1,
    MeasurementFeatureListViewV1,
    MeasurementFeatureRefusalV1,
    MeasurementFeatureRevisionListViewV1,
    MeasurementFeatureRevisionV1,
    MeasurementFeatureWriteViewV1,
    ReviseMeasurementFeatureV1,
)
from ksi_event_contracts.work_area import WorkAreaStatus
from pydantic import ValidationError

from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, require_permission

#: 영역 하나가 가질 수 있는 측정 대상 수. 요청 하나가 읽는 선을 고르므로 상한 없이 두지 않는다.
MAX_FEATURES_PER_WORK_AREA = 200
#: 선 하나의 revision 수 — 편집 이력이 원장을 무한히 늘리지 못하게 한다.
MAX_REVISIONS_PER_FEATURE = 100
MAX_IDEMPOTENCY_KEY_LENGTH = 255

_KIND = "measurement-feature-revision"


class MeasurementFeatureVerdict(StrEnum):
    CREATED = "CREATED"
    REVISED = "REVISED"
    REPLAYED = "REPLAYED"
    UNKNOWN_WORK_AREA = "UNKNOWN_WORK_AREA"
    UNKNOWN_FEATURE = "UNKNOWN_FEATURE"
    UNKNOWN_REVISION = "UNKNOWN_REVISION"
    WORK_AREA_NOT_ACTIVE = "WORK_AREA_NOT_ACTIVE"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    TOO_MANY_FEATURES = "TOO_MANY_FEATURES"
    TOO_MANY_REVISIONS = "TOO_MANY_REVISIONS"
    INVALID = "INVALID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[MeasurementFeatureVerdict, int] = {
    MeasurementFeatureVerdict.CREATED: 201,
    MeasurementFeatureVerdict.REVISED: 201,
    MeasurementFeatureVerdict.REPLAYED: 200,
    MeasurementFeatureVerdict.UNKNOWN_WORK_AREA: 404,
    MeasurementFeatureVerdict.UNKNOWN_FEATURE: 404,
    MeasurementFeatureVerdict.UNKNOWN_REVISION: 404,
    MeasurementFeatureVerdict.WORK_AREA_NOT_ACTIVE: 409,
    MeasurementFeatureVerdict.REVISION_CONFLICT: 409,
    MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT: 409,
    MeasurementFeatureVerdict.TOO_MANY_FEATURES: 409,
    MeasurementFeatureVerdict.TOO_MANY_REVISIONS: 409,
    MeasurementFeatureVerdict.INVALID: 422,
    MeasurementFeatureVerdict.STORE_UNAVAILABLE: 503,
}


class MeasurementFeatureStoreRecoveryError(RuntimeError):
    """원장 재생 실패 — 기동을 거부한다."""


@dataclass(frozen=True, slots=True)
class MeasurementFeatureResult:
    verdict: MeasurementFeatureVerdict
    revision: MeasurementFeatureRevisionV1 | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _Stored:
    organization_id: str
    actor: str
    revision: MeasurementFeatureRevisionV1


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _valid_key(key: str) -> bool:
    return (
        type(key) is str
        and 0 < len(key) <= MAX_IDEMPOTENCY_KEY_LENGTH
        and key.strip() != ""
        and not any(ord(c) < 32 or ord(c) == 127 for c in key)
    )


class MeasurementFeatureStore:
    """``DurableJournal`` 위의 인메모리 projection. 쓰기는 영역·현장 가시성과 한도를 함께 본다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        work_areas: WorkAreaStore,
        site_visible_to: Callable[[str, str], bool],
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._work_areas = work_areas
        self._site_visible_to = site_visible_to
        self._coordinator = coordinator or work_areas.coordinator
        self._lock = threading.Lock()
        # feature_id -> 순서대로 쌓인 revision (index = revision - 1)
        self._features: dict[str, list[_Stored]] = {}
        self._by_area: dict[tuple[str, str], list[str]] = {}
        # (org, principal, site, area, key_hash) -> (request_digest, feature_id, revision)
        self._idempotency: dict[tuple[str, str, str, str, str], tuple[str, str, int]] = {}
        try:
            self._replay(journal)
        except BaseException:
            journal.close()
            raise

    # ── 재생 ────────────────────────────────────────────────────────────
    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                if raw["kind"] != _KIND:
                    raise ValueError(f"알 수 없는 kind: {raw['kind']!r}")
                self._apply(raw)
            except (KeyError, ValueError, TypeError, ValidationError) as exc:
                raise MeasurementFeatureStoreRecoveryError(
                    f"measurement-feature journal 재생 실패 — 오염된 레코드: {exc}"
                ) from exc

    def _apply(self, raw: dict[str, Any]) -> None:
        revision = MeasurementFeatureRevisionV1.model_validate(raw["revision"])
        if revision.revision_digest is None or revision.revision_digest != (
            revision.canonical_digest()
        ):
            raise ValueError("revision 서명이 내용과 맞지 않는다")
        organization_id, actor = raw["organizationId"], raw["actor"]
        if not (isinstance(organization_id, str) and isinstance(actor, str)):
            raise ValueError("조직·주체가 문자열이 아니다")
        history = self._features.get(revision.feature_id)
        if revision.revision == 1:
            if history is not None:
                raise ValueError(f"중복 생성 레코드: {revision.feature_id}")
            self._features[revision.feature_id] = history = []
            self._by_area.setdefault((revision.site_id, revision.work_area_id), []).append(
                revision.feature_id
            )
        else:
            if history is None or len(history) != revision.revision - 1:
                raise ValueError(f"revision 번호가 이어지지 않는다: {revision.feature_id}")
            first = history[0]
            if (
                first.organization_id != organization_id
                or first.revision.site_id != revision.site_id
                or first.revision.work_area_id != revision.work_area_id
            ):
                raise ValueError("다른 조직·현장·영역의 revision 을 이어 붙일 수 없다")
        history.append(_Stored(organization_id, actor, revision))
        key_hash, request_digest = raw["keyHash"], raw["requestDigest"]
        self._idempotency[
            (organization_id, actor, revision.site_id, revision.work_area_id, key_hash)
        ] = (request_digest, revision.feature_id, revision.revision)

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _visible_area(self, organization_id: str, site_id: str, work_area_id: str) -> Any:
        area = self._work_areas.get(work_area_id)
        if area is None or area.site_id != site_id:
            return None
        return area if self._site_visible_to(site_id, organization_id) else None

    def list_latest(
        self, *, organization_id: str, site_id: str, work_area_id: str
    ) -> tuple[MeasurementFeatureRevisionV1, ...] | None:
        """영역의 측정 대상별 최신 revision. 보이지 않는 영역이면 ``None``."""
        if self._visible_area(organization_id, site_id, work_area_id) is None:
            return None
        with self._lock:
            return tuple(
                self._features[fid][-1].revision
                for fid in self._by_area.get((site_id, work_area_id), ())
                if self._features[fid][0].organization_id == organization_id
            )

    def get(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        feature_id: str,
        revision: int | None = None,
    ) -> MeasurementFeatureRevisionV1 | None:
        """정확한 revision(없으면 최신). 다른 조직·현장·영역의 것은 존재하지 않는 것으로 본다."""
        if self._visible_area(organization_id, site_id, work_area_id) is None:
            return None
        with self._lock:
            history = self._features.get(feature_id)
            if (
                not history
                or history[0].organization_id != organization_id
                or history[0].revision.site_id != site_id
                or history[0].revision.work_area_id != work_area_id
            ):
                return None
            if revision is None:
                return history[-1].revision
            return history[revision - 1].revision if 1 <= revision <= len(history) else None

    def list_revisions(
        self, *, organization_id: str, site_id: str, work_area_id: str, feature_id: str
    ) -> tuple[MeasurementFeatureRevisionV1, ...] | None:
        if (
            self.get(
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                feature_id=feature_id,
            )
            is None
        ):
            return None
        with self._lock:
            return tuple(item.revision for item in self._features[feature_id])

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def create(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        principal_id: str,
        body: CreateMeasurementFeatureV1,
        idempotency_key: str,
        now: datetime,
    ) -> MeasurementFeatureResult:
        if body.work_area_id != work_area_id:
            return MeasurementFeatureResult(
                MeasurementFeatureVerdict.INVALID, detail="본문의 workAreaId 가 경로와 다르다"
            )
        request_digest = _digest(
            {
                "op": "create",
                "workAreaId": work_area_id,
                "name": body.name,
                "line": body.line.model_dump(by_alias=True, mode="json"),
            }
        )
        return self._write(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            principal_id=principal_id,
            feature_id=None,
            expected_revision=None,
            name=body.name,
            line=body.line,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            now=now,
        )

    def revise(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        feature_id: str,
        principal_id: str,
        body: ReviseMeasurementFeatureV1,
        idempotency_key: str,
        now: datetime,
    ) -> MeasurementFeatureResult:
        request_digest = _digest(
            {
                "op": "revise",
                "workAreaId": work_area_id,
                "featureId": feature_id,
                "expectedRevision": body.expected_revision,
                "name": body.name,
                "line": body.line.model_dump(by_alias=True, mode="json"),
            }
        )
        return self._write(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            principal_id=principal_id,
            feature_id=feature_id,
            expected_revision=body.expected_revision,
            name=body.name,
            line=body.line,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            now=now,
        )

    def _write(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        principal_id: str,
        feature_id: str | None,
        expected_revision: int | None,
        name: str,
        line: Any,
        request_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> MeasurementFeatureResult:
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다")
        if not _valid_key(idempotency_key):
            return MeasurementFeatureResult(
                MeasurementFeatureVerdict.INVALID, detail="Idempotency-Key 가 올바르지 않다"
            )
        key_hash = _digest({"key": idempotency_key})
        idem = (organization_id, principal_id, site_id, work_area_id, key_hash)
        with self._coordinator.mutation():
            area = self._visible_area(organization_id, site_id, work_area_id)
            with self._lock:
                if area is None:
                    return MeasurementFeatureResult(MeasurementFeatureVerdict.UNKNOWN_WORK_AREA)
                existing = self._idempotency.get(idem)
                if existing is not None:
                    # 같은 키는 영역이 보관된 뒤에도 원래 결과를 돌려준다(응답 유실 복구).
                    stored_digest, existing_id, existing_revision = existing
                    if stored_digest != request_digest:
                        return MeasurementFeatureResult(
                            MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT,
                            detail="Idempotency-Key 가 다른 요청에 이미 사용됐다",
                        )
                    return MeasurementFeatureResult(
                        MeasurementFeatureVerdict.REPLAYED,
                        self._features[existing_id][existing_revision - 1].revision,
                    )
                if self._journal.sealed_reason is not None:
                    return MeasurementFeatureResult(
                        MeasurementFeatureVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                    )
                if area.status is not WorkAreaStatus.ACTIVE:
                    return MeasurementFeatureResult(
                        MeasurementFeatureVerdict.WORK_AREA_NOT_ACTIVE,
                        detail="보관된 영역에는 새 측정 대상이나 revision 을 쓸 수 없다",
                    )
                if feature_id is None:
                    count = len(self._by_area.get((site_id, work_area_id), ()))
                    if count >= MAX_FEATURES_PER_WORK_AREA:
                        return MeasurementFeatureResult(
                            MeasurementFeatureVerdict.TOO_MANY_FEATURES,
                            detail=f"영역의 측정 대상이 상한 {MAX_FEATURES_PER_WORK_AREA}개다",
                        )
                    feature_id = (
                        "mf-"
                        + _digest(
                            {
                                "scope": [
                                    organization_id,
                                    principal_id,
                                    site_id,
                                    work_area_id,
                                    key_hash,
                                ]
                            }
                        ).removeprefix("sha256:")[:32]
                    )
                    if feature_id in self._features:  # 결정적 id 충돌 — 다른 요청이 선점했다
                        return MeasurementFeatureResult(
                            MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT
                        )
                    number = 1
                else:
                    history = self._features.get(feature_id)
                    if (
                        not history
                        or history[0].organization_id != organization_id
                        or history[0].revision.site_id != site_id
                        or history[0].revision.work_area_id != work_area_id
                    ):
                        return MeasurementFeatureResult(MeasurementFeatureVerdict.UNKNOWN_FEATURE)
                    if expected_revision != len(history):
                        return MeasurementFeatureResult(
                            MeasurementFeatureVerdict.REVISION_CONFLICT,
                            detail=f"최신 revision 은 {len(history)} 다 — 다시 읽고 고친다",
                        )
                    if len(history) >= MAX_REVISIONS_PER_FEATURE:
                        return MeasurementFeatureResult(
                            MeasurementFeatureVerdict.TOO_MANY_REVISIONS,
                            detail=f"revision 이 상한 {MAX_REVISIONS_PER_FEATURE}개다",
                        )
                    number = len(history) + 1
                try:
                    revision = MeasurementFeatureRevisionV1(
                        feature_id=feature_id,
                        site_id=site_id,
                        work_area_id=work_area_id,
                        revision=number,
                        name=name,
                        line=line,
                        line_digest=line.digest(),
                        created_at=now,
                    ).sealed()
                except ValidationError as exc:
                    return MeasurementFeatureResult(
                        MeasurementFeatureVerdict.INVALID, detail=str(exc.errors()[0]["msg"])
                    )
                raw: dict[str, Any] = {
                    "kind": _KIND,
                    "ts": iso_utc(now),
                    "actor": principal_id,
                    "organizationId": organization_id,
                    "keyHash": key_hash,
                    "requestDigest": request_digest,
                    "revision": revision.model_dump(by_alias=True, mode="json"),
                }
                try:
                    self._journal.append(raw)
                except JournalSealedError:
                    return MeasurementFeatureResult(
                        MeasurementFeatureVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                    )
                self._apply(raw)
                return MeasurementFeatureResult(
                    MeasurementFeatureVerdict.CREATED
                    if number == 1
                    else MeasurementFeatureVerdict.REVISED,
                    revision,
                )


# ── HTTP ─────────────────────────────────────────────────────────────────
_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/measurement-features"


def build_measurement_feature_router(
    store: MeasurementFeatureStore, *, clock: Callable[[], datetime]
) -> APIRouter:
    router = APIRouter(tags=["measurement-features"])

    def scope(principal: Principal, site_id: str, work_area_id: str) -> None:
        """권한이 닿지 않는 범위는 존재 자체를 숨긴다 — 영역 라우터와 같은 404."""
        if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
            raise HTTPException(status_code=404, detail="현장을 찾을 수 없다")
        if (
            principal.allowed_work_area_ids is not None
            and work_area_id not in principal.allowed_work_area_ids
        ):
            raise HTTPException(status_code=404, detail="작업구역을 찾을 수 없다")

    def respond(result: MeasurementFeatureResult) -> Response:
        """성공은 revision 을, 거부는 종류가 정해진 사유만 낸다(다른 조직 식별자·경로 없음)."""
        body: MeasurementFeatureWriteViewV1 | MeasurementFeatureRefusalV1
        if result.revision is not None:
            body = MeasurementFeatureWriteViewV1(
                verdict=result.verdict.value,  # type: ignore[arg-type]
                revision=result.revision,
            )
        else:
            body = MeasurementFeatureRefusalV1(
                verdict=result.verdict.value,  # type: ignore[arg-type]
                detail=result.detail,
            )
        reply = JSONResponse(
            body.model_dump(by_alias=True, mode="json"), status_code=_STATUS[result.verdict]
        )
        if result.verdict is MeasurementFeatureVerdict.STORE_UNAVAILABLE:
            reply.headers["Retry-After"] = "30"
        return reply

    def not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="측정 대상을 찾을 수 없다")

    @router.post(_BASE, response_model=MeasurementFeatureWriteViewV1, status_code=201)
    def create_feature(
        site_id: str,
        work_area_id: str,
        body: CreateMeasurementFeatureV1,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> Response:
        scope(principal, site_id, work_area_id)
        return respond(
            store.create(
                organization_id=principal.organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                principal_id=principal.principal_id,
                body=body,
                idempotency_key=idempotency_key,
                now=clock(),
            ),
        )

    @router.get(_BASE, response_model=MeasurementFeatureListViewV1)
    def list_features(
        site_id: str,
        work_area_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> MeasurementFeatureListViewV1:
        scope(principal, site_id, work_area_id)
        found = store.list_latest(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
        )
        if found is None:
            raise HTTPException(status_code=404, detail="작업구역을 찾을 수 없다")
        return MeasurementFeatureListViewV1(features=found)

    @router.get(_BASE + "/{feature_id}", response_model=MeasurementFeatureRevisionV1)
    def get_feature(
        site_id: str,
        work_area_id: str,
        feature_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> MeasurementFeatureRevisionV1:
        scope(principal, site_id, work_area_id)
        found = store.get(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            feature_id=feature_id,
        )
        if found is None:
            raise not_found()
        return found

    @router.get(
        _BASE + "/{feature_id}/revisions", response_model=MeasurementFeatureRevisionListViewV1
    )
    def list_revisions(
        site_id: str,
        work_area_id: str,
        feature_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> MeasurementFeatureRevisionListViewV1:
        scope(principal, site_id, work_area_id)
        found = store.list_revisions(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            feature_id=feature_id,
        )
        if found is None:
            raise not_found()
        return MeasurementFeatureRevisionListViewV1(revisions=found)

    @router.get(
        _BASE + "/{feature_id}/revisions/{revision}", response_model=MeasurementFeatureRevisionV1
    )
    def get_revision(
        site_id: str,
        work_area_id: str,
        feature_id: str,
        revision: int,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> MeasurementFeatureRevisionV1:
        scope(principal, site_id, work_area_id)
        found = store.get(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            feature_id=feature_id,
            revision=revision,
        )
        if found is None:
            raise not_found()
        return found

    @router.post(
        _BASE + "/{feature_id}/revisions",
        response_model=MeasurementFeatureWriteViewV1,
        status_code=201,
    )
    def revise_feature(
        site_id: str,
        work_area_id: str,
        feature_id: str,
        body: ReviseMeasurementFeatureV1,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> Response:
        scope(principal, site_id, work_area_id)
        return respond(
            store.revise(
                organization_id=principal.organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                feature_id=feature_id,
                principal_id=principal.principal_id,
                body=body,
                idempotency_key=idempotency_key,
                now=clock(),
            ),
        )

    return router


def mount_measurement_features(
    app: FastAPI, store: MeasurementFeatureStore, *, clock: Callable[[], datetime]
) -> None:
    app.state.measurement_feature_store = store
    app.include_router(build_measurement_feature_router(store, clock=clock))


__all__ = [
    "MAX_FEATURES_PER_WORK_AREA",
    "MAX_REVISIONS_PER_FEATURE",
    "MeasurementFeatureResult",
    "MeasurementFeatureStore",
    "MeasurementFeatureStoreRecoveryError",
    "MeasurementFeatureVerdict",
    "build_measurement_feature_router",
    "mount_measurement_features",
]

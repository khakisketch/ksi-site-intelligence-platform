"""등록된 DSM의 수직 기준 선언 원장 — 주장을 관측과 섞지 않고 append-only 로 둔다 (표면 측정 D2).

수직 좌표계가 없는 DSM은 파일만으로는 높이를 읽을 수 없다. 내보낸 사람이 기준을 알면 자료 하나
(asset_ref)에 대해 선언할 수 있다. 이 원장은 그 **주장**만 기억한다.

- 등록 제출·검사 보고서·판정은 건드리지 않는다. 그래서 어떤 기존 digest도 바뀌지 않는다.
- 파일이 스스로 수직 기준을 담고 있으면 선언을 받지 않는다. 파일의 값을 가릴 수 없게 한다.
- 정정·철회는 새 기록이다. 현재 선언은 가장 큰 sequence 의 ACTIVE 기록이다.
- 선언은 관측값이 아니다. 비교·체적·준비도는 이 원장을 읽지 않는다.

멱등·재생은 저장 선 원장과 같은 규율이다. 같은 (조직·주체·현장·자료·키)가 같은 본문이면 원래 기록을
돌려주고 다른 본문이면 409다. 재생은 fail-closed 다 — 서명이 틀린 기록, 건너뛴 sequence, 다른
조직·현장·자료의 이어붙이기, 활성 선언 없는 철회는 기동을 거부한다.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference_declaration import (
    MAX_DECLARATIONS_PER_ASSET,
    DeclareVerticalReferenceV1,
    VerticalReferenceDeclarationRefusalV1,
    VerticalReferenceDeclarationStateViewV1,
    VerticalReferenceDeclarationV1,
    VerticalReferenceDeclarationWriteViewV1,
    WithdrawVerticalReferenceV1,
)
from pydantic import ValidationError

from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, require_permission

MAX_IDEMPOTENCY_KEY_LENGTH = 255
_KIND = "vertical-reference-declaration"


class DeclarationVerdict(StrEnum):
    DECLARED = "DECLARED"
    WITHDRAWN = "WITHDRAWN"
    REPLAYED = "REPLAYED"
    UNKNOWN_ASSET = "UNKNOWN_ASSET"
    NOT_A_DSM = "NOT_A_DSM"
    NOT_MEASURED = "NOT_MEASURED"
    OBSERVED_REFERENCE_PRESENT = "OBSERVED_REFERENCE_PRESENT"
    SEQUENCE_CONFLICT = "SEQUENCE_CONFLICT"
    NOTHING_TO_WITHDRAW = "NOTHING_TO_WITHDRAW"
    TOO_MANY_DECLARATIONS = "TOO_MANY_DECLARATIONS"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID = "INVALID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[DeclarationVerdict, int] = {
    DeclarationVerdict.DECLARED: 201,
    DeclarationVerdict.WITHDRAWN: 201,
    DeclarationVerdict.REPLAYED: 200,
    DeclarationVerdict.UNKNOWN_ASSET: 404,
    DeclarationVerdict.NOT_A_DSM: 409,
    DeclarationVerdict.NOT_MEASURED: 409,
    DeclarationVerdict.OBSERVED_REFERENCE_PRESENT: 409,
    DeclarationVerdict.SEQUENCE_CONFLICT: 409,
    DeclarationVerdict.NOTHING_TO_WITHDRAW: 409,
    DeclarationVerdict.TOO_MANY_DECLARATIONS: 409,
    DeclarationVerdict.IDEMPOTENCY_CONFLICT: 409,
    DeclarationVerdict.INVALID: 422,
    DeclarationVerdict.STORE_UNAVAILABLE: 503,
}


class VerticalReferenceDeclarationRecoveryError(RuntimeError):
    """원장 재생 실패 — 기동을 거부한다."""


@dataclass(frozen=True, slots=True)
class AssetFacts:
    """선언이 가능한지 판단하는 데 필요한 자료의 현재 사실. 카탈로그가 만든다."""

    site_id: str
    work_area_id: str
    asset_ref: str
    kind: ProcessingArtifactKind
    measured: bool
    observed_vertical_reference: bool


class DeclarationAssetPort(Protocol):
    """현재 권한 범위 안에서 자료 하나의 사실을 돌려준다. 보이지 않으면 ``None`` 또는 404."""

    def facts(
        self, *, principal: Principal, site_id: str, work_area_id: str, asset_ref: str
    ) -> AssetFacts | None: ...


@dataclass(frozen=True, slots=True)
class DeclarationResult:
    verdict: DeclarationVerdict
    declaration: VerticalReferenceDeclarationV1 | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _Stored:
    organization_id: str
    actor: str
    record: VerticalReferenceDeclarationV1


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _valid_key(key: str) -> bool:
    return (
        type(key) is str
        and 0 < len(key) <= MAX_IDEMPOTENCY_KEY_LENGTH
        and key.strip() != ""
        and not any(ord(c) < 32 or ord(c) == 127 for c in key)
    )


class VerticalReferenceDeclarationStore:
    """``DurableJournal`` 위의 인메모리 projection. 자료 사실은 쓰기마다 호출자가 넘긴다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._journal = journal
        self._coordinator = coordinator
        self._lock = threading.Lock()
        # (org, site, asset_ref) -> 순서대로 쌓인 기록 (index = sequence - 1)
        self._ledger: dict[tuple[str, str, str], list[_Stored]] = {}
        # (org, principal, site, asset_ref, key_hash) -> (request_digest, sequence)
        self._idempotency: dict[tuple[str, str, str, str, str], tuple[str, int]] = {}
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
                raise VerticalReferenceDeclarationRecoveryError(
                    f"vertical-reference-declaration journal 재생 실패 — 오염된 레코드: {exc}"
                ) from exc

    def _apply(self, raw: dict[str, Any]) -> None:
        record = VerticalReferenceDeclarationV1.model_validate(raw["declaration"])
        if record.declaration_digest is None or record.declaration_digest != (
            record.canonical_digest()
        ):
            raise ValueError("선언 서명이 내용과 맞지 않는다")
        organization_id, actor = raw["organizationId"], raw["actor"]
        if not (isinstance(organization_id, str) and isinstance(actor, str)):
            raise ValueError("조직·주체가 문자열이 아니다")
        if actor != record.declared_by:
            raise ValueError("기록의 선언자와 원장 주체가 다르다")
        key = (organization_id, record.site_id, record.asset_ref)
        history = self._ledger.setdefault(key, [])
        if len(history) != record.sequence - 1:
            raise ValueError(f"sequence 가 이어지지 않는다: {record.asset_ref}")
        if history and history[0].record.work_area_id != record.work_area_id:
            raise ValueError("다른 작업구역의 기록을 이어 붙일 수 없다")
        if record.declaration_id != self._declaration_id(
            organization_id, record.site_id, record.asset_ref, record.sequence
        ):
            raise ValueError("선언 식별자가 결정적 신원과 다르다")
        if record.status == "WITHDRAWN" and (not history or history[-1].record.status != "ACTIVE"):
            raise ValueError("활성 선언이 없는데 철회가 기록돼 있다")
        history.append(_Stored(organization_id, actor, record))
        key_hash, request_digest = raw["keyHash"], raw["requestDigest"]
        self._idempotency[(organization_id, actor, record.site_id, record.asset_ref, key_hash)] = (
            request_digest,
            record.sequence,
        )

    @staticmethod
    def _declaration_id(organization_id: str, site_id: str, asset_ref: str, sequence: int) -> str:
        scope = {"scope": [organization_id, site_id, asset_ref, sequence]}
        return "vrd-" + _digest(scope).removeprefix("sha256:")[:32]

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def history(
        self, *, organization_id: str, site_id: str, asset_ref: str
    ) -> tuple[VerticalReferenceDeclarationV1, ...]:
        with self._lock:
            stored = self._ledger.get((organization_id, site_id, asset_ref), [])
            return tuple(item.record for item in stored)

    def current(
        self, *, organization_id: str, site_id: str, asset_ref: str
    ) -> VerticalReferenceDeclarationV1 | None:
        """지금 유효한 선언, 없거나 철회됐으면 ``None``. 판정이 읽는 유일한 진입점이다."""
        history = self.history(
            organization_id=organization_id, site_id=site_id, asset_ref=asset_ref
        )
        if history and history[-1].status == "ACTIVE":
            return history[-1]
        return None

    def active_declaration(
        self,
        *,
        organization_id: str,
        site_id: str,
        asset_ref: str,
        at: datetime | None = None,
    ) -> VerticalReferenceDeclarationV1 | None:
        """``at`` 시점(없으면 지금)에 유효했던 선언. 과거 판정의 근거를 그 시점으로 묻는 용도다."""
        history = self.history(
            organization_id=organization_id, site_id=site_id, asset_ref=asset_ref
        )
        if at is not None:
            history = tuple(item for item in history if item.declared_at <= at)
        if history and history[-1].status == "ACTIVE":
            return history[-1]
        return None

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def declare(
        self,
        *,
        organization_id: str,
        principal_id: str,
        facts: AssetFacts | None,
        body: DeclareVerticalReferenceV1,
        idempotency_key: str,
        now: datetime,
    ) -> DeclarationResult:
        request_digest = _digest({"op": "declare", **body.model_dump(by_alias=True, mode="json")})
        return self._write(
            organization_id=organization_id,
            principal_id=principal_id,
            facts=facts,
            expected_sequence=body.expected_sequence,
            declaration=body,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            now=now,
        )

    def withdraw(
        self,
        *,
        organization_id: str,
        principal_id: str,
        facts: AssetFacts | None,
        body: WithdrawVerticalReferenceV1,
        idempotency_key: str,
        now: datetime,
    ) -> DeclarationResult:
        request_digest = _digest({"op": "withdraw", **body.model_dump(by_alias=True, mode="json")})
        return self._write(
            organization_id=organization_id,
            principal_id=principal_id,
            facts=facts,
            expected_sequence=body.expected_sequence,
            declaration=None,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            now=now,
        )

    def _write(
        self,
        *,
        organization_id: str,
        principal_id: str,
        facts: AssetFacts | None,
        expected_sequence: int,
        declaration: DeclareVerticalReferenceV1 | None,
        request_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> DeclarationResult:
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다")
        if not _valid_key(idempotency_key):
            return DeclarationResult(
                DeclarationVerdict.INVALID, detail="Idempotency-Key 가 올바르지 않다"
            )
        if facts is None:
            return DeclarationResult(DeclarationVerdict.UNKNOWN_ASSET)
        key_hash = _digest({"key": idempotency_key})
        ledger_key = (organization_id, facts.site_id, facts.asset_ref)
        idem = (organization_id, principal_id, facts.site_id, facts.asset_ref, key_hash)
        with self._coordinator.mutation(), self._lock:
            history = self._ledger.get(ledger_key, [])
            existing = self._idempotency.get(idem)
            if existing is not None:
                # 같은 키는 자료 상태가 바뀐 뒤에도 원래 결과를 돌려준다(응답 유실 복구).
                stored_digest, sequence = existing
                if stored_digest != request_digest:
                    return DeclarationResult(
                        DeclarationVerdict.IDEMPOTENCY_CONFLICT,
                        detail="Idempotency-Key 가 다른 요청에 이미 사용됐다",
                    )
                return DeclarationResult(DeclarationVerdict.REPLAYED, history[sequence - 1].record)
            if self._journal.sealed_reason is not None:
                return DeclarationResult(
                    DeclarationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if facts.kind is not ProcessingArtifactKind.DSM:
                return DeclarationResult(
                    DeclarationVerdict.NOT_A_DSM, detail="수직 기준은 DSM에만 선언한다"
                )
            if not facts.measured:
                return DeclarationResult(
                    DeclarationVerdict.NOT_MEASURED,
                    detail="파일 검사로 확인된 DSM에만 선언한다",
                )
            if declaration is not None and facts.observed_vertical_reference:
                return DeclarationResult(
                    DeclarationVerdict.OBSERVED_REFERENCE_PRESENT,
                    detail="파일이 수직 기준을 담고 있어 선언이 필요 없다",
                )
            if expected_sequence != len(history):
                return DeclarationResult(
                    DeclarationVerdict.SEQUENCE_CONFLICT,
                    detail=f"최신 sequence 는 {len(history)} 다 — 다시 읽고 선언한다",
                )
            if declaration is None and (not history or history[-1].record.status != "ACTIVE"):
                return DeclarationResult(DeclarationVerdict.NOTHING_TO_WITHDRAW)
            if len(history) >= MAX_DECLARATIONS_PER_ASSET:
                return DeclarationResult(
                    DeclarationVerdict.TOO_MANY_DECLARATIONS,
                    detail=f"선언 기록이 상한 {MAX_DECLARATIONS_PER_ASSET}개다",
                )
            number = len(history) + 1
            try:
                record = VerticalReferenceDeclarationV1(
                    declaration_id=self._declaration_id(
                        organization_id, facts.site_id, facts.asset_ref, number
                    ),
                    site_id=facts.site_id,
                    work_area_id=facts.work_area_id,
                    asset_ref=facts.asset_ref,
                    sequence=number,
                    status="ACTIVE" if declaration is not None else "WITHDRAWN",
                    datum=declaration.datum if declaration is not None else None,
                    unit="metre",
                    basis=declaration.basis if declaration is not None else None,
                    declared_by=principal_id,
                    declared_at=now,
                ).sealed()
            except ValidationError as exc:
                return DeclarationResult(
                    DeclarationVerdict.INVALID, detail=str(exc.errors()[0]["msg"])
                )
            raw: dict[str, Any] = {
                "kind": _KIND,
                "ts": iso_utc(now),
                "actor": principal_id,
                "organizationId": organization_id,
                "keyHash": key_hash,
                "requestDigest": request_digest,
                "declaration": record.model_dump(by_alias=True, mode="json"),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return DeclarationResult(
                    DeclarationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            self._apply(raw)
            return DeclarationResult(
                DeclarationVerdict.DECLARED
                if declaration is not None
                else DeclarationVerdict.WITHDRAWN,
                record,
            )


class CatalogDeclarationAssetPort:
    """실제 자료 카탈로그가 현재 권한 범위에서 만든 사실만 쓴다. 새 권한도 저장소도 만들지 않는다.

    자료가 없거나 범위 밖이면 카탈로그가 404 를 던지거나 ``None`` 이다. 파일 검사 결과는 선택한
    자료 하나에만 붙인다(카탈로그의 규칙 그대로).
    """

    _ASSET_REF = re.compile(r"^ksa-v1-[0-9a-f]{64}$")

    def __init__(self, catalog: SpatialAssetCatalog) -> None:
        self._catalog = catalog

    def facts(
        self, *, principal: Principal, site_id: str, work_area_id: str, asset_ref: str
    ) -> AssetFacts | None:
        if self._ASSET_REF.fullmatch(asset_ref) is None:
            return None
        candidate = next(
            (
                item
                for item in self._catalog.items(site_id, work_area_id, principal)
                if item.asset_ref == asset_ref
            ),
            None,
        )
        if candidate is None:
            return None
        item = self._catalog.with_inspection(candidate, principal)
        raster = item.inspection.raster
        return AssetFacts(
            site_id=item.site_id,
            work_area_id=item.work_area_id,
            asset_ref=item.asset_ref,
            kind=item.kind,
            measured=item.inspection.outcome == "MEASURED",
            observed_vertical_reference=(
                raster is not None and raster.observed_vertical_reference is not None
            ),
        )


# ── HTTP ─────────────────────────────────────────────────────────────────
_BASE = (
    "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}/vertical-reference"
)


def build_vertical_reference_declaration_router(
    store: VerticalReferenceDeclarationStore,
    assets: DeclarationAssetPort,
    *,
    clock: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(tags=["vertical-reference-declarations"])

    def facts_for(
        principal: Principal, site_id: str, work_area_id: str, asset_ref: str
    ) -> AssetFacts | None:
        """권한 밖 범위는 존재 자체를 숨긴다. 자료 포트가 404 를 던지면 그대로 올린다."""
        return assets.facts(
            principal=principal, site_id=site_id, work_area_id=work_area_id, asset_ref=asset_ref
        )

    def respond(result: DeclarationResult) -> Response:
        body: VerticalReferenceDeclarationWriteViewV1 | VerticalReferenceDeclarationRefusalV1
        if result.declaration is not None:
            body = VerticalReferenceDeclarationWriteViewV1(
                verdict=result.verdict.value,  # type: ignore[arg-type]
                declaration=result.declaration,
            )
        else:
            body = VerticalReferenceDeclarationRefusalV1(
                verdict=result.verdict.value,  # type: ignore[arg-type]
                detail=result.detail,
            )
        reply = JSONResponse(
            body.model_dump(by_alias=True, mode="json"), status_code=_STATUS[result.verdict]
        )
        if result.verdict is DeclarationVerdict.STORE_UNAVAILABLE:
            reply.headers["Retry-After"] = "30"
        return reply

    @router.get(_BASE, response_model=VerticalReferenceDeclarationStateViewV1)
    def get_state(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> VerticalReferenceDeclarationStateViewV1:
        facts = facts_for(principal, site_id, work_area_id, asset_ref)
        if facts is None:
            raise HTTPException(status_code=404, detail="자료를 찾을 수 없다")
        history = store.history(
            organization_id=principal.organization_id, site_id=site_id, asset_ref=asset_ref
        )
        current = history[-1] if history and history[-1].status == "ACTIVE" else None
        return VerticalReferenceDeclarationStateViewV1(
            asset_ref=asset_ref,
            observed=facts.observed_vertical_reference,
            current=current,
            history=history,
        )

    @router.post(
        _BASE + "/declarations",
        response_model=VerticalReferenceDeclarationWriteViewV1,
        status_code=201,
    )
    def declare(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        body: DeclareVerticalReferenceV1,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008
    ) -> Response:
        return respond(
            store.declare(
                organization_id=principal.organization_id,
                principal_id=principal.principal_id,
                facts=facts_for(principal, site_id, work_area_id, asset_ref),
                body=body,
                idempotency_key=idempotency_key,
                now=clock(),
            )
        )

    @router.post(
        _BASE + "/withdrawals",
        response_model=VerticalReferenceDeclarationWriteViewV1,
        status_code=201,
    )
    def withdraw(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        body: WithdrawVerticalReferenceV1,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008
    ) -> Response:
        return respond(
            store.withdraw(
                organization_id=principal.organization_id,
                principal_id=principal.principal_id,
                facts=facts_for(principal, site_id, work_area_id, asset_ref),
                body=body,
                idempotency_key=idempotency_key,
                now=clock(),
            )
        )

    return router


def mount_vertical_reference_declarations(
    app: FastAPI,
    store: VerticalReferenceDeclarationStore,
    assets: DeclarationAssetPort,
    *,
    clock: Callable[[], datetime],
) -> None:
    app.state.vertical_reference_declaration_store = store
    app.include_router(build_vertical_reference_declaration_router(store, assets, clock=clock))


__all__ = [
    "AssetFacts",
    "CatalogDeclarationAssetPort",
    "DeclarationAssetPort",
    "DeclarationResult",
    "DeclarationVerdict",
    "VerticalReferenceDeclarationRecoveryError",
    "VerticalReferenceDeclarationStore",
    "build_vertical_reference_declaration_router",
    "mount_vertical_reference_declarations",
]

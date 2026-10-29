"""Durable, scoped external/Console handoff. Analysis and WorkArea stay authoritative.

No URL is a capability. Every read/transition resolves current authenticated scope,
and the external creator must reauthenticate to resume. Human selection is limited
by both the human's current grants and the creator's original scope ceiling.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_spatial_task import (
    CreateSpatialTaskV1,
    RunSpatialTaskV1,
    SelectSpatialTaskV1,
    SpatialTaskAreaV1,
    SpatialTaskObservationV1,
    SpatialTaskOptionsV1,
    SpatialTaskPurposeV1,
    SpatialTaskSelectionV1,
    SpatialTaskSitesV1,
    SpatialTaskSiteV1,
    SpatialTaskV1,
    SpatialTaskViewV1,
)
from ksi_event_contracts.work_area import WorkAreaStatus
from pydantic import Field

from ksi_core.domains.external.quantity.external_analysis_api import (
    AnalysisScopeNotFound,
    AnalysisSnapshotChanged,
)
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    principal_permissions,
    require_permission_any,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fail(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail=code)


class _Record(_CamelModel):
    task: SpatialTaskV1
    organization_id: str
    creator_id: str
    creator_kind: str
    area_ceiling: tuple[str, ...] | None
    idempotency_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_from_revision: int | None = Field(default=None, ge=1)


class _Event(_CamelModel):
    kind: Literal["spatial-task-snapshot"] = "spatial-task-snapshot"
    version: Literal[1] = 1
    record: _Record
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SpatialTaskRecoveryError(RuntimeError):
    pass


class SpatialTaskStore:
    """Single-writer journal, bounded retained tasks/revisions, fail-closed replay.

    The common coordinator serializes selection, area archival and run reservation.
    A durable reservation freezes selection before calling the existing idempotent
    Analysis create, making a crash between those two journals safely resumable.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        sites: Any,
        areas: Any,
        work_orders: Any,
        analysis: Any,
        coordinator: Any,
    ) -> None:
        self.journal = journal
        self.sites, self.areas, self.work_orders = sites, areas, work_orders
        self.analysis, self.coordinator = analysis, coordinator
        self._lock = threading.RLock()
        self._records: dict[str, _Record] = {}
        self._keys: dict[tuple[str, str, str, str], str] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            raise SpatialTaskRecoveryError("invalid spatial task journal") from exc

    @staticmethod
    def _key(record: _Record) -> tuple[str, str, str, str]:
        return (
            record.organization_id,
            record.creator_id,
            record.creator_kind,
            record.idempotency_digest,
        )

    def _validate(self, record: _Record) -> None:
        old = self._records.get(record.task.task_id)
        task = record.task
        if task.expires_at != task.created_at + timedelta(days=7):
            raise ValueError("invalid task lifetime")
        if task.revision > 128 or (task.analysis_id and not task.execution_requested):
            raise ValueError("invalid task lifecycle")
        if (
            task.selection.work_area_id is not None
            and record.area_ceiling is not None
            and (task.selection.work_area_id not in record.area_ceiling)
        ):
            raise ValueError("selected area outside retained ceiling")
        if task.execution_requested != (record.run_from_revision is not None):
            raise ValueError("invalid run reservation")
        if task.execution_requested and (
            task.selection.purpose is not SpatialTaskPurposeV1.OBSERVED_CHANGE
            or task.selection.inputs is None
            or task.selection.work_area_id is None
        ):
            raise ValueError("unsupported reserved selection")
        if old is None:
            if task.revision != 1 or task.execution_requested or task.analysis_id:
                raise ValueError("invalid initial task")
            if self._key(record) in self._keys:
                raise ValueError("duplicate task key")
            if record.request_digest != _digest(
                {
                    "siteId": task.site_id,
                    "request": task.selection.model_dump(mode="json"),
                }
            ):
                raise ValueError("initial request binding mismatch")
            if (
                len(self._records) >= 10000
                or sum(
                    item.organization_id == record.organization_id
                    for item in self._records.values()
                )
                >= 2048
            ):
                raise ValueError("retained task capacity")
            return
        identity = (
            "organization_id",
            "creator_id",
            "creator_kind",
            "area_ceiling",
            "idempotency_digest",
            "request_digest",
        )
        if any(getattr(old, key) != getattr(record, key) for key in identity):
            raise ValueError("task identity changed")
        if (
            task.revision != old.task.revision + 1
            or task.site_id != old.task.site_id
            or task.created_at != old.task.created_at
            or task.expires_at != old.task.expires_at
        ):
            raise ValueError("invalid task revision")
        if old.task.execution_requested:
            if (
                not task.execution_requested
                or task.selection != old.task.selection
                or record.run_from_revision != old.run_from_revision
                or (old.task.analysis_id and task.analysis_id != old.task.analysis_id)
            ):
                raise ValueError("reserved task changed")
        elif task.execution_requested and (
            record.run_from_revision != old.task.revision
            or task.selection != old.task.selection
            or task.analysis_id is not None
        ):
            raise ValueError("invalid reservation transition")

    def _apply(self, raw: Any) -> None:
        event = _Event.model_validate(raw)
        record = event.record
        if event.digest != _digest(record.model_dump(mode="json", by_alias=True)):
            raise ValueError("task digest mismatch")
        self._validate(record)
        self._records[record.task.task_id] = record
        self._keys[self._key(record)] = record.task.task_id

    def _save(self, record: _Record) -> _Record:
        try:
            self._validate(record)
        except ValueError as exc:
            raise _fail("SPATIAL_TASK_CAPACITY_OR_TRANSITION", 409) from exc
        event = _Event(record=record, digest=_digest(record.model_dump(mode="json", by_alias=True)))
        try:
            self.journal.append(event.model_dump(mode="json", by_alias=True))
        except JournalSealedError as exc:
            raise _fail("SPATIAL_TASK_STORE_UNAVAILABLE", 503) from exc
        self._apply(event.model_dump(mode="json", by_alias=True))
        return record

    def _site(self, principal: Principal, site_id: str) -> Any:
        if principal.kind not in (PrincipalKind.OPERATOR, PrincipalKind.ANALYSIS_MCP_CLIENT):
            raise _fail("SPATIAL_TASK_PERMISSION_DENIED", 403)
        if not principal_permissions(principal).intersection(
            {Permission.SITES_READ, Permission.ANALYSIS_API_READ}
        ):
            raise _fail("SPATIAL_TASK_PERMISSION_DENIED", 403)
        site = self.sites.get_scoped(site_id, principal.organization_id)
        if site is None or (
            principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids
        ):
            raise _fail("SPATIAL_TASK_NOT_FOUND", 404)
        if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT and not site.ai_egress_allowed:
            raise _fail("AI_EGRESS_NOT_ALLOWED", 403)
        return site

    @staticmethod
    def _write(principal: Principal) -> None:
        if not principal_permissions(principal).intersection(
            {Permission.SITES_WRITE, Permission.ANALYSIS_API_CREATE}
        ):
            raise _fail("SPATIAL_TASK_PERMISSION_DENIED", 403)

    def _area_ids(
        self, principal: Principal, site_id: str, ceiling: tuple[str, ...] | None
    ) -> set[str]:
        return {
            area.work_area_id
            for area in self.areas.list_for_site(site_id)
            if area.status is WorkAreaStatus.ACTIVE
            and (ceiling is None or area.work_area_id in ceiling)
            and (
                principal.allowed_work_area_ids is None
                or area.work_area_id in principal.allowed_work_area_ids
            )
        }

    def options(
        self, principal: Principal, site_id: str, ceiling: tuple[str, ...] | None, offset: int = 0
    ) -> SpatialTaskOptionsV1:
        self._site(principal, site_id)
        ids = self._area_ids(principal, site_id, ceiling)
        areas = tuple(
            SpatialTaskAreaV1(work_area_id=area.work_area_id, name=area.name)
            for area in self.areas.list_for_site(site_id)
            if area.work_area_id in ids
        )
        options = self.analysis.observation_options(principal=principal, site_id=site_id)
        observations = []
        for item in options.items:
            order = self.work_orders.get(
                item.selector.work_order_id, organization_id=principal.organization_id
            )
            # All source WorkOrder areas must be in both scopes. No partial disclosure.
            if (
                order is None
                or order.site_id != site_id
                or not order.work_area_ids
                or not set(order.work_area_ids).issubset(ids)
            ):
                continue
            observations.append(
                SpatialTaskObservationV1(
                    **item.model_dump(), work_area_ids=tuple(order.work_area_ids)
                )
            )
        return SpatialTaskOptionsV1(
            site_id=site_id,
            areas=areas,
            observations=tuple(observations[offset : offset + 32]),
            next_offset=offset + 32 if offset + 32 < len(observations) else None,
        )

    def _selection(
        self,
        principal: Principal,
        site_id: str,
        ceiling: tuple[str, ...] | None,
        selection: SpatialTaskSelectionV1,
    ) -> None:
        self._site(principal, site_id)
        if selection.work_area_id is not None and selection.work_area_id not in self._area_ids(
            principal, site_id, ceiling
        ):
            raise _fail("SPATIAL_TASK_SELECTION_UNAVAILABLE", 409)
        if selection.inputs is not None:
            # Resolve the exact selectors, not latest timestamps or approximate WorkOrders.
            available: list[SpatialTaskObservationV1] = []
            offset = 0
            while True:
                page = self.options(principal, site_id, ceiling, offset)
                available.extend(page.observations)
                if page.next_offset is None:
                    break
                offset = page.next_offset
            for selector in (selection.inputs.baseline, selection.inputs.current):
                if not any(
                    item.selector == selector
                    and (
                        selection.work_area_id is None
                        or selection.work_area_id in item.work_area_ids
                    )
                    for item in available
                ):
                    raise _fail("SPATIAL_TASK_SELECTION_UNAVAILABLE", 409)

    def _get(self, principal: Principal, site_id: str, task_id: str, now: datetime) -> _Record:
        self._site(principal, site_id)
        record = self._records.get(task_id)
        if (
            record is None
            or record.organization_id != principal.organization_id
            or record.task.site_id != site_id
            or (
                principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
                and (
                    record.creator_id != principal.principal_id
                    or record.creator_kind != principal.kind.value
                )
            )
        ):
            raise _fail("SPATIAL_TASK_NOT_FOUND", 404)
        # A scoped human must have an intersection before any task facts are disclosed.
        if (
            principal.allowed_work_area_ids is not None
            and record.area_ceiling is not None
            and not set(principal.allowed_work_area_ids).intersection(record.area_ceiling)
        ):
            raise _fail("SPATIAL_TASK_NOT_FOUND", 404)
        if now >= record.task.expires_at:
            raise _fail("SPATIAL_TASK_EXPIRED", 410)
        selected = record.task.selection
        if (
            selected.work_area_id is not None
            and principal.allowed_work_area_ids is not None
            and selected.work_area_id not in principal.allowed_work_area_ids
        ):
            raise _fail("SPATIAL_TASK_NOT_FOUND", 404)
        if selected.inputs is not None:
            for selector in (selected.inputs.baseline, selected.inputs.current):
                order = self.work_orders.get(
                    selector.work_order_id, organization_id=principal.organization_id
                )
                if (
                    order is None
                    or order.site_id != site_id
                    or not order.work_area_ids
                    or (
                        principal.allowed_work_area_ids is not None
                        and not set(order.work_area_ids).issubset(principal.allowed_work_area_ids)
                    )
                ):
                    raise _fail("SPATIAL_TASK_NOT_FOUND", 404)
        return record.model_copy(deep=True)

    def create(
        self,
        principal: Principal,
        site_id: str,
        request: CreateSpatialTaskV1,
        key: str,
        now: datetime,
    ) -> SpatialTaskViewV1:
        self._write(principal)
        with self.coordinator.mutation(), self._lock:
            ceiling = (
                tuple(sorted(principal.allowed_work_area_ids))
                if principal.allowed_work_area_ids is not None
                else None
            )
            self._selection(principal, site_id, ceiling, request)
            digest = _digest({"key": key})
            lookup = (
                principal.organization_id,
                principal.principal_id,
                principal.kind.value,
                digest,
            )
            previous = self._keys.get(lookup)
            request_digest = _digest(
                {"siteId": site_id, "request": request.model_dump(mode="json")}
            )
            if previous:
                record = self._get(principal, site_id, previous, now)
                if record.request_digest != request_digest:
                    raise _fail("SPATIAL_TASK_IDEMPOTENCY_CONFLICT")
            else:
                record = self._save(
                    _Record(
                        task=SpatialTaskV1(
                            task_id="st-" + uuid4().hex,
                            site_id=site_id,
                            revision=1,
                            selection=SpatialTaskSelectionV1(**request.model_dump()),
                            created_at=now,
                            expires_at=now + timedelta(days=7),
                        ),
                        organization_id=principal.organization_id,
                        creator_id=principal.principal_id,
                        creator_kind=principal.kind.value,
                        area_ceiling=ceiling,
                        idempotency_digest=digest,
                        request_digest=request_digest,
                    )
                )
            return self.view(record, principal, now)

    def select(
        self,
        principal: Principal,
        site_id: str,
        task_id: str,
        request: SelectSpatialTaskV1,
        now: datetime,
    ) -> SpatialTaskViewV1:
        self._write(principal)
        with self.coordinator.mutation(), self._lock:
            record = self._get(principal, site_id, task_id, now)
            selection = SpatialTaskSelectionV1(**request.model_dump(exclude={"expected_revision"}))
            if record.task.execution_requested:
                raise _fail("SPATIAL_TASK_SELECTION_LOCKED")
            if request.expected_revision != record.task.revision:
                if (
                    request.expected_revision == record.task.revision - 1
                    and selection == record.task.selection
                ):
                    return self.view(record, principal, now)  # lost response retry
                raise _fail("SPATIAL_TASK_REVISION_CONFLICT")
            self._selection(principal, site_id, record.area_ceiling, selection)
            task = record.task.model_copy(
                update={"selection": selection, "revision": record.task.revision + 1}
            )
            return self.view(self._save(record.model_copy(update={"task": task})), principal, now)

    def view(self, record: _Record, principal: Principal, now: datetime) -> SpatialTaskViewV1:
        task, selection = record.task, record.task.selection
        unavailable = False
        try:
            self._selection(principal, task.site_id, record.area_ceiling, selection)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            unavailable = True
        state: Literal[
            "PURPOSE_REQUIRED",
            "UNSUPPORTED_PURPOSE",
            "AREA_REQUIRED",
            "OBSERVATIONS_REQUIRED",
            "CHECK_REQUIRED",
            "ANALYSIS_PENDING",
            "ANALYSIS_LINKED",
            "SELECTION_UNAVAILABLE",
        ]
        if unavailable:
            state = "SELECTION_UNAVAILABLE"
        elif task.analysis_id:
            state = "ANALYSIS_LINKED"
        elif task.execution_requested:
            state = "ANALYSIS_PENDING"
        elif selection.purpose is SpatialTaskPurposeV1.CLARIFY:
            state = "PURPOSE_REQUIRED"
        elif selection.purpose is not SpatialTaskPurposeV1.OBSERVED_CHANGE:
            state = "UNSUPPORTED_PURPOSE"
        elif selection.work_area_id is None:
            state = "AREA_REQUIRED"
        elif selection.inputs is None:
            state = "OBSERVATIONS_REQUIRED"
        else:
            state = "CHECK_REQUIRED"
        try:
            analysis = (
                self.analysis.get_v2(
                    principal=principal, site_id=task.site_id, analysis_id=task.analysis_id, now=now
                )
                if task.analysis_id and not unavailable
                else None
            )
        except AnalysisSnapshotChanged as exc:
            raise _fail("ANALYSIS_SNAPSHOT_CHANGED") from exc
        except AnalysisScopeNotFound as exc:
            raise _fail("SPATIAL_TASK_NOT_FOUND", 404) from exc
        return SpatialTaskViewV1(
            task=task,
            state=state,
            selection_href=f"/sites/{task.site_id}/spatial-tasks/{task.task_id}",
            analysis_href=f"/sites/{task.site_id}/analysis?analysisId={task.analysis_id}"
            if task.analysis_id
            else None,
            analysis=analysis,
        )

    def read(
        self, principal: Principal, site_id: str, task_id: str, now: datetime
    ) -> SpatialTaskViewV1:
        with self.coordinator.guarded_read(), self._lock:
            return self.view(self._get(principal, site_id, task_id, now), principal, now)

    def check_or_run(
        self,
        principal: Principal,
        site_id: str,
        task_id: str,
        revision: int,
        now: datetime,
        *,
        run: bool,
        activation: Any,
    ) -> SpatialTaskViewV1:
        if run:
            self._write(principal)
        with self.coordinator.mutation(), self._lock:
            record = self._get(principal, site_id, task_id, now)
            self._selection(principal, site_id, record.area_ceiling, record.task.selection)
            if revision != record.task.revision and not (
                run and record.task.execution_requested and revision == record.run_from_revision
            ):
                raise _fail("SPATIAL_TASK_REVISION_CONFLICT")
            selection = record.task.selection
            if selection.purpose is not SpatialTaskPurposeV1.OBSERVED_CHANGE:
                raise _fail("SPATIAL_TASK_PURPOSE_UNSUPPORTED")
            if selection.work_area_id is None or selection.inputs is None:
                raise _fail("SPATIAL_TASK_SELECTION_REQUIRED")
            readiness = self.analysis.check_readiness(
                principal=principal,
                site_id=site_id,
                work_area_id=selection.work_area_id,
                request=selection.inputs,
                now=now,
            )
            if run:
                if activation is None or not activation.is_current_at(now):
                    raise _fail("ANALYSIS_ACTIVATION_UNAVAILABLE", 503)
                if not record.task.execution_requested:
                    # Reserve room for BOTH reservation and Analysis linkage.
                    # Never create an Analysis that this task cannot durably link.
                    if record.task.revision > 126:
                        raise _fail("SPATIAL_TASK_REVISION_LIMIT")
                    record = self._save(
                        record.model_copy(
                            update={
                                "task": record.task.model_copy(
                                    update={
                                        "execution_requested": True,
                                        "revision": record.task.revision + 1,
                                    }
                                ),
                                "run_from_revision": record.task.revision,
                            }
                        )
                    )
                analysis = self.analysis.create_v2(
                    principal=principal,
                    site_id=site_id,
                    work_area_id=selection.work_area_id,
                    request=selection.inputs,
                    idempotency_key="spatial-task-" + task_id,
                    now=now,
                )
                if record.task.analysis_id is None:
                    record = self._save(
                        record.model_copy(
                            update={
                                "task": record.task.model_copy(
                                    update={
                                        "analysis_id": analysis.analysis_id,
                                        "revision": record.task.revision + 1,
                                    }
                                )
                            }
                        )
                    )
            return self.view(record, principal, now).model_copy(update={"readiness": readiness})


def build_spatial_task_router(
    store: SpatialTaskStore, *, activation: Any = None, clock: Any = None
) -> APIRouter:
    router = APIRouter(tags=["external-spatial-tasks"])
    read = require_permission_any(Permission.SITES_READ, Permission.ANALYSIS_API_READ)
    write = require_permission_any(Permission.SITES_WRITE, Permission.ANALYSIS_API_CREATE)
    now = clock or (lambda: datetime.now(UTC))

    def headers(principal: Principal, response: Response) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT:
            response.headers["X-KSI-External-AI-Egress"] = "ALLOWED"

    @router.get("/v1/spatial-task-sites", response_model=SpatialTaskSitesV1)
    def sites(
        response: Response,
        offset: int = Query(default=0, ge=0, le=10000),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialTaskSitesV1:  # noqa: B008
        # External identities enumerate only already provisioned Site grants.
        items = []
        if principal.allowed_site_ids is None:
            raise _fail("SPATIAL_TASK_EXPLICIT_SITE_SCOPE_REQUIRED", 403)
        for site_id in sorted(principal.allowed_site_ids):
            site = store.sites.get_scoped(site_id, principal.organization_id)
            if site is not None and (
                principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT or site.ai_egress_allowed
            ):
                items.append(SpatialTaskSiteV1(site_id=site_id, name=site.name))
        headers(principal, response)
        return SpatialTaskSitesV1(
            items=tuple(items[offset : offset + 32]),
            next_offset=offset + 32 if offset + 32 < len(items) else None,
        )

    base = "/v1/sites/{site_id}/spatial-tasks"

    @router.post(base, response_model=SpatialTaskViewV1, status_code=201)
    def create(
        site_id: str,
        request: CreateSpatialTaskV1,
        response: Response,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
        principal: Principal = Depends(write),  # noqa: B008
    ) -> SpatialTaskViewV1:  # noqa: B008
        if not all(0x21 <= ord(c) <= 0x7E for c in idempotency_key):
            raise _fail("SPATIAL_TASK_INVALID_IDEMPOTENCY_KEY", 400)
        result = store.create(principal, site_id, request, idempotency_key, now())
        headers(principal, response)
        return result

    @router.get(base + "/{task_id}", response_model=SpatialTaskViewV1)
    def get(
        site_id: str,
        task_id: str,
        response: Response,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialTaskViewV1:  # noqa: B008
        result = store.read(principal, site_id, task_id, now())
        headers(principal, response)
        return result

    @router.get(base + "/{task_id}/options", response_model=SpatialTaskOptionsV1)
    def options(
        site_id: str,
        task_id: str,
        response: Response,
        offset: int = Query(default=0, ge=0, le=500),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialTaskOptionsV1:  # noqa: B008
        with store.coordinator.guarded_read(), store._lock:
            record = store._get(principal, site_id, task_id, now())
            result = store.options(principal, site_id, record.area_ceiling, offset)
        headers(principal, response)
        return result

    @router.post(base + "/{task_id}/selection", response_model=SpatialTaskViewV1)
    def select(
        site_id: str,
        task_id: str,
        request: SelectSpatialTaskV1,
        response: Response,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> SpatialTaskViewV1:  # noqa: B008
        result = store.select(principal, site_id, task_id, request, now())
        headers(principal, response)
        return result

    def action(
        site_id: str,
        task_id: str,
        request: RunSpatialTaskV1,
        response: Response,
        principal: Principal,
        run: bool,
    ) -> SpatialTaskViewV1:
        try:
            result = store.check_or_run(
                principal,
                site_id,
                task_id,
                request.expected_revision,
                now(),
                run=run,
                activation=activation,
            )
        except AnalysisScopeNotFound as exc:
            raise _fail("SPATIAL_TASK_SELECTION_UNAVAILABLE", 409) from exc
        except AnalysisSnapshotChanged as exc:
            raise _fail("ANALYSIS_SNAPSHOT_CHANGED", 409) from exc
        headers(principal, response)
        return result

    @router.post(base + "/{task_id}/readiness", response_model=SpatialTaskViewV1)
    def check(
        site_id: str,
        task_id: str,
        request: RunSpatialTaskV1,
        response: Response,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialTaskViewV1:  # noqa: B008
        return action(site_id, task_id, request, response, principal, False)

    @router.post(base + "/{task_id}/run", response_model=SpatialTaskViewV1)
    def run(
        site_id: str,
        task_id: str,
        request: RunSpatialTaskV1,
        response: Response,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> SpatialTaskViewV1:  # noqa: B008
        return action(site_id, task_id, request, response, principal, True)

    return router

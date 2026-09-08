"""Read-only civil workflow readiness projected from existing immutable ledgers.

This module deliberately does **not** create a new workflow state or a second
comparison decision.  It makes the next two completed ProcessingJob epochs
and the existing civil preflight legible at Site scope, so an operator does
not have to infer an apparently-ready quantitative workflow from a successful
reconstruction alone.

The projection is advisory navigation only:

* :mod:`ksi_core.civil_preflight` remains the sole compatibility authority;
* creating a comparison or a design-conformance request still repeats every
  gate against the exact selected input;
* it never reports field acceptance, survey accuracy, a flight state, or a
  device capability.

That separation preserves REQ-INT-102/103/104 and INV-017/018/020/024/053:
unknown evidence is a typed blocker, not a green shortcut.  It also keeps
INV-060 at the public boundary by resolving the Site through the requesting
organization before reading any derived facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from ksi_event_contracts.design_surface import DesignSurfaceStatus
from ksi_event_contracts.processing_job import ProcessingJobStatus
from pydantic import Field

from ksi_core.api_base import CamelModel
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.civil_preflight import (
    AnalysisReadinessCheck,
    CivilPreflightReason,
    preflight_epoch_pair,
)

if TYPE_CHECKING:
    from ksi_event_contracts.design_surface import DesignSurface

    from ksi_core.processing_jobs import ProcessingJobRecord


class _SiteReader(Protocol):
    """Small read contract; the projector must not gain Site write authority."""

    def get_scoped(self, site_id: str, organization_id: str) -> object | None: ...


class _ProcessingJobReader(Protocol):
    """The only ProcessingJob operation needed for a Site readiness projection."""

    def list_for_site(
        self,
        site_id: str,
        *,
        organization_id: str | None = None,
        limit: int | None = None,
    ) -> list[ProcessingJobRecord]: ...


class _DesignSurfaceReader(Protocol):
    """Read-only design inventory contract; revision selection stays elsewhere."""

    def list_for_site(self, site_id: str) -> list[DesignSurface]: ...


_NOT_FOUND_DETAIL = "현장을 찾을 수 없다"


class CivilReadinessStatus(StrEnum):
    """The current Site-level temporal-comparison posture, never a field verdict."""

    SYSTEM_UNAVAILABLE = "SYSTEM_UNAVAILABLE"
    FIRST_EPOCH_REQUIRED = "FIRST_EPOCH_REQUIRED"
    SECOND_EPOCH_REQUIRED = "SECOND_EPOCH_REQUIRED"
    PAIR_BLOCKED = "PAIR_BLOCKED"
    PAIR_COMPATIBLE = "PAIR_COMPATIBLE"


class CivilReadinessReason(StrEnum):
    """Reasons owned by this projection rather than the quantitative preflight."""

    SYSTEM_UNAVAILABLE = "SYSTEM_UNAVAILABLE"
    FIRST_EPOCH_REQUIRED = "FIRST_EPOCH_REQUIRED"
    SECOND_EPOCH_REQUIRED = "SECOND_EPOCH_REQUIRED"


class CivilDesignSurfaceStatus(StrEnum):
    """Inventory summary only; the exact selected request repeats its own gate."""

    SYSTEM_UNAVAILABLE = "SYSTEM_UNAVAILABLE"
    NOT_REGISTERED = "NOT_REGISTERED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    VERIFIED_AVAILABLE = "VERIFIED_AVAILABLE"


CivilReadinessReasonCode = CivilReadinessReason | CivilPreflightReason
CivilReadinessLimitations = tuple[
    Literal["OPERATIONAL_RELATIVE_QUANTITY_ONLY"],
    Literal["FIELD_ACCEPTANCE_NOT_INCLUDED"],
]
_LIMITATIONS: CivilReadinessLimitations = (
    "OPERATIONAL_RELATIVE_QUANTITY_ONLY",
    "FIELD_ACCEPTANCE_NOT_INCLUDED",
)


class CivilEpochPairReadinessView(CamelModel):
    """Compatibility of the two latest succeeded epochs, newest as ``current``."""

    baseline_job_id: str | None
    current_job_id: str | None
    compatible: bool
    reason: CivilReadinessReasonCode | None
    detail: str


class CivilDesignSurfaceReadinessView(CamelModel):
    """Verified design-surface inventory without guessing which revision to use."""

    status: CivilDesignSurfaceStatus
    total_surface_count: int = Field(ge=0)
    verified_surface_count: int = Field(ge=0)
    detail: str


class CivilReadinessNextAction(CamelModel):
    """One informational next action; this object cannot authorize any write."""

    label: str
    href: str | None
    reason: str


class CivilReadinessView(CamelModel):
    """Site-scoped, evidence-derived civil workflow progress.

    ``limitations`` is deliberately part of the response rather than a UI
    footnote.  A consumer that omits it cannot honestly turn a compatible pair
    into a field-acceptance or survey-accuracy claim.
    """

    schema_version: Literal["1.0"] = "1.0"
    site_id: str
    status: CivilReadinessStatus
    succeeded_epoch_count: int = Field(ge=0)
    pair: CivilEpochPairReadinessView
    design_surface: CivilDesignSurfaceReadinessView
    next_action: CivilReadinessNextAction
    limitations: CivilReadinessLimitations


class CivilReadinessProjector:
    """Projects civil readiness without mutating a Site, job, surface, or request.

    The two latest successful jobs are shown intentionally.  Searching an
    older pair until a green pair appears would hide the fact that the latest
    acquisition cannot currently participate in a reproducible comparison.
    A user can still select a different historical pair in the existing
    ComparisonSubmitPanel, where Core checks that exact request again.
    """

    def __init__(
        self,
        *,
        site_store: _SiteReader,
        processing_job_store: _ProcessingJobReader,
        design_surface_store: _DesignSurfaceReader,
        analysis_readiness: AnalysisReadinessCheck | None,
    ) -> None:
        self._sites = site_store
        self._processing_jobs = processing_job_store
        self._design_surfaces = design_surface_store
        self._analysis_readiness = analysis_readiness

    def project(self, site_id: str, *, organization_id: str) -> CivilReadinessView:
        site = self._sites.get_scoped(site_id, organization_id)
        if site is None:
            raise LookupError(_NOT_FOUND_DETAIL)

        try:
            jobs = self._processing_jobs.list_for_site(
                site_id, organization_id=organization_id
            )
        except Exception:
            return self._unavailable(site_id)

        try:
            surfaces = self._design_surfaces.list_for_site(site_id)
            design_surface = self._design_surface_summary(surfaces)
        except Exception:
            design_surface = CivilDesignSurfaceReadinessView(
                status=CivilDesignSurfaceStatus.SYSTEM_UNAVAILABLE,
                total_surface_count=0,
                verified_surface_count=0,
                detail="설계 기준면 원장을 확인하지 못했습니다.",
            )

        succeeded = [job for job in jobs if job.status is ProcessingJobStatus.SUCCEEDED]
        if not succeeded:
            return CivilReadinessView(
                site_id=site_id,
                status=CivilReadinessStatus.FIRST_EPOCH_REQUIRED,
                succeeded_epoch_count=0,
                pair=CivilEpochPairReadinessView(
                    baseline_job_id=None,
                    current_job_id=None,
                    compatible=False,
                    reason=CivilReadinessReason.FIRST_EPOCH_REQUIRED,
                    detail="완료된 처리 시점이 없어 첫 조사 원본의 봉인·처리가 필요합니다.",
                ),
                design_surface=design_surface,
                next_action=self._first_epoch_action(site_id),
                limitations=_LIMITATIONS,
            )

        current = succeeded[0]
        if len(succeeded) == 1:
            return CivilReadinessView(
                site_id=site_id,
                status=CivilReadinessStatus.SECOND_EPOCH_REQUIRED,
                succeeded_epoch_count=1,
                pair=CivilEpochPairReadinessView(
                    baseline_job_id=None,
                    current_job_id=current.job_id,
                    compatible=False,
                    reason=CivilReadinessReason.SECOND_EPOCH_REQUIRED,
                    detail=(
                        "완료된 처리 시점이 1개입니다. 같은 처리 기준의 두 번째 조사 시점이 "
                        "필요합니다."
                    ),
                ),
                design_surface=design_surface,
                next_action=CivilReadinessNextAction(
                    label="두 번째 조사 시점 준비",
                    href=f"/sites/{quote(site_id, safe='')}?section=work",
                    reason="시계열 변화와 상대 물량은 서로 다른 두 시점을 비교해야 합니다.",
                ),
                limitations=_LIMITATIONS,
            )

        baseline = succeeded[1]
        result = preflight_epoch_pair(
            baseline,
            current,
            analysis_readiness=self._analysis_readiness,
        )
        pair = CivilEpochPairReadinessView(
            baseline_job_id=baseline.job_id,
            current_job_id=current.job_id,
            compatible=result.compatible,
            reason=result.reason,
            detail=(
                "두 최신 처리 시점의 evidence·profile·lineage·CRS·수직기준이 일치합니다."
                if result.compatible
                else result.detail or "두 최신 처리 시점의 비교 가능성을 확인하지 못했습니다."
            ),
        )
        if not result.compatible:
            return CivilReadinessView(
                site_id=site_id,
                status=CivilReadinessStatus.PAIR_BLOCKED,
                succeeded_epoch_count=len(succeeded),
                pair=pair,
                design_surface=design_surface,
                next_action=CivilReadinessNextAction(
                    label="비교 차단 사유 확인",
                    href=f"/missions/{quote(current.mission_id, safe='')}",
                    reason=(
                        "선택한 두 시점이 quantitative preflight를 통과하기 전에는 "
                        "수치를 만들지 않습니다."
                    ),
                ),
                limitations=_LIMITATIONS,
            )

        if design_surface.status is CivilDesignSurfaceStatus.NOT_REGISTERED:
            next_action = CivilReadinessNextAction(
                label="설계 기준면 등록",
                href=f"/sites/{quote(site_id, safe='')}/design",
                reason="설계 대비 절토·성토 잔량에는 검증 가능한 설계 기준면이 필요합니다.",
            )
        elif design_surface.status is CivilDesignSurfaceStatus.VERIFICATION_REQUIRED:
            next_action = CivilReadinessNextAction(
                label="설계 기준면 검증 상태 확인",
                href=f"/sites/{quote(site_id, safe='')}/design",
                reason="봉인만 된 설계면은 정량 비교 입력이 될 수 없습니다.",
            )
        elif design_surface.status is CivilDesignSurfaceStatus.SYSTEM_UNAVAILABLE:
            next_action = CivilReadinessNextAction(
                label="설계 기준면 상태 다시 확인",
                href=f"/sites/{quote(site_id, safe='')}/design",
                reason="설계 기준면 원장을 확인할 수 없어 설계 대비 결과를 준비하지 않습니다.",
            )
        else:
            next_action = CivilReadinessNextAction(
                label="두 시점 비교 열기",
                href=f"/missions/{quote(current.mission_id, safe='')}",
                reason="실제 비교 요청은 선택한 입력을 Core가 다시 검증한 뒤에만 생성됩니다.",
            )

        return CivilReadinessView(
            site_id=site_id,
            status=CivilReadinessStatus.PAIR_COMPATIBLE,
            succeeded_epoch_count=len(succeeded),
            pair=pair,
            design_surface=design_surface,
            next_action=next_action,
            limitations=_LIMITATIONS,
        )

    @staticmethod
    def _design_surface_summary(
        surfaces: Sequence[DesignSurface],
    ) -> CivilDesignSurfaceReadinessView:
        total = len(surfaces)
        verified = sum(
            1
            for surface in surfaces
            if getattr(surface, "status", None) is DesignSurfaceStatus.VERIFIED
        )
        if total == 0:
            return CivilDesignSurfaceReadinessView(
                status=CivilDesignSurfaceStatus.NOT_REGISTERED,
                total_surface_count=0,
                verified_surface_count=0,
                detail=(
                    "등록된 설계 기준면이 없습니다. 시계열 비교는 가능해도 설계 대비 "
                    "잔량은 계산하지 않습니다."
                ),
            )
        if verified == 0:
            return CivilDesignSurfaceReadinessView(
                status=CivilDesignSurfaceStatus.VERIFICATION_REQUIRED,
                total_surface_count=total,
                verified_surface_count=0,
                detail="등록된 설계 기준면은 있지만 VERIFIED 관측 근거가 없습니다.",
            )
        return CivilDesignSurfaceReadinessView(
            status=CivilDesignSurfaceStatus.VERIFIED_AVAILABLE,
            total_surface_count=total,
            verified_surface_count=verified,
            detail=(
                "검증된 설계 기준면이 있습니다. 실제 요청에서는 사용할 revision과 "
                "입력 호환성을 다시 확인합니다."
            ),
        )

    @staticmethod
    def _first_epoch_action(site_id: str) -> CivilReadinessNextAction:
        return CivilReadinessNextAction(
            label="첫 조사 시점 준비",
            href=f"/sites/{quote(site_id, safe='')}?section=work",
            reason=(
                "시계열 비교를 시작하려면 원본을 봉인하고 고정 profile로 첫 처리를 "
                "완료해야 합니다."
            ),
        )

    @staticmethod
    def _unavailable(site_id: str) -> CivilReadinessView:
        return CivilReadinessView(
            site_id=site_id,
            status=CivilReadinessStatus.SYSTEM_UNAVAILABLE,
            succeeded_epoch_count=0,
            pair=CivilEpochPairReadinessView(
                baseline_job_id=None,
                current_job_id=None,
                compatible=False,
                reason=CivilReadinessReason.SYSTEM_UNAVAILABLE,
                detail="처리 시점 원장을 확인하지 못했습니다. 비교 가능으로 추정하지 않습니다.",
            ),
            design_surface=CivilDesignSurfaceReadinessView(
                status=CivilDesignSurfaceStatus.SYSTEM_UNAVAILABLE,
                total_surface_count=0,
                verified_surface_count=0,
                detail="설계 기준면 원장을 확인하지 못했습니다.",
            ),
            next_action=CivilReadinessNextAction(
                label="준비 상태 다시 확인",
                href=f"/sites/{quote(site_id, safe='')}?section=data",
                reason="원장 조회가 복구될 때까지 정량 비교를 시작하지 않습니다.",
            ),
            limitations=_LIMITATIONS,
        )


def build_civil_readiness_router(projector: CivilReadinessProjector) -> APIRouter:
    """Mount the organization-scoped, read-only Site civil-readiness surface."""

    router = APIRouter(prefix="/v1/sites", tags=["civil-readiness"])

    @router.get("/{site_id}/civil-readiness", response_model=CivilReadinessView)
    def get_civil_readiness(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> CivilReadinessView:
        try:
            return projector.project(site_id, organization_id=principal.organization_id)
        except LookupError as exc:
            # Same response for unknown and cross-organization Site IDs (INV-060).
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL) from exc

    return router


def mount_civil_readiness(app: FastAPI, projector: CivilReadinessProjector) -> None:
    """Compatibility mount wrapper used by ``create_app``."""

    app.include_router(build_civil_readiness_router(projector))


__all__ = [
    "CivilDesignSurfaceReadinessView",
    "CivilDesignSurfaceStatus",
    "CivilEpochPairReadinessView",
    "CivilReadinessNextAction",
    "CivilReadinessProjector",
    "CivilReadinessReason",
    "CivilReadinessStatus",
    "CivilReadinessView",
    "build_civil_readiness_router",
    "mount_civil_readiness",
]

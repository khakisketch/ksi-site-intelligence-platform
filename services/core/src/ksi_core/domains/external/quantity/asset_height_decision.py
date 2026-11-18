"""한 DSM 자료의 높이 읽기 판정을 자료 참조로 요청한다 — 단면 요청이 판정 식별자를 얻는 길.

기존 판정 요청 경로는 작업·제출 참조로 들어가고 범위가 제한된 OIDC 운영자에게는 닫혀 있다. 이 경로는
카탈로그가 현재 권한 범위(조직·허용 현장·허용 작업구역)에서 보여 주는 자료에만 닿는다. 판정 자체는
같은 ``ExternalUseEvaluator.request_single(HEIGHT)`` 가 한다. 새 권한·판정 규칙·저장소는 없다.

- 요청자는 사람(OPERATOR)이어야 하고 SITES_WRITE 가 필요하다(기존 경로와 같다).
- DSM 이 아닌 자료는 409 로 거부한다. 정사영상의 높이는 판정할 수 없다.
- 판정이 BLOCKED 여도 201 로 사유를 돌려준다. 사유 코드는 판정 기록의 값 그대로다.
- 판정은 제출 단위다. 같은 제출의 다른 DSM 때문에 ELIGIBLE 이 되었어도 이 자료 자신의 수직 기준(관측
  또는 현재 선언)이 없으면 409 ASSET_VERTICAL_REFERENCE_UNKNOWN 으로 돌려준다.
- 같은 (주체·자료·키)는 같은 판정을 돌려준다(응답 유실 복구).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from ksi_event_contracts.external_artifact_validation import DecisionVerdict
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.domains.external.quantity.external_use_decisions import (
    ExternalUseDecisionConflictError,
)
from ksi_core.domains.external.quantity.external_use_evaluator import (
    ExternalUseDecisionResponse,
    ExternalUseEvaluator,
    _sealed_subject_from_revision,
)
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}/height-decision"


def build_asset_height_decision_router(
    evaluator: ExternalUseEvaluator, catalog: SpatialAssetCatalog, *, work_orders: Any
) -> APIRouter:
    router = APIRouter(tags=["external-use-decisions"])

    def idempotency_header(
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=255, pattern=r".*\S.*"
        ),
    ) -> str:
        return idempotency_key.strip()

    @router.post(_BASE, response_model=ExternalUseDecisionResponse, status_code=201)
    def request_height(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(403, "HUMAN_AUTHORITY_REQUIRED")
        found = catalog.revision_for(site_id, work_area_id, asset_ref, principal)
        if found is None:
            raise HTTPException(404, "자료를 찾을 수 없다")
        item, record = found
        if item.kind is not ProcessingArtifactKind.DSM:
            raise HTTPException(409, "NOT_A_DSM")
        subject = _sealed_subject_from_revision(record)
        if subject is None:
            raise HTTPException(409, "EXTERNAL_RECONSTRUCTION_NOT_SEALED")
        try:
            with work_orders.guard_new_external_intent(
                record.work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: (
                    evaluator.existing_single_retry(
                        subject, use="HEIGHT", principal=principal, idempotency_key=idempotency_key
                    )
                    is not None
                ),
            ):
                decision = evaluator.request_single(
                    subject,
                    use="HEIGHT",
                    idempotency_key=idempotency_key,
                    principal=principal,
                    now=datetime.now(UTC),
                )
        except LookupError as exc:
            raise HTTPException(404, "자료를 찾을 수 없다") from exc
        except ExternalUseDecisionConflictError as exc:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(409, str(exc)) from exc
            raise
        # 판정은 제출 단위라서 같은 제출의 다른 DSM이 수직 기준을 가지면 이 자료에 기준이 없어도
        # ELIGIBLE이 된다. 이 경로는 한 자료에 대한 답이므로 이 자료 자신의 기준(파일에서 관측했거나
        # 현재 선언이 있음)이 없으면 그 판정을 이 자료의 근거로 돌려주지 않는다.
        raster = catalog.with_inspection(item, principal).inspection.raster
        observed = raster is not None and raster.observed_vertical_reference is not None
        if (
            decision.verdict is DecisionVerdict.ELIGIBLE
            and not observed
            and not evaluator.has_declared_vertical(subject, item.artifact_id)
        ):
            raise HTTPException(409, "ASSET_VERTICAL_REFERENCE_UNKNOWN")
        return ExternalUseDecisionResponse(decision=decision.model_dump(by_alias=True, mode="json"))

    return router


__all__ = ["build_asset_height_decision_router"]

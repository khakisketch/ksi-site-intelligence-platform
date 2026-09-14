"""Authenticated CAP-5 observation ingress and scoped diagnostic projection.

The read endpoint is deliberately diagnostic-only: it evaluates Mission policy
as DENY and therefore can never return an operational authorization token.
Execution consumers use the internal projector with their independently
evaluated Mission policy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityIntegrationPath,
)
from ksi_domain.enums import MissionExecutionStatus
from ksi_mission_contracts.models import parse_mission_contract
from pydantic import Field, field_validator

from ksi_core.capability.runtime_projection import (
    MissionPolicyDecision,
    ObservationIngestDisposition,
    RuntimeCapabilityProjector,
    RuntimeCapabilityValidationError,
    RuntimeObservationConflict,
    RuntimeObservationUnavailable,
    RuntimeRouteInvocationRequest,
    RuntimeRouteObservationV1,
)
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel
from ksi_core.foundation.identifiers import PATH_SAFE_IDENTIFIER_PATTERN, is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.missions.mission_execution import MissionExecutionStore
    from ksi_core.domains.missions.mission_records import MissionStore


_REQUIRE_RUNTIME_OBSERVE = require_permission(Permission.CAPABILITY_RUNTIME_OBSERVE)
_REQUIRE_RUNTIME_PREFLIGHT = require_permission(Permission.CAPABILITY_RUNTIME_PREFLIGHT)
_REQUIRE_SITES_READ = require_permission(Permission.SITES_READ)


_OPERATION_CAPABILITIES: dict[str, frozenset[CanonicalTransportCapability]] = {
    "WAYLINE_DISPATCH": frozenset({CanonicalTransportCapability.WAYLINE_DELIVERY}),
    "EDGE_DISPATCH": frozenset({CanonicalTransportCapability.EDGE_DOWNLINK}),
    "EDGE_UPLINK": frozenset({CanonicalTransportCapability.EDGE_UPLINK}),
    "MEDIA_SYNC": frozenset(
        {
            CanonicalTransportCapability.MEDIA_PULL,
            CanonicalTransportCapability.MEDIA_UPLOAD,
        }
    ),
}

_COMMAND_OPERATIONS = frozenset({"WAYLINE_DISPATCH", "EDGE_DISPATCH"})
_TERMINAL_EXECUTION_STATES = frozenset(
    {
        MissionExecutionStatus.CANCELLED,
        MissionExecutionStatus.COMPLETED,
        MissionExecutionStatus.ENDED_INCOMPLETE,
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeRoutePreflightRequestV1(CamelModel):
    """Exact Gateway-selected route and Mission scope for one new invocation."""

    organization_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    site_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    gateway_device_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    edge_device_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    canonical_capability: CanonicalTransportCapability
    integration_path: CapabilityIntegrationPath
    subject_port_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    transport: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    hardware_model: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    firmware_version: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    mission_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    operation: Literal[
        "WAYLINE_DISPATCH", "EDGE_DISPATCH", "EDGE_UPLINK", "MEDIA_SYNC"
    ]
    idempotency_key: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]
    activation_authorization_id: Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN)]

    @field_validator(
        "organization_id", "site_id", "gateway_device_id", "edge_device_id",
        "subject_port_id", "transport", "hardware_model", "firmware_version",
        "mission_id", "idempotency_key", "activation_authorization_id",
    )
    @classmethod
    def _require_path_safe_identifier(cls, value: str) -> str:
        if not is_path_safe_identifier(value):
            raise ValueError("must be a path-safe identifier")
        return value


class RuntimeRoutePreflightResponseV1(CamelModel):
    durable_authority_valid: bool
    current_runtime_ready: bool
    current_mission_policy_allows: bool
    operationally_usable: bool
    new_route_invocation_allowed: bool
    reason: str
    existing_signed_mission_contract_effect: str


def _mission_policy_for_new_route(
    request: RuntimeRoutePreflightRequestV1,
    *,
    mission_store: MissionStore | None,
    mission_execution_store: MissionExecutionStore | None,
    now: datetime,
) -> MissionPolicyDecision:
    """Conservative Core-owned Mission conjunct; absence or ambiguity is DENY.

    This does not reissue, mutate, or cancel a signed Mission Contract. It only
    verifies that the requested *new* route invocation belongs to a current,
    trusted Mission record assigned to the exact Edge device.
    """

    if mission_store is None or mission_execution_store is None:
        return MissionPolicyDecision.DENY
    if request.canonical_capability not in _OPERATION_CAPABILITIES[request.operation]:
        return MissionPolicyDecision.DENY
    record = mission_store.get_scoped(
        request.mission_id, organization_id=request.organization_id
    )
    execution_status = mission_execution_store.effective_status(request.mission_id)
    if (
        record is None
        or record.site_id != request.site_id
        or record.assigned_device_id != request.edge_device_id
    ):
        return MissionPolicyDecision.DENY
    try:
        contract = parse_mission_contract(record.contract)
        not_before = datetime.fromisoformat(
            contract.validity.not_before.replace("Z", "+00:00")
        )
        not_after = datetime.fromisoformat(
            contract.validity.not_after.replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError):
        return MissionPolicyDecision.DENY
    if (
        contract.mission_id != request.mission_id
        or contract.site_id != request.site_id
        or not_before.tzinfo is None
        or not_after.tzinfo is None
        or not (not_before <= now <= not_after)
        or (
            request.operation in _COMMAND_OPERATIONS
            and execution_status in _TERMINAL_EXECUTION_STATES
        )
    ):
        return MissionPolicyDecision.DENY
    return MissionPolicyDecision.ALLOW


class RuntimeObservationIngestResponse(CamelModel):
    disposition: ObservationIngestDisposition
    observation: RuntimeRouteObservationV1


class ScopedRuntimeCapabilityView(CamelModel):
    authorization_purpose: Literal["DIAGNOSTIC_ONLY"] = "DIAGNOSTIC_ONLY"
    activation_authorization_id: str
    organization_id: str
    site_id: str
    durable_authority_valid: bool
    current_runtime_ready: bool
    current_mission_policy_allows: bool
    operationally_usable: bool
    reason: str
    classification: str
    activation_lifecycle_status: str | None
    observation_id: str | None
    new_route_invocation_allowed: bool
    existing_signed_mission_contract_effect: str
    warning: Annotated[str, Field(min_length=1)] = (
        "Diagnostic projection only; Mission policy is independently required "
        "and this response does not authorize route or device behavior."
    )


def build_runtime_capability_router(
    projector: RuntimeCapabilityProjector,
    *,
    mission_store: MissionStore | None = None,
    mission_execution_store: MissionExecutionStore | None = None,
) -> APIRouter:
    router = APIRouter(tags=["capability-runtime"])

    @router.post(
        "/v1/capability-runtime/observations",
        response_model=RuntimeObservationIngestResponse,
        status_code=201,
    )
    def ingest_observation(
        request: RuntimeRouteObservationV1,
        principal: Principal = Depends(_REQUIRE_RUNTIME_OBSERVE),  # noqa: B008
    ) -> RuntimeObservationIngestResponse:
        try:
            result = projector.ingest_observation(
                request, principal=principal, received_at=_utc_now()
            )
        except RuntimeObservationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeCapabilityValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeObservationUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=JOURNAL_SEALED_DETAIL,
                headers={"Retry-After": "30"},
            ) from exc
        return RuntimeObservationIngestResponse(
            disposition=result.disposition,
            observation=result.observation,
        )

    @router.post(
        "/v1/capability-runtime/preflight",
        response_model=RuntimeRoutePreflightResponseV1,
    )
    def preflight_new_route(
        request: RuntimeRoutePreflightRequestV1,
        principal: Principal = Depends(_REQUIRE_RUNTIME_PREFLIGHT),  # noqa: B008
    ) -> RuntimeRoutePreflightResponseV1:
        now = _utc_now()
        # Authentication supplies tenant and Gateway identity. Payload values
        # cannot select either scope, and legacy identity never authorizes HIL.
        principal_matches = (
            principal.organization_id != "legacy"
            and principal.organization_id == request.organization_id
            and principal.device_id == request.gateway_device_id
        )
        mission_policy = (
            _mission_policy_for_new_route(
                request,
                mission_store=mission_store,
                mission_execution_store=mission_execution_store,
                now=now,
            )
            if principal_matches
            else MissionPolicyDecision.DENY
        )
        try:
            invocation = RuntimeRouteInvocationRequest(
                activation_authorization_id=request.activation_authorization_id,
                organization_id=(
                    principal.organization_id if principal_matches else "legacy"
                ),
                site_id=request.site_id,
                gateway_device_id=request.gateway_device_id,
                edge_device_id=request.edge_device_id,
                canonical_capability_id=request.canonical_capability,
                integration_path=request.integration_path,
                subject_port_id=request.subject_port_id,
                selected_transport=request.transport,
                hardware_model=request.hardware_model,
                firmware_version=request.firmware_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        projection = projector.project_new_route_invocation(
            invocation,
            mission_policy=mission_policy,
            now=now,
        )
        return RuntimeRoutePreflightResponseV1(
            durable_authority_valid=projection.durable_authority_valid,
            current_runtime_ready=projection.current_runtime_ready,
            current_mission_policy_allows=projection.current_mission_policy_allows,
            operationally_usable=projection.operationally_usable,
            new_route_invocation_allowed=projection.new_route_invocation_allowed,
            reason=projection.reason.value,
            existing_signed_mission_contract_effect=(
                projection.existing_signed_mission_contract_effect.value
            ),
        )

    @router.get(
        "/v1/sites/{site_id}/capability-runtime/activations/{activation_id}",
        response_model=ScopedRuntimeCapabilityView,
    )
    def get_scoped_runtime_projection(
        site_id: str,
        activation_id: str,
        principal: Principal = Depends(_REQUIRE_SITES_READ),  # noqa: B008
    ) -> ScopedRuntimeCapabilityView:
        scope = projector.activation_scope_for(activation_id)
        if (
            scope is None
            or scope[0] != principal.organization_id
            or scope[1] != site_id
            or principal.organization_id == "legacy"
        ):
            # Do not reveal whether another tenant's activation exists.
            raise HTTPException(status_code=404, detail="runtime activation을 찾을 수 없다")
        projection = projector.project(
            activation_id,
            trusted_organization_id=principal.organization_id,
            # An HTTP catalog/diagnostic query is not a Mission policy decision.
            mission_policy=MissionPolicyDecision.DENY,
            now=_utc_now(),
        )
        return ScopedRuntimeCapabilityView(
            activation_authorization_id=projection.activation_authorization_id,
            organization_id=scope[0],
            site_id=scope[1],
            durable_authority_valid=projection.durable_authority_valid,
            current_runtime_ready=projection.current_runtime_ready,
            current_mission_policy_allows=projection.current_mission_policy_allows,
            operationally_usable=projection.operationally_usable,
            reason=projection.reason.value,
            classification=projection.classification.value,
            activation_lifecycle_status=(
                projection.activation_lifecycle_status.value
                if projection.activation_lifecycle_status is not None
                else None
            ),
            observation_id=projection.observation_id,
            new_route_invocation_allowed=projection.new_route_invocation_allowed,
            existing_signed_mission_contract_effect=(
                projection.existing_signed_mission_contract_effect.value
            ),
        )

    return router


def mount_runtime_capability(
    app: FastAPI,
    projector: RuntimeCapabilityProjector,
    *,
    mission_store: MissionStore | None = None,
    mission_execution_store: MissionExecutionStore | None = None,
) -> None:
    app.state.runtime_capability_projector = projector
    app.include_router(
        build_runtime_capability_router(
            projector,
            mission_store=mission_store,
            mission_execution_store=mission_execution_store,
        )
    )


__all__ = [
    "RuntimeObservationIngestResponse",
    "RuntimeRoutePreflightRequestV1",
    "RuntimeRoutePreflightResponseV1",
    "ScopedRuntimeCapabilityView",
    "build_runtime_capability_router",
    "mount_runtime_capability",
]

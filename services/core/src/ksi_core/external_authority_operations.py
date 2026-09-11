"""Administrator trigger for fixed, independently signed operational inputs.

This is an operator-control endpoint, not a customer authority-submission API.
The body cannot select files, supply approval facts, or change the trust root.
"""

from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException

from ksi_core.api_base import CamelModel
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission


class ExternalAuthorityOperations(Protocol):
    @property
    def organization_id(self) -> str: ...

    def reload_and_reconcile(self, *, now: datetime) -> dict[str, object]: ...

    def status(self) -> dict[str, object]: ...


class ExternalAuthorityReloadIntent(CamelModel):
    """Empty intent; authority facts arrive only through the protected provider."""


def mount_external_authority_operations(
    app: FastAPI, controller: ExternalAuthorityOperations
) -> None:
    @app.get("/ready/external-authority", include_in_schema=False)
    def readiness() -> dict[str, str]:
        try:
            configured = controller.status().get("status") == "PROVIDER_CONFIGURED"
        except Exception:
            configured = False
        if not configured:
            raise HTTPException(status_code=503, detail="EXTERNAL_AUTHORITY_UNAVAILABLE")
        return {"status": "PROVIDER_CONFIGURED"}

    @app.post("/v1/operations/external-authority/reload", include_in_schema=False)
    def reload_authority(
        intent: ExternalAuthorityReloadIntent,
        principal: Annotated[
            Principal, Depends(require_permission(Permission.EXTERNAL_AUTHORITY_MANAGE))
        ],
    ) -> dict[str, object]:
        del intent
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        if principal.organization_id != controller.organization_id:
            raise HTTPException(status_code=404, detail="operation was not found")
        try:
            result = controller.reload_and_reconcile(now=datetime.now(UTC))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="EXTERNAL_AUTHORITY_UNAVAILABLE") from exc
        # Do not return provider paths, input records, signatures or exception content.
        return {
            key: result[key]
            for key in ("status", "sequence", "snapshotDigest")
            if key in result
        }

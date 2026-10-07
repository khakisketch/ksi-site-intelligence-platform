"""Ephemeral per-request authentication refresh; never a durable bearer or frozen Principal."""

from datetime import datetime

from fastapi import HTTPException, Request

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Principal, resolve_bearer_principal


class SpatialDataCredentialCurrentness:
    __slots__ = ("_request", "_token", "_expected_principal_id", "_expected_organization_id")

    def __init__(
        self,
        request: Request,
        token: str,
        *,
        expected_principal_id: str,
        expected_organization_id: str,
    ) -> None:
        if not isinstance(request, Request) or type(token) is not str or not token:
            raise ValueError("explicit request-local bearer required")
        if not (
            is_path_safe_identifier(expected_principal_id)
            and is_path_safe_identifier(expected_organization_id)
        ):
            raise ValueError("explicit expected ownership identity required")
        self._request = request
        self._token = token
        self._expected_principal_id = expected_principal_id
        self._expected_organization_id = expected_organization_id

    def __repr__(self) -> str:
        return "SpatialDataCredentialCurrentness(<request-local credential>)"

    def expected_identity(self) -> tuple[str, str]:
        """Routing-only expected owner identity (ids, never token/Principal).

        Lets the owner snapshot capture bind the locally current requester
        through the trusted local currentness port without invoking the
        potentially remote credential refresh. The genuine request-credential
        refresh in the bounded metadata-response stages stays the sole
        request authorization.
        """
        return (self._expected_principal_id, self._expected_organization_id)

    def resolve(self, *, now: datetime) -> Principal:
        """May consult OIDC; run outside Core's local check-and-commit coordinator."""
        try:
            principal = resolve_bearer_principal(self._request, self._token, now=now)
        except RuntimeError as exc:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if (principal.principal_id, principal.organization_id) != (
            self._expected_principal_id,
            self._expected_organization_id,
        ):
            raise HTTPException(
                status_code=401, detail="인증이 필요하다", headers={"WWW-Authenticate": "Bearer"}
            )
        return principal

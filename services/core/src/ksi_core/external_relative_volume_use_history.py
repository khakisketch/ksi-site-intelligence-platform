"""Independent permission at a historical use time, separate from report provenance."""

from datetime import datetime
from typing import Protocol

from ksi_core.external_relative_volumes import ExternalRelativeVolumeExecutionAuthority


class ExternalRelativeVolumeHistoricalUseAuthorityPort(Protocol):
    """Reconstruct policy/evidence/mapping/actor lifecycle at the exact use time.

    An immutable report or an authority's original validity interval alone is
    insufficient: early revocation must be reflected independently. Implementors
    return the exact permitted execution snapshot or None, without a Principal
    synthesized from current roles. This port may perform independent I/O and
    must not run inside the final coordinator-held current guard.
    """

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None: ...


class ClosedExternalRelativeVolumeUseHistory:
    """No production use-history authority is inferred from retained reports."""

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del historical_authority_digest, decision_id, decision_digest, evaluated_at
        return None

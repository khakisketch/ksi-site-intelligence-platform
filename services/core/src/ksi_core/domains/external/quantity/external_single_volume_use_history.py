"""Independent single-volume permission at a historical use time.

The single-epoch sibling of ``external_relative_volume_use_history``: report
provenance alone never grants use, and early revocation is reflected here.
"""

from datetime import datetime
from typing import Protocol

from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
)


class ExternalSingleVolumeHistoricalUseAuthorityPort(Protocol):
    """Reconstruct single-volume use permission at the exact use time.

    Implementors return the exact permitted execution snapshot or None, without
    a Principal synthesized from current roles. This port may perform
    independent I/O and must not run inside the final coordinator-held guard.
    """

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None: ...


class ClosedExternalSingleVolumeUseHistory:
    """No production use-history authority is inferred from retained reports."""

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        del historical_authority_digest, decision_id, decision_digest, evaluated_at
        return None


__all__ = [
    "ClosedExternalSingleVolumeUseHistory",
    "ExternalSingleVolumeHistoricalUseAuthorityPort",
]

"""Safe typed data-lane failures, not storage paths or exception tracebacks."""

from ksi_event_contracts.spatial_data import SpatialDataReasonV1, SpatialDataRemediationV1
from ksi_event_contracts.spatial_data_ai import SpatialDataAiReasonV1
from pydantic import TypeAdapter

_REASON: TypeAdapter[SpatialDataReasonV1] = TypeAdapter(SpatialDataReasonV1)
_AI_REASON: TypeAdapter[SpatialDataAiReasonV1] = TypeAdapter(SpatialDataAiReasonV1)


class SpatialDataDomainError(RuntimeError):
    def __init__(
        self, reason: SpatialDataReasonV1 | str, status_code: int, retryable: bool = False
    ) -> None:
        self.reason = _REASON.validate_python(reason)
        if type(status_code) is not int or not 400 <= status_code <= 599:
            raise ValueError("invalid failure status")
        if type(retryable) is not bool:
            raise ValueError("retryable must be boolean")
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(self.reason)


class SpatialDataAiDomainError(RuntimeError):
    """AI-identity refusal only; never serialized through the old V1 error model.

    Carries the closed AI reason union (V1 reasons plus the AI cursor-stale code)
    beside the AI DTOs. Old ``SpatialDataReasonV1`` and ``SpatialDataErrorV1``
    shapes are unchanged; shared old domain refusals keep their typed values and
    are mapped to the AI envelope by the AI route layer, not here.
    """

    def __init__(
        self, reason: SpatialDataAiReasonV1 | str, status_code: int, retryable: bool = False
    ) -> None:
        self.reason: SpatialDataAiReasonV1 = _AI_REASON.validate_python(reason)
        if type(status_code) is not int or not 400 <= status_code <= 599:
            raise ValueError("invalid failure status")
        if type(retryable) is not bool:
            raise ValueError("retryable must be boolean")
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(self.reason)


_AI_REMEDIATION: dict[str, tuple[SpatialDataRemediationV1, ...]] = {
    "AI_EGRESS_DENIED": ("CHECK_AI_CONSENT",),
    "ACCESS_REVOKED": ("REQUEST_NEW_GRANT",),
    "ACCESS_EXPIRED": ("REQUEST_NEW_GRANT",),
    "GRANT_REQUIRED": ("REQUEST_NEW_GRANT",),
    "PROCESSING_LOCATION_DENIED": ("CHECK_PROCESSING_LOCATION",),
    "NOT_READY": ("WAIT_FOR_COMPLETION",),
    "SPATIAL_DATA_CURSOR_STALE": ("RETRY_REQUEST",),
    "IDEMPOTENCY_CONFLICT": ("REQUEST_NEW_JOB",),
    "RETENTION_EXPIRED": ("REQUEST_NEW_JOB",),
    "INVALID_REQUEST_BOUNDS": ("REDUCE_REQUEST",),
    "RESOURCE_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
    "RETAINED_HISTORY_LIMIT_EXCEEDED": ("CONTACT_OPERATOR",),
    "OUTPUT_BYTE_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
    "OUTPUT_PIXEL_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
}


def ai_remediation_for(reason: str) -> tuple[SpatialDataRemediationV1, ...]:
    """Closed safe remediation for one AI reason; never caller text or raw detail."""
    remediation = _AI_REMEDIATION.get(reason)
    if remediation is not None:
        return remediation
    if reason in ("CONCURRENCY_LIMIT_EXCEEDED", "WORKSPACE_LIMIT_EXCEEDED"):
        return ("RETRY_REQUEST",)
    return ("CONTACT_OPERATOR",)


def ai_retryable(status_code: int, explicit: bool) -> bool:
    if explicit:
        return True
    return status_code == 429 or status_code >= 500

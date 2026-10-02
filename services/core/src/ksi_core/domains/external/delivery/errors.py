"""Safe typed data-lane failures, not storage paths or exception tracebacks."""

from ksi_event_contracts.spatial_data import SpatialDataReasonV1
from pydantic import TypeAdapter

_REASON: TypeAdapter[SpatialDataReasonV1] = TypeAdapter(SpatialDataReasonV1)


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

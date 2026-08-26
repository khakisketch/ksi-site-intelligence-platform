"""Public fail-closed Gateway errors."""


class GatewayError(RuntimeError):
    pass


class CapabilityUnavailableError(GatewayError):
    pass


class IdempotencyConflictError(GatewayError):
    pass


class GatewayJournalRecoveryError(GatewayError):
    pass


__all__ = [
    "CapabilityUnavailableError",
    "GatewayError",
    "GatewayJournalRecoveryError",
    "IdempotencyConflictError",
]

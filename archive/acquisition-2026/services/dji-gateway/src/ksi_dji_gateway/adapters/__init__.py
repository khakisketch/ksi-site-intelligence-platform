"""Fail-closed candidate adapters for all five integration paths."""

from ksi_dji_gateway.adapters.catalog import (
    CANDIDATE_PATH_CAPABILITIES,
    SUPPORTED_TRANSPORTS,
    build_candidate_ports,
)
from ksi_dji_gateway.adapters.transport import (
    AdapterRuntimeConfig,
    BridgeClient,
    BridgeOperation,
    HttpsJsonBridgeClient,
    UnixJsonBridgeClient,
)

__all__ = [
    "AdapterRuntimeConfig",
    "BridgeClient",
    "BridgeOperation",
    "CANDIDATE_PATH_CAPABILITIES",
    "HttpsJsonBridgeClient",
    "SUPPORTED_TRANSPORTS",
    "UnixJsonBridgeClient",
    "build_candidate_ports",
]

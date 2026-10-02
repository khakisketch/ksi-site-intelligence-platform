"""Distinct data-worker activation verification only. No key generation or provisioning."""

from datetime import datetime

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts._spatial_data import require_utc
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)
from pydantic import ValidationError


class SpatialDataActivationVerificationError(ValueError):
    """Safe failure, without reflecting signature/key/payload values."""


def verify_spatial_data_activation(
    *,
    payload: SpatialDataActivationV1,
    signature: bytes,
    trusted_public_key: bytes,
    policy: SpatialDataPolicyV1,
    runtime: SpatialDataRuntimeV1,
    now: datetime,
) -> SpatialDataActivationV1:
    try:
        require_utc(now)
        if type(signature) is not bytes or len(signature) != 64:
            raise ValueError("invalid signature representation")
        if type(trusted_public_key) is not bytes or len(trusted_public_key) != 32:
            raise ValueError("invalid trusted public key representation")
        payload = SpatialDataActivationV1.model_validate(payload.model_dump())
        policy = SpatialDataPolicyV1.model_validate(policy.model_dump())
        runtime = SpatialDataRuntimeV1.model_validate(runtime.model_dump())
        if any(
            getattr(value, value._digest_field) != value.canonical_digest()
            for value in (payload, policy, runtime)
        ):
            raise ValueError("activation verification requires sealed snapshots")
        if (
            payload.policy_digest != policy.policy_digest
            or payload.runtime_digest != runtime.runtime_digest
            or payload.preparation_profile != runtime.preparation_profile
            or not payload.is_current_at(now)
        ):
            raise ValueError("activation policy/runtime/validity mismatch")
        # signing_bytes has the distinct ksi-spatial-data-activation.v1 domain.
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            signature, payload.signing_bytes()
        )
        return payload.model_copy(deep=True)
    except (InvalidSignature, UnsupportedAlgorithm, ValidationError, ValueError, TypeError) as exc:
        raise SpatialDataActivationVerificationError(
            "spatial data activation not verified"
        ) from exc

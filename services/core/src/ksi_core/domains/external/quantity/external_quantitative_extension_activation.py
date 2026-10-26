"""Strict verification of the purpose-separated quantitative extension activation.

This module is strictly additive: it does not modify the V2 activation loader
(:mod:`ksi_core.domains.external.quantity.analysis_activation_authority`), any
shared model, or any existing registry. An old ``AnalysisActivationV1`` record
— which carries no ``purpose`` — can never authorize the new purposes: it fails
this module's shape validation before any signature or binding check.

Trust-root reuse, stated explicitly:

- Protected-file loading (``O_NOFOLLOW`` descriptor pinning, single-link
  regular-file hardening, bounded reads with before/after ``fstat`` TOCTOU
  comparison), strict no-duplicate-field JSON parsing, UTC discipline, and the
  Ed25519 verification mechanics are reused by importing the proven private
  helpers from the V2 activation authority module (same Core package, same
  owner). Only the behavior is reused; no V2 state, registry entry, or key is.
- The verification-key registry parsed here is a NEW registry document with
  its own version (``quantitative-extension-activation-key-registry.v1``) and
  its own key role (``QUANTITATIVE_EXTENSION_ACTIVATION_VERIFY``), both
  distinct from the V2 ``analysis-activation-key-registry.v1`` /
  ``ANALYSIS_ACTIVATION_VERIFY`` pair. A V2 registry — and any key minted for
  the V2 authority — is rejected as an unknown registry here. Key rollover and
  revocation are expressed the same way as in V2 (``ACTIVE`` status plus the
  ``notBefore``/``notAfter`` window, re-read on every check), but against this
  module's own registry file.
- The explicit signing domain is
  ``ksi.quantitative-extension-activation.v1`` (see
  :mod:`ksi_event_contracts.external_quantitative_extension_activation`),
  distinct from ``ksi.analysis-activation.v1``. A signature minted for the old
  domain never verifies here, and vice versa.

Currentness discipline: every current-use check takes a caller-supplied,
UTC-aware ``now`` from the Core trusted clock (this module never calls
``datetime.now`` itself) and re-loads and re-verifies the activation file, the
registry file, and the public key on each check. A key revoked or rotated after
startup therefore fails the next check closed. Callers that mutate shared Core
state should hold the supplied
:class:`~ksi_core.foundation.currentness.ExternalAuthorityCurrentnessCoordinator`
across their check-and-append section; this module's own checks take the
coordinator's ``guarded_read`` only around their own re-verification.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts.external_quantitative_extension_activation import (
    DELTA_PUBLICATION_PURPOSE,
    MASKED_ANALYSIS_PURPOSE,
    QuantitativeExtensionActivationV1,
    QuantitativeExtensionPurpose,
)

from ksi_core.domains.external.quantity import analysis_activation_authority as _v2_authority
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_MAX_FILE_BYTES = 64 * 1024
_REGISTRY_VERSION = "quantitative-extension-activation-key-registry.v1"
_KEY_ROLE = "QUANTITATIVE_EXTENSION_ACTIVATION_VERIFY"
_ALLOWED_PURPOSES: frozenset[str] = frozenset({MASKED_ANALYSIS_PURPOSE, DELTA_PUBLICATION_PURPOSE})
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _require_digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{description} digest is invalid")
    return value


def _require_opaque_shape(value: object, description: str) -> str:
    """Opaque Core identifiers name protected records, never paths or URLs."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{description} identifier is invalid")
    lowered = value.lower()
    if (
        _OPAQUE_ID_RE.fullmatch(value) is None
        or "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(f"{description} identifier must be opaque, never a path or URL")
    return value


def _registry_key(
    registry_path: Path,
    registry: object,
    *,
    key_id: str,
    now: datetime,
    issued_at: datetime,
    valid_until: datetime,
    allow_out_of_window: bool,
) -> Ed25519PublicKey:
    """Resolve the designated Ed25519 key from this module's own registry.

    Mirrors the V2 registry discipline (exact closed shapes, single-match key
    identity, issuance-within-key-validity, current validity unless historical
    replay is explicitly requested) but accepts only
    ``quantitative-extension-activation-key-registry.v1`` documents and the
    ``QUANTITATIVE_EXTENSION_ACTIVATION_VERIFY`` role. A V2 registry or V2
    key role fails here as an unknown registry/role.
    """
    body = _v2_authority._exact_mapping(
        registry,
        frozenset({"version", "keys"}),
        name="Quantitative extension activation verification-key registry",
    )
    if body["version"] != _REGISTRY_VERSION or not isinstance(body["keys"], list):
        raise ValueError("unknown quantitative extension activation verification-key registry")
    if len(body["keys"]) > 64:
        raise ValueError("quantitative extension activation key registry exceeds its key limit")
    matches: list[dict[str, object]] = []
    expected_fields = frozenset(
        {"keyId", "role", "algorithm", "status", "publicKeyFile", "notBefore", "notAfter"}
    )
    for item in body["keys"]:
        key = _v2_authority._exact_mapping(
            item, expected_fields, name="Quantitative extension activation key"
        )
        if key["keyId"] == key_id:
            matches.append(key)
    if len(matches) != 1:
        raise ValueError("quantitative extension activation key identity is missing or ambiguous")
    key = matches[0]
    if (
        key["role"] != _KEY_ROLE
        or key["algorithm"] != "Ed25519"
        or key["status"] != "ACTIVE"
        or not isinstance(key["publicKeyFile"], str)
        or Path(key["publicKeyFile"]).name != key["publicKeyFile"]
        or key["publicKeyFile"] in {".", ".."}
        or not key["publicKeyFile"].endswith(".pem")
    ):
        raise ValueError(
            "quantitative extension activation key does not have the required verification role"
        )
    not_before = _v2_authority._utc(key["notBefore"], name="key notBefore")
    not_after = _v2_authority._utc(key["notAfter"], name="key notAfter")
    if not_before >= not_after or not (not_before <= issued_at < valid_until <= not_after):
        raise ValueError(
            "quantitative extension activation was not issued within its signing key validity"
        )
    if not allow_out_of_window and not (not_before <= now < not_after):
        raise ValueError(
            "quantitative extension activation verification key is not currently valid"
        )
    public_path = registry_path.parent / key["publicKeyFile"]
    if public_path.parent != registry_path.parent:
        raise ValueError(
            "quantitative extension activation public key escapes its registry directory"
        )
    public_bytes = _v2_authority._protected_bytes(
        public_path,
        name="Quantitative extension activation public key",
        maximum=16 * 1024,
        private=False,
    )
    loaded = serialization.load_pem_public_key(public_bytes)
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("quantitative extension activation public key is not Ed25519")
    return loaded


def load_quantitative_extension_activation(
    activation_path: Path,
    verification_keys_path: Path,
    *,
    organization_id: str,
    purpose: str,
    policy_digest: str,
    runtime_digest: str,
    resource_envelope_digest: str,
    worker_principal: Principal,
    now: datetime,
    allow_out_of_window: bool = False,
) -> QuantitativeExtensionActivationV1:
    """Load and verify the activation against explicit, trusted Core bindings.

    The returned record remains historical evidence; callers decide whether its
    signed half-open validity window permits a new operation by re-verifying
    with :func:`is_quantitative_extension_current` (which re-reads both files)
    at use time. No ambient authority bundle, local config, caller hash, or
    generic processing identity is consulted: every pin is an explicit argument
    and the verified activation must equal it exactly.

    ``purpose`` must be exactly ``MASKED_ANALYSIS_V3`` or
    ``DELTA_PUBLICATION_V1``; the old V2 activation shape (no purpose) fails
    model validation here. ``now`` must come from the Core trusted clock.
    """
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError("quantitative extension activation verification requires a UTC-aware time")
    if purpose not in _ALLOWED_PURPOSES:
        raise ValueError("quantitative extension activation requires an explicit known purpose")
    if (
        not organization_id
        or worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
        or Permission.ANALYSIS_WORK not in principal_permissions(worker_principal)
        or worker_principal.organization_id != organization_id
    ):
        raise ValueError(
            "quantitative extension activation requires the dedicated organization worker"
        )
    _require_digest(policy_digest, "pinned policy")
    _require_digest(runtime_digest, "pinned runtime")
    _require_digest(resource_envelope_digest, "pinned resource envelope")

    raw_activation = _v2_authority._strict_json(
        activation_path, name="Quantitative extension activation record", private=True
    )
    activation = QuantitativeExtensionActivationV1.model_validate(raw_activation)
    if not allow_out_of_window and not activation.is_current_at(now):
        raise ValueError("quantitative extension activation is not current")
    if (
        activation.purpose != purpose
        or activation.organization_id != organization_id
        or activation.organization_id != worker_principal.organization_id
        or activation.policy_digest != policy_digest
        or activation.runtime_digest != runtime_digest
        or activation.resource_envelope_digest != resource_envelope_digest
        or activation.worker_principal_id != worker_principal.principal_id
    ):
        raise ValueError(
            "quantitative extension activation does not bind the exact trusted execution graph"
        )

    registry = _v2_authority._strict_json(
        verification_keys_path,
        name="Quantitative extension activation verification-key registry",
        private=True,
    )
    public_key = _registry_key(
        verification_keys_path,
        registry,
        key_id=activation.key_id,
        now=now,
        issued_at=activation.issued_at,
        valid_until=activation.valid_until,
        allow_out_of_window=allow_out_of_window,
    )
    try:
        public_key.verify(
            base64.b64decode(activation.signature, validate=True),
            activation.signing_bytes(),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("quantitative extension activation signature verification failed") from exc
    return activation


def is_quantitative_extension_current(
    activation_path: Path,
    verification_keys_path: Path,
    *,
    organization_id: str,
    purpose: str,
    policy_digest: str,
    runtime_digest: str,
    resource_envelope_digest: str,
    worker_principal: Principal,
    now: datetime,
    coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
) -> bool:
    """Re-verify the activation files against the pins at the trusted instant.

    Both protected files are re-read (so post-startup revocation or rotation
    fails the next check closed); any failure — missing/unsafe files, shape
    errors, binding mismatches, expired windows, revoked keys, bad signatures —
    returns ``False``. ``now`` must come from the Core trusted clock; this
    function never samples its own wall clock.
    """
    try:
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            return False
        if coordinator is not None:
            with coordinator.guarded_read():
                load_quantitative_extension_activation(
                    activation_path,
                    verification_keys_path,
                    organization_id=organization_id,
                    purpose=purpose,
                    policy_digest=policy_digest,
                    runtime_digest=runtime_digest,
                    resource_envelope_digest=resource_envelope_digest,
                    worker_principal=worker_principal,
                    now=now,
                )
        else:
            load_quantitative_extension_activation(
                activation_path,
                verification_keys_path,
                organization_id=organization_id,
                purpose=purpose,
                policy_digest=policy_digest,
                runtime_digest=runtime_digest,
                resource_envelope_digest=resource_envelope_digest,
                worker_principal=worker_principal,
                now=now,
            )
    except Exception:
        return False
    return True


@dataclass(frozen=True, slots=True)
class VerifiedQuantitativeExtensionPurpose:
    """Minimal verified purpose snapshot for masked-evidence resolution.

    Produced only from a fully verified
    :class:`QuantitativeExtensionActivationV1` (never from caller claims) so a
    masked-evidence port can expose *which* purpose the current activation
    authorizes without re-parsing the signed file. It carries no permission by
    itself: the parent still rechecks currentness, revocation, scope, and
    egress before any use.
    """

    purpose: QuantitativeExtensionPurpose
    activation_id: str
    organization_id: str
    worker_principal_id: str
    policy_digest: str
    runtime_digest: str
    resource_envelope_digest: str
    issued_at: datetime
    valid_until: datetime
    key_id: str

    def is_current_at(self, now: datetime) -> bool:
        """Check the snapshot's signed half-open window; not a re-verification."""
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("purpose snapshot currentness requires a UTC-aware time")
        return self.issued_at <= now < self.valid_until


def verified_purpose_snapshot(
    activation: QuantitativeExtensionActivationV1,
) -> VerifiedQuantitativeExtensionPurpose:
    """Project the purpose facts of an already-verified activation."""
    if not isinstance(activation, QuantitativeExtensionActivationV1):
        raise ValueError("purpose snapshot requires a verified quantitative extension activation")
    if activation.purpose not in _ALLOWED_PURPOSES:
        raise ValueError("purpose snapshot requires an explicit known purpose")
    return VerifiedQuantitativeExtensionPurpose(
        purpose=activation.purpose,
        activation_id=activation.activation_id,
        organization_id=activation.organization_id,
        worker_principal_id=activation.worker_principal_id,
        policy_digest=activation.policy_digest,
        runtime_digest=activation.runtime_digest,
        resource_envelope_digest=activation.resource_envelope_digest,
        issued_at=activation.issued_at,
        valid_until=activation.valid_until,
        key_id=activation.key_id,
    )


class QuantitativeExtensionDeltaPublicationAuthority:
    """Real :class:`DeltaPublicationAuthorityPort` over the new activation.

    The designated principal (an ``ANALYSIS_WORKER`` in the pinned
    organization) and the required exact activation are pinned at construction;
    a caller-supplied digest never becomes permission — ``is_policy_current``
    additionally demands equality with the pinned policy digest, and the
    verified activation's digests must equal the pins on every check. Both
    methods re-verify the protected files at the supplied trusted ``now``, so
    post-startup revocation, rotation, or expiry fails the next check closed.

    ``worker_principal_id`` / ``publication_id`` / ``lease_generation``, when
    supplied to ``is_runtime_current``, are validated for required shape (the
    worker id must equal the designated principal; the publication id must be
    an opaque non-path identifier; the generation must be a positive integer)
    and any mismatch returns ``False``. Actual lease liveness and holder
    binding remain the publication store's own decision — this adapter reports
    only activation currency for the designated worker attempt.
    """

    def __init__(
        self,
        *,
        activation_path: Path,
        verification_keys_path: Path,
        organization_id: str,
        policy_digest: str,
        runtime_digest: str,
        resource_envelope_digest: str,
        worker_principal: Principal,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if not isinstance(activation_path, Path) or not isinstance(verification_keys_path, Path):
            raise ValueError("delta publication authority requires explicit activation file paths")
        if not organization_id:
            raise ValueError("delta publication authority requires an explicit organization")
        _require_digest(policy_digest, "pinned policy")
        _require_digest(runtime_digest, "pinned runtime")
        _require_digest(resource_envelope_digest, "pinned resource envelope")
        if (
            worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or Permission.ANALYSIS_WORK not in principal_permissions(worker_principal)
            or worker_principal.organization_id != organization_id
        ):
            raise ValueError(
                "delta publication authority requires the dedicated organization worker"
            )
        if coordinator is not None and not isinstance(
            coordinator, ExternalAuthorityCurrentnessCoordinator
        ):
            raise ValueError("delta publication authority coordinator must be a Core coordinator")
        self._activation_path = activation_path
        self._verification_keys_path = verification_keys_path
        self._organization_id = organization_id
        self._policy_digest = policy_digest
        self._runtime_digest = runtime_digest
        self._resource_envelope_digest = resource_envelope_digest
        self._worker_principal = worker_principal
        self._coordinator = coordinator

    @property
    def purpose(self) -> QuantitativeExtensionPurpose:
        return DELTA_PUBLICATION_PURPOSE

    def _verified_at(self, now: datetime) -> QuantitativeExtensionActivationV1 | None:
        try:
            if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
                return None
            if self._coordinator is not None:
                with self._coordinator.guarded_read():
                    return load_quantitative_extension_activation(
                        self._activation_path,
                        self._verification_keys_path,
                        organization_id=self._organization_id,
                        purpose=DELTA_PUBLICATION_PURPOSE,
                        policy_digest=self._policy_digest,
                        runtime_digest=self._runtime_digest,
                        resource_envelope_digest=self._resource_envelope_digest,
                        worker_principal=self._worker_principal,
                        now=now,
                    )
            return load_quantitative_extension_activation(
                self._activation_path,
                self._verification_keys_path,
                organization_id=self._organization_id,
                purpose=DELTA_PUBLICATION_PURPOSE,
                policy_digest=self._policy_digest,
                runtime_digest=self._runtime_digest,
                resource_envelope_digest=self._resource_envelope_digest,
                worker_principal=self._worker_principal,
                now=now,
            )
        except Exception:
            return None

    def is_policy_current(self, *, policy_digest: str, now: datetime) -> bool:
        """Policy currency: pinned digest equality plus a fresh activation."""
        try:
            _require_digest(policy_digest, "queried policy")
        except ValueError:
            return False
        if policy_digest != self._policy_digest:
            return False
        verified = self._verified_at(now)
        return verified is not None and verified.policy_digest == policy_digest

    def is_runtime_current(
        self,
        *,
        now: datetime,
        worker_principal_id: str | None = None,
        publication_id: str | None = None,
        lease_generation: int | None = None,
    ) -> bool:
        """Runtime currency for the designated worker attempt, or False.

        Optional attempt identifiers are shape-checked (worker id must name the
        designated principal; publication id must be opaque; generation must be
        a positive integer) but confer no lease rights: the publication store
        alone decides whether the lease is live and held by this worker.
        """
        try:
            if worker_principal_id is not None and (
                not isinstance(worker_principal_id, str)
                or worker_principal_id != self._worker_principal.principal_id
            ):
                return False
            if publication_id is not None:
                _require_opaque_shape(publication_id, "publication")
            if lease_generation is not None and (
                type(lease_generation) is not int
                or isinstance(lease_generation, bool)
                or lease_generation <= 0
            ):
                return False
        except ValueError:
            return False
        verified = self._verified_at(now)
        return (
            verified is not None
            and verified.runtime_digest == self._runtime_digest
            and verified.worker_principal_id == self._worker_principal.principal_id
        )


__all__ = [
    "QuantitativeExtensionDeltaPublicationAuthority",
    "VerifiedQuantitativeExtensionPurpose",
    "is_quantitative_extension_current",
    "load_quantitative_extension_activation",
    "verified_purpose_snapshot",
]

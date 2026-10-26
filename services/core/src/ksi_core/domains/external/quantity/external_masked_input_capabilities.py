"""Closed masked DSM capability seam for the first-execution worker lane (P2, additive).

Unmounted by default: the parent composition mounts the router factories only
after wiring the real masked lane plus the real reconstruction/storage ports.
The existing V2 worker transport, the existing masked ``/input``/``/bytes``
seam, and the late-export publication lane are untouched.

What this seam does, read carefully:

- It reveals, for ONE live masked attempt, the two already-sealed DSM
  identities as short-lived storage capabilities projected through the actual
  :class:`DeltaPublicationS3InputCapabilityIssuer` (pure issuer: it accepts the
  actual embedded source ``CalculationIdentityV2`` plus the new masked attempt
  lease/expiry, never a publication intent and never a V2 attempt). The mask
  itself never travels this seam: the worker fetches it through the existing
  Core-bearer ``EXCLUSION_MASK`` byte window behind the same live masked fence
  (``/inputs/EXCLUSION_MASK/bytes``). A Core bearer is never sent to
  object-storage origins.
- Every issuance rechecks, under the shared currentness coordinator where Core
  state is consulted: live masked fence (holder/instance/generation/scope),
  current masked evidence (source/mask/area/policy/runtime plus fresh signed
  ``MASKED_ANALYSIS_V3`` activation), capability TTL bounding, and wall-clock
  currency. Because presigning performs reconstruction/storage I/O outside any
  guard, a final freshness recheck re-reads the live attempt, the exact input,
  and fresh evidence at a fresh trusted instant under the shared guard after
  that I/O; any source/lease/cancel/policy drift in between drops the signed
  URLs instead of returning them.
- Capabilities are projected through the actual ``EvidenceStorage`` primitive
  (``presigned_get``), exactly like the V2 Analysis input issuer, but into the
  NEW closed worker caps (``external_masked_worker``). The old V2 capability
  schema is not widened.

Discovery uses the Lead-owned pendings:
``GET /v1/internal/mask-inspection-jobs/pending`` and
``GET /v1/internal/masked-calculations/pending``. No duplicate discovery
router lives here.

Parent integration: the factory takes the scoped passed concrete
``MaskedQuantitativeWiring`` (not a Protocol), plus the concrete
reconstruction/storage ports that share its coordinator, plus the designated
worker pin and a trusted clock. Tests use strict fakes over loopback origins;
production DSM object stores remain operator-owned.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_api import (
    MASKED_ATTEMPT_DIGEST_HEADER,
    MASKED_WORKER_INSTANCE_ID_HEADER,
)
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionAttemptV3,
    masked_execution_runtime_digest,
)
from ksi_event_contracts.external_masked_worker import (
    MaskedWorkflowDsmCapabilityV1,
    MaskedWorkflowDsmInputViewV1,
)
from starlette.concurrency import run_in_threadpool

from ksi_core.composition.masked_quantitative_graph import MaskedQuantitativeWiring
from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
    DeltaPublicationS3InputCapabilityIssuer,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
)

_MAX_SLICE = 1024 * 1024
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _deadline_for(authorization: Any) -> datetime:
    return authorization.authorized_at + timedelta(
        seconds=authorization.resource_envelope.max_deadline_seconds
    )


def _require_concrete_wiring(wiring: Any) -> MaskedQuantitativeWiring:
    if not isinstance(wiring, MaskedQuantitativeWiring):
        raise ValueError(
            "masked DSM capability seam requires the concrete MaskedQuantitativeWiring"
        )
    return wiring


@dataclass(frozen=True, slots=True)
class ResolvedMaskedDsmLeg:
    """Two sealed DSM caps plus their Core-bound lane seals.

    All digests come from Core state at the fresh post-I/O instant (lane
    config seals, live attempt authorization, fresh witness admission) —
    never from caller hashes.
    """

    baseline: MaskedWorkflowDsmCapabilityV1
    current: MaskedWorkflowDsmCapabilityV1
    execution_runtime_digest: str
    resource_envelope_digest: str
    activation_digest: str


def resolve_masked_dsm_capabilities(
    *,
    wiring: MaskedQuantitativeWiring,
    reconstruction: Any,
    storage: Any,
    request_id: str,
    worker_principal: Principal,
    attempt: MaskedExecutionAttemptV3,
    now: datetime,
) -> ResolvedMaskedDsmLeg | None:
    """Issue the two sealed DSM capabilities for one live masked attempt.

    Fails closed (``None``) for unknown/foreign/unleased/expired/canceled
    records, for non-current sources, for non-current policy/runtime authority,
    and for any reconstruction/storage drift. The returned capabilities name
    only the sealed DSM identities; the worker input binding is checked by the
    caller against its ``/input`` fetch. Lane seals (five-pin runtime,
    envelope, signed activation) travel alongside from the same fresh instant
    so the worker can pin them before any download. No publication intent and
    no V2 attempt is borrowed here.
    """
    wiring = _require_concrete_wiring(wiring)
    if worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER:
        return None
    if not _is_utc(now):
        return None
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        return None
    try:
        sealed_attempt = MaskedExecutionAttemptV3.model_validate(attempt.model_dump(by_alias=True))
    except Exception:
        return None
    if (
        sealed_attempt.execution_attempt_digest is None
        or sealed_attempt.execution_attempt_digest != sealed_attempt.canonical_digest()
    ):
        return None
    # Live fence via the real calculation store (public methods only, no private scan).
    try:
        record = wiring.calculations.get_history(
            request_id, organization_id=worker_principal.organization_id
        )
    except Exception:
        return None
    if record is None:
        return None
    if (
        record.organization_id != worker_principal.organization_id
        or record.active_attempt != sealed_attempt
        or record.status.value != "RUNNING"
        or sealed_attempt.lease_expires_at <= now
        or now >= _deadline_for(record.authorization)
    ):
        return None
    if record.authorization.worker_principal_id != worker_principal.principal_id:
        # The V3 authorization binds the designated lane worker as the
        # expected owner; any other identity (human issuer id, borrowed V2
        # worker) fails closed with no capabilities issued.
        return None
    trusted = wiring.config.clock()
    if not _is_utc(trusted):
        return None
    try:
        worker_input = wiring.calculations.input_for_worker(
            request_id=request_id,
            worker_principal=worker_principal,
            attempt=sealed_attempt,
            now=trusted,
        )
    except Exception:
        return None
    if worker_input is None:
        return None
    identity = worker_input.masked_calculation_identity
    if (
        identity.organization_id != worker_principal.organization_id
        or identity.organization_id != record.organization_id
    ):
        return None
    source = identity.source_calculation_identity
    # Pure issuer: actual embedded source V2 identity plus the NEW masked
    # attempt lease/expiry. No publication intent, no V2 attempt borrowing.
    try:
        issuer = DeltaPublicationS3InputCapabilityIssuer(
            reconstruction=reconstruction,
            storage=storage,
            signing_clock=wiring.config.clock,
        )
    except Exception:
        return None
    try:
        issued = issuer(
            identity=source,
            lease_expires_at=sealed_attempt.lease_expires_at,
            publication_expires_at=sealed_attempt.lease_expires_at,
            worker_principal=worker_principal,
            worker_instance_id=sealed_attempt.worker_instance_id,
            lease_generation=sealed_attempt.lease_generation,
            now=trusted,
        )
    except Exception:
        return None
    if issued is None:
        return None
    try:
        caps = tuple(
            MaskedWorkflowDsmCapabilityV1(
                role=item.role,
                artifact_id=item.artifact_id,
                observed_sha256=item.observed_sha256,
                observed_size_bytes=item.observed_size_bytes,
                download_url=item.download_url,
                required_headers=dict(item.required_headers),
                expires_at=item.expires_at,
            )
            for item in issued
        )
        if len(caps) != 2:
            return None
        baseline, current = caps
    except Exception:
        return None
    # Fresh post-I/O checks under the shared guard at a fresh trusted instant:
    # presigning performed reconstruction/storage I/O outside any guard, so the
    # source, lease, cancel, or policy may have changed beneath the signed URLs.
    try:
        with wiring.coordinator.guarded_read():
            fresh = wiring.config.clock()
            if not _is_utc(fresh):
                return None
            fresh_record = wiring.calculations.get_history(
                request_id, organization_id=worker_principal.organization_id
            )
            if (
                fresh_record is None
                or fresh_record.active_attempt != sealed_attempt
                or fresh_record.status.value != "RUNNING"
                or sealed_attempt.lease_expires_at <= fresh
                or fresh >= _deadline_for(fresh_record.authorization)
            ):
                return None
            fresh_input = wiring.calculations.input_for_worker(
                request_id=request_id,
                worker_principal=worker_principal,
                attempt=sealed_attempt,
                now=fresh,
            )
            if fresh_input is None:
                return None
            if (
                fresh_input.masked_calculation_identity.masked_calculation_identity_digest
                != identity.masked_calculation_identity_digest
            ):
                return None
            # Current evidence plus fresh signed activation: a revoked source,
            # withdrawn mask, expired activation, or stale fence drops the URLs.
            witness = wiring.evidence.prepare_witness(
                masked_calculation_identity_digest=(
                    identity.masked_calculation_identity_digest or ""
                ),
                organization_id=worker_principal.organization_id,
                now=fresh,
                expected_admission=fresh_record.admission,
            )
            fresh_witness = (
                wiring.evidence.witness_is_current(witness=witness, now=fresh)
                if witness is not None
                else None
            )
            if fresh_witness is None or fresh_witness.admission != fresh_record.admission:
                return None
            if worker_principal.organization_id != fresh_witness.admission.organization_id:
                return None
            if not all(
                _is_utc(cap.expires_at)
                and fresh < cap.expires_at <= sealed_attempt.lease_expires_at
                for cap in caps
            ):
                return None
            # Lane seals from the same fresh instant: five-pin runtime from
            # the lane config seals, envelope from the live authorization,
            # activation from the fresh witness admission. Never caller
            # hashes.
            try:
                execution_runtime_digest = masked_execution_runtime_digest(
                    wiring.config.execution_runtime,
                    wiring.config.masked_profile_digest,
                    wiring.config.resource_envelope.canonical_digest(),
                    wiring.config.inspection_profile.canonical_digest(),
                )
            except Exception:
                return None
            resource_envelope_digest = fresh_record.authorization.resource_envelope_digest
            activation_digest = fresh_witness.admission.activation_digest
            if (
                not isinstance(resource_envelope_digest, str)
                or _DIGEST_RE.fullmatch(resource_envelope_digest) is None
                or not isinstance(activation_digest, str)
                or _DIGEST_RE.fullmatch(activation_digest) is None
            ):
                return None
    except Exception:
        return None
    baseline, current = caps
    assert isinstance(baseline, MaskedWorkflowDsmCapabilityV1)
    assert isinstance(current, MaskedWorkflowDsmCapabilityV1)
    return ResolvedMaskedDsmLeg(
        baseline=baseline,
        current=current,
        execution_runtime_digest=execution_runtime_digest,
        resource_envelope_digest=resource_envelope_digest,
        activation_digest=activation_digest,
    )


def build_external_masked_dsm_capability_router(
    *,
    wiring: MaskedQuantitativeWiring,
    reconstruction: Any,
    storage: Any,
    designated_worker: Principal,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the closed masked DSM capability HTTP seam over the genuine lane."""
    wiring = _require_concrete_wiring(wiring)
    if not callable(getattr(reconstruction, "resolve_sealed_subject", None)):
        raise ValueError("masked DSM seam requires a reconstruction subject resolver")
    if not callable(getattr(storage, "presigned_get", None)):
        raise ValueError("masked DSM seam requires protected storage with presigned_get")
    if (
        designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
        or not designated_worker.organization_id
    ):
        raise ValueError("masked DSM seam requires the designated organization worker")
    if (
        wiring.config.worker_principal.principal_id != designated_worker.principal_id
        or wiring.config.worker_principal.organization_id != designated_worker.organization_id
    ):
        raise ValueError("masked DSM seam designated worker must match the lane pin")
    if getattr(reconstruction, "coordinator", None) is not wiring.coordinator:
        raise ValueError("masked DSM seam reconstruction must share the lane coordinator")
    envelope = ResourceEnvelopeV1.model_validate(wiring.config.resource_envelope.model_dump())
    if envelope.resource_envelope_digest != envelope.canonical_digest():
        raise ValueError("masked DSM seam requires a sealed resource envelope")
    now_fn = clock or wiring.config.clock
    if not callable(now_fn):
        raise ValueError("masked DSM seam requires a trusted clock")
    router = APIRouter(tags=["external-masked-dsm-capability"])
    work = require_permission(Permission.ANALYSIS_WORK)

    def require_designated_worker(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="MASKED_WORKER_REQUIRED")
        if (
            principal.principal_id != designated_worker.principal_id
            or principal.organization_id != designated_worker.organization_id
        ):
            raise HTTPException(status_code=403, detail="MASKED_WORKER_MISMATCH")

    def active_for(
        principal: Principal, request_id: str, attempt_digest: str | None, instance: str | None
    ) -> MaskedExecutionAttemptV3:
        if not attempt_digest or not instance:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REQUIRED")
        try:
            record = wiring.calculations.get_history(
                request_id, organization_id=principal.organization_id
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="MASKED_JOB_NOT_FOUND")
        attempt = record.active_attempt
        if (
            attempt is None
            or attempt.execution_attempt_digest != attempt_digest
            or attempt.worker_instance_id != instance
        ):
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        return attempt

    @router.get(
        "/v1/internal/masked-calculations/{request_id}/dsm-input",
        response_model=MaskedWorkflowDsmInputViewV1,
    )
    async def dsm_input(
        request_id: str,
        attempt_digest: str | None = Header(default=None, alias=MASKED_ATTEMPT_DIGEST_HEADER),
        worker_instance_id: str | None = Header(
            default=None, alias=MASKED_WORKER_INSTANCE_ID_HEADER
        ),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedWorkflowDsmInputViewV1:
        require_designated_worker(principal)
        checked_at = now_fn()
        attempt = active_for(principal, request_id, attempt_digest, worker_instance_id)
        leg = await run_in_threadpool(
            resolve_masked_dsm_capabilities,
            wiring=wiring,
            reconstruction=reconstruction,
            storage=storage,
            request_id=request_id,
            worker_principal=principal,
            attempt=attempt,
            now=checked_at,
        )
        if leg is None:
            # Unknown record already answered 404 above; anything else is a
            # live-fence/evidence/authority drift that fails closed as 409
            # without distinguishing the cause and without journal mutation.
            raise HTTPException(status_code=409, detail="MASKED_DSM_FENCE_REJECTED")
        baseline, current = leg.baseline, leg.current
        try:
            record = wiring.calculations.get_history(
                request_id, organization_id=principal.organization_id
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="MASKED_DSM_FENCE_REJECTED") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="MASKED_JOB_NOT_FOUND")
        worker_input = wiring.calculations.input_for_worker(
            request_id=request_id,
            worker_principal=principal,
            attempt=attempt,
            now=now_fn(),
        )
        if worker_input is None:
            raise HTTPException(status_code=409, detail="MASKED_DSM_FENCE_REJECTED")
        identity = worker_input.masked_calculation_identity
        return MaskedWorkflowDsmInputViewV1(
            request_id=request_id,
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            source_calculation_identity_digest=identity.source_calculation_identity_digest,
            attempt_digest=attempt.execution_attempt_digest or "",
            worker_instance_id=attempt.worker_instance_id,
            lease_generation=attempt.lease_generation,
            lease_expires_at=attempt.lease_expires_at,
            execution_runtime_digest=leg.execution_runtime_digest,
            resource_envelope_digest=leg.resource_envelope_digest,
            activation_digest=leg.activation_digest,
            capabilities=(baseline, current),
        )

    return router


__all__ = [
    "ResolvedMaskedDsmLeg",
    "build_external_masked_dsm_capability_router",
    "resolve_masked_dsm_capabilities",
]

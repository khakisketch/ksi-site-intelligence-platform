"""Additive V3 masked-execution dispatch: three exact inputs, one V3 output.

New dispatch for the masked (P2) path only.  It does not modify the existing
two-input V2 worker transport, does not borrow the V2 worker identity, and
does not dispatch the old two-input protocol.  Three Core-bound input
capabilities (baseline DSM, current DSM, exclusion mask) are resolved to
already-staged local sealed files; the contained numeric primitive
(:func:`measure_masked_volume_v3`) is reused without edits and returns the
new V3 numeric identity only.

Transport rules enforced here, before any byte access:

- Exactly three capabilities, ordered baseline/current/mask, each binding an
  opaque artifact id plus observed SHA-256/size.  Client-supplied URLs are
  rejected: capabilities carry no URL field at all.
- Capability bytes must equal the sealed masked identity (source DSM
  artifact/sha/size plus mask binding artifact/sha/size); any mismatch,
  reordering, truncation to two inputs, or V2 identity reuse fails closed.
- Capability expiry must not outlive the lease; stale leases, expired
  capabilities, cancelled watchdogs, and exceeded resource caps fail closed
  with the same typed reasons as the contained primitive.
- The worker runtime binding is V3: the dispatch compares the configured
  masked runtime against the authorization's activation-bound expectation
  supplied by Core.  A V2 worker identity is never accepted as a substitute.

This module mounts no route, activates no worker, and stores no bytes.  The
parent owns composition, route allowlists, and activation wiring.  Tests drive
the pure dispatch with synthetic local GeoTIFFs labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionAttemptV3,
    MaskedWorkerInputV3,
)
from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
    MaskedVolumeCalculationReportV3,
)

from ksi_processing_controller.external_masked_volume_measurement import (
    MaskedVolumeMeasuredV3,
    measure_masked_volume_v3,
)
from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2


class MaskedExecutionDispatchError(RuntimeError):
    """The V3 dispatch binding is invalid; no numeric result was produced."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class MaskedDispatchInputsV3:
    """Already-staged local sealed files bound to one V3 worker input."""

    baseline_path: Path
    current_path: Path
    mask_path: Path


@dataclass(frozen=True, slots=True)
class MaskedDispatchResultV3:
    report: MaskedVolumeCalculationReportV3 | None
    failure: MaskedVolumeCalculationFailureV3 | None
    delta_grid_m: np.ndarray[Any, Any] | None
    row_offset: int | None
    column_offset: int | None


def _require_sealed_attempt(attempt: MaskedExecutionAttemptV3) -> MaskedExecutionAttemptV3:
    validated = MaskedExecutionAttemptV3.model_validate(attempt.model_dump(by_alias=True))
    if (
        validated.execution_attempt_digest is None
        or validated.execution_attempt_digest != validated.canonical_digest()
    ):
        raise MaskedExecutionDispatchError("MASKED_ATTEMPT_MISMATCH")
    authorization = validated.authorization
    if (
        authorization.execution_authorization_digest is None
        or authorization.execution_authorization_digest != authorization.canonical_digest()
    ):
        raise MaskedExecutionDispatchError("MASKED_AUTHORIZATION_MISMATCH")
    if validated.authorization_digest != authorization.execution_authorization_digest:
        raise MaskedExecutionDispatchError("MASKED_AUTHORIZATION_MISMATCH")
    return validated


def _require_three_exact_inputs(
    worker_input: MaskedWorkerInputV3,
    files: MaskedDispatchInputsV3,
) -> MaskedWorkerInputV3:
    validated = MaskedWorkerInputV3.model_validate(worker_input.model_dump(by_alias=True))
    # Shape already enforces exactly three ordered roles; re-check against the
    # staged files so a swapped path cannot silently rebind bytes.
    baseline, current, mask = validated.inputs
    if (baseline.role, current.role, mask.role) != (
        "BASELINE_DSM",
        "CURRENT_DSM",
        "EXCLUSION_MASK",
    ):
        raise MaskedExecutionDispatchError("MASKED_INPUT_MISMATCH")
    for capability in validated.inputs:
        # No URL field exists on V3 capabilities by construction; reject any
        # smuggled URL-like artifact id (defence in depth with the contract).
        value = capability.artifact_id
        lowered = value.lower()
        if (
            "://" in value
            or value.startswith(("/", "\\"))
            or ".." in value
            or "\\" in value
            or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
        ):
            raise MaskedExecutionDispatchError("MASKED_INPUT_MISMATCH")
    _ = files
    return validated


def dispatch_masked_execution_v3(
    *,
    worker_input: MaskedWorkerInputV3,
    files: MaskedDispatchInputsV3,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    lease_expires_at: datetime,
    report_id: str,
    computed_at: datetime,
    reported_at: datetime,
) -> MaskedDispatchResultV3:
    """Run one fenced V3 masked measurement over three exact staged files.

    The masked identity inside ``worker_input`` is the source of truth for
    expected SHA/size/grid; the staged files must be the Core-sealed bytes
    those capabilities name.  The contained primitive re-proves every byte,
    grid, and resource fact before decoding.
    """
    try:
        attempt = _require_sealed_attempt(worker_input.attempt)
        validated_input = _require_three_exact_inputs(worker_input, files)
        identity: MaskedCalculationIdentityV3 = validated_input.masked_calculation_identity
        if (
            identity.masked_calculation_identity_digest is None
            or identity.masked_calculation_identity_digest != identity.canonical_digest()
        ):
            raise MaskedExecutionDispatchError("MASKED_IDENTITY_MISMATCH")
        if (
            attempt.authorization.masked_calculation_identity_digest
            != identity.masked_calculation_identity_digest
        ):
            raise MaskedExecutionDispatchError("MASKED_IDENTITY_MISMATCH")
        # Fenced transport: capability expiry must not outlive the lease, and
        # the dispatch window must sit inside the live fence.
        for capability in validated_input.inputs:
            if capability.expires_at > attempt.lease_expires_at:
                raise MaskedExecutionDispatchError("INPUT_CAPABILITY_EXPIRED")
        if not (attempt.issued_at <= computed_at <= reported_at <= lease_expires_at):
            raise MaskedExecutionDispatchError("STALE_LEASE")
        if reported_at > attempt.lease_expires_at:
            raise MaskedExecutionDispatchError("STALE_LEASE")
    except MaskedExecutionDispatchError as exc:
        # Binding failures before measurement produce no numeric content.
        # The caller (Core) records a typed V3 failure against the live fence.
        raise exc
    outcome = measure_masked_volume_v3(
        masked_identity=identity,
        baseline_path=files.baseline_path,
        current_path=files.current_path,
        mask_path=files.mask_path,
        envelope=envelope,
        watchdog=watchdog,
        lease_expires_at=lease_expires_at,
        report_id=report_id,
        computed_at=computed_at,
        reported_at=reported_at,
    )
    if isinstance(outcome, MaskedVolumeMeasuredV3):
        return MaskedDispatchResultV3(
            report=outcome.report,
            failure=None,
            delta_grid_m=outcome.delta_grid_m,
            row_offset=outcome.row_offset,
            column_offset=outcome.column_offset,
        )
    return MaskedDispatchResultV3(
        report=None,
        failure=outcome,
        delta_grid_m=None,
        row_offset=None,
        column_offset=None,
    )


__all__ = [
    "MaskedDispatchInputsV3",
    "MaskedDispatchResultV3",
    "MaskedExecutionDispatchError",
    "dispatch_masked_execution_v3",
]

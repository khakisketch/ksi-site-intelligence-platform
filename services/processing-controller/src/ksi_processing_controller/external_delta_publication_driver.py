"""Bounded discovery-driven drain for late-export output jobs.

One bounded poll, never a daemon loop: fetch the worker-visible discovery
page, then run each discovered publication through
:func:`run_delta_publication_job` exactly once. The caller supplies no
publication id out of band — ids come only from the closed discovery page —
and each job reuses the per-id replaced config, so every exact observed
input/worker pin, currentness guard, and closed failure semantic of the
single-job path holds unchanged.

No autoretry: each discovered id is attempted at most once per drain call, in
page order. A failed id is reported, never retried here; server-side attempt
caps (policy ``max_upload_attempts``) additionally bound re-acquisition, and
re-driving requires a new explicit service-caller call, never an internal
loop. No V2 analysis attempt is leased, renewed, reported, or treated as
live: the delegate never touches the V2 lane, and the old numeric state is
never rewritten.

All credentials, pins, origins, and bounds come from the explicit runtime
config; this module reads no environment and provides no defaults. Local
generated tests prove the software handshake only, never an OS sandbox, host
provisioning, or deployment containment claim.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ksi_event_contracts.external_delta_publication_api import SourceVersion

from ksi_processing_controller.external_delta_publication_worker import (
    DeltaPublicationCoreClient,
    DeltaPublicationWorkerConfig,
    DeltaPublicationWorkerError,
    run_delta_publication_job,
    run_masked_delta_publication_job,
)

DrainResult = Literal["PUBLISHED", "FAILED", "SKIPPED"]
DrainFlavor = Literal["v2", "masked"]

#: Exact Core source-contract strings per drain flavor (mirrors the parent
#: publication contracts; the driver never guesses versions).
_FLAVOR_SOURCE_VERSIONS: dict[DrainFlavor, SourceVersion] = {
    "v2": "external-relative-volume-calculation-report.v2",
    "masked": "external-masked-volume-calculation-identity.v3",
}


@dataclass(frozen=True, slots=True)
class PendingDrainOutcome:
    """One discovered id and what this single drain pass did with it."""

    publication_id: str
    result: DrainResult


@dataclass(frozen=True, slots=True)
class PendingDrainSummary:
    """Bounded outcome of one drain pass over one discovery page."""

    discovered: tuple[str, ...]
    outcomes: tuple[PendingDrainOutcome, ...]

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(
            outcome.publication_id for outcome in self.outcomes if outcome.result == "PUBLISHED"
        )

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(
            outcome.publication_id for outcome in self.outcomes if outcome.result == "FAILED"
        )

    @property
    def skipped(self) -> tuple[str, ...]:
        return tuple(
            outcome.publication_id for outcome in self.outcomes if outcome.result == "SKIPPED"
        )


def run_pending_delta_publications(
    *,
    config: DeltaPublicationWorkerConfig,
    worker_principal_id: str,
    limit: int = 50,
    flavor: DrainFlavor = "v2",
    core_client: DeltaPublicationCoreClient | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    owned_client: bool = False,
) -> PendingDrainSummary:
    """Discover pending publications and run each exactly once, in page order.

    ``config.publication_id`` is only a discovery placeholder: every
    discovered id replaces it via :func:`dataclasses.replace` before the
    delegate runs, so no out-of-band publication id can steer the drain. The
    shared ``lease_acquisition_id`` is safe to reuse across publications
    because Core tracks spent acquisitions per publication, not globally.
    ``flavor`` selects the lane delegate explicitly — ``"v2"`` runs the V2
    output job, ``"masked"`` runs the V3 masked output job — and stamps the
    matching source contract on the discovery query, so Core filters to that
    lane's pending ids before its limit/lease checks and the drain can never
    lease a foreign-lane job. There is no auto-detection, and each run
    additionally verifies the leased intent's source contract before any
    input fetch.
    """
    if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
        raise DeltaPublicationWorkerError("INVALID_DISCOVERY_LIMIT")
    if flavor not in ("v2", "masked"):
        raise DeltaPublicationWorkerError("INVALID_DRAIN_FLAVOR")
    cancel = is_cancelled or (lambda: False)
    owns = core_client is None
    client = core_client or DeltaPublicationCoreClient(
        base_url=config.core_base_url,
        bearer_token=config.core_bearer_token,
        maximum_response_bytes=config.maximum_response_bytes,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    run_one = run_delta_publication_job if flavor == "v2" else run_masked_delta_publication_job
    source_contract_version = _FLAVOR_SOURCE_VERSIONS[flavor]
    try:
        if cancel():
            return PendingDrainSummary(discovered=(), outcomes=())
        page = client.discover_pending(limit, source_contract_version=source_contract_version)
        discovered = tuple(page.publication_ids)
        now_monotonic = time.monotonic()
        wall = maximum_wall_seconds or float(config.envelope.max_deadline_seconds)
        shared_expires_at = now_monotonic + wall
        if deadline_monotonic is not None:
            shared_expires_at = min(shared_expires_at, deadline_monotonic)
        outcomes: list[PendingDrainOutcome] = []
        for index, publication_id in enumerate(discovered):
            if cancel():
                outcomes.extend(
                    PendingDrainOutcome(publication_id=rest, result="SKIPPED")
                    for rest in discovered[index:]
                )
                break
            per_config = dataclasses.replace(config, publication_id=publication_id)
            result = run_one(
                config=per_config,
                core_client=client,
                worker_principal_id=worker_principal_id,
                is_cancelled=is_cancelled,
                maximum_wall_seconds=maximum_wall_seconds,
                check_current=check_current,
                deadline_monotonic=shared_expires_at,
                owned_client=False,
            )
            outcomes.append(PendingDrainOutcome(publication_id=publication_id, result=result))
        return PendingDrainSummary(discovered=discovered, outcomes=tuple(outcomes))
    finally:
        if owns or owned_client:
            import contextlib as _contextlib

            with _contextlib.suppress(Exception):
                client.close()


__all__ = [
    "PendingDrainOutcome",
    "PendingDrainSummary",
    "run_pending_delta_publications",
]

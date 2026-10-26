"""Authenticated pinned-worker output receipts, separate from byte uploads.

Core records the result of the contained worker's actual output measurement;
it does not invoke TIFF decoders. A valid upload lease alone cannot invent a
FLOAT64/grid assertion. This store receives those assertions on the separately
authenticated worker-result path, checks the exact source and active runtime,
and exposes only the accepted immutable receipt to the publication store.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from threading import RLock

from ksi_domain.canonical_json import canonical_json_bytes

from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaOutputObservation,
    ExternalDeltaPublicationStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind


def _digest(raw: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()


def _key(observation: DeltaOutputObservation) -> tuple[str, str, str, str, int]:
    return (
        observation.organization_id,
        observation.publication_id,
        observation.worker_principal_id,
        observation.worker_instance_id,
        observation.lease_generation,
    )


def observation_from_record(raw: object) -> DeltaOutputObservation:
    """Closed, bounded field decoding shared by the authenticated API and replay."""
    if not isinstance(raw, dict) or set(raw) != {
        field.name for field in fields(DeltaOutputObservation)
    }:
        raise ValueError("delta output observation has missing or unknown fields")
    data = dict(raw)
    for name, size in (("transform", 6), ("bounds", 4)):
        value = data[name]
        if not isinstance(value, (list, tuple)) or len(value) != size:
            raise ValueError("delta output observation grid shape is invalid")
        data[name] = tuple(value)
    observation = DeltaOutputObservation(**data)
    if observation.observation_digest is None:
        raise ValueError("worker output observation must be sealed")
    return observation


class DeltaOutputObservationRecoveryError(RuntimeError):
    """The worker-result receipt journal cannot establish its exact history."""


class CoreDeltaOutputObservationStore:
    """Only exact active publication workers may submit measured output receipts.

    The store argument to ``record_worker_result`` is a concrete server-side
    participant, never deserialized from the request. Verifying that participant
    uses this observation store closes the otherwise cyclic composition without
    a mutable 'bind later' fallback or a caller-created lease view.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(coordinator, ExternalAuthorityCurrentnessCoordinator) or not callable(
            clock
        ):
            raise ValueError("output observations require explicit coordinator and trusted clock")
        self.coordinator, self._clock, self._journal = coordinator, clock, journal
        self._lock = RLock()
        self._records: dict[tuple[str, str, str, str, int], DeltaOutputObservation] = {}
        try:
            for event in journal.replay():
                self._apply(event)
        except BaseException as exc:
            journal.close()
            raise DeltaOutputObservationRecoveryError(str(exc)) from exc

    def record_worker_result(
        self,
        *,
        publication_store: ExternalDeltaPublicationStore,
        worker_principal: Principal,
        observation: DeltaOutputObservation,
    ) -> DeltaOutputObservation | None:
        if (
            not isinstance(publication_store, ExternalDeltaPublicationStore)
            or publication_store.coordinator is not self.coordinator
            or publication_store._observations is not self
        ):
            raise ValueError("worker output receipt requires the exact publication graph")
        if worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise PermissionError(
                "only the designated Analysis worker may submit output observations"
            )
        observed = replace(observation)
        if observed.observation_digest is None:
            raise ValueError("worker output observation must be sealed")
        if (worker_principal.organization_id, worker_principal.principal_id) != (
            observed.organization_id,
            observed.worker_principal_id,
        ):
            return None
        with self.coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            lease = publication_store.intent_for_worker(
                observed.publication_id,
                worker_principal=worker_principal,
                worker_instance_id=observed.worker_instance_id,
            )
            if lease is None or lease.lease_generation != observed.lease_generation:
                return None
            if observed.output_size_bytes > publication_store.policy.max_output_bytes:
                return None
            source = publication_store._source.resolve_current_source(
                organization_id=observed.organization_id,
                site_id=observed.site_id,
                work_area_id=observed.work_area_id,
                source_calculation_identity_digest=observed.source_calculation_identity_digest,
                source_numeric_result_identity_digest=observed.source_numeric_result_identity_digest,
                source_coverage_witness_digest=observed.source_coverage_witness_digest,
                now=trusted,
            )
            if source is None or any(
                getattr(source, field.name) != getattr(observed, field.name)
                for field in fields(source)
            ):
                return None
            if not publication_store._authority.is_policy_current(
                policy_digest=publication_store.policy_digest,
                now=trusted,
            ) or not publication_store._authority.is_runtime_current(
                now=trusted,
                worker_principal_id=worker_principal.principal_id,
                publication_id=observed.publication_id,
                lease_generation=observed.lease_generation,
            ):
                return None
            if (
                lease.organization_id != observed.organization_id
                or lease.site_id != observed.site_id
                or lease.work_area_id != observed.work_area_id
                or lease.source_contract_version != observed.source_contract_version
                or lease.source_calculation_identity_digest
                != observed.source_calculation_identity_digest
                or lease.source_numeric_result_identity_digest
                != observed.source_numeric_result_identity_digest
                or lease.source_coverage_witness_digest != observed.source_coverage_witness_digest
                or lease.lease_expires_at is None
                or not trusted < lease.lease_expires_at
            ):
                return None
            existing = self._records.get(_key(observed))
            if existing is not None:
                return existing if existing == observed else None
            event = {
                "kind": "delta-output-observed",
                "version": 1,
                "acceptedAt": trusted.isoformat(),
                "observation": asdict(observed),
            }
            event["eventDigest"] = _digest(event)
            self._journal.append(event)
            self._apply(event)
            return observed

    def resolve_output_observation(
        self,
        *,
        organization_id: str,
        publication_id: str,
        worker_principal_id: str,
        worker_instance_id: str,
        lease_generation: int,
        now: datetime,
    ) -> DeltaOutputObservation | None:
        with self._lock:
            return self._records.get(
                (
                    organization_id,
                    publication_id,
                    worker_principal_id,
                    worker_instance_id,
                    lease_generation,
                )
            )

    def _apply(self, event: object) -> None:
        if not isinstance(event, dict) or set(event) != {
            "kind",
            "version",
            "acceptedAt",
            "observation",
            "eventDigest",
        }:
            raise ValueError("output receipt journal event shape is invalid")
        if (
            event["kind"] != "delta-output-observed"
            or type(event["version"]) is not int
            or event["version"] != 1
        ):
            raise ValueError("output receipt journal kind/version is invalid")
        if event["eventDigest"] != _digest({k: v for k, v in event.items() if k != "eventDigest"}):
            raise ValueError("output receipt journal digest is invalid")
        stamp = datetime.fromisoformat(event["acceptedAt"])
        if stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp):
            raise ValueError("output receipt acceptance must use UTC")
        observation = observation_from_record(event["observation"])
        if _key(observation) in self._records:
            raise ValueError("duplicate output receipt event")
        self._records[_key(observation)] = observation

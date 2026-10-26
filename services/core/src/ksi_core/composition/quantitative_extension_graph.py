"""Explicit optional delta assembly over the exact common Core participants.

No environment discovery, implicit V2 activation, or default signing/runtime
authority. A missing config mounts nothing; an invalid explicit config fails
closed. Test-created signatures establish local software behavior only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

from ksi_core.composition.external_graph import ExternalAnalysisWiring
from ksi_core.composition.masked_quantitative_graph import MaskedQuantitativeWiring
from ksi_core.domains.external.quantity.analysis_activation_authority import _runtime_digest
from ksi_core.domains.external.quantity.external_delta_output_observations import (
    CoreDeltaOutputObservationStore,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaPublicationPolicy,
    ExternalDeltaPublicationStore,
    FilesystemDeltaByteStore,
)
from ksi_core.domains.external.quantity.external_delta_source_adapters import (
    CoreDeltaEgressAdapter,
    CoreV2DeltaSourceAdapter,
)
from ksi_core.domains.external.quantity.external_masked_delta_source_adapter import (
    CoreMaskedDeltaSourceAdapter,
    CoreVersionedDeltaSourceAdapter,
)
from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
    QuantitativeExtensionDeltaPublicationAuthority,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind


@dataclass(frozen=True)
class DeltaPublicationLocalConfig:
    policy: DeltaPublicationPolicy
    runtime: AnalysisRuntimeIdentityV2
    resource_envelope: ResourceEnvelopeV1
    worker_principal: Principal
    activation_path: Path
    verification_keys_path: Path
    byte_root: Path
    clock: Callable[[], datetime]
    mask_core_origin: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy, DeltaPublicationPolicy) or not isinstance(
            self.runtime,
            AnalysisRuntimeIdentityV2,
        ):
            raise ValueError("delta assembly requires exact explicit policy and runtime pins")
        if (
            not isinstance(self.worker_principal, Principal)
            or self.worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
        ):
            raise ValueError("delta assembly requires the designated Analysis worker")
        envelope = ResourceEnvelopeV1.model_validate(self.resource_envelope.model_dump())
        if envelope.resource_envelope_digest != envelope.canonical_digest():
            raise ValueError("delta assembly requires a sealed envelope")
        if (
            self.policy.max_output_bytes > envelope.max_output_bytes
            or self.policy.max_grid_cells > envelope.max_pixels
            or self.policy.max_upload_attempts > envelope.max_retry_attempts
        ):
            raise ValueError("delta publication policy exceeds the configured native envelope")
        for path in (self.activation_path, self.verification_keys_path, self.byte_root):
            if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "delta assembly paths must be explicit absolute owner-controlled paths"
                )
        if not callable(self.clock):
            raise ValueError("delta assembly requires a trusted clock")
        if self.mask_core_origin is not None:
            if (
                not isinstance(self.mask_core_origin, str)
                or not 1 <= len(self.mask_core_origin) <= 2048
            ):
                raise ValueError("masked delta inputs require an explicit pinned Core origin")
            try:
                origin = urlsplit(self.mask_core_origin)
                address = ip_address(origin.hostname or "")
                if (
                    origin.scheme not in {"http", "https"}
                    or origin.username is not None
                    or origin.password is not None
                    or origin.path not in {"", "/"}
                    or origin.query
                    or origin.fragment
                    or origin.port is not None
                    and not 1 <= origin.port <= 65535
                    or origin.scheme == "http"
                    and not address.is_loopback
                    or any(ord(char) <= 32 for char in self.mask_core_origin)
                ):
                    raise ValueError("invalid origin")
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "masked delta inputs require an explicit pinned Core origin"
                ) from exc


@dataclass(frozen=True)
class DeltaPublicationWiring:
    config: DeltaPublicationLocalConfig
    store: ExternalDeltaPublicationStore
    source: CoreV2DeltaSourceAdapter
    observations: CoreDeltaOutputObservationStore
    bytes: FilesystemDeltaByteStore
    analysis: ExternalAnalysisWiring
    sites: SiteStore
    masked_source: CoreMaskedDeltaSourceAdapter | None = None

    def verify_participants(
        self,
        *,
        analysis: ExternalAnalysisWiring,
        sites: SiteStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if (
            self.analysis is not analysis
            or self.sites is not sites
            or self.store.coordinator is not coordinator
            or self.source.coordinator is not coordinator
            or self.observations.coordinator is not coordinator
            or self.store._observations is not self.observations
            or self.source._intents is not analysis.intents
            or self.source._assessments is not analysis.assessments
            or self.source._calculations is not analysis.calculations
            or not isinstance(self.store._egress, CoreDeltaEgressAdapter)
            or self.store._egress._sites is not sites
        ):
            raise ValueError("delta publication requires the exact mounted common Core graph")
        if self.masked_source is None:
            if self.store._source is not self.source:
                raise ValueError("V2 delta publication requires the exact source adapter")
        elif (
            not isinstance(self.store._source, CoreVersionedDeltaSourceAdapter)
            or self.store._source.v2 is not self.source
            or self.store._source.v3 is not self.masked_source
            or self.masked_source.coordinator is not coordinator
        ):
            raise ValueError("V3 delta publication requires the exact versioned source adapter")

    def close(self) -> None:
        self.bytes.close()


def build_delta_publication_wiring(
    *,
    journal: Callable[[str], DurableJournal],
    config: DeltaPublicationLocalConfig,
    analysis: ExternalAnalysisWiring | None,
    sites: SiteStore,
    coordinator: ExternalAuthorityCurrentnessCoordinator,
    masked: MaskedQuantitativeWiring | None = None,
) -> DeltaPublicationWiring:
    if not isinstance(config, DeltaPublicationLocalConfig) or not isinstance(
        analysis, ExternalAnalysisWiring
    ):
        raise ValueError(
            "delta publication requires explicit config and the existing Analysis graph"
        )
    source = CoreV2DeltaSourceAdapter(
        intents=analysis.intents,
        assessments=analysis.assessments,
        calculations=analysis.calculations,
        coordinator=coordinator,
    )
    masked_source = None
    if masked is not None:
        if config.mask_core_origin is None:
            raise ValueError("masked delta publication requires its explicit Core byte origin")
        if (
            not isinstance(masked, MaskedQuantitativeWiring)
            or masked.assessments is not analysis.assessments
            or masked.sites is not sites
            or masked.coordinator is not coordinator
        ):
            raise ValueError("delta masked sources must belong to the exact common graph")
        masked_source = CoreMaskedDeltaSourceAdapter(
            calculations=masked.calculations,
            coordinator=coordinator,
        )
    routed_source = (
        CoreVersionedDeltaSourceAdapter(
            v2=source,
            v3=masked_source,
            coordinator=coordinator,
        )
        if masked_source is not None
        else source
    )
    authority = QuantitativeExtensionDeltaPublicationAuthority(
        activation_path=config.activation_path,
        verification_keys_path=config.verification_keys_path,
        organization_id=config.worker_principal.organization_id,
        policy_digest=config.policy.canonical_digest(),
        runtime_digest=_runtime_digest(config.runtime),
        resource_envelope_digest=config.resource_envelope.canonical_digest(),
        worker_principal=config.worker_principal,
        coordinator=coordinator,
    )
    if not authority.is_policy_current(
        policy_digest=config.policy.canonical_digest(), now=config.clock()
    ):
        raise ValueError(
            "delta publication activation is missing, invalid, expired or not purpose-bound"
        )
    owned_journals: list[DurableJournal] = []
    byte_store: FilesystemDeltaByteStore | None = None
    try:
        observations_journal = journal("external-delta-output-observations.jsonl")
        owned_journals.append(observations_journal)
        observations = CoreDeltaOutputObservationStore(
            observations_journal,
            coordinator=coordinator,
            clock=config.clock,
        )
        byte_store = FilesystemDeltaByteStore(config.byte_root)
        publication_journal = journal("external-delta-publications.jsonl")
        owned_journals.append(publication_journal)
        store = ExternalDeltaPublicationStore(
            publication_journal,
            source_witness=routed_source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=sites),
            byte_store=byte_store,
            observations=observations,
            policy=config.policy,
            clock=config.clock,
            coordinator=coordinator,
        )
        wiring = DeltaPublicationWiring(
            config, store, source, observations, byte_store, analysis, sites, masked_source
        )
        wiring.verify_participants(analysis=analysis, sites=sites, coordinator=coordinator)
        return wiring
    except BaseException:
        if byte_store is not None:
            byte_store.close()
        for owned in reversed(owned_journals):
            owned.close()
        raise

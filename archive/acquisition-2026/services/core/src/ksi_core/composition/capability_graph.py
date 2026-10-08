"""Capability authority/configuration/observation projection composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ksi_core.capability.authority_store import (
    CAPABILITY_AUTHORITY_JOURNAL_NAME,
    CapabilityAuthorityStore,
)
from ksi_core.capability.runtime_projection import (
    RUNTIME_ROUTE_OBSERVATION_JOURNAL_NAME,
    LegacyConnectivitySnapshotAdapter,
    RuntimeCapabilityProjector,
    RuntimeRouteFreshnessPolicyV1,
    RuntimeRouteObservationStore,
    TrustedRuntimeRouteConfigurationRegistry,
    TrustedRuntimeRouteConfigurationV1,
)


@dataclass(frozen=True)
class CapabilityGraph:
    """Durable capability authority and separate current runtime state."""

    authority_store: Any
    configuration_registry: Any
    observation_store: Any
    projector: Any


def build_capability_graph(
    *,
    journal: Callable[[str], Any],
    capability_freshness_policies: Mapping[str, RuntimeRouteFreshnessPolicyV1] | None,
    runtime_route_configurations: tuple[TrustedRuntimeRouteConfigurationV1, ...],
    acquisition_connectivity_store: Any,
) -> CapabilityGraph:
    # CAP-2/3/4 durable authority and CAP-5 current runtime state remain
    # separate stores.  Both replay during normal startup; observations never
    # enter the authority journal and their original expiry is never rebased.
    freshness_policies = dict(capability_freshness_policies or {})
    capability_authority_store = CapabilityAuthorityStore(
        journal(CAPABILITY_AUTHORITY_JOURNAL_NAME),
        supported_freshness_policies={
            policy_id: policy.freshness_policy_digest
            for policy_id, policy in freshness_policies.items()
        },
    )
    runtime_configuration_registry = TrustedRuntimeRouteConfigurationRegistry(
        runtime_route_configurations
    )
    runtime_observation_store = RuntimeRouteObservationStore(
        journal(RUNTIME_ROUTE_OBSERVATION_JOURNAL_NAME)
    )
    legacy_connectivity_adapter = LegacyConnectivitySnapshotAdapter(
        connectivity_store=acquisition_connectivity_store,
        configuration_registry=runtime_configuration_registry,
    )
    runtime_capability_projector = RuntimeCapabilityProjector(
        authority_store=capability_authority_store,
        configuration_registry=runtime_configuration_registry,
        observation_store=runtime_observation_store,
        supported_freshness_policies=freshness_policies,
        legacy_connectivity_adapter=legacy_connectivity_adapter,
    )
    return CapabilityGraph(
        authority_store=capability_authority_store,
        configuration_registry=runtime_configuration_registry,
        observation_store=runtime_observation_store,
        projector=runtime_capability_projector,
    )

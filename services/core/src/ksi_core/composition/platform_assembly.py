"""Public external-only platform Core assembly entrypoint (Task 2).

``assemble_platform_app`` is the explicit opt-in counterpart of the retained
legacy ``assemble_app``: it boots without a Mission signing key, device
attestation, acquisition stores or flight/Edge journals. Missing
auth/storage/participants fail closed before any protected route is mounted;
the caller still owns closing every journal accumulated in ``opened`` when
assembly raises, following the legacy convention.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from ksi_core.auth import HumanAuthMode
from ksi_core.composition.external_graph import ExternalAnalysisLocalGraphConfig
from ksi_core.composition.platform_app import create_platform_app
from ksi_core.composition.platform_graph import build_platform_graph
from ksi_core.composition.runtime_surfaces import mount_runtime_surfaces
from ksi_core.composition.spatial_data_graph import SpatialDataLocalAssemblyConfig
from ksi_core.domains.sites.sites import _DEFAULT_MAX_BOOTSTRAP_SITES_PER_ORG
from ksi_core.external_result_workflow_assembly import ExternalResultWorkflowAssemblyConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1

    from ksi_core.auth import AuthRegistry, OidcVerifier
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.evidence import EvidenceStorage


def assemble_platform_app(
    data_dir: Path,
    *,
    journal: Callable[[str], DurableJournal],
    opened: list[Any],
    auth_registry: AuthRegistry,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcVerifier | None = None,
    evidence_storage: EvidenceStorage,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None,
    external_analysis_local_graph: ExternalAnalysisLocalGraphConfig | None = None,
    analysis_activation: AnalysisActivationV1 | None = None,
    spatial_data: SpatialDataLocalAssemblyConfig | None = None,
    site_bootstrap_max_sites_per_org: int = _DEFAULT_MAX_BOOTSTRAP_SITES_PER_ORG,
    expose_docs: bool = False,
) -> FastAPI:
    """Build the platform graph, mount the external-only app, add runtime surfaces."""
    if auth_registry is None:
        raise ValueError(
            "platform Core mounts no unauthenticated protected surface — auth_registry is required"
        )
    graph = build_platform_graph(
        data_dir=data_dir,
        journal=journal,
        opened=opened,
        evidence_storage=evidence_storage,
        external_result_workflow=external_result_workflow,
        external_analysis_local_graph=external_analysis_local_graph,
        analysis_activation=analysis_activation,
        spatial_data=spatial_data,
        site_bootstrap_max_sites_per_org=site_bootstrap_max_sites_per_org,
    )
    app = create_platform_app(
        graph=graph,
        auth_registry=auth_registry,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        expose_docs=expose_docs,
    )
    # Legacy-only state this profile legitimately does not own is declared
    # absent (None) rather than fabricated — capability/device/runtime,
    # managed-processing and flight routes stay unmounted.
    mount_runtime_surfaces(
        app,
        opened=opened,
        capability_authority_store=None,
        runtime_route_configuration_registry=None,
        runtime_route_observation_store=None,
        external_validation_policy_registry=graph.external.validation_policy_registry,
        external_artifact_inspection_store=graph.external.artifact_inspection_store,
        external_display_artifact_store=graph.external.display_artifact_store,
        external_evidence_store=graph.external.evidence_store,
        external_evidence_validation_store=graph.external.evidence_validation_store,
        external_relative_volume_mapping_authority=graph.external.volume_mapping,
        external_use_decision_store=graph.external.use_decision_store,
        external_use_evaluator=graph.external.use_evaluator,
        external_authority_currentness=graph.coordinator,
    )
    return app


__all__ = ["assemble_platform_app"]

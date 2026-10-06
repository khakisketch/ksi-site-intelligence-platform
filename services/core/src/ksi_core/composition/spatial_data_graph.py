"""Explicit local data-lane composition; no production activation/configuration fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from ksi_event_contracts.processing_job import ExecutionLocus
from ksi_event_contracts.spatial_data import (
    SpatialDataErrorV1,
    SpatialDataJobViewV1,
    SpatialDataPageV1,
    SpatialDataRequestV1,
)
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataCompleteRequestV1,
    SpatialDataFailureRequestV1,
    SpatialDataLeaseRequestV1,
    SpatialDataLeaseViewV1,
    SpatialDataOutputUploadRequestV1,
    SpatialDataOutputUploadViewV1,
    SpatialDataRenewRequestV1,
    SpatialDataWorkerInputResponseV1,
    SpatialDataWorkerMutationViewV1,
    SpatialDataWorkerPendingPageV1,
)

from ksi_core.domains.external.delivery.ai_egress import SpatialDataAiEgress
from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore
from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService
from ksi_core.domains.external.delivery.grants import (
    SpatialDataGrantAuthorizer,
    SpatialDataGrantStore,
)
from ksi_core.domains.external.delivery.jobs import (
    SpatialDataJobCurrentnessPort,
    SpatialDataJobStore,
)
from ksi_core.domains.external.delivery.metadata_audit import SpatialDataMetadataAuditStore
from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
from ksi_core.domains.external.delivery.storage import SpatialDataStoragePort
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal


def _storage_ready(storage: SpatialDataStoragePort) -> bool:
    return all(
        callable(getattr(storage, name, None))
        for name in (
            "observe_owned_output",
            "open_version",
            "issue_source_get",
            "issue_output_put",
            "list_owned_versions",
            "delete_owned_version",
        )
    )


def _currentness_ready(currentness: SpatialDataJobCurrentnessPort) -> bool:
    return (
        getattr(currentness, "coordinator", None) is not None
        and callable(getattr(currentness, "resolve_requester", None))
        and callable(getattr(currentness, "is_current", None))
    )


@dataclass(frozen=True)
class SpatialDataLocalGraphConfig:
    policy: SpatialDataPolicyV1
    runtime: SpatialDataRuntimeV1
    activation: SpatialDataActivationV1
    processing_location: ExecutionLocus
    clock: Callable[[], datetime]

    def __post_init__(self) -> None:
        for name, model in (
            ("policy", SpatialDataPolicyV1),
            ("runtime", SpatialDataRuntimeV1),
            ("activation", SpatialDataActivationV1),
        ):
            original = getattr(self, name)
            if not isinstance(original, model):
                raise ValueError("explicit complete data policy/runtime/activation required")
            validated = model.model_validate(original.model_dump())
            if getattr(validated, validated._digest_field) != validated.canonical_digest():
                raise ValueError("sealed data policy/runtime/activation required")
            object.__setattr__(self, name, validated.model_copy(deep=True))
        if (
            not callable(self.clock)
            or not isinstance(self.processing_location, ExecutionLocus)
            or self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
        ):
            raise ValueError("exact data activation policy/runtime/location and clock required")


@dataclass(frozen=True)
class SpatialDataWiring:
    config: SpatialDataLocalGraphConfig
    grants: SpatialDataGrantStore
    authorizer: SpatialDataGrantAuthorizer
    sources: SpatialDataSourceResolver
    jobs: SpatialDataJobStore
    storage: SpatialDataStoragePort
    currentness: SpatialDataJobCurrentnessPort
    downloads: SpatialDataDownloadService | None = None
    metadata_audit: SpatialDataMetadataAuditStore | None = None
    ai_egress: SpatialDataAiEgress | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.config, SpatialDataLocalGraphConfig)
            or not isinstance(self.grants, SpatialDataGrantStore)
            or not isinstance(self.authorizer, SpatialDataGrantAuthorizer)
            or not isinstance(self.sources, SpatialDataSourceResolver)
            or not isinstance(self.jobs, SpatialDataJobStore)
            or not _currentness_ready(self.currentness)
            or not _storage_ready(self.storage)
            or self.downloads is not None
            and not isinstance(self.downloads, SpatialDataDownloadService)
            or self.metadata_audit is not None
            and not isinstance(self.metadata_audit, SpatialDataMetadataAuditStore)
            or self.ai_egress is not None
            and not isinstance(self.ai_egress, SpatialDataAiEgress)
        ):
            raise ValueError("complete exact data wiring required")

    def verify_participants(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        sites: SiteStore,
        work_areas: WorkAreaStore,
        work_orders: ObservationWorkOrderStore,
    ) -> None:
        if (
            not self.sources.uses_exact_participants(
                reconstruction=reconstruction,
                inspections=inspections,
                sites=sites,
                work_areas=work_areas,
                work_orders=work_orders,
            )
            or not self.authorizer.uses_exact_participants(grants=self.grants, sites=sites)
            or not self.jobs.uses_exact_participants(
                grants=self.authorizer, sources=self.sources, currentness=self.currentness
            )
            or self.currentness.coordinator is not self.jobs.coordinator
            or self.config.policy != self.jobs.policy
            or self.config.activation != self.jobs.activation
            or self.downloads is not None
            and (
                self.downloads.jobs is not self.jobs
                or self.downloads.storage is not self.storage
                or self.downloads.policy != self.config.policy
                or self.downloads.audit_store.policy != self.config.policy
            )
            or self.metadata_audit is not None
            and self.metadata_audit.policy != self.config.policy
            or self.ai_egress is not None
            and (
                self.metadata_audit is None
                or not self.ai_egress.uses_exact_participants(
                    jobs=self.jobs,
                    sources=self.sources,
                    grants=self.authorizer,
                    audit=self.metadata_audit,
                )
            )
        ):
            raise ValueError("spatial data must bind exact mounted Core participants and authority")


def build_spatial_data_wiring(
    *,
    journal: Callable[[str], DurableJournal],
    config: SpatialDataLocalGraphConfig,
    reconstruction: ExternalReconstructionStore,
    inspections: ExternalArtifactInspectionStore,
    sites: SiteStore,
    work_areas: WorkAreaStore,
    work_orders: ObservationWorkOrderStore,
    coordinator: ExternalAuthorityCurrentnessCoordinator,
    storage: SpatialDataStoragePort,
    currentness: SpatialDataJobCurrentnessPort,
    spool_root: Path | None = None,
) -> SpatialDataWiring:
    if (
        not isinstance(config, SpatialDataLocalGraphConfig)
        or not callable(journal)
        or not _currentness_ready(currentness)
        or currentness.coordinator is not coordinator
        or not _storage_ready(storage)
    ):
        raise ValueError(
            "spatial data requires complete explicit local storage/currentness material"
        )
    config = SpatialDataLocalGraphConfig(
        config.policy, config.runtime, config.activation, config.processing_location, config.clock
    )
    sources = SpatialDataSourceResolver(
        reconstruction=reconstruction,
        inspections=inspections,
        sites=sites,
        work_areas=work_areas,
        work_orders=work_orders,
        policy=config.policy,
        coordinator=coordinator,
        clock=config.clock,
    )
    grants = SpatialDataGrantStore(journal("spatial-data-grants.jsonl"), coordinator=coordinator)
    authorizer = SpatialDataGrantAuthorizer(
        grants=grants, sites=sites, processing_location=config.processing_location
    )
    jobs = SpatialDataJobStore(
        journal("spatial-data-jobs.jsonl"),
        grants=authorizer,
        sources=sources,
        policy=config.policy,
        runtime=config.runtime,
        activation=config.activation,
        coordinator=coordinator,
        currentness=currentness,
    )
    downloads = None
    if spool_root is not None:
        audit = SpatialDataAuditStore(journal("spatial-data-audit.jsonl"), policy=config.policy)
        downloads = SpatialDataDownloadService(
            jobs=jobs,
            storage=storage,
            audit=audit,
            policy=config.policy,
            spool_root=spool_root,
            clock=config.clock,
        )
    metadata_audit = SpatialDataMetadataAuditStore(
        journal("spatial-data-metadata-audit.jsonl"), policy=config.policy
    )
    ai_egress = SpatialDataAiEgress(jobs, sources, authorizer, metadata_audit, clock=config.clock)
    lane = SpatialDataWiring(
        config,
        grants,
        authorizer,
        sources,
        jobs,
        storage,
        currentness,
        downloads,
        metadata_audit,
        ai_egress,
    )
    lane.verify_participants(
        reconstruction=reconstruction,
        inspections=inspections,
        sites=sites,
        work_areas=work_areas,
        work_orders=work_orders,
    )
    return lane


@dataclass(frozen=True)
class SpatialDataLocalAssemblyConfig:
    """Factories receive real assembled authorities; no environment/account provisioning."""

    config: SpatialDataLocalGraphConfig
    build_storage: Callable[[ExternalReconstructionStore], SpatialDataStoragePort]
    build_currentness: Callable[
        [ExternalAuthorityCurrentnessCoordinator], SpatialDataJobCurrentnessPort
    ]
    spool_root: Path | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.config, SpatialDataLocalGraphConfig)
            or not callable(self.build_storage)
            or not callable(self.build_currentness)
        ):
            raise ValueError(
                "complete explicit local data config/storage/currentness factories required"
            )


def bind_spatial_data_openapi(app: FastAPI) -> None:
    """Keep exact data-contract bounds; FastAPI's schema DTO rounds large integers to float.

    Only opt-in data models/paths are overlaid. Shared non-data leaf names are namespaced
    rather than altering existing inspection/analysis documentation. Actual route discovery
    and caching remain the application's original OpenAPI generator's responsibility.
    """
    original = app.openapi

    def name(value: str) -> str:
        return value if value.startswith("SpatialData") else "SpatialDataV1__" + value

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {
                key: (
                    "#/components/schemas/" + name(item.rsplit("/", 1)[-1])
                    if key == "$ref" and isinstance(item, str)
                    else rewrite(item)
                )
                for key, item in value.items()
            }
        return value

    models = (
        SpatialDataErrorV1,
        SpatialDataJobViewV1,
        SpatialDataPageV1,
        SpatialDataRequestV1,
        SpatialDataCompleteRequestV1,
        SpatialDataFailureRequestV1,
        SpatialDataLeaseRequestV1,
        SpatialDataLeaseViewV1,
        SpatialDataOutputUploadRequestV1,
        SpatialDataOutputUploadViewV1,
        SpatialDataRenewRequestV1,
        SpatialDataWorkerInputResponseV1,
        SpatialDataWorkerMutationViewV1,
        SpatialDataWorkerPendingPageV1,
    )
    exact: dict[str, Any] = {}
    for model in models:
        schema = model.model_json_schema(by_alias=True)
        definitions = schema.pop("$defs", {})
        exact.update({name(key): rewrite(value) for key, value in definitions.items()})
        exact[model.__name__] = rewrite(schema)

    def openapi() -> dict[str, Any]:
        schema = original()
        schema.setdefault("components", {}).setdefault("schemas", {}).update(exact)
        for path, operations in schema["paths"].items():
            if "spatial-data" not in path:
                continue
            for operation in operations.values():
                body = operation.get("requestBody", {}).get("content", {}).get("application/json")
                if body is not None:
                    model_name = body.get("schema", {}).get("title")
                    if model_name in exact:
                        body["schema"] = {"$ref": "#/components/schemas/" + model_name}
        return schema

    # FastAPI's documented per-instance hook replaces a method with a zero-argument callable.
    setattr(app, "openapi", openapi)  # noqa: B010 -- intentional supported method customization

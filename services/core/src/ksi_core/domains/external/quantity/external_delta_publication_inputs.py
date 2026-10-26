"""Closed, opt-in DSM input seam for one delta-publication lease.

Unmounted by default: the parent composition mounts the router factory only
after wiring the real publication store, the real V2 material adapter, the
real reconstruction + protected storage primitive, and the signed output
authority. Public Analysis contracts and old worker transports are unchanged.

What this seam does, read carefully:

- It reveals the exact sealed V2 identity plus its sealed numeric result for
  ONE live publication lease, then projects the two already-sealed DSM
  identities into short-lived storage capabilities. No caller URL, path, or
  grid is accepted: the grid comes from the Core-resolved material, the bytes
  come from the protected storage primitive, and the lease binding comes from
  the publication store's live lease tuple.
- The masked lane (``resolve_publication_masked_worker_input``) mirrors this
  for V3: the exact sealed masked identity plus its sealed COMPLETED V3
  report, two DSM capabilities from the embedded source identity, and a
  worker-only mask retrieval descriptor (no mask URL/path/capability string
  ever leaves Core). It never fabricates a V2 numeric result.
- The late-export input authorizes re-measurement only. It never fabricates a
  V2 analysis attempt, admission, or authorization, and it never treats the
  old COMPLETED attempt as live. The old numeric report stays immutable; the
  worker must reproduce its exact grid/metrics/NaN before any byte upload.
- Every issuance rechecks, under the shared currentness coordinator where
  Core state is consulted: live lease holder/instance/generation, intent and
  lease expiry, publication terminal state, current V2 material (actual
  intents → NX COMPLETED report → fresh AP witness), policy and worker-tied
  runtime currency, and per-capability TTL bounding. Any drift returns
  ``None`` without distinguishing the cause. Because presigning performs
  reconstruction/storage I/O outside any guard, a final freshness recheck
  re-reads the live lease, the exact entry snapshot, fresh source material
  plus witness, and worker-tied authority at a fresh trusted instant under
  the shared guard after that I/O; any source/lease/cancel/policy change in
  between drops the signed URLs instead of returning them.
- Capabilities are projected through the actual ``EvidenceStorage`` primitive
  (``presigned_get``), exactly like the V2 Analysis input issuer, but into the
  NEW worker input contract. The old V2 capability schema is not widened.

Scoped interfaces: the router factory accepts the concrete publication store
plus narrow Protocols for material resolution, reconstruction, and storage so
the parent can wire fakes in tests without importing the full graph. Only the
concrete store type is required for lease/witness/authority truth.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_event_contracts.external_delta_publication_worker import (
    DeltaPublicationMaskedWorkerInputV1,
    DeltaPublicationMaskInputCapabilityV1,
    DeltaPublicationWorkerInputCapabilityV1,
    DeltaPublicationWorkerInputV1,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from starlette.concurrency import run_in_threadpool

from ksi_core.domains.artifacts.evidence import DEFAULT_VIEW_TTL, EvidenceStorageError
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaPublicationStatusV1,
    DeltaSourceWitness,
    ExternalDeltaPublicationStore,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
)


class DeltaPublicationMaterialResolver(Protocol):
    """Narrow source-material seam: exact sealed identity plus sealed report."""

    def resolve_current_material(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> Any | None: ...


class DeltaPublicationReconstructionLike(Protocol):
    """Narrow reconstruction seam: resolve one sealed subject to its manifest."""

    def resolve_sealed_subject(self, subject: Any) -> Any | None: ...


class DeltaPublicationStorageLike(Protocol):
    """Narrow protected-storage seam: project one object key into a GET URL."""

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str: ...


class DeltaPublicationMaskedMaterialResolver(Protocol):
    """Narrow V3 source-material seam: exact sealed masked identity plus V3 report.

    Satisfied by the parent-owned masked source adapter over the actual
    masked calculation store; a later parent-provided union wrapper may front
    the V2 and masked adapters behind one resolver plus versioned dispatch.
    """

    def resolve_current_material(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> Any | None: ...

    def resolve_current_source(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> DeltaSourceWitness | None: ...


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


class DeltaPublicationS3InputCapabilityIssuer:
    """Project the sealed V2 DSM pair into lease-bound GET capabilities.

    Mirrors the V2 Analysis input issuer's verification order (record fence,
    sealed reconstruction, artifact binding, TTL bounding, wall-clock
    currency) but binds the publication lease instead of a V2 attempt. The
    returned capabilities name only the sealed DSM identities; the worker
    input contract built by :func:`resolve_publication_worker_input` binds
    them to the exact lease tuple.
    """

    def __init__(
        self,
        *,
        reconstruction: DeltaPublicationReconstructionLike,
        storage: DeltaPublicationStorageLike,
        signing_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(reconstruction, "resolve_sealed_subject", None)):
            raise ValueError("publication input issuer requires a reconstruction resolver")
        if not callable(getattr(storage, "presigned_get", None)):
            raise ValueError("publication input issuer requires protected storage")
        self._reconstruction = reconstruction
        self._storage = storage
        self._signing_clock = signing_clock or (lambda: datetime.now(UTC))

    def __call__(
        self,
        *,
        identity: CalculationIdentityV2,
        lease_expires_at: datetime,
        publication_expires_at: datetime,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_generation: int,
        now: datetime,
    ) -> (
        tuple[DeltaPublicationWorkerInputCapabilityV1, DeltaPublicationWorkerInputCapabilityV1]
        | None
    ):
        if (
            worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or worker_principal.role is not None
            or worker_principal.device_id is not None
            or type(lease_generation) is not int
            or lease_generation <= 0
            or not worker_instance_id.strip()
        ):
            return None
        if not _is_utc(now) or not _is_utc(lease_expires_at) or not _is_utc(publication_expires_at):
            return None
        if not now < lease_expires_at <= publication_expires_at:
            return None
        bindings = (
            (
                "BASELINE_DSM",
                identity.baseline_subject,
                identity.baseline_dsm_artifact_id,
                identity.baseline_dsm_observed_sha256,
                identity.baseline_dsm_observed_size_bytes,
            ),
            (
                "CURRENT_DSM",
                identity.current_subject,
                identity.current_dsm_artifact_id,
                identity.current_dsm_observed_sha256,
                identity.current_dsm_observed_size_bytes,
            ),
        )
        resolved: list[tuple[str, str, str, str, int]] = []
        try:
            from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
        except Exception:
            return None
        for role, subject, artifact_id, observed_sha256, observed_size_bytes in bindings:
            revision = self._reconstruction.resolve_sealed_subject(subject)
            if revision is None or getattr(revision, "manifest", None) is None:
                return None
            dsm = next(
                (
                    entry
                    for entry in revision.manifest.entries
                    if entry.kind is ProcessingArtifactKind.DSM
                    and entry.artifact_id == artifact_id
                    and "sha256:" + entry.observed_sha256 == observed_sha256
                    and entry.observed_size_bytes == observed_size_bytes
                ),
                None,
            )
            if dsm is None:
                return None
            resolved.append(
                (role, dsm.object_key, artifact_id, observed_sha256, observed_size_bytes)
            )
        upper_bound = min(now + DEFAULT_VIEW_TTL, lease_expires_at, publication_expires_at)
        baseline = self._presign_one(*resolved[0], upper_bound=upper_bound, not_before=now)
        if baseline is None:
            return None
        current = self._presign_one(*resolved[1], upper_bound=upper_bound, not_before=baseline[1])
        if current is None:
            return None
        completed_at = self._signing_clock()
        if (
            not _is_utc(completed_at)
            or completed_at < current[1]
            or completed_at >= upper_bound
            or completed_at >= min(baseline[0].expires_at, current[0].expires_at)
        ):
            return None
        return baseline[0], current[0]

    def _presign_one(
        self,
        role: str,
        object_key: str,
        artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        *,
        upper_bound: datetime,
        not_before: datetime,
    ) -> tuple[DeltaPublicationWorkerInputCapabilityV1, datetime] | None:
        signed_at = self._signing_clock()
        if not _is_utc(signed_at) or signed_at < not_before:
            return None
        seconds = int((upper_bound - signed_at).total_seconds())
        if seconds < 1:
            return None
        ttl = timedelta(seconds=seconds)
        try:
            url = self._storage.presigned_get(object_key, ttl=ttl)
        except EvidenceStorageError:
            return None
        except Exception:
            return None
        if not isinstance(url, str) or not url:
            return None
        return (
            DeltaPublicationWorkerInputCapabilityV1(
                role=role,  # type: ignore[arg-type]
                artifact_id=artifact_id,
                observed_sha256=observed_sha256,
                observed_size_bytes=observed_size_bytes,
                download_url=url,
                required_headers={},
                expires_at=signed_at + ttl,
            ),
            signed_at,
        )


def resolve_publication_worker_input(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: DeltaPublicationMaterialResolver,
    capability_issuer: DeltaPublicationS3InputCapabilityIssuer,
    publication_id: str,
    worker_principal: Principal,
    worker_instance_id: str,
    now: datetime,
) -> DeltaPublicationWorkerInputV1 | None:
    """Issue the exact late-export input for one live publication lease.

    Fails closed (``None``) for unknown/foreign/unleased/expired/canceled/
    failed/published records, for non-current sources, for non-current
    policy/runtime authority, and for any reconstruction/storage drift. The
    returned input embeds the sealed identity and numeric result verbatim and
    binds the two capabilities to the exact lease tuple; it never invents a
    V2 attempt or authorization.
    """
    if worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER:
        return None
    if not _is_utc(now):
        return None
    lease = store.intent_for_worker(
        publication_id, worker_principal=worker_principal, worker_instance_id=worker_instance_id
    )
    if lease is None:
        return None
    if (
        lease.lease_generation <= 0
        or lease.lease_holder_principal_id != worker_principal.principal_id
        or lease.lease_holder_instance_id != worker_instance_id
        or lease.lease_expires_at is None
        or not now < lease.lease_expires_at <= lease.expires_at
    ):
        return None
    trusted = store._clock()  # noqa: SLF001 - same-package trusted clock read
    if not _is_utc(trusted):
        return None
    material = material_resolver.resolve_current_material(
        organization_id=lease.organization_id,
        site_id=lease.site_id,
        work_area_id=lease.work_area_id,
        source_calculation_identity_digest=lease.source_calculation_identity_digest,
        source_numeric_result_identity_digest=lease.source_numeric_result_identity_digest,
        source_coverage_witness_digest=lease.source_coverage_witness_digest,
        now=trusted,
    )
    if material is None:
        return None
    identity = getattr(material, "calculation_identity", None)
    report = getattr(material, "report", None)
    if identity is None or report is None:
        return None
    if (
        getattr(identity, "organization_id", None) != lease.organization_id
        or getattr(identity, "site_id", None) != lease.site_id
        or getattr(identity, "work_area_id", None) != lease.work_area_id
    ):
        return None
    capabilities = capability_issuer(
        identity=identity,
        lease_expires_at=lease.lease_expires_at,
        publication_expires_at=lease.expires_at,
        worker_principal=worker_principal,
        worker_instance_id=worker_instance_id,
        lease_generation=lease.lease_generation,
        now=trusted,
    )
    if capabilities is None:
        return None
    if not store._authority.is_policy_current(  # noqa: SLF001
        policy_digest=lease.policy_digest, now=trusted
    ):
        return None
    if not store._authority.is_runtime_current(  # noqa: SLF001
        now=trusted,
        worker_principal_id=worker_principal.principal_id,
        publication_id=lease.publication_id,
        lease_generation=lease.lease_generation,
    ):
        return None
    try:
        pre_entry = _lease_entry(store, lease)
        if pre_entry is None:
            return None
        pre_snapshot = _entry_snapshot(pre_entry)
        # Final freshness: presigning performed reconstruction/storage I/O
        # outside any guard, so the source, lease, terminal state, policy, or
        # clock may have changed beneath the already-signed URLs. Re-read
        # everything at a fresh trusted instant under the shared guard: the
        # live lease (holder, instance, generation, scope, expiry), the exact
        # entry snapshot, fresh source material plus witness, worker-tied
        # authority, and capability expiry. Any drift drops the signed URLs
        # instead of returning them. An issued URL cannot be un-issued, but
        # the later worker accept guards deny its use after invalidation.
        with store.coordinator.guarded_read(), store._lock:  # noqa: SLF001
            fresh = store._clock()  # noqa: SLF001
            if not _is_utc(fresh):
                return None
            fresh_entry = store._entries.get(  # noqa: SLF001
                (lease.organization_id, lease.publication_id)
            )
            if fresh_entry is None:
                return None
            if (
                fresh_entry.status is not DeltaPublicationStatusV1.PENDING
                or _entry_snapshot(fresh_entry) != pre_snapshot
                or fresh_entry.lease_generation != lease.lease_generation
                or fresh_entry.lease_holder_principal_id != worker_principal.principal_id
                or fresh_entry.lease_holder_instance_id != worker_instance_id
                or fresh_entry.lease_expires_at is None
                or not fresh < fresh_entry.lease_expires_at <= fresh_entry.expires_at
            ):
                return None
            if worker_principal.organization_id != fresh_entry.organization_id or (
                not store._caller_scope_allows(  # noqa: SLF001
                    worker_principal, fresh_entry.site_id, fresh_entry.work_area_id
                )
            ):
                return None
            fresh_material = material_resolver.resolve_current_material(
                organization_id=fresh_entry.organization_id,
                site_id=fresh_entry.site_id,
                work_area_id=fresh_entry.work_area_id,
                source_calculation_identity_digest=(fresh_entry.source_calculation_identity_digest),
                source_numeric_result_identity_digest=(
                    fresh_entry.source_numeric_result_identity_digest
                ),
                source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
                now=fresh,
            )
            if fresh_material is None:
                return None
            fresh_identity = getattr(fresh_material, "calculation_identity", None)
            fresh_report = getattr(fresh_material, "report", None)
            if (
                fresh_identity is None
                or fresh_report is None
                or fresh_identity != identity
                or fresh_report != report
            ):
                return None
            fresh_witness = store._source.resolve_current_source(  # noqa: SLF001
                organization_id=fresh_entry.organization_id,
                site_id=fresh_entry.site_id,
                work_area_id=fresh_entry.work_area_id,
                source_calculation_identity_digest=(fresh_entry.source_calculation_identity_digest),
                source_numeric_result_identity_digest=(
                    fresh_entry.source_numeric_result_identity_digest
                ),
                source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
                now=fresh,
            )
            if fresh_witness is None or not store._witness_matches_entry(  # noqa: SLF001
                fresh_witness, fresh_entry
            ):
                return None
            if not store._authority_is_current(  # noqa: SLF001
                fresh,
                fresh_entry.policy_digest,
                worker_principal_id=worker_principal.principal_id,
                publication_id=fresh_entry.publication_id,
                lease_generation=fresh_entry.lease_generation,
            ):
                return None
            if not all(
                _is_utc(capability.expires_at)
                and fresh < capability.expires_at <= fresh_entry.lease_expires_at
                and capability.expires_at <= fresh_entry.expires_at
                for capability in capabilities
            ):
                return None
        return DeltaPublicationWorkerInputV1(
            publication_id=fresh_entry.publication_id,
            organization_id=fresh_entry.organization_id,
            site_id=fresh_entry.site_id,
            work_area_id=fresh_entry.work_area_id,
            source_contract_version="external-relative-volume-calculation-report.v2",
            source_calculation_identity_digest=fresh_entry.source_calculation_identity_digest,
            source_numeric_result_identity_digest=(
                fresh_entry.source_numeric_result_identity_digest
            ),
            source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
            worker_principal_id=worker_principal.principal_id,
            worker_instance_id=worker_instance_id,
            lease_generation=fresh_entry.lease_generation,
            lease_expires_at=fresh_entry.lease_expires_at,
            publication_expires_at=fresh_entry.expires_at,
            grid_rows=fresh_entry.grid_rows,
            grid_columns=fresh_entry.grid_columns,
            transform=fresh_entry.transform,
            transform_digest=fresh_entry.transform_digest,
            grid_crs_identifier=fresh_entry.grid_crs_identifier,
            grid_crs_digest=fresh_entry.grid_crs_digest,
            bounds=fresh_entry.bounds,
            calculation_identity=fresh_identity,
            numeric_result=fresh_report.numeric_result,
            inputs=capabilities,
        )
    except Exception:
        return None


def _lease_entry(store: ExternalDeltaPublicationStore, lease: Any) -> Any:
    entry = store._entries.get((lease.organization_id, lease.publication_id))  # noqa: SLF001
    return entry


def _entry_snapshot(entry: Any) -> tuple[Any, ...]:
    """Immutable entry facts the final freshness guard requires unchanged."""
    return (
        entry.status,
        entry.organization_id,
        entry.publication_id,
        entry.site_id,
        entry.work_area_id,
        entry.source_contract_version,
        entry.source_calculation_identity_digest,
        entry.source_numeric_result_identity_digest,
        entry.source_coverage_witness_digest,
        entry.grid_rows,
        entry.grid_columns,
        entry.transform,
        entry.transform_digest,
        entry.grid_crs_identifier,
        entry.grid_crs_digest,
        entry.bounds,
        entry.output_id,
        entry.upload_fence_id,
        entry.issued_at,
        entry.expires_at,
        entry.policy_digest,
        entry.lease_generation,
        entry.lease_holder_principal_id,
        entry.lease_holder_instance_id,
        entry.lease_acquisition_id,
        entry.lease_issued_at,
        entry.lease_expires_at,
    )


def _lease_transform(store: ExternalDeltaPublicationStore, lease: Any) -> tuple:
    entry = _lease_entry(store, lease)
    return entry.transform


def _lease_transform_digest(store: ExternalDeltaPublicationStore, lease: Any) -> str:
    entry = _lease_entry(store, lease)
    return entry.transform_digest


def _lease_crs(store: ExternalDeltaPublicationStore, lease: Any) -> tuple[str, str]:
    entry = _lease_entry(store, lease)
    return entry.grid_crs_identifier, entry.grid_crs_digest


def _lease_bounds(store: ExternalDeltaPublicationStore, lease: Any) -> tuple:
    entry = _lease_entry(store, lease)
    return entry.bounds


def build_external_delta_publication_input_router(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: DeltaPublicationMaterialResolver,
    capability_issuer: DeltaPublicationS3InputCapabilityIssuer,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the opt-in worker input router; the parent mounts it explicitly.

    ``GET /v1/internal/delta-publication-uploads/{publication_id}/input``
    requires the ANALYSIS_WORKER bearer, the ``worker_instance_id`` query
    naming the live lease holder, and current source/policy/runtime. The
    response is the exact ``DeltaPublicationWorkerInputV1`` wire shape; Core
    never logs or journals capability URLs.
    """
    if not isinstance(store, ExternalDeltaPublicationStore):
        raise ValueError("publication input router requires the concrete publication store")
    if not callable(getattr(material_resolver, "resolve_current_material", None)):
        raise ValueError("publication input router requires a material resolver")
    if not isinstance(capability_issuer, DeltaPublicationS3InputCapabilityIssuer):
        raise ValueError("publication input router requires the publication capability issuer")
    now_fn = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-delta-publication-input"])
    worker = require_permission(Permission.ANALYSIS_WORK)

    def worker_only(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="DELTA_WORKER_REQUIRED")

    @router.get(
        "/v1/internal/delta-publication-uploads/{publication_id}/input",
        response_model=dict,
    )
    async def worker_input(
        publication_id: str,
        worker_instance_id: str = Query(min_length=1, max_length=255),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict:
        worker_only(principal)
        trusted = now_fn()
        result = await run_in_threadpool(
            resolve_publication_worker_input,
            store=store,
            material_resolver=material_resolver,
            capability_issuer=capability_issuer,
            publication_id=publication_id,
            worker_principal=principal,
            worker_instance_id=worker_instance_id,
            now=trusted,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return {"input": result.model_dump(by_alias=True, mode="json")}

    return router


def _mask_base_origin(value: object) -> str:
    """Explicit Core origin mask capability URLs are minted from.

    The late-export mask route lives on Core itself (same origin as the Core
    API the worker already trusts); it must never point at object-storage
    origins, carry credentials, or come from the environment. The worker
    additionally refuses to send its Core bearer anywhere but this origin.
    """
    from urllib.parse import urlsplit as _split

    if not isinstance(value, str) or not value or len(value) > 16384:
        raise ValueError("mask base origin is invalid")
    try:
        parsed = _split(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(character) <= 32 for character in value)
        ):
            raise ValueError
    except ValueError:
        raise ValueError(
            "mask base origin must be an explicit credential-free HTTP(S) origin"
        ) from None
    return value.rstrip("/")


def _mask_download_url(
    *, base_origin: str, publication_id: str, worker_instance_id: str, lease_generation: int
) -> str:
    from urllib.parse import quote as _quote

    return (
        f"{base_origin}/v1/internal/delta-publication-uploads/{_quote(publication_id, safe='')}"
        f"/mask-bytes?worker_instance_id={_quote(worker_instance_id, safe='')}"
        f"&lease_generation={lease_generation}"
    )


def resolve_publication_masked_worker_input(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: DeltaPublicationMaskedMaterialResolver,
    capability_issuer: DeltaPublicationS3InputCapabilityIssuer,
    mask_base_url: str,
    publication_id: str,
    worker_principal: Principal,
    worker_instance_id: str,
    now: datetime,
) -> DeltaPublicationMaskedWorkerInputV1 | None:
    """Issue the exact V3 late-export input for one live publication lease.

    Mirrors :func:`resolve_publication_worker_input` for the masked profile:
    the exact sealed masked identity plus its sealed COMPLETED V3 report,
    two DSM capabilities projected from the embedded source identity, and a
    worker-only mask retrieval descriptor bound to the sealed mask binding.
    The mask capability carries a server-minted URL only (from the explicit
    ``mask_base_url`` Core origin, never a client URL, path, or object key);
    the bytes themselves travel the dedicated lease-scoped mask route.
    Fails closed (``None``) on the same drift conditions, including a revoked
    masked source; never fabricates a V2 numeric result or touches a V2
    attempt. The mask capability carries a server-minted URL only (from the
    explicit ``mask_base_url`` Core origin, never a client URL, path, or
    object key); the bytes themselves travel the dedicated lease-scoped mask
    route.
    """
    if worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER:
        return None
    if not _is_utc(now):
        return None
    try:
        mask_origin = _mask_base_origin(mask_base_url)
    except ValueError:
        return None
    lease = store.intent_for_worker(
        publication_id, worker_principal=worker_principal, worker_instance_id=worker_instance_id
    )
    if lease is None:
        return None
    if (
        lease.lease_generation <= 0
        or lease.lease_holder_principal_id != worker_principal.principal_id
        or lease.lease_holder_instance_id != worker_instance_id
        or lease.lease_expires_at is None
        or not now < lease.lease_expires_at <= lease.expires_at
    ):
        return None
    trusted = store._clock()  # noqa: SLF001 - same-package trusted clock read
    if not _is_utc(trusted):
        return None
    if lease.source_contract_version != "external-masked-volume-calculation-identity.v3":
        return None
    material = material_resolver.resolve_current_material(
        organization_id=lease.organization_id,
        site_id=lease.site_id,
        work_area_id=lease.work_area_id,
        source_calculation_identity_digest=lease.source_calculation_identity_digest,
        source_numeric_result_identity_digest=lease.source_numeric_result_identity_digest,
        source_coverage_witness_digest=lease.source_coverage_witness_digest,
        now=trusted,
    )
    if material is None:
        return None
    masked_identity = getattr(material, "masked_calculation_identity", None)
    report = getattr(material, "report", None)
    if masked_identity is None or report is None:
        return None
    if (
        getattr(masked_identity, "organization_id", None) != lease.organization_id
        or getattr(masked_identity, "site_id", None) != lease.site_id
        or getattr(masked_identity, "work_area_id", None) != lease.work_area_id
    ):
        return None
    source_identity = masked_identity.source_calculation_identity
    capabilities = capability_issuer(
        identity=source_identity,
        lease_expires_at=lease.lease_expires_at,
        publication_expires_at=lease.expires_at,
        worker_principal=worker_principal,
        worker_instance_id=worker_instance_id,
        lease_generation=lease.lease_generation,
        now=trusted,
    )
    if capabilities is None:
        return None
    if not store._authority.is_policy_current(  # noqa: SLF001
        policy_digest=lease.policy_digest, now=trusted
    ):
        return None
    if not store._authority.is_runtime_current(  # noqa: SLF001
        now=trusted,
        worker_principal_id=worker_principal.principal_id,
        publication_id=lease.publication_id,
        lease_generation=lease.lease_generation,
    ):
        return None
    try:
        pre_entry = _lease_entry(store, lease)
        if pre_entry is None:
            return None
        pre_snapshot = _entry_snapshot(pre_entry)
        mask_expires_at = min(capabilities[0].expires_at, capabilities[1].expires_at)
        with store.coordinator.guarded_read(), store._lock:  # noqa: SLF001
            fresh = store._clock()  # noqa: SLF001
            if not _is_utc(fresh):
                return None
            fresh_entry = store._entries.get(  # noqa: SLF001
                (lease.organization_id, lease.publication_id)
            )
            if fresh_entry is None:
                return None
            if (
                fresh_entry.status is not DeltaPublicationStatusV1.PENDING
                or _entry_snapshot(fresh_entry) != pre_snapshot
                or fresh_entry.lease_generation != lease.lease_generation
                or fresh_entry.lease_holder_principal_id != worker_principal.principal_id
                or fresh_entry.lease_holder_instance_id != worker_instance_id
                or fresh_entry.lease_expires_at is None
                or not fresh < fresh_entry.lease_expires_at <= fresh_entry.expires_at
            ):
                return None
            if worker_principal.organization_id != fresh_entry.organization_id or (
                not store._caller_scope_allows(  # noqa: SLF001
                    worker_principal, fresh_entry.site_id, fresh_entry.work_area_id
                )
            ):
                return None
            fresh_material = material_resolver.resolve_current_material(
                organization_id=fresh_entry.organization_id,
                site_id=fresh_entry.site_id,
                work_area_id=fresh_entry.work_area_id,
                source_calculation_identity_digest=(fresh_entry.source_calculation_identity_digest),
                source_numeric_result_identity_digest=(
                    fresh_entry.source_numeric_result_identity_digest
                ),
                source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
                now=fresh,
            )
            if fresh_material is None:
                return None
            fresh_identity = getattr(fresh_material, "masked_calculation_identity", None)
            fresh_report = getattr(fresh_material, "report", None)
            if (
                fresh_identity is None
                or fresh_report is None
                or fresh_identity != masked_identity
                or fresh_report != report
            ):
                return None
            fresh_source: DeltaSourceWitness | None = material_resolver.resolve_current_source(
                organization_id=fresh_entry.organization_id,
                site_id=fresh_entry.site_id,
                work_area_id=fresh_entry.work_area_id,
                source_calculation_identity_digest=(fresh_entry.source_calculation_identity_digest),
                source_numeric_result_identity_digest=(
                    fresh_entry.source_numeric_result_identity_digest
                ),
                source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
                now=fresh,
            )
            if fresh_source is None or not store._witness_matches_entry(  # noqa: SLF001
                fresh_source, fresh_entry
            ):
                return None
            if not store._authority_is_current(  # noqa: SLF001
                fresh,
                fresh_entry.policy_digest,
                worker_principal_id=worker_principal.principal_id,
                publication_id=fresh_entry.publication_id,
                lease_generation=fresh_entry.lease_generation,
            ):
                return None
            if not all(
                _is_utc(capability.expires_at)
                and fresh < capability.expires_at <= fresh_entry.lease_expires_at
                and capability.expires_at <= fresh_entry.expires_at
                for capability in capabilities
            ):
                return None
            if not fresh < mask_expires_at <= fresh_entry.lease_expires_at:
                return None
        binding = fresh_identity.mask_binding
        return DeltaPublicationMaskedWorkerInputV1(
            publication_id=fresh_entry.publication_id,
            organization_id=fresh_entry.organization_id,
            site_id=fresh_entry.site_id,
            work_area_id=fresh_entry.work_area_id,
            source_calculation_identity_digest=fresh_entry.source_calculation_identity_digest,
            source_numeric_result_identity_digest=(
                fresh_entry.source_numeric_result_identity_digest
            ),
            source_coverage_witness_digest=fresh_entry.source_coverage_witness_digest,
            worker_principal_id=worker_principal.principal_id,
            worker_instance_id=worker_instance_id,
            lease_generation=fresh_entry.lease_generation,
            lease_expires_at=fresh_entry.lease_expires_at,
            publication_expires_at=fresh_entry.expires_at,
            grid_rows=fresh_entry.grid_rows,
            grid_columns=fresh_entry.grid_columns,
            transform=fresh_entry.transform,
            transform_digest=fresh_entry.transform_digest,
            grid_crs_identifier=fresh_entry.grid_crs_identifier,
            grid_crs_digest=fresh_entry.grid_crs_digest,
            bounds=fresh_entry.bounds,
            masked_calculation_identity=fresh_identity,
            report=fresh_report,
            inputs=(
                capabilities[0],
                capabilities[1],
                DeltaPublicationMaskInputCapabilityV1(
                    artifact_id=binding.mask_artifact_id,
                    observed_sha256=binding.observed_sha256,
                    observed_size_bytes=binding.observed_size_bytes,
                    download_url=_mask_download_url(
                        base_origin=mask_origin,
                        publication_id=fresh_entry.publication_id,
                        worker_instance_id=worker_instance_id,
                        lease_generation=fresh_entry.lease_generation,
                    ),
                    expires_at=mask_expires_at,
                ),
            ),
        )
    except Exception:
        return None


def build_external_delta_publication_masked_input_router(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: DeltaPublicationMaskedMaterialResolver,
    capability_issuer: DeltaPublicationS3InputCapabilityIssuer,
    mask_base_url: str,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the opt-in V3 worker input router; the parent mounts it explicitly.

    ``GET /v1/internal/delta-publication-uploads/{publication_id}/masked-input``
    requires the ANALYSIS_WORKER bearer, the ``worker_instance_id`` query
    naming the live lease holder, and current masked source/policy/runtime.
    The response is the exact ``DeltaPublicationMaskedWorkerInputV1`` wire
    shape; the mask capability carries a server-minted URL rooted at the
    explicit ``mask_base_url`` Core origin, and Core never logs or journals
    capability URLs. Mask bytes themselves travel only the dedicated
    lease-scoped mask route (see ``external_delta_mask_inputs``).
    """
    if not isinstance(store, ExternalDeltaPublicationStore):
        raise ValueError("publication input router requires the concrete publication store")
    if not callable(getattr(material_resolver, "resolve_current_material", None)):
        raise ValueError("publication input router requires a masked material resolver")
    if not isinstance(capability_issuer, DeltaPublicationS3InputCapabilityIssuer):
        raise ValueError("publication input router requires the publication capability issuer")
    try:
        _mask_base_origin(mask_base_url)
    except ValueError as exc:
        raise ValueError(
            f"publication input router requires an explicit mask origin: {exc}"
        ) from exc
    if not isinstance(store, ExternalDeltaPublicationStore):
        raise ValueError("publication input router requires the concrete publication store")
    if not callable(getattr(material_resolver, "resolve_current_material", None)):
        raise ValueError("publication input router requires a masked material resolver")
    if not isinstance(capability_issuer, DeltaPublicationS3InputCapabilityIssuer):
        raise ValueError("publication input router requires the publication capability issuer")
    now_fn = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-delta-publication-input"])
    worker = require_permission(Permission.ANALYSIS_WORK)

    def worker_only(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="DELTA_WORKER_REQUIRED")

    @router.get(
        "/v1/internal/delta-publication-uploads/{publication_id}/masked-input",
        response_model=dict,
    )
    async def masked_worker_input(
        publication_id: str,
        worker_instance_id: str = Query(min_length=1, max_length=255),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict:
        worker_only(principal)
        trusted = now_fn()
        result = await run_in_threadpool(
            resolve_publication_masked_worker_input,
            store=store,
            material_resolver=material_resolver,
            capability_issuer=capability_issuer,
            mask_base_url=mask_base_url,
            publication_id=publication_id,
            worker_principal=principal,
            worker_instance_id=worker_instance_id,
            now=trusted,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return {"input": result.model_dump(by_alias=True, mode="json")}

    return router


__all__ = [
    "DeltaPublicationMaskedMaterialResolver",
    "DeltaPublicationMaterialResolver",
    "DeltaPublicationReconstructionLike",
    "DeltaPublicationS3InputCapabilityIssuer",
    "DeltaPublicationStorageLike",
    "build_external_delta_publication_input_router",
    "build_external_delta_publication_masked_input_router",
    "resolve_publication_masked_worker_input",
    "resolve_publication_worker_input",
]

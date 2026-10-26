"""Lease-scoped Core mask-byte route backing the V3 third capability.

Unmounted by default: the parent quant-graph API lead mounts the factory
below after wiring the real masked source adapter plus the real mask
manifest/byte stores. No V2 contract, route, or worker transport is changed.

What this seam does, read carefully:

- It serves the exact sealed mask bytes bound to ONE live publication lease:
  the worker fetches ``GET
  /v1/internal/delta-publication-uploads/{publicationId}/mask-bytes``
  with its bearer plus the opaque ``worker_instance_id``/``lease_generation``
  query, and receives the bounded raw octet stream. No path, object key, or
  capability string is ever minted or accepted: the server resolves the mask
  child bidirectionally from the sealed mask binding (artifact plus SHA via
  the genuine mask manifest index), reads bounded windows through the byte
  store's own ``read_slice`` primitive (same-fd full proof hash under the
  store guard, pinned root, private uid), and verifies the running hash and
  size against the sealed binding before returning anything.
- Only a live PENDING publication lease authorizes the read, and the DELTA
  publication policy/runtime authority is re-proved — not merely the masked
  execution authority that admitted the original calculation. The check runs
  before the stream (holder, instance, generation, scope, expiry, PENDING
  state, current masked source with a witness that matches the entry, and
  worker-tied DELTA policy/runtime currency) and again after it at a fresh
  trusted instant; any drift fails closed with no bytes sent. A completed
  masked execution attempt is never required, consumed, or re-authorized
  here: the publication lease alone fences the re-measurement, and the old
  COMPLETED masked report stays immutable.
- Mask bytes are never resampled, reinterpreted, or trusted from caller
  claims: reads are bounded by an explicit configured byte cap on top of the
  sealed size, the worker hash/size-verifies the body against the sealed
  binding and runs the strict uint8 single-band NO_NODATA decode before
  measuring.

Scoped interfaces: the factory takes the concrete masked source adapter plus
the concrete mask manifest/byte stores (only narrow methods are used: child
resolution, scoped full-hash window reads, lease/source/authority truth).
The parent owns composition, mounting, allowlists, MCP/UI, and any further
hardening. The byte reads go through the store-owned ``read_slice``
primitive (same-fd full proof hash under the store guard); this module
vendors no reopen path.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    ExternalMaskInputStore,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaPublicationStatusV1,
    ExternalDeltaPublicationStore,
)
from ksi_core.domains.external.quantity.external_masked_delta_source_adapter import (
    CoreMaskedDeltaSourceAdapter,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
)

_MASK_READ_CHUNK_BYTES = 262144
_MASK_SOURCE_CONTRACT_VERSION = "external-masked-volume-calculation-identity.v3"


def _is_utc(value: datetime) -> bool:
    from datetime import timedelta

    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _require_positive_int(value: object, description: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{description} must be a positive integer")
    return value


def _entry_fingerprint(entry: Any) -> tuple[Any, ...]:
    """Immutable entry facts the before/after freshness guard requires unchanged."""
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


def _mask_child_and_manifest(
    *,
    manifests: ExternalMaskInputStore,
    organization_id: str,
    site_id: str,
    work_area_id: str,
    mask_artifact_id: str,
    observed_sha256: str,
    observed_size_bytes: int,
) -> tuple[str, Any] | None:
    """Bidirectional manifest resolution: artifact+SHA to child to manifest.

    Returns ``(child_id, manifest)`` only when exactly one child binds the
    sealed artifact identity and the manifest re-binds the same scope and
    bytes. Anything else fails closed.
    """
    child_id = manifests.find_child_by_artifact(
        organization_id=organization_id,
        mask_artifact_id=mask_artifact_id,
        observed_sha256=observed_sha256,
    )
    if not isinstance(child_id, str) or not child_id:
        return None
    manifest = manifests.resolve_manifest_by_child(
        organization_id=organization_id, mask_child_id=child_id
    )
    if manifest is None:
        return None
    if (
        manifest.organization_id != organization_id
        or manifest.site_id != site_id
        or manifest.work_area_id != work_area_id
        or manifest.mask_artifact_id != mask_artifact_id
        or manifest.observed_sha256 != observed_sha256
        or manifest.observed_size_bytes != observed_size_bytes
    ):
        return None
    return child_id, manifest


def _read_verified_mask_bytes(
    *,
    byte_store: ExternalMaskInputByteStore,
    organization_id: str,
    site_id: str,
    mask_child_id: str,
    manifest: Any,
    expected_sha256: str,
    expected_size_bytes: int,
    max_mask_bytes: int,
) -> bytes | None:
    """Stream the sealed mask bytes with running hash/size verification.

    Every window comes from the byte store-owned ``read_slice`` primitive
    (full proof hash on the SAME bound fd under the store guard, pinned
    root, private uid); this module never re-opens a path. Reads are
    additionally bounded by the explicit configured ``max_mask_bytes`` cap,
    and the assembled body must hash and size-match the sealed binding.
    No path leaves Core; the caller only ever sees this body.
    """
    import hashlib

    if (
        type(expected_size_bytes) is not int
        or isinstance(expected_size_bytes, bool)
        or expected_size_bytes <= 0
        or expected_size_bytes > max_mask_bytes
    ):
        return None
    subject_digest = manifest.subject.canonical_digest()
    out = bytearray()
    hasher = hashlib.sha256()
    offset = 0
    while offset < expected_size_bytes:
        try:
            window = byte_store.read_slice(
                organization_id=organization_id,
                site_id=site_id,
                mask_child_id=mask_child_id,
                mask_artifact_id=manifest.mask_artifact_id,
                subject_digest=subject_digest,
                offset=offset,
                length=min(_MASK_READ_CHUNK_BYTES, expected_size_bytes - offset),
            )
        except (ValueError, OSError):
            return None
        if not window:
            return None
        out.extend(window)
        hasher.update(window)
        offset += len(window)
    if len(out) != expected_size_bytes or "sha256:" + hasher.hexdigest() != expected_sha256:
        return None
    return bytes(out)


def resolve_mask_bytes_for_lease(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: CoreMaskedDeltaSourceAdapter,
    mask_manifests: ExternalMaskInputStore,
    mask_bytes: ExternalMaskInputByteStore,
    publication_id: str,
    worker_principal: Principal,
    worker_instance_id: str,
    lease_generation: int,
    max_mask_bytes: int,
    now: datetime,
) -> bytes | None:
    """Serve the sealed mask bytes for one live publication lease, or None.

    Strict current-lease gate before the stream (holder, instance, generation,
    scope, expiry, PENDING state, current masked source with a witness that
    matches the entry, worker-tied DELTA publication policy/runtime currency,
    exact mask-child/manifest/byte binding, explicit byte cap) and a fresh
    recheck of the same gate after it. Any drift fails closed with no bytes
    returned. A revoked DELTA_PUBLICATION_V1 activation denies the read even
    while the masked execution authority that admitted the original
    calculation stays current: mask bytes are fenced by the publication
    authority, never the execution authority.
    """
    if worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER:
        return None
    if not isinstance(worker_instance_id, str) or not worker_instance_id.strip():
        return None
    if type(lease_generation) is not int or lease_generation <= 0:
        return None
    try:
        max_mask_bytes = _require_positive_int(max_mask_bytes, "mask byte cap")
    except ValueError:
        return None
    if not _is_utc(now):
        return None
    lease = store.intent_for_worker(
        publication_id, worker_principal=worker_principal, worker_instance_id=worker_instance_id
    )
    if lease is None:
        return None
    if (
        lease.lease_generation != lease_generation
        or lease.source_contract_version != _MASK_SOURCE_CONTRACT_VERSION
        or lease.lease_expires_at is None
        or not now < lease.lease_expires_at <= lease.expires_at
    ):
        return None
    trusted = store._clock()  # noqa: SLF001 - same-package trusted clock read
    if not _is_utc(trusted):
        return None
    entry = store._entries.get(  # noqa: SLF001
        (lease.organization_id, lease.publication_id)
    )
    if (
        entry is None
        or entry.status is not DeltaPublicationStatusV1.PENDING
        or trusted >= entry.expires_at
    ):
        return None
    pre_snapshot = _entry_fingerprint(entry)
    if not store._lease_issue_checks(  # noqa: SLF001 - same-package authority gate
        entry, worker_principal, lease_generation, trusted
    ):
        return None
    material = material_resolver.resolve_current_material(
        organization_id=entry.organization_id,
        site_id=entry.site_id,
        work_area_id=entry.work_area_id,
        source_calculation_identity_digest=entry.source_calculation_identity_digest,
        source_numeric_result_identity_digest=entry.source_numeric_result_identity_digest,
        source_coverage_witness_digest=entry.source_coverage_witness_digest,
        now=trusted,
    )
    if material is None:
        return None
    masked_identity = getattr(material, "masked_calculation_identity", None)
    report = getattr(material, "report", None)
    if masked_identity is None or report is None:
        return None
    binding = masked_identity.mask_binding
    resolved = _mask_child_and_manifest(
        manifests=mask_manifests,
        organization_id=entry.organization_id,
        site_id=entry.site_id,
        work_area_id=entry.work_area_id,
        mask_artifact_id=binding.mask_artifact_id,
        observed_sha256=binding.observed_sha256,
        observed_size_bytes=binding.observed_size_bytes,
    )
    if resolved is None:
        return None
    child_id, manifest = resolved
    payload = _read_verified_mask_bytes(
        byte_store=mask_bytes,
        organization_id=entry.organization_id,
        site_id=entry.site_id,
        mask_child_id=child_id,
        manifest=manifest,
        expected_sha256=binding.observed_sha256,
        expected_size_bytes=binding.observed_size_bytes,
        max_mask_bytes=max_mask_bytes,
    )
    if payload is None:
        return None
    with store.coordinator.guarded_read(), store._lock:  # noqa: SLF001
        fresh = store._clock()  # noqa: SLF001
        if not _is_utc(fresh):
            return None
        releas = store.intent_for_worker(
            entry.publication_id,
            worker_principal=worker_principal,
            worker_instance_id=worker_instance_id,
        )
        if (
            releas is None
            or releas.lease_generation != lease_generation
            or releas.lease_expires_at is None
            or not fresh < releas.lease_expires_at <= releas.expires_at
        ):
            return None
        fresh_entry = store._entries.get(  # noqa: SLF001
            (entry.organization_id, entry.publication_id)
        )
        if (
            fresh_entry is None
            or fresh_entry.status is not DeltaPublicationStatusV1.PENDING
            or fresh >= fresh_entry.expires_at
            or _entry_fingerprint(fresh_entry) != pre_snapshot
        ):
            return None
        if not store._lease_issue_checks(  # noqa: SLF001 - same-package authority gate
            fresh_entry, worker_principal, lease_generation, fresh
        ):
            return None
        fresh_material = material_resolver.resolve_current_material(
            organization_id=fresh_entry.organization_id,
            site_id=fresh_entry.site_id,
            work_area_id=fresh_entry.work_area_id,
            source_calculation_identity_digest=fresh_entry.source_calculation_identity_digest,
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
        if fresh_identity is None or fresh_report is None:
            return None
        if fresh_identity != masked_identity or fresh_report != report:
            return None
    return payload


def build_external_delta_mask_input_router(
    *,
    store: ExternalDeltaPublicationStore,
    material_resolver: CoreMaskedDeltaSourceAdapter,
    mask_manifests: ExternalMaskInputStore,
    mask_bytes: ExternalMaskInputByteStore,
    max_mask_bytes: int,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the lease-scoped Core mask-byte router; the parent mounts it.

    ``GET /v1/internal/delta-publication-uploads/{publication_id}/mask-bytes``
    requires the ANALYSIS_WORKER bearer plus the opaque ``worker_instance_id``
    and ``lease_generation`` query naming the live lease. Only the lease
    holder of a PENDING V3 intent with a current masked source and current
    DELTA publication policy/runtime receives the bounded raw octet stream;
    everything else sees an indistinguishable 404. ``max_mask_bytes`` is the
    explicit configured envelope cap for a single mask body. The parent
    quant-graph API lead mounts this factory; the response shape
    (raw ``application/octet-stream``) never carries paths, keys, or digests.
    """
    if not isinstance(store, ExternalDeltaPublicationStore):
        raise ValueError("mask input router requires the concrete publication store")
    if not isinstance(material_resolver, CoreMaskedDeltaSourceAdapter):
        raise ValueError("mask input router requires the concrete masked source adapter")
    if not isinstance(mask_manifests, ExternalMaskInputStore):
        raise ValueError("mask input router requires the concrete mask manifest store")
    if not isinstance(mask_bytes, ExternalMaskInputByteStore):
        raise ValueError("mask input router requires the concrete mask byte store")
    try:
        max_mask_bytes = _require_positive_int(max_mask_bytes, "mask byte cap")
    except ValueError as exc:
        raise ValueError(f"mask input router requires an explicit mask byte cap: {exc}") from exc

    now_fn = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-delta-mask-input"])
    worker = require_permission(Permission.ANALYSIS_WORK)

    def worker_only(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="DELTA_WORKER_REQUIRED")

    @router.get(
        "/v1/internal/delta-publication-uploads/{publication_id}/mask-bytes",
    )
    async def mask_bytes_route(
        publication_id: str,
        worker_instance_id: str = Query(min_length=1, max_length=255),
        lease_generation: int = Query(gt=0),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> Response:
        worker_only(principal)
        trusted = now_fn()
        payload = await run_in_threadpool(
            resolve_mask_bytes_for_lease,
            store=store,
            material_resolver=material_resolver,
            mask_manifests=mask_manifests,
            mask_bytes=mask_bytes,
            publication_id=publication_id,
            worker_principal=principal,
            worker_instance_id=worker_instance_id,
            lease_generation=lease_generation,
            max_mask_bytes=max_mask_bytes,
            now=trusted,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return Response(content=payload, media_type="application/octet-stream")

    return router


__all__ = [
    "build_external_delta_mask_input_router",
    "resolve_mask_bytes_for_lease",
]

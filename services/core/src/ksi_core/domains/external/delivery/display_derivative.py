"""Pure display-derivative identity projection over existing bounded jobs.

This module is the smallest honest Core-side use of the display-derivative
identity records: it COMPUTES and VERIFIES the identity for an existing
bounded native-window preparation, bound to the frozen job and sealed receipt
Core already produced. It deliberately does NOT:

- add a public tile endpoint, a cache service, an LOD table, or a new
  preparation mode;
- alter the existing request -> job -> receipt -> file flow (no changes to
  ``jobs.py`` / ``job_projection.py`` / views);
- mutate any durable state: every function here is pure (inputs in, typed
  records out), so existing receipts/jobs and their digests are byte-identical
  before and after;
- introduce a composite ready/status/verified flag or restate validation
  suitability: the only surfaced state is ``DisplaySpatialViewV1``, a
  representation fact.

Three-state separation: audit integrity, per-purpose suitability, and spatial
viewability stay distinct. These helpers read the SOURCE identity and the
receipt geometry; they never join inspection/checkpoint/use-decision outcomes.
"""

from __future__ import annotations

from ksi_event_contracts._spatial_data import Digest
from ksi_event_contracts.spatial_data import (
    SpatialDataFrozenJobV1,
    SpatialDataReceiptV1,
)
from ksi_event_contracts.spatial_data_display import (
    DisplayDerivativeBindingV1,
    DisplayDerivativeSourceV1,
    DisplayDerivativeV1,
    DisplayDerivativeWindowV1,
    DisplayLodV1,
    DisplayPermissionV1,
    DisplayProvenanceV1,
    DisplayRegistration,
    DisplaySpatialViewV1,
    DisplayStyleV1,
    DisplayValidityV1,
    PairRegistrationStatusV1,
    PairRegistrationV1,
)


def _require_sealed_job_and_receipt(
    job: SpatialDataFrozenJobV1, receipt: SpatialDataReceiptV1
) -> None:
    for snapshot in (job, receipt, job.source, job.grant, job.policy, job.runtime):
        if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
            raise ValueError("display projection requires sealed job/receipt snapshots")
    if (
        receipt.job_id != job.job_id
        or receipt.job_digest != job.job_digest
        or receipt.source_digest != job.source.source_digest
        or receipt.grant_digest != job.grant.grant_digest
        or receipt.policy_digest != job.policy.policy_digest
        or receipt.runtime_digest != job.runtime.runtime_digest
    ):
        raise ValueError("receipt does not bind this exact frozen job")


def _require_optional_digest(name: str, value: str | None) -> Digest:
    if value is None:
        raise ValueError(f"frozen {name} must be sealed before display projection")
    return value


def project_display_derivative(
    *,
    job: SpatialDataFrozenJobV1,
    receipt: SpatialDataReceiptV1,
    lod: DisplayLodV1,
    style: DisplayStyleV1,
    validity: DisplayValidityV1,
    registration: DisplayRegistration,
    prepared_for_principal_hash: Digest,
) -> DisplayDerivativeV1:
    """Compute the sealed derivative identity for an existing preparation.

    SOURCE/window/permission/provenance pins are COPIED from the frozen job
    and sealed receipt (never re-derived or re-rounded); only the display
    pins (lod/style/validity/registration/principal-hash) are caller inputs.
    The SOURCE identity referenced by an existing analysis result is
    provably unaffected: this function returns a NEW record and mutates
    neither the job, the source, nor the receipt.
    """
    _require_sealed_job_and_receipt(job, receipt)
    measurements = job.source.inspection.measurements
    if measurements is None:
        raise ValueError("frozen source must have measured raster facts")
    source = DisplayDerivativeSourceV1(
        asset_ref=job.source.asset_ref,
        observed_sha256=job.source.observed_sha256,
        observed_crs_digest=measurements.observed_crs_digest,
        revision=job.source.revision,
        inspection_report_digest=job.source.inspection_report_digest,
    )
    window = DisplayDerivativeWindowV1(
        pixel_window=receipt.pixel_window,
        actual_bounds=receipt.actual_bounds,
        grid_transform=receipt.transform,
    )
    permission = DisplayPermissionV1(
        grant_digest=_require_optional_digest("grant", job.grant.grant_digest),
        policy_digest=_require_optional_digest("policy", job.policy.policy_digest),
        purpose=job.request.purpose,
        prepared_for_principal_hash=prepared_for_principal_hash,
    )
    provenance = DisplayProvenanceV1(
        prepare_job_id=job.job_id,
        receipt_digest=_require_optional_digest("receipt", receipt.receipt_digest),
        prepared_at=receipt.prepared_at,
        worker_build_digest=_require_optional_digest("runtime", job.runtime.build_digest),
    )
    return DisplayDerivativeV1(
        source=source,
        window=window,
        lod=lod,
        style=style,
        validity=validity,
        registration=registration,
        permission=permission,
        provenance=provenance,
    ).sealed()


def display_binding_for(
    *,
    derivative: DisplayDerivativeV1,
    job: SpatialDataFrozenJobV1,
    receipt: SpatialDataReceiptV1,
    spatial_view: DisplaySpatialViewV1,
) -> DisplayDerivativeBindingV1:
    """Project the typed Core-side facts for one sealed derivative.

    Re-verifies that the derivative's SOURCE/window/permission/provenance
    pins still match the exact frozen job and sealed receipt before emitting
    the binding, so a derivative can never drift off its preparation.
    ``spatial_view`` is a representation fact only.
    """
    _require_sealed_job_and_receipt(job, receipt)
    if derivative.derivative_id != derivative.canonical_digest():
        raise ValueError("derivative must be sealed before binding")
    source_digest = _require_optional_digest("source", job.source.source_digest)
    measurements = job.source.inspection.measurements
    if measurements is None:
        raise ValueError("frozen source must have measured raster facts")
    expected_source = DisplayDerivativeSourceV1(
        asset_ref=job.source.asset_ref,
        observed_sha256=job.source.observed_sha256,
        observed_crs_digest=measurements.observed_crs_digest,
        revision=job.source.revision,
        inspection_report_digest=job.source.inspection_report_digest,
    )
    if (
        derivative.source != expected_source
        or derivative.window.pixel_window != receipt.pixel_window
        or derivative.window.actual_bounds != receipt.actual_bounds
        or derivative.window.grid_transform != receipt.transform
        or derivative.permission.grant_digest != job.grant.grant_digest
        or derivative.permission.policy_digest != job.policy.policy_digest
        or derivative.permission.purpose != job.request.purpose
        or derivative.provenance.prepare_job_id != job.job_id
        or derivative.provenance.receipt_digest != receipt.receipt_digest
        or derivative.provenance.prepared_at != receipt.prepared_at
    ):
        raise ValueError("derivative pins do not match this exact job and receipt")
    return DisplayDerivativeBindingV1(
        derivative_id=derivative.derivative_id,
        source_digest=source_digest,
        prepare_job_id=job.job_id,
        receipt_digest=derivative.provenance.receipt_digest,
        spatial_view=spatial_view,
    )


def pair_is_registered(registration: DisplayRegistration) -> bool:
    """True ONLY for an evidence-backed REGISTERED record.

    Equal CRS is never consulted here: two epochs sharing an observed CRS
    digest with NONE (or UNREGISTERED) registration are NOT registered.
    Construction-time validators already guarantee a REGISTERED record
    carries non-empty evidence digests.
    """
    return (
        isinstance(registration, PairRegistrationV1)
        and registration.status is PairRegistrationStatusV1.REGISTERED
    )

"""Public Floreat-f3 DSM pair: local read-only admission baseline (SDP-20260930).

What this pair is
-----------------
Two public digital-surface-model GeoTIFFs of Floreat (Perth, Western Australia),
published by Cambridge Coastcare and obtained via DataWA, used here under
CC BY 4.0 with attribution: Cambridge Coastcare, Floreat-f3, 17 Aug 2021 and
24 Aug 2022.  Epoch A (2021, 10 cm grid) and epoch B (2022, 5 cm grid) form the
public two-epoch DSM pair behind the "long-term contract / development order"
decision baseline.

Evidence boundary
-----------------
This module is LOCAL software proof on public bytes only: it runs the real
product inspector over the real files and pins the real Core admission refusal
for such bytes.  It is NOT customer acceptance, NOT field acceptance, NOT
Terra-compatibility acceptance, and NOT quantitative/settlement accuracy
acceptance.  A passing numeric result for these bytes would be the defect,
not the goal: both files carry no observed vertical reference, so the
relative-volume analysis must refuse to resolve them.

Fixture handling
----------------
The files live as untracked read-only fixtures under
``.dev-data/public-geotiff/floreat-f3-2021-08-17_2022-08-24/`` and must NEVER
be committed.  Nothing in this module writes to that directory, retags or
reprojects the bytes, or adds a vertical CRS to make anything pass.  When the
directory is absent the tests SKIP with a clear reason: a clean clone still
passes, and nothing is ever downloaded.

Envelope note
-------------
The pinned 1 MB / ~1 Mpx test envelope cannot measure these files (up to
~181 MB and ~45 Mpx), so this local check uses a generous read-only
ResourceEnvelopeV1 -- the same envelope-renewal precedent as the 2026-10-14
public-sample acceptance.  The envelope only widens local decode caps; it
changes no product rule.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    ExternalRelativeVolumeAnalysisStore,
    _PreflightBlocked,
)
from ksi_core.domains.sites.work_areas import WorkAreaStatus
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_geotiff_inspector import (
    inspect_synthetic_sealed_geotiff,
)

_PAIR_DIR = (
    Path(__file__).resolve().parents[2]
    / ".dev-data/public-geotiff/floreat-f3-2021-08-17_2022-08-24"
)

# Recorded read-only facts for the public pair (sizes in bytes, sha256 of bytes).
_EPOCH_A: dict[str, Any] = {
    "name": "floreat-f3-2021_10cm-dsm.tif",
    "size_bytes": 61_735_807,
    "sha256": "170f98edac9869b768788132569df1c274082d967e21e9d2a6255f9cd12b9c5b",
    "width": 2755,
    "height": 5596,
}
_EPOCH_B: dict[str, Any] = {
    "name": "floreat-f3_2022_dsm.tif",
    "size_bytes": 181_144_647,
    "sha256": "bfc5f43ebf576e6400046f5b840663879a38224880cf5efad4e1157eeb2edfb1",
    "width": 5202,
    "height": 8703,
}
_EPOCHS: tuple[dict[str, Any], ...] = (_EPOCH_A, _EPOCH_B)

_EXPECTED_CRS = "EPSG:7850"
_EXPECTED_DTYPE = "float32"
_EXPECTED_NODATA = -10000.0


def _generous_envelope() -> ResourceEnvelopeV1:
    """Read-only decode caps sized for the public pair (largest: ~181 MB, ~45 Mpx)."""
    return ResourceEnvelopeV1(
        max_input_bytes=512_000_000,
        max_streamed_bytes=512_000_000,
        max_tiff_directories=16,
        max_tiff_entries=1024,
        max_pixels=64_000_000,
        max_bands=4,
        max_blocks=100_000,
        max_decompressed_bytes=2_000_000_000,
        max_sample_bytes=2_000_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=600.0,
        max_memory_bytes=8_000_000_000,
        max_workspace_bytes=8_000_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=600.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()


def _require_pair_dir() -> Path:
    if not _PAIR_DIR.is_dir():
        pytest.skip(
            "optional public fixture absent: "
            ".dev-data/public-geotiff/floreat-f3-2021-08-17_2022-08-24/ "
            "(never downloaded by tests)"
        )
    return _PAIR_DIR


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_public_epoch(spec: dict[str, Any], pair_dir: Path) -> ArtifactInspectionOutcomeV1:
    """Run the REAL product inspector over one public file (read-only)."""
    path = pair_dir / str(spec["name"])
    assert path.is_file(), f"public fixture missing: {path}"
    actual_size = path.stat().st_size
    assert actual_size == spec["size_bytes"], (
        f"{spec['name']}: size changed ({actual_size} != {spec['size_bytes']})"
    )
    observed = "sha256:" + _sha256_of(path)
    assert observed == "sha256:" + str(spec["sha256"]), f"{spec['name']}: byte identity changed"
    return inspect_synthetic_sealed_geotiff(
        path=path,
        artifact_id="floreat-public:" + str(spec["name"]),
        observed_sha256=observed,
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=_generous_envelope(),
    )


@pytest.mark.parametrize("spec", _EPOCHS, ids=[_EPOCH_A["name"], _EPOCH_B["name"]])
def test_public_floreat_pair_inspects_measured_without_vertical_reference(
    spec: dict[str, Any],
) -> None:
    """Both public files MEASURE with EPSG:7850 and no observed vertical reference."""
    pair_dir = _require_pair_dir()
    outcome = _inspect_public_epoch(spec, pair_dir)
    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.reason is None
    measurements = outcome.measurements
    assert measurements is not None
    assert measurements.observed_crs_identifier == _EXPECTED_CRS
    assert measurements.observed_vertical_reference is None
    assert (measurements.width, measurements.height) == (spec["width"], spec["height"])
    assert measurements.band_count == 1
    assert measurements.dtype == _EXPECTED_DTYPE
    assert measurements.nodata_value == _EXPECTED_NODATA
    assert measurements.valid_pixel_count > 0


def _stub_analysis_store(
    outcomes: dict[str, ArtifactInspectionOutcomeV1],
) -> Any:
    """Bind stub sealed-store lookups around the REAL admission gate code.

    Only the store boundaries (reconstruction / inspection / work-area /
    evidence / validation lookups) are stubbed with SimpleNamespace lookups.
    The epoch-resolution refusal and the typed-blocker mapping under test are
    the real ``ExternalRelativeVolumeAnalysisStore`` methods; the inspection
    outcomes fed through them are real bytes-derived measurements from the
    product inspector, not hand-built values.
    """
    organization_id = "org-floreat"
    site_id = "site-floreat"
    revisions: dict[str, Any] = {}
    snapshots: dict[str, Any] = {}
    capture_windows = {
        "baseline": (
            datetime(2021, 8, 17, 0, 0, 0, tzinfo=UTC),
            datetime(2021, 8, 17, 1, 0, 0, tzinfo=UTC),
        ),
        "current": (
            datetime(2022, 8, 24, 0, 0, 0, tzinfo=UTC),
            datetime(2022, 8, 24, 1, 0, 0, tzinfo=UTC),
        ),
    }
    for epoch, spec in (("baseline", _EPOCH_A), ("current", _EPOCH_B)):
        outcome = outcomes[str(spec["name"])]
        assert outcome.measurements is not None
        subject = SimpleNamespace(organization_id=organization_id, site_id=site_id)
        entry = SimpleNamespace(
            kind=ProcessingArtifactKind.DSM,
            artifact_id=outcome.artifact_id,
            observed_sha256=outcome.observed_sha256.removeprefix("sha256:"),
            observed_size_bytes=spec["size_bytes"],
        )
        started_at, ended_at = capture_windows[epoch]
        revisions[epoch] = SimpleNamespace(
            subject=subject,
            manifest=SimpleNamespace(entries=[entry]),
            submission=SimpleNamespace(
                input_declaration=SimpleNamespace(
                    capture_started_at=started_at,
                    capture_ended_at=ended_at,
                )
            ),
        )
        snapshots[epoch] = SimpleNamespace(
            report=SimpleNamespace(
                report_digest="sha256:" + "0" * 64,
                measurement_payload=SimpleNamespace(outcomes=[outcome]),
            )
        )
    store: Any = ExternalRelativeVolumeAnalysisStore.__new__(ExternalRelativeVolumeAnalysisStore)
    store._reconstruction = SimpleNamespace(
        resolve_sealed_subject=lambda subject: revisions[subject.epoch]
    )
    store._inspections = SimpleNamespace(public_snapshot=lambda subject: snapshots[subject.epoch])
    store._work_areas = SimpleNamespace(
        get=lambda work_area_id: SimpleNamespace(status=WorkAreaStatus.ACTIVE, site_id=site_id)
    )
    store._evidence = SimpleNamespace(list=lambda revision: [])
    store._validations = SimpleNamespace(
        analysis_facts_for_subject_dsm=lambda **kwargs: [],
        analysis_fact_currentness=lambda facts, now: [],
        analysis_validation_lifecycles_for_subject_dsm=lambda **kwargs: [],
        analysis_validation_lifecycles_are_locally_current=lambda lifecycles: True,
    )
    return store


def test_public_floreat_epochs_refuse_relative_volume_resolution() -> None:
    """MEASURED-but-vertical-less public epochs are unusable: ESSENTIAL_INPUT_UNAVAILABLE.

    Drives the real product path -- ``_resolve_epoch`` returns None for both
    real public outcomes (the ``observed_vertical_reference is None`` gate),
    and the real ``_prepare_resolved`` maps that to the typed blocker.  No
    numeric result exists for these bytes, and that refusal is the pinned
    behaviour (a passing numeric result would be the defect, not the goal).
    """
    pair_dir = _require_pair_dir()
    outcomes = {str(spec["name"]): _inspect_public_epoch(spec, pair_dir) for spec in _EPOCHS}
    store = _stub_analysis_store(outcomes)
    now = datetime.now(UTC)
    selections = {
        epoch: SimpleNamespace(
            subject=SimpleNamespace(
                epoch=epoch,
                organization_id="org-floreat",
                site_id="site-floreat",
            )
        )
        for epoch in ("baseline", "current")
    }
    for epoch, selection in selections.items():
        assert store._resolve_epoch(selection, now=now, epoch=epoch) is None, (
            f"{epoch}: public epoch without a vertical reference must not resolve"
        )
    request = SimpleNamespace(
        request_id="req-floreat-public",
        work_area_id="wa-floreat",
        baseline=selections["baseline"],
        current=selections["current"],
    )
    with pytest.raises(_PreflightBlocked) as excinfo:
        store._prepare_resolved(organization_id="org-floreat", request=request, now=now)
    assert excinfo.value.reason == "ESSENTIAL_INPUT_UNAVAILABLE"


def test_public_floreat_bytes_unchanged_after_inspection() -> None:
    """The no-fabrication guard: inspection left both public files byte-identical."""
    pair_dir = _require_pair_dir()
    for spec in _EPOCHS:
        path = pair_dir / str(spec["name"])
        assert path.is_file(), f"public fixture missing: {path}"
        assert _sha256_of(path) == spec["sha256"], (
            f"{spec['name']}: public bytes changed; fixtures must stay read-only"
        )
        assert path.stat().st_size == spec["size_bytes"]

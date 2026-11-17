"""표면 단면 작업 계약 — 동결 입력의 결속, 정책의 유한성, 실패·완료 요청의 모양.

합성 값만 쓴다. 이 시험은 계약 모양의 증거이지 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts import surface_profile, surface_profile_job
from ksi_event_contracts.surface_profile_job import (
    CreateSurfaceProfileJobV1,
    SurfaceProfileCompleteRequestV1,
    SurfaceProfileFailureRequestV1,
    SurfaceProfileFrozenJobV1,
    SurfaceProfileJobViewV1,
    SurfaceProfileReadWindowV1,
    SurfaceProfileVerticalReferenceV1,
)
from pydantic import ValidationError
from spatial_data_fixture import ASSET, DIGEST, NOW, make_grant, make_policy
from surface_profile_job_fixture import (
    AREA,
    ORG,
    SITE,
    FakeAuthority,
    declared_vertical,
    feature_revision,
    genuine_answer,
    issue_request,
    line,
    measured_source,
    observed_vertical,
    profile_policy,
    profile_runtime,
    receipt_for,
    write_raster,
)

ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "spj-" + "0" * 32


def _job(**overrides: Any) -> SurfaceProfileFrozenJobV1:
    feature = feature_revision()
    request = issue_request()
    source = overrides.pop("source", None) or measured_source()
    vertical = overrides.pop("vertical_reference", None) or observed_vertical(source)
    from ksi_event_contracts.surface_profile import CreateSurfaceProfileV1

    payload: dict[str, Any] = dict(
        job_id=JOB_ID,
        organization_id=ORG,
        requester_principal_id="reader-local",
        site_id=SITE,
        work_area_id=AREA,
        request=request,
        feature=feature,
        profile_request=CreateSurfaceProfileV1(
            asset_ref=ASSET, line=feature.line, feature=feature.ref()
        ),
        source=source,
        grant=FakeAuthority(coordinator=None).grant,  # type: ignore[arg-type]
        data_policy_digest=make_policy().policy_digest,
        height_decision_digest=DIGEST,
        vertical_reference=vertical,
        policy=profile_policy(),
        runtime=profile_runtime(),
        read_window=SurfaceProfileReadWindowV1(
            pixel_window=(2, 13, 3, 10),
            actual_bounds=(200_002.0, 499_990.0, 200_013.0, 499_997.0),
        ),
        idempotency_key_hash=DIGEST,
        request_fingerprint=request.canonical_digest(),
        created_at=NOW,
        deadline=NOW + timedelta(seconds=30),
    )
    payload.update(overrides)
    return SurfaceProfileFrozenJobV1(**payload).sealed()


def test_a_well_formed_frozen_job_is_sealed_and_bound() -> None:
    job = _job()
    assert job.job_digest == job.canonical_digest()
    assert _job(read_window=None).read_window is None  # 전부 표면 밖이면 읽을 창이 없다


@pytest.mark.parametrize(
    "change",
    [
        dict(job_id="spj-short"),
        dict(job_id="sdj-v1-00000000-0000-4000-8000-000000000001"),
        dict(site_id="another-site"),
        dict(work_area_id="another-area"),
        dict(organization_id="org-other"),
        dict(requester_principal_id="someone-else"),
        dict(data_policy_digest="sha256:" + "5" * 64),
        dict(request_fingerprint="sha256:" + "5" * 64),
        dict(deadline=NOW + timedelta(seconds=3600)),
        dict(deadline=NOW),
        dict(created_at=NOW + timedelta(days=2), deadline=NOW + timedelta(days=2, seconds=30)),
    ],
)
def test_a_frozen_job_refuses_scope_policy_and_time_that_do_not_bind(
    change: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _job(**change)


def test_the_request_the_line_and_the_asset_must_all_agree() -> None:
    other_feature = feature_revision(line((1.0, 1.0), (5.0, 5.0)), revision=2)
    base = issue_request()
    with pytest.raises(ValidationError, match="saved line revision"):
        _job(request=issue_request(feature=other_feature.ref()))
    with pytest.raises(ValidationError, match="same exact asset"):
        _job(request=issue_request(asset_ref="ksa-v1-" + "9" * 64))
    from ksi_event_contracts.surface_profile import CreateSurfaceProfileV1

    moved = line((1.0, 1.0), (5.0, 5.0))
    with pytest.raises(ValidationError):
        _job(
            profile_request=CreateSurfaceProfileV1(
                asset_ref=ASSET, line=moved, feature=feature_revision().ref()
            )
        )
    with pytest.raises(ValidationError, match="spacing"):
        _job(
            profile_request=CreateSurfaceProfileV1(
                asset_ref=ASSET,
                line=feature_revision().line,
                feature=feature_revision().ref(),
                sample_spacing_m=2.0,
            )
        )
    assert base.sample_spacing_m is None


@pytest.mark.parametrize(
    "grant_change",
    [
        dict(operations=("PREPARE",)),
        dict(operations=("READ",)),
        dict(purposes=("EXTERNAL_AI",)),
        dict(
            valid_from=NOW - timedelta(hours=2), valid_until=NOW - timedelta(hours=1)
        ),  # 이미 만료
        dict(observed_crs_digest="sha256:" + "6" * 64),
        dict(allowed_bounds=(200_000.0, 499_980.0, 200_005.0, 500_000.0)),  # 읽기 창보다 좁다
    ],
)
def test_a_frozen_job_needs_a_grant_that_actually_covers_the_read(
    grant_change: dict[str, Any],
) -> None:
    base = FakeAuthority(coordinator=None).grant  # type: ignore[arg-type]
    grant = make_grant(
        **{
            "allowed_bounds": base.allowed_bounds,
            "observed_crs_digest": DIGEST,
            "valid_until": base.valid_until,
            **grant_change,
        }
    )
    with pytest.raises(ValidationError):
        _job(grant=grant)


def test_a_surface_profile_reads_a_dsm_and_never_an_ortho() -> None:
    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ArtifactOutcome,
    )
    from spatial_data_fixture import make_measurements, make_source

    ortho = make_source(
        artifact_kind="ortho",
        inspection=ArtifactInspectionOutcomeV1(
            artifact_id="artifact-local",
            observed_sha256=DIGEST,
            outcome=ArtifactOutcome.MEASURED,
            measurements=make_measurements(dtype="uint8", band_count=3),
        ),
    )
    with pytest.raises(ValidationError, match="DSM"):
        _job(
            source=ortho,
            vertical_reference=SurfaceProfileVerticalReferenceV1(
                provenance="DECLARED", declared=declared_vertical()
            ),
        )


def test_the_saved_line_must_belong_to_the_jobs_work_area() -> None:
    from ksi_event_contracts.measurement_feature import MeasurementFeatureRevisionV1

    saved = feature_revision().line
    foreign = MeasurementFeatureRevisionV1(
        feature_id=feature_revision().feature_id,
        site_id=SITE,
        work_area_id="another-area",
        revision=1,
        name="n",
        line=saved,
        line_digest=saved.digest(),
        created_at=NOW,
    ).sealed()
    with pytest.raises(ValidationError, match="work area"):
        _job(feature=foreign)


def test_the_read_window_must_fit_the_policy_and_have_extent() -> None:
    with pytest.raises(ValidationError, match="positive extent"):
        SurfaceProfileReadWindowV1(pixel_window=(3, 3, 1, 5), actual_bounds=(0.0, 0.0, 1.0, 1.0))
    with pytest.raises(ValidationError, match="policy limit"):
        _job(policy=profile_policy(maximum_window_cells=10))


@pytest.mark.parametrize(
    "change",
    [
        dict(maximum_window_cells=10**9),
        dict(maximum_source_block_cells=10**9),
        dict(maximum_vertices=65),
        dict(max_result_bytes=10**9),
        dict(lease_seconds=500.0),
        dict(deadline_seconds=1000.0),
        dict(max_attempts=99),
        dict(max_active_jobs_per_organization=99),
        dict(max_pending_records=99),
        dict(min_retry_backoff_seconds=10.0, max_retry_backoff_seconds=1.0),
        dict(maximum_samples=10_000),
        dict(maximum_line_length_m=float("inf")),
        dict(maximum_line_length_m=0.0),
    ],
)
def test_the_policy_is_finite_and_fits_its_envelope(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        profile_policy(**change)


def test_a_retry_is_only_for_storage_and_transport_trouble() -> None:
    from ksi_event_contracts.surface_profile_job import SurfaceProfileAttemptV1

    attempt = SurfaceProfileAttemptV1(
        job_id=JOB_ID,
        frozen_job_digest=DIGEST,
        attempt_number=1,
        fence=1,
        worker_principal_id="w",
        worker_instance_id="i",
        acquisition_key_hash=DIGEST,
        acquired_at=NOW,
        lease_until=NOW + timedelta(seconds=5),
    ).sealed()
    SurfaceProfileFailureRequestV1(attempt=attempt, reason="STORAGE_UNAVAILABLE", retryable=True)
    SurfaceProfileFailureRequestV1(attempt=attempt, reason="WINDOW_TOO_LARGE", retryable=False)
    with pytest.raises(ValidationError):
        SurfaceProfileFailureRequestV1(
            attempt=attempt, reason="STORAGE_UNAVAILABLE", retryable=False
        )
    with pytest.raises(ValidationError):
        SurfaceProfileFailureRequestV1(attempt=attempt, reason="WINDOW_TOO_LARGE", retryable=True)
    with pytest.raises(ValidationError):
        SurfaceProfileFailureRequestV1(attempt=attempt, reason="/etc/passwd", retryable=False)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SurfaceProfileAttemptV1(
            job_id=JOB_ID,
            frozen_job_digest=DIGEST,
            attempt_number=1,
            fence=1,
            worker_principal_id="w",
            worker_instance_id="i",
            acquisition_key_hash=DIGEST,
            acquired_at=NOW,
            lease_until=NOW,
        )


def test_a_completion_request_binds_the_result_to_its_receipt(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.surface_profile_jobs import SurfaceProfileJobStore
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_event_contracts.surface_profile_job import SurfaceProfileLeaseRequestV1
    from surface_profile_job_fixture import issue_request as make_request
    from surface_profile_job_fixture import requester, worker

    coordinator = ExternalAuthorityCurrentnessCoordinator()
    store = SurfaceProfileJobStore(
        DurableJournal(tmp_path / "j.jsonl"),
        authority=FakeAuthority(coordinator=coordinator),
        policy=profile_policy(),
        runtime=profile_runtime(),
        coordinator=coordinator,
    )
    job_id = store.issue(
        site_id=SITE,
        work_area_id=AREA,
        request=make_request(),
        principal=requester(),
        idempotency_key="k",
        now=NOW,
    ).job_id
    attempt = store.lease(
        job_id=job_id,
        worker=worker(),
        request=SurfaceProfileLeaseRequestV1(worker_instance_id="instance-1", acquisition_id="a"),
        now=NOW + timedelta(seconds=1),
    )
    job = store.worker_input(
        job_id=job_id, worker=worker(), attempt=attempt, now=NOW + timedelta(seconds=1)
    )
    result, receipt = genuine_answer(
        job, write_raster(tmp_path / "d.tif"), NOW + timedelta(seconds=2)
    )

    SurfaceProfileCompleteRequestV1(attempt=attempt, result=result, receipt=receipt)
    other = receipt_for(job, result, NOW + timedelta(seconds=2), result_digest=DIGEST)
    with pytest.raises(ValidationError):
        SurfaceProfileCompleteRequestV1(attempt=attempt, result=result, receipt=other)
    unsealed = result.model_copy(update={"result_digest": None})
    with pytest.raises(ValidationError):
        SurfaceProfileCompleteRequestV1(attempt=attempt, result=unsealed, receipt=receipt)


def test_a_job_view_has_a_receipt_only_when_completed() -> None:
    base: dict[str, Any] = dict(
        job_id=JOB_ID,
        asset_ref=ASSET,
        site_id=SITE,
        work_area_id=AREA,
        feature=feature_revision().ref(),
        created_at=NOW,
        execution_state="QUEUED",
        availability="NOT_READY",
    )
    assert SurfaceProfileJobViewV1(**base).receipt is None
    with pytest.raises(ValidationError):
        SurfaceProfileJobViewV1(
            **{**base, "execution_state": "COMPLETED", "availability": "AVAILABLE"}
        )


def test_the_request_body_carries_no_line_path_or_url() -> None:
    assert set(CreateSurfaceProfileJobV1.model_fields) == {
        "asset_ref",
        "feature",
        "height_decision_id",
        "sample_spacing_m",
    }
    with pytest.raises(ValidationError):
        CreateSurfaceProfileJobV1(**{**issue_request().model_dump(), "line": {"crs": "EPSG:5186"}})
    for bad in ("/data/dsm.tif", "https://x/y.tif", "ksa-v1-short"):
        with pytest.raises(ValidationError):
            issue_request(asset_ref=bad)


def test_the_job_reason_vocabulary_contains_every_calculation_refusal() -> None:
    job_reasons = set(get_args(surface_profile_job.SurfaceProfileJobReasonV1))
    assert set(get_args(surface_profile.SurfaceProfileRefusalReasonV1)) <= job_reasons
    assert job_reasons >= surface_profile_job.TRANSIENT_JOB_REASONS


def test_the_published_schema_matches_the_models_and_validates_wire_bodies() -> None:
    spec = importlib.util.spec_from_file_location(
        "generate_surface_profile_schemas", ROOT / "tools/generate_surface_profile_schemas.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    actual = json.loads((ROOT / "contracts/schemas/surface-profile-job.v1.json").read_text())
    assert actual == generator.schema_for("surface_profile_job")
    Draft202012Validator.check_schema(actual)

    def validator(name: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": actual["$defs"]})

    job = _job()
    validator("SurfaceProfileFrozenJobV1").validate(job.model_dump(by_alias=True, mode="json"))
    wire = issue_request().model_dump(by_alias=True, mode="json")
    validator("CreateSurfaceProfileJobV1").validate(wire)
    assert list(validator("CreateSurfaceProfileJobV1").iter_errors({**wire, "line": {}}))


# ── 수직 기준 출처: 파일의 관측값인가, 사용자의 선언인가 ──────────────────────────────


def test_a_vertical_reference_names_exactly_one_provenance() -> None:
    observed = observed_vertical(measured_source())
    assert observed.provenance == "OBSERVED" and observed.declared is None
    declared = SurfaceProfileVerticalReferenceV1(
        provenance="DECLARED", declared=declared_vertical()
    )
    assert declared.observed is None
    with pytest.raises(ValidationError):
        SurfaceProfileVerticalReferenceV1(provenance="OBSERVED")
    with pytest.raises(ValidationError):
        SurfaceProfileVerticalReferenceV1(provenance="DECLARED")
    with pytest.raises(ValidationError):
        SurfaceProfileVerticalReferenceV1(
            provenance="DECLARED", declared=declared_vertical(), observed=observed.observed
        )
    with pytest.raises(ValidationError):
        SurfaceProfileVerticalReferenceV1(
            provenance="OBSERVED", observed=observed.observed, declared=declared_vertical()
        )


def test_a_declared_vertical_is_metres_only_with_a_closed_datum() -> None:
    with pytest.raises(ValidationError):
        declared_vertical(unit="foot")
    with pytest.raises(ValidationError):
        declared_vertical(datum="EGM96")


def test_a_job_on_a_file_observation_must_carry_that_very_observation() -> None:
    source = measured_source()
    other = SurfaceProfileVerticalReferenceV1(
        provenance="OBSERVED",
        observed=source.inspection.measurements.observed_vertical_reference.model_copy(
            update={"basis": "다른 기준"}
        ),
    )
    with pytest.raises(ValidationError, match="source's own"):
        _job(vertical_reference=other)


def test_a_declaration_is_only_for_a_file_without_a_vertical_reference() -> None:
    declared = SurfaceProfileVerticalReferenceV1(
        provenance="DECLARED", declared=declared_vertical()
    )
    with pytest.raises(ValidationError, match="takes no declaration"):
        _job(vertical_reference=declared)  # 이 원본은 자기 수직 기준을 갖고 있다
    job = _job(source=measured_source(observed_vertical=False), vertical_reference=declared)
    assert job.vertical_reference.provenance == "DECLARED"
    # 선언 위의 작업이 수직 기준 관측값을 주장해도 안 된다.
    with pytest.raises(ValidationError):
        _job(
            source=measured_source(observed_vertical=False),
            vertical_reference=observed_vertical(measured_source()),
        )


def test_the_job_digest_binds_the_vertical_provenance() -> None:
    declared_a = SurfaceProfileVerticalReferenceV1(
        provenance="DECLARED", declared=declared_vertical()
    )
    declared_b = SurfaceProfileVerticalReferenceV1(
        provenance="DECLARED", declared=declared_vertical(basis="다른 근거")
    )
    source = measured_source(observed_vertical=False)
    first = _job(source=source, vertical_reference=declared_a)
    second = _job(source=source, vertical_reference=declared_b)
    assert first.job_digest != second.job_digest

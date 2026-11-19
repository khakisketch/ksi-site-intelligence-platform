"""Public contract rules for retained two-epoch surface profile comparisons."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ksi_core.domains.external.delivery.surface_profile_comparisons import (
    _comparison_binding_digest,
)
from ksi_event_contracts.surface_profile_job import (
    CreateSurfaceProfileComparisonV1,
    SurfaceProfileComparisonResultV1,
    SurfaceProfileComparisonSampleV1,
    SurfaceProfileComparisonV1,
    SurfaceProfileErrorV1,
)
from pydantic import ValidationError


def _job_id(suffix: str) -> str:
    return "spj-" + suffix * 32


def test_comparison_request_requires_distinct_ordered_job_ids() -> None:
    payload = {
        "baselineJobId": _job_id("a"),
        "currentJobId": _job_id("b"),
    }
    assert CreateSurfaceProfileComparisonV1.model_validate(payload).baseline_job_id == _job_id("a")

    payload["currentJobId"] = payload["baselineJobId"]
    with pytest.raises(ValidationError):
        CreateSurfaceProfileComparisonV1.model_validate(payload)


def test_unknown_side_has_reason_and_never_a_zero_delta() -> None:
    sample = SurfaceProfileComparisonSampleV1(
        distance_m=1.0,
        baseline_m=None,
        current_m=4.0,
        difference_m=None,
        invalid_reason="BASELINE_UNAVAILABLE",
    )
    assert sample.model_dump(by_alias=True)["invalidReason"] == "BASELINE_UNAVAILABLE"

    with pytest.raises(ValidationError):
        SurfaceProfileComparisonSampleV1(
            distance_m=1.0,
            baseline_m=None,
            current_m=4.0,
            difference_m=0.0,
            invalid_reason="BASELINE_UNAVAILABLE",
        )


def test_only_eligible_decision_can_carry_sealed_numbers() -> None:
    sample0 = SurfaceProfileComparisonSampleV1(
        distance_m=0.0,
        baseline_m=1.0,
        current_m=2.0,
        difference_m=1.0,
        invalid_reason=None,
    )
    sample1 = SurfaceProfileComparisonSampleV1(
        distance_m=1.0,
        baseline_m=2.0,
        current_m=1.5,
        difference_m=-0.5,
        invalid_reason=None,
    )
    result = SurfaceProfileComparisonResultV1(
        baseline_result_digest="sha256:" + "a" * 64,
        current_result_digest="sha256:" + "b" * 64,
        samples=(sample0, sample1),
        valid_count=2,
        largest_rise_m=1.0,
        largest_drop_m=-0.5,
    ).sealed()
    envelope = SurfaceProfileComparisonV1(
        baseline_job_id=_job_id("a"),
        current_job_id=_job_id("b"),
        decision_id="external-use-decision-1",
        decision_digest="sha256:" + "c" * 64,
        verdict="ELIGIBLE",
        reasons=("USE_ELIGIBLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",),
        result=result,
    )
    assert envelope.result is not None

    with pytest.raises(ValidationError):
        SurfaceProfileComparisonV1(
            baseline_job_id=_job_id("a"),
            current_job_id=_job_id("b"),
            decision_id="external-use-decision-1",
            decision_digest="sha256:" + "c" * 64,
            verdict="BLOCKED",
            reasons=("VERTICAL_REFERENCE_UNKNOWN",),
            remediations=("OBSERVE_VERTICAL_REFERENCE",),
            result=result,
        )


def test_stale_eligible_pair_has_a_recovery_action() -> None:
    error = SurfaceProfileErrorV1(
        reason="PROFILE_COMPARISON_NO_LONGER_ELIGIBLE",
        message="현재 비교 자격을 다시 확인한 뒤 새 비교를 요청해 주세요.",
        retryable=False,
        remediation=("RECHECK_CURRENT_PAIR", "CREATE_NEW_COMPARISON"),
    )
    assert error.remediation == ("RECHECK_CURRENT_PAIR", "CREATE_NEW_COMPARISON")


def test_decision_binding_covers_ordered_jobs_receipts_and_results() -> None:
    def retained(job: str, digest: str) -> SimpleNamespace:
        return SimpleNamespace(
            job=SimpleNamespace(job_id=job, job_digest=f"job-{job}"),
            receipt=SimpleNamespace(receipt_digest=f"receipt-{digest}"),
            result=SimpleNamespace(result_digest=f"result-{digest}"),
        )

    baseline = retained("baseline", "a")
    current = retained("current", "b")
    binding = _comparison_binding_digest(baseline, current)  # type: ignore[arg-type]
    assert binding != _comparison_binding_digest(current, baseline)  # type: ignore[arg-type]
    assert binding != _comparison_binding_digest(retained("baseline-2", "a"), current)  # type: ignore[arg-type]
    assert binding != _comparison_binding_digest(retained("baseline", "c"), current)  # type: ignore[arg-type]

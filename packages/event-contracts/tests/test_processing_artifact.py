"""ArtifactAccuracy.rmse — non-finite 값 거부 회귀 테스트.

reviewer 지적: ``Field(ge=0)`` 만으로는 ``+inf``를 걸러내지 못한다(``inf >= 0`` 은
참이라 통과한다). ``rmse`` 는 측량 정확도 실측값이라 non-finite 는 등록 시점에
거부해야 한다.
"""

from __future__ import annotations

import math

import pytest
from ksi_event_contracts.processing_artifact import ArtifactAccuracy
from pydantic import ValidationError


def test_rmse_accepts_finite_nonnegative_value() -> None:
    accuracy = ArtifactAccuracy(gcp_count=5, rmse=0.021, report_uri="s3://r/1.pdf")
    assert accuracy.rmse == 0.021


@pytest.mark.parametrize("bad_rmse", [math.inf, -math.inf, math.nan])
def test_rmse_rejects_non_finite_values(bad_rmse: float) -> None:
    with pytest.raises(ValidationError):
        ArtifactAccuracy(gcp_count=5, rmse=bad_rmse, report_uri="s3://r/1.pdf")


def test_rmse_rejects_infinity_from_wire_json() -> None:
    """raw JSON 의 리터럴 ``Infinity`` 도 ``json.loads`` 기본값으로 통과하므로,
    wire 경로(model_validate_json)에서도 같은 방어가 작동해야 한다."""
    payload = '{"gcpCount": 5, "rmse": Infinity, "reportUri": "s3://r/1.pdf"}'
    with pytest.raises(ValidationError):
        ArtifactAccuracy.model_validate_json(payload)


# ── INV-024: 절대 RMSE 는 독립 검사점이 있을 때만 ──────────────────────────


def test_checkpoint_rmse_without_checkpoints_is_rejected() -> None:
    """검사점 0개인데 검사점 RMSE 를 주장하면 거부한다 — INV-024 의 핵심 게이트."""
    with pytest.raises(ValidationError):
        ArtifactAccuracy(
            gcp_count=12,
            rmse=0.03,
            report_uri="s3://r/1.pdf",
            checkpoint_count=0,
            checkpoint_rmse_m=0.042,
        )


def test_checkpoint_count_without_checkpoint_rmse_is_rejected() -> None:
    """검사점을 뒀다면서 그 잔차를 안 내면 거부한다 — 절반만 실린 주장은 받지 않는다."""
    with pytest.raises(ValidationError):
        ArtifactAccuracy(
            gcp_count=12,
            rmse=0.03,
            report_uri="s3://r/1.pdf",
            checkpoint_count=8,
        )


def test_checkpoint_backed_accuracy_is_accepted() -> None:
    """[비공허 대조] 검사점과 그 잔차가 함께 실리면 통과하고 값이 보존된다."""
    accuracy = ArtifactAccuracy(
        gcp_count=12,
        rmse=0.03,
        report_uri="s3://r/1.pdf",
        checkpoint_count=8,
        checkpoint_rmse_m=0.042,
    )
    assert accuracy.checkpoint_count == 8
    assert accuracy.checkpoint_rmse_m == 0.042


def test_accuracy_without_any_checkpoint_field_is_still_valid() -> None:
    """[비공허 대조] 검사점을 아예 주장하지 않는 기존 wire 는 그대로 유효하다.

    ``rmse`` 는 GCP 피팅 잔차이지 절대정확도가 아니므로 검사점 없이도 성립한다.
    """
    accuracy = ArtifactAccuracy(gcp_count=5, rmse=0.021, report_uri="s3://r/1.pdf")
    assert accuracy.checkpoint_count == 0
    assert accuracy.checkpoint_rmse_m is None


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_checkpoint_rmse_rejects_non_finite_values(bad: float) -> None:
    with pytest.raises(ValidationError):
        ArtifactAccuracy(
            gcp_count=5,
            rmse=0.021,
            report_uri="s3://r/1.pdf",
            checkpoint_count=4,
            checkpoint_rmse_m=bad,
        )


def test_zero_checkpoint_rmse_is_rejected() -> None:
    """절대오차 0m 은 물리적으로 불가능한 주장이다 — 형식만 갖춘 완벽 정확도 신고를 막는다."""
    with pytest.raises(ValidationError):
        ArtifactAccuracy(
            gcp_count=12,
            rmse=0.03,
            report_uri="s3://r/1.pdf",
            checkpoint_count=1,
            checkpoint_rmse_m=0.0,
        )

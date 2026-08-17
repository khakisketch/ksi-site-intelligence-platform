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

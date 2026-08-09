"""VolumeChangeReport 계약 — 구역 체적과 오차한계의 정직성 (INV-024, ADR-KSI-016 D6).

초점 셋:

1. **계약이 스스로 모순을 본다** — cut·fill·net 은 둘이 셋째를 정한다. 셋을
   그대로 받아 적으면 "깎기만 했는데 순증가"가 원장에 남고, 그건 어느 화면에서도
   이상해 보이지 않는다.
2. **오차한계 없음에는 이유가 따라온다** — ``uncertaintyM3`` 가 null 인 것은
   정상이지만(ODM 경로는 항상 null), **왜 없는지**를 비워둘 수는 없다. 숫자만
   보여주고 한계를 감추면 화면이 "믿을 만하다"고 말하는 것과 같다(INV-024).
3. **자기 자신과의 차분을 막는다** — 결과가 언제나 0 이고, 그 0 이 "변화 없음"
   으로 읽힌다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.volume_change_report import (
    VolumeChangeReport,
    ZoneVolumeDelta,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "volume-change-report.v1.json"

_NOW = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)


def _zone(**overrides: object) -> ZoneVolumeDelta:
    payload: dict[str, object] = {
        "zone_id": "zone-0",
        "cut_m3": 30.0,
        "fill_m3": 100.0,
        "net_m3": 70.0,
        "area_m2": 2500.0,
        "threshold_m": 0.05,
        "uncertainty_m3": None,
        "uncertainty_note": "ODM 경로는 검사점 RMSE 를 내지 않는다 — 상대 비교만 유효",
    }
    payload.update(overrides)
    return ZoneVolumeDelta(**payload)  # type: ignore[arg-type]


def _report(**overrides: object) -> VolumeChangeReport:
    payload: dict[str, object] = {
        "volume_change_id": "vc-1",
        "baseline": ArtifactRef(job_id="job-1", artifact_id="dsm"),
        "current": ArtifactRef(job_id="job-2", artifact_id="dsm"),
        "crs": "EPSG:5186",
        "vertical_datum": "ellipsoidal_native",
        "zones": [_zone()],
        "computed_at": _NOW,
    }
    payload.update(overrides)
    return VolumeChangeReport(**payload)  # type: ignore[arg-type]


def test_a_consistent_report_round_trips() -> None:
    report = _report()
    assert report.total_net_m3 == pytest.approx(70.0)
    assert report.model_dump(by_alias=True)["verticalDatum"] == "ellipsoidal_native"


def test_net_that_contradicts_cut_and_fill_is_refused() -> None:
    """[핵심] 깎기만 했는데 순증가 — 계약이 스스로 볼 수 있는 모순이다."""
    with pytest.raises(ValidationError, match="netM3"):
        _zone(cut_m3=100.0, fill_m3=0.0, net_m3=50.0)


def test_negative_cut_or_fill_is_refused() -> None:
    """부호는 net 하나로만 말한다 — cut/fill 이 음수면 방향이 두 곳에 생긴다."""
    with pytest.raises(ValidationError):
        _zone(cut_m3=-1.0)


def test_uncertainty_may_be_null_but_the_reason_may_not() -> None:
    """null 은 정상이고 이유 없음은 아니다 (INV-024).

    ODM 경로는 검사점 RMSE 를 내지 않아 이 값이 **항상** null 이다. 그래서
    null 자체를 막으면 정직한 결과가 거부된다 — 대신 왜 없는지를 요구한다.
    """
    assert _zone(uncertainty_m3=None).uncertainty_m3 is None
    with pytest.raises(ValidationError):
        _zone(uncertainty_note="")


def test_naive_timestamp_is_refused() -> None:
    """시간대 없는 시각은 나중에 어느 시점인지 복원할 수 없다."""
    with pytest.raises(ValidationError, match="tz-aware"):
        _report(computed_at=datetime(2026, 8, 7, 3, 0))


def test_self_comparison_is_refused() -> None:
    """[음성] 자기 자신과의 차분은 언제나 0 이고, 그 0 이 '변화 없음'으로 읽힌다."""
    same = ArtifactRef(job_id="job-1", artifact_id="dsm")
    with pytest.raises(ValidationError, match="같은 산출물"):
        _report(baseline=same, current=same)


def test_same_artifact_id_in_different_jobs_is_allowed() -> None:
    """두 시점의 DSM 은 artifactId 가 같다 — 그게 정상 경로다."""
    report = _report(
        baseline=ArtifactRef(job_id="job-1", artifact_id="dsm"),
        current=ArtifactRef(job_id="job-2", artifact_id="dsm"),
    )
    assert report.baseline.job_id != report.current.job_id


def test_duplicate_zone_ids_are_refused() -> None:
    """[음성] 같은 구역이 두 번 집계되면 총합이 조용히 두 배가 된다."""
    with pytest.raises(ValidationError, match="중복"):
        _report(zones=[_zone(), _zone()])


def test_empty_zones_is_refused() -> None:
    """구역이 없는 체적 리포트는 아무것도 말하지 않는다."""
    with pytest.raises(ValidationError):
        _report(zones=[])


def test_unknown_field_is_refused() -> None:
    """계약 밖 필드를 조용히 삼키지 않는다(extra=forbid)."""
    with pytest.raises(ValidationError):
        VolumeChangeReport(  # type: ignore[call-arg]
            volume_change_id="vc-1",
            baseline=ArtifactRef(job_id="job-1", artifact_id="dsm"),
            current=ArtifactRef(job_id="job-2", artifact_id="dsm"),
            crs="EPSG:5186",
            vertical_datum="ellipsoidal_native",
            zones=[_zone()],
            computed_at=_NOW,
            totalNetM3=70.0,
        )


# ── 계약 모델 ↔ JSON 스키마 왕복 ────────────────────────────────────────────


def test_wire_payload_validates_against_the_json_schema() -> None:
    """계약 모델이 내는 payload 가 정본 스키마를 통과한다.

    둘이 갈라지면 "파이썬에서는 되는데 스키마로 검증하는 소비자는 거부"가
    생기고, 그 갈라짐은 파이썬만 쓰는 테스트에서 보이지 않는다.
    """
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    payload = _report().model_dump(by_alias=True, mode="json")
    jsonschema.validate(payload, schema)


def test_schema_refuses_a_payload_missing_the_uncertainty_reason() -> None:
    """스키마 쪽에서도 이유 없는 null 을 막는다 — 두 겹이 같은 규칙을 강제한다."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    payload = _report().model_dump(by_alias=True, mode="json")
    del payload["zones"][0]["uncertaintyNote"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_refuses_unknown_fields() -> None:
    """additionalProperties:false — 계약 밖 필드가 조용히 흘러가지 않는다."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    payload = _report().model_dump(by_alias=True, mode="json")
    payload["totalNetM3"] = 70.0

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

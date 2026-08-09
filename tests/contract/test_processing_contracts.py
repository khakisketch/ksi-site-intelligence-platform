"""ProcessingJob/ProcessingArtifact 계약 round-trip 테스트 (ADR-KSI-012·013, INV-050·051).

`services/processing-controller`의 처리 워커 구현은 이 테스트의 범위 밖이다 —
초점은 계약 스키마·Pydantic 모델·둘의 정합, 그리고 INV-050·051이 실제로 거부를
만드는가 하나다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts.processing_artifact import (
    ProcessingArtifact,
    processing_artifact_wire_dict,
)
from ksi_event_contracts.processing_job import ProcessingJob, processing_job_wire_dict
from pydantic import ValidationError

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_JOB_SCHEMA_FILE = "processing-job.v1.json"
# v1.1 이 정본(auxiliaryFiles 추가, mesh-multi-file-artifact-persistence) — v1.0 은
# "옛 소비자가 auxiliaryFiles 없는 wire 를 계속 읽는다"를 증명하는 backward-compat
# 비교용으로만 남긴다(아래 test_artifact_without_auxiliary_files_also_satisfies_v1_0).
_ARTIFACT_SCHEMA_FILE = "processing-artifact.v1.1.json"
_ARTIFACT_SCHEMA_FILE_V1_0 = "processing-artifact.v1.json"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _valid_job_dict(
    *, execution_locus: str = "site_onprem", egress_allowed: bool = False
) -> dict[str, Any]:
    return {
        "jobId": "job-001",
        "missionId": "mission-001",
        "provider": "odm",
        "engineVersion": "3.5.2",
        "engineDigest": "sha256:" + "ab" * 32,
        "executionLocus": execution_locus,
        "dataResidency": {"egressAllowed": egress_allowed, "jurisdiction": "KR"},
        "licenseBasis": {
            "licenseId": "oss-agpl-3.0",
            "tier": "self_hosted_oss",
            "attributionRequired": False,
        },
        "input": {
            "imageCount": 1039,
            "totalMegapixels": 20780.0,
            "sourceBundleDigest": "sha256:" + "cd" * 32,
        },
        "processingParams": {"orthoResolution": 5, "fastOrthophoto": False},
        "billing": {
            "creditsCharged": 0,
            "rateBasis": "onprem_zero_credit",
            "meteredAt": "2026-08-05T03:00:00Z",
        },
    }


def _valid_artifact_dict(
    *,
    authority: str = "source",
    kind: str = "point_cloud",
    derived_from: list[str] | None = None,
    crs: str | None = "EPSG:5186",
    gsd: float | None = 0.02,
) -> dict[str, Any]:
    return {
        "artifactId": "art-001",
        "jobId": "job-001",
        "kind": kind,
        "lineage": {
            "authority": authority,
            "derivedFrom": derived_from if derived_from is not None else [],
            "sourceDigest": "sha256:" + "ef" * 32,
        },
        "digest": "sha256:" + "12" * 32,
        "format": "laz",
        "crs": crs,
        "gsd": gsd,
        "accuracy": None,
    }


# ── 스키마 파일 자체의 유효성 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "schema_file", [_JOB_SCHEMA_FILE, _ARTIFACT_SCHEMA_FILE, _ARTIFACT_SCHEMA_FILE_V1_0]
)
def test_schema_file_is_valid_draft202012(schema_file: str) -> None:
    Draft202012Validator.check_schema(_load_schema(schema_file))


# ── ProcessingJob round-trip ───────────────────────────────────────────────


def test_processing_job_roundtrip_matches_schema() -> None:
    schema = _load_schema(_JOB_SCHEMA_FILE)
    job = ProcessingJob.model_validate(_valid_job_dict())
    wire = processing_job_wire_dict(job)
    Draft202012Validator(schema).validate(wire)


def test_processing_job_extra_field_rejected() -> None:
    data = _valid_job_dict()
    data["unexpectedField"] = "should be rejected"
    with pytest.raises(ValidationError):
        ProcessingJob.model_validate(data)


def test_processing_job_status_omitted_when_unset() -> None:
    """status는 optional — 미설정이면 wire에서 생략된다(스키마도 required가 아니다)."""
    job = ProcessingJob.model_validate(_valid_job_dict())
    assert "status" not in processing_job_wire_dict(job)
    schema = _load_schema(_JOB_SCHEMA_FILE)
    assert "status" not in schema["required"]


# ── INV-050: executionLocus=vendor_cloud × egressAllowed 불일치 거부 ────────


def test_vendor_cloud_without_egress_rejected_by_schema() -> None:
    """[핵심 1/3] JSON Schema 레벨 — allOf/if/then이 이 조합을 거부한다."""
    schema = _load_schema(_JOB_SCHEMA_FILE)
    payload = _valid_job_dict(execution_locus="vendor_cloud", egress_allowed=False)
    payload["provider"] = "dji_flighthub"
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    assert errors, "vendor_cloud + egressAllowed=false 조합이 스키마를 통과했다"


def test_vendor_cloud_without_egress_rejected_by_model() -> None:
    """[핵심 1/3] Pydantic 레벨 — model_validator가 같은 조합을 생성 시점에 막는다."""
    payload = _valid_job_dict(execution_locus="vendor_cloud", egress_allowed=False)
    payload["provider"] = "dji_flighthub"
    with pytest.raises(ValidationError, match="INV-050"):
        ProcessingJob.model_validate(payload)


def test_vendor_cloud_with_egress_allowed_is_accepted() -> None:
    """[비공허 대조] egressAllowed=true면 vendor_cloud도 정상 성립한다 — 과잉 거부가 아니다."""
    payload = _valid_job_dict(execution_locus="vendor_cloud", egress_allowed=True)
    payload["provider"] = "dji_flighthub"
    job = ProcessingJob.model_validate(payload)
    schema = _load_schema(_JOB_SCHEMA_FILE)
    Draft202012Validator(schema).validate(processing_job_wire_dict(job))


def test_non_vendor_cloud_locus_ignores_egress_gate() -> None:
    """[비공허 대조] site_onprem 등은 egressAllowed=false라도 정상 — 게이트는 vendor_cloud 전용."""
    payload = _valid_job_dict(execution_locus="site_onprem", egress_allowed=False)
    job = ProcessingJob.model_validate(payload)
    assert job.execution_locus.value == "site_onprem"


# ── ProcessingArtifact round-trip ──────────────────────────────────────────


def test_processing_artifact_roundtrip_matches_schema() -> None:
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    artifact = ProcessingArtifact.model_validate(_valid_artifact_dict())
    wire = processing_artifact_wire_dict(artifact)
    Draft202012Validator(schema).validate(wire)


def test_processing_artifact_extra_field_rejected() -> None:
    data = _valid_artifact_dict()
    data["unexpectedField"] = "should be rejected"
    with pytest.raises(ValidationError):
        ProcessingArtifact.model_validate(data)


# ── auxiliaryFiles (mesh-multi-file-artifact-persistence) ──────────────────


def test_artifact_without_auxiliary_files_also_satisfies_v1_0() -> None:
    """[핵심 — 하위호환] auxiliaryFiles 를 안 준(기본값 빈 튜플) wire 는 v1.0
    소비자도 그대로 읽는다 — v1.1 로의 이행이 기존 소비자를 깨지 않는다."""
    artifact = ProcessingArtifact.model_validate(_valid_artifact_dict())
    wire = processing_artifact_wire_dict(artifact)
    assert "auxiliaryFiles" not in wire
    Draft202012Validator(_load_schema(_ARTIFACT_SCHEMA_FILE_V1_0)).validate(wire)


def test_artifact_with_auxiliary_files_roundtrips() -> None:
    payload = _valid_artifact_dict(kind="mesh", derived_from=["point-cloud"], authority="derived")
    payload["format"] = "obj"
    aux_files = ["odm_textured_model_geo.mtl", "odm_textured_model_geo_map_Kd.png"]
    artifact = ProcessingArtifact.model_validate({**payload, "auxiliaryFiles": aux_files})
    assert artifact.auxiliary_files == (
        "odm_textured_model_geo.mtl",
        "odm_textured_model_geo_map_Kd.png",
    )
    wire = processing_artifact_wire_dict(artifact)
    assert wire["auxiliaryFiles"] == [
        "odm_textured_model_geo.mtl",
        "odm_textured_model_geo_map_Kd.png",
    ]
    Draft202012Validator(_load_schema(_ARTIFACT_SCHEMA_FILE)).validate(wire)
    # v1.0(auxiliaryFiles 를 모르는 스키마)은 additionalProperties:false 라
    # 이 wire 를 거부해야 한다 — v1.1 로만 표현 가능한 사실을 v1.0 이 조용히
    # 받아주면 "이행"이라는 말이 성립하지 않는다.
    with pytest.raises(Exception):  # noqa: B017,PT011 — jsonschema ValidationError
        Draft202012Validator(_load_schema(_ARTIFACT_SCHEMA_FILE_V1_0)).validate(wire)


def test_auxiliary_file_name_with_path_component_rejected_by_schema() -> None:
    """basename 만 허용한다 — '/'·'..' 가 들어가면 저장 위치 유도가 경로 탈출이 된다."""
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    for bad_name in ("../escape.mtl", "sub/dir.mtl", "/etc/passwd"):
        payload = {**_valid_artifact_dict(), "auxiliaryFiles": [bad_name]}
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        assert errors, f"{bad_name!r} 이 스키마를 통과했다"


# ── INV-051: authority=derived without derivedFrom 거부 ────────────────────


def test_derived_without_derived_from_rejected_by_schema() -> None:
    """[핵심 2/3] JSON Schema 레벨 — lineage 내부 allOf/if/then이 거부한다."""
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    payload = _valid_artifact_dict(authority="derived", kind="mesh", derived_from=[])
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    assert errors, "authority=derived + derivedFrom=[] 조합이 스키마를 통과했다"


def test_derived_without_derived_from_rejected_by_model() -> None:
    """[핵심 2/3] Pydantic 레벨 — model_validator가 같은 조합을 생성 시점에 막는다."""
    payload = _valid_artifact_dict(authority="derived", kind="mesh", derived_from=[])
    with pytest.raises(ValidationError, match="INV-051"):
        ProcessingArtifact.model_validate(payload)


def test_derived_with_derived_from_is_accepted() -> None:
    """[비공허 대조] derivedFrom이 채워지면 derived도 정상 성립한다."""
    payload = _valid_artifact_dict(authority="derived", kind="mesh", derived_from=["art-001"])
    artifact = ProcessingArtifact.model_validate(payload)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    Draft202012Validator(schema).validate(processing_artifact_wire_dict(artifact))


# ── accuracy nullable (ODM 경로) ────────────────────────────────────────────


def test_null_accuracy_artifact_is_valid_odm_path() -> None:
    """[핵심 3/3] accuracy=null인 산출물(ODM 경로)이 스키마·모델 양쪽에서 정상 유효하다."""
    payload = _valid_artifact_dict()
    assert payload["accuracy"] is None
    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.accuracy is None

    wire = processing_artifact_wire_dict(artifact)
    assert "accuracy" in wire and wire["accuracy"] is None, (
        "accuracy는 생략이 아니라 명시적 null이어야 한다 — "
        "'측정 안 함'과 '필드를 잊음'을 구분하기 위해서다"
    )

    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    Draft202012Validator(schema).validate(wire)


def test_populated_accuracy_artifact_is_valid() -> None:
    """[비공허 대조] accuracy가 채워진 산출물(Pix4D 등)도 정상 유효하다."""
    payload = _valid_artifact_dict()
    payload["accuracy"] = {"gcpCount": 12, "rmse": 0.03, "reportUri": "s3://bucket/report.pdf"}
    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.accuracy is not None
    assert artifact.accuracy.gcp_count == 12

    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    Draft202012Validator(schema).validate(processing_artifact_wire_dict(artifact))


def test_accuracy_missing_key_still_defaults_to_null() -> None:
    """accuracy 키를 아예 생략한 입력도 모델은 None으로 받는다(schema는 required지만
    이는 Python-측 편의 입력 경로 — wire 직렬화는 여전히 명시적 null을 싣는다)."""
    payload = _valid_artifact_dict()
    del payload["accuracy"]
    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.accuracy is None
    wire = processing_artifact_wire_dict(artifact)
    assert wire["accuracy"] is None


# ── crs/gsd nullable — kind별 강제 (2026-08-05 코디네이터 지적 반영) ────────────
#
# 최초 버전은 crs/gsd를 모든 kind에 non-nullable로 강제했다 — report/camera_poses
# 처럼 공간 좌표계·픽셀 GSD가 원천적으로 없는 산출물의 생산자가 값을 지어내야
# 하는 결함이었다("요청이 자기 증명서를 스스로 쓰는" 클래스, ADR-KSI-011 D3와 동류).
# accuracy와 같은 방식(required 유지 + nullable 타입 + kind별 null 금지)으로 고쳤다.


def test_report_artifact_with_null_crs_and_gsd_is_valid() -> None:
    """[핵심] report 산출물은 crs=null, gsd=null로 정상 유효하다 — 스키마·모델 양쪽."""
    payload = _valid_artifact_dict(kind="report", crs=None, gsd=None)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    assert not list(Draft202012Validator(schema).iter_errors(payload)), "스키마가 거부했다"

    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.crs is None
    assert artifact.gsd is None
    wire = processing_artifact_wire_dict(artifact)
    assert wire["crs"] is None and wire["gsd"] is None, "생략이 아니라 명시적 null이어야 한다"
    Draft202012Validator(schema).validate(wire)


def test_camera_poses_artifact_with_null_crs_and_gsd_is_valid() -> None:
    """[비공허 대조] report뿐 아니라 camera_poses도 같은 예외에 속한다."""
    payload = _valid_artifact_dict(kind="camera_poses", crs=None, gsd=None)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.crs is None and artifact.gsd is None


def test_ortho_artifact_with_null_gsd_rejected_by_schema() -> None:
    """[핵심] ortho(래스터 계열)는 gsd=null이면 스키마가 거부한다."""
    payload = _valid_artifact_dict(kind="ortho", crs="EPSG:5186", gsd=None)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert errors, "ortho + gsd=null 조합이 스키마를 통과했다"


def test_ortho_artifact_with_null_gsd_rejected_by_model() -> None:
    """[핵심] ortho는 gsd=null이면 Pydantic model_validator도 거부한다."""
    payload = _valid_artifact_dict(kind="ortho", crs="EPSG:5186", gsd=None)
    with pytest.raises(ValidationError, match="gsd"):
        ProcessingArtifact.model_validate(payload)


@pytest.mark.parametrize("raster_kind", ["ortho", "dsm", "dtm"])
def test_raster_kinds_with_populated_gsd_are_valid(raster_kind: str) -> None:
    """[비공허 대조] gsd를 채우면 래스터 계열도 정상 성립한다 — 과잉 거부가 아니다."""
    payload = _valid_artifact_dict(kind=raster_kind, crs="EPSG:5186", gsd=0.05)
    artifact = ProcessingArtifact.model_validate(payload)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    Draft202012Validator(schema).validate(processing_artifact_wire_dict(artifact))


def test_point_cloud_artifact_with_null_crs_rejected_by_schema() -> None:
    """[핵심] point_cloud는 crs=null이면 스키마가 거부한다 — 공간 SSOT가 좌표계 없이 성립 불가."""
    payload = _valid_artifact_dict(kind="point_cloud", crs=None, gsd=None)
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert errors, "point_cloud + crs=null 조합이 스키마를 통과했다"


def test_point_cloud_artifact_with_null_crs_rejected_by_model() -> None:
    """[핵심] point_cloud는 crs=null이면 Pydantic model_validator도 거부한다."""
    payload = _valid_artifact_dict(kind="point_cloud", crs=None, gsd=None)
    with pytest.raises(ValidationError, match="crs"):
        ProcessingArtifact.model_validate(payload)


@pytest.mark.parametrize("kind_with_optional_gsd", ["point_cloud", "mesh", "tiles_3d"])
def test_non_raster_spatial_kinds_allow_null_gsd_but_require_crs(
    kind_with_optional_gsd: str,
) -> None:
    """[비공허 대조] point_cloud/mesh/tiles_3d는 crs는 필수, gsd는 null 허용."""
    payload = _valid_artifact_dict(kind=kind_with_optional_gsd, crs="EPSG:5186", gsd=None)
    artifact = ProcessingArtifact.model_validate(payload)
    assert artifact.gsd is None
    schema = _load_schema(_ARTIFACT_SCHEMA_FILE)
    Draft202012Validator(schema).validate(processing_artifact_wire_dict(artifact))


# ── 공허 방지 ────────────────────────────────────────────────────────────────


def test_valid_fixtures_are_not_accidentally_identical() -> None:
    """위 fixture 헬퍼가 매 호출 독립 dict를 주는지 — 공유 mutable state로 인한
    거짓 통과를 방지."""
    a = _valid_job_dict()
    b = _valid_job_dict()
    a["jobId"] = "mutated"
    assert b["jobId"] == "job-001"
    assert copy.deepcopy(a) != copy.deepcopy(b)

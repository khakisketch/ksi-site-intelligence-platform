"""Strict AI/MCP projection contracts: closed shapes and V1 output immutability."""

import importlib
import json
from pathlib import Path
from typing import Any, Literal, get_args

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_event_contracts import spatial_data_ai
from ksi_event_contracts._spatial_data import SpatialDataModel
from ksi_event_contracts.spatial_data import SpatialDataJobViewV1, SpatialDataReasonV1
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema
from spatial_data_fixture import ASSET, DIGEST, JOB_ID, NOW, make_receipt

ROOT = Path(__file__).resolve().parents[2]
TRANSFORM = (1.0, 0.0, 0.0, 0.0, -1.0, 10.0)
RECEIPT_DIGEST = "sha256:" + "c" * 64


def _literal_values(alias: Any) -> set[str]:
    values: set[str] = set()
    for arg in get_args(alias):
        values.update(get_args(arg) if get_args(arg) else {arg})
    return {value for value in values if isinstance(value, str)}


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / "contracts/schemas/spatial-data-ai.v1.json").read_text())
    return Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    )


def _asset_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = dict(
        assetRef=ASSET,
        siteId="site-local",
        workAreaId="area-local",
        workOrderId="order-local",
        epochId="epoch-local",
        submissionRef="ref-local",
        revision=1,
        artifactKind="dsm",
        lifecycleState="SEALED",
        observedSha256=DIGEST,
        observedSizeBytes=4096,
        inspectionReportDigest=DIGEST,
        inspectorBuildDigest=DIGEST,
        observedCrsIdentifier="EPSG:7850",
        observedCrsDigest=DIGEST,
        observedCrsUnits="metre",
        observedVerticalReference=None,
        transform=list(TRANSFORM),
        resolution=[1.0, 1.0],
        bandCount=1,
        dtype="float32",
        permittedBounds=[0.0, 0.0, 1.0, 1.0],
        captureStartedAt=None,
        captureEndedAt=None,
        producerProcessedAt=None,
        declarationRecordedAt=NOW.isoformat().replace("+00:00", "Z"),
        timestampProvenance="SUBMISSION_DECLARATION",
        permittedOperations=["READ", "PREPARE"],
        restrictions=[],
        attribution="Synthetic local fixture",
        modificationNotice="Native rectangular crop",
        accuracyAssessed=False,
        analysisStatus="NOT_EVALUATED",
    )
    payload.update(overrides)
    return payload


def _completed_job_payload() -> dict[str, Any]:
    receipt = make_receipt()
    return dict(
        jobId=JOB_ID,
        assetRef=ASSET,
        siteId="site-local",
        workAreaId="area-local",
        createdAt=NOW.isoformat().replace("+00:00", "Z"),
        executionState="COMPLETED",
        availability="AVAILABLE",
        receipt=receipt.model_dump(by_alias=True, mode="json"),
    )


def _descriptor_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = dict(
        referenceVersion="spatial-data-file-reference.v1",
        siteId="site-local",
        workAreaId="area-local",
        jobId=JOB_ID,
        method="GET",
        relativePath=f"/v1/sites/site-local/work-areas/area-local/spatial-data-requests/{JOB_ID}/file",
        outputSha256=RECEIPT_DIGEST,
        outputSizeBytes=128,
        authenticationRequired=True,
        rangeSupported=False,
    )
    payload.update(overrides)
    return payload


def test_ai_models_schema_concordance() -> None:
    asset = spatial_data_ai.SpatialDataAssetViewV1.model_validate(_asset_payload())
    page = spatial_data_ai.SpatialDataAssetPageV1.model_validate(
        {"items": [asset.model_dump(by_alias=True, mode="json")], "nextCursor": None}
    )
    wrapper = spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
        {"job": _completed_job_payload(), "fileReference": _descriptor_payload()}
    )
    ai_error = spatial_data_ai.SpatialDataAiErrorV1.model_validate(
        {
            "reason": "SPATIAL_DATA_CURSOR_STALE",
            "message": "Listing cursor is stale.",
            "retryable": False,
            "remediation": ["REQUEST_NEW_JOB"],
        }
    )
    mcp_error = spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
        {"code": "CORE_TIMEOUT", "remediation": ["RETRY_REQUEST"]}
    )
    for record in (asset, page, wrapper, ai_error, mcp_error):
        wire = record.model_dump(by_alias=True, mode="json")
        _validator(type(record).__name__).validate(wire)
        tampered = dict(wire)
        tampered["callerAuthority"] = True
        assert not _validator(type(record).__name__).is_valid(tampered)
        with pytest.raises(ValidationError):
            type(record).model_validate(tampered)

    namespace = importlib.import_module("ksi_event_contracts.spatial_data_ai")
    models: list[tuple[type[SpatialDataModel], Literal["validation"]]] = [
        (value, "validation")
        for value in vars(namespace).values()
        if isinstance(value, type)
        and issubclass(value, SpatialDataModel)
        and value.__module__ == namespace.__name__
        and not value.__name__.startswith("_")
    ]
    assert {model.__name__ for model, _ in models} == {
        "SpatialDataAssetViewV1",
        "SpatialDataAssetPageV1",
        "SpatialDataFileReferenceV1",
        "SpatialDataMcpJobViewV1",
        "SpatialDataAiErrorV1",
        "SpatialDataMcpErrorV1",
    }
    _, expected = models_json_schema(models, by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    actual = json.loads((ROOT / "contracts/schemas/spatial-data-ai.v1.json").read_text())
    assert actual == expected
    Draft202012Validator.check_schema(actual)


def test_v1_output_models_stay_immutable() -> None:
    assert set(SpatialDataJobViewV1.model_fields) == {
        "job_id",
        "asset_ref",
        "site_id",
        "work_area_id",
        "created_at",
        "execution_state",
        "availability",
        "reason",
        "remediation",
        "receipt",
    }
    assert "SPATIAL_DATA_CURSOR_STALE" not in get_args(SpatialDataReasonV1)
    ai_reasons = _literal_values(spatial_data_ai.SpatialDataAiReasonV1)
    assert "SPATIAL_DATA_CURSOR_STALE" in ai_reasons
    assert set(get_args(SpatialDataReasonV1)) <= ai_reasons
    mcp_codes = _literal_values(spatial_data_ai.SpatialDataMcpErrorCodeV1)
    assert {
        "UNKNOWN_TOOL",
        "INVALID_TOOL_ARGUMENTS",
        "CONFIGURATION_UNAVAILABLE",
        "CORE_UNAVAILABLE",
        "CORE_TIMEOUT",
        "CORE_RESPONSE_TOO_LARGE",
        "INVALID_CORE_RESPONSE",
        "AI_EGRESS_UNACKNOWLEDGED",
        "CONCURRENCY_LIMIT_EXCEEDED",
    } <= mcp_codes
    assert ai_reasons <= mcp_codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", "1"),
        ("observedSizeBytes", "4096"),
        ("permittedBounds", [True, 0, 1, 1]),
        ("permittedBounds", ["0", 0, 1, 1]),
        ("permittedBounds", [0, 0, 1, 1, 2]),
        ("permittedBounds", [0, 0, float("inf"), 1]),
        ("assetRef", "not-an-asset"),
        ("observedSha256", "a" * 64),
        ("lifecycleState", "DRAFT"),
        ("timestampProvenance", "INSPECTOR_OBSERVATION"),
        ("analysisStatus", "EVALUATED"),
        ("dtype", "uint16"),
        ("artifactKind", "mesh"),
        ("revision", 0),
    ],
)
def test_asset_view_rejects_hostile_scalar_shapes(field: str, value: Any) -> None:
    payload = _asset_payload(**{field: value})
    assert not _validator("SpatialDataAssetViewV1").is_valid(payload)
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetViewV1.model_validate(payload)


@pytest.mark.parametrize(
    "bounds",
    [
        [0, 0, 0, 1],
        [0, 0, 1, 0],
        [1, 0, 0, 1],
        [0, 2, 1, 1],
        [0, 0, float("nan"), 1],
    ],
)
def test_asset_view_rejects_empty_reversed_or_nonfinite_permitted_bounds(
    bounds: Any,
) -> None:
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetViewV1.model_validate(
            _asset_payload(permittedBounds=bounds)
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("accuracyAssessed", True),
        ("dtype", "uint8"),
        ("bandCount", 3),
        ("transform", [1.0, 0.5, 0.0, 0.0, -1.0, 10.0]),
        ("transform", [-1.0, 0.0, 0.0, 0.0, -1.0, 10.0]),
        ("resolution", [2.0, 1.0]),
        ("permittedOperations", []),
        ("permittedOperations", ["READ", "READ"]),
        ("permittedOperations", ["WRITE"]),
        ("restrictions", ["TRAINING_USE"]),
        ("captureStartedAt", "2026-10-02T00:00:00Z"),
    ],
)
def test_asset_view_rejects_false_claims_and_native_profile_violations(
    field: str, value: Any
) -> None:
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetViewV1.model_validate(_asset_payload(**{field: value}))


def test_ai_error_keeps_old_reason_enum_closed() -> None:
    valid = spatial_data_ai.SpatialDataAiErrorV1.model_validate(
        {
            "reason": "PERMISSION_DENIED",
            "message": "Access was refused.",
            "retryable": False,
            "remediation": ["CHECK_AUTHENTICATION"],
        }
    )
    assert valid.reason == "PERMISSION_DENIED"
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAiErrorV1.model_validate(
            {
                "reason": "TRAINING_USE",
                "message": "Invented reason.",
                "retryable": False,
                "remediation": ["RETRY_REQUEST"],
            }
        )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAiErrorV1.model_validate(
            {
                "reason": "CORE_TIMEOUT",
                "message": "Adapter code is not an AI reason.",
                "retryable": True,
                "remediation": ["RETRY_REQUEST"],
            }
        )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAiErrorV1.model_validate(
            {
                "reason": "NOT_FOUND",
                "message": "Missing remediation.",
                "retryable": False,
                "remediation": [],
            }
        )


def test_mcp_error_envelope_is_closed_code_and_remediation() -> None:
    valid = spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
        {"code": "UNKNOWN_TOOL", "remediation": ["CONTACT_OPERATOR"]}
    )
    assert valid.code == "UNKNOWN_TOOL"
    reason_coded = spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
        {"code": "NOT_FOUND", "remediation": ["REQUEST_NEW_GRANT"]}
    )
    assert reason_coded.code == "NOT_FOUND"
    stale_coded = spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
        {"code": "SPATIAL_DATA_CURSOR_STALE", "remediation": ["REQUEST_NEW_JOB"]}
    )
    assert stale_coded.code == "SPATIAL_DATA_CURSOR_STALE"
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
            {"code": "TRAINING_USE", "remediation": ["RETRY_REQUEST"]}
        )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
            {"code": "CORE_TIMEOUT", "remediation": []}
        )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpErrorV1.model_validate(
            {"code": "CORE_TIMEOUT", "remediation": ["RETRY_REQUEST"], "message": "extra"}
        )


def test_file_reference_matches_authorized_job() -> None:
    wrapper = spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
        {"job": _completed_job_payload(), "fileReference": _descriptor_payload()}
    )
    assert wrapper.file_reference is not None
    assert wrapper.file_reference.relative_path.endswith(f"/spatial-data-requests/{JOB_ID}/file")
    bare = spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
        {"job": _completed_job_payload(), "fileReference": None}
    )
    assert bare.file_reference is None


@pytest.mark.parametrize(
    "site_id,work_area_id",
    [
        ("site-a/../site-b", "area-local"),
        ("site-local", "area?query=x"),
        ("site-local", "%2e%2e"),
        ("../", "area-local"),
        ("site/local", "area-local"),
        ("site-local", "area#frag"),
        ("site-local\n", "area-local"),
        ("site-local", "area\x00x"),
        ("-leading-dash", "area-local"),
        (".", "area-local"),
        ("x" * 256, "area-local"),
        ("", "area-local"),
    ],
)
def test_file_reference_rejects_unsafe_scope_segments_with_matching_path(
    site_id: str, work_area_id: str
) -> None:
    hostile_path = (
        f"/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests/{JOB_ID}/file"
    )
    payload = _descriptor_payload(
        siteId=site_id, workAreaId=work_area_id, relativePath=hostile_path
    )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataFileReferenceV1.model_validate(payload)
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
            {"job": _completed_job_payload(), "fileReference": payload}
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("outputSha256", DIGEST),
        ("outputSizeBytes", 4097),
        ("siteId", "site-other"),
        ("workAreaId", "area-other"),
        ("jobId", "sdj-v1-00000000-0000-4000-8000-000000000002"),
        ("relativePath", "/v1/sites/site-local/work-areas/area-local/spatial-data-requests/file"),
        (
            "relativePath",
            "/v1/sites/site-local/work-areas/area-local/spatial-data-requests/../file",
        ),
        ("method", "POST"),
        ("referenceVersion", "spatial-data-file-reference.v2"),
        ("authenticationRequired", False),
        ("rangeSupported", True),
    ],
)
def test_file_reference_rejects_descriptor_mismatch(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
            {
                "job": _completed_job_payload(),
                "fileReference": _descriptor_payload(**{field: value}),
            }
        )


@pytest.mark.parametrize(
    "execution_state,availability",
    [
        ("RUNNING", "NOT_READY"),
        ("QUEUED", "NOT_READY"),
        ("COMPLETED", "ACCESS_REVOKED"),
        ("COMPLETED", "ACCESS_EXPIRED"),
        ("FAILED", "UNAVAILABLE"),
    ],
)
def test_file_reference_requires_completed_available_receipt(
    execution_state: str, availability: str
) -> None:
    job = _completed_job_payload()
    job.update({"executionState": execution_state, "availability": availability})
    if execution_state != "COMPLETED":
        job.pop("receipt")
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataMcpJobViewV1.model_validate(
            {"job": job, "fileReference": _descriptor_payload()}
        )


def test_asset_page_bounds_items_and_cursor() -> None:
    asset = _asset_payload()
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetPageV1.model_validate(
            {"items": [asset] * 201, "nextCursor": None}
        )
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetPageV1.model_validate({"items": [asset], "nextCursor": ""})
    with pytest.raises(ValidationError):
        spatial_data_ai.SpatialDataAssetPageV1.model_validate(
            {"items": [asset], "nextCursor": "c" * 2049}
        )
    page = spatial_data_ai.SpatialDataAssetPageV1.model_validate(
        {"items": [asset], "nextCursor": "opaque-cursor"}
    )
    assert page.next_cursor == "opaque-cursor"

"""Private capabilities cannot introduce arbitrary transport headers or identities."""

import base64
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from ksi_event_contracts.spatial_data import SpatialDataErrorV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataCompleteRequestV1,
    SpatialDataFailureRequestV1,
    SpatialDataLeaseViewV1,
    SpatialDataRenewRequestV1,
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
    SpatialDataUploadDeclarationV1,
    SpatialDataWorkerInputV1,
)
from pydantic import ValidationError
from spatial_data_fixture import (
    DIGEST,
    NOW,
    make_activation,
    make_attempt,
    make_job,
    make_receipt,
    make_runtime,
)
from test_spatial_data_contracts import _validator


def source_cap(**overrides: Any) -> SpatialDataSourceCapabilityV1:
    payload = dict(
        artifact_id="artifact-local",
        source_digest=make_job().source.source_digest,
        observed_sha256=DIGEST,
        observed_size_bytes=4096,
        download_url="https://store.invalid/exact-object?signature=local-fixture",
        required_headers=(),
        expires_at=NOW + timedelta(seconds=5),
    )
    payload.update(overrides)
    return SpatialDataSourceCapabilityV1.model_validate(payload)


def upload_cap(**overrides: Any) -> SpatialDataUploadCapabilityV1:
    receipt = make_receipt()
    checksum = base64.b64encode(bytes.fromhex(receipt.output_sha256[7:])).decode("ascii")
    payload = dict(
        receipt_digest=receipt.receipt_digest,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
        upload_url="https://store.invalid/exact-output?signature=local-fixture",
        required_headers=(
            {"name": "Content-Type", "value": "image/tiff"},
            {"name": "Content-Length", "value": "128"},
            {"name": "x-amz-checksum-sha256", "value": checksum},
        ),
        expires_at=NOW + timedelta(seconds=5),
    )
    payload.update(overrides)
    return SpatialDataUploadCapabilityV1.model_validate(payload)


def worker_input(**overrides: Any) -> SpatialDataWorkerInputV1:
    payload = dict(
        job=make_job(),
        attempt=make_attempt(),
        runtime=make_runtime(),
        activation=make_activation(),
        source_capability=source_cap(),
    )
    payload.update(overrides)
    return SpatialDataWorkerInputV1.model_validate(payload)


@pytest.mark.parametrize("factory", [source_cap, upload_cap, worker_input])
def test_private_capability_and_input_roundtrip_schema(factory: Callable[..., Any]) -> None:
    record = factory()
    _validator(type(record).__name__, "spatial-data-worker").validate(
        record.model_dump(by_alias=True, mode="json")
    )
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    "url",
    [
        "file:///data",
        "https://user:pass@store.invalid/file",
        "https://store.invalid/#fragment",
        "https://store.invalid:bad/file",
        "https://store.invalid/\r\nAuthorization:token",
        "https://store.invalid\\evil/path",
        "//store.invalid/file",
    ],
)
def test_capability_refuses_credentialed_non_http_and_control_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        source_cap(download_url=url)
    with pytest.raises(ValidationError):
        upload_cap(upload_url=url)


@pytest.mark.parametrize(
    "headers",
    [
        ({"name": "Authorization", "value": "Bearer secret"},),
        ({"name": "Cookie", "value": "secret"},),
        ({"name": "Host", "value": "other.invalid"},),
        ({"name": "x-amz-checksum-mode", "value": "ENABLED\r\nAuthorization:secret"},),
        (
            {"name": "x-amz-checksum-mode", "value": "ENABLED"},
            {"name": "X-Amz-Checksum-Mode", "value": "ENABLED"},
        ),
    ],
)
def test_no_arbitrary_sensitive_duplicate_or_injected_headers(headers: Any) -> None:
    with pytest.raises(ValidationError):
        source_cap(required_headers=headers)


def test_required_headers_are_immutable_and_transport_mapping_is_a_copy() -> None:
    cap = upload_cap()
    with pytest.raises(ValidationError):
        cap.required_headers[0].value = "text/plain"
    headers = cap.header_mapping()
    headers["Content-Type"] = "text/plain"
    assert cap.header_mapping()["Content-Type"] == "image/tiff"


@pytest.mark.parametrize(
    "headers",
    [
        (),
        ({"name": "Content-Type", "value": "image/tiff"},),
        (
            {"name": "Content-Type", "value": "image/tiff"},
            {"name": "Content-Length", "value": "129"},
            {"name": "x-amz-checksum-sha256", "value": "invalid"},
        ),
    ],
)
def test_upload_requires_exact_size_type_and_full_sha256_headers(headers: Any) -> None:
    with pytest.raises(ValidationError):
        upload_cap(required_headers=headers)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_capability": source_cap(observed_sha256="sha256:" + "0" * 64)},
        {"source_capability": source_cap(observed_size_bytes=4097)},
        {"source_capability": source_cap(expires_at=NOW + timedelta(seconds=6))},
        {"source_capability": source_cap(expires_at=NOW)},
        {"attempt": make_attempt(frozen_job_digest="sha256:" + "0" * 64)},
        {"runtime": make_runtime(build_digest="sha256:" + "0" * 64)},
        {"activation": make_activation(worker_instance_id="other")},
        {"activation": make_activation(organization_id="foreign")},
    ],
)
def test_worker_input_rejects_source_attempt_runtime_or_expiry_substitution(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        worker_input(**changes)


def test_upload_declaration_and_completion_refuse_worker_storage_coordinates() -> None:
    receipt = make_receipt()
    declaration = SpatialDataUploadDeclarationV1(
        attempt=make_attempt(),
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
    ).sealed()
    assert declaration.upload_digest == declaration.canonical_digest()
    completion = SpatialDataCompleteRequestV1(
        attempt=make_attempt(), upload_digest=declaration.upload_digest
    )
    _validator(type(completion).__name__, "spatial-data-worker").validate(
        completion.model_dump(by_alias=True, mode="json")
    )
    for field in ("versionId", "objectKey", "outputUrl"):
        with pytest.raises(ValidationError):
            type(completion).model_validate({**completion.model_dump(), field: "caller-location"})
    with pytest.raises(ValidationError):
        SpatialDataUploadDeclarationV1.model_validate(
            {**declaration.model_dump(), "size_bytes": 129, "upload_digest": None}
        )


@pytest.mark.parametrize(
    "reason,retryable",
    [
        ("STORAGE_UNAVAILABLE", True),
        ("SOURCE_UNAVAILABLE", False),
        ("INTEGRITY_MISMATCH", False),
        ("UNSUPPORTED_SOURCE_PROFILE", False),
    ],
)
def test_worker_failure_retries_only_allowlisted_transport(reason: Any, retryable: bool) -> None:
    failure = SpatialDataFailureRequestV1(
        attempt=make_attempt(), reason=reason, retryable=retryable
    )
    assert failure.retryable == retryable
    with pytest.raises(ValidationError):
        SpatialDataFailureRequestV1(attempt=make_attempt(), reason=reason, retryable=not retryable)
    with pytest.raises(ValidationError):
        SpatialDataFailureRequestV1.model_validate(
            {"attempt": make_attempt(), "reason": "ARBITRARY", "retryable": False}
        )


def test_error_envelope_has_typed_safe_remediation_no_exception_details() -> None:
    error = SpatialDataErrorV1(
        reason="CURRENTNESS_UNAVAILABLE",
        message="Access cannot be checked",
        retryable=True,
        remediation=("CONTACT_OPERATOR",),
    )
    _validator(type(error).__name__, "spatial-data").validate(
        error.model_dump(by_alias=True, mode="json")
    )
    with pytest.raises(ValidationError):
        SpatialDataErrorV1.model_validate({**error.model_dump(), "traceback": "private-path"})


@pytest.mark.parametrize(
    "model",
    [
        SpatialDataCompleteRequestV1,
        SpatialDataRenewRequestV1,
        SpatialDataFailureRequestV1,
        SpatialDataLeaseViewV1,
    ],
)
def test_worker_operations_require_sealed_attempt(model: Any) -> None:
    attempt = make_attempt().model_copy(update={"attempt_digest": None})
    payload = {
        SpatialDataCompleteRequestV1: dict(attempt=attempt, upload_digest=DIGEST),
        SpatialDataRenewRequestV1: dict(attempt=attempt),
        SpatialDataFailureRequestV1: dict(
            attempt=attempt, reason="INTEGRITY_MISMATCH", retryable=False
        ),
        SpatialDataLeaseViewV1: dict(attempt=attempt, job_id=attempt.job_id),
    }[model]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_worker_input_origin_and_activation_expiry_are_independent_gates() -> None:
    with pytest.raises(ValidationError):
        worker_input(source_capability=source_cap(download_url="https://other.invalid/file"))
    with pytest.raises(ValidationError):
        worker_input(activation=make_activation(valid_until=NOW + timedelta(seconds=4)))


def test_signed_activation_domain_is_not_analysis_and_binds_full_snapshot() -> None:
    import json

    activation = make_activation()
    signed = json.loads(activation.signing_bytes())
    assert signed["domain"] == "ksi-spatial-data-activation.v1"
    assert signed["payload"] == activation.model_dump(by_alias=True, mode="json")

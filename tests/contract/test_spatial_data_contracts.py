"""Contract boundaries: coercion, authority tampering and schema concordance."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema
from spatial_data_fixture import (
    NOW,
    make_activation,
    make_grant,
    make_policy,
    make_request,
    make_revocation,
    make_runtime,
)

ROOT = Path(__file__).resolve().parents[2]


def _validator(name: str, module: str) -> Draft202012Validator:
    schema = json.loads((ROOT / f"contracts/schemas/{module}.v1.json").read_text())
    return Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}, format_checker=FormatChecker()
    )


def test_strict_request_and_policy() -> None:
    assert make_request().resolution_mode == "NATIVE"
    assert make_policy().stream_chunk_bytes == 512
    with pytest.raises(ValidationError):
        make_request(requested_bounds=(True, 0, 1, 1))
    with pytest.raises(ValidationError):
        make_policy(stream_chunk_bytes=0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("assetRef", "not-an-asset"),
        ("observedCrsDigest", "a" * 64),
        ("purpose", "TRAINING"),
        ("resolutionMode", "RESAMPLED"),
        ("objectKey", "secret"),
        ("requestedBounds", [True, 0, 1, 1]),
        ("requestedBounds", ["0", 0, 1, 1]),
        ("requestedBounds", [0, 0, 1]),
        ("requestedBounds", [0, 0, 1, 1, 2]),
        ("requestedBounds", [0, 0, float("inf"), 1]),
    ],
)
def test_request_model_and_schema_reject_hostile_shape(field: str, value: Any) -> None:
    request = make_request()
    payload = request.model_dump(by_alias=True, mode="json")
    payload[field] = value
    assert not _validator(type(request).__name__, "spatial-data").is_valid(payload)
    with pytest.raises(ValidationError):
        type(request).model_validate(payload)


@pytest.mark.parametrize(
    "bounds",
    [
        (0, 0, 0, 1),
        (0, 0, 1, 0),
        (1, 0, 0, 1),
        (0, 2, 1, 1),
        (0, 0, float("nan"), 1),
        (0, 0, -float("inf"), 1),
    ],
)
def test_request_rejects_empty_reversed_or_nonfinite_geometry(bounds: Any) -> None:
    with pytest.raises(ValidationError):
        make_request(requested_bounds=bounds)


@pytest.mark.parametrize(
    "field",
    [
        "max_output_pixels",
        "max_output_bytes",
        "stream_chunk_bytes",
        "max_stream_bytes",
        "stream_deadline_seconds",
        "max_active_jobs_per_organization",
        "max_active_downloads_per_organization",
        "max_pending_records",
        "max_list_records",
        "max_snapshot_bytes",
        "max_json_bytes",
        "max_idempotency_key_bytes",
        "lease_seconds",
        "max_attempts",
        "min_retry_backoff_seconds",
        "max_retry_backoff_seconds",
        "retention_seconds",
        "max_cleanup_attempts",
        "cleanup_deadline_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, "1", float("inf"), float("nan")])
def test_policy_budgets_are_positive_finite_uncoerced_and_required(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        make_policy(**{field: value})
    policy = make_policy()
    payload = policy.model_dump(by_alias=True, mode="json")
    alias = type(policy).model_fields[field].alias
    assert alias is not None
    del payload[alias]
    with pytest.raises(ValidationError):
        type(policy).model_validate(payload)
    assert not _validator(type(policy).__name__, "spatial-data-authority").is_valid(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"stream_chunk_bytes": 4097},
        {"max_stream_bytes": 256},
        {"max_output_pixels": 4097},
        {"max_output_bytes": 8193},
        {"lease_seconds": 31.0},
        {"max_attempts": 4},
        {"max_active_jobs_per_organization": 3},
        {"max_pending_records": 9},
        {"min_retry_backoff_seconds": 6.0},
        {"max_json_bytes": 1_048_577},
    ],
)
def test_policy_rejects_cross_field_overcommit(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_policy(**override)


@pytest.mark.parametrize(
    "factory", [make_policy, make_grant, make_runtime, make_activation, make_revocation]
)
def test_canonical_digest_detects_tampering_and_unchecked_copy(factory: Callable[..., Any]) -> None:
    record = factory()
    own_digest = {
        make_policy: "policy_digest",
        make_grant: "grant_digest",
        make_runtime: "runtime_digest",
        make_activation: "activation_digest",
        make_revocation: "revocation_digest",
    }[factory]
    payload = record.model_dump(by_alias=True, mode="json", exclude={own_digest})
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    assert record.canonical_digest() == expected == getattr(record, own_digest)
    tampered = record.model_dump()
    tampered[own_digest] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        type(record).model_validate(tampered)
    with pytest.raises(ValidationError):
        record.model_copy(update={own_digest: "sha256:" + "0" * 64}).canonical_digest()
    with pytest.raises(ValidationError):
        record.model_copy(update={own_digest: "sha256:" + "0" * 64}).sealed()


@pytest.mark.parametrize("factory", [make_grant, make_activation])
def test_authority_half_open_currentness_and_utc(factory: Callable[..., Any]) -> None:
    record = factory()
    assert record.is_current_at(NOW)
    assert not record.is_current_at(NOW - timedelta(microseconds=1))
    assert not record.is_current_at(record.valid_until)
    with pytest.raises(ValueError):
        record.is_current_at(datetime(2026, 10, 1))
    for value in (datetime(2026, 10, 1), "2026-10-01T01:00:00+01:00", 1_790_000_000):
        with pytest.raises(ValidationError):
            factory(valid_from=value)
    with pytest.raises(ValidationError):
        factory(valid_until=NOW)


@pytest.mark.parametrize(
    "override",
    [
        {"operations": ()},
        {"purposes": ()},
        {"operations": ("READ", "READ")},
        {"purposes": ("TRAINING",)},
        {"processing_location": "unknown"},
        {"attribution": ""},
        {"license_provenance_digest": None},
        {"allowed_bounds": (0, 0, True, 1)},
        {"revision": True},
    ],
)
def test_grant_requires_explicit_nonempty_rights(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_grant(**override)


@pytest.mark.parametrize(
    "origin",
    [
        "file:///store",
        "https://user:password@store.invalid",
        "https://store.invalid/path",
        "https://store.invalid?token=secret",
        "https://store.invalid#fragment",
        "https://store.invalid:bad",
        "https://store.invalid\n",
        "//store.invalid",
    ],
)
def test_activation_refuses_noncanonical_or_credentialed_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_activation(trusted_endpoint_origins=(origin,))


@pytest.mark.parametrize(
    "factory,module",
    [
        (make_request, "spatial-data"),
        (make_policy, "spatial-data-authority"),
        (make_grant, "spatial-data-authority"),
        (make_runtime, "spatial-data-authority"),
        (make_activation, "spatial-data-authority"),
        (make_revocation, "spatial-data-authority"),
    ],
)
def test_generated_schema_accepts_wire_and_forbids_extra(
    factory: Callable[..., Any], module: str
) -> None:
    record = factory()
    payload = record.model_dump(by_alias=True, mode="json")
    validator = _validator(type(record).__name__, module)
    validator.validate(payload)
    payload["callerAuthority"] = True
    assert not validator.is_valid(payload)
    with pytest.raises(ValidationError):
        type(record).model_validate(payload)


@pytest.mark.parametrize(
    "module", ["spatial_data", "spatial_data_authority", "spatial_data_worker"]
)
def test_schema_is_exactly_generated_from_exported_models(module: str) -> None:
    import importlib

    from ksi_event_contracts._spatial_data import SpatialDataModel

    namespace = importlib.import_module(f"ksi_event_contracts.{module}")
    models: list[tuple[type[SpatialDataModel], Literal["validation"]]] = [
        (value, "validation")
        for value in vars(namespace).values()
        if isinstance(value, type)
        and issubclass(value, SpatialDataModel)
        and value.__module__ == namespace.__name__
        and not value.__name__.startswith("_")
    ]
    _, expected = models_json_schema(models, by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    path = ROOT / f"contracts/schemas/{module.replace('_', '-')}.v1.json"
    actual = json.loads(path.read_text())
    assert actual == expected
    Draft202012Validator.check_schema(actual)


def test_nested_envelope_cannot_overcommit_workspace_or_be_unsealed() -> None:
    from spatial_data_fixture import make_envelope

    with pytest.raises(ValidationError):
        make_policy(resource_envelope=make_envelope(max_workspace_bytes=20_479))
    envelope = make_envelope().model_copy(update={"resource_envelope_digest": None})
    with pytest.raises(ValidationError):
        make_policy(resource_envelope=envelope)


@pytest.mark.parametrize("field", ["assetRef", "observedCrsDigest"])
def test_digest_schema_refuses_trailing_newline(field: str) -> None:
    request = make_request()
    payload = request.model_dump(by_alias=True, mode="json")
    payload[field] += "\n"
    assert not _validator(type(request).__name__, "spatial-data").is_valid(payload)
    with pytest.raises(ValidationError):
        type(request).model_validate(payload)

"""Closed delta API contract must not accept source/grid/bytes coercion."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts.external_delta_publication_api import (
    CreateDeltaPublicationV1,
    DeltaOutputObservationWireV1,
    DeltaPublicationBytesV1,
)
from pydantic import ValidationError
from test_external_delta_publications import _observation


def test_worker_wire_observation_matches_the_core_canonical_receipt_without_reinterpretation(
) -> None:
    receipt = _observation(b"unit-only-payload")
    model = DeltaOutputObservationWireV1.model_validate(asdict(receipt))
    assert model.observation_digest == receipt.canonical_digest()
    assert (
        model.model_dump(by_alias=True, mode="json", exclude={"observation_digest"})
        == receipt.canonical_payload()
    )
    with pytest.raises(ValidationError):
        DeltaOutputObservationWireV1.model_validate(
            {**model.model_dump(), "output_size_bytes": True}
        )
    with pytest.raises(ValidationError):
        DeltaOutputObservationWireV1.model_validate({**model.model_dump(), "dtype": "FLOAT32"})


def test_source_only_request_rejects_undeclared_grid_and_resource_coercion() -> None:
    payload = {
        "publicationId": "pub-01",
        "sourceCalculationIdentityDigest": "sha256:" + "a" * 64,
        "sourceNumericResultIdentityDigest": "sha256:" + "b" * 64,
        "sourceCoverageWitnessDigest": "sha256:" + "c" * 64,
        "lifetimeSeconds": 60,
    }
    assert CreateDeltaPublicationV1.model_validate(payload).lifetime_seconds == 60
    for bad in (
        {"gridRows": 4},
        {"downloadUrl": "file:///not-allowed"},
        {"lifetimeSeconds": True},
        {"lifetimeSeconds": "60"},
    ):
        with pytest.raises(ValidationError):
            CreateDeltaPublicationV1.model_validate({**payload, **bad})


def test_byte_slices_reject_bad_encoding_noncanonical_pad_bits_and_oversize() -> None:
    assert DeltaPublicationBytesV1(publication_id="pub", offset=0, content_base64="YQ==")
    for raw in ("YR==", "YQ", "YQ==\n", "!!!!", "eA==" * 400000):
        with pytest.raises(ValidationError):
            DeltaPublicationBytesV1(publication_id="pub", offset=0, content_base64=raw)


def test_checked_in_schema_matches_generator_and_accepts_closed_observation() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "delta_schema_generator", root / "tools/generate_delta_publication_api_schema.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = json.loads(
        (root / "contracts/schemas/external-delta-publication-api.v1.json").read_text()
    )
    assert schema == module.schema()
    Draft202012Validator.check_schema(schema)
    value = DeltaOutputObservationWireV1.model_validate(asdict(_observation(b"unit"))).model_dump(
        by_alias=True,
        mode="json",
    )
    Draft202012Validator(schema).validate(value)
    assert list(Draft202012Validator(schema).iter_errors({**value, "userDeclaredInspection": True}))

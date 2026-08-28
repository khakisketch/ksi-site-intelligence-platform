"""Immutable KSI processing profile contract and registry gates (ADR-KSI-030)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_core.processing_profiles import (
    KSI_NODEODM_IMAGE_DIGEST,
    KSI_ODM_CIVIL_V1_ID,
    ProcessingProfileRegistry,
    UnknownProcessingProfileError,
    ksi_odm_civil_v1,
)
from ksi_event_contracts.processing_profile import (
    ProcessingProfileV1,
    processing_profile_wire_dict,
)


def test_ksi_odm_civil_v1_is_canonical_and_matches_schema() -> None:
    profile = ksi_odm_civil_v1()
    wire = processing_profile_wire_dict(profile)
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts/schemas/processing-profile.v1.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    assert wire["processingProfileId"] == KSI_ODM_CIVIL_V1_ID
    assert wire["ociImageDigest"] == KSI_NODEODM_IMAGE_DIGEST
    assert wire["preprocessing"]["dynamicObjectMasking"] is False
    assert wire["profileDigest"] == profile.canonical_digest()
    assert ProcessingProfileV1.model_validate(wire).profile_digest == wire["profileDigest"]


def test_profile_digest_is_deterministic_and_tampering_is_rejected() -> None:
    profile = ksi_odm_civil_v1()
    assert profile.canonical_digest() == ksi_odm_civil_v1().canonical_digest()
    forged = processing_profile_wire_dict(profile)
    forged["processingParams"]["pc-quality"] = "ultra"
    with pytest.raises(ValueError, match="processingProfileDigest"):
        ProcessingProfileV1.model_validate(forged)


def test_registry_never_resolves_an_unissued_profile() -> None:
    registry = ProcessingProfileRegistry()
    assert registry.get(KSI_ODM_CIVIL_V1_ID).profile_digest == ksi_odm_civil_v1().profile_digest
    with pytest.raises(UnknownProcessingProfileError):
        registry.get("customer-supplied-odm")


def test_registry_returns_defensive_copies_of_nested_profile_state() -> None:
    registry = ProcessingProfileRegistry()
    original_digest = registry.get(KSI_ODM_CIVIL_V1_ID).profile_digest

    caller_copy = registry.get(KSI_ODM_CIVIL_V1_ID)
    caller_copy.processing_params["pc-quality"] = "ultra"

    fresh = registry.get(KSI_ODM_CIVIL_V1_ID)
    assert fresh.processing_params["pc-quality"] == "medium"
    assert fresh.profile_digest == original_digest

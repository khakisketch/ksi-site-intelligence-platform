"""Replay-only historical processing-profile facts (Task 2).

The retired ODM recipe (``ksi_odm_civil_v1`` + ``ProcessingProfileRegistry``)
must never come back as an issuance path. This pins the replacement contract:
opaque (profile id, digest) facts that map to required artifact kinds only —
no image, no engine version, no params, no factory, no registry.
"""

from __future__ import annotations

import ksi_core.domains.processing.historical_processing_profiles as facts
import pytest
from ksi_core.domains.processing.historical_processing_profiles import (
    HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
    HISTORICAL_KSI_ODM_CIVIL_V1_ID,
    HISTORICAL_KSI_ODM_CIVIL_V1_REQUIRED_ARTIFACTS,
    UnknownHistoricalProcessingProfileError,
    historical_required_artifacts,
)


def test_historical_civil_binding_is_pinned() -> None:
    assert HISTORICAL_KSI_ODM_CIVIL_V1_ID == "ksi-odm-civil-v1"
    assert (
        HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST
        == "sha256:d19e3ce42e9cfd34cc504c651a8cc78d781a94f36040a58d525a5cfbd7586dc1"
    )
    assert HISTORICAL_KSI_ODM_CIVIL_V1_REQUIRED_ARTIFACTS == (
        "point_cloud",
        "dsm",
        "dtm",
    )


def test_known_binding_resolves_required_artifact_kinds() -> None:
    assert historical_required_artifacts(
        HISTORICAL_KSI_ODM_CIVIL_V1_ID,
        HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
    ) == ("point_cloud", "dsm", "dtm")


def test_unknown_profile_id_is_fail_closed() -> None:
    with pytest.raises(UnknownHistoricalProcessingProfileError):
        historical_required_artifacts(
            "customer-supplied-odm",
            HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
        )


def test_tampered_digest_is_fail_closed() -> None:
    with pytest.raises(UnknownHistoricalProcessingProfileError):
        historical_required_artifacts(
            HISTORICAL_KSI_ODM_CIVIL_V1_ID,
            "sha256:" + "0" * 64,
        )


def test_facts_module_carries_no_issuance_surface() -> None:
    """No recipe, factory, registry, image, engine, or params may live here."""
    for name in (
        "ksi_odm_civil_v1",
        "ProcessingProfileRegistry",
        "UnknownProcessingProfileError",
        "KSI_ODM_CIVIL_V1_ID",
        "KSI_NODEODM_IMAGE",
        "KSI_NODEODM_IMAGE_DIGEST",
        "ksi_civil_pilot_r1",
        "ProcessingResourcePolicyRegistry",
    ):
        assert not hasattr(facts, name), name

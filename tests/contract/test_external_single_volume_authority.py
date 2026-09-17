"""Single-volume compatibility record: sealed, bound to one epoch and one zone."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from ksi_core.domains.external.quantity.external_single_volume_authority import (
    ExternalSingleVolumeCompatibilityRecord,
    SingleVolumeCompatibilityRuleDescriptorV1,
)
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)

_NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest=_digest("submission-a"),
        manifest_digest=_digest("manifest-a"),
    )


def _binding() -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(),
        inspection_report_digest=_digest("inspection-a"),
        dsm_artifact_id="dsm-a",
        observed_sha256=_digest("dsm-bytes-a"),
        observed_size_bytes=16,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=_NOW,
        captured_to=_NOW + timedelta(hours=1),
    )


def _zone() -> ExternalVolumeZoneSnapshotV1:
    return ExternalVolumeZoneSnapshotV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
        },
        crs="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        analysis_vertical_reference_digest=_digest("vertical"),
    ).sealed()


def single_mapping() -> ExternalSingleVolumeCompatibilityRecord:
    return ExternalSingleVolumeCompatibilityRecord(
        organization_id="org-a",
        site_id="site-a",
        target=_binding(),
        zone_snapshot=_zone(),
        validation_policy_digest=_digest("validation-policy"),
        external_profile="external-geotiff-profile.v1",
        grammar_digest=_digest("grammar"),
        inspector_build_digest=_digest("inspector-build"),
        evidence_record_digests=(_digest("evidence-a"),),
        execution_policy_ref=_digest("execution-policy-authority"),
        valid_from=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(minutes=10),
    ).sealed()


def test_sealed_record_round_trips_through_its_event_payload() -> None:
    record = single_mapping()
    assert record.mapping_digest == record.canonical_digest()
    payload = {"mappingRecordDigest": record.mapping_digest, **record.canonical_payload()}
    assert ExternalSingleVolumeCompatibilityRecord.from_event_payload(payload) == record
    assert (
        record.compatibility_rule_digest
        == SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest()
    )


def test_record_requires_exactly_one_evidence_record_and_matching_references() -> None:
    from dataclasses import replace

    base = single_mapping()
    with pytest.raises(ValueError, match="exactly one evidence"):
        replace(
            base, evidence_record_digests=(_digest("x"), _digest("y")), mapping_record_digest=None
        )
    with pytest.raises(ValueError, match="references must match"):
        replace(
            base,
            target=_binding().model_copy(
                update={"observed_vertical_reference_digest": _digest("other")}
            ),
            mapping_record_digest=None,
        )
    with pytest.raises(ValueError, match="share organization and site"):
        replace(base, site_id="site-b", mapping_record_digest=None)


def test_rule_digest_differs_from_the_pair_rule() -> None:
    from ksi_core.external_quantitative_authority import CompatibilityRuleDescriptorV1

    assert (
        SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest()
        != CompatibilityRuleDescriptorV1().canonical_digest()
    )

"""Sealing unrelated evidence never binds it to an epoch's uncertainty."""

from datetime import UTC, datetime
from typing import Any

import pytest
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
)
from test_external_measurement_protocol import launch_volume


def with_records(mutation: str | None = None) -> Any:
    launch = launch_volume()
    assert launch.volume_request is not None
    assert launch.validation_policy.policy_digest is not None
    records = []
    for index, binding in enumerate(
        (launch.volume_request.baseline, launch.volume_request.current)
    ):
        subject = binding.subject.canonical_digest()
        dsm = binding.observed_sha256
        policy = launch.validation_policy.policy_digest
        if index == 0:
            if mutation == "subject":
                subject = "sha256:" + "3" * 64
            if mutation == "dsm":
                dsm = "sha256:" + "3" * 64
            if mutation == "policy":
                policy = "sha256:" + "3" * 64
        payload = ExternalEvidenceMeasurementPayloadV1(
            validation_id=f"validation-{index}",
            evidence_manifest_digest="sha256:" + str(index) * 64,
            target_dsm_observed_sha256=dsm,
            policy_digest=policy,
            measured_checkpoint_count=3,
            mean_error_m=0.1,
            mae_m=0.1,
            rmse_m=0.1,
            max_abs_error_m=0.1,
            measured_at=datetime(2026, 9, 9, tzinfo=UTC),
        )
        records.append(
            ExternalEvidenceRecordV1(
                evidence_record_id=f"record-{index}",
                validation_id=payload.validation_id,
                subject_digest=subject,
                evidence_manifest_digest=payload.evidence_manifest_digest,
                target_dsm_observed_sha256=dsm,
                policy_digest=policy,
                measurement_payload=payload,
                core_verdict=EvidenceCoreVerdict.VALIDATED,
                core_recorded_at=payload.measured_at,
            ).sealed()
        )
    if mutation == "order":
        records.reverse()
    if mutation == "cardinality":
        records = records[:1]
    if mutation == "duplicate":
        records[1] = (
            records[0]
            .model_copy(
                update={
                    "evidence_record_id": "distinct-id-same-epoch",
                    "evidence_record_digest": None,
                }
            )
            .sealed()
        )
    request = launch.volume_request.model_copy(
        update={
            "evidence_record_digests": tuple(r.evidence_record_digest for r in records),
            "request_digest": None,
        }
    ).sealed()
    return launch.model_copy(
        update={
            "volume_request": request,
            "volume_evidence_records": tuple(records),
            "canonical_input_digest": None,
        }
    ).sealed()


def test_exact_ordered_records_bind_to_two_epochs() -> None:
    assert len(with_records().volume_evidence_records) == 2


@pytest.mark.parametrize(
    "mutation", ["subject", "dsm", "policy", "order", "duplicate", "cardinality"]
)
def test_self_consistent_unrelated_records_are_rejected(mutation: str) -> None:
    with pytest.raises(ValueError, match="evidence|record"):
        with_records(mutation)

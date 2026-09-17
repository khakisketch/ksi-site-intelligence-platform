"""The single-volume review receipt binds one exact, sealed single-epoch source.

Synthetic digests only.  These tests establish neither Core authorization nor
review currentness; they pin the immutable receipt shape, its fail-closed
bindings, the receipt union discriminator and the unchanged relative digest.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from external_single_volume_contract_fixture import (
    _NOW,
    _binding,
    _decision,
    _digest,
    _policy,
    _report,
    _request,
    _subject,
    _zone,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import DecisionVerdict
from ksi_event_contracts.external_result_review import (
    ExternalResultReviewReceiptV1,
    external_result_review_receipt_wire_dict,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
)
from ksi_event_contracts.external_single_volume_result_review import (
    SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS,
    ExternalSingleVolumeResultReviewAuthorityV1,
    ExternalSingleVolumeResultReviewReceiptV1,
    external_single_volume_result_review_receipt_wire_dict,
    parse_external_result_review_receipt,
)
from pydantic import ValidationError
from test_external_result_review_proposals import _NOW as _RELATIVE_NOW
from test_external_result_review_proposals import _sealed_source

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "contracts/schemas/external-single-volume-result-review-receipt.v1.json"
)
_RELATIVE_POLYGON: dict[str, object] = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
}
_RELATIVE_LIMITATIONS = (
    "RELATIVE_VOLUME_IS_OPERATIONAL_ONLY",
    "ABSOLUTE_ACCURACY_NOT_CLAIMED",
    "NO_AUTOMATIC_REOBSERVATION_THRESHOLD",
)
# Computed from the relative fixture below before the single-volume receipt existed.
_PINNED_RELATIVE_REVIEW_DIGEST = (
    "sha256:92b34f5aebdd005b9a376d8f1d11eafe024029d5d2d1a409629a887dfd494b93"
)


def _authority(
    decision: ExternalSingleVolumeDecisionV1, **update: Any
) -> ExternalSingleVolumeResultReviewAuthorityV1:
    assert decision.decision_digest is not None
    fields: dict[str, Any] = {
        "organization_id": "organization-1",
        "site_id": "site-1",
        "current_work_order_id": "work-order-1",
        "decision_id": "decision-1",
        "decision_digest": decision.decision_digest,
        "compatibility_mapping_digest": _digest("7"),
        "target": _binding(),
        "evidence_record_digests": (_digest("6"),),
        "validation_policy_digest": _digest("5"),
        "zone_snapshot": _zone(),
        "execution_policy": _policy(),
        "authorized_actor_ids": ("operator-1",),
        "valid_from": _NOW - timedelta(days=1),
        "valid_until": _NOW + timedelta(days=1),
        "historical_authority_digest": _digest("b"),
        "target_rmse_m": 0.02,
        "maximum_zone_cell_count": 1_000,
        "maximum_zone_area_m2": 1_000.0,
        "synthetic_test_only": True,
    }
    fields.update(update)
    return ExternalSingleVolumeResultReviewAuthorityV1(**fields).sealed()


def _resealed_request(
    decision: ExternalSingleVolumeDecisionV1, **update: Any
) -> ExternalSingleVolumeRequestV1:
    return (
        _request()
        .model_copy(
            update={"decision_digest": decision.decision_digest, **update, "request_digest": None},
            deep=True,
        )
        .sealed()
    )


def _resealed_report(
    report: ExternalSingleVolumeReportV1,
    *,
    payload: dict[str, Any] | None = None,
    **update: Any,
) -> ExternalSingleVolumeReportV1:
    return report.model_copy(
        update={
            "payload": report.payload.model_copy(update=payload or {}),
            **update,
            "measurement_payload_digest": None,
            "report_digest": None,
        },
        deep=True,
    ).sealed()


def _receipt(
    *,
    decision: ExternalSingleVolumeDecisionV1 | None = None,
    request_update: dict[str, Any] | None = None,
    report_payload_update: dict[str, Any] | None = None,
    report_update: dict[str, Any] | None = None,
    other_report_request_update: dict[str, Any] | None = None,
    receipt_update: dict[str, Any] | None = None,
) -> ExternalSingleVolumeResultReviewReceiptV1:
    decision = _decision() if decision is None else decision
    request = _resealed_request(decision, **(request_update or {}))
    report = _report(request)
    if other_report_request_update is not None:
        report = _report(_resealed_request(decision, **other_report_request_update))
    if report_payload_update is not None or report_update is not None:
        report = _resealed_report(report, payload=report_payload_update, **(report_update or {}))
    fields: dict[str, Any] = {
        "review_ref": "review-1",
        "organization_id": "organization-1",
        "site_id": "site-1",
        "source_work_order_id": "work-order-1",
        "report_ref": "external-single-volume-report-1",
        "request": request,
        "report": report,
        "authority": _authority(decision),
        "decision": decision,
        "factual_limitations": SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS,
        "reviewed_at": _NOW,
    }
    fields.update(receipt_update or {})
    return ExternalSingleVolumeResultReviewReceiptV1(**fields).sealed()


def _decision_with(**update: Any) -> ExternalSingleVolumeDecisionV1:
    return _decision().model_copy(update={**update, "decision_digest": None}, deep=True).sealed()


def _relative_receipt() -> ExternalResultReviewReceiptV1:
    source = _sealed_source(
        source_work_order_id="work-current",
        work_area_id="zone-a",
        polygon=_RELATIVE_POLYGON,
    )
    return ExternalResultReviewReceiptV1(
        review_ref="review-a",
        organization_id="org-a",
        site_id="site-a",
        source_work_order_id="work-current",
        report_ref=source.report_ref,
        request=source.request,
        report=source.report,
        authority=source.authority,
        decision=source.decision,
        factual_limitations=_RELATIVE_LIMITATIONS,
        reviewed_at=_RELATIVE_NOW,
    ).sealed()


def test_receipt_seals_and_round_trips() -> None:
    receipt = _receipt()
    assert receipt.contract_version == "external-single-volume-result-review-receipt.v1"
    assert receipt.authority.contract_version == "external-single-volume-result-review-authority.v1"
    assert receipt.review_digest == receipt.canonical_digest()
    assert receipt.authority.authority_digest == receipt.authority.canonical_digest()
    assert receipt.authority.is_active_at(_NOW)
    assert not receipt.authority.is_active_at(_NOW + timedelta(days=1))
    assert receipt.factual_limitations == (
        "SINGLE_VOLUME_IS_OPERATIONAL_ONLY",
        "ABSOLUTE_ACCURACY_NOT_CLAIMED",
        "NO_AUTOMATIC_REOBSERVATION_THRESHOLD",
    )
    wire = external_single_volume_result_review_receipt_wire_dict(receipt)
    assert ExternalSingleVolumeResultReviewReceiptV1.model_validate(wire) == receipt
    assert _receipt().review_digest == receipt.review_digest


_OTHER_ZONE = _zone().model_copy(update={"work_area_id": "zone-2", "definition_digest": None})

_BROKEN_BINDINGS: dict[str, dict[str, Any]] = {
    "request target differs from authority": {
        "request_update": {
            "target": _binding().model_copy(update={"dsm_artifact_id": "dsm-2"}),
        }
    },
    "request evidence differs from authority": {
        "request_update": {"evidence_record_digests": (_digest("9"),)}
    },
    "validation policy digest mismatch": {
        "request_update": {"validation_policy_digest": _digest("9")}
    },
    "zone snapshot mismatch": {"request_update": {"zone_snapshot": _OTHER_ZONE.sealed()}},
    "execution policy digest mismatch": {
        "request_update": {"execution_policy_digest": _digest("9")}
    },
    "report request id mismatch": {"report_update": {"request_id": "other-request"}},
    "report request digest mismatch": {"other_report_request_update": {"idempotency_key": "key-2"}},
    "payload target dsm digest mismatch": {
        "report_payload_update": {"target_dsm_digest": _digest("9")}
    },
    "payload zone snapshot digest mismatch": {
        "report_payload_update": {"zone_snapshot_digest": _digest("9")}
    },
    "payload execution policy digest mismatch": {
        "report_payload_update": {"execution_policy_digest": _digest("9")}
    },
    "payload algorithm build digest mismatch": {
        "report_payload_update": {"algorithm_build_digest": _digest("9")}
    },
    "payload config digest mismatch": {"report_payload_update": {"config_digest": _digest("9")}},
    "decision not eligible": {"decision": _decision(verdict=DecisionVerdict.RESTRICTED)},
    "decision subject differs from target": {
        "decision": _decision_with(
            subject=_subject().model_copy(update={"submission_id": "submission-2"}),
            subject_digest=_subject()
            .model_copy(update={"submission_id": "submission-2"})
            .canonical_digest(),
        )
    },
    "decision inspection report differs from target": {
        "decision": _decision_with(inspection_report_digest=_digest("9"))
    },
    "decision evidence differs from request": {
        "decision": _decision_with(evidence_record_digests=(_digest("9"),))
    },
    "decision zone differs from request zone": {
        "decision": _decision_with(zone=_OTHER_ZONE.sealed().to_zone_reference())
    },
    "decision mapping differs from authority": {
        "decision": _decision_with(compatibility_mapping_digest=_digest("9"))
    },
    "source work order differs from request": {
        "receipt_update": {"source_work_order_id": "work-order-2"}
    },
    "relative factual limitations": {
        "receipt_update": {"factual_limitations": _RELATIVE_LIMITATIONS}
    },
}


@pytest.mark.parametrize("broken", list(_BROKEN_BINDINGS), ids=list(_BROKEN_BINDINGS))
def test_receipt_rejects_each_broken_binding(broken: str) -> None:
    with pytest.raises(ValidationError, match="review (request|report|decision|factual) "):
        _receipt(**_BROKEN_BINDINGS[broken])


def test_union_dispatches_on_contract_version() -> None:
    relative_wire = external_result_review_receipt_wire_dict(_relative_receipt())
    single_wire = external_single_volume_result_review_receipt_wire_dict(_receipt())
    relative = parse_external_result_review_receipt(relative_wire)
    single = parse_external_result_review_receipt(single_wire)
    assert type(relative) is ExternalResultReviewReceiptV1
    assert type(single) is ExternalSingleVolumeResultReviewReceiptV1
    assert relative == _relative_receipt()
    assert single == _receipt()
    with pytest.raises(ValidationError):
        parse_external_result_review_receipt(
            {**single_wire, "contractVersion": "external-unknown-review-receipt.v1"}
        )
    # A relative body under the single discriminator must not be accepted.
    with pytest.raises(ValidationError):
        parse_external_result_review_receipt(
            {**relative_wire, "contractVersion": "external-single-volume-result-review-receipt.v1"}
        )


def test_relative_receipt_digest_is_unchanged() -> None:
    receipt = _relative_receipt()
    assert receipt.review_digest == _PINNED_RELATIVE_REVIEW_DIGEST
    assert (
        parse_external_result_review_receipt(
            external_result_review_receipt_wire_dict(receipt)
        ).review_digest
        == _PINNED_RELATIVE_REVIEW_DIGEST
    )


def test_schema_accepts_wire_and_rejects_extra_keys() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    wire = external_single_volume_result_review_receipt_wire_dict(_receipt())
    validator.validate(wire)
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**wire, "unexpected": 1})
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**wire, "authority": {**wire["authority"], "unexpected": 1}})
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**wire, "contractVersion": "external-result-review-receipt.v1"})
    relative_wire = external_result_review_receipt_wire_dict(_relative_receipt())
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(relative_wire)

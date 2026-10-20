"""V3 ingress for honestly incomplete metadata (ADR-KSI-036 D4, ADR-KSI-038 D4).

Covers the additive ``external-reconstruction-submission.v3`` contract only:
date-only or unknown capture timing, explicitly unknown producers (typed
nulls, never a fabricated version string), an honestly declared raw-photo
locus, and an upstream-source versus derivative-export provenance split.

Frozen V1/V2 schemas, digests, and replay are pinned here as unchanged, and
quantitative admission still refuses V3 epochs without exact UTC bounds with
typed blockers instead of inventing times.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
    InspectionVerdict,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionStore,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    ExternalRelativeVolumeAnalysisStore,
    _PreflightBlocked,
)
from ksi_core.domains.sites.work_areas import WorkAreaStatus
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV2,
    ExternalReconstructionSubmissionV3,
    external_reconstruction_submission_v3_wire_dict,
    parse_external_reconstruction_submission_v3,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import ValidationError
from support.external_artifact_inspection_fixtures import policy_template
from test_external_reconstruction_api import (
    _TOKEN,
    _client,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_V3_SCHEMA = "external-reconstruction-submission.v3.json"
_SHA_A = "a" * 64
_SHA_B = "b" * 64

# Frozen pins: V1/V2 meanings and digests must not move for V3.
_PINNED_V1_DIGEST = "sha256:cd1d1c6da7c2001014ad98b406567bd1662028c8bf5e36ec3fd508de9eeef8b9"
_PINNED_V2_DIGEST = "sha256:7637e074f8443b53c2e2dfb2d73a0b71d4a94b721f820fe4b4402ac479126d48"


def _v3_wire(
    *,
    epoch_id: str,
    submission_id: str = "datawa-2021-ortho",
    basis: str = "DATE_ONLY",
    locus: str = "unknown",
    submitted_by: str = "operator-a",
    with_provenance: bool = True,
) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "contractVersion": "external-reconstruction-submission.v3",
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": epoch_id,
        "submittedAt": "2026-10-20T00:00:00Z",
        "submittedBy": submitted_by,
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "producerKnowledge": "UNKNOWN",
            "softwareName": None,
            "softwareVersion": None,
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
            "sourceNote": "Publisher page states a date only; upstream software not identified.",
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": locus,
            "originalRetentionDetail": (
                "Only published derived bytes observed; raw-photo retention unknown — "
                "not asserted to be held by this customer workstation, KSI, or any upstream."
            ),
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
            "captureDate": "2021-08-17" if basis == "DATE_ONLY" else None,
            "captureBasis": basis,
            "upstreamSource": (
                {
                    "sourceUri": "https://data.wa.gov.au/floreat-f3-2021-ortho.jp2",
                    "sourceSha256": _SHA_A,
                    "licenceDeclaration": "Publisher-stated licence, transcribed only.",
                    "retrievalNote": (
                        "Original 4-band RGBA JPEG ortho; artifact is a derived GeoTIFF."
                    ),
                }
                if with_provenance
                else None
            ),
            "derivativeExport": (
                {
                    "toolName": "GDAL",
                    "toolVersion": "3.8.4",
                    "settingsDigest": None,
                    "exportedAt": None,
                    "exportNote": "Supported GeoTIFF export for product viewing.",
                }
                if with_provenance
                else None
            ),
        },
        "artifacts": [
            {
                "artifactId": "ortho-2021",
                "kind": "ortho",
                "fileName": "floreat-2021-ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(b"v3 ortho bytes").hexdigest(),
                "declaredSizeBytes": len(b"v3 ortho bytes"),
                "declaredCrs": "EPSG:7850",
                "declaredVerticalReference": None,
                "declaredGsdM": 0.1,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    return wire


def _schema(name: str) -> dict[str, Any]:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_v3_schema_file_is_explicit_draft_2020_12_contract() -> None:
    schema = _schema(_V3_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_v3_date_only_ortho_only_round_trips_schema_parser_and_digest() -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert parsed.contract_version == "external-reconstruction-submission.v3"
    assert parsed.input_declaration.capture_date is not None
    assert parsed.input_declaration.capture_started_at is None
    assert parsed.producer_declaration.producer_knowledge == "UNKNOWN"
    assert parsed.producer_declaration.software_name is None
    assert parsed.input_declaration.upstream_source is not None
    assert parsed.input_declaration.derivative_export is not None
    assert parsed.input_declaration.derivative_export.tool_name == "GDAL"
    assert (
        external_reconstruction_submission_v3_wire_dict(parsed)["submissionDigest"]
        == wire["submissionDigest"]
    )


def test_v3_dsm_only_with_exact_interval_and_customer_locus_round_trips() -> None:
    wire = _v3_wire(epoch_id="epoch-1", submission_id="v3-dsm-exact")
    wire["inputDeclaration"]["captureBasis"] = "EXACT_INTERVAL"
    wire["inputDeclaration"]["captureDate"] = None
    wire["producerDeclaration"] = {
        "producerKnowledge": "DECLARED",
        "softwareName": "Customer Mapper",
        "softwareVersion": "2026.9",
        "buildIdentifier": None,
        "producerRunIdentifier": "run-7",
        "configurationDigest": None,
        "completedAt": None,
        "sourceNote": None,
    }
    wire["inputDeclaration"]["originalRetentionLocus"] = "customer_workstation"
    wire["inputDeclaration"]["captureStartedAt"] = "2026-09-06T00:00:00Z"
    wire["inputDeclaration"]["captureEndedAt"] = "2026-09-06T00:10:00Z"
    wire["inputDeclaration"]["upstreamSource"] = None
    wire["inputDeclaration"]["derivativeExport"] = None
    wire["artifacts"] = [
        {
            "artifactId": "dsm-1",
            "kind": "dsm",
            "fileName": "surface.tif",
            "format": "GeoTIFF",
            "contentType": "application/octet-stream",
            "declaredSha256": _SHA_A,
            "declaredSizeBytes": 200,
            "declaredCrs": None,
            "declaredVerticalReference": None,
            "declaredGsdM": None,
        }
    ]
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert [a.kind for a in parsed.artifacts] == [ProcessingArtifactKind.DSM]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda w: w["producerDeclaration"].update({"softwareName": "Mapper"}),
            id="unknown-with-name",
        ),
        pytest.param(
            lambda w: w["producerDeclaration"].update({"softwareVersion": "1.0"}),
            id="unknown-with-version",
        ),
        pytest.param(
            lambda w: w["producerDeclaration"].update(
                {
                    "producerKnowledge": "DECLARED",
                    "softwareName": "unknown",
                    "softwareVersion": "1.0",
                }
            ),
            id="declared-fabricated-unknown-label",
        ),
        pytest.param(
            lambda w: w["producerDeclaration"].update({"producerKnowledge": "DECLARED"}),
            id="declared-without-version",
        ),
        pytest.param(
            lambda w: w["inputDeclaration"].update({"captureStartedAt": "2021-08-17T00:00:00Z"}),
            id="date-only-with-exact-start",
        ),
        pytest.param(
            lambda w: (
                w["inputDeclaration"].update({"captureBasis": "UNKNOWN", "captureDate": None})
                or w["inputDeclaration"].update({"captureStartedAt": "2021-08-17T00:00:00Z"})
            ),
            id="unknown-with-timestamp",
        ),
        pytest.param(
            lambda w: w["inputDeclaration"].update({"captureDate": "2021-08-17T00:00:00Z"}),
            id="date-carrying-a-timestamp",
        ),
        pytest.param(
            lambda w: w["inputDeclaration"].update({"originalRetentionLocus": "mars_station"}),
            id="unknown-locus-value",
        ),
        pytest.param(
            lambda w: w["inputDeclaration"].update({"captureBasis": "SOMETIME"}),
            id="unknown-basis-value",
        ),
        pytest.param(
            lambda w: w["artifacts"].__setitem__(slice(None), []),
            id="no-dsm-or-ortho",
        ),
    ],
)
def test_v3_rejects_invented_or_unbounded_fields(
    mutate: Any,
) -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    mutate(wire)
    wire.pop("submissionDigest", None)
    with pytest.raises((ValidationError, ValueError)):
        ExternalReconstructionSubmissionV3.model_validate(wire)


def test_v3_partial_producer_keeps_known_name_without_invented_version() -> None:
    """PARTIAL preserves a known engine with a null version; no fake version."""
    wire = _v3_wire(epoch_id="epoch-1", submission_id="v3-partial")
    wire["producerDeclaration"] = {
        "producerKnowledge": "PARTIAL",
        "softwareName": "Publisher Export Tool",
        "softwareVersion": None,
        "buildIdentifier": None,
        "producerRunIdentifier": None,
        "configurationDigest": None,
        "completedAt": None,
        "sourceNote": "Engine named on the publisher page; version not stated.",
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert parsed.producer_declaration.producer_knowledge == "PARTIAL"
    assert parsed.producer_declaration.software_name == "Publisher Export Tool"
    assert parsed.producer_declaration.software_version is None


@pytest.mark.parametrize(
    "producer",
    [
        pytest.param(
            {
                "producerKnowledge": "PARTIAL",
                "softwareName": None,
                "softwareVersion": None,
            },
            id="partial-without-name",
        ),
        pytest.param(
            {
                "producerKnowledge": "PARTIAL",
                "softwareName": "Engine",
                "softwareVersion": "1.0",
            },
            id="partial-with-version",
        ),
        pytest.param(
            {
                "producerKnowledge": "PARTIAL",
                "softwareName": "unknown",
                "softwareVersion": None,
            },
            id="partial-with-fabricated-label",
        ),
        pytest.param(
            {
                "producerKnowledge": "UNKNOWN",
                "softwareName": None,
                "softwareVersion": "1.0",
            },
            id="unknown-with-unattributed-version",
        ),
    ],
)
def test_v3_rejects_partial_and_unknown_confusion(producer: dict[str, Any]) -> None:
    base = _v3_wire(epoch_id="epoch-1")["producerDeclaration"]
    wire = _v3_wire(epoch_id="epoch-1")
    wire["producerDeclaration"] = {**base, **producer}
    wire.pop("submissionDigest", None)
    with pytest.raises((ValidationError, ValueError)):
        ExternalReconstructionSubmissionV3.model_validate(wire)


@pytest.mark.parametrize(
    "uri",
    [
        "https://data.wa.gov.au/floreat-f3-2021-ortho.jp2",
        "http://127.0.0.1:0/objects/floreat-2021.tif",
        "HTTPS://DATA.WA.GOV.AU/Floreat.TIF",
    ],
)
def test_v3_accepts_safe_public_source_references_verbatim(uri: str) -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    wire["inputDeclaration"]["upstreamSource"]["sourceUri"] = uri
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert parsed.input_declaration.upstream_source is not None
    assert parsed.input_declaration.upstream_source.source_uri == uri


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "data:text/plain,hi",
        "ftp://host/file.tif",
        "file:///etc/passwd",
        "https://user:pass@host/file.tif",
        "https://host/pa th.tif",
        "https://",
        "https://host/\x01file.tif",
        "notauri",
    ],
)
def test_v3_rejects_unsafe_or_malformed_source_references(uri: str) -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    wire["inputDeclaration"]["upstreamSource"]["sourceUri"] = uri
    wire.pop("submissionDigest", None)
    with pytest.raises((ValidationError, ValueError), match="sourceUri"):
        ExternalReconstructionSubmissionV3.model_validate(wire)


def test_v3_parser_never_echoes_a_credential_bearing_source_reference() -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    secret_uri = "https://user:pass@host/file.tif"
    wire["inputDeclaration"]["upstreamSource"]["sourceUri"] = secret_uri
    with pytest.raises(ValueError, match="safe public http") as excinfo:
        parse_external_reconstruction_submission_v3(wire)
    assert secret_uri not in str(excinfo.value)
    assert "user" not in str(excinfo.value) and "pass" not in str(excinfo.value)


def test_v3_never_claims_raw_media_stored_by_ksi() -> None:
    wire = _v3_wire(epoch_id="epoch-1")
    wire["inputDeclaration"]["rawMediaStoredByKsi"] = True
    with pytest.raises((ValidationError, ValueError)):
        ExternalReconstructionSubmissionV3.model_validate(wire)
    schema = _schema(_V3_SCHEMA)
    wire["submissionDigest"] = "sha256:" + "0" * 64
    assert list(Draft202012Validator(schema).iter_errors(wire))


def test_v3_exact_interval_must_be_positive() -> None:
    wire = _v3_wire(epoch_id="epoch-1", submission_id="v3-equal")
    wire["inputDeclaration"]["captureBasis"] = "EXACT_INTERVAL"
    wire["inputDeclaration"]["captureDate"] = None
    wire["producerDeclaration"] = {
        "producerKnowledge": "DECLARED",
        "softwareName": "Customer Mapper",
        "softwareVersion": "2026.9",
        "buildIdentifier": None,
        "producerRunIdentifier": None,
        "configurationDigest": None,
        "completedAt": None,
        "sourceNote": None,
    }
    wire["inputDeclaration"]["captureStartedAt"] = "2026-09-06T00:10:00Z"
    wire["inputDeclaration"]["captureEndedAt"] = "2026-09-06T00:10:00Z"
    wire.pop("submissionDigest", None)
    with pytest.raises((ValidationError, ValueError)):
        ExternalReconstructionSubmissionV3.model_validate(wire)


def test_v3_top_level_execution_consts_are_fixed() -> None:
    """executionResponsibility/Locus are the intake boundary, never run geography.

    Per ADR-KSI-036 D1/D2 (customer/KSI responsibility split; separately
    identified externally produced result; no forged managed identity) and the
    release-plan submission identity, these consts state that the declaration
    is customer-operated and assembled outside KSI execution. They cannot
    express KSI execution (ksi_server_gpu/vendor_cloud rejected) or per-run
    production geography (upstream_source/unknown rejected at top level —
    that honesty lives in producer/input/upstreamSource). V1/V2 literals are
    untouched.
    """
    wire = _v3_wire(epoch_id="epoch-1")
    assert wire["executionResponsibility"] == "customer_operator"
    assert wire["executionLocus"] == "customer_workstation"
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert parsed.execution_responsibility == "customer_operator"
    assert parsed.execution_locus == "customer_workstation"

    for field, bad in [
        ("executionResponsibility", "ksi_operator"),
        ("executionResponsibility", "vendor"),
        ("executionLocus", "ksi_server_gpu"),
        ("executionLocus", "vendor_cloud"),
        ("executionLocus", "upstream_source"),
        ("executionLocus", "unknown"),
    ]:
        forged = _v3_wire(epoch_id="epoch-1")
        forged[field] = bad
        forged.pop("submissionDigest", None)
        with pytest.raises((ValidationError, ValueError)):
            ExternalReconstructionSubmissionV3.model_validate(forged)
        schema = _schema(_V3_SCHEMA)
        forged["submissionDigest"] = "sha256:" + "0" * 64
        assert list(Draft202012Validator(schema).iter_errors(forged))


def test_v3_unknown_production_keeps_responsibility_consts() -> None:
    """Unknown production facts do not fork the responsibility boundary.

    An UNKNOWN producer with an unknown raw-photo locus and an upstream source
    reference is valid alongside the unchanged top-level consts: the consts
    mark whose declaration this is (customer operator, outside KSI execution),
    while where the upstream reconstruction ran stays honestly unknown in the
    typed declaration blocks.
    """
    wire = _v3_wire(epoch_id="epoch-1")
    assert wire["producerDeclaration"]["producerKnowledge"] == "UNKNOWN"
    assert wire["inputDeclaration"]["originalRetentionLocus"] == "unknown"
    assert wire["inputDeclaration"]["upstreamSource"] is not None
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    Draft202012Validator(_schema(_V3_SCHEMA)).validate(wire)
    parsed = parse_external_reconstruction_submission_v3(wire)
    assert parsed.execution_responsibility == "customer_operator"
    assert parsed.execution_locus == "customer_workstation"
    assert parsed.producer_declaration.producer_knowledge == "UNKNOWN"


def test_v1_and_v2_digests_and_wires_are_unchanged_by_v3() -> None:
    from test_external_reconstruction_contracts import (
        _artifact,
        _submission,
        _submission_v2,
    )

    v1 = _submission()
    assert v1.submission_digest == _PINNED_V1_DIGEST
    v2 = _submission_v2((_artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200),))
    assert v2.submission_digest == _PINNED_V2_DIGEST
    # V3 contract names stay distinct; old schemas reject the new version.
    v3_wire = _v3_wire(epoch_id="epoch-1")
    v1_schema = _schema("external-reconstruction-submission.v1.json")
    v2_schema = _schema("external-reconstruction-submission.v2.json")
    assert list(Draft202012Validator(v1_schema).iter_errors(v3_wire))
    assert list(Draft202012Validator(v2_schema).iter_errors(v3_wire))
    assert isinstance(v1, ExternalReconstructionSubmissionV1)
    assert isinstance(v2, ExternalReconstructionSubmissionV2)


def _derived_epoch_id() -> str:
    raw = b"org-a\x00order-a\x001"
    return "obs-epoch-" + hashlib.sha256(raw).hexdigest()[:24]


def _v3_revision_journal(tmp_path: Path) -> DurableJournal:
    journal = DurableJournal(tmp_path / "v3-replay.jsonl")
    store = ExternalReconstructionStore(journal)
    wire = _v3_wire(epoch_id=_derived_epoch_id())
    submission = parse_external_reconstruction_submission_v3(wire)
    order = SimpleNamespace(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-a",
        version=1,
        cycle_number=1,
    )
    result = store.register(
        submission, work_order=order, registered_by="operator-a", now=datetime.now(UTC)
    )
    assert result.revision is not None
    return journal


def test_v3_journal_replays_with_stable_digests_and_rejects_mixed_streams(
    tmp_path: Path,
) -> None:
    journal = _v3_revision_journal(tmp_path)
    replayed = ExternalReconstructionStore(journal)
    record = replayed.get(
        "order-a", "datawa-2021-ortho", 1, organization_id="org-a", site_id="site-a"
    )
    assert record is not None
    assert record.manifest is None
    assert (
        record.submission.submission_digest
        == _v3_wire(epoch_id=_derived_epoch_id())["submissionDigest"]
    )
    assert isinstance(record.submission, ExternalReconstructionSubmissionV3)
    # A V1 declaration for the same stream is a conflict, never a silent merge.
    v1_wire = dict(_v3_wire(epoch_id="epoch-1"))
    v1_wire["contractVersion"] = "external-reconstruction-submission.v1"
    order = SimpleNamespace(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-a",
        version=1,
        cycle_number=1,
    )
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    forged = ExternalReconstructionSubmissionV1(
        submission_id="datawa-2021-ortho",
        revision=2,
        organization_id="org-a",
        site_id="site-a",
        observation_epoch_id=_derived_epoch_id(),
        submitted_at=datetime(2026, 10, 20, tzinfo=UTC),
        submitted_by="operator-a",
        producer_declaration={
            "softwareName": "Mapper",
            "softwareVersion": "1",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        input_declaration={
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
        },
        artifacts=(
            {
                "artifactId": "ortho-2021",
                "kind": ProcessingArtifactKind.ORTHO,
                "fileName": "o.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(b"v3 ortho bytes").hexdigest(),
                "declaredSizeBytes": len(b"v3 ortho bytes"),
            },
        ),
    ).sealed()
    from ksi_core.domains.external.ingress.external_reconstruction import (
        ExternalReconstructionVerdict,
    )

    assert (
        replayed.register(
            forged, work_order=order, registered_by="operator-a", now=datetime.now(UTC)
        ).verdict
        is ExternalReconstructionVerdict.CONFLICT
    )


def test_v3_http_register_grant_seal_and_inspection_issue(tmp_path: Path) -> None:
    client, storage, order_id, epoch = _client(tmp_path, external_reconstruction=True)
    wire = _v3_wire(epoch_id=epoch)
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    registered = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions-v3",
        json=wire,
        headers={**headers, "Idempotency-Key": "v3-incomplete-1"},
    )
    assert registered.status_code == 201, registered.text
    ref = registered.json()["submissionRef"]

    # The frozen V1 route must not accept the V3 contract.
    refused = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions",
        json=wire,
        headers={**headers, "Idempotency-Key": "v3-on-v1"},
    )
    assert refused.status_code == 422

    grants = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions/{ref}/revisions/1/upload-grants",
        headers=headers,
    )
    assert grants.status_code == 200
    object_key = next(
        item["objectKey"] for item in grants.json()["grants"] if item["artifactId"] == "ortho-2021"
    )
    storage.put_bytes(object_key, b"v3 ortho bytes", content_type="application/octet-stream")

    sealed = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions/{ref}/revisions/1/seal",
        headers=headers,
    )
    assert sealed.status_code == 200, sealed.text
    body = sealed.json()
    assert body["state"] == "SEALED"
    assert body["submission"]["contractVersion"] == "external-reconstruction-submission.v3"
    assert body["submission"]["inputDeclaration"]["captureBasis"] == "DATE_ONLY"
    assert body["submission"]["inputDeclaration"]["captureDate"] == "2021-08-17"
    assert body["submission"]["producerDeclaration"]["producerKnowledge"] == "UNKNOWN"
    assert body["manifest"]["submissionDigest"] == body["submission"]["submissionDigest"]

    # The sealed V3 revision is inspection-addressable through the real intake.
    store: ExternalReconstructionStore = client.app.state.external_reconstruction_store  # type: ignore[attr-defined]
    revision = store.get(
        order_id, wire["submissionId"], 1, organization_id="org-a", site_id="site-a"
    )
    assert revision is not None and revision.manifest is not None
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=order_id,
        submission_id=wire["submissionId"],
        revision=1,
        submission_digest=revision.submission.submission_digest,
        manifest_digest=revision.manifest.manifest_digest,
    )
    assert store.resolve_sealed_subject(subject) is revision

    now = datetime.now(UTC)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    template = policy_template()

    class _Authority(PolicyAuthorityPort):
        def __init__(self, record: PolicyAuthorityRecord) -> None:
            self.record = record
            self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

        def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _Authority:
            self._coordinator = coordinator
            return self

        @property
        def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
            assert self._coordinator is not None
            return self._coordinator

        def resolve(self, digest: str, now: datetime) -> PolicyAuthorityRecord | None:
            del now
            return self.record if digest == self.record.digest else None

        def resolve_historical(self, digest: str, at: datetime) -> PolicyAuthorityRecord | None:
            return (
                self.record
                if digest == self.record.digest and self.record.is_active_at(at)
                else None
            )

        def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
            return authority == self.record and self.record.is_active_at(now)

    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=now - timedelta(minutes=1),
        active_until=now + timedelta(days=1),
        synthetic_test_only=True,
    ).sealed()
    port = _Authority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policies.jsonl"),
        authority_port=port,
        authority_currentness_port=port.bind(coordinator),
        clock=lambda: now,
        coordinator=coordinator,
    )
    registry.admit(
        template.model_copy(
            update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
        ).sealed(),
        actor="authority",
        now=now,
    )
    inspections = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspections.jsonl"),
        policy_registry=registry,
        external_reconstruction=store,
        coordinator=coordinator,
    )
    issued = inspections.issue_after_seal(subject, now)
    assert issued.verdict is InspectionVerdict.ISSUED, issued.verdict
    assert issued.request is not None


def _epoch_stub(
    *,
    epoch: str,
    capture_started_at: datetime | None,
    capture_ended_at: datetime | None,
    with_vertical: bool = False,
) -> tuple[Any, Any]:
    entry = SimpleNamespace(
        kind=ProcessingArtifactKind.DSM,
        artifact_id="dsm-2021",
        observed_sha256=_SHA_A,
        observed_size_bytes=100,
        model_dump=lambda **kwargs: {
            "artifactId": "dsm-2021",
            "kind": "dsm",
            "observedSha256": _SHA_A,
            "observedSizeBytes": 100,
        },
    )
    measurements = SimpleNamespace(
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest="sha256:" + "1" * 64,
        observed_vertical_reference=(
            SimpleNamespace(
                identifier="EPSG:3855",
                basis="EGM2008 height",
                canonical_digest=lambda: "sha256:" + "5" * 64,
                model_dump=lambda **kwargs: {
                    "identifier": "EPSG:3855",
                    "basis": "EGM2008 height",
                },
            )
            if with_vertical
            else None
        ),
        transform=(1.0, 0.0, 10.0, 0.0, -1.0, 20.0),
        width=4,
        height=4,
    )
    outcome = SimpleNamespace(
        artifact_id="dsm-2021",
        observed_sha256="sha256:" + _SHA_A,
        outcome=ArtifactOutcome.MEASURED,
        measurements=measurements,
    )
    entry_dump = {
        "artifactId": "dsm-2021",
        "kind": "dsm",
        "observedSha256": _SHA_A,
        "observedSizeBytes": 100,
    }
    manifest_dump = {"entries": [entry_dump]}
    revision = SimpleNamespace(
        manifest=SimpleNamespace(
            entries=[entry],
            model_dump=lambda **kwargs: dict(manifest_dump),
        ),
        submission=SimpleNamespace(
            model_dump=lambda **kwargs: {
                "contractVersion": "external-reconstruction-submission.v3"
            },
            input_declaration=SimpleNamespace(
                capture_started_at=capture_started_at,
                capture_ended_at=capture_ended_at,
            ),
        ),
    )
    report_dump = {"report": "synthetic-v3-epoch"}
    snapshot = SimpleNamespace(
        report=SimpleNamespace(
            report_digest="sha256:" + "2" * 64,
            measurement_payload=SimpleNamespace(outcomes=[outcome]),
            inspection_policy_digest="sha256:" + "3" * 64,
            inspector_build_digest="sha256:" + "4" * 64,
            model_dump=lambda **kwargs: dict(report_dump),
        )
    )
    selection = SimpleNamespace(
        subject=SimpleNamespace(
            epoch=epoch,
            organization_id="org-a",
            site_id="site-a",
            model_dump=lambda **kwargs: {
                "organizationId": "org-a",
                "siteId": "site-a",
                "epoch": epoch,
            },
        )
    )
    return selection, (revision, snapshot)


def _analysis_store_with(revisions: dict[str, Any], snapshots: dict[str, Any]) -> Any:
    store: Any = ExternalRelativeVolumeAnalysisStore.__new__(ExternalRelativeVolumeAnalysisStore)
    store._reconstruction = SimpleNamespace(
        resolve_sealed_subject=lambda subject: revisions[subject.epoch]
    )
    store._inspections = SimpleNamespace(public_snapshot=lambda subject: snapshots[subject.epoch])
    store._work_areas = SimpleNamespace(
        get=lambda work_area_id: SimpleNamespace(status=WorkAreaStatus.ACTIVE, site_id="site-a")
    )
    store._evidence = SimpleNamespace(list=lambda revision: [])
    store._validations = SimpleNamespace(
        analysis_facts_for_subject_dsm=lambda **kwargs: [],
        analysis_fact_currentness=lambda facts, now: [],
        analysis_validation_lifecycles_for_subject_dsm=lambda **kwargs: [],
        analysis_validation_lifecycles_are_locally_current=lambda lifecycles, now: True,
    )
    return store


@pytest.mark.parametrize("basis", ["DATE_ONLY", "UNKNOWN"])
def test_v3_incomplete_chronology_is_not_analysis_eligible(basis: str) -> None:
    """Unknown exact time stays a typed blocker; no midnight is invented."""
    baseline_sel, (baseline_rev, baseline_snap) = _epoch_stub(
        epoch="baseline", capture_started_at=None, capture_ended_at=None
    )
    current_sel, (current_rev, current_snap) = _epoch_stub(
        epoch="current", capture_started_at=None, capture_ended_at=None
    )
    store = _analysis_store_with(
        {"baseline": baseline_rev, "current": current_rev},
        {"baseline": baseline_snap, "current": current_snap},
    )
    now = datetime.now(UTC)
    assert store._resolve_epoch(baseline_sel, now=now, epoch="BASELINE") is None
    assert store._resolve_epoch(current_sel, now=now, epoch="CURRENT") is None
    request = SimpleNamespace(
        request_id="req-v3-incomplete",
        work_area_id="wa-a",
        baseline=baseline_sel,
        current=current_sel,
    )
    with pytest.raises(_PreflightBlocked) as excinfo:
        store._prepare_resolved(organization_id="org-a", request=request, now=now)
    assert excinfo.value.reason == "ESSENTIAL_INPUT_UNAVAILABLE"


def test_v3_exact_interval_reaches_epoch_resolution_like_v1_v2() -> None:
    """A V3 EXACT_INTERVAL epoch resolves identically; strictness is unchanged."""
    baseline_sel, (baseline_rev, baseline_snap) = _epoch_stub(
        epoch="baseline",
        capture_started_at=datetime(2021, 8, 17, 0, 0, 0, tzinfo=UTC),
        capture_ended_at=datetime(2021, 8, 17, 1, 0, 0, tzinfo=UTC),
        with_vertical=True,
    )
    current_sel, (current_rev, current_snap) = _epoch_stub(
        epoch="current",
        capture_started_at=datetime(2022, 8, 24, 0, 0, 0, tzinfo=UTC),
        capture_ended_at=datetime(2022, 8, 24, 1, 0, 0, tzinfo=UTC),
        with_vertical=True,
    )
    store = _analysis_store_with(
        {"baseline": baseline_rev, "current": current_rev},
        {"baseline": baseline_snap, "current": current_snap},
    )
    now = datetime.now(UTC)
    assert store._resolve_epoch(baseline_sel, now=now, epoch="BASELINE") is not None
    assert store._resolve_epoch(current_sel, now=now, epoch="CURRENT") is not None

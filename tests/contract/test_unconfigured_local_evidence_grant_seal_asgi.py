"""Unconfigured local storage must fail closed on V3 grant/seal routes.

Actual platform assembly (assemble_platform_app, same as run_core_dev) with
the canonical _UnavailableEvidenceStorage. Synthetic V3 fixture reuses the
existing date-only ortho pattern (b"v3 ortho bytes"). Owns only this file.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.composition.platform_assembly import assemble_platform_app
from ksi_core.domains.observations.epoch_identity import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundEvidenceStorage, ObjectStorageObservationPort
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV3
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_event_contracts.site_frame import SiteFrame

ROOT = Path(__file__).resolve().parents[2]
_TOKEN = "v3-unconfigured-owner"  # noqa: S105 -- deterministic test credential
_FOREIGN_TOKEN = "v3-unconfigured-foreign"  # noqa: S105 -- deterministic test credential
_NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _runner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_unconfigured_runner", ROOT / "scripts/run_core_dev.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["v3_unconfigured_runner"] = module
    spec.loader.exec_module(module)
    return module


def _record(token: str, organization_id: str) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id="operator-a" if organization_id == "org-a" else "operator-b",
            kind=PrincipalKind.OPERATOR,
            role=Role.FIELD_OPERATOR,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def _v3_wire(epoch_id: str) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "contractVersion": "external-reconstruction-submission.v3",
        "submissionId": "datawa-2021-ortho",
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": epoch_id,
        "submittedAt": "2026-10-20T00:00:00Z",
        "submittedBy": "operator-a",
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
            "sourceNote": "Synthetic date-only fixture; upstream unidentified.",
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "unknown",
            "originalRetentionDetail": None,
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
            "captureDate": "2021-08-17",
            "captureBasis": "DATE_ONLY",
            "upstreamSource": None,
            "derivativeExport": None,
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


@pytest.mark.parametrize("operation", ["upload-grants", "seal"])
def test_v3_grant_and_seal_fail_closed_without_local_storage(
    tmp_path: Path, operation: str
) -> None:
    runner = _runner()
    storage = runner._UnavailableEvidenceStorage()
    assert not isinstance(storage, DigestBoundEvidenceStorage)
    assert not isinstance(storage, ObjectStorageObservationPort)
    opened: list[DurableJournal] = []

    def _journal(name: str) -> DurableJournal:
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    tmp_path.mkdir(parents=True, exist_ok=True)
    app = assemble_platform_app(
        tmp_path,
        journal=_journal,
        opened=opened,
        auth_registry=AuthRegistry(
            [_record(_TOKEN, "org-a"), _record(_FOREIGN_TOKEN, "org-b")]
        ),
        evidence_storage=cast(Any, storage),
    )
    try:
        site_store = app.state.site_store
        registered = site_store.register(
            "site-a",
            "Platform V3 site",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="EGM96 height",
                unit="meter",
                transform_version="fixture-v1",
            ),
            organization_id="org-a",
            actor="operator-a",
            now=_NOW - timedelta(minutes=30),
        )
        assert registered.record is not None
        area = app.state.work_area_store.register(
            "site-a",
            name="Platform V3 area",
            polygon={
                "type": "Polygon",
                "coordinates": [
                    [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
                ],
            },
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=_NOW - timedelta(minutes=29),
        )
        assert area.work_area is not None
        order = app.state.observation_work_order_store.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="V3 unconfigured flow",
            work_area_ids=[area.work_area.work_area_id],
            schedule_id=None,
            execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
            idempotency_key="v3-unconfigured-order",
            actor="operator-a",
            now=_NOW - timedelta(minutes=28),
        )
        epoch = observation_epoch_id(order)
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        with TestClient(app, raise_server_exceptions=False) as client:
            registered_v3 = client.post(
                f"/v1/observation-work-orders/{order.work_order_id}"
                "/external-reconstruction-submissions-v3",
                json=_v3_wire(epoch),
                headers={**headers, "Idempotency-Key": "v3-red-1"},
            )
            assert registered_v3.status_code == 201, registered_v3.text
            ref = registered_v3.json()["submissionRef"]
            journal = app.state.external_reconstruction_store._journal
            before = list(journal.replay())
            path = (
                f"/v1/observation-work-orders/{order.work_order_id}"
                f"/external-reconstruction-submissions/{ref}/revisions/1/{operation}"
            )
            foreign = client.post(path, headers={"Authorization": f"Bearer {_FOREIGN_TOKEN}"})
            assert foreign.status_code == 404
            for _ in range(2):
                response = client.post(path, headers=headers)
                assert response.status_code == 503, response.text
                assert response.json() == {"detail": "STORAGE_UNAVAILABLE"}
            assert list(journal.replay()) == before
    finally:
        for journal in opened:
            journal.close()

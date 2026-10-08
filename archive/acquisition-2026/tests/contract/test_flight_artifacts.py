"""Pilot-export FlightArtifact candidates stay immutable and unbound."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.flight_artifacts import FlightArtifactStore, inspect_pilot_export_kmz
from ksi_core.mission_records import MissionRecord, MissionStore

_NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


class _MemoryStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_put = False

    def presigned_put(self, object_key: str, *, content_type: str, ttl: object) -> str:
        del object_key, content_type, ttl
        return "https://example.invalid/put"

    def presigned_get(self, object_key: str, *, ttl: object) -> str:
        del object_key, ttl
        return "https://example.invalid/get"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        assert content_type == "application/octet-stream"
        if self.fail_put:
            raise EvidenceStorageError("storage unavailable")
        self.data[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        try:
            return self.data[object_key]
        except KeyError as exc:
            raise EvidenceStorageError("missing") from exc

    def delete(self, object_key: str) -> None:
        self.data.pop(object_key, None)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth() -> AuthRegistry:
    def record(
        token: str, principal_id: str, role: Role, organization_id: str
    ) -> PrincipalTokenRecord:
        return PrincipalTokenRecord(
            token_sha256=_token_digest(token),
            principal=Principal(
                principal_id=principal_id,
                kind=PrincipalKind.OPERATOR,
                role=role,
                device_id=None,
                organization_id=organization_id,
            ),
        )

    return AuthRegistry(
        [
            record("issue-a", "issuer-a", Role.FIELD_OPERATOR, "org-a"),
            record("read-a", "reader-a", Role.VIEWER, "org-a"),
            record("read-b", "reader-b", Role.VIEWER, "org-b"),
        ]
    )


def _contract(mission_id: str) -> dict[str, object]:
    return {
        "missionId": mission_id,
        "flightEnvelope": {
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
            "altitudeReference": "relativeToStartPoint",
        },
        "signature": {"value": "original-contract-must-not-change"},
    }


def _mission_store(tmp_path: Path) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    for mission_id, organization_id in (("mission-a", "org-a"), ("mission-b", "org-b")):
        assert (
            store.record_issuance(
                MissionRecord(
                    mission_id=mission_id,
                    site_id="site-a" if organization_id == "org-a" else "site-b",
                    mission_type="BASELINE_MAPPING",
                    artifact_kind="contract",
                    contract=_contract(mission_id),
                    kmz_sha256=None,
                    route_pattern=None,
                    waypoint_count=None,
                    planned_coverage_ratio=None,
                    issued_at=_NOW,
                    issued_by="issuer",
                    organization_id=organization_id,
                )
            ).value
            == "RECORDED"
        )
    return store


def _kmz(*, height: float = 40.0, traversal: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # DJI-like archives may carry an explicit safe resource directory.  It
        # is neither a traversal segment nor executable content.
        archive.writestr("wpmz/res/", b"")
        archive.writestr(
            "wpmz/template.kml",
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark/></Document></kml>',
        )
        archive.writestr(
            "wpmz/waylines.wpml",
            (
                '<kml xmlns="http://www.opengis.net/kml/2.2" '
                'xmlns:wpml="http://www.dji.com/wpmz/1.0.6"><Document><Folder>'
                "<wpml:executeHeightMode>relativeToStartPoint</wpml:executeHeightMode>"
                f"<Placemark><wpml:executeHeight>{height}</wpml:executeHeight></Placemark>"
                "</Folder></Document></kml>"
            ),
        )
        if traversal:
            archive.writestr("../escape", "not allowed")
    return output.getvalue()


def _client(tmp_path: Path) -> tuple[TestClient, FlightArtifactStore, _MemoryStorage, MissionStore]:
    mission_store = _mission_store(tmp_path)
    storage = _MemoryStorage()
    artifacts = FlightArtifactStore(
        DurableJournal(tmp_path / "flight-artifacts.jsonl"),
        mission_store=mission_store,
        storage=storage,
    )
    app = create_app(
        auth_registry=_auth(),
        mission_store=mission_store,
        evidence_storage=storage,
        flight_artifact_store=artifacts,
    )
    return TestClient(app), artifacts, storage, mission_store


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pilot_export_candidate_is_immutable_revisioned_and_never_changes_contract(
    tmp_path: Path,
) -> None:
    client, artifacts, storage, mission_store = _client(tmp_path)
    original_record = mission_store.get_scoped("mission-a", organization_id="org-a")
    assert original_record is not None
    original_contract = deepcopy(original_record.contract)
    first = _kmz(height=40.0)

    response = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={
            "kmzBase64": base64.b64encode(first).decode(),
            "provenanceRef": "pilot2-export:run-1",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "RECORDED"
    assert body["candidate"]["source"] == "DJI_PILOT_EXPORT"
    assert body["candidate"]["status"] == "VALIDATED_CANDIDATE_UNBOUND"
    assert body["candidate"]["validatorVersion"] == "1.0"
    assert body["candidate"]["executable"] is False
    assert body["candidate"]["revision"] == 1
    assert body["candidate"]["envelopeCheck"] == "COMPATIBLE"
    candidate_id = body["candidate"]["candidateId"]

    retry = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={
            "kmzBase64": base64.b64encode(first).decode(),
            "provenanceRef": "pilot2-export:changed",
        },
    )
    assert retry.status_code == 200
    assert retry.json()["verdict"] == "DUPLICATE"
    assert retry.json()["candidate"]["candidateId"] == candidate_id
    assert len(artifacts.list_for_mission("mission-a", organization_id="org-a")) == 1

    second = _kmz(height=50.0)
    revised = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={
            "kmzBase64": base64.b64encode(second).decode(),
            "provenanceRef": "pilot2-export:run-2",
        },
    )
    assert revised.status_code == 201
    assert revised.json()["candidate"]["revision"] == 2
    assert len(artifacts.list_for_mission("mission-a", organization_id="org-a")) == 2

    downloaded = client.get(
        f"/v1/missions/mission-a/flight-artifacts/{candidate_id}/download",
        headers=_headers("read-a"),
    )
    assert downloaded.status_code == 200
    assert downloaded.content == first
    assert downloaded.headers["x-ksi-flightartifact-status"] == "VALIDATED_CANDIDATE_UNBOUND"
    assert downloaded.headers["x-ksi-executable"] == "false"
    assert storage.data

    current = mission_store.get_scoped("mission-a", organization_id="org-a")
    assert current is not None
    assert current.contract == original_contract
    assert current.artifact_kind == "contract"
    assert current.kmz_sha256 is None
    assert current.plan_request is None


def test_invalid_archive_org_boundary_auth_and_digest_mismatch_are_fail_closed(
    tmp_path: Path,
) -> None:
    client, artifacts, storage, _mission_store_value = _client(tmp_path)
    invalid = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={
            "kmzBase64": base64.b64encode(_kmz(traversal=True)).decode(),
            "provenanceRef": "pilot2-export:bad-zip",
        },
    )
    assert invalid.status_code == 422
    assert artifacts.list_for_mission("mission-a", organization_id="org-a") == []

    assert (
        client.post(
            "/v1/missions/mission-a/flight-artifacts/pilot-export",
            headers=_headers("read-a"),
            json={"kmzBase64": base64.b64encode(_kmz()).decode(), "provenanceRef": "x"},
        ).status_code
        == 403
    )

    valid = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={"kmzBase64": base64.b64encode(_kmz()).decode(), "provenanceRef": "pilot2-export:ok"},
    )
    candidate_id = valid.json()["candidate"]["candidateId"]
    assert (
        client.get(
            "/v1/missions/mission-a/flight-artifacts", headers=_headers("read-b")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/missions/mission-a/flight-artifacts/{candidate_id}/download",
            headers=_headers("read-b"),
        ).status_code
        == 404
    )

    candidate = artifacts.get("mission-a", candidate_id, organization_id="org-a")
    assert candidate is not None
    storage.data[candidate.object_key] = b"tampered"
    mismatch = client.get(
        f"/v1/missions/mission-a/flight-artifacts/{candidate_id}/download",
        headers=_headers("read-a"),
    )
    assert mismatch.status_code == 409


def test_storage_failure_creates_no_durable_candidate_and_structure_is_explicitly_unbound(
    tmp_path: Path,
) -> None:
    client, artifacts, storage, _mission_store_value = _client(tmp_path)
    storage.fail_put = True
    response = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={
            "kmzBase64": base64.b64encode(_kmz()).decode(),
            "provenanceRef": "pilot2-export:retry",
        },
    )
    assert response.status_code == 503
    assert artifacts.list_for_mission("mission-a", organization_id="org-a") == []

    inspection = inspect_pilot_export_kmz(_kmz())
    assert inspection.placemark_count == 1
    assert inspection.execute_height_mode == "relativeToStartPoint"
    assert inspection.execute_heights_m == (40.0,)


@pytest.mark.parametrize("encoded", ["not base64!", base64.b64encode(b"not-a-zip").decode()])
def test_base64_and_zip_inputs_are_rejected_before_durable_record(
    tmp_path: Path, encoded: str
) -> None:
    client, artifacts, _storage, _mission_store_value = _client(tmp_path)
    response = client.post(
        "/v1/missions/mission-a/flight-artifacts/pilot-export",
        headers=_headers("issue-a"),
        json={"kmzBase64": encoded, "provenanceRef": "pilot2-export:invalid"},
    )
    assert response.status_code == 422
    assert artifacts.list_for_mission("mission-a", organization_id="org-a") == []

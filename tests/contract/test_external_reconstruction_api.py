"""External reconstruction ingress stays a scoped byte declaration, not a managed job."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from ksi_core.acquisition import observation_epoch_id
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_mission_contracts.models import SiteFrame

_NOW = datetime(2026, 9, 6, tzinfo=UTC)
_TOKEN = "external-reconstruction-owner"  # noqa: S105 -- deterministic test credential
_OTHER_TOKEN = "external-reconstruction-other"  # noqa: S105


class _Storage:
    """Real store-facing behavior; only the remote S3 boundary is replaced."""

    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}
        self.bytes_by_key: dict[str, bytes] = {}

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://storage.invalid/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://storage.invalid/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self.bytes_by_key[object_key] = data
        self.objects[object_key] = ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        return self.bytes_by_key[object_key]

    def delete(self, object_key: str) -> None:
        self.bytes_by_key.pop(object_key, None)
        self.objects.pop(object_key, None)

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> DigestBoundUploadCapability:
        del ttl
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )


def _record(
    token: str,
    *,
    principal_id: str,
    organization_id: str,
    kind: PrincipalKind = PrincipalKind.OPERATOR,
    role: Role | None = Role.FIELD_OPERATOR,
    device_id: str | None = None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=kind,
            role=role,
            device_id=device_id,
            organization_id=organization_id,
        ),
    )


def _client(
    tmp_path: Path,
    *,
    storage: _Storage | None = None,
    auth_records: list[PrincipalTokenRecord] | None = None,
    organization_id: str = "org-a",
    site_id: str = "site-a",
) -> tuple[TestClient, _Storage, str, str]:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
    )
    if sites.get_scoped("site-a", "org-a") is None:
        assert sites.register(
            "site-a", "site-a", frame, organization_id="org-a", actor="fixture", now=_NOW
        ).record
    if sites.get_scoped("site-b", "org-b") is None:
        assert sites.register(
            "site-b", "site-b", frame, organization_id="org-b", actor="fixture", now=_NOW
        ).record
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = work_orders.get("obs-work-00000001", organization_id=organization_id)
    if order is None:
        order = work_orders.create_work_order(
            organization_id=organization_id,
            site_id=site_id,
            name="External export",
            work_area_ids=["wa-a"],
            schedule_id=None,
            actor="fixture",
            now=_NOW,
        )
    storage = storage or _Storage()
    app = create_app(
        auth_registry=AuthRegistry(
            auth_records
            or [
                _record(_TOKEN, principal_id="operator-a", organization_id="org-a"),
                _record(_OTHER_TOKEN, principal_id="operator-b", organization_id="org-b"),
            ]
        ),
        site_store=sites,
        observation_work_order_store=work_orders,
        evidence_storage=storage,
        external_reconstruction_store=ExternalReconstructionStore(
            DurableJournal(tmp_path / "external-reconstruction.jsonl")
        ),
    )
    app.state.external_reconstruction_test_sites = sites
    app.state.external_reconstruction_test_work_orders = work_orders
    return TestClient(app), storage, order.work_order_id, observation_epoch_id(order)


def _submission(
    *,
    work_order_id: str,
    epoch_id: str,
    declared_sha256: str | None = None,
    declared_size_bytes: int | None = None,
    revision: int = 1,
    submission_id: str = "external-001",
    content_type: str = "application/octet-stream",
    include_dsm: bool = False,
    organization_id: str = "org-a",
    site_id: str = "site-a",
    submitted_by: str = "operator-a",
) -> dict[str, Any]:
    del work_order_id
    digest = declared_sha256 or hashlib.sha256(b"ortho bytes").hexdigest()
    artifacts = [
        {
            "artifactId": "ortho",
            "kind": "ortho",
            "fileName": "ortho.tif",
            "format": "GeoTIFF",
            "contentType": content_type,
            "declaredSha256": digest,
            "declaredSizeBytes": declared_size_bytes or len(b"ortho bytes"),
            "declaredCrs": None,
            "declaredVerticalReference": None,
            "declaredGsdM": None,
        }
    ]
    if include_dsm:
        artifacts.append(
            {
                "artifactId": "dsm",
                "kind": "dsm",
                "fileName": "surface.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(b"dsm bytes").hexdigest(),
                "declaredSizeBytes": len(b"dsm bytes"),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        )
    return {
        "submissionId": submission_id,
        "revision": revision,
        "organizationId": organization_id,
        "siteId": site_id,
        "observationEpochId": epoch_id,
        "submittedAt": "2026-09-06T00:00:00Z",
        "submittedBy": submitted_by,
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Customer Mapper",
            "softwareVersion": "1.0",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
        },
        "artifacts": artifacts,
    }


def _headers(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_grant_and_seal_observed_ortho_bytes_without_promoting_a_managed_job(
    tmp_path: Path,
) -> None:
    """Deleting actor/scope/digest checks or sealing unobserved bytes must break this."""
    client, storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    registered = client.post(path, headers=_headers(), json=submitted)
    repeated = client.post(path, headers=_headers(), json=submitted)
    assert registered.status_code == repeated.status_code == 201, registered.text
    assert registered.json()["submission"]["submissionDigest"] == submitted["submissionDigest"]
    assert repeated.json() == registered.json()
    assert "processingJob" not in registered.json()

    submission_ref = registered.json()["submissionRef"]
    grants = client.post(f"{path}/{submission_ref}/revisions/1/upload-grants", headers=_headers())
    assert grants.status_code == 200, grants.text
    grant = grants.json()["grants"][0]
    not_uploaded = client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers())
    assert not_uploaded.status_code == 422
    storage.objects[grant["objectKey"]] = ObjectStorageObservation(
        object_key=grant["objectKey"],
        exists=True,
        size_bytes=len(b"ortho bytes"),
        sha256="sha256:" + hashlib.sha256(b"ortho bytes").hexdigest(),
        content_type="application/octet-stream",
    )
    sealed = client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers())
    assert sealed.status_code == 200, sealed.text
    assert (
        sealed.json()["manifest"]["entries"][0]["observedSha256"]
        == hashlib.sha256(b"ortho bytes").hexdigest()
    )
    assert (
        client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers()).json()
        == sealed.json()
    )


def test_registration_hides_foreign_work_order_and_rejects_conflicting_revision(
    tmp_path: Path,
) -> None:
    """Removing principal-scoped lookup or digest conflict handling must break this."""
    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    registered = client.post(path, headers=_headers(), json=submitted)
    assert registered.status_code == 201
    changed = _submission(work_order_id=work_order_id, epoch_id=epoch_id, declared_sha256="f" * 64)
    changed["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(changed)
    conflict = client.post(path, headers=_headers(), json=changed)
    foreign = client.get(path, headers=_headers(_OTHER_TOKEN))
    absent = client.get(
        "/v1/observation-work-orders/not-a-work-order/external-reconstruction-submissions",
        headers=_headers(_OTHER_TOKEN),
    )
    assert conflict.status_code == 409
    assert foreign.status_code == absent.status_code == 404


@pytest.mark.parametrize(
    "submission_id",
    ["customer/run-1", "x/revisions/1", "..", "a%2Fb", "고객 실행 1"],
)
def test_opaque_submission_ref_addresses_every_contract_valid_customer_identifier(
    tmp_path: Path,
    submission_id: str,
) -> None:
    """Raw customer IDs cannot safely be route segments, so clients must use the returned ref."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted = _submission(
        work_order_id=work_order_id,
        epoch_id=epoch_id,
        submission_id=submission_id,
    )
    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    registered = client.post(path, headers=_headers(), json=submitted)
    assert registered.status_code == 201, registered.text
    encoded_raw = quote(submission_id, safe="")
    raw_route_responses = [
        client.get(f"{path}/{encoded_raw}/revisions/1", headers=_headers()),
        client.post(f"{path}/{encoded_raw}/revisions/1/upload-grants", headers=_headers()),
        client.post(f"{path}/{encoded_raw}/revisions/1/seal", headers=_headers()),
    ]
    assert [response.status_code for response in raw_route_responses] == [404, 404, 404]
    body = registered.json()
    submission_ref = body["submissionRef"]
    assert re.fullmatch(r"ers-v1-[0-9a-f]{64}", submission_ref)
    assert client.post(path, headers=_headers(), json=submitted).json() == body
    listed = client.get(path, headers=_headers())
    assert listed.status_code == 200
    assert listed.json()["submissions"] == [body]
    detail = client.get(f"{path}/{submission_ref}/revisions/1", headers=_headers())
    assert detail.status_code == 200
    assert detail.json() == body
    unknown = "ers-v1-" + "0" * 64
    assert client.get(f"{path}/{unknown}/revisions/1", headers=_headers()).status_code == 404


def test_same_raw_customer_identifier_has_distinct_organization_bound_refs(
    tmp_path: Path,
) -> None:
    """Omitting organization from the opaque identity would make tenant refs collide."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    raw_submission_id = "customer/run-1"
    client_a, _storage, work_order_id, epoch_id = _client(tmp_path / "org-a")
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted_a = _submission(
        work_order_id=work_order_id,
        epoch_id=epoch_id,
        submission_id=raw_submission_id,
    )
    submitted_a["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        submitted_a
    )
    registered_a = client_a.post(path, headers=_headers(), json=submitted_a)
    assert registered_a.status_code == 201

    client_b, _storage, other_work_order_id, other_epoch_id = _client(
        tmp_path / "org-b",
        auth_records=[_record(_TOKEN, principal_id="operator-b", organization_id="org-b")],
        organization_id="org-b",
        site_id="site-b",
    )
    assert other_work_order_id == work_order_id
    submitted_b = _submission(
        work_order_id=other_work_order_id,
        epoch_id=other_epoch_id,
        submission_id=raw_submission_id,
        organization_id="org-b",
        site_id="site-b",
        submitted_by="operator-b",
    )
    submitted_b["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        submitted_b
    )
    registered_b = client_b.post(path, headers=_headers(), json=submitted_b)
    assert registered_b.status_code == 201
    assert registered_a.json()["submissionRef"] != registered_b.json()["submissionRef"]


def test_same_scope_slash_and_literal_percent_submission_ids_have_distinct_refs(
    tmp_path: Path,
) -> None:
    """Decoding a customer ID before ref derivation would collapse two accepted identities."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    responses: dict[str, dict[str, Any]] = {}
    for submission_id in ("a/b", "a%2Fb"):
        submitted = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch_id,
            submission_id=submission_id,
        )
        submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
            submitted
        )
        registered = client.post(path, headers=_headers(), json=submitted)
        assert registered.status_code == 201, registered.text
        responses[submission_id] = registered.json()
    assert responses["a/b"]["submissionRef"] != responses["a%2Fb"]["submissionRef"]
    for submission_id, response in responses.items():
        detail = client.get(
            f"{path}/{response['submissionRef']}/revisions/1", headers=_headers()
        )
        assert detail.status_code == 200
        assert detail.json()["submission"]["submissionId"] == submission_id


def test_valid_shaped_unknown_ref_has_no_route_specific_authority_or_state_effect(
    tmp_path: Path,
) -> None:
    """An unknown ref must fail before grant, object-observation, or journal side effects."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    class CountingStorage(_Storage):
        def __init__(self) -> None:
            super().__init__()
            self.capabilities_issued = 0
            self.object_observations = 0

        def presigned_put_bound_digest(
            self, *args: Any, **kwargs: Any
        ) -> DigestBoundUploadCapability:
            self.capabilities_issued += 1
            return super().presigned_put_bound_digest(*args, **kwargs)

        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            self.object_observations += 1
            return super().observe_object(object_key)

    storage = CountingStorage()
    client, _storage, work_order_id, epoch_id = _client(tmp_path, storage=storage)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    assert client.post(path, headers=_headers(), json=submitted).status_code == 201
    store = cast(Any, client.app).state.external_reconstruction_store
    events_before = store._journal.replay()
    unknown_ref = "ers-v1-" + "0" * 64
    responses = [
        client.get(f"{path}/{unknown_ref}/revisions/1", headers=_headers()),
        client.post(f"{path}/{unknown_ref}/revisions/1/upload-grants", headers=_headers()),
        client.post(f"{path}/{unknown_ref}/revisions/1/seal", headers=_headers()),
    ]
    assert [response.status_code for response in responses] == [404, 404, 404]
    assert [response.json() for response in responses] == [responses[0].json()] * 3
    assert storage.capabilities_issued == storage.object_observations == 0
    assert store._journal.replay() == events_before


def test_same_org_human_can_correct_with_own_actor_provenance_and_replay(
    tmp_path: Path,
) -> None:
    """Freezing the first actor would deny a valid same-tenant correction."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    operator_b_token = "same-org-operator-b"  # noqa: S105 -- deterministic test credential
    client, _storage, work_order_id, epoch_id = _client(
        tmp_path,
        auth_records=[
            _record(_TOKEN, principal_id="operator-a", organization_id="org-a"),
            _record(operator_b_token, principal_id="operator-b", organization_id="org-a"),
        ],
    )
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"

    def signed(revision: int, *, actor: str, payload: bytes) -> dict[str, Any]:
        wire = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch_id,
            revision=revision,
            declared_sha256=hashlib.sha256(payload).hexdigest(),
            declared_size_bytes=len(payload),
        )
        wire["submittedBy"] = actor
        wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
        return wire

    first = signed(1, actor="operator-a", payload=b"revision-one")
    correction = signed(2, actor="operator-b", payload=b"revision-two")
    assert client.post(path, headers=_headers(), json=first).status_code == 201
    accepted = client.post(path, headers=_headers(operator_b_token), json=correction)
    assert accepted.status_code == 201, accepted.text

    app = cast(Any, client.app)
    store = app.state.external_reconstruction_store
    before_rejected_claim = len(store._journal.replay())
    claimed = signed(3, actor="operator-a", payload=b"revision-three")
    rejected = client.post(path, headers=_headers(operator_b_token), json=claimed)
    assert rejected.status_code == 422
    assert len(store._journal.replay()) == before_rejected_claim

    first_record = store.get(
        work_order_id, "external-001", 1, organization_id="org-a", site_id="site-a"
    )
    second_record = store.get(
        work_order_id, "external-001", 2, organization_id="org-a", site_id="site-a"
    )
    assert first_record is not None and second_record is not None
    assert (first_record.registered_by, first_record.submission.submitted_by) == (
        "operator-a",
        "operator-a",
    )
    assert (second_record.registered_by, second_record.submission.submitted_by) == (
        "operator-b",
        "operator-b",
    )

    store._journal.close()
    reopened = ExternalReconstructionStore(
        DurableJournal(tmp_path / "external-reconstruction.jsonl")
    )
    reopened_first = reopened.get(
        work_order_id, "external-001", 1, organization_id="org-a", site_id="site-a"
    )
    reopened_second = reopened.get(
        work_order_id, "external-001", 2, organization_id="org-a", site_id="site-a"
    )
    assert reopened_first is not None and reopened_second is not None
    assert (reopened_first.registered_by, reopened_first.submission.submitted_by) == (
        "operator-a",
        "operator-a",
    )
    assert (reopened_second.registered_by, reopened_second.submission.submitted_by) == (
        "operator-b",
        "operator-b",
    )
    reopened._journal.close()


def test_sealed_revision_cannot_issue_a_new_upload_grant_or_change_its_manifest(
    tmp_path: Path,
) -> None:
    """Granting after a seal would expand storage authority beyond its byte proof."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    class CountingStorage(_Storage):
        def __init__(self) -> None:
            super().__init__()
            self.capabilities_issued = 0

        def presigned_put_bound_digest(
            self, *args: Any, **kwargs: Any
        ) -> DigestBoundUploadCapability:
            self.capabilities_issued += 1
            return super().presigned_put_bound_digest(*args, **kwargs)

    storage = CountingStorage()
    client, _storage, work_order_id, epoch_id = _client(tmp_path, storage=storage)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    registered = client.post(path, headers=_headers(), json=submitted)
    assert registered.status_code == 201
    submission_ref = registered.json()["submissionRef"]
    grant_response = client.post(
        f"{path}/{submission_ref}/revisions/1/upload-grants", headers=_headers()
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()["grants"][0]
    storage.objects[grant["objectKey"]] = ObjectStorageObservation(
        object_key=grant["objectKey"],
        exists=True,
        size_bytes=len(b"ortho bytes"),
        sha256="sha256:" + hashlib.sha256(b"ortho bytes").hexdigest(),
        content_type="application/octet-stream",
    )
    sealed = client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers())
    assert sealed.status_code == 200, sealed.text
    manifest = sealed.json()["manifest"]
    store = cast(Any, client.app).state.external_reconstruction_store
    events_before = len(store._journal.replay())
    attempted_grant = client.post(
        f"{path}/{submission_ref}/revisions/1/upload-grants", headers=_headers()
    )
    assert attempted_grant.status_code == 409
    assert storage.capabilities_issued == 1
    assert len(store._journal.replay()) == events_before
    current = client.get(f"{path}/{submission_ref}/revisions/1", headers=_headers())
    assert current.status_code == 200
    assert current.json()["manifest"] == manifest


def test_foreign_journal_record_with_same_work_order_id_is_not_an_idempotent_retry(
    tmp_path: Path,
) -> None:
    """Removing frozen org/site/actor checks before retry exposes a foreign receipt."""
    foreign_client, _storage, work_order_id, epoch_id = _client(tmp_path / "foreign")
    foreign_path = (
        f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    )
    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    foreign_registered = foreign_client.post(foreign_path, headers=_headers(), json=submitted)
    assert foreign_registered.status_code == 201
    foreign_ref = foreign_registered.json()["submissionRef"]
    foreign_app = cast(Any, foreign_client.app)
    foreign_app.state.external_reconstruction_store._journal.close()

    sites = SiteStore(DurableJournal(tmp_path / "other-sites.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186",
        vertical_datum="KNGeoid2018",
        unit="meter",
        transform_version="1.0.0",
    )
    assert sites.register(
        "site-b", "site-b", frame, organization_id="org-b", actor="fixture", now=_NOW
    ).record
    orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "other-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    other_order = orders.create_work_order(
        organization_id="org-b",
        site_id="site-b",
        name="Independent order",
        work_area_ids=["wa-b"],
        schedule_id=None,
        actor="fixture",
        now=_NOW,
    )
    assert other_order.work_order_id == work_order_id
    external_journal_path = tmp_path / "foreign" / "external-reconstruction.jsonl"
    external_store = ExternalReconstructionStore(DurableJournal(external_journal_path))
    client = TestClient(
        create_app(
            auth_registry=AuthRegistry(
                [_record(_OTHER_TOKEN, principal_id="operator-a", organization_id="org-b")]
            ),
            site_store=sites,
            observation_work_order_store=orders,
            evidence_storage=_Storage(),
            external_reconstruction_store=external_store,
        )
    )
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    clean_client = TestClient(
        create_app(
            auth_registry=AuthRegistry(
                [_record(_OTHER_TOKEN, principal_id="operator-a", organization_id="org-b")]
            ),
            site_store=sites,
            observation_work_order_store=orders,
            evidence_storage=_Storage(),
            external_reconstruction_store=ExternalReconstructionStore(
                DurableJournal(tmp_path / "clean-external.jsonl")
            ),
        )
    )
    absent = clean_client.post(path, headers=_headers(_OTHER_TOKEN), json=submitted)
    retry = client.post(path, headers=_headers(_OTHER_TOKEN), json=submitted)
    assert retry.status_code == absent.status_code == 422
    assert client.get(path, headers=_headers(_OTHER_TOKEN)).json() == {"submissions": []}
    for suffix in (
        f"{foreign_ref}/revisions/1",
        f"{foreign_ref}/revisions/1/upload-grants",
        f"{foreign_ref}/revisions/1/seal",
    ):
        method = client.get if suffix.endswith("/1") else client.post
        response = method(f"{path}/{suffix}", headers=_headers(_OTHER_TOKEN))
        assert response.status_code == 404


def test_every_external_route_returns_the_same_absent_response_for_foreign_work_order_scope(
    tmp_path: Path,
) -> None:
    """Resolving an unscoped WorkOrder before a route leaks cross-tenant record existence."""
    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    foreign_base = (
        f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    )
    absent_base = "/v1/observation-work-orders/not-a-work-order/external-reconstruction-submissions"
    submission_ref = "ers-v1-" + "a" * 64
    calls = [
        (client.post, "", submitted),
        (client.get, "", None),
        (client.get, f"/{submission_ref}/revisions/1", None),
        (client.post, f"/{submission_ref}/revisions/1/upload-grants", None),
        (client.post, f"/{submission_ref}/revisions/1/seal", None),
    ]
    for method, suffix, body in calls:
        kwargs = {"headers": _headers(_OTHER_TOKEN)}
        if body is not None:
            kwargs["json"] = body
        foreign = method(foreign_base + suffix, **kwargs)
        absent = method(absent_base + suffix, **kwargs)
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()


def test_ortho_only_and_ortho_dsm_declarations_round_trip_without_raw_media_authority(
    tmp_path: Path,
) -> None:
    """Dropping DSM bindings or adding managed-job/source fields breaks this byte-only receipt."""
    client, storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    for submission_id, with_dsm in (("ortho-only", False), ("ortho-dsm", True)):
        submitted = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch_id,
            submission_id=submission_id,
            include_dsm=with_dsm,
        )
        submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
            submitted
        )
        registered = client.post(path, headers=_headers(), json=submitted)
        assert registered.status_code == 201, registered.text
        submission_ref = registered.json()["submissionRef"]
        assert {artifact["kind"] for artifact in registered.json()["submission"]["artifacts"]} == (
            {"ortho", "dsm"} if with_dsm else {"ortho"}
        )
        assert not {"processingJob", "profile", "rawBundle"} & set(registered.json())
        grants = client.post(
            f"{path}/{submission_ref}/revisions/1/upload-grants",
            headers=_headers(),
        )
        assert grants.status_code == 200
        for grant in grants.json()["grants"]:
            payload = b"dsm bytes" if grant["artifactId"] == "dsm" else b"ortho bytes"
            storage.objects[grant["objectKey"]] = ObjectStorageObservation(
                object_key=grant["objectKey"],
                exists=True,
                size_bytes=len(payload),
                sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
                content_type="application/octet-stream",
            )
        sealed = client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers())
        assert sealed.status_code == 200, sealed.text
        assert {entry["kind"] for entry in sealed.json()["manifest"]["entries"]} == (
            {"ortho", "dsm"} if with_dsm else {"ortho"}
        )


def test_only_human_site_writers_can_register_grant_or_seal_and_viewers_can_read(
    tmp_path: Path,
) -> None:
    """Granting device or worker principals SITES_WRITE breaks the human authority boundary."""
    tokens = {
        "admin": "external-admin",
        "viewer": "external-viewer",
        "gateway": "external-gateway",
        "edge": "external-edge",
        "worker": "external-worker",
    }
    records = [
        _record(tokens["admin"], principal_id="admin-a", organization_id="org-a", role=Role.ADMIN),
        _record(
            tokens["viewer"], principal_id="viewer-a", organization_id="org-a", role=Role.VIEWER
        ),
        _record(
            tokens["gateway"],
            principal_id="gateway-a",
            organization_id="org-a",
            kind=PrincipalKind.GATEWAY_DEVICE,
            role=None,
            device_id="gateway-a",
        ),
        _record(
            tokens["edge"],
            principal_id="edge-a",
            organization_id="org-a",
            kind=PrincipalKind.EDGE_DEVICE,
            role=None,
            device_id="edge-a",
        ),
        _record(
            tokens["worker"],
            principal_id="worker-a",
            organization_id="org-a",
            kind=PrincipalKind.PROCESSING_WORKER,
            role=None,
        ),
    ]
    client, _storage, work_order_id, epoch_id = _client(tmp_path, auth_records=records)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    submitted["submittedBy"] = "admin-a"
    submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submitted)
    assert client.post(path, json=submitted).status_code == 401
    registered = client.post(path, headers=_headers(tokens["admin"]), json=submitted)
    assert registered.status_code == 201
    submission_ref = registered.json()["submissionRef"]
    assert client.get(path, headers=_headers(tokens["viewer"])).status_code == 200
    for token in (tokens["viewer"], tokens["gateway"], tokens["edge"], tokens["worker"]):
        assert client.post(path, headers=_headers(token), json=submitted).status_code == 403
        assert (
            client.post(
                f"{path}/{submission_ref}/revisions/1/upload-grants",
                headers=_headers(token),
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{path}/{submission_ref}/revisions/1/seal",
                headers=_headers(token),
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    ("field", "value", "drop"),
    [
        ("organizationId", "org-b", False),
        ("siteId", "site-b", False),
        ("observationEpochId", "obs-epoch-forged", False),
        ("submittedBy", "someone-else", False),
        ("submissionDigest", None, True),
    ],
)
def test_register_rejects_forged_scope_actor_and_unsealed_declaration(
    tmp_path: Path,
    field: str,
    value: str | None,
    drop: bool,
) -> None:
    """Removing declaration or principal binding must not create a receipt."""
    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    submitted = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    if drop:
        assert field == "submissionDigest"
    else:
        submitted[field] = value
        submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
            submitted
        )
    response = client.post(path, headers=_headers(), json=submitted)
    assert response.status_code == 422
    assert client.get(path, headers=_headers()).json() == {"submissions": []}


def test_register_rejects_stale_digest_active_types_and_client_object_keys(
    tmp_path: Path,
) -> None:
    """Accepting stale seals, executable MIME, or caller keys reaches storage authority."""
    client, _storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    stale = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    stale["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(stale)
    stale["artifacts"][0]["declaredSizeBytes"] = 999
    assert client.post(path, headers=_headers(), json=stale).status_code == 422
    for content_type in ("text/html", "image/svg+xml"):
        active = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch_id,
            content_type=content_type,
            submission_id=content_type.replace("/", "-"),
        )
        active["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(active)
        assert client.post(path, headers=_headers(), json=active).status_code == 422
    unsafe_name = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    unsafe_name["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        unsafe_name
    )
    unsafe_name["artifacts"][0]["fileName"] = "../customer-photo.tif"
    assert client.post(path, headers=_headers(), json=unsafe_name).status_code == 422
    caller_key = _submission(work_order_id=work_order_id, epoch_id=epoch_id)
    caller_key["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(caller_key)
    caller_key["artifacts"][0]["objectKey"] = "tenant-a/customer/bytes"
    assert client.post(path, headers=_headers(), json=caller_key).status_code == 422


def test_revisions_are_contiguous_and_only_latest_unsealed_revision_can_be_granted_or_sealed(
    tmp_path: Path,
) -> None:
    """Allowing gaps or an old unsealed revision to acquire authority breaks supersession."""
    client, storage, work_order_id, epoch_id = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    def submit(revision: int, payload: bytes) -> Any:
        wire = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch_id,
            revision=revision,
            declared_sha256=hashlib.sha256(payload).hexdigest(),
            declared_size_bytes=len(payload),
        )
        wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
        return client.post(path, headers=_headers(), json=wire)

    assert submit(2, b"revision two").status_code == 409
    registered = submit(1, b"ortho bytes")
    assert registered.status_code == 201
    submission_ref = registered.json()["submissionRef"]
    assert submit(3, b"revision three").status_code == 409
    corrected = submit(2, b"revision two")
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["submissionRef"] == submission_ref
    old_grant = client.post(
        f"{path}/{submission_ref}/revisions/1/upload-grants", headers=_headers()
    )
    old_seal = client.post(f"{path}/{submission_ref}/revisions/1/seal", headers=_headers())
    assert old_grant.status_code == old_seal.status_code == 409
    grants = client.post(f"{path}/{submission_ref}/revisions/2/upload-grants", headers=_headers())
    assert grants.status_code == 200
    grant = grants.json()["grants"][0]
    storage.objects[grant["objectKey"]] = ObjectStorageObservation(
        object_key=grant["objectKey"],
        exists=True,
        size_bytes=len(b"revision two"),
        sha256="sha256:" + hashlib.sha256(b"revision two").hexdigest(),
        content_type="application/octet-stream",
    )
    sealed = client.post(f"{path}/{submission_ref}/revisions/2/seal", headers=_headers())
    retry = client.post(f"{path}/{submission_ref}/revisions/2/seal", headers=_headers())
    assert sealed.status_code == retry.status_code == 200
    assert retry.json() == sealed.json()
    assert client.get(f"{path}/{submission_ref}/revisions/1", headers=_headers()).status_code == 200


def test_historical_stream_uses_frozen_first_work_order_witness_after_real_cycle_advance(
    tmp_path: Path,
) -> None:
    """Deriving an old stream from current cycle/version rejects valid historical correction."""
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
    from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus

    client, _storage, work_order_id, old_epoch = _client(tmp_path)
    path = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"

    def sealed_wire(
        *, revision: int, epoch: str, submission_id: str = "external-001"
    ) -> dict[str, Any]:
        wire = _submission(
            work_order_id=work_order_id,
            epoch_id=epoch,
            revision=revision,
            submission_id=submission_id,
        )
        wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
        return wire

    first_wire = sealed_wire(revision=1, epoch=old_epoch)
    assert client.post(path, headers=_headers(), json=first_wire).status_code == 201
    app = cast(Any, client.app)
    orders = app.state.external_reconstruction_test_work_orders
    orders.approve(
        work_order_id,
        organization_id="org-a",
        expected_version=1,
        actor="operator-a",
        now=_NOW,
    )
    for status in (
        ObservationWorkOrderStatus.DISPATCHED,
        ObservationWorkOrderStatus.START_REPORTED,
        ObservationWorkOrderStatus.MEDIA_RECEIVING,
        ObservationWorkOrderStatus.PROCESSING,
        ObservationWorkOrderStatus.REVIEW_READY,
    ):
        orders.record_status(
            work_order_id,
            organization_id="org-a",
            status=status,
            status_reason=None,
            mission_ids=None,
            processing_job_ids=None,
            report_refs=None,
            actor="operator-a",
            now=_NOW,
        )
    draft = orders.create_reobservation_draft(
        work_order_id,
        organization_id="org-a",
        reason_refs=["reason-1"],
        target_region_refs=["region-1"],
        proposed_effort="repeat",
        planner_version="planner-1",
        policy_version="policy-1",
        expires_at=_NOW + timedelta(days=1),
        actor="operator-a",
        now=_NOW,
    )
    orders.approve_reobservation(
        draft.draft_id,
        organization_id="org-a",
        expected_version=draft.version,
        actor="operator-a",
        now=_NOW,
    )
    advanced = orders.get(work_order_id, organization_id="org-a")
    assert advanced is not None and advanced.cycle_number == 2
    assert client.post(path, headers=_headers(), json=first_wire).status_code == 201
    old_correction = sealed_wire(revision=2, epoch=old_epoch)
    assert client.post(path, headers=_headers(), json=old_correction).status_code == 201
    stored = app.state.external_reconstruction_store.get(
        work_order_id,
        "external-001",
        2,
        organization_id="org-a",
        site_id="site-a",
    )
    assert stored is not None
    assert (stored.work_order_version, stored.cycle_number, stored.observation_epoch_id) == (
        1,
        1,
        old_epoch,
    )
    assert (
        client.post(
            path,
            headers=_headers(),
            json=sealed_wire(revision=3, epoch=observation_epoch_id(advanced)),
        ).status_code
        == 409
    )
    new_cycle = sealed_wire(
        revision=1,
        epoch=observation_epoch_id(advanced),
        submission_id="external-002",
    )
    assert client.post(path, headers=_headers(), json=new_cycle).status_code == 201

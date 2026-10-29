"""Human external-evidence ingress is scoped, opaque, and occurrence-only."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.domains.observations.epoch_identity import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.external_evidence import (
    EvidenceVerdict,
    ExternalEvidenceDeclarationIntent,
    ExternalEvidenceRecoveryError,
    ExternalEvidenceStore,
)
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_evidence import (
    ExternalEvidenceDeclarationV1,
    external_evidence_declaration_wire_dict,
)
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from ksi_event_contracts.site_frame import SiteFrame

_NOW = datetime(2026, 9, 8, tzinfo=UTC)
_TOKEN = "external-evidence-owner"  # noqa: S105 -- deterministic test credential
_OTHER_TOKEN = "external-evidence-other"  # noqa: S105


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}
        self.capabilities = 0

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> DigestBoundUploadCapability:
        del ttl
        self.capabilities += 1
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(object_key, ObjectStorageObservation(object_key, exists=False))


def _record(token: str, *, principal_id: str, organization_id: str) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=Role.FIELD_OPERATOR,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def _client(
    tmp_path: Path, *, clock: Callable[[], datetime] | None = None
) -> tuple[TestClient, _Storage, str]:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
    )
    assert sites.register(
        "site-a", "site-a", frame, organization_id="org-a", actor="test", now=_NOW
    ).record
    assert sites.register(
        "site-b", "site-b", frame, organization_id="org-b", actor="test", now=_NOW
    ).record
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="External evidence",
        work_area_ids=["wa-a"],
        schedule_id=None,
        actor="test",
        now=_NOW,
    )
    storage = _Storage()
    app = create_app(
        auth_registry=AuthRegistry(
            [
                _record(_TOKEN, principal_id="operator-a", organization_id="org-a"),
                _record(_OTHER_TOKEN, principal_id="operator-b", organization_id="org-b"),
            ]
        ),
        site_store=sites,
        observation_work_order_store=work_orders,
        evidence_storage=cast(Any, storage),
        external_reconstruction_store=ExternalReconstructionStore(
            DurableJournal(tmp_path / "external-reconstruction.jsonl")
        ),
        external_evidence_store=ExternalEvidenceStore(
            DurableJournal(tmp_path / "external-evidence.jsonl"), clock=clock or (lambda: _NOW)
        ),
    )
    return TestClient(app), storage, order.work_order_id


def _headers(token: str = _TOKEN, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _seal_external_revision(client: TestClient, storage: _Storage, work_order_id: str) -> str:
    order = cast(Any, client.app).state.observation_work_order_store.get(
        work_order_id, organization_id="org-a"
    )
    artifacts = []
    for artifact_id, kind, payload in (("ortho", "ortho", b"ortho"), ("dsm", "dsm", b"dsm")):
        artifacts.append(
            {
                "artifactId": artifact_id,
                "kind": kind,
                "fileName": f"{artifact_id}.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(payload).hexdigest(),
                "declaredSizeBytes": len(payload),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        )
    submission: dict[str, Any] = {
        "submissionId": "customer-evidence-run",
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": observation_epoch_id(order),
        "submittedAt": "2026-09-08T00:00:00Z",
        "submittedBy": "operator-a",
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
    submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submission)
    root = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    registered = client.post(root, headers=_headers(), json=submission)
    assert registered.status_code == 201, registered.text
    ref = registered.json()["submissionRef"]
    grants = client.post(f"{root}/{ref}/revisions/1/upload-grants", headers=_headers())
    assert grants.status_code == 200, grants.text
    payloads = {"dsm": b"dsm", "ortho": b"ortho"}
    for grant in grants.json()["grants"]:
        payload = payloads[grant["artifactId"]]
        storage.objects[grant["objectKey"]] = ObjectStorageObservation(
            object_key=grant["objectKey"],
            exists=True,
            size_bytes=len(payload),
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            content_type="application/octet-stream",
        )
    sealed = client.post(f"{root}/{ref}/revisions/1/seal", headers=_headers())
    assert sealed.status_code == 200, sealed.text
    return ref


def _base(work_order_id: str, submission_ref: str) -> str:
    return (
        f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
        f"{submission_ref}/revisions/1/evidence"
    )


def _intent(payload: bytes = b"existing checkpoint facts") -> dict[str, str]:
    return {
        "targetDsmArtifactId": "dsm",
        "declaredContentDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "declaredContentType": "application/octet-stream",
        "independenceBasis": "Customer retained this independent checkpoint export.",
    }


def test_human_evidence_routes_derive_sealed_scope_and_never_expose_internal_storage(
    tmp_path: Path,
) -> None:
    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    intent = _intent()
    declared = client.post(base, headers=_headers(key="declare-1"), json=intent)
    assert declared.status_code == 201, declared.text
    assert (
        client.post(base, headers=_headers(key="declare-1"), json=intent).json() == declared.json()
    )
    body = declared.json()
    assert body["state"] == "DECLARED" and body["evidenceRef"].startswith("eev-v1-")
    assert body["targetDsmObservedSha256"] == "sha256:" + hashlib.sha256(b"dsm").hexdigest()
    assert set(body) == {
        "evidenceRef",
        "state",
        "targetDsmArtifactId",
        "targetDsmObservedSha256",
        "declaredContentDigest",
        "declaredContentType",
        "independenceBasis",
        "declaredAt",
    }
    assert client.post(base, headers=_headers(key="declare-2"), json=intent).json() == body
    assert (
        client.post(
            base,
            headers=_headers(key="declared-object-key"),
            json={**intent, "objectKey": "caller/key"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            base, headers=_headers(key="declare-1"), json={**intent, "independenceBasis": "changed"}
        ).status_code
        == 409
    )
    assert client.get(base, headers=_headers()).json()["items"] == [body]

    grant_url = f"{base}/{body['evidenceRef']}/upload-grant"
    assert client.post(grant_url, headers=_headers(key="declare-1")).status_code == 409
    capabilities_before = storage.capabilities
    grant = client.post(grant_url, headers=_headers(key="grant-1"))
    assert grant.status_code == 200, grant.text
    assert {"evidenceRef", "uploadUrl", "expiresAt", "requiredHeaders"} == set(grant.json())
    assert client.post(grant_url, headers=_headers(key="grant-1")).status_code == 200
    assert storage.capabilities == capabilities_before + 2  # replay re-signs; no URL is persisted
    item = cast(Any, client.app).state.external_evidence_store._items[body["evidenceRef"]]
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=intent["declaredContentDigest"],
        content_type=intent["declaredContentType"],
    )
    sealed = client.post(f"{base}/{body['evidenceRef']}/seal", headers=_headers(key="seal-1"))
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["state"] == "SEALED_BYTE_OBSERVED"
    assert sealed.json()["observedObjectDigest"] == intent["declaredContentDigest"]
    assert {"objectKey", "serverObjectKey", "workerId", "rawCoordinates"}.isdisjoint(sealed.json())
    assert (
        client.post(
            f"{base}/{body['evidenceRef']}/seal", headers=_headers(key="declare-1")
        ).status_code
        == 409
    )
    assert client.get(base, headers=_headers(_OTHER_TOKEN)).status_code == 404


def test_blank_idempotency_key_is_a_bounded_request_validation_error(tmp_path: Path) -> None:
    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    response = safe_client.post(base, headers=_headers(key="   "), json=_intent())
    assert response.status_code == 422


def test_grant_expiry_and_replay_are_durable_and_typed(tmp_path: Path) -> None:
    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    declared = client.post(base, headers=_headers(key="declare"), json=_intent(b"facts"))
    assert declared.status_code == 201
    evidence_store = cast(Any, client.app).state.external_evidence_store
    reconstruction = cast(Any, client.app).state.external_reconstruction_store
    revision = reconstruction.get(
        work_order_id, "customer-evidence-run", 1, organization_id="org-a", site_id="site-a"
    )
    assert revision is not None
    principal = _record(_TOKEN, principal_id="operator-a", organization_id="org-a").principal
    ref = declared.json()["evidenceRef"]
    assert (
        evidence_store.grant(
            ref, revision=revision, principal=principal, key="expiry", storage=storage, now=_NOW
        ).verdict
        is EvidenceVerdict.DECLARED
    )
    assert (
        evidence_store.grant(
            ref,
            revision=revision,
            principal=principal,
            key="expiry",
            storage=storage,
            now=_NOW + timedelta(minutes=15),
        ).verdict
        is EvidenceVerdict.EXPIRED
    )
    evidence_store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened.list(revision)[0].evidence_ref == ref
    reopened._journal.close()


def test_same_natural_evidence_declared_concurrently_has_one_durable_identity(
    tmp_path: Path,
) -> None:
    client, storage, work_order_id = _client(tmp_path)
    _seal_external_revision(client, storage, work_order_id)
    evidence_store = cast(Any, client.app).state.external_evidence_store
    reconstruction = cast(Any, client.app).state.external_reconstruction_store
    revision = reconstruction.get(
        work_order_id,
        "customer-evidence-run",
        1,
        organization_id="org-a",
        site_id="site-a",
    )
    assert revision is not None
    principal = _record(_TOKEN, principal_id="operator-a", organization_id="org-a").principal
    intent = ExternalEvidenceDeclarationIntent.model_validate(_intent(b"concurrent-facts"))

    def declare(key: str) -> str:
        result = evidence_store.declare(
            intent, revision=revision, principal=principal, key=key, now=_NOW
        )
        assert result.verdict is EvidenceVerdict.DECLARED and result.item is not None
        return result.item.evidence_ref

    with ThreadPoolExecutor(max_workers=4) as executor:
        refs = list(executor.map(declare, ("a", "b", "c", "d")))
    assert len(set(refs)) == 1
    assert [raw["kind"] for raw in evidence_store._journal.replay()].count(
        "external-evidence-declared"
    ) == 1


class _BlockingStorage(_Storage):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self._count_lock = Lock()
        self.observations = 0
        self.ttls: list[timedelta] = []

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> DigestBoundUploadCapability:
        with self._count_lock:
            self.capabilities += 1
            self.ttls.append(ttl)
            first = self.capabilities == 1
        if first:
            self.entered.set()
            assert self.release.wait(timeout=2)
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        self.observations += 1
        return super().observe_object(object_key)


def _direct_evidence_context(
    tmp_path: Path, *, clock: Callable[[], datetime] | None = None
) -> tuple[Any, _Storage, Any, Principal, str]:
    client, storage, work_order_id = _client(tmp_path, clock=clock)
    _seal_external_revision(client, storage, work_order_id)
    evidence_store = cast(Any, client.app).state.external_evidence_store
    revision = cast(Any, client.app).state.external_reconstruction_store.get(
        work_order_id,
        "customer-evidence-run",
        1,
        organization_id="org-a",
        site_id="site-a",
    )
    assert revision is not None
    principal = _record(_TOKEN, principal_id="operator-a", organization_id="org-a").principal
    result = evidence_store.declare(
        ExternalEvidenceDeclarationIntent.model_validate(_intent()),
        revision=revision,
        principal=principal,
        key="declare-direct",
        now=_NOW,
    )
    assert result.item is not None
    return evidence_store, storage, revision, principal, result.item.evidence_ref


def test_pending_grant_key_blocks_cross_item_mutation_before_storage_io(tmp_path: Path) -> None:
    evidence_store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    second = evidence_store.declare(
        ExternalEvidenceDeclarationIntent.model_validate(_intent(b"second")),
        revision=revision,
        principal=principal,
        key="declare-second",
        now=_NOW,
    )
    assert second.item is not None
    blocked = _BlockingStorage()
    first = ThreadPoolExecutor(max_workers=1)
    first_future = first.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="shared-key",
        storage=blocked,
        now=_NOW,
    )
    assert blocked.entered.wait(timeout=2)
    conflict = evidence_store.grant(
        second.item.evidence_ref,
        revision=revision,
        principal=principal,
        key="shared-key",
        storage=blocked,
        now=_NOW,
    )
    blocked.release.set()
    assert conflict.verdict is EvidenceVerdict.CONFLICT
    assert first_future.result(timeout=2).verdict is EvidenceVerdict.DECLARED
    assert blocked.capabilities == 1
    first.shutdown()
    evidence_store._journal.close()
    ExternalEvidenceStore(DurableJournal(evidence_store._journal._path))._journal.close()


def test_pending_grant_key_blocks_cross_operation_before_observation(tmp_path: Path) -> None:
    evidence_store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = evidence_store._items[ref]
    blocked = _BlockingStorage()
    blocked.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    first = ThreadPoolExecutor(max_workers=1)
    future = first.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="shared-key",
        storage=blocked,
        now=_NOW,
    )
    assert blocked.entered.wait(timeout=2)
    conflict = evidence_store.seal(
        ref,
        revision=revision,
        principal=principal,
        key="shared-key",
        storage=blocked,
        now=_NOW,
    )
    blocked.release.set()
    assert conflict.verdict is EvidenceVerdict.CONFLICT
    assert blocked.observations == 0
    assert future.result(timeout=2).verdict is EvidenceVerdict.DECLARED
    first.shutdown()
    evidence_store._journal.close()
    ExternalEvidenceStore(DurableJournal(evidence_store._journal._path))._journal.close()


def test_pending_same_grant_key_uses_one_canonical_expiry(tmp_path: Path) -> None:
    evidence_store, _storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    blocked = _BlockingStorage()
    executor = ThreadPoolExecutor(max_workers=2)
    first = executor.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="same-key",
        storage=blocked,
        now=_NOW,
    )
    assert blocked.entered.wait(timeout=2)
    second = executor.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="same-key",
        storage=blocked,
        now=_NOW + timedelta(seconds=1),
    )
    blocked.release.set()
    first_result, second_result = first.result(timeout=2), second.result(timeout=2)
    assert first_result.expires_at == second_result.expires_at
    executor.shutdown()


def test_pending_grant_refreshes_the_clock_before_represigning_remaining_ttl(
    tmp_path: Path,
) -> None:
    current = [_NOW]
    second_clock_called = Event()
    release_second_clock = Event()
    calls = [0]

    def clock() -> datetime:
        calls[0] += 1
        if calls[0] == 3:
            second_clock_called.set()
            assert release_second_clock.wait(timeout=2)
            return _NOW
        return current[0]

    evidence_store, _storage, revision, principal, ref = _direct_evidence_context(
        tmp_path, clock=clock
    )
    blocked = _BlockingStorage()
    executor = ThreadPoolExecutor(max_workers=2)
    first = executor.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="same-key",
        storage=blocked,
        now=_NOW,
    )
    assert blocked.entered.wait(timeout=2)
    second = executor.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="same-key",
        storage=blocked,
        now=_NOW,
    )
    assert second_clock_called.wait(timeout=2)
    current[0] = _NOW + timedelta(minutes=5)
    release_second_clock.set()
    blocked.release.set()
    assert first.result(timeout=2).verdict is EvidenceVerdict.DECLARED
    assert second.result(timeout=2).verdict is EvidenceVerdict.DECLARED
    assert blocked.ttls == [timedelta(minutes=15), timedelta(minutes=10)]
    executor.shutdown()


def test_delayed_grant_presign_rechecks_the_canonical_expiry_before_handoff(tmp_path: Path) -> None:
    current = [_NOW]
    evidence_store, _storage, revision, principal, ref = _direct_evidence_context(
        tmp_path, clock=lambda: current[0]
    )
    blocked = _BlockingStorage()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        evidence_store.grant,
        ref,
        revision=revision,
        principal=principal,
        key="delayed",
        storage=blocked,
        now=_NOW,
    )
    assert blocked.entered.wait(timeout=2)
    current[0] = _NOW + timedelta(minutes=15)
    blocked.release.set()
    assert future.result(timeout=2).verdict is EvidenceVerdict.EXPIRED
    assert all(
        raw["kind"] != "external-evidence-grant-issued" for raw in evidence_store._journal.replay()
    )
    executor.shutdown()


def _event_digest(raw: dict[str, object]) -> str:
    payload = dict(raw)
    payload.pop("eventDigest", None)
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _rewrite_journal(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))


def test_replay_rejects_resealed_cross_dsm_when_server_identity_is_stale(tmp_path: Path) -> None:
    store, _storage, _revision, _principal, _ref = _direct_evidence_context(tmp_path)
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    raw = records[0]
    declaration = ExternalEvidenceDeclarationV1.model_validate(raw["declaration"])
    forged = declaration.model_copy(
        update={
            "target_dsm_observed_sha256": "sha256:" + "0" * 64,
            "declaration_digest": None,
        }
    ).sealed()
    raw["declaration"] = external_evidence_declaration_wire_dict(forged)
    raw["eventDigest"] = _event_digest(raw)
    _rewrite_journal(path, records)
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_replay_rejects_null_manifest_digest_even_when_other_fields_match(tmp_path: Path) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    assert store.seal(
        ref,
        revision=revision,
        principal=principal,
        key="seal",
        storage=storage,
        now=item.declaration.declared_at,
    ).item
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    raw = next(record for record in records if record["kind"] == "external-evidence-sealed")
    raw["manifest"]["evidenceManifestDigest"] = None
    raw["eventDigest"] = _event_digest(raw)
    _rewrite_journal(path, records)
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_fresh_seal_replay_key_is_durable_and_cross_operation_key_conflicts(tmp_path: Path) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    assert (
        store.seal(
            ref, revision=revision, principal=principal, key="seal-a", storage=storage, now=_NOW
        ).verdict
        is EvidenceVerdict.SEALED
    )
    assert (
        store.seal(
            ref, revision=revision, principal=principal, key="seal-b", storage=storage, now=_NOW
        ).verdict
        is EvidenceVerdict.SEALED
    )
    assert (
        store.grant(
            ref, revision=revision, principal=principal, key="seal-b", storage=storage, now=_NOW
        ).verdict
        is EvidenceVerdict.CONFLICT
    )
    path = store._journal._path
    store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(path))
    assert (
        reopened.seal(
            ref, revision=revision, principal=principal, key="seal-b", storage=storage, now=_NOW
        ).verdict
        is EvidenceVerdict.SEALED
    )
    reopened._journal.close()


def test_new_evidence_seal_notifies_additive_lifecycle_once_after_commit(tmp_path: Path) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    observed: list[str] = []
    store.bind_seal_listener(lambda sealed, _now: observed.append(sealed.evidence_ref))

    assert store.seal(
        ref, revision=revision, principal=principal, key="seal-a", storage=storage, now=_NOW
    ).verdict is EvidenceVerdict.SEALED
    assert observed == [ref]
    assert store.sealed_items_snapshot() == (store.resolve_for_validation(ref),)

    assert store.seal(
        ref, revision=revision, principal=principal, key="seal-b", storage=storage, now=_NOW
    ).verdict is EvidenceVerdict.SEALED
    assert observed == [ref]


def test_replay_rejects_a_grant_event_after_a_seal(tmp_path: Path) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    assert store.grant(
        ref, revision=revision, principal=principal, key="grant", storage=storage, now=_NOW
    ).item
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    assert store.seal(
        ref, revision=revision, principal=principal, key="seal", storage=storage, now=_NOW
    ).item
    binding = store._binding(
        principal,
        "grant",
        {"evidenceRef": ref, "revision": revision.submission.revision},
        {},
        "late",
    )
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    forged: dict[str, object] = {
        "kind": "external-evidence-grant-issued",
        "version": 1,
        "evidenceRef": ref,
        "idempotency": binding,
        "expiresAt": "2026-09-08T00:15:00+00:00",
    }
    forged["eventDigest"] = _event_digest(forged)
    _rewrite_journal(path, [*records, forged])
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_replay_rejects_reordered_events(tmp_path: Path) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    assert store.grant(
        ref, revision=revision, principal=principal, key="grant", storage=storage, now=_NOW
    ).item
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"existing checkpoint facts"),
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    assert store.seal(
        ref, revision=revision, principal=principal, key="seal", storage=storage, now=_NOW
    ).item
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    _rewrite_journal(path, list(reversed(records)))
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_replay_rejects_boolean_event_version(tmp_path: Path) -> None:
    store, _storage, _revision, _principal, _ref = _direct_evidence_context(tmp_path)
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    records[0]["version"] = True
    records[0]["eventDigest"] = _event_digest(records[0])
    _rewrite_journal(path, records)
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_replay_rejects_rehashed_event_with_a_forged_idempotency_fingerprint(
    tmp_path: Path,
) -> None:
    store, _storage, _revision, _principal, _ref = _direct_evidence_context(tmp_path)
    path = store._journal._path
    records = copy.deepcopy(store._journal.replay())
    store._journal.close()
    records[0]["idempotency"]["fingerprint"] = "sha256:" + "0" * 64
    records[0]["eventDigest"] = _event_digest(records[0])
    _rewrite_journal(path, records)
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(path))


def test_declaration_text_is_normalized_before_natural_identity_derivation(tmp_path: Path) -> None:
    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    response = client.post(
        base,
        headers=_headers(key="normalized"),
        json={
            **_intent(),
            "declaredContentType": " application/octet-stream ",
            "independenceBasis": " Existing customer facts. ",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["declaredContentType"] == "application/octet-stream"
    assert response.json()["independenceBasis"] == "Existing customer facts."
    evidence_store = cast(Any, client.app).state.external_evidence_store
    journal_path = evidence_store._journal._path
    evidence_store._journal.close()
    ExternalEvidenceStore(DurableJournal(journal_path))._journal.close()


def test_natural_dedupe_returns_typed_storage_failure_when_journal_is_sealed(
    tmp_path: Path,
) -> None:
    store, _storage, revision, principal, _ref = _direct_evidence_context(tmp_path)
    store._journal.close()
    result = store.declare(
        ExternalEvidenceDeclarationIntent.model_validate(_intent()),
        revision=revision,
        principal=principal,
        key="same-natural-new-key",
        now=_NOW,
    )
    assert result.verdict is EvidenceVerdict.STORAGE_UNAVAILABLE


@pytest.mark.parametrize("operation", ["upload-grant", "seal"])
def test_unconfigured_local_evidence_storage_fails_closed_without_reservation_leak(
    tmp_path: Path, operation: str
) -> None:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "evidence_local_runner", Path(__file__).resolve().parents[2] / "scripts/run_core_dev.py"
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    declared = client.post(base, headers=_headers(key="declare-unconfigured"), json=_intent())
    assert declared.status_code == 201
    ref = declared.json()["evidenceRef"]
    store = cast(Any, client.app).state.external_evidence_store
    before = list(store._journal.replay())
    storage.__class__ = runner._UnavailableEvidenceStorage
    safe = TestClient(client.app, raise_server_exceptions=False)
    url = f"{base}/{ref}/{operation}"
    assert safe.post(url, headers=_headers(_OTHER_TOKEN, key="foreign")).status_code == 404
    first = safe.post(url, headers=_headers(key="unconfigured"))
    assert first.status_code == 503, first.text
    assert first.json() == {"detail": "STORAGE_UNAVAILABLE"}
    second = safe.post(url, headers=_headers(key="unconfigured"))
    assert second.status_code == 503
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: safe.post(url, headers=_headers(key="unconfigured")), range(4))
        )
    assert all(response.status_code == 503 for response in responses)
    assert not store._pending
    assert list(store._journal.replay()) == before


@pytest.mark.parametrize("operation", ["grant", "seal"])
def test_unexpected_storage_failure_releases_waiter_without_hiding_error(
    tmp_path: Path, operation: str
) -> None:
    from ksi_core.evidence import EvidenceStorageError

    store, _, revision, principal, ref = _direct_evidence_context(tmp_path)
    before = list(store._journal.replay())
    entered, release, waiting = Event(), Event(), Event()

    class FailingStorage(_Storage):
        calls = 0

        def fail(self) -> None:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(3)
                raise RuntimeError("unexpected adapter failure")
            raise EvidenceStorageError("unavailable")

        def presigned_put_bound_digest(self, *args: Any, **kwargs: Any) -> Any:
            self.fail()

        def observe_object(self, *args: Any, **kwargs: Any) -> Any:
            self.fail()

    storage = FailingStorage()
    method = getattr(store, operation)
    kwargs = dict(
        revision=revision, principal=principal, key="same-failure", storage=storage, now=_NOW
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(method, ref, **kwargs)
        assert entered.wait(3)
        with store._lock:
            pending = next(iter(store._pending.values()))
            original_wait = pending.completed.wait

            def instrumented_wait(timeout: float | None = None) -> bool:
                waiting.set()
                return original_wait(timeout)

            pending.completed.wait = instrumented_wait
        waiter = executor.submit(method, ref, **kwargs)
        try:
            assert waiting.wait(3)
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="unexpected adapter failure"):
            owner.result(timeout=3)
        assert waiter.result(timeout=3).verdict is EvidenceVerdict.STORAGE_UNAVAILABLE
    assert not store._pending
    assert list(store._journal.replay()) == before


def test_invalid_observation_releases_waiter_before_any_append(tmp_path: Path) -> None:
    from pydantic import ValidationError

    store, _, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    before = list(store._journal.replay())
    entered, release, waiting = Event(), Event(), Event()

    class InvalidObservation(_Storage):
        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            entered.set()
            assert release.wait(3)
            return ObjectStorageObservation(
                object_key=object_key,
                exists=True,
                size_bytes=cast(Any, 0.5),  # runtime adapter metadata is not validated
                sha256=item.declaration.declared_content_digest,
                content_type=item.declaration.declared_content_type,
            )

    kwargs = dict(
        revision=revision, principal=principal, key="invalid-observation",
        storage=InvalidObservation(), now=_NOW,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(store.seal, ref, **kwargs)
        assert entered.wait(3)
        with store._lock:
            pending = next(iter(store._pending.values()))
            original_wait = pending.completed.wait

            def instrumented_wait(timeout: float | None = None) -> bool:
                waiting.set()
                return original_wait(timeout)

            pending.completed.wait = instrumented_wait
        waiter = executor.submit(store.seal, ref, **kwargs)
        try:
            assert waiting.wait(3)
            release.set()
            with pytest.raises(ValidationError):
                owner.result(timeout=3)
            with pytest.raises(ValidationError):
                waiter.result(timeout=3)
        finally:
            release.set()
            with store._lock:
                for key, reservation in list(store._pending.items()):
                    store._release_locked({"key": key}, reservation)
    assert not store._pending
    assert list(store._journal.replay()) == before
    store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened._items[ref].manifest is None
    reopened._journal.close()


def test_seal_durable_append_projection_failure_recovers_on_restart(tmp_path: Path) -> None:
    store, _, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage = _Storage()
    storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=5,
        sha256=item.declaration.declared_content_digest,
        content_type=item.declaration.declared_content_type,
    )
    before = list(store._journal.replay())
    original_apply = store._apply

    def fail_live_projection(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-sealed":
            raise RuntimeError("synthetic live projection failure")
        original_apply(raw)

    store._apply = fail_live_projection
    kwargs = dict(revision=revision, principal=principal, key="projection-failure", now=_NOW)
    with pytest.raises(RuntimeError, match="synthetic live projection failure"):
        store.seal(ref, storage=storage, **kwargs)
    assert len(store._journal.replay()) == len(before) + 1
    assert store._items[ref].manifest is None
    store._journal.close()

    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened._items[ref].manifest is not None
    assert reopened.seal(ref, storage=storage, **kwargs).verdict is EvidenceVerdict.SEALED
    assert len(reopened._journal.replay()) == len(before) + 1
    reopened._journal.close()


@pytest.mark.parametrize("partial_apply", [False, True])
def test_live_projection_failure_fails_closed_at_asgi_until_replay(
    tmp_path: Path, partial_apply: bool
) -> None:
    client, storage, work_order_id = _client(tmp_path)
    base = _base(work_order_id, _seal_external_revision(client, storage, work_order_id))
    declared = client.post(base, headers=_headers(key="projection-declare"), json=_intent())
    assert declared.status_code == 201
    ref = declared.json()["evidenceRef"]
    store = cast(Any, client.app).state.external_evidence_store
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        item.object_key, True, 5, item.declaration.declared_content_digest,
        item.declaration.declared_content_type,
    )
    before = list(store._journal.replay())
    original_apply = store._apply
    listeners: list[str] = []
    store.bind_seal_listener(lambda sealed, now: listeners.append(sealed.evidence_ref))

    def fail_live(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-sealed":
            if partial_apply:
                original_apply(raw)
            raise RuntimeError("synthetic projection failure")
        original_apply(raw)

    store._apply = fail_live
    safe = TestClient(client.app, raise_server_exceptions=False)
    url = f"{base}/{ref}/seal"
    assert safe.post(url, headers=_headers(key="first")).status_code == 500
    assert not listeners
    assert len(store._journal.replay()) == len(before) + 1
    assert safe.post(url, headers=_headers(_OTHER_TOKEN, key="foreign")).status_code == 404
    assert safe.get(base).status_code == 401
    assert safe.post(url, headers=_headers(key="different")).status_code == 503
    assert safe.post(url, headers=_headers(key="first")).status_code == 503
    assert safe.post(f"{base}/{ref}/upload-grant", headers=_headers(key="grant")).status_code == 503
    assert safe.post(base, headers=_headers(key="new-declare"), json=_intent()).status_code == 503
    assert safe.get(base, headers=_headers()).status_code == 503
    assert len(store._journal.replay()) == len(before) + 1
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.resolve_for_validation(ref)
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.sealed_items_snapshot()
    store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened._items[ref].manifest is not None
    assert len(reopened._journal.replay()) == len(before) + 1
    reopened._journal.close()


def test_projection_failure_wakes_waiter_and_rejects_inflight_grant(tmp_path: Path) -> None:
    store, _, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    before = list(store._journal.replay())
    seal_entered, seal_release, waiting = Event(), Event(), Event()
    grant_entered, grant_release = Event(), Event()

    class PausedStorage(_Storage):
        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            seal_entered.set()
            assert seal_release.wait(3)
            return ObjectStorageObservation(
                object_key, True, 5, item.declaration.declared_content_digest,
                item.declaration.declared_content_type,
            )

        def presigned_put_bound_digest(self, *args: Any, **kwargs: Any) -> Any:
            grant_entered.set()
            assert grant_release.wait(3)
            return super().presigned_put_bound_digest(*args, **kwargs)

    storage = PausedStorage()
    original_apply = store._apply

    def fail_live(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-sealed":
            raise RuntimeError("synthetic projection failure")
        original_apply(raw)

    store._apply = fail_live
    args = dict(revision=revision, principal=principal, storage=storage, now=_NOW)
    with ThreadPoolExecutor(max_workers=3) as executor:
        seal = executor.submit(store.seal, ref, key="same", **args)
        assert seal_entered.wait(3)
        with store._lock:
            reservation = next(iter(store._pending.values()))
            original_wait = reservation.completed.wait

            def instrumented_wait(timeout: float | None = None) -> bool:
                waiting.set()
                return original_wait(timeout)

            reservation.completed.wait = instrumented_wait
        waiter = executor.submit(store.seal, ref, key="same", **args)
        grant = executor.submit(store.grant, ref, key="other", **args)
        try:
            assert waiting.wait(3) and grant_entered.wait(3)
            seal_release.set()
            with pytest.raises(RuntimeError, match="synthetic projection failure"):
                seal.result(timeout=3)
            with pytest.raises(ExternalEvidenceRecoveryError):
                waiter.result(timeout=3)
            grant_release.set()
            with pytest.raises(ExternalEvidenceRecoveryError):
                grant.result(timeout=3)
        finally:
            seal_release.set()
            grant_release.set()
    assert not store._pending
    assert len(store._journal.replay()) == len(before) + 1
    store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened._items[ref].manifest is not None
    reopened._journal.close()


@pytest.mark.parametrize("event", ["declare", "grant", "seal", "bind"])
@pytest.mark.parametrize("partial_apply", [False, True])
def test_each_projection_failure_requires_replay(
    tmp_path: Path, event: str, partial_apply: bool
) -> None:
    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        item.object_key, True, 5, item.declaration.declared_content_digest,
        item.declaration.declared_content_type,
    )
    before = list(store._journal.replay())
    original_apply = store._apply
    kind = {
        "declare": "external-evidence-declared",
        "grant": "external-evidence-grant-issued",
        "seal": "external-evidence-sealed",
        "bind": "external-evidence-idempotency-bound",
    }[event]

    def fail_live(raw: dict[str, Any]) -> None:
        if raw["kind"] == kind:
            if partial_apply:
                original_apply(raw)
            raise RuntimeError("projection fault")
        original_apply(raw)

    store._apply = fail_live
    intent = ExternalEvidenceDeclarationIntent.model_validate(
        _intent(b"new") if event == "declare" else _intent()
    )
    kwargs = dict(revision=revision, principal=principal, key="fault", now=_NOW)
    with pytest.raises(RuntimeError, match="projection fault"):
        if event in {"declare", "bind"}:
            store.declare(intent, **kwargs)
        elif event == "grant":
            store.grant(ref, storage=storage, **kwargs)
        else:
            store.seal(ref, storage=storage, **kwargs)
    assert len(store._journal.replay()) == len(before) + 1
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.list(revision)
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.is_declaration_retry(intent, revision=revision, principal=principal, key="fault")
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.declare(intent, **kwargs)
    store._journal.close()
    reopened = ExternalEvidenceStore(
        DurableJournal(tmp_path / "external-evidence.jsonl"), clock=lambda: _NOW
    )
    if event in {"declare", "bind"}:
        assert reopened.declare(intent, **kwargs).verdict is EvidenceVerdict.DECLARED
    elif event == "grant":
        assert reopened.grant(ref, storage=storage, **kwargs).verdict is EvidenceVerdict.DECLARED
    else:
        assert reopened.seal(ref, storage=storage, **kwargs).verdict is EvidenceVerdict.SEALED
    assert len(reopened._journal.replay()) == len(before) + 1
    reopened._journal.close()


def test_uncertain_journal_append_requires_replay_and_refuses_other_keys(tmp_path: Path) -> None:
    from ksi_core.durable_journal import JournalSealedError

    store, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    item = store._items[ref]
    storage.objects[item.object_key] = ObjectStorageObservation(
        item.object_key, True, 5, item.declaration.declared_content_digest,
        item.declaration.declared_content_type,
    )
    before = list(store._journal.replay())
    original_append = store._journal.append

    def append_then_fail(raw: Any) -> None:
        original_append(raw)
        raise JournalSealedError("synthetic uncertain append")

    store._journal.append = append_then_fail
    args = dict(revision=revision, principal=principal, storage=storage, now=_NOW)
    result = store.seal(ref, key="first", **args)
    assert result.verdict is EvidenceVerdict.STORAGE_UNAVAILABLE and result.item is None
    with pytest.raises(ExternalEvidenceRecoveryError):
        store.seal(ref, key="different", **args)
    assert len(store._journal.replay()) == len(before) + 1
    store._journal.close()
    reopened = ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
    assert reopened.seal(ref, key="first", **args).verdict is EvidenceVerdict.SEALED
    assert len(reopened._journal.replay()) == len(before) + 1
    reopened._journal.close()

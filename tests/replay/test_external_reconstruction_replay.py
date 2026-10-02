"""Strict replay for externally declared reconstruction byte observations."""

from __future__ import annotations

import copy
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_core.acquisition import observation_epoch_id
from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    DigestBoundUploadCapability,
    EvidenceStorageError,
    ObjectStorageObservation,
)
from ksi_core.external_reconstruction import (
    ExternalReconstructionRecoveryError,
    ExternalReconstructionStore,
    ExternalReconstructionVerdict,
    build_external_reconstruction_submission_ref,
)
from ksi_core.observation_work_orders import ObservationWorkOrder
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV2,
    parse_external_reconstruction_submission_v2,
)

_NOW = datetime(2026, 9, 6, tzinfo=UTC)


class _Storage:
    def __init__(self) -> None:
        self.observations: dict[str, ObjectStorageObservation] = {}

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: object
    ) -> DigestBoundUploadCapability:
        del content_type, content_digest, ttl
        return DigestBoundUploadCapability(
            upload_url=f"https://test.invalid/{object_key}", required_headers={}
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.observations[object_key]


def _order() -> ObservationWorkOrder:
    return cast(
        ObservationWorkOrder,
        SimpleNamespace(
            organization_id="org-a",
            site_id="site-a",
            work_order_id="order-a",
            version=1,
            cycle_number=1,
        ),
    )


def _submission(
    order: ObservationWorkOrder,
    *,
    revision: int = 1,
    submission_id: str = "submission-a",
    payload: bytes = b"bytes",
    content_type: str = "application/octet-stream",
) -> ExternalReconstructionSubmissionV1:
    wire = {
        "submissionId": submission_id,
        "revision": revision,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": observation_epoch_id(order),
        "submittedAt": "2026-09-06T00:00:00Z",
        "submittedBy": "operator-a",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Mapper",
            "softwareVersion": "1",
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
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "o.tif",
                "format": "GeoTIFF",
                "contentType": content_type,
                "declaredSha256": hashlib.sha256(payload).hexdigest(),
                "declaredSizeBytes": len(payload),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
    return ExternalReconstructionSubmissionV1.model_validate(wire)


def _submission_v2(
    order: ObservationWorkOrder,
    *,
    revision: int = 1,
    submission_id: str = "submission-v2",
    payload: bytes = b"dsm-bytes",
    content_type: str = "application/octet-stream",
) -> ExternalReconstructionSubmissionV2:
    wire: dict[str, Any] = {
        "contractVersion": "external-reconstruction-submission.v2",
        "submissionId": submission_id,
        "revision": revision,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": observation_epoch_id(order),
        "submittedAt": "2026-09-06T00:00:00Z",
        "submittedBy": "operator-a",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Mapper",
            "softwareVersion": "1",
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
        "artifacts": [
            {
                "artifactId": "dsm",
                "kind": "dsm",
                "fileName": "dsm.tif",
                "format": "GeoTIFF",
                "contentType": content_type,
                "declaredSha256": hashlib.sha256(payload).hexdigest(),
                "declaredSizeBytes": len(payload),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV2.digest_for_wire(wire)
    return parse_external_reconstruction_submission_v2(wire)


def test_replay_restores_exact_sealed_manifest_and_refuses_unknown_event(
    tmp_path: Path,
) -> None:
    """Removing event digests, binding derivation, or fail-closed replay must break this."""
    path = tmp_path / "external.jsonl"
    order, storage = _order(), _Storage()
    journal = DurableJournal(path)
    store = ExternalReconstructionStore(journal)
    submission = _submission(order)
    assert (
        store.register(submission, work_order=order, registered_by="operator-a", now=_NOW).verdict
        is ExternalReconstructionVerdict.REGISTERED
    )
    grants = store.upload_grants(
        "order-a", "submission-a", 1, organization_id="org-a", site_id="site-a", storage=storage
    )
    grant = grants.grants[0]
    storage.observations[grant.object_key] = ObjectStorageObservation(
        object_key=grant.object_key,
        exists=True,
        size_bytes=5,
        sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
        content_type="application/octet-stream",
    )
    sealed = store.seal(
        "order-a",
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert sealed.verdict is ExternalReconstructionVerdict.SEALED
    assert sealed.revision is not None and sealed.revision.manifest is not None
    expected = sealed.revision.manifest.manifest_digest
    journal.close()

    reopened_journal = DurableJournal(path)
    reopened = ExternalReconstructionStore(reopened_journal)
    replayed = reopened.get("order-a", "submission-a", 1, organization_id="org-a", site_id="site-a")
    assert replayed is not None and replayed.manifest is not None
    assert replayed.manifest.manifest_digest == expected
    reopened_journal.close()

    forged_path = tmp_path / "forged.jsonl"
    forged = DurableJournal(forged_path)
    forged.append({"kind": "unknown", "version": 1, "eventDigest": "sha256:" + "0" * 64})
    forged.close()
    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(forged_path))


def test_spatial_asset_reference_and_observed_identity_survive_replay(tmp_path: Path) -> None:
    path = tmp_path / "catalog-identity.jsonl"
    order, storage = _order(), _Storage()
    journal = DurableJournal(path)
    store = ExternalReconstructionStore(journal)
    submission = _submission(order)
    assert store.register(
        submission, work_order=order, registered_by="operator-a", now=_NOW
    ).revision is not None
    grant = store.upload_grants(
        "order-a", "submission-a", 1, organization_id="org-a", site_id="site-a", storage=storage
    ).grants[0]
    storage.observations[grant.object_key] = ObjectStorageObservation(
        object_key=grant.object_key,
        exists=True,
        size_bytes=5,
        sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
        content_type="application/octet-stream",
    )
    sealed = store.seal(
        "order-a",
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert sealed.revision is not None and sealed.revision.manifest is not None
    assert store.register(
        _submission(order, revision=2),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).revision is not None
    before_ref = build_external_reconstruction_submission_ref(
        organization_id="org-a", work_order_id="order-a", submission_id="submission-a"
    )
    before_asset_ref = SpatialAssetCatalog._asset_ref(before_ref, 1, "ortho")
    before_manifest_digest = sealed.revision.manifest.manifest_digest
    journal.close()

    replayed_store = ExternalReconstructionStore(DurableJournal(path))
    replayed = replayed_store.get(
        "order-a", "submission-a", 1, organization_id="org-a", site_id="site-a"
    )
    assert replayed is not None and replayed.manifest is not None
    bounded_revisions = replayed_store.list_bounded_for_work_order(
        "order-a",
        organization_id="org-a",
        site_id="site-a",
        max_submissions=1,
        max_revisions=2,
    )
    assert bounded_revisions[0] == replayed
    assert bounded_revisions[1].submission.revision == 2
    after_ref = build_external_reconstruction_submission_ref(
        organization_id=replayed.submission.organization_id,
        work_order_id=replayed.work_order_id,
        submission_id=replayed.submission.submission_id,
    )
    after_asset_ref = SpatialAssetCatalog._asset_ref(
        after_ref, replayed.submission.revision, replayed.submission.artifacts[0].artifact_id
    )

    assert after_asset_ref == before_asset_ref
    assert replayed.manifest.manifest_digest == before_manifest_digest
    assert replayed.manifest.entries[0].observed_sha256 == hashlib.sha256(b"bytes").hexdigest()
    replayed_store._journal.close()  # noqa: SLF001 -- close replay fixture journal


def test_v2_dsm_register_grant_seal_retry_and_replay_preserve_v1_manifest_shape(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v2-dsm.jsonl"
    order, storage = _order(), _Storage()
    journal = DurableJournal(path)
    store = ExternalReconstructionStore(journal)
    submission = _submission_v2(order)

    registered = store.register(
        submission, work_order=order, registered_by="operator-a", now=_NOW
    )
    assert registered.verdict is ExternalReconstructionVerdict.REGISTERED
    assert registered.revision is not None
    submission_ref = build_external_reconstruction_submission_ref(
        organization_id="org-a", work_order_id="order-a", submission_id="submission-v2"
    )
    assert store.resolve_submission_ref(
        "order-a", submission_ref, organization_id="org-a", site_id="site-a"
    ) == "submission-v2"
    retry = store.register(
        submission, work_order=order, registered_by="operator-a", now=_NOW
    )
    assert retry.verdict is ExternalReconstructionVerdict.REGISTERED
    assert retry.revision is registered.revision
    assert len(journal.replay()) == 1

    cross_version = _submission(order, revision=2, submission_id="submission-v2")
    assert store.register(
        cross_version, work_order=order, registered_by="operator-a", now=_NOW
    ).verdict is ExternalReconstructionVerdict.CONFLICT

    v1_first = ExternalReconstructionStore(DurableJournal(tmp_path / "v1-first.jsonl"))
    first_v1 = _submission(order, submission_id="submission-mixed")
    assert v1_first.register(
        first_v1, work_order=order, registered_by="operator-a", now=_NOW
    ).verdict is ExternalReconstructionVerdict.REGISTERED
    v2_successor = _submission_v2(
        order, revision=2, submission_id="submission-mixed", payload=b"successor"
    )
    assert v1_first.register(
        v2_successor, work_order=order, registered_by="operator-a", now=_NOW
    ).verdict is ExternalReconstructionVerdict.CONFLICT
    v1_first._journal.close()

    grants = store.upload_grants(
        "order-a", "submission-v2", 1, organization_id="org-a", site_id="site-a", storage=storage
    )
    grant = grants.grants[0]
    _observe_declared(storage, grant, payload=b"wrong")
    mismatch = store.seal(
        "order-a",
        "submission-v2",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert mismatch.verdict is ExternalReconstructionVerdict.OBSERVATION_MISMATCH
    _observe_declared(storage, grant, payload=b"dsm-bytes")
    sealed = store.seal(
        "order-a",
        "submission-v2",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert sealed.verdict is ExternalReconstructionVerdict.SEALED
    assert sealed.revision is not None and sealed.revision.manifest is not None
    assert sealed.revision.submission.submission_digest == submission.submission_digest
    assert sealed.revision.manifest.contract_version == "external-reconstruction-manifest.v1"
    assert [(entry.artifact_id, entry.kind) for entry in sealed.revision.manifest.entries] == [
        ("dsm", "dsm")
    ]
    assert len(journal.replay()) == 2
    sealed_retry = store.seal(
        "order-a",
        "submission-v2",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert sealed_retry.verdict is ExternalReconstructionVerdict.SEALED
    assert len(journal.replay()) == 2
    journal.close()

    reopened = ExternalReconstructionStore(DurableJournal(path))
    replayed = reopened.get(
        "order-a", "submission-v2", 1, organization_id="org-a", site_id="site-a"
    )
    assert replayed is not None and replayed.manifest is not None
    assert isinstance(replayed.submission, ExternalReconstructionSubmissionV2)
    assert replayed.submission.submission_digest == submission.submission_digest
    assert replayed.manifest.manifest_digest == sealed.revision.manifest.manifest_digest
    assert reopened.resolve_submission_ref(
        "order-a", submission_ref, organization_id="org-a", site_id="site-a"
    ) == "submission-v2"
    reopened._journal.close()


@pytest.mark.parametrize(
    "tamper", ("missing-version", "forged-version", "missing-digest", "forged-digest")
)
def test_v2_registration_replay_rejects_version_or_digest_tampering(
    tmp_path: Path, tamper: str
) -> None:
    from ksi_core.external_reconstruction import _event_digest

    source = ExternalReconstructionStore(DurableJournal(tmp_path / f"source-{tamper}.jsonl"))
    assert source.register(
        _submission_v2(_order()), work_order=_order(), registered_by="operator-a", now=_NOW
    ).revision
    event = copy.deepcopy(source._journal.replay()[0])
    source._journal.close()
    submission = event["submission"]
    if tamper == "missing-version":
        submission.pop("contractVersion")
    elif tamper == "forged-version":
        submission["contractVersion"] = "external-reconstruction-submission.v3"
    elif tamper == "missing-digest":
        submission.pop("submissionDigest")
    else:
        submission["submissionDigest"] = "sha256:" + "0" * 64
    event["eventDigest"] = _event_digest(event)
    forged_path = tmp_path / f"forged-{tamper}.jsonl"
    forged = DurableJournal(forged_path)
    forged.append(event)
    forged.close()

    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(forged_path))


def test_v2_replay_rejects_cross_version_revision_stream(tmp_path: Path) -> None:
    target_path = tmp_path / "mixed-stream.jsonl"
    order = _order()
    target = ExternalReconstructionStore(DurableJournal(target_path))
    assert target.register(
        _submission_v2(order, submission_id="submission-mixed"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).revision
    target._journal.close()

    source = ExternalReconstructionStore(DurableJournal(tmp_path / "v1-source.jsonl"))
    assert source.register(
        _submission(order, submission_id="submission-mixed"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).revision
    assert source.register(
        _submission(order, revision=2, submission_id="submission-mixed", payload=b"next"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).revision
    v1_revision_two = source._journal.replay()[1]
    source._journal.close()

    append = DurableJournal(target_path)
    append.append(v1_revision_two)
    append.close()
    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(target_path))


def test_replay_rejects_boolean_event_version_even_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    """Changing strict event-version type checking admits forged JSON booleans."""
    from ksi_core.external_reconstruction import _event_digest

    store = ExternalReconstructionStore(DurableJournal(tmp_path / "source.jsonl"))
    submission = _submission(_order())
    assert store.register(
        submission, work_order=_order(), registered_by="operator-a", now=_NOW
    ).revision
    source = store._journal.replay()[0]
    store._journal.close()
    source["version"] = True
    source["eventDigest"] = _event_digest(source)
    forged_path = tmp_path / "bool-version.jsonl"
    forged = DurableJournal(forged_path)
    forged.append(source)
    forged.close()
    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(forged_path))


def _registered_store(
    tmp_path: Path,
) -> tuple[ExternalReconstructionStore, _Storage, ObservationWorkOrder]:
    order = _order()
    storage = _Storage()
    store = ExternalReconstructionStore(DurableJournal(tmp_path / "external.jsonl"))
    result = store.register(
        _submission(order), work_order=order, registered_by="operator-a", now=_NOW
    )
    assert result.verdict is ExternalReconstructionVerdict.REGISTERED
    return store, storage, order


def _observe_declared(
    storage: _Storage,
    grant: Any,
    payload: bytes = b"bytes",
) -> None:
    storage.observations[grant.object_key] = ObjectStorageObservation(
        object_key=grant.object_key,
        exists=True,
        size_bytes=len(payload),
        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        content_type="application/octet-stream",
    )


def test_storage_failures_do_not_publish_grants_or_seals_and_retry_without_registration_duplicate(
    tmp_path: Path,
) -> None:
    """Publishing a capability or manifest after presign/HEAD failure corrupts the receipt state."""
    store, storage, order = _registered_store(tmp_path)
    original_count = len(store._journal.replay())

    class PresignFailure(_Storage):
        def presigned_put_bound_digest(
            self, *args: Any, **kwargs: Any
        ) -> DigestBoundUploadCapability:
            del args, kwargs
            raise EvidenceStorageError("offline")

    failed_grant = store.upload_grants(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=PresignFailure(),
    )
    assert failed_grant.verdict is ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
    assert len(store._journal.replay()) == original_count
    grants = store.upload_grants(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
    )
    assert grants.verdict is ExternalReconstructionVerdict.REGISTERED
    assert len(store._journal.replay()) == original_count

    class HeadFailure(_Storage):
        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            del object_key
            raise EvidenceStorageError("offline")

    failed_seal = store.seal(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=HeadFailure(),
        now=_NOW,
    )
    assert failed_seal.verdict is ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
    assert len(store._journal.replay()) == original_count
    _observe_declared(storage, grants.grants[0])
    sealed = store.seal(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert sealed.verdict is ExternalReconstructionVerdict.SEALED
    assert len(store._journal.replay()) == original_count + 1


@pytest.mark.parametrize(
    "observation",
    [
        ObjectStorageObservation(
            object_key="wrong-key",
            exists=True,
            size_bytes=5,
            sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
            content_type="application/octet-stream",
        ),
        ObjectStorageObservation(
            object_key="placeholder",
            exists=True,
            size_bytes=4,
            sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
            content_type="application/octet-stream",
        ),
        ObjectStorageObservation(
            object_key="placeholder",
            exists=True,
            size_bytes=5,
            sha256="sha256:" + "f" * 64,
            content_type="application/octet-stream",
        ),
        ObjectStorageObservation(
            object_key="placeholder",
            exists=True,
            size_bytes=5,
            sha256=None,
            content_type="application/octet-stream",
        ),
        ObjectStorageObservation(
            object_key="placeholder",
            exists=True,
            size_bytes=5,
            sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
            content_type="text/html",
        ),
    ],
)
def test_untrusted_or_mismatched_head_observations_do_not_append_seals(
    tmp_path: Path,
    observation: ObjectStorageObservation,
) -> None:
    """Accepting wrong HEAD metadata falsely turns a byte declaration into a seal."""
    store, _storage, order = _registered_store(tmp_path)
    grants = store.upload_grants(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=_Storage(),
    )
    assert grants.grants
    expected_key = grants.grants[0].object_key

    class FixedObservation(_Storage):
        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            del object_key
            return ObjectStorageObservation(
                object_key=expected_key
                if observation.object_key == "placeholder"
                else observation.object_key,
                exists=observation.exists,
                size_bytes=observation.size_bytes,
                sha256=observation.sha256,
                content_type=observation.content_type,
            )

    result = store.seal(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=FixedObservation(),
        now=_NOW,
    )
    assert result.verdict is ExternalReconstructionVerdict.OBSERVATION_MISMATCH
    assert len(store._journal.replay()) == 1


def test_journal_append_failure_never_publishes_registration_or_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applying state before durable append would make a failed journal write visible."""
    order = _order()
    registration_store = ExternalReconstructionStore(
        DurableJournal(tmp_path / "registration.jsonl")
    )

    def fail_append(_raw: dict[str, Any]) -> None:
        raise JournalSealedError("disk failure")

    monkeypatch.setattr(registration_store._journal, "append", fail_append)
    registration = registration_store.register(
        _submission(order),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    )
    assert registration.verdict is ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
    assert (
        registration_store.list(order.work_order_id, organization_id="org-a", site_id="site-a")
        == ()
    )

    store, storage, order = _registered_store(tmp_path / "seal")
    grants = store.upload_grants(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
    )
    _observe_declared(storage, grants.grants[0])
    monkeypatch.setattr(store._journal, "append", fail_append)
    seal = store.seal(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=_NOW,
    )
    assert seal.verdict is ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
    record = store.get(
        order.work_order_id, "submission-a", 1, organization_id="org-a", site_id="site-a"
    )
    assert record is not None and record.manifest is None


def test_concurrent_identical_and_conflicting_registration_have_one_durable_winner(
    tmp_path: Path,
) -> None:
    """Removing the registration lock can append duplicate or contradictory revisions."""
    order = _order()
    store = ExternalReconstructionStore(DurableJournal(tmp_path / "external.jsonl"))
    barrier = threading.Barrier(2, timeout=3)

    def register(submission: ExternalReconstructionSubmissionV1) -> ExternalReconstructionVerdict:
        barrier.wait()
        return store.register(
            submission,
            work_order=order,
            registered_by="operator-a",
            now=_NOW,
        ).verdict

    original = _submission(order)
    with ThreadPoolExecutor(max_workers=2) as pool:
        verdicts = list(pool.map(register, (original, original)))
    assert verdicts == [ExternalReconstructionVerdict.REGISTERED] * 2
    assert len(store._journal.replay()) == 1

    conflict_store = ExternalReconstructionStore(DurableJournal(tmp_path / "conflict.jsonl"))
    barrier = threading.Barrier(2, timeout=3)

    def conflict_register(
        submission: ExternalReconstructionSubmissionV1,
    ) -> ExternalReconstructionVerdict:
        barrier.wait()
        return conflict_store.register(
            submission,
            work_order=order,
            registered_by="operator-a",
            now=_NOW,
        ).verdict

    with ThreadPoolExecutor(max_workers=2) as pool:
        verdicts = list(
            pool.map(conflict_register, (_submission(order), _submission(order, payload=b"other")))
        )
    assert sorted(verdict.value for verdict in verdicts) == ["CONFLICT", "REGISTERED"]
    assert len(conflict_store._journal.replay()) == 1


def test_concurrent_identical_seals_return_the_same_manifest_and_append_once(
    tmp_path: Path,
) -> None:
    """Treating a concurrently sealed same revision as superseded breaks idempotent sealing."""
    store, _storage, order = _registered_store(tmp_path)

    class BarrierStorage(_Storage):
        def __init__(self) -> None:
            super().__init__()
            self.barrier = threading.Barrier(2, timeout=3)

        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            self.barrier.wait()
            return ObjectStorageObservation(
                object_key=object_key,
                exists=True,
                size_bytes=5,
                sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
                content_type="application/octet-stream",
            )

    storage = BarrierStorage()

    def seal() -> Any:
        return store.seal(
            order.work_order_id,
            "submission-a",
            1,
            organization_id="org-a",
            site_id="site-a",
            storage=storage,
            now=_NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: seal(), range(2)))
    assert [result.verdict for result in results] == [ExternalReconstructionVerdict.SEALED] * 2
    manifests = [
        result.revision.manifest.manifest_digest
        for result in results
        if result.revision and result.revision.manifest
    ]
    assert manifests == [manifests[0], manifests[0]]
    assert len(store._journal.replay()) == 2


def test_corrective_revision_can_invalidate_blocked_head_or_presign_without_holding_store_lock(
    tmp_path: Path,
) -> None:
    """Holding the lock over I/O deadlocks correction; omitting recheck returns stale authority."""
    store, _storage, order = _registered_store(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class BlockingStorage(_Storage):
        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            entered.set()
            assert release.wait(3)
            return ObjectStorageObservation(
                object_key=object_key,
                exists=True,
                size_bytes=5,
                sha256="sha256:" + hashlib.sha256(b"bytes").hexdigest(),
                content_type="application/octet-stream",
            )

        def presigned_put_bound_digest(
            self, *args: Any, **kwargs: Any
        ) -> DigestBoundUploadCapability:
            entered.set()
            assert release.wait(3)
            return super().presigned_put_bound_digest(*args, **kwargs)

    storage = BlockingStorage()

    def seal() -> Any:
        return store.seal(
            order.work_order_id,
            "submission-a",
            1,
            organization_id="org-a",
            site_id="site-a",
            storage=storage,
            now=_NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        seal_future = pool.submit(seal)
        assert entered.wait(3)
        correction = store.register(
            _submission(order, revision=2, payload=b"revised"),
            work_order=order,
            registered_by="operator-a",
            now=_NOW,
        )
        assert correction.verdict is ExternalReconstructionVerdict.REGISTERED
        release.set()
        assert seal_future.result(timeout=3).verdict is ExternalReconstructionVerdict.SUPERSEDED

    entered.clear()
    release.clear()

    def grants() -> Any:
        return store.upload_grants(
            order.work_order_id,
            "submission-a",
            2,
            organization_id="org-a",
            site_id="site-a",
            storage=storage,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        grant_future = pool.submit(grants)
        assert entered.wait(3)
        correction = store.register(
            _submission(order, revision=3, payload=b"revised-again"),
            work_order=order,
            registered_by="operator-a",
            now=_NOW,
        )
        assert correction.verdict is ExternalReconstructionVerdict.REGISTERED
        release.set()
        assert grant_future.result(timeout=3).verdict is ExternalReconstructionVerdict.SUPERSEDED


def _sealed_records(tmp_path: Path) -> list[dict[str, Any]]:
    store, storage, order = _registered_store(tmp_path)
    grants = store.upload_grants(
        order.work_order_id,
        "submission-a",
        1,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
    )
    _observe_declared(storage, grants.grants[0])
    assert (
        store.seal(
            order.work_order_id,
            "submission-a",
            1,
            organization_id="org-a",
            site_id="site-a",
            storage=storage,
            now=_NOW,
        ).verdict
        is ExternalReconstructionVerdict.SEALED
    )
    records = store._journal.replay()
    store._journal.close()
    return records


def _rejects_replay(tmp_path: Path, name: str, records: list[dict[str, Any]]) -> None:
    path = tmp_path / f"{name}.jsonl"
    journal = DurableJournal(path)
    for record in records:
        journal.append(record)
    journal.close()
    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(path))


def _reseal_manifest(raw: dict[str, Any]) -> None:
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionManifestV1

    candidate = dict(raw["manifest"])
    candidate.pop("manifestDigest", None)
    raw["manifest"]["manifestDigest"] = ExternalReconstructionManifestV1.model_validate(
        candidate
    ).canonical_digest()


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-kind",
        "unknown-version",
        "bool-version",
        "bool-cycle",
        "bool-revision",
        "extra-field",
        "binding-key",
        "forged-epoch",
        "forged-actor",
    ],
)
def test_replay_rejects_complete_semantically_forged_registration_events(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Checking only unkeyed outer digest permits coherent forged journal semantics."""
    from ksi_core.external_reconstruction import _event_digest
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    records = _sealed_records(tmp_path / mutation)
    registration = records[0]
    if mutation == "unknown-kind":
        registration["kind"] = "external-reconstruction-unknown"
    elif mutation == "unknown-version":
        registration["version"] = 2
    elif mutation == "bool-version":
        registration["version"] = True
    elif mutation == "bool-cycle":
        registration["cycleNumber"] = True
    elif mutation == "bool-revision":
        registration["submission"]["revision"] = True
    elif mutation == "extra-field":
        registration["unexpected"] = "forged"
    elif mutation == "binding-key":
        registration["bindings"][0]["objectKey"] = "external-reconstruction/v1/forged"
    elif mutation == "forged-epoch":
        registration["observationEpochId"] = "obs-epoch-forged"
        registration["submission"]["observationEpochId"] = "obs-epoch-forged"
        registration["submission"]["submissionDigest"] = (
            ExternalReconstructionSubmissionV1.digest_for_wire(registration["submission"])
        )
    else:
        registration["registeredBy"] = "forged-actor"
    registration["eventDigest"] = _event_digest(registration)
    _rejects_replay(tmp_path, mutation, records)


def test_replay_rejects_frozen_witness_drift_gaps_duplicates_and_illegal_seal_transitions(
    tmp_path: Path,
) -> None:
    """Removing stream transition checks accepts contradictory revision and seal histories."""
    from ksi_core.external_reconstruction import (
        _event_digest,
        build_external_reconstruction_object_key,
    )
    from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

    order = _order()
    source = ExternalReconstructionStore(DurableJournal(tmp_path / "source.jsonl"))
    assert source.register(
        _submission(order), work_order=order, registered_by="operator-a", now=_NOW
    ).revision
    assert source.register(
        _submission(order, revision=2, payload=b"revised"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).revision
    registrations = source._journal.replay()
    source._journal.close()

    witness_drift = [dict(item) for item in registrations]
    witness_drift[1]["workOrderVersion"] = 2
    witness_drift[1]["eventDigest"] = _event_digest(witness_drift[1])
    _rejects_replay(tmp_path, "version-drift", witness_drift)

    first_revision_gap = [dict(registrations[0])]
    first_gap_submission = dict(first_revision_gap[0]["submission"])
    first_gap_submission["revision"] = 2
    first_gap_submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        first_gap_submission
    )
    first_revision_gap[0]["submission"] = first_gap_submission
    first_revision_gap[0]["bindings"] = [
        {
            "artifactId": "ortho",
            "objectKey": build_external_reconstruction_object_key(
                organization_id="org-a",
                site_id="site-a",
                work_order_id="order-a",
                cycle_number=1,
                observation_epoch_id=observation_epoch_id(order),
                submission_id="submission-a",
                revision=2,
                artifact_id="ortho",
            ),
        }
    ]
    first_revision_gap[0]["eventDigest"] = _event_digest(first_revision_gap[0])
    _rejects_replay(tmp_path, "first-revision-gap", first_revision_gap)

    gap = [dict(item) for item in registrations]
    gap_submission = dict(gap[1]["submission"])
    gap_submission["revision"] = 3
    gap_submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        gap_submission
    )
    gap[1]["submission"] = gap_submission
    gap[1]["bindings"] = [
        {
            "artifactId": "ortho",
            "objectKey": build_external_reconstruction_object_key(
                organization_id="org-a",
                site_id="site-a",
                work_order_id="order-a",
                cycle_number=1,
                observation_epoch_id=observation_epoch_id(order),
                submission_id="submission-a",
                revision=3,
                artifact_id="ortho",
            ),
        }
    ]
    gap[1]["eventDigest"] = _event_digest(gap[1])
    _rejects_replay(tmp_path, "revision-gap", gap)

    _rejects_replay(tmp_path, "duplicate-registration", [registrations[0], registrations[0]])
    conflicting_duplicate = [dict(registrations[0]), dict(registrations[0])]
    changed_submission = dict(conflicting_duplicate[1]["submission"])
    changed_submission["artifacts"] = [dict(changed_submission["artifacts"][0])]
    changed_submission["artifacts"][0]["declaredSha256"] = "f" * 64
    changed_submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        changed_submission
    )
    conflicting_duplicate[1]["submission"] = changed_submission
    conflicting_duplicate[1]["eventDigest"] = _event_digest(conflicting_duplicate[1])
    _rejects_replay(tmp_path, "conflicting-duplicate", conflicting_duplicate)
    sealed = _sealed_records(tmp_path / "seal-source")
    _rejects_replay(tmp_path, "seal-before-registration", [sealed[1]])
    _rejects_replay(tmp_path, "duplicate-seal", [sealed[0], sealed[1], sealed[1]])
    conflicting_seal = [dict(sealed[0]), dict(sealed[1]), dict(sealed[1])]
    conflicting_seal[2]["observedAt"] = "2026-09-06T00:01:00Z"
    conflicting_manifest = dict(conflicting_seal[2]["manifest"])
    conflicting_manifest["observedAt"] = "2026-09-06T00:01:00Z"
    conflicting_seal[2]["manifest"] = conflicting_manifest
    _reseal_manifest(conflicting_seal[2])
    conflicting_seal[2]["eventDigest"] = _event_digest(conflicting_seal[2])
    _rejects_replay(tmp_path, "conflicting-duplicate-seal", conflicting_seal)
    _rejects_replay(
        tmp_path,
        "superseded-seal",
        [registrations[0], registrations[1], sealed[1]],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact-set",
        "object-key",
        "observed-sha256",
        "observed-size",
        "content-type",
        "submission-digest",
    ],
)
def test_replay_rejects_complete_manifest_binding_tamper(
    tmp_path: Path,
    mutation: str,
) -> None:
    """A manifest digest alone cannot prove it binds the registered declaration and bytes."""
    from ksi_core.external_reconstruction import _event_digest

    records = _sealed_records(tmp_path / mutation)
    seal = records[1]
    if mutation == "artifact-set":
        seal["manifest"]["entries"][0]["artifactId"] = "different-artifact"
    elif mutation == "object-key":
        seal["manifest"]["entries"][0]["objectKey"] = "external-reconstruction/v1/forged"
    elif mutation == "observed-sha256":
        seal["manifest"]["entries"][0]["observedSha256"] = "f" * 64
    elif mutation == "observed-size":
        seal["manifest"]["entries"][0]["observedSizeBytes"] = 4
    elif mutation == "content-type":
        seal["manifest"]["entries"][0]["observedContentType"] = "application/x-forged"
    else:
        seal["manifest"]["submissionDigest"] = "sha256:" + "f" * 64
    _reseal_manifest(seal)
    seal["eventDigest"] = _event_digest(seal)
    _rejects_replay(tmp_path, mutation, records)


def test_replay_restores_historical_frozen_witness_without_current_work_order_projection(
    tmp_path: Path,
) -> None:
    """Consulting current WorkOrder state during replay breaks durable historical corrections."""
    first = _order()
    advanced = cast(
        ObservationWorkOrder,
        SimpleNamespace(
            organization_id="org-a",
            site_id="site-a",
            work_order_id="order-a",
            version=7,
            cycle_number=2,
        ),
    )
    journal = DurableJournal(tmp_path / "historical.jsonl")
    store = ExternalReconstructionStore(journal)
    assert store.register(
        _submission(first), work_order=first, registered_by="operator-a", now=_NOW
    ).revision
    correction = store.register(
        _submission(first, revision=2, payload=b"revised"),
        work_order=advanced,
        registered_by="operator-a",
        now=_NOW,
    )
    assert correction.verdict is ExternalReconstructionVerdict.REGISTERED
    journal.close()
    reopened = ExternalReconstructionStore(DurableJournal(tmp_path / "historical.jsonl"))
    record = reopened.get("order-a", "submission-a", 2, organization_id="org-a", site_id="site-a")
    assert record is not None
    assert (record.work_order_version, record.cycle_number, record.observation_epoch_id) == (
        1,
        1,
        observation_epoch_id(first),
    )
    reopened._journal.close()


def test_replay_derives_stable_public_refs_from_old_raw_identifier_events_without_rewrite(
    tmp_path: Path,
) -> None:
    """Adding public refs must not require rewriting accepted raw-ID journal events."""
    from ksi_core.external_reconstruction import build_external_reconstruction_submission_ref

    order = _order()
    journal_path = tmp_path / "old-format.jsonl"
    store = ExternalReconstructionStore(DurableJournal(journal_path))
    raw_submission_id = "customer/run-1"
    assert store.register(
        _submission(order, submission_id=raw_submission_id),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).verdict is ExternalReconstructionVerdict.REGISTERED
    assert store.register(
        _submission(order, submission_id=raw_submission_id, revision=2, payload=b"revised"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).verdict is ExternalReconstructionVerdict.REGISTERED
    recorded = store._journal.replay()
    assert all("submissionRef" not in event for event in recorded)
    store._journal.close()

    submission_ref = build_external_reconstruction_submission_ref(
        organization_id="org-a",
        work_order_id=order.work_order_id,
        submission_id=raw_submission_id,
    )
    reopened = ExternalReconstructionStore(DurableJournal(journal_path))
    assert reopened.resolve_submission_ref(
        order.work_order_id,
        submission_ref,
        organization_id="org-a",
        site_id="site-a",
    ) == raw_submission_id
    assert reopened.resolve_submission_ref(
        order.work_order_id,
        submission_ref,
        organization_id="org-b",
        site_id="site-b",
    ) is None
    replayed = reopened.get(
        order.work_order_id,
        raw_submission_id,
        2,
        organization_id="org-a",
        site_id="site-a",
    )
    assert replayed is not None
    assert build_external_reconstruction_submission_ref(
        organization_id=replayed.submission.organization_id,
        work_order_id=replayed.work_order_id,
        submission_id=replayed.submission.submission_id,
    ) == submission_ref
    reopened._journal.close()


def test_submission_ref_collision_fails_closed_before_append_and_during_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mapping two raw IDs to one opaque address must neither publish nor recover ambiguity."""
    import ksi_core.external_reconstruction as external_reconstruction

    order = _order()
    replay_path = tmp_path / "collision-replay.jsonl"
    source = ExternalReconstructionStore(DurableJournal(replay_path))
    assert source.register(
        _submission(order, submission_id="first-raw-id"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).verdict is ExternalReconstructionVerdict.REGISTERED
    assert source.register(
        _submission(order, submission_id="second-raw-id"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    ).verdict is ExternalReconstructionVerdict.REGISTERED
    source._journal.close()

    def colliding_ref(**_scope: str) -> str:
        return "ers-v1-" + "0" * 64

    monkeypatch.setattr(
        external_reconstruction,
        "build_external_reconstruction_submission_ref",
        colliding_ref,
    )
    with pytest.raises(ExternalReconstructionRecoveryError):
        ExternalReconstructionStore(DurableJournal(replay_path))

    live = ExternalReconstructionStore(DurableJournal(tmp_path / "collision-live.jsonl"))
    first = live.register(
        _submission(order, submission_id="first-raw-id"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    )
    assert first.verdict is ExternalReconstructionVerdict.REGISTERED
    event_count = len(live._journal.replay())
    collision = live.register(
        _submission(order, submission_id="second-raw-id"),
        work_order=order,
        registered_by="operator-a",
        now=_NOW,
    )
    assert collision.verdict is ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
    assert len(live._journal.replay()) == event_count
    live._journal.close()

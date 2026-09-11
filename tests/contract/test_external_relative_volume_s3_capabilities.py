"""S3 DSM capabilities for a leased external relative-volume worker.

The durable reconstruction and relative-volume stores remain real here.  The
only boundary replacement is a deterministic object-storage test double: it
records presign requests but never creates a real bearer URL.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from ksi_core.acquisition import observation_epoch_id
from ksi_core.auth import Principal, PrincipalKind
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError, ObjectStorageObservation
from ksi_core.external_reconstruction import (
    ExternalReconstructionStore,
    ExternalReconstructionVerdict,
)
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_reconstruction import (
    ExternalArtifactDeclarationV1,
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from test_external_relative_volumes import _NOW, _authority, _principal, _store


class _RecordingStorage:
    """Test-only storage boundary that records GET presigning, never real URLs."""

    def __init__(self) -> None:
        self.observations: dict[str, ObjectStorageObservation] = {}
        self.presigned_get_calls: list[tuple[str, timedelta]] = []
        self.fail_presign = False
        self.fail_on_presign_call: int | None = None

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.observations.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        self.presigned_get_calls.append((object_key, ttl))
        if self.fail_presign or len(self.presigned_get_calls) == self.fail_on_presign_call:
            raise EvidenceStorageError("test storage unavailable")
        return f"https://storage.invalid/get/{object_key}"

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        del content_type, ttl
        return f"https://storage.invalid/put/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self.observations[object_key] = ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        raise EvidenceStorageError(f"test storage has no bytes for {object_key}")

    def delete(self, object_key: str) -> None:
        self.observations.pop(object_key, None)


def _worker(*, organization_id: str = "org-a") -> Principal:
    return Principal(
        principal_id="volume-worker",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id=organization_id,
    )


def _submission(
    *,
    binding: Any,
    work_order_id: str,
    epoch_id: str,
) -> ExternalReconstructionSubmissionV1:
    def artifact(
        artifact_id: str, kind: ProcessingArtifactKind, digest: str, size: int
    ) -> ExternalArtifactDeclarationV1:
        return ExternalArtifactDeclarationV1(
            artifact_id=artifact_id,
            kind=kind,
            file_name=f"{artifact_id}.tif",
            format="GeoTIFF",
            content_type="application/octet-stream",
            declared_sha256=digest.removeprefix("sha256:"),
            declared_size_bytes=size,
            declared_crs=None,
            declared_vertical_reference=None,
            declared_gsd_m=None,
        )

    return ExternalReconstructionSubmissionV1(
        submission_id=binding.subject.submission_id,
        revision=binding.subject.revision,
        organization_id="org-a",
        site_id="site-a",
        observation_epoch_id=epoch_id,
        submitted_at=_NOW,
        submitted_by="operator-a",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="Customer Mapper",
            software_version="1.0",
            build_identifier=None,
            producer_run_identifier="run-1",
            configuration_digest=None,
            completed_at=None,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=None,
            image_count=None,
            capture_started_at=None,
            capture_ended_at=None,
        ),
        artifacts=(
            artifact("ortho", ProcessingArtifactKind.ORTHO, "sha256:" + "a" * 64, 10),
            artifact(
                binding.dsm_artifact_id,
                ProcessingArtifactKind.DSM,
                binding.observed_sha256,
                binding.observed_size_bytes,
            ),
        ),
    ).sealed()


def _sealed_subject(revision: Any) -> SealedExternalSubjectV1:
    assert revision.manifest is not None
    assert revision.submission.submission_digest is not None
    assert revision.manifest.manifest_digest is not None
    return SealedExternalSubjectV1(
        organization_id=revision.submission.organization_id,
        site_id=revision.submission.site_id,
        work_order_id=revision.work_order_id,
        submission_id=revision.submission.submission_id,
        revision=revision.submission.revision,
        submission_digest=revision.submission.submission_digest,
        manifest_digest=revision.manifest.manifest_digest,
    )


def _policy_with_synthetic_marker(
    policy: ExternalRelativeVolumeExecutionPolicyV1, *, synthetic: bool
) -> ExternalRelativeVolumeExecutionPolicyV1:
    payload = policy.model_dump(by_alias=True, mode="json", exclude={"policy_digest"})
    payload["syntheticTestOnly"] = synthetic
    return ExternalRelativeVolumeExecutionPolicyV1.model_validate(payload).sealed()


def _fixture(
    tmp_path: Path, *, seal_baseline: bool = True
) -> tuple[Any, Any, LeaseFence, Principal, _RecordingStorage, Any]:
    """Create a running volume record and its two real external declarations."""
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )
    baseline_order = work_orders.create_work_order(
        organization_id="org-a", site_id="site-a", name="baseline", work_area_ids=["area-a"],
        schedule_id=None, actor="operator-a", now=_NOW,
    )
    current_order = work_orders.create_work_order(
        organization_id="org-a", site_id="site-a", name="current", work_area_ids=["area-a"],
        schedule_id=None, actor="operator-a", now=_NOW,
    )
    base = replace(
        _authority(valid_until=_NOW + timedelta(hours=1)),
        authorized_actor_ids=frozenset({"operator-a", "volume-worker"}),
        synthetic_test_only=False,
        execution_policy=_policy_with_synthetic_marker(
            _authority().execution_policy, synthetic=False
        ),
    )
    baseline = base.baseline.model_copy(
        update={
            "subject": base.baseline.subject.model_copy(
                update={"work_order_id": baseline_order.work_order_id}
            )
        }
    )
    current = base.current.model_copy(
        update={
            "subject": base.current.subject.model_copy(
                update={"work_order_id": current_order.work_order_id}
            )
        }
    )
    storage = _RecordingStorage()
    reconstruction = ExternalReconstructionStore(DurableJournal(tmp_path / "reconstruction.jsonl"))

    def register(binding: Any, order: Any, *, seal: bool) -> Any:
        submission = _submission(
            binding=binding,
            work_order_id=order.work_order_id,
            epoch_id=observation_epoch_id(order),
        )
        registered = reconstruction.register(
            submission, work_order=order, registered_by="operator-a", now=_NOW
        )
        assert registered.verdict is ExternalReconstructionVerdict.REGISTERED
        assert registered.revision is not None
        for artifact_id, object_key in registered.revision.bindings:
            artifact = next(
                item for item in submission.artifacts if item.artifact_id == artifact_id
            )
            storage.observations[object_key] = ObjectStorageObservation(
                object_key=object_key,
                exists=True,
                size_bytes=artifact.declared_size_bytes,
                sha256="sha256:" + artifact.declared_sha256,
                content_type=artifact.content_type,
            )
        if not seal:
            return registered.revision
        sealed = reconstruction.seal(
            order.work_order_id,
            submission.submission_id,
            submission.revision,
            organization_id="org-a",
            site_id="site-a",
            storage=storage,
            now=_NOW,
        )
        assert sealed.verdict is ExternalReconstructionVerdict.SEALED
        assert sealed.revision is not None
        return sealed.revision

    baseline_revision = register(baseline, baseline_order, seal=seal_baseline)
    current_revision = register(current, current_order, seal=True)
    authority = replace(
        base,
        current_work_order_id=current_order.work_order_id,
        baseline=baseline.model_copy(update={"subject": _sealed_subject(baseline_revision)})
        if baseline_revision.manifest is not None
        else baseline,
        current=current.model_copy(update={"subject": _sealed_subject(current_revision)}),
    )
    volume_store = _store(tmp_path, authority)
    issued = volume_store.issue(
        principal=_principal(),
        current_work_order_id=current_order.work_order_id,
        decision_ref=authority.decision_id,
        idempotency_key="s3-capability",
        now=_NOW,
    )
    assert issued.record is not None
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = volume_store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="volume-worker",
        fence=fence,
        now=_NOW,
    )
    assert leased.record is not None and leased.fence is not None
    return reconstruction, leased.record, leased.fence, _worker(), storage, authority


def test_issuer_returns_exact_ordered_sealed_dsm_capabilities(tmp_path: Path) -> None:
    """Changing DSM role/order, identity, or the five-minute cap must break this."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, authority = _fixture(tmp_path)
    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: _NOW
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is not None
    assert record.issued_by != worker.principal_id
    assert [capability.role for capability in issued] == ["BASELINE_DSM", "CURRENT_DSM"]
    assert [capability.expires_at for capability in issued] == [_NOW + timedelta(minutes=5)] * 2
    assert [ttl for _, ttl in storage.presigned_get_calls] == [timedelta(minutes=5)] * 2
    expected_object_keys = [
        next(
            entry.object_key
            for entry in reconstruction.resolve_sealed_subject(binding.subject).manifest.entries
            if entry.kind is ProcessingArtifactKind.DSM
            and entry.artifact_id == binding.dsm_artifact_id
        )
        for binding in (authority.baseline, authority.current)
    ]
    assert [capability.download_url for capability in issued] == [
        f"https://storage.invalid/get/{object_key}" for object_key in expected_object_keys
    ]


@pytest.mark.parametrize(
    "case",
    (
        "wrong",
        "missing",
        "nonsealed",
        "swapped",
        "cross-tenant",
        "unauthorized-worker",
        "synthetic",
        "nested-synthetic",
        "stale",
    ),
)
def test_invalid_or_foreign_or_stale_volume_input_is_rejected_before_presign(
    tmp_path: Path, case: str
) -> None:
    """Removing an issuer-side precondition must expose a storage presign call."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, authority = _fixture(
        tmp_path, seal_baseline=case != "nonsealed"
    )
    now = _NOW
    if case == "wrong":
        changed = authority.baseline.model_copy(update={"observed_sha256": "sha256:" + "f" * 64})
        record = replace(
            record,
            authority=replace(authority, baseline=changed),
            request=record.request.model_copy(update={"baseline": changed}),
        )
    elif case == "missing":
        changed = authority.baseline.model_copy(
            update={
                "subject": authority.baseline.subject.model_copy(
                    update={"submission_id": "absent"}
                )
            }
        )
        record = replace(
            record,
            authority=replace(authority, baseline=changed),
            request=record.request.model_copy(update={"baseline": changed}),
        )
    elif case == "swapped":
        changed = authority.baseline.model_copy(update={"subject": authority.current.subject})
        record = replace(
            record,
            request=record.request.model_copy(
                update={"baseline": changed}
            ),
            authority=replace(authority, baseline=changed),
        )
    elif case == "cross-tenant":
        worker = _worker(organization_id="org-b")
    elif case == "unauthorized-worker":
        worker = replace(worker, principal_id="other-worker")
    elif case == "synthetic":
        record = replace(record, authority=replace(authority, synthetic_test_only=True))
    elif case == "nested-synthetic":
        nested = _policy_with_synthetic_marker(authority.execution_policy, synthetic=True)
        record = replace(record, authority=replace(authority, execution_policy=nested))
    elif case == "stale":
        now = _NOW + timedelta(minutes=6)

    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: now
    )(record, fence=fence, principal=worker, now=now)

    assert issued is None
    assert storage.presigned_get_calls == []


def test_storage_failure_returns_no_partial_capability(tmp_path: Path) -> None:
    """Returning one URL after either S3 presign failure would leak a partial bearer capability."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, _ = _fixture(tmp_path)
    storage.fail_presign = True

    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: _NOW
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is None
    assert len(storage.presigned_get_calls) == 1


def test_each_presign_ttl_is_clamped_to_the_remaining_absolute_window(tmp_path: Path) -> None:
    """Reusing the first five-minute TTL after clock advance would outlive the lease."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, _ = _fixture(tmp_path)
    near_expiry = _NOW + timedelta(minutes=4, seconds=59)
    clock_values = iter((_NOW, near_expiry, near_expiry))
    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: next(clock_values)
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is not None
    assert [ttl for _, ttl in storage.presigned_get_calls] == [
        timedelta(minutes=5),
        timedelta(seconds=1),
    ]
    assert [capability.expires_at for capability in issued] == [_NOW + timedelta(minutes=5)] * 2


def test_window_closing_after_presign_drops_both_capabilities(tmp_path: Path) -> None:
    """Returning URLs after the final clock check reaches the lease bound is unsafe."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, _ = _fixture(tmp_path)
    expires_at = _NOW + timedelta(minutes=5)
    clock_values = iter((_NOW, _NOW, expires_at))
    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: next(clock_values)
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is None
    assert len(storage.presigned_get_calls) == 2


def test_post_presign_check_uses_the_earliest_projected_capability_expiry(
    tmp_path: Path,
) -> None:
    """Integer-second TTL truncation can close a URL before the absolute upper bound."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, _ = _fixture(tmp_path)
    signed_at = _NOW + timedelta(milliseconds=100)
    completed_after_projected_expiry = _NOW + timedelta(seconds=299, milliseconds=200)
    clock_values = iter((signed_at, signed_at, completed_after_projected_expiry))
    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: next(clock_values)
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is None
    assert [ttl for _, ttl in storage.presigned_get_calls] == [timedelta(seconds=299)] * 2


def test_second_presign_failure_returns_no_partial_capability(tmp_path: Path) -> None:
    """A returned first URL after the second S3 failure would leak partial worker access."""
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    reconstruction, record, fence, worker, storage, _ = _fixture(tmp_path)
    storage.fail_on_presign_call = 2
    issued = ExternalRelativeVolumeS3InputCapabilityIssuer(
        reconstruction=reconstruction, storage=storage, signing_clock=lambda: _NOW
    )(record, fence=fence, principal=worker, now=_NOW)

    assert issued is None
    assert len(storage.presigned_get_calls) == 2

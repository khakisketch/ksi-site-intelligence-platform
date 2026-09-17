"""S3 capabilities for a leased single-volume worker fail closed on any drift."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from ksi_core.auth import Principal, PrincipalKind
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeVerdict,
)
from ksi_core.domains.external.quantity.external_single_volume_s3_capabilities import (
    ExternalSingleVolumeS3InputCapabilityIssuer,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    SingleVolumeWorkerLaunchMaterial,
)
from ksi_core.leasing import LeaseFence
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from test_external_single_volumes import (
    _NOW,
    _authority,
    _AuthorityPort,
    _evidence,
    _principal,
    _store,
    _validation_policy,
)


class _Storage:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        del ttl
        self.calls.append(object_key)
        return f"https://storage.invalid/get/{object_key}"


def _fixture(tmp_path: Path) -> tuple[Any, SingleVolumeWorkerLaunchMaterial, LeaseFence, Any]:
    policy = _validation_policy()
    assert policy.policy_digest is not None
    record, context = _evidence(_authority().target, policy, attested=True)
    assert record.evidence_record_digest is not None
    authority = replace(
        _authority(
            evidence_digest=record.evidence_record_digest,
            validation_policy_digest=policy.policy_digest,
        ),
        synthetic_test_only=False,
        execution_policy=_authority()
        .execution_policy.model_copy(update={"synthetic_test_only": False, "policy_digest": None})
        .sealed(),
    )
    store = _store(tmp_path, _AuthorityPort(authority))
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="s3-single",
        now=_NOW,
    )
    assert issued.record is not None
    leased = store.claim(
        issued.record.request.request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
        now=_NOW,
    )
    assert leased.verdict is ExternalRelativeVolumeVerdict.LEASED
    assert leased.record is not None and leased.fence is not None
    material = SingleVolumeWorkerLaunchMaterial(
        validation_policy=policy, evidence_record=record, evidence_context=context
    )
    target = authority.target
    revision = SimpleNamespace(
        manifest=SimpleNamespace(
            entries=(
                SimpleNamespace(
                    kind=ProcessingArtifactKind.DSM,
                    artifact_id=target.dsm_artifact_id,
                    observed_sha256=target.observed_sha256.removeprefix("sha256:"),
                    observed_size_bytes=target.observed_size_bytes,
                    object_key="reconstruction/target-dsm",
                ),
            )
        )
    )
    manifest = SimpleNamespace(
        evidence_manifest_digest=record.evidence_manifest_digest,
        observed_object_digest=context.evidence_observed_sha256,
        observed_size_bytes=context.evidence_observed_size_bytes,
        target_dsm_observed_sha256=target.observed_sha256,
    )
    collaborators = SimpleNamespace(
        reconstruction=SimpleNamespace(resolve_sealed_subject=lambda subject: revision),
        evidence=SimpleNamespace(
            sealed_evidence_object_for=lambda *_a, **_k: ("evidence/checkpoints.csv", manifest)
        ),
        manifest=manifest,
    )
    return leased.record, material, leased.fence, collaborators


def _issuer(collaborators: Any, storage: _Storage) -> ExternalSingleVolumeS3InputCapabilityIssuer:
    return ExternalSingleVolumeS3InputCapabilityIssuer(
        reconstruction=cast(Any, collaborators.reconstruction),
        evidence_validations=cast(Any, collaborators.evidence),
        storage=cast(Any, storage),
        signing_clock=lambda: _NOW,
    )


def _worker() -> Principal:
    return Principal("worker-principal", PrincipalKind.PROCESSING_WORKER, None, None, "org-a")


def test_issues_target_dsm_then_checkpoint_csv_for_the_exact_lease(tmp_path: Path) -> None:
    record, material, fence, collaborators = _fixture(tmp_path)
    storage = _Storage()
    issued = _issuer(collaborators, storage)(
        record, material, fence=fence, principal=_worker(), now=_NOW
    )
    assert issued is not None
    assert [item.role for item in issued] == ["TARGET_DSM", "CHECKPOINT_CSV"]
    assert storage.calls == ["reconstruction/target-dsm", "evidence/checkpoints.csv"]


@pytest.mark.parametrize(
    "drift",
    [
        "operator_principal",
        "stale_fence",
        "manifest_digest",
        "missing_evidence_object",
    ],
)
def test_any_drift_withholds_every_capability(tmp_path: Path, drift: str) -> None:
    record, material, fence, collaborators = _fixture(tmp_path)
    principal = _worker()
    if drift == "operator_principal":
        principal = _principal()
    elif drift == "stale_fence":
        fence = LeaseFence(fence.worker_instance_id, str(uuid4()), fence.lease_generation)
    elif drift == "manifest_digest":
        collaborators.manifest.observed_object_digest = "sha256:" + "0" * 64
    else:
        collaborators.evidence.sealed_evidence_object_for = lambda *_a, **_k: None
    storage = _Storage()
    assert (
        _issuer(collaborators, storage)(
            record, material, fence=fence, principal=principal, now=_NOW
        )
        is None
    )
    assert storage.calls == []

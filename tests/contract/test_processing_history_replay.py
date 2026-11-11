"""Task 2 retirement proof: execution is gone, history replays read-only.

Covers the brief's replay coupling: manifest-aware SUCCEEDED replay resolves
the replay-only immutable facts (no live registry), unknown/mismatched
bindings and missing artifacts stay fail-closed, and legacy no-profile jobs
replay untouched. Also pins the router end-state: authorized historical GETs
only, no managed POSTs/worker mutations/pending queue/catalogs, and no
auth_registry fallback mount.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.domains.artifacts.artifact_manifest import (
    ArtifactObjectBinding,
    AuthoritativeArtifactManifestV1,
    CandidateArtifact,
)
from ksi_core.domains.processing.historical_processing_profiles import (
    HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
    HISTORICAL_KSI_ODM_CIVIL_V1_ID,
)
from ksi_core.domains.processing.processing_jobs import (
    ProcessingJobRecoveryError,
    ProcessingJobStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.leasing import LeaseMode, lease_raw_fields, next_lease
from ksi_core.sites import SiteStore
from ksi_event_contracts.processing_artifact import (
    ArtifactLineage,
    LineageAuthority,
    ProcessingArtifact,
    ProcessingArtifactKind,
    processing_artifact_wire_dict,
)

_MISSION_ID = "mission-a"
_SITE_ID = "site-a"
_JOB_ID = "mission-a-pj1"
_SOURCE_DIGEST = "sha256:" + "c" * 64
_ACTOR = "worker-1"
_T0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
_T1 = _T0 + timedelta(seconds=60)
_T4 = _T1 + timedelta(seconds=1800)


class _SourceMediaStub:
    """Minimal sealed-bundle authority for replay input-verification reads."""

    def __init__(self, *, digest: str = _SOURCE_DIGEST) -> None:
        self._digest = digest

    def get(self, mission_id: str) -> Any:
        if mission_id != _MISSION_ID:
            return None
        return SimpleNamespace(is_verified=True, source_bundle_digest=self._digest)

    def mission_is_visible(self, mission_id: str) -> bool:
        return mission_id == _MISSION_ID

    def mission_is_visible_for_organization(self, mission_id: str, organization_id: str) -> bool:
        del organization_id
        return mission_id == _MISSION_ID


def _artifact(
    artifact_id: str, kind: ProcessingArtifactKind, digest_word: str
) -> ProcessingArtifact:
    derived = [] if kind is ProcessingArtifactKind.POINT_CLOUD else ["pc"]
    if kind is ProcessingArtifactKind.POINT_CLOUD:
        authority = LineageAuthority.SOURCE
    else:
        authority = LineageAuthority.DERIVED
    return ProcessingArtifact(
        artifact_id=artifact_id,
        job_id=_JOB_ID,
        kind=kind,
        lineage=ArtifactLineage(
            authority=authority,
            derived_from=derived,
            source_digest=_SOURCE_DIGEST,
        ),
        digest="sha256:" + digest_word * 64,
        format="laz" if kind is ProcessingArtifactKind.POINT_CLOUD else "tif",
        crs="EPSG:5186",
        gsd=None if kind is ProcessingArtifactKind.POINT_CLOUD else 0.05,
    )


def _issued_raw(
    *,
    profile_id: str | None = HISTORICAL_KSI_ODM_CIVIL_V1_ID,
    profile_digest: str | None = HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "kind": "processing-job-issued",
        "ts": iso_utc(_T0),
        "jobId": _JOB_ID,
        "sequence": 1,
        "missionId": _MISSION_ID,
        "siteId": _SITE_ID,
        "provider": "odm",
        "engineVersion": "3.5.6",
        "engineDigest": "sha256:" + "e" * 64,
        "executionLocus": "ksi_server_gpu",
        "dataResidency": {"egressAllowed": False, "jurisdiction": "KR"},
        "licenseBasis": {
            "licenseId": "AGPL-3.0",
            "tier": "self_hosted_unmodified_container",
            "attributionRequired": False,
        },
        "input": {
            "imageCount": 2,
            "totalMegapixels": 24.0,
            "sourceBundleDigest": _SOURCE_DIGEST,
        },
        "processingParams": {"dsm": True},
        "issuedBy": "op-1",
    }
    if profile_id is not None:
        raw["processingProfileId"] = profile_id
    if profile_digest is not None:
        raw["processingProfileDigest"] = profile_digest
    return raw


def _versioned_journal(
    tmp_path: Path,
    *,
    profile_id: str | None = HISTORICAL_KSI_ODM_CIVIL_V1_ID,
    profile_digest: str | None = HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
    kinds: tuple[ProcessingArtifactKind, ...] = (
        ProcessingArtifactKind.POINT_CLOUD,
        ProcessingArtifactKind.DSM,
        ProcessingArtifactKind.DTM,
    ),
    accepted_generation: int = 1,
) -> Path:
    """Sealed manifest-aware history: issued → leased → RUNNING → 3 candidates → SUCCEEDED."""
    worker = str(uuid4())
    acquisition = str(uuid4())
    lease = next_lease(
        worker_instance_id=worker,
        lease_acquisition_id=acquisition,
        lease_generation=1,
        authenticated_actor_id=_ACTOR,
        now=_T1,
        ttl=timedelta(hours=1),
    )
    journal_path = tmp_path / "processing-job.jsonl"
    journal = DurableJournal(journal_path)
    try:
        journal.append(_issued_raw(profile_id=profile_id, profile_digest=profile_digest))
        journal.append(
            {
                "kind": "processing-job-leased",
                "ts": iso_utc(_T1),
                "jobId": _JOB_ID,
                "expiresAt": iso_utc(lease.expires_at),
                **lease_raw_fields(lease=lease, mode=LeaseMode.CLAIM),
            }
        )
        journal.append(
            {
                "kind": "processing-job-transitioned",
                "ts": iso_utc(_T1 + timedelta(seconds=60)),
                "jobId": _JOB_ID,
                "before": "QUEUED",
                "after": "RUNNING",
                "detail": None,
                "actor": _ACTOR,
                # The generation-aware lease already marks the record
                # manifest-aware, so the RUNNING commit carries its fence.
                "leaseFence": {
                    "workerInstanceId": worker,
                    "leaseAcquisitionId": acquisition,
                    "leaseGeneration": 1,
                },
            }
        )
        ids = {"point_cloud": "pc", "dsm": "dsm", "dtm": "dtm"}
        candidates: list[CandidateArtifact] = []
        for step, kind in enumerate(kinds):
            artifact_id = ids[kind.value]
            artifact = _artifact(artifact_id, kind, str(step + 1))
            binding = ArtifactObjectBinding(
                object_key=(
                    f"sites/{_SITE_ID}/processing-jobs/{_JOB_ID}/attempts/1/artifacts/{artifact_id}"
                ),
                sha256=artifact.digest,
                size_bytes=100 + step,
                content_type="application/octet-stream",
            )
            candidate = CandidateArtifact(
                artifact=artifact,
                worker_instance_id=worker,
                lease_acquisition_id=acquisition,
                lease_generation=1,
                primary=binding,
                auxiliary_files=(),
            )
            candidates.append(candidate)
            moment = _T1 + timedelta(seconds=300 + step * 10)
            journal.append(
                {
                    "kind": "processing-artifact-upload-granted",
                    "ts": iso_utc(moment),
                    "jobId": _JOB_ID,
                    "artifactId": artifact_id,
                    "filename": None,
                    "leaseGeneration": 1,
                    "leaseFence": {
                        "workerInstanceId": worker,
                        "leaseAcquisitionId": acquisition,
                        "leaseGeneration": 1,
                    },
                    "grantedBy": _ACTOR,
                    "binding": binding.to_wire(),
                }
            )
            journal.append(
                {
                    "kind": "processing-artifact-registered",
                    "ts": iso_utc(moment + timedelta(seconds=5)),
                    "jobId": _JOB_ID,
                    "artifactId": artifact_id,
                    "registeredBy": _ACTOR,
                    "candidate": candidate.to_wire(),
                    "acceptedObjectObservations": [
                        {"filename": None, "binding": binding.to_wire()}
                    ],
                }
            )
        manifest = AuthoritativeArtifactManifestV1.create(
            job_id=_JOB_ID,
            producing_worker_instance_id=worker,
            lease_acquisition_id=acquisition,
            lease_generation=1,
            entries=tuple(candidates),
        )
        journal.append(
            {
                "kind": "processing-job-transitioned",
                "ts": iso_utc(_T4),
                "jobId": _JOB_ID,
                "before": "RUNNING",
                "after": "SUCCEEDED",
                "detail": "done",
                "actor": _ACTOR,
                "leaseFence": {
                    "workerInstanceId": worker,
                    "leaseAcquisitionId": acquisition,
                    "leaseGeneration": 1,
                },
                "acceptedLeaseGeneration": accepted_generation,
                "artifactManifest": manifest.to_wire(),
                "artifactManifestDigest": manifest.manifest_digest,
            }
        )
    finally:
        journal.close()
    return journal_path


def _open_store(journal_path: Path, *, digest: str = _SOURCE_DIGEST) -> ProcessingJobStore:
    return ProcessingJobStore(
        DurableJournal(journal_path),
        source_media_store=_SourceMediaStub(digest=digest),  # type: ignore[arg-type]
        site_store=SiteStore(DurableJournal(journal_path.parent / "sites.jsonl")),
    )


def test_versioned_success_replays_with_recorded_facts(tmp_path: Path) -> None:
    store = _open_store(_versioned_journal(tmp_path))

    record = store.get(_JOB_ID)
    assert record is not None
    assert record.status.value == "SUCCEEDED"
    assert record.processing_profile_id == HISTORICAL_KSI_ODM_CIVIL_V1_ID
    assert record.processing_profile_digest == HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST
    assert record.processing_profile_classification == "VERSIONED"
    assert [job.job_id for job in store.list_for_mission(_MISSION_ID)] == [_JOB_ID]
    assert [job.job_id for job in store.list_for_site(_SITE_ID)] == [_JOB_ID]

    resolved = store.resolve_artifact(_JOB_ID, "dsm")
    assert resolved is not None
    assert resolved.legacy is False
    assert resolved.artifact.kind is ProcessingArtifactKind.DSM
    assert resolved.object_key == (
        f"sites/{_SITE_ID}/processing-jobs/{_JOB_ID}/attempts/1/artifacts/dsm"
    )
    assert {a.kind.value for a in store.accepted_artifacts(_JOB_ID)} == {
        "point_cloud",
        "dsm",
        "dtm",
    }


def test_tampered_profile_digest_is_fail_closed(tmp_path: Path) -> None:
    path = _versioned_journal(tmp_path, profile_digest="sha256:" + "0" * 64)
    with pytest.raises(ProcessingJobRecoveryError):
        _open_store(path)


def test_unknown_profile_id_is_fail_closed(tmp_path: Path) -> None:
    path = _versioned_journal(tmp_path, profile_id="customer-supplied-odm")
    with pytest.raises(ProcessingJobRecoveryError):
        _open_store(path)


def test_missing_required_artifact_is_fail_closed(tmp_path: Path) -> None:
    path = _versioned_journal(
        tmp_path,
        kinds=(ProcessingArtifactKind.POINT_CLOUD, ProcessingArtifactKind.DSM),
    )
    with pytest.raises(ProcessingJobRecoveryError, match="dtm"):
        _open_store(path)


def test_manifest_fence_mismatch_is_fail_closed(tmp_path: Path) -> None:
    path = _versioned_journal(tmp_path, accepted_generation=2)
    with pytest.raises(ProcessingJobRecoveryError):
        _open_store(path)


def test_half_profile_binding_is_fail_closed(tmp_path: Path) -> None:
    path = _versioned_journal(tmp_path, profile_digest=None)
    with pytest.raises(ProcessingJobRecoveryError, match="반쪽"):
        _open_store(path)


def test_legacy_job_without_profile_binding_replays(tmp_path: Path) -> None:
    journal_path = tmp_path / "processing-job.jsonl"
    journal = DurableJournal(journal_path)
    try:
        journal.append(_issued_raw(profile_id=None, profile_digest=None))
        journal.append(
            {
                "kind": "processing-job-transitioned",
                "ts": iso_utc(_T1 + timedelta(seconds=60)),
                "jobId": _JOB_ID,
                "before": "QUEUED",
                "after": "RUNNING",
                "detail": None,
                "actor": _ACTOR,
            }
        )
        artifact = _artifact("pc", ProcessingArtifactKind.POINT_CLOUD, "1")
        journal.append(
            {
                "kind": "processing-artifact-registered",
                "ts": iso_utc(_T1 + timedelta(seconds=300)),
                "jobId": _JOB_ID,
                "artifactId": "pc",
                "artifact": processing_artifact_wire_dict(artifact),
                "registeredBy": _ACTOR,
            }
        )
        journal.append(
            {
                "kind": "processing-job-transitioned",
                "ts": iso_utc(_T4),
                "jobId": _JOB_ID,
                "before": "RUNNING",
                "after": "SUCCEEDED",
                "detail": "done",
                "actor": _ACTOR,
            }
        )
    finally:
        journal.close()

    store = _open_store(journal_path)
    record = store.get(_JOB_ID)
    assert record is not None
    assert record.status.value == "SUCCEEDED"
    assert record.processing_profile_id is None
    assert record.processing_profile_classification == "LEGACY_UNMANAGED"

    resolved = store.resolve_artifact(_JOB_ID, "pc")
    assert resolved is not None
    assert resolved.legacy is True
    assert resolved.object_key == (f"sites/{_SITE_ID}/processing-jobs/{_JOB_ID}/artifacts/pc")


def test_managed_execution_surface_is_gone() -> None:
    for dead in (
        "issue",
        "transition",
        "acquire_lease",
        "artifact_upload_target",
        "register_artifact",
        "input_for",
        "verify_input",
        "list_pending",
        "resolve_processing_profile",
        "processing_profiles",
        "processing_resource_policies",
        "processing_profile_issuance_enabled",
    ):
        assert not hasattr(ProcessingJobStore, dead), dead


def test_removed_modules_stay_unimportable() -> None:
    import importlib

    for name in (
        "ksi_core.processing_profiles",
        "ksi_core.processing_resource_policy",
        "ksi_core.domains.processing.processing_profiles",
        "ksi_core.domains.processing.processing_resource_policy",
    ):
        with pytest.raises(ImportError):
            importlib.import_module(name)


# --- router end-state ---------------------------------------------------------


class _StorageStub:
    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://storage.invalid/get/{object_key}"


def _digest_hex(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _authed_app(journal_path: Path, tmp_path: Path) -> FastAPI:
    from ksi_core.composition.routes.processing import mount_processing_routes

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest_hex("reader"),
                    principal=Principal(
                        principal_id="reader-1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                    ),
                )
            ]
        ),
    )
    store = ProcessingJobStore(
        DurableJournal(journal_path),
        source_media_store=_SourceMediaStub(),  # type: ignore[arg-type]
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
    )
    mount_processing_routes(
        app,
        processing_job_store=store,
        evidence_storage=_StorageStub(),
        site_lifecycle=None,
        checkpoint_validation_store=None,
        checkpoint_validation_registration_enabled=False,
        site_store=None,
        defect_candidate_store=None,
        change_detection_store=None,
        volume_change_store=None,
        comparison_request_store=None,
        design_conformance_request_store=None,
        region_extraction_request_store=None,
        design_conformance_report_store=None,
        report_export_store=None,
        work_area_store=None,
        region_extraction_report_store=None,
        equipment_state_store=None,
        equipment_support_store=None,
        design_surface_store=None,
    )
    return app


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def walk(container: Any) -> None:
        for route in getattr(container, "routes", None) or []:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if methods and path:
                for method in methods:
                    if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                        found.add((method, path))
            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk(inner)

    walk(app)
    return found


_HISTORICAL_GETS = {
    ("GET", "/v1/missions/{mission_id}/processing-jobs"),
    ("GET", "/v1/sites/{site_id}/processing-jobs"),
    ("GET", "/v1/processing-jobs/{job_id}"),
    (
        "GET",
        "/v1/processing-jobs/{job_id}/artifacts/{artifact_id}/download",
    ),
}

_MANAGED_ABSENT = {
    ("POST", "/v1/missions/{mission_id}/processing-jobs"),
    ("GET", "/v1/processing-jobs"),
    ("POST", "/v1/processing-jobs/{job_id}/transitions"),
    ("POST", "/v1/processing-jobs/{job_id}/lease"),
    ("GET", "/v1/processing-jobs/{job_id}/input"),
    ("POST", "/v1/processing-jobs/{job_id}/verify-input"),
    ("POST", "/v1/processing-jobs/{job_id}/artifacts/upload-url"),
    ("POST", "/v1/processing-jobs/{job_id}/artifacts"),
    ("GET", "/v1/processing-profiles"),
    ("GET", "/v1/processing-resource-policies"),
}


def test_router_mounts_only_historical_gets(tmp_path: Path) -> None:
    app = _authed_app(_versioned_journal(tmp_path), tmp_path)
    routes = _routes(app)
    assert routes >= _HISTORICAL_GETS
    assert not (_MANAGED_ABSENT & routes)


def test_managed_paths_are_absent_not_forbidden(tmp_path: Path) -> None:
    app = _authed_app(_versioned_journal(tmp_path), tmp_path)
    headers = {"Authorization": "Bearer reader"}
    with TestClient(app) as client:
        for method, path in sorted(_MANAGED_ABSENT):
            rendered = (
                path.replace("{mission_id}", _MISSION_ID)
                .replace("{job_id}", _JOB_ID)
                .replace("{site_id}", _SITE_ID)
                .replace("{artifact_id}", "dsm")
            )
            response = client.request(method, rendered, headers=headers)
            # 404 (no route) or 405 (same path serves only a kept GET):
            # either proves the managed method is not mounted.
            assert response.status_code in (404, 405), (
                method,
                rendered,
                response.status_code,
            )


def test_historical_gets_serve_sealed_history(tmp_path: Path) -> None:
    app = _authed_app(_versioned_journal(tmp_path), tmp_path)
    headers = {"Authorization": "Bearer reader"}
    with TestClient(app) as client:
        listed = client.get(f"/v1/missions/{_MISSION_ID}/processing-jobs", headers=headers)
        assert listed.status_code == 200, listed.text
        assert [job["jobId"] for job in listed.json()["jobs"]] == [_JOB_ID]

        site_listed = client.get(f"/v1/sites/{_SITE_ID}/processing-jobs", headers=headers)
        assert site_listed.status_code == 200, site_listed.text
        assert [job["jobId"] for job in site_listed.json()["jobs"]] == [_JOB_ID]

        detail = client.get(f"/v1/processing-jobs/{_JOB_ID}", headers=headers)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["status"] == "SUCCEEDED"
        assert body["processingProfileId"] == HISTORICAL_KSI_ODM_CIVIL_V1_ID
        assert body["processingProfileDigest"] == HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST
        assert body["processingProfileClassification"] == "VERSIONED"

        download = client.get(
            f"/v1/processing-jobs/{_JOB_ID}/artifacts/dsm/download", headers=headers
        )
        assert download.status_code == 200, download.text
        assert download.json()["downloadUrl"] == (
            "https://storage.invalid/get/"
            f"sites/{_SITE_ID}/processing-jobs/{_JOB_ID}/attempts/1/artifacts/dsm"
        )

        assert client.get("/v1/processing-jobs/no-such-job", headers=headers).status_code == 404


def test_no_store_means_no_processing_surface() -> None:
    from ksi_core.composition.routes.processing import mount_processing_routes

    app = FastAPI()
    mount_processing_routes(
        app,
        processing_job_store=None,
        evidence_storage=None,
        site_lifecycle=None,
        checkpoint_validation_store=None,
        checkpoint_validation_registration_enabled=False,
        site_store=None,
        defect_candidate_store=None,
        change_detection_store=None,
        volume_change_store=None,
        comparison_request_store=None,
        design_conformance_request_store=None,
        region_extraction_request_store=None,
        design_conformance_report_store=None,
        report_export_store=None,
        work_area_store=None,
        region_extraction_report_store=None,
        equipment_state_store=None,
        equipment_support_store=None,
        design_surface_store=None,
    )
    assert {path for _, path in _routes(app) if "processing" in path} == set()

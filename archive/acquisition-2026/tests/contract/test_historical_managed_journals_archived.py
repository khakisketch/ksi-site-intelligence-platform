"""Archived managed-journal replay proof (P3 Task 5 relocation record, RB-08).

Relocated verbatim from
``tests/contract/test_historical_managed_readers.py::test_retained_managed_journals_replay_byte_identical``
(+ its exclusive ``_sha`` helper) at base 2900214: the proof writes and
reopens the mission journal through the REAL ``MissionStore`` constructor,
which retired to ``archive/acquisition-2026/.../domains/missions/`` with the
managed set. The active tree keeps the platform-reader pins in
``tests/contract/test_historical_managed_readers.py``; this file is
archive-internal (``archive/`` is not a pytest testpath, import path, or
workspace member) and is NOT executed — it records what was proven, not a
live gate. Inverse: ``git mv archive/acquisition-2026/tests/contract/
test_historical_managed_journals_archived.py
tests/contract/test_historical_managed_journals_archived.py`` (plus restoring
the managed modules it imports).

Required imports (active ``ksi_core`` readers + archived ``MissionStore``):

    from ksi_core.durable_journal import DurableJournal
    from ksi_core.mission_records import MissionRecord, MissionStore  # ARCHIVED
    from ksi_core.processing_jobs import (ArtifactSpec, JobSpec, ...)
    from ksi_core.sites import SiteStore
    from ksi_core.source_media import (...)
"""

import hashlib
from datetime import UTC, datetime

import pytest

from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore  # noqa: F401 -- archived
from ksi_core.processing_jobs import (
    ArtifactSpec,
    JobSpec,
    ProcessingJobStatus,
    ProcessingJobStore,
    ProcessingJobVerdict,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import (
    SourceBundleVerifyVerdict,
    SourceMediaClaim,
    SourceMediaMeasurement,
    SourceMediaStore,
)
from ksi_event_contracts.processing_artifact import (
    LineageAuthority,
    ProcessingArtifactKind,
)
from ksi_event_contracts.processing_job import (
    ExecutionLocus,
    LicenseBasis,
    ProcessingProvider,
)
from ksi_event_contracts.site_frame import SiteFrame

_NOW = datetime(2026, 10, 8, tzinfo=UTC)
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def test_retained_managed_journals_replay_byte_identical(tmp_path: Path) -> None:
    """Old managed journals stay interpretable through the REAL constructors.

    Mission → sealed/verified source bundle → site → managed job
    (lease/RUNNING/artifact) is written, closed, then reopened over the same
    files: projections and journal bytes must be identical, and the artifact
    byte binding (the durable grant record) must survive the reopen.
    """
    mission_id = "mission-historical-1"
    site_id = "site-historical-1"
    journal_names = ("missions.jsonl", "source-media.jsonl", "sites.jsonl", "processing-jobs.jsonl")

    mission_journal = DurableJournal(tmp_path / "missions.jsonl")
    missions = MissionStore(mission_journal)
    assert (
        missions.record_issuance(
            MissionRecord(
                mission_id=mission_id,
                site_id=site_id,
                mission_type="BASELINE_MAPPING",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": mission_id},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="do-1",
                organization_id="legacy",
            )
        ).value
        == "RECORDED"
    )
    bundle_journal = DurableJournal(tmp_path / "source-media.jsonl")
    bundles = SourceMediaStore(bundle_journal, mission_store=missions)
    claims = [
        SourceMediaClaim(
            media_id=f"img-{i:03d}.jpg",
            sha256=_sha(f"img-{i:03d}.jpg"),
            size_bytes=1_000_000,
            width=4000,
            height=3000,
            content_type="image/jpeg",
        )
        for i in range(2)
    ]
    assert (
        bundles.register_batch(mission_id, claims, registered_by="op-1", now=_NOW).verdict.value
        == "PROCESSED"
    )
    assert bundles.seal(mission_id, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    bundle = bundles.get(mission_id)
    assert bundle is not None
    assert (
        bundles.verify(
            mission_id,
            [
                SourceMediaMeasurement(
                    media_id=m.media_id,
                    sha256=m.sha256,
                    size_bytes=m.size_bytes,
                    width=m.width,
                    height=m.height,
                )
                for m in bundle.media
            ],
            verified_by="worker-1",
            now=_NOW,
        ).verdict
        is SourceBundleVerifyVerdict.VERIFIED
    )
    site_journal = DurableJournal(tmp_path / "sites.jsonl")
    sites = SiteStore(site_journal)
    assert (
        sites.register(site_id, site_id, _FRAME, actor="op-1", now=_NOW).verdict.value
        == "REGISTERED"
    )
    job_journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    jobs = ProcessingJobStore(
        job_journal,
        source_media_store=bundles,
        site_store=sites,
    )
    issued = jobs.issue(
        mission_id,
        JobSpec(
            provider=ProcessingProvider.ODM,
            engine_version="3.5.4",
            engine_digest="sha256:" + "a" * 64,
            execution_locus=ExecutionLocus.KSI_SERVER_GPU,
            license_basis=LicenseBasis(
                license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
            ),
            processing_params={"quality": "high"},
        ),
        issued_by="op-1",
        now=_NOW,
    )
    assert issued.record is not None
    job_id = issued.record.job_id
    assert jobs.acquire_lease(job_id, worker_id="w-1", now=_NOW).verdict in {
        ProcessingJobVerdict.LEASED,
        ProcessingJobVerdict.LEASE_RENEWED,
    }
    assert (
        jobs.transition(
            job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    artifact_digest = "sha256:" + _sha("pointcloud")
    registered = jobs.register_artifact(
        job_id,
        ArtifactSpec(
            artifact_id="pointcloud",
            kind=ProcessingArtifactKind.POINT_CLOUD,
            authority=LineageAuthority.SOURCE,
            derived_from=(),
            digest=artifact_digest,
            format="laz",
            crs="EPSG:5186",
            gsd=None,
            accuracy=None,
            vertical_reference=None,
        ),
        registered_by="w-1",
        now=_NOW,
    )
    assert registered.artifact is not None

    before_bytes = {name: (tmp_path / name).read_bytes() for name in journal_names}
    before_job = jobs.get(job_id)
    assert before_job is not None
    before_site_jobs = jobs.list_for_site(site_id)
    assert [j.job_id for j in before_site_jobs] == [job_id]
    assert jobs.artifact_of(job_id, "pointcloud") is not None

    for handle in (mission_journal, bundle_journal, site_journal, job_journal):
        handle.close()

    # Reopen over the same files with fresh constructors.

    reborn_mission_journal = DurableJournal(tmp_path / "missions.jsonl")
    reborn_missions = MissionStore(reborn_mission_journal)
    reborn_bundle_journal = DurableJournal(tmp_path / "source-media.jsonl")
    reborn_bundles = SourceMediaStore(reborn_bundle_journal, mission_store=reborn_missions)
    reborn_site_journal = DurableJournal(tmp_path / "sites.jsonl")
    reborn_sites = SiteStore(reborn_site_journal)
    reborn_job_journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    reborn_jobs = ProcessingJobStore(
        reborn_job_journal,
        source_media_store=reborn_bundles,
        site_store=reborn_sites,
    )
    try:
        after_job = reborn_jobs.get(job_id)
        assert after_job is not None
        assert after_job.status is ProcessingJobStatus.RUNNING
        assert after_job.spec.engine_version == before_job.spec.engine_version
        assert [j.job_id for j in reborn_jobs.list_for_site(site_id)] == [job_id]
        assert [j.job_id for j in reborn_jobs.list_for_mission(mission_id)] == [job_id]
        artifact_pair = reborn_jobs.artifact_of(job_id, "pointcloud")
        assert artifact_pair is not None
        assert artifact_pair[1].digest == artifact_digest
        reborn_bundle = reborn_bundles.get(mission_id)
        assert reborn_bundle is not None
        assert reborn_bundle.is_sealed
        assert reborn_bundle.source_bundle_digest == bundle.source_bundle_digest
        for name in journal_names:
            assert (tmp_path / name).read_bytes() == before_bytes[name]
    finally:
        for handle in (
            reborn_mission_journal,
            reborn_bundle_journal,
            reborn_site_journal,
            reborn_job_journal,
        ):
            handle.close()



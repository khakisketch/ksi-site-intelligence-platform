"""Current managed producer bytes meet real fenced Core registration and replay.

Generated ZIP bytes and storage observations are test fixtures; no NodeODM host,
remote storage, customer reconstruction or quantitative acceptance is claimed.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import replace
from pathlib import Path

import test_odm_adapter as odm_fixtures
import test_processing_jobs as processing_fixtures
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_processing_controller.core_client import ArtifactSubmission, HttpCoreClient
from ksi_processing_controller.odm import plan_artifacts
from ksi_processing_controller.worker import _archive_object_binding


def test_generated_mesh_registers_in_real_core_and_replays_exact_bindings(tmp_path: Path) -> None:
    storage = processing_fixtures._FakeStorage()
    app_client = processing_fixtures._client(tmp_path, storage=storage)
    issued = app_client.post(
        f"/v1/missions/{processing_fixtures._MISSION_ID}/processing-jobs",
        json=processing_fixtures._issue_payload(),
    )
    assert issued.status_code == 201, issued.text
    job_id = issued.json()["job"]["jobId"]
    core = HttpCoreClient(
        "http://testserver", token=processing_fixtures._WORKER_TOKEN, client=app_client
    )
    lease = core.acquire_lease(job_id)
    core.transition(job_id, "RUNNING")
    archive = odm_fixtures._mesh_archive(
        tmp_path, "generated-core-mesh", obj=b"obj", mtl=b"mtl", texture=b"tex"
    )
    reports = plan_artifacts(archive, crs="EPSG:5186")
    for report in reports:
        entries = [(None, report.archive_entry)] + [
            (name, posixpath.join(posixpath.dirname(report.archive_entry), name))
            for name in report.auxiliary_files
        ]
        bindings = []
        for filename, entry in entries:
            measured = _archive_object_binding(archive, entry, object_key="pending")
            target = core.presign_artifact_upload(
                job_id, artifact_id=report.artifact_id, filename=filename,
                sha256=measured.sha256, size_bytes=measured.size_bytes,
                content_type=measured.content_type,
            )
            binding = replace(measured, object_key=target.object_key)
            storage.record_observation(
                object_key=binding.object_key, sha256=binding.sha256,
                size_bytes=binding.size_bytes, content_type=binding.content_type,
            )
            bindings.append(binding)
        core.register_artifact(
            job_id,
            ArtifactSubmission(
                artifact_id=report.artifact_id, kind=report.kind, authority=report.authority,
                derived_from=report.derived_from, digest=report.digest, format=report.fmt,
                crs=report.crs, gsd=report.gsd, auxiliary_files=report.auxiliary_files,
                primary_object=bindings[0], auxiliary_objects=tuple(bindings[1:]),
            ),
        )

    # Replay the genuine journals read-only rather than manufacturing accepted records.
    missions = MissionStore(DurableJournal.open_read_only(tmp_path / "http-missions.jsonl"))
    sources = SourceMediaStore(
        DurableJournal.open_read_only(tmp_path / "http-source-media.jsonl"), mission_store=missions
    )
    sites = SiteStore(DurableJournal.open_read_only(tmp_path / "http-sites.jsonl"))
    replayed = ProcessingJobStore(
        DurableJournal.open_read_only(tmp_path / "http-processing-jobs.jsonl"),
        source_media_store=sources, site_store=sites,
    )
    job = replayed.get(job_id)
    assert job is not None
    assert len(job.artifact_candidates) == len(reports)
    mesh = next(c for c in job.artifact_candidates if c.artifact.artifact_id == "mesh")
    assert mesh.artifact.digest == mesh.primary.sha256 == (
        "sha256:" + hashlib.sha256(b"obj").hexdigest()
    )
    assert mesh.primary.size_bytes == 3
    assert mesh.lease_generation == 1
    assert mesh.worker_instance_id == lease.worker_instance_id
    assert mesh.artifact.lineage.authority.value == "derived"
    assert mesh.artifact.lineage.derived_from == ["point-cloud"]
    assert dict(mesh.auxiliary_files)["odm_textured_model_geo.mtl"].sha256 == (
        "sha256:" + hashlib.sha256(b"mtl").hexdigest()
    )
    assert dict(mesh.auxiliary_files)["odm_textured_model_geo_material0000_map_Kd.png"].sha256 == (
        "sha256:" + hashlib.sha256(b"tex").hexdigest()
    )

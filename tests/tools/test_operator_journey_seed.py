"""Focused seed checks for the isolated synthetic operator journey.

Server-free: pins IDs, names, filename grammar, canonical-digest stability,
raster determinism, admission planning (skip/admit/mismatch) and guard rails
of scripts/rehearse_operator_journey.py. The live 8096 runtime verification
lives in the unit handback receipts, not here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from ksi_core.domains.external.ingress.external_validation_policy import (
        ExternalValidationPolicyV1,
        PolicyAuthorityRecord,
    )
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

_TOOL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rehearse_operator_journey.py"


def _load_seed() -> ModuleType:
    """Load the rehearsal script without adding ``scripts/`` to the import path.

    Mirrors the ``importlib`` pattern of the neighbouring HIL tool tests so the
    static checker resolves a real module object instead of an unresolvable
    flat import; the executed bytes and module name are unchanged.
    """
    spec = importlib.util.spec_from_file_location("rehearse_operator_journey", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_seed()


class NoAdministration:
    def post(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("a reuse/refusal must never reload or administer")


def _finish_fixture(
    tmp_path: Path,
) -> tuple[
    SimpleNamespace,
    tuple[SealedExternalSubjectV1, SealedExternalSubjectV1],
    dict[str, Any],
    datetime,
]:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-2", "syn-demo-t1-submission", "cd"),
    )
    policy, record, _, now = _sealed_test_policy(subjects)
    provider, data = tmp_path / "provider", tmp_path / "owner-data"
    provider.mkdir()
    data.mkdir()
    (provider / "authority-snapshot.json").write_text(
        json.dumps(
            {
                "policyAuthorities": {
                    "records": [record.event_payload()],
                    "currentDigests": [record.digest],
                }
            }
        )
    )
    (provider / "policy-v5-syn-practical.json").write_text(policy.model_dump_json(by_alias=True))
    (data / "external-validation-policy.jsonl").write_text(
        json.dumps(_admit_row(policy, record)) + "\n"
    )
    args = SimpleNamespace(provider_dir=provider, core_data_dir=data)
    template = policy.model_dump(by_alias=True, mode="json")
    return args, subjects, template, now


def test_finish_reuse_preserves_every_artifact_without_administration(
    tmp_path: Path,
) -> None:
    args, subjects, template, now = _finish_fixture(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*.json*")}
    assert (
        seed.finish_admit(
            args, NoAdministration(), {}, subjects, template, now + timedelta(minutes=1)
        )
        == 0
    )
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*.json*")}


def test_finish_refuses_tampered_standalone_policy_mirror_without_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, subjects, template, now = _finish_fixture(tmp_path)
    policy_path = args.provider_dir / "policy-v5-syn-practical.json"
    policy_path.write_text('{"mismatched":true}')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*.json*")}
    assert seed.finish_admit(args, NoAdministration(), {}, subjects, template, now) == 2
    assert "standalone policy mirror" in capsys.readouterr().err
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*.json*")}


def test_fresh_finish_uses_provided_journal_and_never_requires_historical_v2(
    tmp_path: Path,
) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    args, subjects, template, now = _finish_fixture(tmp_path)
    (args.core_data_dir / "external-validation-policy.jsonl").write_text("")
    (args.core_data_dir / "external-authority-provider-receipts.jsonl").write_text(
        json.dumps({"sequence": 13, "snapshotDigest": "sha256:" + "d" * 64}) + "\n"
    )
    (args.provider_dir / "policy-v5-syn-practical.json").unlink()
    (args.provider_dir / "authority-snapshot.json").write_text(
        json.dumps({"policyAuthorities": {"records": [], "currentDigests": []}})
    )
    key = Ed25519PrivateKey.generate()
    (args.provider_dir / "authority-signer.private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    calls: list[str] = []

    class FreshAdministration:
        def post(self, path: str, **kwargs: Any) -> SimpleNamespace:
            calls.append(path)
            return SimpleNamespace(status_code=200, text="accepted fake administration")

    assert seed.finish_admit(args, FreshAdministration(), {}, subjects, template, now) == 0
    assert calls == ["/v1/operations/external-authority/reload"]
    assert (args.provider_dir / "policy-v5-syn-practical.json").stat().st_mode & 0o777 == 0o600
    assert not (args.provider_dir / "policy-v2-syn-practical.json").exists()
    snapshot = json.loads((args.provider_dir / "authority-snapshot.json").read_text())
    assert snapshot["sequence"] == 14
    assert snapshot["previousSnapshotDigest"] == "sha256:" + "d" * 64


def test_analysis_rehearsal_reads_v2_detail_result_not_nonexistent_result_route() -> None:
    paths: list[str] = []

    class AnalysisClient:
        def post(self, path: str, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                status_code=202,
                text="queued",
                json=lambda: {"analysisId": kwargs["headers"]["Idempotency-Key"]},
            )

        def get(self, path: str, **kwargs: Any) -> SimpleNamespace:
            paths.append(path)
            return SimpleNamespace(
                json=lambda: {
                    "executionState": "COMPLETED",
                    "result": {"metrics": {"cutM3": 128, "fillM3": 0, "netM3": -128}},
                }
            )

    out = {
        "site": seed.SITE_ID,
        "areas": {"north": "north"},
        "epochs": {label: {"workOrderId": label, "submissionRef": label} for label in ("t0", "t1")},
    }
    assert seed.post_analyses(AnalysisClient(), {}, out, skip_review=True) == 0
    assert len(paths) == 2 and all(not path.endswith("/result") for path in paths)


def test_synthetic_identity_markers() -> None:
    assert seed.SITE_ID == "syn-demo-site-01"
    assert "F03" not in seed.SITE_ID and "f03" not in seed.SITE_ID
    assert seed.SITE_NAME == "시연 · 토공 현장"
    assert seed.AREA_NORTH_NAME == "북측 절토구역"
    assert seed.AREA_SOUTH_NAME == "남측 성토구역"
    assert seed.CRS == "EPSG:5186"
    assert seed.ORG == "org-a"


def test_canonical_digest_is_stable_and_shaped() -> None:
    now = "2026-10-05T00:00:00Z"
    cand = {
        "contractVersion": "external-reconstruction-submission.v1",
        "submissionId": "syn-demo-t0-submission",
        "revision": 1,
        "organizationId": "org-a",
        "siteId": seed.SITE_ID,
        "observationEpochId": "epoch-x",
        "submittedAt": now,
        "submittedBy": "syn-operator",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "SYNTHETIC practical-journey raster writer",
            "softwareVersion": "0.0.1",
        },
        "inputDeclaration": {"captureStartedAt": now, "captureEndedAt": now},
        "artifacts": [
            {"artifactId": "ortho", "kind": "ortho"},
            {"artifactId": "dsm", "kind": "dsm"},
        ],
    }
    first, second = seed.canonical_digest(cand), seed.canonical_digest(cand)
    assert first == second
    assert first.startswith("sha256:") and len(first) == 7 + 64
    assert "SYNTHETIC" in cand["producerDeclaration"]["softwareName"]


def test_artifact_filenames_match_wire_grammar() -> None:
    import re

    pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    for label in ("t0", "t1"):
        for kind in ("dsm", "ortho"):
            row = seed.artifact_row(kind, b"0123456789abcdef", f"syn-north-{label}-{kind}.tif")
            assert pattern.fullmatch(row["fileName"]), row["fileName"]
            assert row["declaredCrs"] == "EPSG:5186"
            assert row["declaredSha256"] == hashlib.sha256(b"0123456789abcdef").hexdigest()


def test_geotiffs_are_deterministic_and_sized() -> None:
    dsm0, ortho0, dsm1, ortho1 = seed.geotiffs()
    again = seed.geotiffs()
    assert (dsm0, ortho0, dsm1, ortho1) == again
    assert dsm0 != dsm1  # designed cut between epochs
    assert len(dsm0) > 1024  # meaningful size, not a 4-pixel toy
    assert ortho0 != ortho1


def test_south_pair_readme_contract() -> None:
    # A clean checkout has no private live rehearsal directory. Exercise the
    # generator itself; live receipt/raster checks are separate runtime evidence.
    doc = seed.south_pair_readme("wa-syn-demo-site-01-0003")
    assert doc["crs"] == "EPSG:5186"
    assert "SYNTHETIC" in doc["captureSoftware"]
    assert len(doc["captureWindows"]) == 2
    assert "not registered" in doc["purpose"]
    assert "INSPECTION_PENDING_POLICY" in doc["note"]


def test_core_url_accepts_only_isolated_8096() -> None:
    assert seed.validate_core_url("http://127.0.0.1:8096") == "http://127.0.0.1:8096"
    assert seed.validate_core_url("http://localhost:8096") == "http://localhost:8096"


def test_core_url_rejects_protected_rigs() -> None:
    for bad in (
        "http://127.0.0.1:8092",  # F03 live Core
        "http://127.0.0.1:8061",
        "http://127.0.0.1:8062",
        "http://127.0.0.1:9100",
    ):
        with pytest.raises(ValueError):
            seed.validate_core_url(bad)


def test_core_url_rejects_remote_and_unsafe_shapes() -> None:
    for bad in (
        "https://127.0.0.1:8096",
        "http://192.168.1.10:8096",
        "http://example.com:8096",
        "http://user:pass@127.0.0.1:8096",
        "http://127.0.0.1:8096/v1/sites",
        "http://127.0.0.1:8096?x=1",
        "http://127.0.0.1",
        "not-a-url",
        "",
    ):
        with pytest.raises(ValueError):
            seed.validate_core_url(bad)


def _area(
    wid: str, name: str, status: str = "ACTIVE", polygon: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "workAreaId": wid,
        "name": name,
        "status": status,
        "polygon": polygon or {"type": "Polygon", "coordinates": []},
    }


def test_decide_area_receipt_hit_reuses_without_touching_same_named() -> None:
    action, wid = seed.decide_area(
        [
            _area("wa-1", "북측 절토구역"),
            _area("wa-2", "북측 절토구역", polygon={"type": "Polygon", "coordinates": [[[9, 9]]]}),
        ],
        receipt_id="wa-1",
        name="북측 절토구역",
    )
    assert (action, wid) == ("reuse", "wa-1")


def test_decide_area_receipt_archived_or_unknown_fails_clearly() -> None:
    with pytest.raises(seed.AreaAmbiguityError):
        seed.decide_area(
            [_area("wa-1", "북측 절토구역", status="ARCHIVED")],
            receipt_id="wa-1",
            name="북측 절토구역",
        )
    with pytest.raises(seed.AreaAmbiguityError):
        seed.decide_area(
            [_area("wa-1", "북측 절토구역")], receipt_id="wa-missing", name="북측 절토구역"
        )


def test_decide_area_single_match_reuses_zero_creates() -> None:
    assert seed.decide_area(
        [_area("wa-9", "남측 성토구역")], receipt_id=None, name="남측 성토구역"
    ) == ("reuse", "wa-9")
    assert seed.decide_area([], receipt_id=None, name="남측 성토구역") == ("create", None)


def test_decide_area_ambiguous_same_name_different_geometry_raises() -> None:
    existing = [
        _area("wa-a", "북측 절토구역", polygon={"type": "Polygon", "coordinates": [[[0, 0]]]}),
        _area("wa-b", "북측 절토구역", polygon={"type": "Polygon", "coordinates": [[[5, 5]]]}),
    ]
    with pytest.raises(seed.AreaAmbiguityError) as exc:
        seed.decide_area(existing, receipt_id=None, name="북측 절토구역")
    assert "wa-a" in str(exc.value) and "wa-b" in str(exc.value)


def test_decide_area_archived_twin_does_not_block_active_reuse() -> None:
    action, wid = seed.decide_area(
        [_area("wa-old", "북측 절토구역", status="ARCHIVED"), _area("wa-new", "북측 절토구역")],
        receipt_id=None,
        name="북측 절토구역",
    )
    assert (action, wid) == ("reuse", "wa-new")


NORTH_GOLDEN_DIGESTS = {
    "syn-north-t0-dsm.tif": "c301c46169861d543a9aa6a6bb32f933c1da05abe230709f72f816f0fd5271c9",
    "syn-north-t0-ortho.tif": "28a511840d88189d6769563c126e22842740778f20727d7056f5a50631cd0019",
    "syn-north-t1-dsm.tif": "eb6bf789efdd53b3b3913ce1e330dd95650fc411234913ee7ea0b484b7377108",
    "syn-north-t1-ortho.tif": "d1e58b20b51c5efde90be6f9923f38caca6de785dfa89dd4800b2612152cae51",
}
NORTH_BBOX = (seed.X0, seed.Y0 - seed.N * seed.PIX, seed.X0 + seed.N * seed.PIX, seed.Y0)
SOUTH_BBOX = (
    seed.X0,
    seed.Y0 - 2 * seed.N * seed.PIX,
    seed.X0 + seed.N * seed.PIX,
    seed.Y0 - seed.N * seed.PIX,
)


def _raster_bounds(data: bytes) -> tuple[float, float, float, float]:
    from rasterio.io import MemoryFile

    with MemoryFile(data) as mem, mem.open() as ds:
        left, bottom, right, top = ds.bounds
        return (left, bottom, right, top)


def test_north_admitted_bytes_unchanged() -> None:
    import hashlib

    for (name, digest), data in zip(NORTH_GOLDEN_DIGESTS.items(), seed.geotiffs(), strict=True):
        assert hashlib.sha256(data).hexdigest() == digest, name
        assert _raster_bounds(data) == NORTH_BBOX


def test_south_files_cover_actual_south_polygon_not_north() -> None:
    south = seed.south_footprint_bbox()
    assert south == SOUTH_BBOX
    assert south != NORTH_BBOX
    generated = seed.geotiffs(y_origin=seed.Y0 - seed.N * seed.PIX)
    for data in generated:
        assert _raster_bounds(data) == SOUTH_BBOX
    # Same synthetic pattern translated south: same pixel count, new footprint.
    import hashlib

    north_dsm = hashlib.sha256(seed.geotiffs()[0]).hexdigest()
    south_dsm = hashlib.sha256(generated[0]).hexdigest()
    assert north_dsm != south_dsm


def test_south_readme_matches_translated_footprint() -> None:
    doc = json.loads(json.dumps(seed.south_pair_readme("wa-syn-demo-site-01-0003")))
    assert doc == seed.south_pair_readme("wa-syn-demo-site-01-0003")
    fp = doc["footprint"]
    assert (fp["minx"], fp["miny"], fp["maxx"], fp["maxy"]) == SOUTH_BBOX
    assert set(doc["files"]) == {
        "syn-south-t0-dsm.tif",
        "syn-south-t0-ortho.tif",
        "syn-south-t1-dsm.tif",
        "syn-south-t1-ortho.tif",
    }


def _test_subject(work_order_id: str, submission_id: str, tag: str) -> SealedExternalSubjectV1:
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="syn-demo-site-01",
        work_order_id=work_order_id,
        submission_id=submission_id,
        revision=1,
        submission_digest="sha256:" + tag[0] * 64,
        manifest_digest="sha256:" + tag[1] * 64,
    )


def _sealed_test_policy(
    subjects: tuple[SealedExternalSubjectV1, SealedExternalSubjectV1],
    *,
    body_overrides: dict[str, Any] | None = None,
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord, str, datetime]:
    from analysis_api_local_fixture import _envelope
    from ksi_core.domains.external.ingress.external_validation_policy import (
        PolicyAuthorityRecord,
        authorized_policy_body_digest,
    )
    from ksi_event_contracts.external_artifact_validation import (
        ExternalValidationPolicyV1,
        PolicyStatus,
    )
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )
    from test_external_inspector_container_entrypoint import _manifest

    envelope = _envelope()
    manifest = _manifest(envelope)
    body: dict[str, Any] = {
        "policy_id": "syn-practical-geotiff-v1",
        "version": 5,
        "status": PolicyStatus.ACTIVE,
        "parser_build_digest": manifest.parser_build_digest,
        "grammar_digest": external_geotiff_profile_digest_v1(),
        "resource_envelope": envelope.model_dump(by_alias=True, mode="json"),
        "resource_envelope_digest": envelope.resource_envelope_digest,
        "authority_record_digest": "sha256:" + "0" * 64,
        "inspection_rule_ids": ("EXTERNAL_GEOTIFF_MEASURED_V1",),
        "evidence_rule_ids": ("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        "compatibilityMappingDigests": (),
        "synthetic_test_only": False,
    }
    body.update(body_overrides or {})
    draft = ExternalValidationPolicyV1(**body)
    sealed_draft = draft.model_copy(update={"policy_digest": None}, deep=True).sealed()
    correct = authorized_policy_body_digest(sealed_draft)
    now = datetime.now(UTC).replace(microsecond=0)
    record = PolicyAuthorityRecord(
        policy_id="syn-practical-geotiff-v1",
        policy_version=5,
        authorized_policy_body_digest=correct,
        permitted_subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(days=7),
        synthetic_test_only=False,
    ).sealed()
    policy = draft.model_copy(
        update={"authority_record_digest": record.digest, "policy_digest": None}, deep=True
    ).sealed()
    return policy, record, correct, now


def _record_variant(
    correct: str,
    subjects: tuple[SealedExternalSubjectV1, ...],
    *,
    hours_back: int,
    days_valid: int,
) -> PolicyAuthorityRecord:
    from ksi_core.domains.external.ingress.external_validation_policy import (
        PolicyAuthorityRecord,
    )

    now = datetime.now(UTC).replace(microsecond=0)
    return PolicyAuthorityRecord(
        policy_id="syn-practical-geotiff-v1",
        policy_version=5,
        authorized_policy_body_digest=correct,
        permitted_subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=hours_back),
        active_until=now + timedelta(days=days_valid),
        synthetic_test_only=False,
    ).sealed()


def _admit_row(policy: ExternalValidationPolicyV1, record: PolicyAuthorityRecord) -> dict[str, Any]:
    return {
        "kind": "external-validation-policy-admitted",
        "policyId": policy.policy_id,
        "policyVersion": policy.version,
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "authority": record.event_payload(),
    }


def _planner_inputs(
    policy: ExternalValidationPolicyV1,
    record: PolicyAuthorityRecord,
    correct: str,
    subjects: tuple[SealedExternalSubjectV1, ...],
    *,
    file_records: list[dict[str, Any]] | None = None,
    file_current: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "policy_id": "syn-practical-geotiff-v1",
        "version": 5,
        "body_digest": correct,
        "subjects": tuple(subjects),
        "permitted_uses": ("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        "authorized_actor_ids": ("policy-admin",),
        "synthetic_test_only": False,
        "file_records": file_records if file_records is not None else [record.event_payload()],
        "file_current": file_current if file_current is not None else [record.digest],
    }


def test_plan_skip_reuse_writes_nothing() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    journal = [_admit_row(policy, record)]
    mirror = {"records": [record.event_payload()], "currentDigests": [record.digest]}
    before_bytes = json.dumps(mirror, sort_keys=True).encode()
    decision, detail = seed.plan_policy_admission(
        journal_rows=journal, now=now, **_planner_inputs(policy, record, correct, subjects)
    )
    assert decision == "skip", detail
    assert json.dumps(mirror, sort_keys=True).encode() == before_bytes


def test_plan_skip_proves_no_file_touch_via_mtime(tmp_path: Path) -> None:
    import os
    import time

    marker = tmp_path / "provider-snapshot.json"
    marker.write_bytes(b'{"records": []}')
    before_stat = marker.stat()
    time.sleep(0.02)
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    journal = [_admit_row(policy, record)]
    decision, _ = seed.plan_policy_admission(
        journal_rows=journal, now=now, **_planner_inputs(policy, record, correct, subjects)
    )
    assert decision == "skip"
    after_stat = marker.stat()
    assert (after_stat.st_mtime_ns, after_stat.st_size) == (
        before_stat.st_mtime_ns,
        before_stat.st_size,
    )
    assert marker.read_bytes() == b'{"records": []}'
    _ = os  # planner performs no filesystem calls at all


def test_plan_mismatch_mirror_refuses_reload() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    other = _record_variant(correct, subjects, hours_back=2, days_valid=6)
    assert other.digest != record.digest
    assert other.digest is not None
    journal = [_admit_row(policy, record)]
    decision, detail = seed.plan_policy_admission(
        journal_rows=journal,
        now=now,
        **_planner_inputs(
            policy,
            record,
            correct,
            subjects,
            file_records=[other.event_payload()],
            file_current=[other.digest],
        ),
    )
    assert decision == "mismatch", detail
    assert "configuration mismatch" in detail
    assert "no reload attempted" in detail


def test_plan_mismatch_body_divergence_no_silent_admit() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    journal = [_admit_row(policy, record)]
    wrong_body = "sha256:" + "f" * 64
    assert wrong_body != correct
    inputs = _planner_inputs(policy, record, correct, subjects)
    inputs["body_digest"] = wrong_body
    decision, detail = seed.plan_policy_admission(journal_rows=journal, now=now, **inputs)
    assert decision == "mismatch", detail
    assert "VERSION" in detail


def test_plan_admit_empty_journal() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    decision, detail = seed.plan_policy_admission(
        journal_rows=[], now=now, **_planner_inputs(policy, record, correct, subjects)
    )
    assert decision == "admit", detail


def test_plan_revoked_latest_refuses_resurrection() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    journal = [
        _admit_row(policy, record),
        {
            "kind": "external-validation-policy-revoked",
            "policyId": "syn-practical-geotiff-v1",
            "policyVersion": 5,
        },
    ]
    decision, detail = seed.plan_policy_admission(
        journal_rows=journal, now=now, **_planner_inputs(policy, record, correct, subjects)
    )
    assert decision == "mismatch", detail


def test_plan_expired_record_fails_clearly_no_writes(tmp_path: Path) -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, _ = _sealed_test_policy(subjects)
    now = datetime.now(UTC).replace(microsecond=0)
    stale = _record_variant(correct, subjects, hours_back=9 * 24, days_valid=-2)
    assert stale.digest is not None
    journal = [_admit_row(policy, stale)]
    sentinel = tmp_path / "snapshot.json"
    sentinel.write_bytes(b'{"records": []}')
    before = sentinel.read_bytes()
    decision, detail = seed.plan_policy_admission(
        journal_rows=journal,
        now=now,
        **_planner_inputs(
            policy,
            stale,
            correct,
            subjects,
            file_records=[stale.event_payload()],
            file_current=[stale.digest],
        ),
    )
    assert decision == "mismatch", detail
    assert "window" in detail
    assert sentinel.read_bytes() == before


def test_plan_subject_tuple_must_match_exactly_not_labels() -> None:
    subjects = (
        _test_subject("obs-work-1", "syn-demo-t0-submission", "ab"),
        _test_subject("obs-work-1", "syn-demo-t1-submission", "cd"),
    )
    policy, record, correct, now = _sealed_test_policy(subjects)
    journal = [_admit_row(policy, record)]
    swapped = (subjects[1], subjects[0])
    inputs = _planner_inputs(policy, record, correct, subjects)
    inputs["subjects"] = swapped
    decision, detail = seed.plan_policy_admission(journal_rows=journal, now=now, **inputs)
    assert decision == "mismatch", detail


def test_latest_policy_status_ordering() -> None:
    adm = {"kind": "external-validation-policy-admitted", "policyId": "p", "policyVersion": 1}
    rev = {"kind": "external-validation-policy-revoked", "policyId": "p", "policyVersion": 1}
    assert seed.latest_policy_status([], "p", 1) == ("absent", None)
    assert seed.latest_policy_status([adm], "p", 1)[0] == "admitted"
    assert seed.latest_policy_status([adm, rev], "p", 1)[0] == "revoked"
    unknown = [{"kind": "unknown", "policyId": "p", "policyVersion": 1}]
    assert seed.latest_policy_status(unknown, "p", 1)[0] == "absent"


def test_read_jsonl_rows_uses_given_path(tmp_path: Path) -> None:
    journal = tmp_path / "external-validation-policy.jsonl"
    journal.write_text('{"kind": "a"}\n\n{"kind": "b"}\n', encoding="utf-8")
    assert seed.read_jsonl_rows(journal) == [{"kind": "a"}, {"kind": "b"}]
    assert seed.read_jsonl_rows(tmp_path / "missing.jsonl") == []
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{oops\n", encoding="utf-8")
    try:
        seed.read_jsonl_rows(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed journal must fail")


def test_build_template_honors_provided_template_path(tmp_path: Path) -> None:
    template = tmp_path / "policy-template.json"
    template.write_text(
        json.dumps(
            {
                "inspectionRuleIds": ["EXTERNAL_GEOTIFF_MEASURED_V1"],
                "evidenceRuleIds": ["CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1"],
                "compatibilityMappingDigests": [],
            }
        ),
        encoding="utf-8",
    )
    built = seed.build_live_template(template)
    assert built["inspectionRuleIds"] == ["EXTERNAL_GEOTIFF_MEASURED_V1"]
    assert built["evidenceRuleIds"] == ["CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1"]

    with pytest.raises((FileNotFoundError, OSError)):
        seed.build_live_template(tmp_path / "does-not-exist.json")

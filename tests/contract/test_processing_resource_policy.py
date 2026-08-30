"""Processing Resource Policy v1 contract and Core admission gates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.metrics import PROCESSING_JOB_ADMISSIONS
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    ProcessingJobRecoveryError,
    ProcessingJobStore,
    ProcessingJobVerdict,
)
from ksi_core.processing_resource_policy import (
    KSI_CIVIL_PILOT_R1_ID,
    ProcessingResourcePolicyRegistry,
    UnknownProcessingResourcePolicyError,
    ksi_civil_pilot_r1,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaStore
from ksi_event_contracts.processing_job import DataResidency
from ksi_event_contracts.processing_resource_policy import (
    ProcessingResourcePolicyV1,
    processing_resource_policy_wire_dict,
)
from ksi_mission_contracts.models import SiteFrame
from pydantic import ValidationError

_NOW = datetime(2026, 8, 30, tzinfo=UTC)
_FRAME = SiteFrame(crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter")
_TOKEN = "resource-policy-admin"  # noqa: S105 -- test-only bearer token


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _claim(
    media_id: str,
    *,
    bytes_: int = 1_000,
    width: int = 100,
    height: int = 100,
) -> SourceMediaClaim:
    return SourceMediaClaim(
        media_id=media_id,
        sha256=_sha(media_id),
        size_bytes=bytes_,
        width=width,
        height=height,
        content_type="image/jpeg",
    )


def _register_mission(missions: MissionStore, mission_id: str, *, organization_id: str) -> None:
    assert missions.record_issuance(
        MissionRecord(
            mission_id=mission_id,
            site_id="site-policy",
            mission_type="BASELINE_MAPPING",
            artifact_kind="contract",
            contract={"schemaVersion": "1.2", "missionId": mission_id},
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=_NOW,
            issued_by="operator-1",
            organization_id=organization_id,
        )
    ).value == "RECORDED"


def _store(
    tmp_path: Path,
    *,
    policy: ProcessingResourcePolicyV1 | None = None,
    missions: tuple[tuple[str, str, tuple[SourceMediaClaim, ...]], ...] = (
        ("mission-policy-1", "org-a", (_claim("image-1"),)),
    ),
) -> ProcessingJobStore:
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    source = SourceMediaStore(
        DurableJournal(tmp_path / "source.jsonl"), mission_store=mission_store
    )
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert sites.register(
        "site-policy",
        "Policy test site",
        _FRAME,
        data_residency=DataResidency(egress_allowed=False, jurisdiction="KR"),
        actor="operator-1",
        now=_NOW,
    ).verdict.value == "REGISTERED"
    for mission_id, organization_id, claims in missions:
        _register_mission(mission_store, mission_id, organization_id=organization_id)
        assert (
            source.register_batch(
                mission_id, claims, registered_by="operator-1", now=_NOW
            ).verdict.value
            == "PROCESSED"
        )
        assert source.seal(mission_id, sealed_by="operator-1", now=_NOW).verdict.value == "SEALED"
    registry = ProcessingResourcePolicyRegistry(
        (policy or ksi_civil_pilot_r1(),),
        current_policy_id=(policy or ksi_civil_pilot_r1()).resource_policy_id,
    )
    return ProcessingJobStore(
        DurableJournal(tmp_path / "jobs.jsonl"),
        source_media_store=source,
        site_store=sites,
        processing_resource_policy_registry=registry,
    )


def _issue(store: ProcessingJobStore, mission_id: str):
    return store.issue(
        mission_id,
        store.resolve_processing_profile("ksi-odm-civil-v1"),
        issued_by="operator-1",
        now=_NOW,
    )


def _policy(**overrides: int | float | str) -> ProcessingResourcePolicyV1:
    values: dict[str, int | float | str] = {
        "resource_policy_id": "test-policy-r1",
        "max_source_media_files": 10,
        "max_source_media_file_bytes": 10_000,
        "max_source_bundle_bytes": 20_000,
        "max_total_megapixels": 10.0,
        "max_active_processing_jobs_per_organization": 2,
    }
    values.update(overrides)
    return ProcessingResourcePolicyV1.model_validate(values).sealed()


def test_civil_pilot_policy_is_canonical_and_matches_schema() -> None:
    policy = ksi_civil_pilot_r1()
    wire = processing_resource_policy_wire_dict(policy)
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts/schemas/processing-resource-policy.v1.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    assert wire["resourcePolicyId"] == KSI_CIVIL_PILOT_R1_ID
    assert wire["maxSourceMediaFiles"] == 5_000
    assert wire["maxSourceMediaFileBytes"] == 1_073_741_824
    assert wire["maxSourceBundleBytes"] == 1_099_511_627_776
    assert wire["maxTotalMegapixels"] == 150_000.0
    assert wire["maxActiveProcessingJobsPerOrganization"] == 20
    assert policy.canonical_digest() == ksi_civil_pilot_r1().canonical_digest()


def test_resource_policy_digest_tamper_is_rejected() -> None:
    forged = processing_resource_policy_wire_dict(ksi_civil_pilot_r1())
    forged["maxSourceMediaFiles"] = 1
    with pytest.raises(ValueError, match="resourcePolicyDigest"):
        ProcessingResourcePolicyV1.model_validate(forged)


def test_sealed_policy_rejects_assignment_and_keeps_content_digest_bound() -> None:
    policy = ksi_civil_pilot_r1()
    original_digest = policy.resource_policy_digest
    original_files = policy.max_source_media_files
    with pytest.raises(ValidationError, match="frozen_instance"):
        policy.max_source_media_files = 1
    assert policy.max_source_media_files == original_files
    assert policy.resource_policy_digest == original_digest
    assert policy.canonical_digest() == original_digest


def test_registry_copy_rejects_assignment_and_cannot_mutate_issued_snapshot() -> None:
    registry = ProcessingResourcePolicyRegistry()
    returned = registry.current()
    original_digest = returned.resource_policy_digest
    with pytest.raises(ValidationError, match="frozen_instance"):
        returned.max_source_bundle_bytes = 1
    fresh = registry.current()
    assert fresh.max_source_bundle_bytes == 1_099_511_627_776
    assert fresh.resource_policy_digest == original_digest
    assert fresh.canonical_digest() == original_digest


def test_resource_policy_registry_rejects_duplicate_or_missing_current_policy() -> None:
    policy = _policy()
    with pytest.raises(ValueError, match="id 중복"):
        ProcessingResourcePolicyRegistry(
            (policy, policy), current_policy_id=policy.resource_policy_id
        )
    with pytest.raises(UnknownProcessingResourcePolicyError):
        ProcessingResourcePolicyRegistry((policy,), current_policy_id="not-issued")


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_resource_policy_rejects_non_finite_megapixel_limits(invalid: float) -> None:
    with pytest.raises(ValueError):
        _policy(max_total_megapixels=invalid)


@pytest.mark.parametrize(
    ("policy", "claims", "reason"),
    [
        (
            _policy(max_source_media_files=1),
            (_claim("a"), _claim("b")),
            "SOURCE_MEDIA_FILES_LIMIT_EXCEEDED",
        ),
        (
            _policy(max_source_media_file_bytes=999),
            (_claim("a", bytes_=1_000),),
            "SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED",
        ),
        (
            _policy(max_source_media_file_bytes=1_000, max_source_bundle_bytes=1_500),
            (_claim("a", bytes_=1_000), _claim("b", bytes_=1_000)),
            "SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED",
        ),
        (
            _policy(max_total_megapixels=0.01),
            (_claim("a", width=200, height=100),),
            "TOTAL_MEGAPIXELS_LIMIT_EXCEEDED",
        ),
    ],
)
def test_issue_fails_closed_for_each_source_resource_limit(
    tmp_path: Path,
    policy: ProcessingResourcePolicyV1,
    claims: tuple[SourceMediaClaim, ...],
    reason: str,
) -> None:
    store = _store(tmp_path, policy=policy, missions=(("mission-policy-1", "org-a", claims),))
    result = _issue(store, "mission-policy-1")
    assert result.verdict is ProcessingJobVerdict.RESOURCE_LIMIT_EXCEEDED
    assert result.reason_code == reason


def test_same_org_active_count_is_limited_but_other_org_is_independent(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        policy=_policy(max_active_processing_jobs_per_organization=1),
        missions=(
            ("mission-a-1", "org-a", (_claim("a1"),)),
            ("mission-a-2", "org-a", (_claim("a2"),)),
            ("mission-b-1", "org-b", (_claim("b1"),)),
        ),
    )
    assert _issue(store, "mission-a-1").verdict is ProcessingJobVerdict.ISSUED
    denied = _issue(store, "mission-a-2")
    assert denied.verdict is ProcessingJobVerdict.RESOURCE_LIMIT_EXCEEDED
    assert denied.reason_code == "ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED"
    assert _issue(store, "mission-b-1").verdict is ProcessingJobVerdict.ISSUED


def test_idempotent_active_retry_precedes_new_policy_limit(tmp_path: Path) -> None:
    store = _store(tmp_path, policy=_policy(max_active_processing_jobs_per_organization=1))
    first = _issue(store, "mission-policy-1")
    assert first.verdict is ProcessingJobVerdict.ISSUED
    # Simulate a later policy rotation without mutating the issued snapshot.
    store._resource_policies = ProcessingResourcePolicyRegistry(  # noqa: SLF001
        (_policy(resource_policy_id="rotated-r2", max_active_processing_jobs_per_organization=1),),
        current_policy_id="rotated-r2",
    )
    retry = _issue(store, "mission-policy-1")
    assert retry.verdict is ProcessingJobVerdict.ALREADY_ISSUED
    assert retry.record is not None
    assert retry.record.resource_policy_id == "test-policy-r1"


def test_current_policy_snapshot_replays_and_forged_binding_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    issued = _issue(store, "mission-policy-1")
    assert issued.verdict is ProcessingJobVerdict.ISSUED
    journal_path = store._journal._path  # noqa: SLF001
    store._journal.close()  # noqa: SLF001
    replayed = ProcessingJobStore(
        DurableJournal(journal_path),
        source_media_store=store._source_media,  # noqa: SLF001
        site_store=store._sites,  # noqa: SLF001
    )
    recovered = replayed.get(issued.record.job_id if issued.record is not None else "")
    assert recovered is not None
    assert recovered.resource_policy_id == KSI_CIVIL_PILOT_R1_ID
    assert recovered.resource_policy_digest == ksi_civil_pilot_r1().resource_policy_digest
    replayed._journal.close()  # noqa: SLF001

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    raw = json.loads(lines[0])
    raw["resourcePolicyDigest"] = "sha256:" + "f" * 64
    journal_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ProcessingJobRecoveryError, match="resource policy snapshot digest"):
        ProcessingJobStore(
            DurableJournal(journal_path),
            source_media_store=store._source_media,  # noqa: SLF001
            site_store=store._sites,  # noqa: SLF001
        )


def test_legacy_job_without_resource_policy_replays_as_honestly_absent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    issued = _issue(store, "mission-policy-1")
    assert issued.record is not None
    journal_path = store._journal._path  # noqa: SLF001
    store._journal.close()  # noqa: SLF001
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    raw.pop("resourcePolicy")
    raw.pop("resourcePolicyDigest")
    journal_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    replayed = ProcessingJobStore(
        DurableJournal(journal_path),
        source_media_store=store._source_media,  # noqa: SLF001
        site_store=store._sites,  # noqa: SLF001
    )
    recovered = replayed.get(issued.record.job_id)
    assert recovered is not None
    assert recovered.resource_policy_id is None
    assert recovered.resource_policy_digest is None


@pytest.mark.parametrize("missing_key", ["resourcePolicy", "resourcePolicyDigest"])
def test_replay_rejects_half_resource_policy_binding(tmp_path: Path, missing_key: str) -> None:
    store = _store(tmp_path)
    assert _issue(store, "mission-policy-1").verdict is ProcessingJobVerdict.ISSUED
    journal_path = store._journal._path  # noqa: SLF001
    store._journal.close()  # noqa: SLF001
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    raw.pop(missing_key)
    journal_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ProcessingJobRecoveryError, match="resource policy binding이 반쪽"):
        ProcessingJobStore(
            DurableJournal(journal_path),
            source_media_store=store._source_media,  # noqa: SLF001
            site_store=store._sites,  # noqa: SLF001
        )


def test_replay_rejects_current_record_that_violates_its_policy(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        missions=(("mission-policy-1", "org-a", (_claim("a"), _claim("b"))),),
    )
    assert _issue(store, "mission-policy-1").verdict is ProcessingJobVerdict.ISSUED
    journal_path = store._journal._path  # noqa: SLF001
    store._journal.close()  # noqa: SLF001
    violating = _policy(max_source_media_files=1)
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    raw["resourcePolicy"] = processing_resource_policy_wire_dict(violating)
    raw["resourcePolicyDigest"] = violating.resource_policy_digest
    journal_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ProcessingJobRecoveryError, match="resource policy 위반"):
        ProcessingJobStore(
            DurableJournal(journal_path),
            source_media_store=store._source_media,  # noqa: SLF001
            site_store=store._sites,  # noqa: SLF001
        )


def test_http_discovery_is_authenticated_and_issue_refuses_policy_overrides(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token_digest = hashlib.sha256(_TOKEN.encode()).hexdigest()
    auth = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=token_digest,
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-a",
                ),
            )
        ]
    )
    app = create_app(
        auth_registry=auth,
        evidence_storage=object(),
        mission_store=store._source_media._mission_store,  # noqa: SLF001
        source_media_store=store._source_media,  # noqa: SLF001
        site_store=store._sites,  # noqa: SLF001
        processing_job_store=store,
        mission_signing_key=None,
    )
    client = TestClient(app)
    assert client.get("/v1/processing-resource-policies").status_code == 401
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    discovered = client.get("/v1/processing-resource-policies")
    assert discovered.status_code == 200
    payload = discovered.json()
    assert payload["currentPolicyId"] == KSI_CIVIL_PILOT_R1_ID
    assert [policy["resourcePolicyId"] for policy in payload["policies"]].count(
        payload["currentPolicyId"]
    ) == 1
    issued = client.post(
        "/v1/missions/mission-policy-1/processing-jobs",
        json={"processingProfileId": "ksi-odm-civil-v1"},
    )
    assert issued.status_code == 201
    metrics = "\n".join(PROCESSING_JOB_ADMISSIONS.render())
    assert 'outcome="issued"' in metrics
    assert 'reason="ISSUED"' in metrics
    for forbidden in ("organization", "mission", "job", "site", "media", "filename"):
        assert f'{forbidden}="' not in metrics
    for hostile_field, hostile_value in (
        ("resourcePolicyId", "attacker"),
        ("maxSourceMediaFiles", 999_999),
        ("resourcePolicyOverride", True),
    ):
        hostile = client.post(
            "/v1/missions/mission-policy-1/processing-jobs",
            json={"processingProfileId": "ksi-odm-civil-v1", hostile_field: hostile_value},
        )
        assert hostile.status_code == 422
        assert hostile.headers["content-type"].startswith("application/json")

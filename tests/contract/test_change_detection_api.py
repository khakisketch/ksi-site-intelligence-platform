"""변화 탐지 결과 수신·조회 계약 + 재방문 권고 (PRD §15.4, §15.2 ⑤).

초점은 둘이다.

**① 무엇과 무엇을 비교했는지가 해석 가능한가.** "변화가 12% 있었다"는 두 point
cloud 를 지목하지 못하면 아무도 재현할 수 없는 주장이다. artifactId 는 처리 작업
단위로만 고유하므로(processing_jobs.py) jobId 와 짝으로만 해석된다 — 서버가 그
짝을 실제 원장에서 대조한다.

**② 권고가 운영자에게 도달하는가.** needs_change_candidate_revisit 는 정확하게
구현돼 있었지만 호출부가 0건이었다(risk phase2-change-candidate-revisit) — 계산은
되는데 읽을 수 있는 곳이 없었다. 이 파일은 그 신호가 실제로 API 응답 필드로
나오는지, 그리고 **무슨 기준으로 켜졌는지**가 함께 나오는지를 고정한다.

green≠작동: 처리 작업을 실제로 발급하고 lease → RUNNING → 산출물 등록까지 진행한
뒤 그 산출물 id 로 비교 결과를 올린다 — 픽스처가 산출물 실재를 우회하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.change_detection import (
    ChangeDetectionRecoveryError,
    ChangeDetectionStore,
    ChangeDetectionVerdict,
    mount_change_detection,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    ArtifactSpec,
    JobSpec,
    ProcessingJobStatus,
    ProcessingJobStore,
    ProcessingJobVerdict,
)
from ksi_core.sites import SiteFrame, SiteStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaStore
from ksi_event_contracts.change_detection_result import ChangeDetectionResult
from ksi_event_contracts.processing_artifact import LineageAuthority, ProcessingArtifactKind
from ksi_event_contracts.processing_job import ExecutionLocus, LicenseBasis, ProcessingProvider

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "change-detection-result.v1.json"

_WORKER_TOKEN = "processing-worker-token"  # noqa: S105 — 테스트 고정값
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_MISSION_ID = "mission-cd-1"
_SITE_ID = "site-001"
_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)
_NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _mission_store(tmp_path: Path, *, path: str = "missions.jsonl") -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="BASELINE_MAPPING",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="op-1",
            )
        ).value
        == "RECORDED"
    )
    return store


def _sealed_bundles(tmp_path: Path) -> SourceMediaStore:
    store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"),
        mission_store=_mission_store(tmp_path, path="m-source.jsonl"),
    )
    claims = [
        SourceMediaClaim(
            media_id=f"img-{i:03d}.jpg",
            sha256=hashlib.sha256(f"img-{i}".encode()).hexdigest(),
            size_bytes=1_000_000 + i,
            width=4000,
            height=3000,
            content_type="image/jpeg",
        )
        for i in range(3)
    ]
    assert (
        store.register_batch(_MISSION_ID, claims, registered_by="op-1", now=_NOW).verdict.value
        == "PROCESSED"
    )
    assert store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    return store


def _job_store(tmp_path: Path, journal: DurableJournal) -> ProcessingJobStore:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert (
        sites.register(
            _SITE_ID, "테스트 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
        ).verdict.value
        == "REGISTERED"
    )
    return ProcessingJobStore(
        journal, source_media_store=_sealed_bundles(tmp_path), site_store=sites
    )


def _job_spec() -> JobSpec:
    return JobSpec(
        provider=ProcessingProvider.ODM,
        engine_version="3.5.4",
        engine_digest="sha256:" + "a" * 64,
        execution_locus=ExecutionLocus.KSI_SERVER_GPU,
        license_basis=LicenseBasis(
            license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
        ),
        processing_params={"quality": "high"},
    )


def _artifact_spec(
    artifact_id: str, *, kind: ProcessingArtifactKind = ProcessingArtifactKind.POINT_CLOUD
) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_id=artifact_id,
        kind=kind,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        digest="sha256:" + hashlib.sha256(artifact_id.encode()).hexdigest(),
        format="laz",
        crs="EPSG:5186",
        gsd=None,
        accuracy=None,
    )


def _job_with_artifacts(jobs: ProcessingJobStore, *artifact_specs: ArtifactSpec) -> str:
    """발급 → lease → RUNNING → 산출물 등록까지 실제로 진행한 작업의 jobId."""
    record = jobs.issue(_MISSION_ID, _job_spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    assert jobs.acquire_lease(record.job_id, worker_id="w-1", now=_NOW).verdict in {
        ProcessingJobVerdict.LEASED,
        ProcessingJobVerdict.LEASE_RENEWED,
    }
    assert (
        jobs.transition(
            record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    for spec in artifact_specs:
        result = jobs.register_artifact(record.job_id, spec, registered_by="w-1", now=_NOW)
        assert result.verdict is ProcessingJobVerdict.ARTIFACT_REGISTERED, result
    return record.job_id


@pytest.fixture
def context(tmp_path: Path) -> tuple[ChangeDetectionStore, str]:
    """(변화탐지 저장소, 산출물 두 개가 등록된 jobId)."""
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(
        jobs, _artifact_spec("pc-baseline"), _artifact_spec("pc-current")
    )
    store = ChangeDetectionStore(
        DurableJournal(tmp_path / "change-detection.jsonl"),
        mission_store=missions,
        processing_job_store=jobs,
    )
    return store, job_id


def _result_payload(
    job_id: str,
    *,
    result_id: str = "cd-001",
    baseline_artifact: str = "pc-baseline",
    current_artifact: str = "pc-current",
    baseline_job: str | None = None,
    point_count: int = 1000,
    candidate_count: int = 120,
    ratio: float | None = None,
    threshold_m: float = 0.05,
    max_distance_m: float | None = 1.4,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "1.0",
        "changeDetectionId": result_id,
        "baseline": {"jobId": baseline_job or job_id, "artifactId": baseline_artifact},
        "current": {"jobId": job_id, "artifactId": current_artifact},
        "distanceThresholdM": threshold_m,
        "pointCount": point_count,
        "candidateCount": candidate_count,
        "candidateRatio": ratio if ratio is not None else candidate_count / point_count,
        "computedAt": "2026-08-08T02:00:00+00:00",
    }
    if max_distance_m is not None:
        payload["maxDistanceM"] = max_distance_m
    return payload


def _client(store: ChangeDetectionStore, *, token: str = _WORKER_TOKEN) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_change_detection(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


# ── 계약 스키마 정합 ────────────────────────────────────────────────────────


def test_payload_satisfies_contract_schema(context: tuple[ChangeDetectionStore, str]) -> None:
    _store, job_id = context
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(_result_payload(job_id)), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]


def test_model_output_satisfies_contract_schema(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """Python 모델의 wire 산출이 스키마를 만족한다 — 두 정본이 갈라지지 않게."""
    _store, job_id = context
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    model = ChangeDetectionResult.model_validate(_result_payload(job_id))
    wire = model.model_dump(by_alias=True, mode="json", exclude_none=False)
    assert not sorted(validator.iter_errors(wire), key=lambda e: e.path)
    assert ChangeDetectionResult.model_validate(wire) == model  # 왕복 역방향


# ── 계약이 자기모순을 거부한다 ──────────────────────────────────────────────


def test_ratio_inconsistent_with_counts_is_rejected(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """[핵심] 후보 0건인데 비율 0.9 — 세 값이 서로를 뒷받침하지 않는다.

    이 결과가 원장에 남으면 그 비율로 재방문 권고가 켜지는데, 어떤 화면에서도
    이상해 보이지 않는다."""
    _store, job_id = context
    with pytest.raises(ValueError, match="candidateRatio"):
        ChangeDetectionResult.model_validate(
            _result_payload(job_id, candidate_count=0, ratio=0.9)
        )


def test_candidate_count_above_point_count_is_rejected(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    _store, job_id = context
    with pytest.raises(ValueError, match="candidateCount"):
        ChangeDetectionResult.model_validate(
            _result_payload(job_id, point_count=10, candidate_count=11, ratio=1.0)
        )


def test_max_distance_below_threshold_with_candidates_is_rejected(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """문턱을 초과한 점이 하나라도 있으면 최댓값은 문턱보다 크다 — 자기모순."""
    _store, job_id = context
    with pytest.raises(ValueError, match="maxDistanceM"):
        ChangeDetectionResult.model_validate(
            _result_payload(job_id, candidate_count=5, threshold_m=0.5, max_distance_m=0.2)
        )


def test_naive_computed_at_is_rejected(context: tuple[ChangeDetectionStore, str]) -> None:
    _store, job_id = context
    payload = _result_payload(job_id)
    payload["computedAt"] = "2026-08-08T02:00:00"
    with pytest.raises(ValueError, match="tz-aware"):
        ChangeDetectionResult.model_validate(payload)


# ── 서버가 비교 대상을 대조한다 ─────────────────────────────────────────────


def test_result_referencing_real_artifacts_is_recorded(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection", json=_result_payload(job_id)
    )
    assert response.status_code == 201, response.json()
    assert response.json()["verdict"] == "RECORDED"


def test_unknown_job_is_rejected(context: tuple[ChangeDetectionStore, str]) -> None:
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, baseline_job="job-never-existed"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == ChangeDetectionVerdict.UNKNOWN_ARTIFACT.value


def test_unknown_artifact_in_known_job_is_rejected(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, baseline_artifact="pc-does-not-exist"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == ChangeDetectionVerdict.UNKNOWN_ARTIFACT.value


def test_non_point_cloud_artifact_is_rejected(tmp_path: Path) -> None:
    """C2C 비교의 입력은 point_cloud 여야 한다.

    camera_poses 를 고른 이유: 같은 ODM 실행이 point_cloud 와 **나란히** 내는
    원본(authority=source) 산출물이라, 워커가 id 를 헷갈려 집어넣기 가장 쉬운
    값이다. 거리 비교가 성립하지 않는 입력인데 결과 숫자는 멀쩡히 생긴다.
    """
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(
        jobs,
        _artifact_spec("pc-baseline"),
        _artifact_spec("poses-1", kind=ProcessingArtifactKind.CAMERA_POSES),
    )
    store = ChangeDetectionStore(
        DurableJournal(tmp_path / "change-detection.jsonl"),
        mission_store=missions,
        processing_job_store=jobs,
    )
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, current_artifact="poses-1"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == ChangeDetectionVerdict.ARTIFACT_KIND_MISMATCH.value


def test_self_comparison_is_rejected(context: tuple[ChangeDetectionStore, str]) -> None:
    """[핵심] 자기 자신과의 C2C 는 전 점 거리 0 이라 '변화 없음'으로 정직해
    보이지만 실제로는 아무것도 비교하지 않은 것이다."""
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(
            job_id,
            baseline_artifact="pc-current",
            current_artifact="pc-current",
            candidate_count=0,
            max_distance_m=None,
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == ChangeDetectionVerdict.SELF_COMPARISON.value


def test_unknown_mission_is_rejected(context: tuple[ChangeDetectionStore, str]) -> None:
    store, job_id = context
    response = _client(store).post(
        "/v1/missions/mission-never-issued/change-detection", json=_result_payload(job_id)
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == ChangeDetectionVerdict.UNKNOWN_MISSION.value


def test_same_id_different_content_is_conflict(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    store, job_id = context
    client = _client(store)
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/change-detection", json=_result_payload(job_id)
        ).status_code
        == 201
    )
    conflict = client.post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, candidate_count=500),
    )
    assert conflict.status_code == 409
    assert conflict.json()["verdict"] == ChangeDetectionVerdict.DUPLICATE_RESULT_ID.value


def test_identical_resubmit_is_idempotent(context: tuple[ChangeDetectionStore, str]) -> None:
    store, job_id = context
    client = _client(store)
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/change-detection", json=_result_payload(job_id)
        ).status_code
        == 201
    )
    again = client.post(
        f"/v1/missions/{_MISSION_ID}/change-detection", json=_result_payload(job_id)
    )
    assert again.status_code == 201
    assert store.history(_MISSION_ID) != []
    assert len(store.history(_MISSION_ID)) == 1


# ── 권한 ────────────────────────────────────────────────────────────────────


def test_operator_cannot_submit_result(context: tuple[ChangeDetectionStore, str]) -> None:
    store, job_id = context
    response = _client(store, token=_VIEWER_TOKEN).post(
        f"/v1/missions/{_MISSION_ID}/change-detection", json=_result_payload(job_id)
    )
    assert response.status_code == 403


# ── PRD §15.2 ⑤ 재방문 권고가 운영자에게 도달한다 ───────────────────────────


def test_revisit_recommended_is_exposed_with_its_threshold(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """[핵심 — risk phase2-change-candidate-revisit] 신호가 API 필드로 나오고,
    **무슨 기준으로 켜졌는지**도 함께 나온다."""
    store, job_id = context
    _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, point_count=1000, candidate_count=120),  # ratio 0.12
    )
    viewer = _client(store, token=_VIEWER_TOKEN)

    hit = viewer.get(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        params={"revisitRatioThreshold": 0.1},
    ).json()
    assert hit["revisitRecommended"] is True
    assert hit["revisitRatioThreshold"] == 0.1

    miss = viewer.get(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        params={"revisitRatioThreshold": 0.2},
    ).json()
    assert miss["revisitRecommended"] is False
    assert miss["revisitRatioThreshold"] == 0.2


def test_revisit_threshold_is_strict_inequality(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """경계값 자체는 권고 트리거가 아니다 — detect_change_candidates 와 같은 규약."""
    store, job_id = context
    _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, point_count=1000, candidate_count=250),  # ratio 0.25
    )
    viewer = _client(store, token=_VIEWER_TOKEN)
    at_boundary = viewer.get(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        params={"revisitRatioThreshold": 0.25},
    ).json()
    assert at_boundary["revisitRecommended"] is False
    just_below = viewer.get(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        params={"revisitRatioThreshold": 0.2499},
    ).json()
    assert just_below["revisitRecommended"] is True


def test_zero_candidates_never_recommends_revisit(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """임계값이 0 이어도 "후보가 없는데 재방문 권고"라는 모순을 만들지 않는다."""
    store, job_id = context
    _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, candidate_count=0, max_distance_m=0.01),
    )
    view = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        params={"revisitRatioThreshold": 0.0},
    ).json()
    assert view["revisitRecommended"] is False


def test_api_signal_matches_the_computation_side_function(
    context: tuple[ChangeDetectionStore, str],
) -> None:
    """[규칙 SSOT] API 가 노출하는 값과 계산 쪽 편의 함수가 같은 판정을 낸다 —
    규칙이 두 곳에 있으면 갈라지고, 그 갈라짐은 화면에서 보이지 않는다."""
    import numpy as np
    from ksi_change_detection.point_cloud_diff import ChangeCandidateResult
    from ksi_change_detection.revisit_signal import needs_change_candidate_revisit

    store, job_id = context
    _client(store).post(
        f"/v1/missions/{_MISSION_ID}/change-detection",
        json=_result_payload(job_id, point_count=1000, candidate_count=120),
    )
    numpy_side = ChangeCandidateResult(
        distances_m=np.zeros(1000),
        is_candidate=np.zeros(1000, dtype=bool),
        candidate_count=120,
        candidate_ratio=0.12,
    )
    viewer = _client(store, token=_VIEWER_TOKEN)
    for threshold in (0.0, 0.05, 0.12, 0.119, 0.5):
        api = viewer.get(
            f"/v1/missions/{_MISSION_ID}/change-detection",
            params={"revisitRatioThreshold": threshold},
        ).json()["revisitRecommended"]
        assert api is needs_change_candidate_revisit(
            numpy_side, candidate_ratio_threshold=threshold
        ), f"threshold={threshold} 에서 API 와 계산 함수의 판정이 갈라졌다"


def test_missing_result_is_404(context: tuple[ChangeDetectionStore, str]) -> None:
    store, _job_id = context
    response = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/missions/{_MISSION_ID}/change-detection"
    )
    assert response.status_code == 404


# ── 재생도 같은 게이트를 탄다 ───────────────────────────────────────────────


def test_replay_refuses_result_that_live_would_reject(tmp_path: Path) -> None:
    """journal 을 손으로 고쳐 존재하지 않는 산출물을 가리키는 결과를 되살릴 수 없다."""
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(jobs, _artifact_spec("pc-baseline"), _artifact_spec("pc-current"))
    journal_path = tmp_path / "change-detection.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "change-detection-recorded",
                "ts": _NOW.isoformat(),
                "missionId": _MISSION_ID,
                "reportedBy": "worker-1",
                "result": _result_payload(job_id, baseline_artifact="pc-ghost"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    journal = DurableJournal(journal_path)
    with pytest.raises(ChangeDetectionRecoveryError, match="UNKNOWN_ARTIFACT"):
        ChangeDetectionStore(
            journal, mission_store=missions, processing_job_store=jobs
        )

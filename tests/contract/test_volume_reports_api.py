"""체적 변화 리포트 수신·조회 계약 (ADR-KSI-016 D3, INV-024).

``test_change_detection_api.py`` 와 같은 골격을 시험하되, 검증 대상이 다르다 —
저기는 입력이 point_cloud 인지 보고 여기는 **dsm** 인지 본다. 그 차이가 두
저장소를 형제로 둔 이유이므로, 잘못된 kind 를 거부하는 테스트가 이 파일의
중심에 있다.

초점 넷:

1. **사람은 체적을 주장할 수 없다** — PROCESSING_WORK 는 어느 Role 에도
   매핑되지 않는다. 이 숫자는 정산·분쟁의 근거가 될 수 있고, 그럴수록 손으로
   적히면 안 된다.
2. **참조가 실재하는 DSM 인가** — "이만큼 깎였다"가 어느 두 산출물의 비교인지
   대조되지 않으면 아무도 재현할 수 없는 주장이 된다.
3. **재생이 live 와 같은 게이트를 탄다** — journal 을 손대 해석 불가능한
   리포트를 되살리는 경로를 막는다.
4. **없는 것과 0 을 구분한다** — 리포트가 없으면 404 다. 빈 목록을 주면
   "아직 계산 안 됨"과 "변화 없음"이 화면에서 같아 보인다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _volume_fixtures import (
    _MISSION_ID,
    _NOW,
    _VIEWER_TOKEN,
    _WORKER_TOKEN,
    _artifact_spec,
    _job_store,
    _job_with_artifacts,
    _mission_store,
    _registry,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.volume_reports import (
    VolumeChangeRecoveryError,
    VolumeChangeStore,
    mount_volume_reports,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind


@pytest.fixture
def context(tmp_path: Path) -> tuple[VolumeChangeStore, str]:
    """(체적 저장소, DSM 두 개와 point cloud 하나가 등록된 jobId)."""
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(
        jobs,
        _artifact_spec("dsm-baseline"),
        _artifact_spec("dsm-current"),
        _artifact_spec("pc-1", kind=ProcessingArtifactKind.POINT_CLOUD),
    )
    store = VolumeChangeStore(
        DurableJournal(tmp_path / "volume-changes.jsonl"),
        mission_store=missions,
        processing_job_store=jobs,
    )
    return store, job_id


def _payload(
    job_id: str,
    *,
    report_id: str = "vc-001",
    baseline_artifact: str = "dsm-baseline",
    current_artifact: str = "dsm-current",
    cut: float = 30.0,
    fill: float = 100.0,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "volumeChangeId": report_id,
        "baseline": {"jobId": job_id, "artifactId": baseline_artifact},
        "current": {"jobId": job_id, "artifactId": current_artifact},
        "crs": "EPSG:5186",
        "verticalDatum": "ellipsoidal_native",
        "zones": [
            {
                "zoneId": "zone-0",
                "cutM3": cut,
                "fillM3": fill,
                "netM3": fill - cut,
                "areaM2": 2500.0,
                "thresholdM": 0.05,
                "uncertaintyM3": None,
                "uncertaintyNote": "ODM 경로는 검사점 RMSE 를 내지 않는다",
            }
        ],
        "computedAt": "2026-08-08T02:00:00+00:00",
    }


def _client(store: VolumeChangeStore, *, token: str = _WORKER_TOKEN) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_volume_reports(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_worker_can_record_and_read_back(context: tuple[VolumeChangeStore, str]) -> None:
    store, job_id = context
    client = _client(store)

    posted = client.post(f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id))
    assert posted.status_code == 201, posted.text
    assert posted.json()["verdict"] == "RECORDED"

    client.headers.update({"Authorization": f"Bearer {_VIEWER_TOKEN}"})
    got = client.get(f"/v1/missions/{_MISSION_ID}/volume-changes")
    assert got.status_code == 200, got.text
    view = got.json()
    assert view["reportCount"] == 1
    assert view["latestTotalNetM3"] == pytest.approx(70.0)
    assert view["reports"][0]["report"]["zones"][0]["cutM3"] == 30.0


def test_point_cloud_input_is_refused(context: tuple[VolumeChangeStore, str]) -> None:
    """[핵심 음성] 체적 차분의 입력은 DSM 이다 — 점군을 그대로 받지 않는다.

    이 검사가 change-detection 과 반대라, 두 저장소를 형제로 둔 이유가
    여기서 드러난다.
    """
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/volume-changes",
        json=_payload(job_id, current_artifact="pc-1"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "ARTIFACT_KIND_MISMATCH"


def test_unknown_artifact_is_refused(context: tuple[VolumeChangeStore, str]) -> None:
    """[음성] 등록된 적 없는 산출물을 비교했다는 주장은 재현할 수 없다."""
    store, job_id = context
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/volume-changes",
        json=_payload(job_id, current_artifact="dsm-nope"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "UNKNOWN_ARTIFACT"


def test_unknown_mission_is_refused(context: tuple[VolumeChangeStore, str]) -> None:
    store, job_id = context
    response = _client(store).post(
        "/v1/missions/mission-does-not-exist/volume-changes", json=_payload(job_id)
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == "UNKNOWN_MISSION"


def test_same_id_with_different_content_is_refused(
    context: tuple[VolumeChangeStore, str],
) -> None:
    """[음성] 같은 id 로 다른 숫자를 덮어쓸 수 없다 — 원장은 append-only 다."""
    store, job_id = context
    client = _client(store)
    assert client.post(
        f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id)
    ).status_code == 201

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id, fill=999.0)
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "DUPLICATE_REPORT_ID"


def test_identical_resubmission_is_idempotent(
    context: tuple[VolumeChangeStore, str],
) -> None:
    """같은 내용의 재전송은 성공이다 — 네트워크 재시도가 409 를 받으면 안 된다."""
    store, job_id = context
    client = _client(store)
    first = client.post(f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id))
    second = client.post(f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id))

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["verdict"] == "RECORDED"


def test_humans_cannot_submit(context: tuple[VolumeChangeStore, str]) -> None:
    """[핵심 음성] 사람은 체적을 원장에 주장할 수 없다."""
    store, job_id = context
    response = _client(store, token=_VIEWER_TOKEN).post(
        f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id)
    )
    assert response.status_code == 403


def test_missing_report_is_404_not_an_empty_list(
    context: tuple[VolumeChangeStore, str],
) -> None:
    """[음성] '아직 계산 안 됨'과 '변화 없음'을 구분한다."""
    store, _job_id = context
    response = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/missions/{_MISSION_ID}/volume-changes"
    )
    assert response.status_code == 404


def test_self_comparison_is_refused_by_the_contract(
    context: tuple[VolumeChangeStore, str],
) -> None:
    """자기 자신과의 차분은 계약 모델이 막는다(422 — 요청 검증 단계)."""
    store, job_id = context
    payload = _payload(job_id, current_artifact="dsm-baseline")
    response = _client(store).post(f"/v1/missions/{_MISSION_ID}/volume-changes", json=payload)
    assert response.status_code == 422


def test_replay_reproduces_the_ledger(tmp_path: Path) -> None:
    """재기동 후에도 같은 리포트가 복원된다."""
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(
        jobs, _artifact_spec("dsm-baseline"), _artifact_spec("dsm-current")
    )
    journal_path = tmp_path / "volume-changes.jsonl"
    journal = DurableJournal(journal_path)
    first = VolumeChangeStore(
        journal, mission_store=missions, processing_job_store=jobs
    )
    assert _client(first).post(
        f"/v1/missions/{_MISSION_ID}/volume-changes", json=_payload(job_id)
    ).status_code == 201
    # journal 은 단일 writer 잠금이라 재기동 전에 닫아야 한다.
    journal.close()

    revived = VolumeChangeStore(
        DurableJournal(journal_path), mission_store=missions, processing_job_store=jobs
    )
    latest = revived.latest(_MISSION_ID)
    assert latest is not None
    assert latest.report.total_net_m3 == pytest.approx(70.0)


def test_replay_refuses_a_report_whose_artifact_was_never_registered(
    tmp_path: Path,
) -> None:
    """[핵심 음성] journal 을 손대 해석 불가능한 리포트를 되살리지 못한다.

    재생이 live 보다 관대하면 원장 조작이 곧 검증 우회가 된다.
    """
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    _job_with_artifacts(jobs, _artifact_spec("dsm-baseline"), _artifact_spec("dsm-current"))

    journal_path = tmp_path / "volume-changes.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "volume-change-recorded",
                "ts": _NOW.isoformat(),
                "missionId": _MISSION_ID,
                "reportedBy": "worker-1",
                "report": _payload("job-that-never-existed"),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(VolumeChangeRecoveryError, match="UNKNOWN_ARTIFACT"):
        VolumeChangeStore(
            DurableJournal(journal_path),
            mission_store=missions,
            processing_job_store=jobs,
        )

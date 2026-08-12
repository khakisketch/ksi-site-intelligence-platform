"""설계 대비 잔량 **리포트** 원장 계약 — 이 milestone 의 신뢰 경계 (M4-A 7단계).

지켜야 하는 불변식은 한 문장이고, 이 파일은 그것만 본다:

    **원장에 있는 모든 설계 대비 리포트에 대해, 그 ``diffRaster.digest`` 로
    스토리지 바이트를 다시 읽어 해싱하면 항상 같다.**

그래서 초점 넷:

**(a) 정상 제출** — Core 가 바이트를 직접 재해싱해 확인하고, 원장에 남는 digest 는
그 재계산 값이다(워커의 신고를 옮겨 적은 것이 아니다).

**(b) 거짓 신고** — 워커가 실제로 올린 바이트와 다른 digest 를 리포트에 주장하면
``FAILED`` + ``DIFF_RASTER_DIGEST_MISMATCH`` 이고 **리포트는 원장에 없다**. 두
경로(확인 기록과 어긋남 / 확인 뒤 바이트가 바뀜)가 모두 같은 결말로 수렴한다.

**(c) 재시도** — 같은 requestId 의 두 번째 업로드는 같은 객체 키를 덮어쓴다.

**(d) 전수 불변식** — 조회 가능한 모든 리포트에 대해 storage 바이트를 다시 읽어
재계산한 sha256 이 항상 일치한다.

픽스처는 ``test_design_conformance_requests.py`` 의 것을 그대로 쓴다 — 설계면은
실제로 VERIFIED 까지, 처리 작업은 실제로 SUCCEEDED 까지 진행된 상태다.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_change_detection.diff_raster import sha256_of_file  # noqa: E402
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_reports import (
    DesignConformanceRecoveryError,
    DesignConformanceStore,
    DesignConformanceVerdict,
    mount_design_conformance_reports,
)
from ksi_core.design_conformance_requests import (
    DesignConformanceRequestRecord,
    DesignConformanceRequestVerdict,
    build_design_conformance_raster_object_key,
    mount_design_conformance_requests,
    recompute_diff_raster_digest,
)
from ksi_core.design_surfaces import build_design_surface_object_key
from ksi_core.durable_journal import DurableJournal
from ksi_core.processing_jobs import (
    ProcessingJobStatus,
    build_processing_artifact_object_key,
)
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from ksi_processing_controller.core_client import HttpCoreClient
from ksi_processing_controller.design_conformance_worker import (
    run_design_conformance_request,
)
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _SITE_ID,
    _VIEWER_TOKEN,
    _WORKER_TOKEN,
    _registry,
)
from test_design_conformance_compute import (  # noqa: E402
    _CRS,
    _EXPECTED_CUT_M3,
    _EXPECTED_FILL_M3,
    _flat,
    _full_extent_zone,
    _ramp,
    _write_raster,
)
from test_design_conformance_requests import (  # noqa: E402
    _RASTER_BYTES,
    _RASTER_DIGEST,
    Fixture,
)

_PIPELINE_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="현재 DSM 과 설계면의 표고차 격자 — 실측된 현재 DSM 의 기준을 승계한다",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


class ReportFixture:
    """요청 픽스처 + 리포트 원장 — 워커가 하는 일(업로드·확인·제출)을 그대로 흉내 낸다."""

    def __init__(self, tmp_path: Path) -> None:
        self.base = Fixture(tmp_path)
        self.tmp_path = tmp_path
        self.report_journal = DurableJournal(tmp_path / "design-conformance.jsonl")
        self.reports = DesignConformanceStore(
            self.report_journal,
            mission_store=self.base.missions,
            processing_job_store=self.base.jobs,
            request_store=self.base.requests,
            storage=self.base.storage,
        )

    # ── 워커 흉내 ────────────────────────────────────────────────────────

    def prepared(
        self, *, raster: bytes = _RASTER_BYTES
    ) -> tuple[DesignConformanceRequestRecord, datetime]:
        """요청 생성 → lease → RUNNING → 래스터 업로드 → **Core 확인**까지."""
        record = self.base.created()
        self.base.leased(record.request_id)
        self.base.running(record.request_id)
        object_key = self.base.upload_raster(record, raster)
        digest, size = recompute_diff_raster_digest(self.base.storage, object_key)
        result = self.base.requests.record_diff_raster_verification(
            record.request_id,
            digest=digest,
            size_bytes=size,
            worker_id="worker-1",
            now=datetime.now(UTC),
        )
        assert result.verdict is DesignConformanceRequestVerdict.DIFF_RASTER_VERIFIED
        assert result.record is not None and result.record.diff_raster is not None
        return result.record, result.record.diff_raster.verified_at

    def app(self) -> FastAPI:
        app = FastAPI()
        mount_auth(app, _registry())
        mount_design_conformance_reports(app, self.reports, self.base.storage)
        return app

    def close(self) -> None:
        self.report_journal.close()
        self.base.close()


@pytest.fixture
def fixture(tmp_path: Path) -> ReportFixture:
    return ReportFixture(tmp_path)


def _report(
    record: DesignConformanceRequestRecord,
    verified_at: datetime,
    *,
    digest: str = _RASTER_DIGEST,
    size_bytes: int = len(_RASTER_BYTES),
    policy: ComparisonPolicy | None = None,
    design_surface_ref: DesignSurfaceRef | None = None,
    current: ArtifactRef | None = None,
) -> DesignConformanceReport:
    """워커가 제출하는 리포트 — 기본값은 **정직한** 값이고, 인자로 거짓을 넣는다."""
    used_policy = policy or record.policy
    threshold = used_policy.volume_threshold_m
    return DesignConformanceReport(
        design_conformance_id=record.design_conformance_id,
        design_surface_ref=design_surface_ref
        or DesignSurfaceRef(
            design_surface_id=record.design_surface_id,
            sha256=record.design_surface_sha256,
        ),
        current=current or record.current,
        crs="EPSG:5186",
        vertical_reference=_PIPELINE_VERTICAL,
        zones=[
            ZoneVolumeDelta(
                zone_id="zone-a",
                cut_m3=900.0,
                fill_m3=1100.0,
                net_m3=200.0,
                area_m2=400.0,
                threshold_m=threshold,
                uncertainty_m3=None,
                uncertainty_note="설계면은 측정물이 아니라 의도라서 검사점 RMSE 가 없다",
            )
        ],
        policy=used_policy,
        diff_raster=DiffRasterRef(
            diff_raster_id=record.diff_raster_id,
            digest=digest,
            crs="EPSG:5186",
            vertical_reference=_PIPELINE_VERTICAL,
            width=20,
            height=20,
            pixel_size_x_m=1.0,
            pixel_size_y_m=1.0,
            transform=(1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0),
            threshold_m=threshold,
            size_bytes=size_bytes,
            core_verified_digest_at=verified_at,
        ),
        computed_at=datetime.now(UTC),
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── (a) 정상 제출 ─────────────────────────────────────────────────────────


def test_honest_submission_is_recorded_with_the_digest_core_recomputed(
    fixture: ReportFixture,
) -> None:
    """[(a)] Core 가 바이트에서 직접 계산한 digest 가 원장에 남는다."""
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)

    outcome = fixture.reports.record(
        _CURRENT_MISSION_ID, report, now=datetime.now(UTC), reported_by="worker-1"
    )
    assert outcome.verdict is DesignConformanceVerdict.RECORDED, outcome

    entry = fixture.reports.get(_CURRENT_MISSION_ID, record.design_conformance_id)
    assert entry is not None
    # 워커가 신고한 값을 옮겨 적은 것이 아니라, Core 가 스토리지에서 잰 값이다.
    assert entry.core_recomputed_digest == _RASTER_DIGEST
    assert entry.report.diff_raster.digest == entry.core_recomputed_digest
    assert entry.report.total_net_m3 == pytest.approx(200.0)
    # 요청은 아직 RUNNING 이다 — SUCCEEDED 전이는 워커의 다음 호출이다.
    still = fixture.base.requests.get(record.request_id)
    assert still is not None and still.status is ProcessingJobStatus.RUNNING


def test_resubmitting_the_same_report_is_idempotent(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    again = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert again.verdict is DesignConformanceVerdict.RECORDED
    assert again.detail is not None and "멱등" in again.detail
    assert len(fixture.reports.history(_CURRENT_MISSION_ID)) == 1


# ── (b) 거짓 신고 — 두 경로 모두 FAILED 로 수렴하고 원장에 남지 않는다 ────


def test_lying_about_the_digest_fails_the_request_and_records_nothing(
    fixture: ReportFixture,
) -> None:
    """[(b) 핵심] 리포트가 Core 의 확인 기록과 다른 digest 를 주장하면 기록되지 않는다."""
    record, verified_at = fixture.prepared()
    lie = _report(record, verified_at, digest=f"sha256:{'c' * 64}")

    outcome = fixture.reports.record(
        _CURRENT_MISSION_ID, lie, now=datetime.now(UTC), reported_by="worker-1"
    )
    assert outcome.verdict is DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH

    # 원장에 없다 — 조회로도 잡히지 않는다.
    assert fixture.reports.get(_CURRENT_MISSION_ID, record.design_conformance_id) is None
    assert fixture.reports.history(_CURRENT_MISSION_ID) == []
    # 요청은 FAILED 로 끝났다(사유가 typed verdict 를 담는다).
    failed = fixture.base.requests.get(record.request_id)
    assert failed is not None
    assert failed.status is ProcessingJobStatus.FAILED
    assert failed.detail is not None
    assert failed.detail.startswith("DIFF_RASTER_DIGEST_MISMATCH")


def test_bytes_swapped_after_verification_are_caught_at_record_time(
    fixture: ReportFixture,
) -> None:
    """[(b) 두 번째 경로] 확인 뒤 객체가 다른 바이트로 덮여도 기록 시점에 걸린다.

    이 창이 리포트 수신 경로가 **한 번 더** 재해싱하는 이유 전부다 — 요청 쪽
    확인만 믿으면 그 사이의 교체를 아무도 보지 못한다.
    """
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    # 확인은 끝났고 리포트도 그 확인과 일치한다. 그런데 바이트가 바뀐다.
    fixture.base.upload_raster(record, b"tampered-bytes")

    outcome = fixture.reports.record(
        _CURRENT_MISSION_ID, report, now=datetime.now(UTC), reported_by="worker-1"
    )
    assert outcome.verdict is DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH
    assert outcome.detail is not None and "직접 다시 해싱" in outcome.detail
    assert fixture.reports.history(_CURRENT_MISSION_ID) == []
    failed = fixture.base.requests.get(record.request_id)
    assert failed is not None and failed.status is ProcessingJobStatus.FAILED


def test_report_without_any_core_verification_is_refused(fixture: ReportFixture) -> None:
    """확인 단계를 건너뛰고 리포트만 올리는 경로는 없다."""
    record = fixture.base.created()
    fixture.base.leased(record.request_id)
    fixture.base.running(record.request_id)
    fixture.base.upload_raster(record)
    report = _report(record, datetime.now(UTC))

    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED
    assert fixture.reports.history(_CURRENT_MISSION_ID) == []


def test_invented_verification_timestamp_is_refused(fixture: ReportFixture) -> None:
    """``coreVerifiedDigestAt`` 은 워커가 적어 넣는 값이 아니다."""
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at + timedelta(seconds=1))
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED


def test_missing_object_at_record_time_is_refused(fixture: ReportFixture) -> None:
    """스토리지가 흔들려도 '지도가 없는 잔량 리포트'를 남기지 않는다."""
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    fixture.base.storage.fail_get = True
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.DIFF_RASTER_UNREADABLE
    assert fixture.reports.history(_CURRENT_MISSION_ID) == []


# ── 요청과의 대조 (원장끼리) ──────────────────────────────────────────────


def test_report_pointing_at_another_design_surface_is_refused(
    fixture: ReportFixture,
) -> None:
    record, verified_at = fixture.prepared()
    report = _report(
        record,
        verified_at,
        design_surface_ref=DesignSurfaceRef(
            design_surface_id=record.design_surface_id, sha256="d" * 64
        ),
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.DESIGN_SURFACE_MISMATCH


def test_report_pointing_at_another_artifact_is_refused(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    report = _report(
        record,
        verified_at,
        current=ArtifactRef(job_id=record.current.job_id, artifact_id="point-cloud"),
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.ARTIFACT_MISMATCH


def test_report_computed_with_another_policy_is_refused(fixture: ReportFixture) -> None:
    """화면이 표시하는 기준과 실제로 쓴 기준이 갈리면 안 된다."""
    record, verified_at = fixture.prepared()
    other_policy = record.policy.model_copy(
        update={"volume_threshold_m": record.policy.volume_threshold_m + 0.05}
    )
    report = _report(record, verified_at, policy=other_policy)
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.POLICY_MISMATCH


def test_report_without_a_request_is_refused(fixture: ReportFixture) -> None:
    """지시 없이 만들어진 결과는 받지 않는다."""
    record, verified_at = fixture.prepared()
    orphan = _report(record, verified_at).model_copy(
        update={"design_conformance_id": "mission-cmp-current-dcf999"}
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, orphan, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.UNKNOWN_REQUEST


def test_report_submitted_to_another_mission_is_refused(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    outcome = fixture.reports.record(
        "mission-cmp-baseline", report, now=datetime.now(UTC)
    )
    assert outcome.verdict is DesignConformanceVerdict.REQUEST_MISMATCH


def test_same_id_with_different_content_is_refused(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    first = _report(record, verified_at)
    assert (
        fixture.reports.record(_CURRENT_MISSION_ID, first, now=datetime.now(UTC)).verdict
        is DesignConformanceVerdict.RECORDED
    )
    second = first.model_copy(update={"computed_at": datetime.now(UTC) + timedelta(hours=1)})
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, second, now=datetime.now(UTC))
    assert outcome.verdict is DesignConformanceVerdict.DUPLICATE_REPORT_ID


# ── (c) 재시도 멱등 + (d) 전수 불변식 ─────────────────────────────────────


def test_retry_overwrites_the_same_object_key(fixture: ReportFixture) -> None:
    """[(c)] 두 번째 시도가 같은 자리를 덮어쓴다 — orphan 이 쌓이지 않는다."""
    record = fixture.base.created()
    fixture.base.leased(record.request_id)
    first_key = fixture.base.upload_raster(record, b"first-attempt-bytes")
    second_key = fixture.base.upload_raster(record, _RASTER_BYTES)
    assert first_key == second_key
    assert set(fixture.base.storage.blobs) == {first_key}
    assert first_key == build_design_conformance_raster_object_key(
        site_id=record.site_id, design_conformance_id=record.design_conformance_id
    )


def test_every_recorded_report_still_matches_its_stored_bytes(
    fixture: ReportFixture,
) -> None:
    """[(d) 불변식] 조회 가능한 모든 리포트 × 스토리지 재해싱 = 항상 일치.

    거짓 신고·바이트 교체·확인 누락을 섞어 제출한 뒤 **원장에 남은 것 전부**를
    훑는다 — 하나라도 어긋나면 지도와 숫자가 갈라진 상태가 존재한다는 뜻이다.
    """
    honest_record, verified_at = fixture.prepared()
    fixture.reports.record(
        _CURRENT_MISSION_ID, _report(honest_record, verified_at), now=datetime.now(UTC)
    )

    # 두 번째 요청: 거짓 digest 를 주장한다(기록되지 않아야 한다).
    other_zones = {"zone-b": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]}}
    liar = fixture.base.created(zones=other_zones)
    fixture.base.leased(liar.request_id)
    fixture.base.running(liar.request_id)
    fixture.base.upload_raster(liar, b"second-request-bytes")
    digest, size = recompute_diff_raster_digest(
        fixture.base.storage,
        build_design_conformance_raster_object_key(
            site_id=liar.site_id, design_conformance_id=liar.design_conformance_id
        ),
    )
    verification = fixture.base.requests.record_diff_raster_verification(
        liar.request_id,
        digest=digest,
        size_bytes=size,
        worker_id="worker-1",
        now=datetime.now(UTC),
    )
    assert verification.record is not None and verification.record.diff_raster is not None
    fixture.reports.record(
        _CURRENT_MISSION_ID,
        _report(
            dataclass_replace(liar, diff_raster=verification.record.diff_raster),
            verification.record.diff_raster.verified_at,
            digest=f"sha256:{'e' * 64}",
            size_bytes=size,
        ),
        now=datetime.now(UTC),
    )

    entries = fixture.reports.history(_CURRENT_MISSION_ID)
    assert [e.report.design_conformance_id for e in entries] == [
        honest_record.design_conformance_id
    ]
    for entry in entries:
        object_key = fixture.reports.diff_raster_object_key(entry)
        assert object_key is not None
        recomputed, size_bytes = recompute_diff_raster_digest(
            fixture.base.storage, object_key
        )
        assert recomputed == entry.report.diff_raster.digest, entry.report.design_conformance_id
        assert size_bytes == entry.report.diff_raster.size_bytes
        assert recomputed == entry.core_recomputed_digest


# ── HTTP 표면 ─────────────────────────────────────────────────────────────


def test_http_submit_read_and_diff_raster_url(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    client = TestClient(fixture.app())

    submitted = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
        json=report.model_dump(by_alias=True, mode="json"),
        headers=_auth(_WORKER_TOKEN),
    )
    assert submitted.status_code == 201, submitted.json()
    assert submitted.json()["verdict"] == "RECORDED"

    listed = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["reportCount"] == 1
    assert body["latestTotalNetM3"] == pytest.approx(200.0)
    assert body["reports"][0]["coreRecomputedDigest"] == _RASTER_DIGEST

    raster = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/"
        f"{record.design_conformance_id}/diff-raster",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert raster.status_code == 200, raster.json()
    assert raster.json()["digest"] == _RASTER_DIGEST
    assert record.design_conformance_id in raster.json()["downloadUrl"]


def test_http_rejects_a_lying_report_with_422_and_keeps_the_ledger_empty(
    fixture: ReportFixture,
) -> None:
    record, verified_at = fixture.prepared()
    lie = _report(record, verified_at, digest=f"sha256:{'f' * 64}")
    client = TestClient(fixture.app())
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
        json=lie.model_dump(by_alias=True, mode="json"),
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "DIFF_RASTER_DIGEST_MISMATCH"
    assert (
        client.get(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 404
    )


def test_people_cannot_submit_and_workers_cannot_read(fixture: ReportFixture) -> None:
    """사람은 잔량을 주장할 수 없고, 워커는 남의 임무 결과를 읽지 않는다."""
    record, verified_at = fixture.prepared()
    report = _report(record, verified_at)
    client = TestClient(fixture.app())
    assert (
        client.post(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
            json=report.model_dump(by_alias=True, mode="json"),
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
            headers=_auth(_WORKER_TOKEN),
        ).status_code
        == 403
    )


def test_missing_history_is_404_not_an_empty_list(fixture: ReportFixture) -> None:
    """"아직 계산 안 됨"과 "잔량이 0"을 소비자가 구분할 수 있어야 한다."""
    client = TestClient(fixture.app())
    assert (
        client.get(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance",
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 404
    )


# ── 재생 ──────────────────────────────────────────────────────────────────


def _reopen(fixture: ReportFixture) -> DesignConformanceStore:
    """리포트 원장을 다시 연다 — 요청 원장은 그대로 살아 있어야 재대조가 가능하다."""
    fixture.report_journal.close()
    return DesignConformanceStore(
        DurableJournal(fixture.tmp_path / "design-conformance.jsonl"),
        mission_store=fixture.base.missions,
        processing_job_store=fixture.base.jobs,
        request_store=fixture.base.requests,
        storage=fixture.base.storage,
    )


def test_replay_restores_recorded_reports_and_skips_rejections(
    fixture: ReportFixture,
) -> None:
    record, verified_at = fixture.prepared()
    fixture.reports.record(
        _CURRENT_MISSION_ID,
        _report(record, verified_at, digest=f"sha256:{'a' * 64}"),
        now=datetime.now(UTC),
    )
    fixture.reports.record(
        _CURRENT_MISSION_ID, _report(record, verified_at), now=datetime.now(UTC)
    )

    replayed = _reopen(fixture)
    entries = replayed.history(_CURRENT_MISSION_ID)
    assert [e.report.design_conformance_id for e in entries] == [
        record.design_conformance_id
    ]
    assert entries[0].core_recomputed_digest == _RASTER_DIGEST


def test_replay_refuses_a_record_whose_core_digest_was_forged(
    fixture: ReportFixture,
) -> None:
    """"Core 가 확인했다"를 손으로 심어도 재생이 리포트와 대조해 잡는다."""
    record, verified_at = fixture.prepared()
    fixture.reports.record(
        _CURRENT_MISSION_ID, _report(record, verified_at), now=datetime.now(UTC)
    )
    path = fixture.tmp_path / "design-conformance.jsonl"
    # journal 은 compact JSON 이다(``separators=(",", ":")``) — 공백을 넣으면
    # 치환이 조용히 아무것도 안 바꾸고 테스트가 거짓 green 이 된다.
    forged = path.read_text(encoding="utf-8").replace(
        f'"coreRecomputedDigest":"{_RASTER_DIGEST}"',
        f'"coreRecomputedDigest":"sha256:{"0" * 64}"',
    )
    assert forged != path.read_text(encoding="utf-8"), "치환이 아무것도 바꾸지 않았다"
    path.write_text(forged, encoding="utf-8")
    with pytest.raises(DesignConformanceRecoveryError, match="재해싱 digest"):
        _reopen(fixture)


def test_replay_refuses_a_report_whose_request_no_longer_backs_it(
    fixture: ReportFixture, tmp_path: Path
) -> None:
    """요청 원장과 어긋나는 리포트는 기동을 막는다(재생도 같은 판정을 다시 태운다)."""
    record, verified_at = fixture.prepared()
    fixture.reports.record(
        _CURRENT_MISSION_ID, _report(record, verified_at), now=datetime.now(UTC)
    )
    path = fixture.tmp_path / "design-conformance.jsonl"
    forged = path.read_text(encoding="utf-8").replace(
        record.design_surface_sha256, "9" * 64
    )
    path.write_text(forged, encoding="utf-8")
    with pytest.raises(DesignConformanceRecoveryError, match="기록될 수 없는 리포트"):
        _reopen(fixture)


def test_replay_refuses_unknown_record_kinds(fixture: ReportFixture) -> None:
    record, verified_at = fixture.prepared()
    fixture.reports.record(
        _CURRENT_MISSION_ID, _report(record, verified_at), now=datetime.now(UTC)
    )
    path = fixture.tmp_path / "design-conformance.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "made-up", "missionId": "x"}\n')
    with pytest.raises(DesignConformanceRecoveryError, match="알 수 없는 journal"):
        _reopen(fixture)


# ── 종단: 사람이 요청하고 **진짜 워커**가 진짜 Core 라우터를 통해 완주한다 ──────
#
# 여기까지가 "green≠작동"의 마지막 칸이다. 위 시험들은 store 를 직접 부르지만,
# 이 시험은 ① 사람이 HTTP 로 요청을 만들고 ② 프로덕션과 같은 ``HttpCoreClient``
# 를 쓴 워커가 ③ 실제 GeoTIFF 를 내려받아 계산하고 ④ presigned PUT 으로 올리고
# ⑤ Core 가 그 바이트를 다시 해싱해 확인하고 ⑥ 리포트가 원장에 굳고 ⑦ 지도가
# 그 래스터를 받아가는 전 경로를 한 번에 지난다.


def _storage_transport(storage: Any) -> httpx.MockTransport:
    """presigned URL 규약(``/get/{objectKey}``·``/put/{objectKey}``)을 그대로 흉내 낸다."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "PUT":
            storage.put_bytes(
                path.split("/put/", 1)[1], request.content,
                content_type="application/octet-stream",
            )
            return httpx.Response(200)
        try:
            return httpx.Response(200, content=storage.get_bytes(path.split("/get/", 1)[1]))
        except Exception:  # noqa: BLE001 -- 없는 키는 404 로(스토리지와 같은 모양)
            return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_end_to_end_human_request_worker_run_and_map_download(tmp_path: Path) -> None:
    """[종단] 요청 → 워커 계산·업로드 → Core 재해싱 확인 → 리포트 → 지도 래스터."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")

    base = Fixture(tmp_path, design_sha256=design_sha)
    # 스토리지에 두 입력의 **진짜 바이트**를 서버가 정한 자리에 둔다.
    base.storage.put_bytes(
        build_design_surface_object_key(
            site_id=base.sites.get(_SITE_ID).site_id,  # type: ignore[union-attr]
            design_surface_id=base.design_surface_id,
        ),
        design_path.read_bytes(),
        content_type="application/octet-stream",
    )
    base.storage.put_bytes(
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=base.current_job_id, artifact_id="dsm"
        ),
        current_path.read_bytes(),
        content_type="application/octet-stream",
    )
    reports = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance.jsonl"),
        mission_store=base.missions,
        processing_job_store=base.jobs,
        request_store=base.requests,
        storage=base.storage,
    )

    app = FastAPI()
    mount_auth(app, _registry())
    mount_design_conformance_requests(app, base.requests, base.storage)
    mount_design_conformance_reports(app, reports, base.storage)

    # ① 사람이 요청을 만든다(MISSIONS_ISSUE).
    human = TestClient(app)
    human.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    created = human.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": base.design_surface_id,
            "currentJobId": base.current_job_id,
            "zones": {"zone-all": _full_extent_zone()},
            "zoneCrs": _CRS,
        },
    )
    assert created.status_code == 201, created.json()
    request_id = created.json()["request"]["requestId"]

    # ② 프로덕션과 같은 HttpCoreClient — TestClient 가 동기↔ASGI 브리지다
    # (test_comparison_requests.py 의 종단 시험과 같은 관용구).
    worker_http = TestClient(app)
    core_client = HttpCoreClient("http://core.test", token=_WORKER_TOKEN, client=worker_http)
    storage_http = httpx.Client(transport=_storage_transport(base.storage))
    try:
        run_design_conformance_request(
            request_id, core=core_client, work_dir=tmp_path / "work",
            http_client=storage_http, now_message=lambda _msg: None,
        )
    finally:
        storage_http.close()

    # ③ 요청은 SUCCEEDED, 리포트는 원장에, 숫자는 손계산과 같다.
    listed = human.get(f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance")
    assert listed.status_code == 200, listed.json()
    report_body = listed.json()["reports"][0]["report"]
    assert report_body["designConformanceId"] == request_id
    zone = report_body["zones"][0]
    assert zone["fillM3"] == pytest.approx(_EXPECTED_FILL_M3)
    assert zone["cutM3"] == pytest.approx(_EXPECTED_CUT_M3)
    assert zone["uncertaintyM3"] is None

    final_request = base.requests.get(request_id)
    assert final_request is not None
    assert final_request.status is ProcessingJobStatus.SUCCEEDED

    # ④ 지도가 받아가는 래스터는 원장의 digest 와 같은 바이트다(불변식).
    raster = human.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{request_id}/diff-raster"
    )
    assert raster.status_code == 200, raster.json()
    downloaded = storage_http_get(base.storage, raster.json()["downloadUrl"])
    assert f"sha256:{hashlib.sha256(downloaded).hexdigest()}" == report_body["diffRaster"]["digest"]
    assert len(downloaded) == report_body["diffRaster"]["sizeBytes"]


def storage_http_get(storage: Any, download_url: str) -> bytes:
    """열람 URL 이 가리키는 바이트 — 지도가 하는 일과 같다."""
    return storage.get_bytes(download_url.split("/get/", 1)[1])

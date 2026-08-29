"""워커 pull 루프 계약 (``ksi_processing_controller.runner``).

``run_job`` 자체의 오케스트레이션(lease→입력→실측→제출→등록→SUCCEEDED)은
``test_worker.py`` 가 이미 고정했다 — 이 파일은 그 **호출자**, 즉 "어떤 jobId 를
``run_job`` 에 넘길지"를 정하는 루프만 시험한다. 가짜 Core·가짜 NodeODM 은
``test_worker.py`` 것을 그대로 가져와 쓴다(같은 디렉토리 rootdir 수집이라
``test_dfine_detector.py`` 와 같은 관용구로 직접 import).

초점 셋:

1. **대기 목록의 후보를 순서대로 시도한다** — 앞선 후보가 lease 경합에 지면
   다음 후보로 넘어간다(``LEASE_HELD_BY_ANOTHER`` 는 이 워커의 실패가 아니다).
2. **Core 장애·개별 작업 실패가 워커 프로세스를 죽이지 않는다** — 로그만 남기고
   다음 라운드로 넘어간다.
3. **아무것도 못 돌렸을 때만 쉰다** — 돌린 게 있으면 밀린 작업이 더 있을 수
   있으니 바로 재폴링한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

# tests/contract 는 rootdir 기반 수집이라 같은 디렉토리 모듈을 직접 import 한다
# (test_dfine_detector.py 의 DetectorConformanceSuite 와 같은 관용구).
from ksi_change_detection.diff_raster import sha256_of_file
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_processing_controller.core_client import (
    ComparisonInput,
    CoreClientError,
    DesignConformanceInput,
    DesignSurfaceMeasurement,
    DiffRasterUploadTarget,
    PendingCheckpointValidation,
    PendingComparisonRequest,
    PendingDesignConformanceRequest,
    PendingDesignSurface,
    PendingJob,
    PendingRegionExtractionRequest,
    RegionExtractionInput,
)
from ksi_processing_controller.odm_masking import odm_mask_filename
from ksi_processing_controller.runner import run_forever, run_pending_batch
from test_comparison_worker import FakeComparisonCoreClient, _grid, _storage_transport, _write_laz
from test_design_conformance_compute import _flat, _ramp, _write_raster
from test_design_conformance_worker import FakeCore as FakeConformanceCore
from test_design_conformance_worker import _input as _conformance_input
from test_design_conformance_worker import _transport as _conformance_transport
from test_worker import (  # noqa: E402
    FakeNodeOdm,
    _FakeDetector,
    _person_result,
    _server_with_two_images,
    _worker_http_client,
)


@dataclass
class _PullableFakeCoreClient(FakeComparisonCoreClient):
    """``FakeComparisonCoreClient`` + ``list_pending``/``list_pending_comparisons``
    — 워커 루프(재구성 + 비교) 전용 확장.

    ``lease_conflict_for``/``comparison_lease_conflict_for`` 에 적힌 id 는
    ``LEASE_HELD_BY_ANOTHER`` 로 거부된다 — "다른 워커가 먼저 잡았다"를 흉내 낸다.
    """

    pending: list[PendingJob] = field(default_factory=list)
    lease_conflict_for: frozenset[str] = field(default_factory=frozenset)
    pending_comparisons: list[PendingComparisonRequest] = field(default_factory=list)
    comparison_lease_conflict_for: frozenset[str] = field(default_factory=frozenset)
    # M4-A — 설계면 검증·설계 대비 잔량 두 종류. 후자는 워커 시험의 가짜 Core
    # (``test_design_conformance_worker.FakeCore``)에 그대로 위임한다: 이 파일의
    # 관심사는 "어떤 순서로 무엇을 폴링하는가"이지 그 워커의 내부가 아니다.
    pending_design_surfaces: list[PendingDesignSurface] = field(default_factory=list)
    # Independent checkpoint validation is a short, terminal worker stage
    # between design-surface verification and comparison.  This pull-loop fake
    # keeps it empty unless a queue-order test explicitly supplies a candidate.
    pending_checkpoint_validations: list[PendingCheckpointValidation] = field(
        default_factory=list
    )
    pending_design_conformances: list[PendingDesignConformanceRequest] = field(
        default_factory=list
    )
    conformance: FakeConformanceCore | None = None
    # M4-E — 변화 영역 추출. 이 파일의 관심사는 폴링 순서이지 그 워커의 내부가
    # 아니므로, 기존 후보 넷과 같은 근거로 목록만 흉내 낸다(비어 있으면 아무
    # 일도 안 한다) — 나머지 메서드는 Protocol 충족용 스텁이다.
    pending_region_extractions: list[PendingRegionExtractionRequest] = field(
        default_factory=list
    )

    def list_pending_design_surfaces(
        self, *, limit: int = 50
    ) -> list[PendingDesignSurface]:
        return self.pending_design_surfaces[:limit]

    def report_design_surface_observation(
        self, design_surface_id: str, measurement: DesignSurfaceMeasurement
    ) -> str:
        self.calls.append(("ds-observation", design_surface_id, measurement.sha256))
        return "VERIFIED"

    def report_design_surface_verification_failure(
        self, design_surface_id: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("ds-verification-failure", design_surface_id, detail))

    def report_design_surface_normalization_failure(
        self, design_surface_id: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("ds-normalization-failure", design_surface_id, detail))

    def list_pending_checkpoint_validations(
        self, *, limit: int = 50
    ) -> list[PendingCheckpointValidation]:
        return self.pending_checkpoint_validations[:limit]

    def report_checkpoint_validation_observation(
        self, validation_id: str, measurement: Any
    ) -> str:  # pragma: no cover - exercised by dedicated validator tests
        self.calls.append(("checkpoint-observation", validation_id, measurement.rmse_m))
        return "VALIDATED"

    def report_checkpoint_validation_failure(
        self, validation_id: str, *, reason: str, detail: str | None = None
    ) -> str:  # pragma: no cover - exercised by dedicated validator tests
        self.calls.append(("checkpoint-failure", validation_id, reason, detail))
        return "REJECTED"

    def list_pending_design_conformances(
        self, *, limit: int = 50
    ) -> list[PendingDesignConformanceRequest]:
        return self.pending_design_conformances[:limit]

    def acquire_design_conformance_lease(self, request_id: str) -> None:
        self.calls.append(("dcf-lease", request_id))
        assert self.conformance is not None
        self.conformance.acquire_design_conformance_lease(request_id)

    def get_design_conformance_input(self, request_id: str) -> DesignConformanceInput:
        assert self.conformance is not None
        return self.conformance.get_design_conformance_input(request_id)

    def transition_design_conformance(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("dcf-transition", target, detail))
        assert self.conformance is not None
        self.conformance.transition_design_conformance(request_id, target, detail=detail)

    def presign_diff_raster_upload(self, request_id: str) -> DiffRasterUploadTarget:
        assert self.conformance is not None
        return self.conformance.presign_diff_raster_upload(request_id)

    def verify_diff_raster(self, request_id: str, *, digest: str, size_bytes: int) -> Any:
        assert self.conformance is not None
        return self.conformance.verify_diff_raster(
            request_id, digest=digest, size_bytes=size_bytes
        )

    def submit_design_conformance(self, mission_id: str, report: Any) -> None:
        self.calls.append(("dcf-submit", mission_id, report.design_conformance_id))
        assert self.conformance is not None
        self.conformance.submit_design_conformance(mission_id, report)

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        return self.pending[:limit]

    def acquire_lease(self, job_id: str) -> None:
        if job_id in self.lease_conflict_for:
            self.calls.append(("lease-conflict", job_id))
            raise CoreClientError(
                what="lease", verdict="LEASE_HELD_BY_ANOTHER", detail="다른 워커가 쥐고 있다"
            )
        super().acquire_lease(job_id)

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        return self.pending_comparisons[:limit]

    def acquire_comparison_lease(self, request_id: str) -> None:
        if request_id in self.comparison_lease_conflict_for:
            self.calls.append(("cmp-lease-conflict", request_id))
            raise CoreClientError(
                what="comparison-lease",
                verdict="LEASE_HELD_BY_ANOTHER",
                detail="다른 워커가 쥐고 있다",
            )
        super().acquire_comparison_lease(request_id)

    def list_pending_region_extractions(
        self, *, limit: int = 50
    ) -> list[PendingRegionExtractionRequest]:
        return self.pending_region_extractions[:limit]

    def acquire_region_extraction_lease(self, request_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_region_extraction_input(  # pragma: no cover
        self, request_id: str
    ) -> RegionExtractionInput:
        raise NotImplementedError

    def transition_region_extraction(  # pragma: no cover
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        raise NotImplementedError

    def submit_region_extraction(self, mission_id: str, report: Any) -> None:  # pragma: no cover
        raise NotImplementedError


def _core(**kwargs: Any) -> _PullableFakeCoreClient:
    return _PullableFakeCoreClient(**kwargs)


def _comparison_storage_client(tmp_path: Path) -> httpx.Client:
    """point_cloud 만 있는 비교 요청 실행용 최소 storage — 실제 .laz 를 서빙한다."""
    cloud = _grid(6)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())
    return httpx.Client(
        transport=_storage_transport({"baseline.laz": base_laz, "current.laz": curr_laz})
    )


def _comparison_input(request_id: str) -> ComparisonInput:
    return ComparisonInput(
        request_id=request_id,
        mission_id="mission-1",
        status="QUEUED",
        policy=current_comparison_policy(),
        point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
        point_cloud_baseline_url="http://fake-storage/baseline.laz",
        point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
        point_cloud_current_url="http://fake-storage/current.laz",
        dsm_baseline=None, dsm_baseline_url=None,
        dsm_current=None, dsm_current_url=None,
        zones=None, zone_crs=None,
    )


# ── run_pending_batch ───────────────────────────────────────────────────────


def test_runs_the_first_pending_candidate_to_completion(tmp_path: Path) -> None:
    core = _core(pending=[PendingJob(job_id="job-1")])
    server = _server_with_two_images()
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core,
        odm=odm,
        work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert any(c[0] == "transition" and c[1] == "SUCCEEDED" for c in core.calls)


def test_returns_false_when_nothing_is_pending(tmp_path: Path) -> None:
    core = _core(pending=[])
    odm = FakeNodeOdm()

    ran = run_pending_batch(core=core, odm=odm, work_dir=tmp_path)

    assert ran is False
    assert core.calls == []


def test_lease_conflict_moves_to_the_next_candidate(tmp_path: Path) -> None:
    """[핵심] 앞선 후보가 다른 워커에게 lease 를 뺏겨도 다음 후보를 시도한다."""
    core = _core(
        pending=[PendingJob(job_id="job-1"), PendingJob(job_id="job-2")],
        lease_conflict_for=frozenset({"job-1"}),
    )
    server = _server_with_two_images()
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core,
        odm=odm,
        work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert ("lease-conflict", "job-1") in core.calls
    # job-2 는 실제로 lease 를 잡고 진행됐다(정상 acquire_lease 호출 기록).
    assert ("lease", "job-2") in core.calls


def test_worker_run_error_counts_as_ran_and_does_not_propagate(tmp_path: Path) -> None:
    """[핵심] run_job 내부 실패(WorkerRunError)는 이 배치의 실패가 아니라 —
    Core 에 이미 FAILED 보고를 시도했으므로 "돌렸다"로 센다."""
    core = _core(pending=[PendingJob(job_id="job-1")])
    server = _server_with_two_images()
    # 엔진 버전이 어긋나게 만들어 run_job 내부에서 EngineIdentityMismatch →
    # WorkerRunError 로 이어지게 한다(test_worker.py 와 같은 유발 방식).
    odm = FakeNodeOdm(engine_version="9.9.9")

    ran = run_pending_batch(
        core=core,
        odm=odm,
        work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert any(c[0] == "transition" and c[1] == "FAILED" for c in core.calls)


def test_list_pending_failure_is_treated_as_no_work_not_a_crash(tmp_path: Path) -> None:
    """[핵심] Core 자체에 못 닿아도 워커 프로세스가 죽지 않는다 — 다음 폴링에서 재시도."""

    class _BrokenCore(_PullableFakeCoreClient):
        def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
            raise ConnectionError("core 에 닿지 못했다(테스트 강제)")

    core = _BrokenCore()
    odm = FakeNodeOdm()

    ran = run_pending_batch(core=core, odm=odm, work_dir=tmp_path)

    assert ran is False


def test_all_candidates_conflicted_returns_false(tmp_path: Path) -> None:
    """목록 전부가 다른 워커에게 뺏겼으면 이번 라운드는 아무것도 못 돌린 것이다."""
    core = _core(
        pending=[PendingJob(job_id="job-1"), PendingJob(job_id="job-2")],
        lease_conflict_for=frozenset({"job-1", "job-2"}),
    )
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path, now_message=lambda _msg: None
    )

    assert ran is False


# ── run_pending_batch: 비교 요청 후보(W2) ───────────────────────────────────


def test_falls_through_to_comparison_when_no_reconstruction_pending(tmp_path: Path) -> None:
    """[핵심] 재구성 후보가 없으면(빈 목록) 비교 요청 후보를 본다 — 새 프로세스가
    아니라 같은 폴링 라운드 안에서(모듈 docstring "왜 별도 데몬이 아닌가")."""
    core = _core(
        pending=[],  # 재구성 후보 없음
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
        comparison_input=_comparison_input("mission-1-cmp1"),
    )
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path,
        http_client=_comparison_storage_client(tmp_path),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert ("cmp-lease", "mission-1-cmp1") in core.calls
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert len(succeeded) == 1


def test_reconstruction_candidate_takes_priority_over_comparison(tmp_path: Path) -> None:
    """재구성 후보가 있으면 비교 후보는 아예 보지 않는다(우선순위, 모듈 docstring)."""
    core = _core(
        pending=[PendingJob(job_id="job-1")],
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
    )
    server = _server_with_two_images()
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert any(c[0] == "transition" and c[1] == "SUCCEEDED" for c in core.calls)
    assert not any(c[0].startswith("cmp-") for c in core.calls)


def test_comparison_lease_conflict_moves_to_the_next_candidate(tmp_path: Path) -> None:
    """[핵심] 비교 요청도 재구성과 동형으로 lease 경합 시 다음 후보로 넘어간다."""
    core = _core(
        pending=[],
        pending_comparisons=[
            PendingComparisonRequest(request_id="mission-1-cmp1"),
            PendingComparisonRequest(request_id="mission-1-cmp2"),
        ],
        comparison_lease_conflict_for=frozenset({"mission-1-cmp1"}),
        comparison_input=_comparison_input("mission-1-cmp2"),
    )
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path,
        http_client=_comparison_storage_client(tmp_path),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert ("cmp-lease-conflict", "mission-1-cmp1") in core.calls
    assert ("cmp-lease", "mission-1-cmp2") in core.calls


def test_comparison_worker_run_error_counts_as_ran_and_does_not_propagate(tmp_path: Path) -> None:
    """[핵심] 비교 실행 실패(ComparisonWorkerRunError)도 재구성과 동형으로 "돌렸다"로
    센다 — 이미 Core 에 FAILED 보고를 시도했다."""
    core = _core(
        pending=[],
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
        comparison_input=_comparison_input("mission-1-cmp1"),
    )
    odm = FakeNodeOdm()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)  # 다운로드 실패를 강제해 계산을 터뜨린다

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert any(c[0] == "cmp-transition" and c[1] == "FAILED" for c in core.calls)


def test_both_lists_empty_returns_false(tmp_path: Path) -> None:
    core = _core(pending=[], pending_comparisons=[])
    odm = FakeNodeOdm()

    ran = run_pending_batch(core=core, odm=odm, work_dir=tmp_path)

    assert ran is False


# ── run_pending_batch: 설계면 검증·설계 대비 잔량 후보(M4-A) ───────────────


def _design_surface_client(tmp_path: Path) -> httpx.Client:
    """검증 대상 설계면 GeoTIFF 를 실제로 서빙한다(rasterio 가 진짜로 연다)."""
    design_path = _write_raster(tmp_path / "pending-design.tif", _flat())
    return httpx.Client(transport=_storage_transport({"pending-design.tif": design_path}))


def _conformance_scene(tmp_path: Path) -> tuple[FakeConformanceCore, httpx.Client]:
    """설계 대비 워커가 끝까지 돌 수 있는 장면 — 워커 시험의 픽스처를 그대로 쓴다."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")
    conformance = FakeConformanceCore(conformance_input=_conformance_input(design_sha))
    client = httpx.Client(
        transport=_conformance_transport(
            conformance, {"current-dsm": current_path, "design": design_path}
        )
    )
    return conformance, client


def test_design_surface_verification_runs_before_comparison(tmp_path: Path) -> None:
    """[우선순위] 설계면 검증은 초 단위 작업이면서 요청 생성을 막고 있다 — 비교보다 앞이다."""
    core = _core(
        pending=[],
        pending_design_surfaces=[
            PendingDesignSurface(
                design_surface_id="site-1-ds1",
                site_id="site-1",
                download_url="http://fake-storage/pending-design.tif",
            )
        ],
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
    )

    ran = run_pending_batch(
        core=core,
        odm=FakeNodeOdm(),
        work_dir=tmp_path,
        http_client=_design_surface_client(tmp_path),
        now_message=lambda _msg: None,
    )

    assert ran is True
    # 실제로 파일을 열어 재고 보고했다 — 신고값을 되읊은 것이 아니다.
    observations = [c for c in core.calls if c[0] == "ds-observation"]
    assert len(observations) == 1 and len(observations[0][2]) == 64
    # 비교 후보는 아예 보지 않았다.
    assert not any(str(c[0]).startswith("cmp-") for c in core.calls)


def test_checkpoint_validation_runs_before_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server-computed checkpoint RMSE is available before any comparison runs."""
    import ksi_processing_controller.runner as runner_module

    candidate = PendingCheckpointValidation(
        validation_id="checkpoint-1",
        checkpoint_download_url="https://storage.test/checkpoints.csv",
        dsm_download_url="https://storage.test/dsm.tif",
        checkpoint_crs="EPSG:5186",
        checkpoint_vertical_reference=VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis="independent survey",
            source=VerticalReferenceSource.USER_DECLARED,
        ),
        dsm_crs="EPSG:5186",
        dsm_vertical_reference=VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis="ODM pipeline output",
            source=VerticalReferenceSource.PIPELINE_DECLARED,
        ),
    )
    core = _core(
        pending=[],
        pending_checkpoint_validations=[candidate],
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
    )
    called: list[str] = []

    def _validate(candidate: PendingCheckpointValidation, **_kwargs: Any) -> str:
        called.append(candidate.validation_id)
        return "VALIDATED"

    monkeypatch.setattr(runner_module, "validate_checkpoint_validation", _validate)
    assert run_pending_batch(core=core, odm=FakeNodeOdm(), work_dir=tmp_path) is True
    assert called == ["checkpoint-1"]
    assert not any(str(call[0]).startswith("cmp-") for call in core.calls)


def test_design_conformance_is_polled_last_and_runs_to_succeeded(tmp_path: Path) -> None:
    """[우선순위] 앞의 셋이 비어야 설계 대비 후보를 본다 — 그리고 끝까지 돈다."""
    conformance, client = _conformance_scene(tmp_path)
    core = _core(
        pending=[],
        pending_design_surfaces=[],
        pending_comparisons=[],
        pending_design_conformances=[
            PendingDesignConformanceRequest(request_id="mission-1-dcf1")
        ],
        conformance=conformance,
    )

    ran = run_pending_batch(
        core=core, odm=FakeNodeOdm(), work_dir=tmp_path, http_client=client,
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert conformance.status == "SUCCEEDED"
    assert [m for m, _r in conformance.submitted] == ["mission-1"]
    assert ("dcf-lease", "mission-1-dcf1") in core.calls


def test_comparison_candidate_takes_priority_over_design_conformance(tmp_path: Path) -> None:
    """기존 경로(M1/M2)의 지연 특성을 새 기능이 밀어내지 않는다."""
    conformance, _client = _conformance_scene(tmp_path)
    core = _core(
        pending=[],
        pending_comparisons=[PendingComparisonRequest(request_id="mission-1-cmp1")],
        comparison_input=_comparison_input("mission-1-cmp1"),
        pending_design_conformances=[
            PendingDesignConformanceRequest(request_id="mission-1-dcf1")
        ],
        conformance=conformance,
    )

    ran = run_pending_batch(
        core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        http_client=_comparison_storage_client(tmp_path),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert any(c[0] == "cmp-transition" and c[1] == "SUCCEEDED" for c in core.calls)
    assert not any(str(c[0]).startswith("dcf-") for c in core.calls)


def test_design_conformance_run_error_counts_as_ran(tmp_path: Path) -> None:
    """Core 가 래스터 확인을 거부하면 워커가 FAILED 로 끝낸다 — "돌렸다"로 센다."""
    conformance, client = _conformance_scene(tmp_path)
    # 업로드된 것과 다른 바이트가 그 자리에 있다고 Core 가 판정한다.
    conformance.swap_uploaded_with = b"someone-else-wrote-here"
    core = _core(
        pending=[],
        pending_design_conformances=[
            PendingDesignConformanceRequest(request_id="mission-1-dcf1")
        ],
        conformance=conformance,
    )

    ran = run_pending_batch(
        core=core, odm=FakeNodeOdm(), work_dir=tmp_path, http_client=client,
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert conformance.status == "FAILED"
    assert conformance.submitted == []


def test_all_six_lists_empty_returns_false(tmp_path: Path) -> None:
    core = _core(
        pending=[],
        pending_design_surfaces=[],
        pending_comparisons=[],
        pending_design_conformances=[],
    )
    assert run_pending_batch(core=core, odm=FakeNodeOdm(), work_dir=tmp_path) is False


# ── run_forever ──────────────────────────────────────────────────────────


def test_run_forever_stops_immediately_without_running_anything(tmp_path: Path) -> None:
    sleep_calls: list[float] = []

    run_forever(
        core=_core(),
        odm=FakeNodeOdm(),
        work_dir=tmp_path,
        should_stop=lambda: True,
        sleep=sleep_calls.append,
    )

    assert sleep_calls == []


def test_run_forever_sleeps_only_on_idle_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """돌린 라운드 뒤에는 바로 재폴링하고, 못 돌린 라운드에서만 쉰다."""
    import ksi_processing_controller.runner as runner_module

    results = iter([True, False, False])  # 돌림 · 쉼 · 쉼
    monkeypatch.setattr(runner_module, "run_pending_batch", lambda **_kw: next(results))

    checks = {"n": 0}

    def should_stop() -> bool:
        checks["n"] += 1
        return checks["n"] > 3

    sleep_calls: list[float] = []
    run_forever(
        core=_core(),
        odm=FakeNodeOdm(),
        work_dir=tmp_path,
        poll_interval_seconds=2.5,
        should_stop=should_stop,
        sleep=sleep_calls.append,
    )

    assert sleep_calls == [2.5, 2.5]


# ── 동적 객체 마스킹 배선(PRD §15.2 ④) — run_pending_batch/run_forever/main ──
#
# 오늘 세 번째로 발견된 패턴이었다(지오이드 격자 자동변환·IFC 설계면 변환에
# 이어): worker.py::run_job 은 dynamic_object_detector 를 이미 받는데, 그
# 인자를 채워 넘기는 호출자가 프로덕션 폴링 경로(run_pending_batch·run_forever·
# main)에 없어 컨테이너로 띄운 워커는 한 번도 마스킹을 하지 않았다. 아래는
# "주입한 stub 감지기가 실제로 run_job 까지 전달돼 마스크 파일을 만드는가"를
# mock 호출 여부가 아니라 odm.submitted_masks 실물로 확인한다.


def test_run_pending_batch_wires_detector_into_reconstruction_and_masks_are_submitted(
    tmp_path: Path,
) -> None:
    """[핵심] run_pending_batch(dynamic_object_detector=...) 가 run_job 까지 실제로
    닿아 마스크 파일을 만든다 — 주입만 받고 안 쓰이는 회귀를 막는다."""
    core = _core(pending=[PendingJob(job_id="job-1")])
    server = _server_with_two_images()
    odm = FakeNodeOdm()
    detector = _FakeDetector([_person_result(), _person_result()])

    ran = run_pending_batch(
        core=core,
        odm=odm,
        work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
        dynamic_object_detector=detector,
    )

    assert ran is True
    assert detector.calls == 2, "사진 2장 모두 실제로 탐지를 거쳤다"
    assert {m.filename for m in odm.submitted_masks} == {
        odm_mask_filename("img-1.png"),
        odm_mask_filename("img-2.png"),
    }


def test_run_pending_batch_defaults_to_no_masking(tmp_path: Path) -> None:
    """[회귀] dynamic_object_detector 를 생략하면(기본) 지금까지와 동일하게
    마스킹 없이 동작한다."""
    core = _core(pending=[PendingJob(job_id="job-1")])
    server = _server_with_two_images()
    odm = FakeNodeOdm()

    ran = run_pending_batch(
        core=core, odm=odm, work_dir=tmp_path,
        http_client=_worker_http_client(server),
        now_message=lambda _msg: None,
    )

    assert ran is True
    assert odm.submitted_masks == []


def test_run_forever_forwards_dynamic_object_detector_to_run_pending_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] run_forever 가 받은 detector 를 매 라운드 run_pending_batch 로
    그대로 넘긴다 — 이 연결이 끊기면 main() 이 아무리 detector 를 만들어도
    폴링 루프에 닿지 않는다."""
    import ksi_processing_controller.runner as runner_module

    detector = _FakeDetector([_person_result()])
    seen: list[Any] = []

    def _fake_run_pending_batch(**kwargs: Any) -> bool:
        seen.append(kwargs.get("dynamic_object_detector"))
        return False

    monkeypatch.setattr(runner_module, "run_pending_batch", _fake_run_pending_batch)

    checks = {"n": 0}

    def should_stop() -> bool:
        checks["n"] += 1
        return checks["n"] > 1

    run_forever(
        core=_core(),
        odm=FakeNodeOdm(),
        work_dir=tmp_path,
        should_stop=should_stop,
        sleep=lambda _s: None,
        dynamic_object_detector=detector,
    )

    assert seen == [detector]


# ── _load_dynamic_object_detector_from_env: 선택적 활성화 스위치 ───────────
#
# KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR. 기본은 꺼짐(미설정 → None, 회귀 없음).
# 설정했는데 로드가 실패하면 fail-closed — 경고만 남기고 마스킹 없이 계속
# 돌지 않고 워커 기동 자체를 거부한다(runner.py 함수 docstring 이 근거를 담는다).


def test_dynamic_object_model_dir_unset_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """[회귀] 미설정이면 마스킹 없이 지금까지와 동일하게 동작한다."""
    import ksi_processing_controller.runner as runner_module

    monkeypatch.delenv(runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV, raising=False)

    assert runner_module._load_dynamic_object_detector_from_env() is None


def test_dynamic_object_model_dir_empty_string_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ksi_processing_controller.runner as runner_module

    monkeypatch.setenv(runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV, "")

    assert runner_module._load_dynamic_object_detector_from_env() is None


def test_dynamic_object_model_dir_missing_path_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] 명시적으로 켰는데 경로 자체가 없으면 조용히 꺼지지 않고 워커
    기동을 거부한다 — "설정 안 함"과 "설정했는데 못 씀"은 다른 사안이다."""
    import ksi_processing_controller.runner as runner_module

    missing = tmp_path / "no-such-model-dir"
    monkeypatch.setenv(runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV, str(missing))

    with pytest.raises(RuntimeError, match=runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV):
        runner_module._load_dynamic_object_detector_from_env()


def test_dynamic_object_model_dir_registry_rejection_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] 경로는 존재하지만 모델 파일이 없어 Registry 검증이 실패하면
    (예: digest 대조 대상 파일 부재) 경고로 넘어가지 않고 기동을 거부한다."""
    import ksi_processing_controller.runner as runner_module

    empty_dir = tmp_path / "empty-model-dir"
    empty_dir.mkdir()
    monkeypatch.setenv(runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV, str(empty_dir))

    with pytest.raises(RuntimeError, match=runner_module._DYNAMIC_OBJECT_MODEL_DIR_ENV):
        runner_module._load_dynamic_object_detector_from_env()

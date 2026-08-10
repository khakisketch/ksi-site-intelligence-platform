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
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_processing_controller.core_client import (
    ComparisonInput,
    CoreClientError,
    PendingComparisonRequest,
    PendingJob,
)
from ksi_processing_controller.runner import run_forever, run_pending_batch

# tests/contract 는 rootdir 기반 수집이라 같은 디렉토리 모듈을 직접 import 한다
# (test_dfine_detector.py 의 DetectorConformanceSuite 와 같은 관용구).
from test_comparison_worker import FakeComparisonCoreClient, _grid, _storage_transport, _write_laz
from test_worker import (  # noqa: E402
    FakeNodeOdm,
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

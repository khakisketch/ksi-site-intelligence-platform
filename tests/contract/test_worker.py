"""워커 오케스트레이션 계약 (services/processing-controller — Core·NodeODM·측정 결합).

``run_job`` 이 생기기 전까지 세 조각(Core 표면·ODM 어댑터·실측)은 개별로는
검증됐지만 **이어 부르는 코드가 없었다**. 이 파일은 그 순서를 가짜 Core·가짜
NodeODM 으로 고정한다 — 네트워크·컨테이너 없이, 각 단계가 정확한 순서·정확한
인자로 불리는지를 본다.

초점 다섯:

1. **순서가 게이트의 순서다** — lease → 입력수신 → RUNNING → 실측·검증 →
   엔진 대조·제출·완주 → 산출물 등록(계보 순) → SUCCEEDED.
2. **실측은 신고값이 아니라 로컬 파일에서 계산된다** — 가짜 Core 가 준
   download_url 을 실제로 받아 실측 함수가 실행된다(mock 이 아니다).
3. **heartbeat 가 폴링마다 lease 를 갱신한다** — ODM 완주까지 여러 폴링이면
   acquire_lease 가 여러 번 불린다.
4. **crs 는 site_crs 에서만 온다** — processing_params 로 흘러들 수 없다.
5. **어떤 단계에서 실패해도 FAILED 로 수렴한다** — 원래 예외는 삼켜지지 않는다.
"""

from __future__ import annotations

import base64
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from ksi_processing_controller.core_client import (
    ArtifactSubmission,
    CoreClientError,
    JobInput,
    JobInputMedia,
    MeasuredImage,
)
from ksi_processing_controller.odm import (
    OdmEngineInfo,
    OdmTaskState,
    OdmTaskStatus,
    SourceImage,
)
from ksi_processing_controller.odm_assets import ODM_ASSETS
from ksi_processing_controller.worker import WorkerRunError, run_job

# 1x1 PNG — Pillow 가 실제로 열어 width=height=1 을 읽는다(mock 아님).
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _FakeHttpServer:
    """워커가 다운로드할 원본 사진을 in-process 로 서빙한다(진짜 소켓 없음).

    httpx 대신 이 트랜스포트를 fake CoreClient/http_client 에 주입한다 —
    ``run_job`` 은 실제 ``httpx.Client`` 를 받으므로, MockTransport 로 파일
    바이트를 그대로 돌려준다.
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            name = request.url.path.rsplit("/", 1)[-1]
            if name not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, content=self.files[name])

        return httpx.MockTransport(handler)


@dataclass
class FakeCoreClient:
    """포트 계약만 만족하는 가짜 Core — 호출 순서를 그대로 기록한다."""

    site_crs: str | None = "EPSG:5186"
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    lease_calls: int = 0
    fail_on: str | None = None  # "verify" | "artifact:<id>" | "transition:<target>"
    _job_status: str = "QUEUED"

    def acquire_lease(self, job_id: str) -> None:
        self.lease_calls += 1
        self.calls.append(("lease", job_id))

    def get_input(self, job_id: str) -> JobInput:
        self.calls.append(("get_input", job_id))
        return JobInput(
            mission_id="mission-1",
            site_id="site-1",
            status=self._job_status,
            provider="odm",
            engine_version="3.5.6",
            engine_digest="sha256:" + "a" * 64,
            execution_locus="ksi_server_gpu",
            processing_params={"pc-quality": "medium"},
            source_bundle_digest="sha256:" + "b" * 64,
            site_crs=self.site_crs,
            media=(
                JobInputMedia(media_id="img-1.png", download_url="http://fake/img-1.png"),
                JobInputMedia(media_id="img-2.png", download_url="http://fake/img-2.png"),
            ),
        )

    def transition(self, job_id: str, target: str, *, detail: str | None = None) -> None:
        self.calls.append(("transition", target, detail))
        if self.fail_on == f"transition:{target}":
            raise CoreClientError(
                what="transition", verdict="ILLEGAL_TRANSITION", detail="테스트 강제 실패"
            )
        self._job_status = target

    def verify_source_media(self, mission_id: str, measurements: list[MeasuredImage]) -> None:
        self.calls.append(("verify", mission_id, tuple(sorted(m.media_id for m in measurements))))
        if self.fail_on == "verify":
            raise CoreClientError(what="verify", verdict="MISMATCH", detail="테스트 강제 실패")

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        self.calls.append(("register_artifact", submission.artifact_id))
        if self.fail_on == f"artifact:{submission.artifact_id}":
            raise CoreClientError(
                what="artifact", verdict="ARTIFACT_CONTRACT_VIOLATION", detail="테스트 강제 실패"
            )


class FakeNodeOdm:
    """포트 계약만 만족하는 가짜 엔진 — test_odm_adapter.py 의 것과 같은 관용구."""

    def __init__(
        self,
        *,
        engine_version: str = "3.5.6",
        states: list[OdmTaskState] | None = None,
        entries: set[str] | None = None,
    ) -> None:
        self.engine_version = engine_version
        self.states = states or [OdmTaskState(status=OdmTaskStatus.COMPLETED)]
        self.entries = entries if entries is not None else {a.archive_entry for a in ODM_ASSETS}
        self.submitted: list[SourceImage] = []
        self.info_calls = 0
        self._state_index = 0

    def info(self) -> OdmEngineInfo:
        self.info_calls += 1
        return OdmEngineInfo(engine="odm", engine_version=self.engine_version, node_version="2.2.4")

    def new_task(self, images: Any, options: dict[str, Any]) -> str:
        del options
        self.submitted = list(images)
        return "task-uuid-1"

    def task_info(self, uuid: str) -> OdmTaskState:
        del uuid
        state = self.states[min(self._state_index, len(self.states) - 1)]
        self._state_index += 1
        return state

    def download_archive(self, uuid: str, dest: Path) -> Path:
        del uuid
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as archive:
            for entry in sorted(self.entries):
                archive.writestr(entry, f"내용:{entry}".encode())
        return dest

    def remove_task(self, uuid: str) -> None:
        del uuid


def _worker_http_client(server: _FakeHttpServer) -> httpx.Client:
    return httpx.Client(transport=server.transport())


def _server_with_two_images() -> _FakeHttpServer:
    server = _FakeHttpServer()
    server.files["img-1.png"] = _TINY_PNG
    server.files["img-2.png"] = _TINY_PNG
    return server


# ── 순서 ─────────────────────────────────────────────────────────────────


def test_happy_path_follows_the_gate_order(tmp_path: Path) -> None:
    core = FakeCoreClient()
    odm = FakeNodeOdm()
    server = _server_with_two_images()

    run_job(
        "job-1", core=core, odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(server),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )

    kinds = [c[0] for c in core.calls]
    assert kinds[0] == "lease"
    assert kinds[1] == "get_input"
    assert ("transition", "RUNNING", None) in core.calls
    verify_idx = kinds.index("verify")
    running_idx = core.calls.index(("transition", "RUNNING", None))
    assert running_idx < verify_idx, "실측 보고는 RUNNING 이후여야 한다"

    artifact_calls = [c for c in core.calls if c[0] == "register_artifact"]
    # 산출물 등록이 전부 SUCCEEDED 전이보다 먼저다.
    succeeded_pos = next(
        i for i, c in enumerate(core.calls) if c == ("transition", "SUCCEEDED", "산출물 7건")
    )
    for i, c in enumerate(core.calls):
        if c[0] == "register_artifact":
            assert i < succeeded_pos
    assert len(artifact_calls) == 7  # ODM_ASSETS 전량(실물 픽스처와 같은 계보)


def test_artifacts_are_registered_in_lineage_order(tmp_path: Path) -> None:
    """[핵심] 부모가 자식보다 먼저 등록된다 — Core 가 부모 실재를 강제하기 때문이다."""
    core = FakeCoreClient()
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )
    order = [c[1] for c in core.calls if c[0] == "register_artifact"]
    position = {aid: i for i, aid in enumerate(order)}
    assert position["point-cloud"] < position["mesh"]
    assert position["mesh"] < position["orthophoto"]
    assert position["point-cloud"] < position["dsm"]
    assert position["point-cloud"] < position["report"]


def test_already_running_job_is_not_re_transitioned(tmp_path: Path) -> None:
    """이미 RUNNING 인 작업(워커 재시작 등)에 다시 RUNNING 전이를 쏘지 않는다."""
    core = FakeCoreClient()
    core._job_status = "RUNNING"  # noqa: SLF001 -- 테스트 픽스처 내부 상태 조작
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    assert ("transition", "RUNNING", None) not in core.calls


# ── 실측은 실제로 파일을 읽어서 계산된다 ─────────────────────────────────────


def test_measurement_comes_from_the_actual_downloaded_bytes(tmp_path: Path) -> None:
    """[핵심] MeasuredImage 가 mock 값이 아니라 로컬 파일에서 실제로 계산된다."""
    core = FakeCoreClient()
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    downloaded = list(tmp_path.glob("img-*.png"))
    assert len(downloaded) == 2, "원본이 로컬에 실제로 저장돼야 실측이 가능하다"
    verify_call = next(c for c in core.calls if c[0] == "verify")
    assert verify_call[2] == ("img-1.png", "img-2.png")


# ── heartbeat ────────────────────────────────────────────────────────────


def test_heartbeat_renews_lease_on_every_poll(tmp_path: Path) -> None:
    """[핵심] ODM 폴링마다 lease 가 갱신된다 — 완주까지 여러 번이면 여러 번 갱신된다."""
    core = FakeCoreClient()
    odm = FakeNodeOdm(
        states=[
            OdmTaskState(status=OdmTaskStatus.QUEUED),
            OdmTaskState(status=OdmTaskStatus.RUNNING),
            OdmTaskState(status=OdmTaskStatus.RUNNING),
            OdmTaskState(status=OdmTaskStatus.COMPLETED),
        ]
    )
    run_job(
        "job-1", core=core, odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    # 최초 취득 1회 + 폴링 3회(QUEUED/RUNNING/RUNNING 다음마다 heartbeat) = 4회 이상.
    assert core.lease_calls >= 4


# ── crs 는 site_crs 에서만 온다 ──────────────────────────────────────────────


@dataclass
class _CrsCapturingCore(FakeCoreClient):
    registered: list[ArtifactSubmission] = field(default_factory=list)

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        self.registered.append(submission)
        super().register_artifact(job_id, submission)


def test_crs_is_read_from_site_crs_field(tmp_path: Path) -> None:
    """[핵심] plan_artifacts 에 넘어가는 crs 가 site_crs 값과 정확히 같다."""
    core = _CrsCapturingCore(site_crs="EPSG:32610")
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    point_cloud = next(s for s in core.registered if s.artifact_id == "point-cloud")
    assert point_cloud.crs == "EPSG:32610"

    core_2 = _CrsCapturingCore(site_crs="EPSG:5186")
    run_job(
        "job-2", core=core_2, odm=FakeNodeOdm(), work_dir=tmp_path / "job2",
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    point_cloud_2 = next(s for s in core_2.registered if s.artifact_id == "point-cloud")
    assert point_cloud_2.crs == "EPSG:5186"


def test_missing_site_crs_refuses_before_touching_the_engine(tmp_path: Path) -> None:
    """[핵심] siteCrs 가 없으면(현장 원장 이상) 엔진을 부르지도 않고 거부한다."""
    core = FakeCoreClient(site_crs=None)
    odm = FakeNodeOdm()
    with pytest.raises(WorkerRunError, match="siteCrs"):
        run_job(
            "job-1", core=core, odm=odm, work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    assert odm.info_calls == 0, "crs 가 없는데 엔진에 이미 제출을 시도했다"
    assert not any(c[0] == "transition" and c[1] == "RUNNING" for c in core.calls)


# ── 실패는 FAILED 로 수렴한다 ────────────────────────────────────────────────


def test_verify_mismatch_transitions_to_failed_and_reraises(tmp_path: Path) -> None:
    core = FakeCoreClient(fail_on="verify")
    with pytest.raises(WorkerRunError):
        run_job(
            "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    failed_calls = [c for c in core.calls if c[0] == "transition" and c[1] == "FAILED"]
    assert len(failed_calls) == 1


def test_engine_mismatch_transitions_to_failed(tmp_path: Path) -> None:
    """엔진 버전이 다르면 제출 전에 거부되고, 그래도 FAILED 로 보고된다."""
    core = FakeCoreClient()
    odm = FakeNodeOdm(engine_version="9.9.9")
    with pytest.raises(WorkerRunError):
        run_job(
            "job-1", core=core, odm=odm, work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    assert odm.submitted == [], "엔진 신원이 다른데 제출이 실행됐다"
    assert ("transition", "FAILED", None) not in core.calls  # detail 이 있어야 한다
    assert any(c[0] == "transition" and c[1] == "FAILED" for c in core.calls)


def test_engine_task_failure_propagates_and_reports_failed(tmp_path: Path) -> None:
    core = FakeCoreClient()
    odm = FakeNodeOdm(
        states=[OdmTaskState(status=OdmTaskStatus.FAILED, error_message="메모리 부족")]
    )
    with pytest.raises(WorkerRunError, match="메모리 부족"):
        run_job(
            "job-1", core=core, odm=odm, work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    failed = next(c for c in core.calls if c[0] == "transition" and c[1] == "FAILED")
    assert "메모리 부족" in (failed[2] or "")


def test_artifact_rejection_transitions_to_failed(tmp_path: Path) -> None:
    """산출물 등록이 Core 에서 거부되면(계약 위반 등) FAILED 로 끝난다."""
    core = FakeCoreClient(fail_on="artifact:point-cloud")
    with pytest.raises(WorkerRunError):
        run_job(
            "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    assert any(c[0] == "transition" and c[1] == "FAILED" for c in core.calls)
    # camera-poses(첫 원본)는 point-cloud 보다 먼저라 등록에 성공했어야 한다.
    assert ("register_artifact", "camera-poses") in core.calls
    # point-cloud 실패 이후 나머지(mesh 등)는 시도되지 않는다 — 계보 순서라
    # 부모 없는 자식을 등록해봐야 어차피 거부된다.
    assert ("register_artifact", "mesh") not in core.calls


def test_original_exception_is_not_swallowed_even_if_failed_report_also_fails(
    tmp_path: Path,
) -> None:
    """[핵심] FAILED 보고 자체가 실패해도(lease 만료 등) 원래 예외가 살아남는다.

    실측 대조 실패(MISMATCH)가 진짜 원인이다. 그 이후 FAILED 보고 시도가
    STORE_UNAVAILABLE 로 또 실패해도, 호출자가 받는 것은 여전히 MISMATCH 다 —
    보고 실패는 부수 정보로 로그에만 남고 원래 원인을 밀어내지 않는다.
    """
    core = FakeCoreClient(fail_on="verify")
    original_transition = core.transition

    def flaky_transition(job_id: str, target: str, *, detail: str | None = None) -> None:
        if target == "FAILED":
            raise CoreClientError(what="transition", verdict="STORE_UNAVAILABLE", detail=None)
        original_transition(job_id, target, detail=detail)

    core.transition = flaky_transition  # type: ignore[method-assign]
    with pytest.raises(WorkerRunError) as excinfo:
        run_job(
            "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )
    cause = excinfo.value.__cause__
    assert isinstance(cause, CoreClientError)
    assert cause.verdict == "MISMATCH", (
        f"FAILED 보고 실패(STORE_UNAVAILABLE)가 원래 원인(MISMATCH)을 가렸다: {cause}"
    )

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
import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from ksi_core.processing_profiles import ksi_odm_civil_v1
from ksi_domain.detection import BoundingBox, Detection
from ksi_domain.detection_adapter import AdapterResult
from ksi_event_contracts.vertical_reference import VerticalDatum, VerticalReferenceSource
from ksi_processing_controller.core_client import (
    ArtifactSubmission,
    ArtifactUploadTarget,
    CoreClientError,
    JobInput,
    JobInputMedia,
    LeaseHandle,
    MeasuredImage,
    PendingJob,
)
from ksi_processing_controller.odm import (
    OdmEngineInfo,
    OdmTaskState,
    OdmTaskStatus,
    SourceImage,
)
from ksi_processing_controller.odm_assets import ODM_ASSETS
from ksi_processing_controller.odm_masking import odm_mask_filename
from ksi_processing_controller.worker import WorkerRunError, run_job
from ksi_processing_controller.workspace import (
    UnsafeWorkspaceError,
    attempt_workspace,
    cleanup_attempt_workspace,
)

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
        #: presigned PUT 으로 실제로 올라온 바이트 — 키는 객체 키다.
        self.uploaded: dict[str, bytes] = {}
        self.fail_upload_of: str | None = None

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PUT":
                # presigned PUT — 경로에서 "/fake-storage/" 뒤가 객체 키다.
                key = request.url.path.lstrip("/")
                if self.fail_upload_of is not None and key.endswith(self.fail_upload_of):
                    return httpx.Response(503)
                self.uploaded[key] = request.content
                return httpx.Response(200)
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
    input_override: JobInput | None = None

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        """이 파일의 시험 대상은 ``run_job(job_id, ...)`` 직접 호출이라 대기
        목록을 쓰지 않는다 — ``CoreClient`` Protocol 을 구조적으로 만족시키기
        위한 최소 구현(호출 시 실제 값이 필요한 시험은 test_runner.py 가 한다)."""
        del limit
        return []

    def acquire_lease(self, job_id: str) -> None:
        self.lease_calls += 1
        self.calls.append(("lease", job_id))

    def get_input(self, job_id: str) -> JobInput:
        self.calls.append(("get_input", job_id))
        if self.input_override is not None:
            return self.input_override
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

    def presign_artifact_upload(
        self,
        job_id: str,
        *,
        artifact_id: str,
        content_type: str,
        filename: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
    ) -> ArtifactUploadTarget:
        del content_type, sha256, size_bytes
        self.calls.append(("presign", artifact_id, filename))
        if self.fail_on == f"presign:{artifact_id}":
            raise CoreClientError(
                what="upload-url", verdict="LEASE_REQUIRED", detail="테스트 강제 실패"
            )
        key = f"sites/site-1/processing-jobs/{job_id}/artifacts/{artifact_id}"
        if filename is not None:
            key = f"{key}/{filename}"
        return ArtifactUploadTarget(
            object_key=key, upload_url=f"http://fake-storage/{key}"
        )

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        self.calls.append(
            ("register_artifact", submission.artifact_id, submission.auxiliary_files)
        )
        if self.fail_on == f"artifact:{submission.artifact_id}":
            raise CoreClientError(
                what="artifact", verdict="ARTIFACT_CONTRACT_VIOLATION", detail="테스트 강제 실패"
            )

    # ── W2 비교 요청 표면 — 이 파일의 시험 대상(run_job)은 쓰지 않는다.
    # CoreClient Protocol 구조 만족용 최소 스텁이다(comparison_worker 시험은
    # test_comparison_worker.py 의 FakeComparisonCoreClient 가 실제로 구현한다).

    def list_pending_comparisons(self, *, limit: int = 50) -> list[Any]:
        raise NotImplementedError

    def acquire_comparison_lease(self, request_id: str) -> None:
        raise NotImplementedError

    def get_comparison_input(self, request_id: str) -> Any:
        raise NotImplementedError

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        raise NotImplementedError

    def submit_change_detection(self, mission_id: str, result: Any) -> None:
        raise NotImplementedError

    def submit_volume_change(self, mission_id: str, report: Any) -> None:
        raise NotImplementedError


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
        self.submitted_masks: list[Any] = []
        self.submitted_ground_control: Any = None
        self.info_calls = 0
        self._state_index = 0

    def info(self) -> OdmEngineInfo:
        self.info_calls += 1
        return OdmEngineInfo(engine="odm", engine_version=self.engine_version, node_version="2.2.4")

    def new_task(
        self,
        images: Any,
        options: dict[str, Any],
        *,
        masks: Any = (),
        ground_control: Any = None,
    ) -> str:
        del options
        self.submitted = list(images)
        self.submitted_masks = list(masks)
        self.submitted_ground_control = ground_control
        return "task-uuid-1"

    def task_info(self, uuid: str) -> OdmTaskState:
        del uuid
        state = self.states[min(self._state_index, len(self.states) - 1)]
        self._state_index += 1
        return state

    def download_archive(self, uuid: str, dest: Path) -> Path:
        del uuid
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 압축(ZIP_DEFLATED)으로 쓴다 — 실물 ODM 산출물이 그렇다. ZIP_STORED(무압축)로
        # 쓰면 file_size == compress_size 라, 업로드 코드가 Content-Length 를
        # file_size 대신 compress_size 로 잘못 읽는 퇴행을 이 픽스처가 못 잡는다.
        # 반복 데이터라야 압축이 실제로 줄어든다 — 짧은 무작위 문자열은 deflate 해도
        # 오버헤드 때문에 compress_size 가 안 줄 수 있다.
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in sorted(self.entries):
                archive.writestr(entry, (f"내용:{entry}" * 200).encode())
        return dest

    def remove_task(self, uuid: str) -> None:
        del uuid


class _FakeDetector:
    """포트 계약(``ImageDetector``, 구조적 타이핑)만 만족하는 가짜 탐지기.

    호출마다 미리 정한 결과를 순서대로 낸다 — media_id 는 안 받는다(실제
    ``DFineDetector.detect_image`` 도 이미지 배열만 받는다, ``odm_masking.py``
    모듈 참고).
    """

    def __init__(self, results: list[AdapterResult]) -> None:
        self._results = results
        self.calls = 0

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        del image
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


class _RaisingDetector:
    """탐지 자체가 예외로 실패하는 가짜 — 사진 1장의 탐지 실패가 작업을 막지
    않는지 본다."""

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        del image
        raise RuntimeError("탐지 런타임 실패(테스트 강제)")


def _person_result() -> AdapterResult:
    detection = Detection(
        detection_class="Person",
        confidence=0.9,
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
        source_class_id=0,
        source_class_name="person",
    )
    return AdapterResult(detections=[detection], dropped=[], clipped=[])


def _empty_result() -> AdapterResult:
    return AdapterResult(detections=[], dropped=[], clipped=[])


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
    """[핵심] MeasuredImage 가 mock 값이 아니라 실제로 받은 바이트에서 계산된다.

    work_dir 청소(2026-08-13 확정 발견 수정)로 ``run_job`` 이 끝나면 파일이
    안 남는다 — "파일이 로컬에 남아 있다"가 아니라 "측정값이 실제 원본 바이트와
    일치한다"로 직접 검증한다(더 강한 증거이지 우회가 아니다).
    """
    core = FakeCoreClient()
    captured: list[MeasuredImage] = []
    original_verify = core.verify_source_media

    def _capturing_verify(mission_id: str, measurements: list[MeasuredImage]) -> None:
        captured.extend(measurements)
        original_verify(mission_id, measurements)

    core.verify_source_media = _capturing_verify  # type: ignore[method-assign]

    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )

    expected_sha256 = hashlib.sha256(_TINY_PNG).hexdigest()
    assert {m.media_id for m in captured} == {"img-1.png", "img-2.png"}
    for measured in captured:
        assert measured.sha256 == expected_sha256, "mock 값이 아니라 실제 바이트에서 계산돼야 한다"
        assert measured.size_bytes == len(_TINY_PNG)
        assert measured.width == 1
        assert measured.height == 1
        assert measured.capture_time.status.value == "UNAVAILABLE"
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


# ── 수직기준은 파이프라인이 선언한다 ─────────────────────────────────────────


def test_spatial_artifacts_declare_the_pipeline_vertical_reference(tmp_path: Path) -> None:
    """[핵심] 공간 산출물마다 "이 높이는 변환 안 한 타원체고다"가 근거와 함께 실린다.

    이 값이 없던 동안 그 사실을 아는 유일한 자리는 **비교 워커의 하드코딩
    상수**였다 — 산출물의 사실이 아니라 소비자의 가정이었다. 선언이 산출물에
    붙어야 바깥에서 들어온 높이(설계면)와 비교할 때 계열을 판정할 수 있다.
    """
    core = _CrsCapturingCore(site_crs="EPSG:5186")
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    spatial = [s for s in core.registered if s.crs is not None]
    assert spatial, "공간 산출물이 하나도 등록되지 않았다 — 이 테스트가 공허하다"
    for submission in spatial:
        reference = submission.vertical_reference
        assert reference is not None, f"{submission.artifact_id} 에 수직기준이 없다"
        assert reference.datum is VerticalDatum.ELLIPSOIDAL_NATIVE
        assert reference.source is VerticalReferenceSource.PIPELINE_DECLARED
        assert reference.basis.strip(), "근거 없는 선언은 추측이다"


def test_artifacts_without_a_crs_declare_no_vertical_reference(tmp_path: Path) -> None:
    """[비공허 대조] 좌표계가 없는 산출물(카메라 포즈)에는 달지 않는다 — 높이가
    그 산출물 자체의 속성이 아닌 곳에 기준만 선언하면 없는 것을 있다고 읽힌다."""
    core = _CrsCapturingCore(site_crs="EPSG:5186")
    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
    )
    non_spatial = [s for s in core.registered if s.crs is None]
    assert non_spatial, "crs 가 null 인 산출물이 없다 — 이 대조가 공허하다"
    assert all(s.vertical_reference is None for s in non_spatial)


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
    # siteCrs 결손도 다른 WorkerRunError 경로와 똑같이 FAILED 로 수렴해야 한다
    # (test_verify_mismatch_transitions_to_failed_and_reraises 와 동일 패턴) —
    # 그렇지 않으면 작업이 QUEUED 에 갇혀 FIFO 선두를 영원히 막는다.
    failed_calls = [c for c in core.calls if c[0] == "transition" and c[1] == "FAILED"]
    assert len(failed_calls) == 1


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
    assert ("register_artifact", "camera-poses", ()) in core.calls
    # point-cloud 실패 이후 나머지(mesh 등)는 시도되지 않는다 — 계보 순서라
    # 부모 없는 자식을 등록해봐야 어차피 거부된다.
    assert not any(c[0] == "register_artifact" and c[1] == "mesh" for c in core.calls)


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


# ── work_dir 청소 + 좁았던 예외 목록 (2026-08-13 프로젝트 두뇌 재감사 확정 발견) ──


def test_work_dir_is_emptied_after_a_successful_run(tmp_path: Path) -> None:
    """work_dir 는 네 종류 작업이 공유한다 — 성공해도 사진·아카이브를 남기면
    다음 작업(또는 다음 재시도)마다 쌓여 영속 볼륨이 무한히 찬다."""
    core = FakeCoreClient()
    odm = FakeNodeOdm()
    server = _server_with_two_images()

    run_job(
        "job-1", core=core, odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(server),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )

    assert list(tmp_path.iterdir()) == [], "성공했는데 work_dir 에 파일이 남았다"


def test_work_dir_is_emptied_after_a_failed_run(tmp_path: Path) -> None:
    """실패해도 이미 받아둔 사진은 지운다 — 실패한 작업의 잔해가 디스크를 갉아먹으면 안 된다."""
    core = FakeCoreClient(fail_on="verify")
    with pytest.raises(WorkerRunError):
        run_job(
            "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )

    assert list(tmp_path.iterdir()) == [], "실패했는데 work_dir 에 사진이 남았다"


def test_a_disk_write_failure_is_reported_as_failed_not_left_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[회귀] 디스크가 찼을 때(OSError)도 FAILED 로 수렴한다.

    옛 코드는 ``except (OdmError, httpx.HTTPError, CoreClientError)`` 로 좁게
    잡았다 — OSError 는 셋 중 어디에도 안 걸려 이 함수를 그냥 빠져나갔다. 그러면
    WorkerRunError 로 감싸이지 않아 runner.py 의 ``_try_candidates`` 가 "이번
    라운드는 아무 일도 안 했다"로 오판하고, lease 를 쥔 채 RUNNING 으로 남은 같은
    작업을 FAILED 보고 없이 다음 라운드에 또 시도한다 — 영원히.
    """
    import ksi_processing_controller.worker as worker_module

    def _raise_disk_full(client: httpx.Client, url: str, dest: Path) -> None:
        del client, url
        dest.write_bytes(b"\x00\x00\x00\x00")  # 디스크가 찼을 때 흔히 남는 부분 파일
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(worker_module, "_download", _raise_disk_full)

    core = FakeCoreClient()
    with pytest.raises(WorkerRunError, match="No space left on device"):
        run_job(
            "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
            poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        )

    failed_calls = [c for c in core.calls if c[0] == "transition" and c[1] == "FAILED"]
    assert len(failed_calls) == 1, "OSError 가 FAILED 보고 없이 새어나갔다"
    assert "No space left on device" in (failed_calls[0][2] or "")
    # 부분 파일까지 지워졌는가 — 디스크가 찬 상황에서 자기가 남긴 부분 파일을
    # 못 치우면 재시도가 시작부터 더 불리해진다.
    assert list(tmp_path.iterdir()) == []


# ── 산출물 바이트 (M1) ──────────────────────────────────────────────────────


def _run(core: FakeCoreClient, odm: FakeNodeOdm, server: _FakeHttpServer, tmp_path: Path) -> None:
    run_job(
        "job-1", core=core, odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(server),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )


def test_bytes_are_uploaded_before_the_artifact_is_registered(tmp_path: Path) -> None:
    """[핵심 순서] 자리를 받고 → 쓰고 → 등록한다.

    뒤집히면 "원장에는 있는데 바이트가 없는" 창이 열리고, 그 창에서 누가
    다운로드를 요청하면 깨진 링크를 받는다.
    """
    core, odm, server = FakeCoreClient(), FakeNodeOdm(), _server_with_two_images()
    _run(core, odm, server, tmp_path)

    for artifact_id in ("camera-poses", "point-cloud", "orthophoto", "dsm"):
        presign_at = core.calls.index(("presign", artifact_id, None))
        register_at = core.calls.index(("register_artifact", artifact_id, ()))
        assert presign_at < register_at, f"{artifact_id}: 등록이 업로드보다 먼저다"


def test_uploaded_bytes_are_the_archive_entry_verbatim(tmp_path: Path) -> None:
    """[핵심] 저장되는 것은 ODM 이 낸 원본 바이트 그대로다.

    저장 시점에 포맷을 변환하면(예: GeoTIFF→COG) 저장된 바이트가 등록된
    digest 와 달라진다 — 서빙용 변환은 원본에서 재생성하는 파생 산출물의
    몫이다(ADR-KSI-003·INV-051).
    """
    core, odm, server = FakeCoreClient(), FakeNodeOdm(), _server_with_two_images()
    _run(core, odm, server, tmp_path)

    key = "sites/site-1/processing-jobs/job-1/artifacts/dsm"
    assert key in server.uploaded
    # FakeNodeOdm 이 각 엔트리에 써넣는 내용과 정확히 같아야 한다.
    assert server.uploaded[key] == ("내용:odm_dem/dsm.tif" * 200).encode()


def test_every_registered_artifact_has_bytes(tmp_path: Path) -> None:
    """등록된 산출물 전부에 대응하는 바이트가 있다 — 다운로드 표면이 기대는 불변식."""
    core, odm, server = FakeCoreClient(), FakeNodeOdm(), _server_with_two_images()
    _run(core, odm, server, tmp_path)

    registered = [c[1] for c in core.calls if c[0] == "register_artifact"]
    assert registered, "등록된 산출물이 하나도 없다"
    for artifact_id in registered:
        assert (
            f"sites/site-1/processing-jobs/job-1/artifacts/{artifact_id}"
            in server.uploaded
        )


def test_multi_file_artifact_uploads_all_files_then_registers_once(tmp_path: Path) -> None:
    """[핵심 — mesh-multi-file-artifact-persistence] 파일 여러 개짜리 산출물은
    전부(주 파일 + 부속 파일) 올린 **뒤에** 한 번만 등록한다.

    메시는 텍스처·재질이 digest 에 함께 들어가 객체 키 하나에 담기지 않는다
    — 예전엔 이 사실 때문에 등록 자체를 건너뛰었다(대표 파일만 올리면
    "digest 는 결합 해시인데 저장된 건 .obj 하나"인 상태가 생기므로). 지금은
    부속 파일마다 별도 객체 키(주 파일 키 아래 basename)를 받아 전부 올리고,
    등록 요청에 그 basename 목록(auxiliaryFiles)을 실어 저장 상태와 등록
    상태가 항상 같이 간다.
    """
    entries = {a.archive_entry for a in ODM_ASSETS} | {
        "odm_texturing/odm_textured_model_geo.mtl",
        "odm_texturing/odm_textured_model_geo_map_Kd.png",
    }
    core, server = FakeCoreClient(), _server_with_two_images()
    _run(core, FakeNodeOdm(entries=entries), server, tmp_path)

    aux_names = ("odm_textured_model_geo.mtl", "odm_textured_model_geo_map_Kd.png")
    presign_calls = [c for c in core.calls if c[0] == "presign" and c[1] == "mesh"]
    assert {c[2] for c in presign_calls} == {None, *aux_names}, (
        "mesh 는 주 파일(filename=None) + 부속 파일 2개, 총 3번 presign 돼야 한다"
    )
    register_calls = [c for c in core.calls if c[0] == "register_artifact" and c[1] == "mesh"]
    assert len(register_calls) == 1, "등록은 파일 개수와 무관하게 한 번이어야 한다"
    # [C3] 등록 요청 자체에 auxiliaryFiles 가 실려야 한다 — 업로드만 하고
    # worker.py 의 auxiliary_files=report.auxiliary_files 를 빠뜨리면(reviewer
    # 지적, 2026-08-08) 파일은 다 올라가는데 등록 원장엔 부속 파일 목록이
    # 빠진 채로 성공해버리고, 이 사실을 이전엔 어떤 테스트도 못 잡았다.
    assert register_calls[0][2] == aux_names

    base_key = "sites/site-1/processing-jobs/job-1/artifacts/mesh"
    assert base_key in server.uploaded
    for name in aux_names:
        assert f"{base_key}/{name}" in server.uploaded

    last_presign_at = max(core.calls.index(c) for c in presign_calls)
    register_at = core.calls.index(register_calls[0])
    assert last_presign_at < register_at, "부속 파일까지 전부 올린 뒤에 등록해야 한다"

    assert ("transition", "SUCCEEDED", "산출물 7건") in core.calls


def test_upload_failure_fails_the_job_without_registering(tmp_path: Path) -> None:
    """[음성] 업로드가 깨지면 등록하지 않고 FAILED 로 수렴한다.

    여기서 등록을 강행하면 바이트 없는 산출물이 원장에 남는다.
    """
    core, odm, server = FakeCoreClient(), FakeNodeOdm(), _server_with_two_images()
    server.fail_upload_of = "artifacts/point-cloud"

    with pytest.raises(WorkerRunError):
        _run(core, odm, server, tmp_path)

    assert not any(c[0] == "register_artifact" and c[1] == "point-cloud" for c in core.calls)
    assert any(c[0] == "transition" and c[1] == "FAILED" for c in core.calls)


def test_upload_sends_an_explicit_content_length_not_chunked_encoding(tmp_path: Path) -> None:
    """[핵심 회귀] presigned PUT 은 청크 전송이 아니라 고정 Content-Length 여야 한다.

    S3 SigV4 presigned URL 은 고정 길이 payload 를 전제한다 — httpx 는 스트리밍
    content 에 길이를 못 정하면 Transfer-Encoding: chunked 를 자동으로 붙이는데,
    그러면 MinIO/S3 가 411 Length Required 로 거부한다(2026-08-08 MinIO 대상
    실기동에서 실제로 재현됐다 — 가짜 스토리지 계약 테스트는 이 차이를 못 본다).
    """
    core, server = FakeCoreClient(), _server_with_two_images()
    captured: dict[str, httpx.Request] = {}
    # _FakeHttpServer.transport() 는 항상 동기 handler 를 만든다(비동기 아님) —
    # httpx.MockTransport.handler 의 유니온 타입을 여기서 좁힌다.
    inner_handler: Callable[[httpx.Request], httpx.Response] = server.transport().handler  # type: ignore[assignment]

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            captured[request.url.path] = request
        return inner_handler(request)

    run_job(
        "job-1", core=core, odm=FakeNodeOdm(), work_dir=tmp_path,
        poll_interval_seconds=0,
        http_client=httpx.Client(transport=httpx.MockTransport(capturing_handler), timeout=30.0),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )

    assert captured, "PUT 요청이 하나도 기록되지 않았다"
    for path, request in captured.items():
        assert "transfer-encoding" not in request.headers, (
            f"{path}: Transfer-Encoding 헤더가 있다 — 청크 전송이면 S3 presigned PUT 이 411 을 낸다"
        )
        assert "content-length" in request.headers, f"{path}: Content-Length 가 없다"
        assert int(request.headers["content-length"]) == len(request.content)


# ── 동적 객체 마스킹 (PRD §15.2 ④, dynamic_object_detector 주입 지점) ────────


def test_no_detector_means_no_masking_by_default(tmp_path: Path) -> None:
    """[회귀] ``dynamic_object_detector`` 를 생략하면 지금까지와 동일하게
    동작한다 — 마스크가 하나도 만들어지지 않는다."""
    odm = FakeNodeOdm()
    _run(FakeCoreClient(), odm, _server_with_two_images(), tmp_path)
    assert odm.submitted_masks == []


def test_standard_v1_rejects_a_configured_dynamic_masker(tmp_path: Path) -> None:
    """The v1 profile fixes pixels as well as engine parameters (INV-053)."""
    base = FakeCoreClient().get_input("seed")
    profile = ksi_odm_civil_v1()
    core = FakeCoreClient(
        input_override=replace(
            base,
            engine_digest=profile.oci_image_digest,
            processing_params=profile.processing_params,
            processing_profile_id=profile.processing_profile_id,
            processing_profile_digest=profile.profile_digest,
            processing_profile_classification="VERSIONED",
        )
    )
    odm = FakeNodeOdm()

    with pytest.raises(WorkerRunError, match="dynamic object masking=OFF"):
        run_job(
            "job-1",
            core=core,
            odm=odm,
            work_dir=tmp_path,
            poll_interval_seconds=0,
            http_client=_worker_http_client(_server_with_two_images()),
            dynamic_object_detector=_FakeDetector([_person_result(), _person_result()]),
        )

    assert odm.info_calls == 0
    assert any(call[0:2] == ("transition", "FAILED") for call in core.calls)


def test_detector_generates_a_mask_per_photo_with_a_detection(tmp_path: Path) -> None:
    """[핵심] 탐지된 사진마다 ``{stem}_mask.png`` 규약의 마스크가 NodeODM 제출에
    함께 실린다(odm_masking 모듈 docstring — 실물 검증된 규약)."""
    odm = FakeNodeOdm()
    detector = _FakeDetector([_person_result(), _person_result()])

    run_job(
        "job-1", core=FakeCoreClient(), odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
        dynamic_object_detector=detector,
    )

    assert detector.calls == 2, "사진 2장 모두 탐지를 거쳐야 한다"
    assert {m.filename for m in odm.submitted_masks} == {
        odm_mask_filename("img-1.png"),
        odm_mask_filename("img-2.png"),
    }
    for mask in odm.submitted_masks:
        assert mask.png_bytes.startswith(b"\x89PNG"), "PNG 매직바이트가 없다"


def test_detector_produces_no_mask_when_nothing_detected(tmp_path: Path) -> None:
    """동적 객체가 없는 사진은 마스크를 만들지 않는다 — 전부 흰색 마스크는
    ODM 입장에서 무의미하다(odm_masking.build_mask_for_photo docstring)."""
    odm = FakeNodeOdm()
    detector = _FakeDetector([_empty_result(), _empty_result()])

    run_job(
        "job-1", core=FakeCoreClient(), odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
        dynamic_object_detector=detector,
    )

    assert odm.submitted_masks == []


def test_detector_failure_on_one_photo_does_not_fail_the_job(tmp_path: Path) -> None:
    """[음성] 탐지 자체가 예외를 던져도 재구성은 계속된다 — 마스킹은 보조
    개선이지 재구성 성공의 필요조건이 아니다(run_job docstring)."""
    core = FakeCoreClient()
    odm = FakeNodeOdm()

    run_job(
        "job-1", core=core, odm=odm, work_dir=tmp_path,
        poll_interval_seconds=0, http_client=_worker_http_client(_server_with_two_images()),
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
        dynamic_object_detector=_RaisingDetector(),
    )

    assert odm.submitted_masks == []
    assert ("transition", "SUCCEEDED", "산출물 7건") in core.calls
# ── fenced local workspace ─────────────────────────────────────────────────


def test_attempt_workspaces_never_share_fixed_all_zip_path(tmp_path: Path) -> None:
    """Same job on two generations/processes gets two exclusive writable paths."""
    first = LeaseHandle(
        work_kind="processing", resource_id="job-1",
        worker_instance_id="11111111-1111-4111-8111-111111111111",
        lease_acquisition_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        lease_generation=1,
    )
    second = LeaseHandle(
        work_kind="processing", resource_id="job-1",
        worker_instance_id="22222222-2222-4222-8222-222222222222",
        lease_acquisition_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        lease_generation=2,
    )
    one = attempt_workspace(tmp_path, first)
    two = attempt_workspace(tmp_path, second)
    assert one / "all.zip" != two / "all.zip"
    (one / "all.zip").write_bytes(b"one")
    (two / "all.zip").write_bytes(b"two")
    with pytest.raises(UnsafeWorkspaceError):
        attempt_workspace(tmp_path, first)
    cleanup_attempt_workspace(tmp_path, one)
    cleanup_attempt_workspace(tmp_path, two)
    assert list(tmp_path.iterdir()) == []


def test_attempt_workspace_namespace_separates_jobs_instances_and_generations(
    tmp_path: Path,
) -> None:
    handles = [
        LeaseHandle(
            work_kind="processing",
            resource_id="job-1",
            worker_instance_id="11111111-1111-4111-8111-111111111111",
            lease_acquisition_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            lease_generation=1,
        ),
        LeaseHandle(
            work_kind="processing",
            resource_id="job-2",
            worker_instance_id="11111111-1111-4111-8111-111111111111",
            lease_acquisition_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            lease_generation=1,
        ),
        LeaseHandle(
            work_kind="processing",
            resource_id="job-1",
            worker_instance_id="11111111-1111-4111-8111-111111111111",
            lease_acquisition_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            lease_generation=2,
        ),
        LeaseHandle(
            work_kind="processing",
            resource_id="job-1",
            worker_instance_id="22222222-2222-4222-8222-222222222222",
            lease_acquisition_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            lease_generation=1,
        ),
    ]
    paths = [attempt_workspace(tmp_path, handle) for handle in handles]
    assert len(set(paths)) == len(paths)
    assert paths[0].relative_to(tmp_path).parts == (
        "processing",
        "job-1",
        handles[0].worker_instance_id,
        "1",
    )
    for index, path in enumerate(paths):
        (path / "all.zip").write_bytes(str(index).encode())
    assert len({(path / "all.zip").read_bytes() for path in paths}) == len(paths)


def test_cleanup_of_generation_n_cannot_remove_generation_n_plus_one(
    tmp_path: Path,
) -> None:
    instance = "11111111-1111-4111-8111-111111111111"
    first = LeaseHandle(
        "processing", "job-1", instance,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 1,
    )
    second = LeaseHandle(
        "processing", "job-1", instance,
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 2,
    )
    first_path = attempt_workspace(tmp_path, first)
    second_path = attempt_workspace(tmp_path, second)
    survivor = second_path / "all.zip"
    survivor.write_bytes(b"generation-2")

    cleanup_attempt_workspace(tmp_path, first_path)

    assert not first_path.exists()
    assert survivor.read_bytes() == b"generation-2"


def test_crash_leftover_is_never_reused_as_a_new_attempt(tmp_path: Path) -> None:
    handle = LeaseHandle(
        "processing",
        "job-1",
        "11111111-1111-4111-8111-111111111111",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        1,
    )
    leftover = attempt_workspace(tmp_path, handle)
    (leftover / "partial.bin").write_bytes(b"orphan")

    with pytest.raises(UnsafeWorkspaceError, match="already exists"):
        attempt_workspace(tmp_path, handle)

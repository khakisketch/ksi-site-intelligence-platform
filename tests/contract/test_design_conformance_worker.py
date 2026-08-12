"""설계 대비 워커 오케스트레이션 계약 (``design_conformance_worker``).

``test_comparison_worker.py`` 가 비교 워커의 순서를 가짜 Core 로 고정한 것과
동형이다: lease → 입력수신 → (QUEUED 면) RUNNING → 계산 → **래스터 업로드 +
Core 확인** → 리포트 제출 → SUCCEEDED. 실패는 FAILED 로 수렴하고 원래 예외를
삼키지 않는다.

가짜인 것은 Core HTTP 표면과 오브젝트 스토리지 트랜스포트뿐이다 — GeoTIFF 는
rasterio 로 진짜로 쓰고, 차분·구역 집계·해시는 실제 코드가 한다. 특히
**업로드된 바이트의 해시를 가짜 Core 가 다시 계산해** 워커의 신고와 대조한다
(실제 Core 가 하는 일과 같은 방식) — 그래야 "워커가 올린 것과 신고한 것이 같은가"
라는 이 milestone 의 질문이 이 파일에서도 진짜로 시험된다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from ksi_change_detection.diff_raster import sha256_of_file
from ksi_event_contracts.change_detection_result import ArtifactRef  # noqa: E402  (정렬 유지)
from ksi_event_contracts.comparison_policy import ComparisonPolicy, current_comparison_policy
from ksi_event_contracts.design_conformance_report import DesignConformanceReport
from ksi_processing_controller.core_client import (
    CoreClientError,
    DesignConformanceInput,
    DiffRasterUploadTarget,
    PendingDesignConformanceRequest,
)
from ksi_processing_controller.design_conformance_worker import (
    DesignConformanceWorkerRunError,
    run_design_conformance_request,
)
from test_design_conformance_compute import (  # noqa: E402
    _CRS,
    _CURRENT_VERTICAL,
    _DESIGN_VERTICAL,
    _EXPECTED_CUT_M3,
    _EXPECTED_FILL_M3,
    _ORTHOMETRIC_VERTICAL,
    _flat,
    _full_extent_zone,
    _ramp,
    _write_raster,
)

_REQUEST_ID = "mission-1-dcf1"
_UPLOAD_URL = "https://storage.invalid/put/diff-raster"


@dataclass
class FakeCore:
    """설계 대비 Core 표면의 대역 — **업로드된 바이트를 스스로 다시 해싱한다.**

    ``verify_diff_raster`` 가 실제 Core 와 같은 판정을 한다: 워커가 신고한 digest
    와 이 대역이 보관 중인 바이트의 해시가 다르면 ``DIFF_RASTER_DIGEST_MISMATCH``
    로 거부한다. 그 거부가 워커에게 어떻게 전달되는지가 이 파일의 관심사다.
    """

    conformance_input: DesignConformanceInput
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    uploaded: bytes | None = None
    submitted: list[tuple[str, DesignConformanceReport]] = field(default_factory=list)
    status: str = "QUEUED"
    verified_at: datetime = datetime(2026, 8, 12, 3, 0, 30, tzinfo=UTC)
    #: 업로드 뒤 신고와 다른 바이트로 바뀌었다고 가정한다(교체 창 재현).
    swap_uploaded_with: bytes | None = None
    duplicate_report: bool = False
    fail_transition_to: str | None = None

    def list_pending_design_conformances(
        self, *, limit: int = 50
    ) -> list[PendingDesignConformanceRequest]:
        del limit
        return []

    def acquire_design_conformance_lease(self, request_id: str) -> None:
        self.calls.append(("lease", request_id))

    def get_design_conformance_input(self, request_id: str) -> DesignConformanceInput:
        self.calls.append(("input", request_id))
        return self.conformance_input

    def transition_design_conformance(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("transition", target, detail))
        if self.fail_transition_to == target:
            raise CoreClientError(
                what="design-conformance-transition",
                verdict="ILLEGAL_TRANSITION",
                detail="테스트 강제",
            )
        self.status = target

    def presign_diff_raster_upload(self, request_id: str) -> DiffRasterUploadTarget:
        self.calls.append(("upload-url", request_id))
        return DiffRasterUploadTarget(
            object_key=f"sites/site-1/design-conformance/{request_id}",
            upload_url=_UPLOAD_URL,
            content_type="application/octet-stream",
        )

    def verify_diff_raster(
        self, request_id: str, *, digest: str, size_bytes: int
    ) -> datetime:
        self.calls.append(("verify", digest, size_bytes))
        stored = self.swap_uploaded_with if self.swap_uploaded_with is not None else self.uploaded
        assert stored is not None, "확인 전에 업로드가 있어야 한다"
        actual = f"sha256:{hashlib.sha256(stored).hexdigest()}"
        if actual != digest or len(stored) != size_bytes:
            raise CoreClientError(
                what=f"diff-raster-verification:{request_id}",
                verdict="DIFF_RASTER_DIGEST_MISMATCH",
                detail=f"Core 재해싱 {actual}, 신고 {digest}",
            )
        return self.verified_at

    def submit_design_conformance(
        self, mission_id: str, report: DesignConformanceReport
    ) -> None:
        self.calls.append(("submit", mission_id, report.design_conformance_id))
        if self.duplicate_report:
            raise CoreClientError(
                what=f"design-conformance:{report.design_conformance_id}",
                verdict="DUPLICATE_REPORT_ID",
                detail="테스트 강제(재시도 시뮬레이션)",
            )
        self.submitted.append((mission_id, report))


def _transport(core: FakeCore, files: dict[str, Path]) -> httpx.MockTransport:
    """GET 은 원본 래스터를, PUT 은 업로드 바이트를 가짜 Core 에 넘긴다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            core.uploaded = request.content
            return httpx.Response(200)
        path = files.get(request.url.path.rsplit("/", 1)[-1])
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.MockTransport(handler)


def _input(
    design_sha256: str,
    *,
    design_vertical: Any = _DESIGN_VERTICAL,
    policy: ComparisonPolicy | None = None,
    status: str = "QUEUED",
) -> DesignConformanceInput:
    return DesignConformanceInput(
        request_id=_REQUEST_ID,
        mission_id="mission-1",
        status=status,
        policy=policy or current_comparison_policy(),
        design_conformance_id=_REQUEST_ID,
        diff_raster_id=f"{_REQUEST_ID}-diff",
        design_surface_id="site-1-ds1",
        design_surface_sha256=design_sha256,
        design_surface_url="https://storage.invalid/design",
        design_vertical_reference=design_vertical,
        current=ArtifactRef(job_id="job-1", artifact_id="dsm"),
        current_url="https://storage.invalid/current-dsm",
        current_vertical_reference=_CURRENT_VERTICAL,
        zones={"zone-all": _full_extent_zone()},
        zone_crs=_CRS,
    )


@pytest.fixture
def scene(tmp_path: Path) -> tuple[FakeCore, httpx.Client]:
    """경사 현재 지형 + 평탄 설계면(5단계 골든 배치) 위에 워커를 세운다."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")
    core = FakeCore(conformance_input=_input(design_sha))
    client = httpx.Client(
        transport=_transport(core, {"current-dsm": current_path, "design": design_path})
    )
    return core, client


def test_full_success_path_uploads_verifies_submits_and_succeeds(
    scene: tuple[FakeCore, httpx.Client], tmp_path: Path
) -> None:
    """[핵심] 업로드된 바이트를 Core 가 재해싱해 확인한 뒤에만 리포트가 제출된다."""
    core, client = scene
    run_design_conformance_request(
        _REQUEST_ID,
        core=core,
        work_dir=tmp_path / "work",
        http_client=client,
        now_message=lambda _msg: None,
    )

    order = [call[0] for call in core.calls]
    assert order == [
        "lease",
        "input",
        "transition",  # QUEUED → RUNNING
        "upload-url",
        "verify",
        "submit",
        "transition",  # → SUCCEEDED
    ]
    assert core.status == "SUCCEEDED"

    assert core.uploaded is not None
    mission_id, report = core.submitted[0]
    assert mission_id == "mission-1"
    # 리포트가 실은 digest 는 **실제로 올라간 바이트**의 해시다.
    assert report.diff_raster.digest == f"sha256:{hashlib.sha256(core.uploaded).hexdigest()}"
    assert report.diff_raster.size_bytes == len(core.uploaded)
    # 확인 시각은 Core 가 준 값이다(워커가 지어내지 않는다).
    assert report.diff_raster.core_verified_digest_at == core.verified_at
    # 부호 규약이 워커 경유에서도 유지된다(5단계 골든과 같은 값).
    zone = report.zones[0]
    assert zone.fill_m3 == pytest.approx(_EXPECTED_FILL_M3)
    assert zone.cut_m3 == pytest.approx(_EXPECTED_CUT_M3)
    assert zone.uncertainty_m3 is None


def test_worker_does_not_clean_up_before_submitting(
    scene: tuple[FakeCore, httpx.Client], tmp_path: Path
) -> None:
    """제출까지 끝난 뒤 작업 디렉터리에 래스터가 남지 않는다(누수 없음)."""
    core, client = scene
    work_dir = tmp_path / "work"
    run_design_conformance_request(
        _REQUEST_ID, core=core, work_dir=work_dir, http_client=client,
        now_message=lambda _msg: None,
    )
    assert core.submitted, "제출이 있어야 한다"
    assert not list(work_dir.glob("design-conformance-*")), "임시 래스터가 남았다"


def test_digest_mismatch_at_verification_prevents_any_report(
    scene: tuple[FakeCore, httpx.Client], tmp_path: Path
) -> None:
    """[핵심] Core 가 확인을 거부하면 **리포트 자체가 만들어지지 않는다.**

    ``coreVerifiedDigestAt`` 이 계약 필수 필드라, 확인 없이는 리포트를 조립할 수
    없다 — 워커가 "그래도 제출"을 선택할 여지가 구조적으로 없다.
    """
    core, client = scene
    core.swap_uploaded_with = b"someone-else-wrote-here"

    with pytest.raises(DesignConformanceWorkerRunError, match="DIFF_RASTER_DIGEST_MISMATCH"):
        run_design_conformance_request(
            _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
            now_message=lambda _msg: None,
        )

    assert core.submitted == []
    assert core.status == "FAILED"
    failed = [call for call in core.calls if call[0] == "transition" and call[1] == "FAILED"]
    assert failed and "DIFF_RASTER_DIGEST_MISMATCH" in str(failed[0][2])


def test_incompatible_vertical_datum_fails_before_uploading_anything(
    tmp_path: Path,
) -> None:
    """수직기준 계열이 다르면 계산 전에 멈춘다 — 스토리지에 아무것도 올리지 않는다."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")
    core = FakeCore(
        conformance_input=_input(design_sha, design_vertical=_ORTHOMETRIC_VERTICAL)
    )
    client = httpx.Client(
        transport=_transport(core, {"current-dsm": current_path, "design": design_path})
    )

    with pytest.raises(DesignConformanceWorkerRunError, match="수직기준 계열"):
        run_design_conformance_request(
            _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
            now_message=lambda _msg: None,
        )
    assert core.uploaded is None
    assert ("upload-url", _REQUEST_ID) not in core.calls
    assert core.status == "FAILED"


def test_design_surface_bytes_that_changed_since_verification_fail(
    tmp_path: Path,
) -> None:
    """받아온 설계면이 검증 때 잰 그 파일이 아니면 숫자를 내지 않는다."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    core = FakeCore(conformance_input=_input("0" * 64))
    client = httpx.Client(
        transport=_transport(core, {"current-dsm": current_path, "design": design_path})
    )
    with pytest.raises(DesignConformanceWorkerRunError, match="설계면 바이트"):
        run_design_conformance_request(
            _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
            now_message=lambda _msg: None,
        )
    assert core.uploaded is None
    assert core.status == "FAILED"


def test_running_request_is_not_transitioned_again(
    tmp_path: Path,
) -> None:
    """재개된 요청(이미 RUNNING)에 RUNNING 전이를 다시 시도하지 않는다."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")
    core = FakeCore(conformance_input=_input(design_sha, status="RUNNING"))
    client = httpx.Client(
        transport=_transport(core, {"current-dsm": current_path, "design": design_path})
    )
    run_design_conformance_request(
        _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
        now_message=lambda _msg: None,
    )
    transitions = [call[1] for call in core.calls if call[0] == "transition"]
    assert transitions == ["SUCCEEDED"]


def test_duplicate_report_on_retry_is_treated_as_already_done(
    scene: tuple[FakeCore, httpx.Client], tmp_path: Path
) -> None:
    """designConformanceId 는 이 요청만 만들 수 있는 값이라 DUPLICATE 는 재시도다."""
    core, client = scene
    core.duplicate_report = True
    run_design_conformance_request(
        _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
        now_message=lambda _msg: None,
    )
    assert core.status == "SUCCEEDED"
    assert core.submitted == []


def test_failed_transition_failure_keeps_the_original_cause(
    scene: tuple[FakeCore, httpx.Client], tmp_path: Path
) -> None:
    """FAILED 보고까지 실패해도 원인은 그대로 올라온다(삼키지 않는다)."""
    core, client = scene
    core.swap_uploaded_with = b"tampered"
    core.fail_transition_to = "FAILED"
    with pytest.raises(DesignConformanceWorkerRunError, match="DIFF_RASTER_DIGEST_MISMATCH"):
        run_design_conformance_request(
            _REQUEST_ID, core=core, work_dir=tmp_path / "work", http_client=client,
            now_message=lambda _msg: None,
        )

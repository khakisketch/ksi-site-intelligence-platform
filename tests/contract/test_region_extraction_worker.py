"""변화 영역 추출 워커 오케스트레이션 계약 (M4-E).

이 파일이 지키는 것은 오직 오케스트레이션 자체다 — 실제 추출 계산은
packages/change-detection/tests/test_region_extraction.py 가 이미 결정성까지
고정했으므로, 여기서는 ``run_region_extraction`` 을 가짜로 갈아 끼우고 워커
골격만 본다:

1. **work_dir 청소** — 성공·실패 관계없이 다운로드한 diff 래스터 파일이
   지워진다(2026-08-13 재감사 발견을 처음부터 피해 간 새 워커가 실제로 그
   약속을 지키는지).
2. **실패는 전부 FAILED 로 수렴한다** — 좁은 예외 목록이 아니라 계산·제출
   단계의 어떤 예외든(OSError 포함) FAILED 보고를 시도하고
   RegionExtractionWorkerRunError 로 감싸 재던진다.
3. **원래 예외를 삼키지 않는다** — FAILED 보고 자체가 실패해도 원래 원인이
   살아남는다(다른 세 워커와 같은 규율).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from ksi_event_contracts.change_region_report import ChangeRegionSetReport
from ksi_event_contracts.region_extraction_policy import current_region_extraction_policy
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_processing_controller.core_client import (
    CoreClientError,
    RegionExtractionInput,
)
from ksi_processing_controller.region_extraction_worker import (
    RegionExtractionWorkerRunError,
    run_region_extraction_request,
)

_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="테스트 고정값",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


def _diff_raster_ref() -> Any:
    from ksi_event_contracts.design_conformance_report import DiffRasterRef

    return DiffRasterRef(
        diff_raster_id="dr-1",
        digest=f"sha256:{'a' * 64}",
        format="geotiff",
        crs="EPSG:5186",
        vertical_reference=_VERTICAL,
        width=4,
        height=4,
        pixel_size_x_m=1.0,
        pixel_size_y_m=1.0,
        transform=(1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0),
        nodata_encoding="nan",
        threshold_m=0.05,
        size_bytes=1234,
        core_verified_digest_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
    )


def _empty_report() -> ChangeRegionSetReport:
    return ChangeRegionSetReport(
        change_region_set_id="dc-1-rex1",
        design_conformance_id="dc-1",
        diff_raster_id="dr-1",
        crs="EPSG:5186",
        threshold_m=0.05,
        extraction_policy=current_region_extraction_policy(),
        regions=[],
        filtered_region_count=0,
        unmeasurable_cell_ratio=0.0,
        unmeasurable_area_m2=0.0,
        total_cell_count=16,
        computed_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
    )


class FakeRegionExtractionCoreClient:
    """포트 계약만 만족하는 가짜 Core — 호출 순서를 그대로 기록한다."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail_on = fail_on  # "submit" | "transition:<target>"
        self._status = "QUEUED"

    def list_pending_region_extractions(self, *, limit: int = 50) -> list[Any]:
        del limit
        return []

    def acquire_region_extraction_lease(self, request_id: str) -> None:
        self.calls.append(("lease", request_id))

    def get_region_extraction_input(self, request_id: str) -> RegionExtractionInput:
        self.calls.append(("get_input", request_id))
        return RegionExtractionInput(
            request_id=request_id,
            mission_id="mission-1",
            status=self._status,
            design_conformance_id="dc-1",
            change_region_set_id="dc-1-rex1",
            diff_raster_id="dr-1",
            diff_raster_url="http://fake/dr-1.tif",
            diff_raster=_diff_raster_ref(),
            threshold_m=0.05,
            crs="EPSG:5186",
            extraction_policy=current_region_extraction_policy(),
        )

    def transition_region_extraction(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("transition", target, detail))
        if self.fail_on == f"transition:{target}":
            raise CoreClientError(
                what="transition", verdict="ILLEGAL_TRANSITION", detail="테스트 강제 실패"
            )
        self._status = target

    def submit_region_extraction(self, mission_id: str, report: ChangeRegionSetReport) -> None:
        self.calls.append(("submit", mission_id, report.change_region_set_id))
        if self.fail_on == "submit":
            raise CoreClientError(
                what="submit", verdict="DIGEST_MISMATCH", detail="테스트 강제 실패"
            )


def _worker_http_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))


# ── work_dir 청소 ──────────────────────────────────────────────────────────


def test_work_dir_is_emptied_after_a_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.region_extraction_worker as worker_module

    def _fake_run(*, raster_path: Path, **kwargs: Any) -> ChangeRegionSetReport:
        del kwargs
        raster_path.write_bytes(b"pretend-geotiff-bytes")
        return _empty_report()

    monkeypatch.setattr(worker_module, "run_region_extraction", _fake_run)

    core = FakeRegionExtractionCoreClient()
    run_region_extraction_request(
        "req-1", core=core, work_dir=tmp_path, http_client=_worker_http_client(),
        heartbeat_interval_seconds=1000,
    )

    assert list(tmp_path.iterdir()) == [], "성공했는데 work_dir 에 파일이 남았다"
    assert any(c[0] == "transition" and c[1] == "SUCCEEDED" for c in core.calls)


def test_work_dir_is_emptied_after_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.region_extraction_worker as worker_module

    def _fake_run(*, raster_path: Path, **kwargs: Any) -> ChangeRegionSetReport:
        del kwargs
        raster_path.write_bytes(b"partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(worker_module, "run_region_extraction", _fake_run)

    core = FakeRegionExtractionCoreClient()
    with pytest.raises(RegionExtractionWorkerRunError, match="No space left on device"):
        run_region_extraction_request(
            "req-1", core=core, work_dir=tmp_path, http_client=_worker_http_client(),
            heartbeat_interval_seconds=1000,
        )

    assert list(tmp_path.iterdir()) == [], "실패했는데 부분 파일이 work_dir 에 남았다"


# ── 실패는 전부 FAILED 로 수렴한다 ─────────────────────────────────────────


def test_a_disk_write_failure_is_reported_as_failed_not_left_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[회귀] OSError 처럼 좁은 예외 목록에는 안 걸리는 오류도 FAILED 로 수렴한다."""
    import ksi_processing_controller.region_extraction_worker as worker_module

    def _fake_run(*, raster_path: Path, **kwargs: Any) -> ChangeRegionSetReport:
        del raster_path, kwargs
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(worker_module, "run_region_extraction", _fake_run)

    core = FakeRegionExtractionCoreClient()
    with pytest.raises(RegionExtractionWorkerRunError, match="No space left on device"):
        run_region_extraction_request(
            "req-1", core=core, work_dir=tmp_path, http_client=_worker_http_client(),
            heartbeat_interval_seconds=1000,
        )

    failed_calls = [c for c in core.calls if c[0] == "transition" and c[1] == "FAILED"]
    assert len(failed_calls) == 1, "OSError 가 FAILED 보고 없이 새어나갔다"
    assert "No space left on device" in (failed_calls[0][2] or "")


def test_submit_rejection_transitions_to_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.region_extraction_worker as worker_module

    monkeypatch.setattr(
        worker_module, "run_region_extraction", lambda **kwargs: _empty_report()
    )

    core = FakeRegionExtractionCoreClient(fail_on="submit")
    with pytest.raises(RegionExtractionWorkerRunError):
        run_region_extraction_request(
            "req-1", core=core, work_dir=tmp_path, http_client=_worker_http_client(),
            heartbeat_interval_seconds=1000,
        )

    assert any(c[0] == "transition" and c[1] == "FAILED" for c in core.calls)


def test_original_exception_is_not_swallowed_even_if_failed_report_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] FAILED 보고 자체가 실패해도(lease 만료 등) 원래 예외가 살아남는다."""
    import ksi_processing_controller.region_extraction_worker as worker_module

    def _fake_run(*, raster_path: Path, **kwargs: Any) -> ChangeRegionSetReport:
        del raster_path, kwargs
        raise ValueError("계산 자체가 깨졌다(테스트 강제)")

    monkeypatch.setattr(worker_module, "run_region_extraction", _fake_run)

    core = FakeRegionExtractionCoreClient(fail_on="transition:FAILED")
    with pytest.raises(RegionExtractionWorkerRunError) as excinfo:
        run_region_extraction_request(
            "req-1", core=core, work_dir=tmp_path, http_client=_worker_http_client(),
            heartbeat_interval_seconds=1000,
        )

    cause = excinfo.value.__cause__
    assert isinstance(cause, ValueError)
    assert "계산 자체가 깨졌다" in str(cause), (
        f"FAILED 보고 실패가 원래 원인을 가렸다: {cause}"
    )

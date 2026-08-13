"""설계면 검증 워커 계약 (M4-A 6단계 — 워커는 재고, Core 가 판정한다).

초점 넷:

1. **실측이다** — 값이 전부 파일에서 나온다(지어낼 수 있는 자리가 없다).
2. **판정하지 않는다** — 3밴드도 유효셀 0도 그대로 담아 보낸다. 거부는 Core 가
   typed verdict 로 내려야 사용자에게 이유가 간다.
3. **세 가지 실패를 가른다** — 다운로드 실패는 재시도(예외), 열지 못함은
   ``verification-failure`` 보고, 잘 열리면 관측 보고.
4. **워커의 측정이 Core 의 대조를 실제로 통과한다** — 문자열 표기(``EPSG:5186``)
   가 어긋나면 정상 파일이 거부되므로, 종단으로 한 번 붙여서 확인한다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.sites import SiteFrame, SiteStore
from ksi_processing_controller.core_client import DesignSurfaceMeasurement, PendingDesignSurface
from ksi_processing_controller.design_surface_verifier import (
    DesignSurfaceMeasurementError,
    measure_design_surface,
    verify_design_surface,
)
from rasterio.transform import from_origin

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 500_000.0
_SITE_ID = "site-001"
_NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
_ADMIN_TOKEN = "verifier-admin"  # noqa: S105 -- 테스트 고정값
_WORKER_TOKEN = "verifier-worker"  # noqa: S105
_DOWNLOAD_URL = "https://storage.example/get/design-surface"


def _write_design_surface(
    path: Path,
    *,
    crs: Any = "EPSG:5186",
    size: int = 8,
    pixel_size_m: float = 0.5,
    bands: int = 1,
    all_nodata: bool = False,
) -> Path:
    """경사면 하나 — 값이 전부 유한하거나(기본) 전부 NaN 이다."""
    fill = np.nan if all_nodata else 1.0
    values = np.full((size, size), fill, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=bands,
        dtype="float32",
        crs=crs,
        nodata=float("nan"),
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, pixel_size_m, pixel_size_m),
    ) as dataset:
        for band in range(1, bands + 1):
            dataset.write(values, band)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _FakeCore:
    """``DesignSurfaceCoreClient`` 를 만족하는 최소 구현 — 무엇이 갔는지만 본다."""

    def __init__(self, *, verdict: str = "VERIFIED") -> None:
        self.verdict = verdict
        self.observations: list[tuple[str, DesignSurfaceMeasurement]] = []
        self.failures: list[tuple[str, str | None]] = []

    def list_pending_design_surfaces(self, *, limit: int = 50) -> list[PendingDesignSurface]:
        del limit
        return []

    def report_design_surface_observation(
        self, design_surface_id: str, measurement: DesignSurfaceMeasurement
    ) -> str:
        self.observations.append((design_surface_id, measurement))
        return self.verdict

    def report_design_surface_verification_failure(
        self, design_surface_id: str, *, detail: str | None = None
    ) -> None:
        self.failures.append((design_surface_id, detail))


def _client_serving(path: Path | None, *, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if path is None:
            return httpx.Response(status, text="스토리지 장애")
        return httpx.Response(status, content=path.read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── 실측 ────────────────────────────────────────────────────────────────


def test_measurement_reports_what_is_in_the_file(tmp_path: Path) -> None:
    path = _write_design_surface(tmp_path / "design.tif", size=8, pixel_size_m=0.5)

    measurement = measure_design_surface(path)

    assert measurement.sha256 == _sha256(path)
    assert measurement.crs == "EPSG:5186"
    assert measurement.vertical_crs_epsg is None
    assert (measurement.width, measurement.height) == (8, 8)
    assert measurement.band_count == 1
    assert measurement.dtype == "float32"
    assert measurement.pixel_size_x_m == pytest.approx(0.5)
    assert measurement.pixel_size_y_m == pytest.approx(0.5)
    # 화소 크기는 부호 없는 크기이고, 방향은 transform 이 그대로 든다.
    assert measurement.transform[4] == pytest.approx(-0.5)
    assert measurement.bounds_min_x == pytest.approx(_ORIGIN_X)
    assert measurement.bounds_max_y == pytest.approx(_ORIGIN_Y)
    assert measurement.finite_cell_count == 64
    # NaN nodata 는 JSON 에 실을 수 없어 불리언으로 옮긴다(계약 규약).
    assert measurement.nodata is None
    assert measurement.nodata_is_nan is True


def test_compound_crs_is_split_into_horizontal_and_vertical(tmp_path: Path) -> None:
    """수평 성분만 선언과 대조된다 — 전체 표기를 그대로 보내면 정상 파일이 거부된다."""
    from pyproj import CRS
    from pyproj.crs import CompoundCRS

    compound = CompoundCRS(
        name="KGD2002 중부원점 + KVD1964 정표고",
        components=[CRS.from_epsg(5186), CRS.from_epsg(5193)],
    )
    path = _write_design_surface(tmp_path / "compound.tif", crs=compound.to_wkt())

    measurement = measure_design_surface(path)

    assert measurement.crs == "EPSG:5186"
    assert measurement.vertical_crs_epsg == 5193


def test_bad_looking_rasters_are_measured_not_judged(tmp_path: Path) -> None:
    """3밴드·유효셀 0 을 **담을 수 있어야** Core 가 사유를 붙여 거부할 수 있다."""
    multiband = measure_design_surface(
        _write_design_surface(tmp_path / "rgb.tif", bands=3)
    )
    assert multiband.band_count == 3

    empty = measure_design_surface(
        _write_design_surface(tmp_path / "empty.tif", all_nodata=True)
    )
    assert empty.finite_cell_count == 0


def test_unopenable_file_is_a_measurement_error(tmp_path: Path) -> None:
    path = tmp_path / "not-a-tiff.tif"
    path.write_bytes("이건 GeoTIFF 가 아니다".encode())
    with pytest.raises(DesignSurfaceMeasurementError, match="열 수 없다"):
        measure_design_surface(path)


def test_raster_without_crs_is_a_measurement_error(tmp_path: Path) -> None:
    """좌표계가 없는 래스터는 '다른 파일'이 아니라 **대조할 수 없는 파일**이다."""
    path = tmp_path / "no-crs.tif"
    values = np.zeros((4, 4), dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32"
    ) as dataset:
        dataset.write(values, 1)
    with pytest.raises(DesignSurfaceMeasurementError, match="좌표계"):
        measure_design_surface(path)


# ── 세 가지 실패의 분리 ──────────────────────────────────────────────────


def test_measured_file_is_reported_as_an_observation(tmp_path: Path) -> None:
    path = _write_design_surface(tmp_path / "design.tif")
    core = _FakeCore()
    with _client_serving(path) as http_client:
        verdict = verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=tmp_path / "work",
        )

    assert verdict == "VERIFIED"
    assert not core.failures
    assert [i for i, _ in core.observations] == ["site-001-ds1"]
    assert core.observations[0][1].sha256 == _sha256(path)


def test_unreadable_file_goes_to_the_failure_path_not_the_observation_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "broken.tif"
    path.write_bytes(b"broken")
    core = _FakeCore()
    with _client_serving(path) as http_client:
        verdict = verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=tmp_path / "work",
        )

    assert verdict == "REJECTED"
    assert not core.observations
    assert [i for i, _ in core.failures] == ["site-001-ds1"]


def test_download_failure_is_raised_and_never_reported_as_unreadable(tmp_path: Path) -> None:
    """네트워크 사고 한 번으로 멀쩡한 설계면이 **영구 거부**되면 안 된다."""
    core = _FakeCore()
    with (
        _client_serving(None, status=503) as http_client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=tmp_path / "work",
        )

    assert not core.failures
    assert not core.observations


# ── work_dir 청소 (2026-08-13 프로젝트 두뇌 재감사 확정 발견의 회귀 방지) ──
#
# 이 워커는 정리 코드가 아예 없었다 — 검증마다(자주·값싸게 도는 것이 이
# 워커의 설계 의도) 내려받은 GeoTIFF 를 work_dir 에 영구히 남겼다. 세 완주
# 경로(검증 완료·거부·다운로드 실패) 모두에서 지워지는지 본다.


def test_verified_run_leaves_no_file_behind(tmp_path: Path) -> None:
    path = _write_design_surface(tmp_path / "design.tif")
    work_dir = tmp_path / "work"
    core = _FakeCore()
    with _client_serving(path) as http_client:
        verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=work_dir,
        )

    assert list(work_dir.iterdir()) == [], "검증 성공했는데 work_dir 에 파일이 남았다"


def test_rejected_run_leaves_no_file_behind(tmp_path: Path) -> None:
    broken = tmp_path / "broken.tif"
    broken.write_bytes(b"broken")
    work_dir = tmp_path / "work"
    core = _FakeCore()
    with _client_serving(broken) as http_client:
        verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=work_dir,
        )

    assert list(work_dir.iterdir()) == [], "거부됐는데 work_dir 에 파일이 남았다"


def test_download_failure_leaves_no_partial_file_behind(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    core = _FakeCore()
    with (
        _client_serving(None, status=503) as http_client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=work_dir,
        )

    assert not work_dir.exists() or list(work_dir.iterdir()) == [], (
        "다운로드가 실패했는데 부분 파일이 work_dir 에 남았다"
    )


def test_core_rejection_is_a_normal_completion(tmp_path: Path) -> None:
    """거부는 워커의 실패가 아니다 — 같은 파일을 다시 읽어도 결과는 같다."""
    path = _write_design_surface(tmp_path / "design.tif")
    core = _FakeCore(verdict="REJECTED")
    with _client_serving(path) as http_client:
        verdict = verify_design_surface(
            "site-001-ds1",
            download_url=_DOWNLOAD_URL,
            core=core,
            http_client=http_client,
            work_dir=tmp_path / "work",
        )
    assert verdict == "REJECTED"


# ── 종단: 워커의 측정 → Core 의 대조 ─────────────────────────────────────


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _StubStorage:
    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://storage.example/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://storage.example/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError

    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _core_app(tmp_path: Path) -> TestClient:
    site_journal = DurableJournal(tmp_path / "sites.jsonl")
    site_store = SiteStore(site_journal)
    assert (
        site_store.register(
            _SITE_ID,
            "테스트 현장",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="KNG2018",
                transform_version="v1",
                unit="meter",
            ),
            data_residency=None,
            actor="op-1",
            now=_NOW,
        ).verdict.value
        == "REGISTERED"
    )
    app = create_app(
        auth_registry=AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest(_ADMIN_TOKEN),
                    principal=Principal(
                        principal_id="op-1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                    ),
                ),
                PrincipalTokenRecord(
                    token_sha256=_digest(_WORKER_TOKEN),
                    principal=Principal(
                        principal_id="worker-1",
                        kind=PrincipalKind.PROCESSING_WORKER,
                        role=None,
                        device_id=None,
                    ),
                ),
            ]
        ),
        site_store=site_store,
        design_surface_store=DesignSurfaceStore(
            DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=site_store
        ),
        evidence_storage=_StubStorage(),
    )
    return TestClient(app)


def _register_and_seal(client: TestClient, *, sha256: str, declared_crs: str) -> str:
    registered = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        json={
            "name": "A공구 계획고",
            "revision": "Rev.C",
            "declared": {
                "crs": declared_crs,
                "lengthUnit": "meter",
                "sha256": sha256,
                "verticalReference": {
                    "datum": "ellipsoidal",
                    "basis": "도면 표제부에 타원체고 명시",
                    "source": "user_declared",
                },
            },
        },
    )
    assert registered.status_code == 201, registered.text
    design_surface_id = str(registered.json()["designSurfaceId"])
    sealed = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
    )
    assert sealed.status_code == 201
    return design_surface_id


def _post_measurement(
    client: TestClient, design_surface_id: str, measurement: DesignSurfaceMeasurement
) -> Any:
    return client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers={"Authorization": f"Bearer {_WORKER_TOKEN}"},
        json={
            "sha256": measurement.sha256,
            "crs": measurement.crs,
            "verticalCrsEpsg": measurement.vertical_crs_epsg,
            "width": measurement.width,
            "height": measurement.height,
            "bandCount": measurement.band_count,
            "dtype": measurement.dtype,
            "nodata": measurement.nodata,
            "nodataIsNan": measurement.nodata_is_nan,
            "pixelSizeXM": measurement.pixel_size_x_m,
            "pixelSizeYM": measurement.pixel_size_y_m,
            "transform": list(measurement.transform),
            "boundsMinX": measurement.bounds_min_x,
            "boundsMinY": measurement.bounds_min_y,
            "boundsMaxX": measurement.bounds_max_x,
            "boundsMaxY": measurement.bounds_max_y,
            "finiteCellCount": measurement.finite_cell_count,
        },
    )


def test_worker_measurement_passes_cores_comparison(tmp_path: Path) -> None:
    """실제 GeoTIFF 를 재서 보낸 값이 Core 의 대조를 통과한다.

    문자열 표기가 어긋나면(예: 워커가 WKT 를 보내고 Core 가 ``EPSG:5186`` 을
    기대하면) 정상 파일이 거부된다 — 그 자리를 종단으로 한 번 붙여서 막는다.
    """
    path = _write_design_surface(tmp_path / "design.tif")
    client = _core_app(tmp_path)
    design_surface_id = _register_and_seal(
        client, sha256=_sha256(path), declared_crs="EPSG:5186"
    )

    response = _post_measurement(client, design_surface_id, measure_design_surface(path))

    assert response.status_code == 201, response.text
    assert response.json()["verdict"] == "VERIFIED"


def test_file_in_another_crs_than_declared_is_refused_end_to_end(tmp_path: Path) -> None:
    """EPSG:5187 파일을 5186 이라고 선언해 올리면 사람 말 사유가 붙어 거부된다."""
    path = _write_design_surface(tmp_path / "east.tif", crs="EPSG:5187")
    client = _core_app(tmp_path)
    design_surface_id = _register_and_seal(
        client, sha256=_sha256(path), declared_crs="EPSG:5186"
    )

    response = _post_measurement(client, design_surface_id, measure_design_surface(path))

    assert response.status_code == 422
    assert response.json()["rejectionReason"] == "CRS_DECLARATION_MISMATCH"
    assert "좌표계" in response.json()["detail"]

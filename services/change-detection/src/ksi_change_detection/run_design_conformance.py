"""설계 대비 잔량 계산 — "설계까지 얼마나 더 깎고 더 쌓아야 하나" (M4-A).

## 새 파이프라인이 아니라 입력이 하나 더 생긴 것

``run_volume_change`` 는 **두 시점**을 뺀다. 이 모듈은 **설계면과 현재 지형**을
뺀다. 계산 엔진(``align_and_diff`` → ``volume_delta_in_polygon``)은 글자 그대로
같은 것을 쓴다 — 그 함수들은 입력이 epoch DSM 인지 설계 DEM 인지 신경 쓰지
않는다. 그래서 여기서 새로 지는 책임은 셋뿐이다: **부호를 뒤집지 않는 것**,
**측정물이 아닌 입력의 오차한계를 지어내지 않는 것**, **집계에 쓴 격자를 그대로
지도에 넘기는 것**.

## 부호 규약 — 이 모듈에서 가장 틀리기 쉬운 한 줄

``align_and_diff(baseline, current)`` 는 ``current - baseline`` 을 낸다.
``volume_delta_in_polygon`` 은 ``delta > 0 → fill``, ``delta < 0 → cut`` 으로 센다.

설계 대비 잔량에서 원하는 뜻은 이것이다:

.. code-block:: text

    delta = 설계 표고 − 현재 표고
      > 0  설계가 더 높다 → 쌓아야 한다 → fill_m3   ✓
      < 0  설계가 더 낮다 → 깎아야 한다 → cut_m3    ✓
    net = fill − cut = 순 성토 필요량                ✓

그러려면 **``baseline`` 자리에 현재 DSM 을, ``current`` 자리에 설계면을** 넣어야
한다. 인자 이름과 실제 의미가 정반대라, 그 뒤집기는 **이 함수 안에서 딱 한 번**
일어나고 호출부에는 절대 노출하지 않는다(``compute_design_conformance`` 는
``current_dsm=``·``design=`` 으로만 받는다). 부호가 두 곳에서 뒤집히면 한쪽만
고쳐지는 날이 오고, 그날 화면은 "1100m³ 쌓아야 함"을 "1100m³ 깎아야 함"으로
바꿔 말하면서도 여전히 그럴듯하다.

덤으로 이 순서는 격자도 옳게 고른다 — ``align_and_diff`` 는 baseline 의 격자를
기준으로 삼으므로, 결과 래스터는 **실측된 현재 지형의 해상도·정렬**을 따르고
설계면이 그 위로 재표본된다.

## 오차한계는 항상 None 이다 (INV-024)

``uncertainty_m3`` 는 **양쪽 입력 모두** 독립 검사점으로 검증된 RMSE 를 가질
때만 값이다. 설계면은 측정물이 아니라 **의도**이므로 RMSE 라는 것이 존재하지
않는다 — 0 으로 두면 "설계면은 완벽히 정확하다"는 주장이 되고, 현재 DSM 쪽
RMSE 만으로 계산하면 "검증된 한쪽만큼만 틀릴 수 있다"는 거짓말이 된다. 그래서
두 값 다 ``None`` 을 넘기고, 사유를 리포트에 실어 화면까지 보낸다.

## 수직기준은 계산 **전**에 판정하고, 계산 **안**에서 잇는다

타원체고와 정표고를 그냥 빼면 한국에서 20~30m 가 조용히 섞이고 결과는 여전히
숫자다. 그래서 ``assert_bridgeable_vertical`` 을 다운로드보다도 먼저 부른다 —
어차피 거부할 계산에 스토리지 바이트를 쓰지 않는다. Core 도 요청 생성 시점에
같은 판정을 하지만(fail-closed 는 요청 경로), 계산 엔진이 그 판정을 **자기
입구에서도** 강제하지 않으면 다른 호출자가 생기는 날 조용히 뚫린다(``dsm_diff``
가 CRS 를 자기 입구에서 다시 보는 것과 같은 근거).

**판정과 변환이 갈라져 있는 이유**(대표자 결정 2026-08-12 "자동으로 맞춰서
계산한다"): 실무 설계도면은 거의 항상 정표고(해발)이고 우리 재구성 파이프라인은
타원체고를 낸다. 둘을 잇는 지오이드고 N 은 격자 파일에서만 나오는데, 그 파일이
붙어 있는 곳은 **워커의 환경**(``KSI_GEOID_GRID``)이지 Core 가 아니다. 그래서

- Core: "이 두 기준을 이을 수 있는 종류인가"라는 **순수 표 판정**만 한다.
- 여기: 격자를 실제로 읽어 **설계면 높이를 현재 DSM 의 계열로 올린다.**

옮기는 쪽은 **언제나 설계면**이다. 차분 격자의 수직기준은 실측된 현재 DSM 의
것을 승계하므로(:func:`_diff_vertical_reference`), 측정물을 건드리면 지도가
말하는 기준 자체가 바뀐다. 설계면은 보통 더 성긴 격자라 비용도 그쪽이 싸다.

격자가 없으면(``KSI_GEOID_GRID`` 미설정 또는 읽기 실패) 숫자를 만들지 않는다.
그 거부는 :class:`~ksi_geo_spatial.vertical.GeoidUnavailableError` 이고,
"수직기준이 근본적으로 이어지지 않는다"(``VerticalDatumIncompatibleError``) 와
**다른 타입**이다 — 사람이 받는 사유가 "격자를 붙여라"와 "이 도면은 못 쓴다"로
갈라져야 하기 때문이다.

## N 은 셀마다 다르다 — 구역 대표점 하나로 상수 보정하지 않는다

지오이드고는 위치의 함수다. 현장 하나 안에서 얼마나 변하는지를 실 격자
(``data/geoid/KNGeoid24.tif``, 셀 간격 0.01636° ≈ 1.82km)로 재 보면:

- 전국 |∇N| 중앙값 0.028 m/km, 상위 5% 0.0495 m/km, 최대 0.1376 m/km.
- 1km 현장에서 중심 한 점의 N 을 상수로 쓰면 최대 편차 0.011~0.041m
  (서울·부산·판교·속초·제주 실측), 2km 현장에서는 0.083m 까지 벌어진다.

이 크기는 집계 문턱(``policy.volumeThresholdM`` 기본 0.05m)과 같은 자릿수다.
게다가 상수 보정의 오차는 **기울기**라서 현장 한쪽은 성토로, 반대쪽은 절토로
쏠린다 — 실 격자로 적분해 보면 1km² 현장에서 |오차|·면적이 4,500~13,300 m³,
2km 각 현장에서 107,000 m³ 다(순증감에서는 상당 부분 상쇄돼 **보이지 않지만**
cut·fill 은 따로 보고되는 값이다).

비용은 실측으로 **100만 셀(1m 격자 1km²) 1.2초**다(격자 조회 자체는 셀당 1.1µs,
나머지는 좌표변환·래스터 입출력). 같은 함수 안의 다운로드·재투영과 같은
자릿수다. 정확도가 문턱과 같은 자릿수로 걸려 있고 비용은 파이프라인의 잡음
수준이라, **셀별 보간이 답이다.**

## 왜 래스터 업로드가 이 함수 한가운데 있나

:class:`~ksi_event_contracts.design_conformance_report.DiffRasterRef` 의
``coreVerifiedDigestAt`` 은 "**Core 가 업로드된 바이트를 직접 재해싱해 확인한
시각**"이고 필수 필드다. 즉 리포트는 래스터가 업로드되고 확인된 **뒤에만**
만들어질 수 있다. 그 순서를 문서로만 적어두면 지켜지지 않으므로, 확인 시각을
돌려주는 :class:`DiffRasterPublisher` 를 주입받아 **확인 없이는 리포트를 만들 수
없게** 만든다. 리포트 자체의 제출은 여전히 호출자 몫이다(``run_volume_change`` 가
계산과 제출을 나눈 것과 같은 이유 — 제출 실패가 계산을 되돌리게 하지 않는다).
"""

from __future__ import annotations

import logging
import math
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
import rasterio
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.vertical_reference import (
    VerticalBridge,
    VerticalDatumFamily,
    VerticalReference,
    VerticalReferenceSource,
    assert_bridgeable_vertical,
    family_of,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from ksi_geo_spatial.crs import assert_supported_project_crs
from ksi_geo_spatial.vertical import (
    GEOID_GRID_ENV,
    GeoidGrid,
    GeoidUnavailableError,
    ellipsoidal_to_orthometric,
    orthometric_to_ellipsoidal,
)
from rasterio.transform import xy as raster_cell_centre
from rasterio.warp import transform as warp_coordinates

from ksi_change_detection.diff_raster import sha256_of_file, write_diff_geotiff
from ksi_change_detection.download_errors import download_failure_detail
from ksi_change_detection.dsm_diff import DsmDiffError, align_and_diff, volume_delta_in_polygon

logger = logging.getLogger(__name__)

#: 왜 설계 대비 잔량에는 오차한계가 없는가 — 리포트에 그대로 실려 화면까지 간다
#: (INV-024, 모듈 docstring "오차한계는 항상 None").
DESIGN_SURFACE_NOT_MEASURED_NOTE = (
    "설계면은 측정물이 아니라 의도라서 검사점 RMSE 가 존재하지 않는다 — 오차한계는 "
    "양쪽 입력이 모두 독립 검사점으로 검증됐을 때만 낼 수 있다. 이 값은 현재 지형과 "
    "설계면의 표고차를 그대로 적분한 상대량이다"
)


#: 지오이드 보정을 한 번에 처리할 셀 수 — 경위도 변환이 파이썬 리스트를 거치므로
#: (``rasterio.warp.transform`` 의 반환형) 한 덩어리가 크면 메모리가 튄다.
#: 100만 셀이면 리스트 두 개가 수십 MB 수준이고, 호출 오버헤드는 무시할 만하다.
_GEOID_CHUNK_CELLS = 1_000_000


class DesignConformanceRunError(RuntimeError):
    """설계 대비 계산이 성립하지 않는다 — 부분 결과를 리포트로 만들지 않는다."""


@dataclass(frozen=True, slots=True)
class CurrentDsmSource:
    """비교 대상인 현재 지형 산출물 — 참조 + 바이트를 받을 URL + 수직기준.

    ``run_volume_change.ArtifactSource`` 와 모양이 비슷하지만 그것을 쓰지 않는다.
    저쪽은 ``rmse_m`` 을 싣고 ``vertical_reference`` 가 없다 — 설계 대비 경로는
    정확히 그 반대가 필요하다(RMSE 는 어차피 쓸 수 없고, 수직기준은 없으면 계산
    자체를 거부해야 한다). 필드 하나를 옵션으로 덧대 두 뜻을 겸하게 하면 "왜
    None 인가"가 호출부마다 달라진다.
    """

    ref: ArtifactRef
    download_url: str
    vertical_reference: VerticalReference


@dataclass(frozen=True, slots=True)
class DesignSource:
    """비교 기준인 설계면 — **VERIFIED 자산의 스냅샷**.

    ``sha256`` 은 접두사 없는 원시 16진(``DesignSurface.observed.sha256``)이다.
    매 실행마다 설계면을 재측정하지는 않지만(VERIFIED 는 한 번), 받아온 바이트가
    그때 잰 그 파일인지는 **매번** 확인한다 — 값싸고, 스토리지 교체·손상·잘못된
    URL 을 잡는다.
    """

    design_surface_id: str
    sha256: str
    download_url: str
    vertical_reference: VerticalReference


class DiffRasterPublisher(Protocol):
    """차분 래스터를 올리고 **Core 가 확인한 시각**을 돌려주는 쪽.

    반환값은 워커가 "올렸다"고 말한 시각이 아니라 **Core 가 업로드된 객체를 직접
    다시 해싱해 ``digest`` 와 같음을 확인한 시각**이다(``DiffRasterRef.
    coreVerifiedDigestAt``). 확인이 없었다면 이 메서드는 값을 돌려주는 대신
    예외를 내야 한다 — 그래야 리포트가 만들어지지 않는다.
    """

    def publish_diff_raster(self, path: Path, *, digest: str, size_bytes: int) -> datetime:
        ...


def compute_design_conformance(
    *,
    design_conformance_id: str,
    diff_raster_id: str,
    current_dsm: CurrentDsmSource,
    design: DesignSource,
    zones: Mapping[str, dict[str, Any]],
    zone_crs: str,
    policy: ComparisonPolicy,
    computed_at: datetime,
    http_client: httpx.Client,
    publish_diff_raster: DiffRasterPublisher,
    geoid_grid: GeoidGrid | None = None,
    work_dir: Path | None = None,
    uncertainty_note: str = DESIGN_SURFACE_NOT_MEASURED_NOTE,
) -> tuple[DesignConformanceReport, Path]:
    """설계면과 현재 DSM 을 받아 구역별 잔량을 재고 리포트를 만든다(제출하지 않는다).

    Args:
        design_conformance_id: 결과 원장의 id — 요청 id 에서 결정적으로 도출된 값을
            호출자가 넘긴다(이 함수가 만들면 재실행이 매번 다른 리포트가 된다).
        diff_raster_id: 차분 래스터 자산 id. 위와 같은 이유로 호출자가 준다.
        current_dsm: 지금 현장이 어떤 모양인가(실측 산출물).
        design: 어떤 모양이어야 하는가(VERIFIED 설계면).
        zones: ``{zoneId: GeoJSON Polygon}``. 구역은 호출자가 명시적으로 준다 —
            ``run_volume_change`` 와 같은 근거(현장 AOI 를 암묵 기본값으로 삼지 않는다).
        zone_crs: 그 폴리곤들의 좌표계(보통 EPSG:4326).
        policy: 이 계산이 쓰는 기준값 한 벌. **문턱값은 여기서만 온다** —
            ``policy.volumeThresholdM`` 이 곧 집계 문턱이고, 같은 값이 리포트의
            구역·래스터 참조에 함께 실린다(계약이 셋의 일치를 검증한다). 문턱을
            따로 받으면 스냅샷된 정책과 실제 쓴 값이 갈라질 수 있다.
        computed_at: 결정성을 위해 인자로 받는다(``compute_volume_change`` 관습).
        http_client: 스토리지 바이트를 받는 클라이언트.
        publish_diff_raster: 래스터를 올리고 Core 의 digest 확인 시각을 돌려주는 쪽
            (모듈 docstring "왜 래스터 업로드가 이 함수 한가운데 있나").
        geoid_grid: 정표고↔타원체고를 이을 지오이드 격자. 호출자가 주입한다
            (``load_geoid_grid()``) — 이 함수가 환경변수를 직접 읽으면 같은 입력이
            환경에 따라 다른 답을 내면서도 그 사실이 인자에 드러나지 않는다.
            계열이 같아 변환이 필요 없으면 ``None`` 이어도 된다.
        work_dir: 임시 파일을 둘 상위 디렉터리(기본: 시스템 임시 디렉터리).
        uncertainty_note: 오차한계가 없는 이유. 기본값을 바꿀 이유는 거의 없다.

    Returns:
        ``(리포트, 차분 래스터 경로)``. 래스터 파일은 **호출자가 정리한다** —
        업로드가 끝난 뒤에도 워커가 그 바이트를 다시 볼 수 있어야 하기 때문이다
        (재시도·검증). ``shutil.rmtree(path.parent)`` 로 지우면 된다.

    Raises:
        VerticalDatumIncompatibleError: 두 입력의 수직기준을 **어떤 격자로도** 이을
            수 없다 — 이 도면으로는 계산 자체가 성립하지 않는다.
        GeoidUnavailableError: 이을 수는 있는데 **격자가 없거나 범위 밖**이다 —
            위와 달리 격자를 붙이면 그대로 계산된다. 두 사유를 같은 타입으로
            뭉치면 사람이 무엇을 고쳐야 하는지 알 수 없다.
        DesignConformanceRunError: 다운로드·해시 대조·차분·집계 중 하나가 실패했다.
    """
    if not zones:
        raise DesignConformanceRunError("잴 구역이 하나도 주어지지 않았다")

    # 계산 전에 판정한다 — 이을 수 없으면 어떤 숫자도 내지 않는다(모듈 docstring).
    bridge = assert_bridgeable_vertical(
        current_dsm.vertical_reference, design.vertical_reference
    )
    if bridge is VerticalBridge.GEOID_GRID and geoid_grid is None:
        # 다운로드 **전**에 멈춘다 — 어차피 못 낼 숫자에 스토리지 바이트를 쓰지 않는다.
        raise GeoidUnavailableError(
            f"설계면({design.vertical_reference.datum.value})과 현재 DSM"
            f"({current_dsm.vertical_reference.datum.value})의 수직기준 계열이 달라 "
            "지오이드 격자로 변환해야 하는데 격자가 없다 — "
            f"{GEOID_GRID_ENV} 미설정이거나 그 경로를 읽지 못했다. N=0 으로 대치하면 "
            "한국에서 20~30m 가 조용히 틀린다. 이것은 '이 도면은 비교할 수 없다'가 "
            "아니라 '격자를 붙이면 계산된다'는 뜻이다"
        )

    threshold_m = policy.volume_threshold_m
    out_dir = Path(tempfile.mkdtemp(prefix="design-conformance-", dir=work_dir))
    try:
        with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
            current_path = Path(tmp) / "current-dsm.tif"
            design_path = Path(tmp) / "design.tif"
            _download(http_client, current_dsm.download_url, current_path, what="현재 DSM")
            _download(http_client, design.download_url, design_path, what="설계면")
            # 해시 대조는 **받은 그대로의 바이트**로 한다 — 변환보다 먼저다.
            _assert_design_bytes_unchanged(design_path, design)

            geoid_applied: _GeoidApplied | None = None
            if bridge is VerticalBridge.GEOID_GRID:
                assert geoid_grid is not None  # noqa: S101 -- 위에서 None 을 이미 거부했다
                bridged_path = Path(tmp) / "design-bridged.tif"
                geoid_applied = _bridge_design_heights(
                    design_path,
                    bridged_path,
                    target_family=family_of(current_dsm.vertical_reference.datum),
                    grid=geoid_grid,
                )
                design_path = bridged_path

            try:
                # ── 부호 규약: 인자 이름이 아니라 이 주석이 뜻이다 ──────────────
                # baseline=현재 지형, current=설계면 → delta = 설계 − 현재.
                # 양수면 설계가 높다 → 쌓아야 한다(fill), 음수면 깎아야 한다(cut).
                # 이 뒤집기는 이 저장소에서 **여기 한 줄뿐**이다(모듈 docstring).
                diff = align_and_diff(current_path, design_path)
                deltas: list[ZoneVolumeDelta] = [
                    volume_delta_in_polygon(
                        diff,
                        polygon,
                        zone_id=zone_id,
                        from_crs=zone_crs,
                        threshold_m=threshold_m,
                        uncertainty_note=uncertainty_note,
                        # 둘 다 None 이 이 경로의 정답이다 — 설계면에는 RMSE 가
                        # 없고, 한쪽만으로는 차이의 오차를 말할 수 없다(INV-024).
                        baseline_rmse_m=None,
                        current_rmse_m=None,
                    )
                    for zone_id, polygon in zones.items()
                ]
                raster_path = out_dir / f"{diff_raster_id}.tif"
                write_diff_geotiff(diff, raster_path)
            except DsmDiffError as exc:
                raise DesignConformanceRunError(f"설계 대비 잔량 계산 실패: {exc}") from exc

        digest = sha256_of_file(raster_path)
        size_bytes = raster_path.stat().st_size
        core_verified_digest_at = publish_diff_raster.publish_diff_raster(
            raster_path, digest=digest, size_bytes=size_bytes
        )

        # 리포트와 래스터 참조는 **같은 객체**를 쓴다 — 계약이 둘의 datum 일치를
        # 검사하는데, 두 번 만들면 나중에 한쪽만 바뀔 여지가 생긴다.
        vertical_reference = _diff_vertical_reference(current_dsm, design, geoid_applied)
        report = DesignConformanceReport(
            design_conformance_id=design_conformance_id,
            design_surface_ref=DesignSurfaceRef(
                design_surface_id=design.design_surface_id, sha256=design.sha256
            ),
            current=current_dsm.ref,
            crs=diff.crs,
            vertical_reference=vertical_reference,
            zones=deltas,
            policy=policy,
            diff_raster=DiffRasterRef(
                diff_raster_id=diff_raster_id,
                digest=digest,
                crs=diff.crs,
                vertical_reference=vertical_reference,
                width=diff.diff_m.shape[1],
                height=diff.diff_m.shape[0],
                pixel_size_x_m=abs(diff.transform.a),
                pixel_size_y_m=abs(diff.transform.e),
                transform=(
                    diff.transform.a,
                    diff.transform.b,
                    diff.transform.c,
                    diff.transform.d,
                    diff.transform.e,
                    diff.transform.f,
                ),
                threshold_m=threshold_m,
                size_bytes=size_bytes,
                core_verified_digest_at=core_verified_digest_at.astimezone(UTC),
            ),
            computed_at=computed_at.astimezone(UTC),
        )
    except BaseException:
        # 리포트를 못 만들었으면 래스터도 남기지 않는다 — 호출자는 실패 경로에서
        # 경로를 받지 못하므로 여기서 지우지 않으면 그대로 샌다.
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    logger.info(
        "설계 대비 잔량 계산 완료: id=%s 구역 %d개 순 성토 필요 %.2f m³ 래스터 %d bytes",
        design_conformance_id,
        len(report.zones),
        report.total_net_m3,
        size_bytes,
    )
    return report, raster_path


@dataclass(frozen=True, slots=True)
class _GeoidApplied:
    """설계면에 **실제로 적용한** 지오이드 보정 — 리포트 근거에 그대로 실린다.

    "격자로 변환했다"는 문장은 *어느 격자로, 어느 방향으로, 얼마나* 를 말하지
    못하면 검증할 수 없는 주장이다. 화면은 이 값들이 녹아든 ``basis`` 를 숫자
    바로 옆에 띄우므로(대시보드 ``DesignConformancePanel``), 사용자는 N 이
    한국 상식 범위(15~35m)인지 그 자리에서 알아볼 수 있다.
    """

    #: 사람이 읽을 방향 — 예 ``"정표고 → 타원체고(h = H + N)"``.
    direction: str
    #: 어느 격자였나(``GeoidGrid.provenance``).
    grid: str
    #: 적용한 지오이드고의 범위(m). 셀마다 다르므로 한 값이 아니다.
    n_min_m: float
    n_max_m: float
    #: 실제로 보정한 유효 셀 수.
    cell_count: int


def _bridge_design_heights(
    design_path: Path,
    out_path: Path,
    *,
    target_family: VerticalDatumFamily,
    grid: GeoidGrid,
) -> _GeoidApplied:
    """설계면 높이를 현재 DSM 의 계열에 맞춘다 — **셀마다** 그 셀의 N 으로.

    셀 중심의 투영좌표를 경위도로 옮겨(``rasterio.warp.transform``) 격자에서 N 을
    이중선형 보간한다. 왜 구역 대표점 하나로 상수 보정하지 않는지는 모듈
    docstring "N 은 셀마다 다르다" 에 실측 수치로 적혀 있다.

    변환은 :func:`~ksi_geo_spatial.vertical.orthometric_to_ellipsoidal` /
    :func:`~ksi_geo_spatial.vertical.ellipsoidal_to_orthometric` 를 그대로 쓴다 —
    부호(``h = H + N``)를 여기서 다시 쓰면 정본이 둘이 된다.

    **nodata 셀은 건드리지 않는다.** 그 셀에는 높이가 없으므로 변환할 것도 없고,
    격자 범위 밖이라는 이유로 계산 전체를 막을 이유도 없다. 반대로 **유효 셀이
    격자 밖이면 거부한다** — 외삽하지 않는다(INV-023).

    좌표는 100만 셀 단위로 끊어 처리한다. 경위도를 한 번에 리스트로 만들면 큰
    설계면(0.25m 격자 1km² = 1600만 셀)에서 메모리가 GB 단위로 튄다.
    """
    with rasterio.open(design_path) as dataset:
        if dataset.crs is None:
            raise DesignConformanceRunError(
                "설계면에 좌표계가 없다 — 어느 지점의 지오이드고인지 알 수 없으면 "
                "정표고를 타원체고로 바꿀 수 없다"
            )
        # 화이트리스트 밖 좌표계면 여기서 멈춘다(``dsm_diff`` 와 같은 근거) —
        # 엉뚱한 좌표계로 경위도를 계산하면 N 을 다른 나라에서 읽어 온다.
        crs = assert_supported_project_crs(str(dataset.crs))
        values = dataset.read(1).astype(np.float64)
        transform = dataset.transform
        nodata = dataset.nodata

    valid = np.isfinite(values)
    if nodata is not None and math.isfinite(nodata):
        valid &= values != nodata
    rows, cols = np.nonzero(valid)
    if rows.size == 0:
        raise DesignConformanceRunError(
            "설계면에 유효한 높이 셀이 하나도 없다 — 변환할 것이 없다"
        )

    convert = (
        orthometric_to_ellipsoidal
        if target_family is VerticalDatumFamily.ELLIPSOIDAL
        else ellipsoidal_to_orthometric
    )
    heights = values[rows, cols]
    converted = np.empty_like(heights)
    for start in range(0, rows.size, _GEOID_CHUNK_CELLS):
        chunk = slice(start, start + _GEOID_CHUNK_CELLS)
        xs, ys = raster_cell_centre(transform, rows[chunk], cols[chunk])
        lons, lats = warp_coordinates(crs, "EPSG:4326", list(xs), list(ys))
        converted[chunk] = [
            convert(float(height), lat_deg=lat, lon_deg=lon, grid=grid)
            for height, lat, lon in zip(heights[chunk], lats, lons, strict=True)
        ]

    # 기록하는 값은 **지오이드고 N 자체**다 — 방향에 따라 부호가 뒤집히는 보정량을
    # 그대로 실으면 리포트의 N 이 음수로 보여, 한국 상식 범위(15~35m) 대조가 깨진다.
    separations = (
        converted - heights
        if target_family is VerticalDatumFamily.ELLIPSOIDAL
        else heights - converted
    )
    out = values.copy()
    out[rows, cols] = converted
    # 프로파일은 **원본에서 물려받지 않고 필요한 것만 새로 적는다.** 물려받으면
    # 압축·타일링 조합 같은 원본의 쓰기 옵션이 딸려와 경고를 내고, 여기서 중요한
    # 것은 격자 기하(crs/transform)와 nodata 뿐이다. dtype 은 float64 로 고정한다 —
    # 원본이 float32 면 H+N 이 float32 로 되접혀 정밀도가 깎인다. 이 파일은 차분
    # 직전의 임시 산출물이라 크기는 문제가 아니다.
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=out.shape[0],
        width=out.shape[1],
        count=1,
        dtype="float64",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(out, 1)

    return _GeoidApplied(
        direction=(
            "정표고 → 타원체고(h = H + N)"
            if target_family is VerticalDatumFamily.ELLIPSOIDAL
            else "타원체고 → 정표고(H = h − N)"
        ),
        grid=grid.provenance,
        n_min_m=float(separations.min()),
        n_max_m=float(separations.max()),
        cell_count=int(rows.size),
    )


def _diff_vertical_reference(
    current_dsm: CurrentDsmSource,
    design: DesignSource,
    geoid_applied: _GeoidApplied | None,
) -> VerticalReference:
    """차분 격자의 수직기준 — **현재 DSM 의 datum 을 승계**한다.

    두 입력을 이을 수 있다는 것은 이미 확인됐고(``assert_bridgeable_vertical``),
    같은 계열 안에서 ``ellipsoidal`` 과 ``ellipsoidal_native`` 의 차이는 비교
    가능성이 아니라 **재처리 대상 표시**다(``VerticalDatum`` docstring). 현재
    DSM 이 "변환하지 못해 남은 상태"라면 그것을 빼서 만든 격자도 같은 상태이므로,
    측정된 쪽의 표시를 그대로 물려받는 것이 그 표시를 잃지 않는 유일한 선택이다.
    설계면 쪽 값을 쓰면 "설계자가 의도적으로 고른 기준"이라는 뜻이 결과에 옮겨
    붙는데, 그건 이 격자에 대한 사실이 아니다.

    **변환을 했다면 그 사실이 여기 남는다.** 설계면을 지오이드 격자로 옮겨서 낸
    숫자와 처음부터 같은 계열이라 그냥 뺀 숫자는 datum 이 같아도 **온 길이
    다르다** — 어느 격자로 얼마를 더했는지가 결과에 드러나지 않으면, 나중에
    격자가 바뀌었을 때 어느 리포트를 다시 계산해야 하는지 아무도 답할 수 없다.

    ``source`` 는 언제나 ``PIPELINE_DECLARED`` 다 — 이 값은 우리 계산이 만든
    것이고, 사용자가 주장할 수 있는 자리가 아니다(계약도 이것만 받는다).
    """
    if geoid_applied is None:
        conversion = (
            "두 입력의 수직기준 계열이 같아 변환 없이 그대로 뺐다"
        )
    else:
        conversion = (
            f"설계면 높이를 지오이드 격자 {geoid_applied.grid} 로 셀마다 보간해 "
            f"{geoid_applied.direction} 로 옮긴 뒤 뺐다 — 적용한 지오이드고 N "
            f"{geoid_applied.n_min_m:.3f}~{geoid_applied.n_max_m:.3f}m "
            f"({geoid_applied.cell_count:,}셀)"
        )
    return VerticalReference(
        datum=current_dsm.vertical_reference.datum,
        basis=(
            "현재 DSM 과 설계면의 표고차 격자 — 현재 DSM: "
            f"{current_dsm.vertical_reference.datum.value}, 설계면: "
            f"{design.vertical_reference.datum.value}. {conversion}. 격자의 기준은 "
            "실측된 현재 DSM 의 것을 그대로 승계한다"
        ),
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


def _assert_design_bytes_unchanged(path: Path, design: DesignSource) -> None:
    """받아온 설계면이 검증 때 잰 그 파일인가 — 아니면 숫자를 내지 않는다."""
    actual = sha256_of_file(path)
    expected = f"sha256:{design.sha256}"
    if actual != expected:
        raise DesignConformanceRunError(
            f"설계면 바이트가 검증 시점과 다르다(designSurfaceId={design.design_surface_id}): "
            f"검증된 {expected}, 받은 {actual} — 같은 id 로 다른 파일을 비교하면 리포트가 "
            "무엇을 기준으로 낸 숫자인지 되짚을 수 없다"
        )


def _download(client: httpx.Client, url: str, dest: Path, *, what: str) -> None:
    """스토리지에서 받아 파일로 쓴다 — 실패 메시지에 presigned 서명을 남기지 않는다.

    ``run_change_detection``·``run_volume_change`` 의 ``_download`` 와 대칭이다
    (``download_errors`` 모듈 docstring: 구조는 복제하되 **무엇을 지울지의 판단**만
    공용으로 둔다).
    """
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        raise DesignConformanceRunError(
            download_failure_detail(
                what=what, url=url, cause=f"HTTP {exc.response.status_code}"
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise DesignConformanceRunError(
            download_failure_detail(what=what, url=url, cause=f"{type(exc).__name__}: {exc}")
        ) from exc


__all__ = [
    "DESIGN_SURFACE_NOT_MEASURED_NOTE",
    "CurrentDsmSource",
    "DesignConformanceRunError",
    "DesignSource",
    "DiffRasterPublisher",
    "compute_design_conformance",
]

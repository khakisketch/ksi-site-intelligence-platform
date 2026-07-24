"""Scout GeoProjector 골든 벡터 캡처 (P0-3).

원 구현(참고, 읽기전용): references/repos/ksi-scout/ksi_scout/geo/projection.py
                        @42ccc0db (ksi-scout HEAD, verify_reference_pins.sh 대상)

이 스크립트는 project_foot_point()/LiveGeoProjector.project() 를 **실제로 실행**해
입력→출력을 캡처한다(손 전사 금지, 대표자 반영사항 8). 출력은
packages/test-vectors/vectors/legacy_compat/geo_projection.json 에 쓴다.

실행 방법(재추출):
    <scratchpad>/.venv-scout/bin/python tools/vector-extraction/capture_scout_projection.py
    (venv 재현: uv venv --python 3.12 .venv-scout && uv pip install --python .venv-scout/bin/python
     numpy pydantic shapely  — 이 3개만 geo/projection.py + geo/zones.py import 에 필요.
     scout 본체 의존성(opencv/ultralytics 등)은 이 벡터 캡처엔 불필요.)

이 스크립트는 tools/vector-extraction/ 아래에 있어 scripts/check_no_reference_imports.sh
가드(CODE_DIRS=apps/services/edge/workers/packages/tests) 대상이 아니다 — tools/ 는
가드 제외 디렉토리로, references/ 를 직접 import 해도 되는 유일한 위치다(README.md 참고).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOUT_ROOT = REPO_ROOT / "references" / "repos" / "ksi-scout"
OUT_PATH = (
    REPO_ROOT
    / "packages"
    / "test-vectors"
    / "vectors"
    / "legacy_compat"
    / "geo_projection.json"
)

sys.path.insert(0, str(SCOUT_ROOT))

import numpy as np  # noqa: E402
import pydantic  # noqa: E402
import shapely  # noqa: E402
from ksi_scout.contracts.detection import Detection, ObjectClass  # noqa: E402
from ksi_scout.contracts.frame import NormalizedFrame  # noqa: E402
from ksi_scout.contracts.geometry import BBox  # noqa: E402
from ksi_scout.contracts.telemetry import NormalizedTelemetry, SourceQuality  # noqa: E402
from ksi_scout.contracts.zone import Zone, ZoneType  # noqa: E402
from ksi_scout.geo.projection import LiveGeoProjector, project_foot_point  # noqa: E402
from ksi_scout.geo.zones import ZoneLayer  # noqa: E402

W, H = 1920, 1080


def _tel(**kw: Any) -> NormalizedTelemetry:
    base: dict[str, Any] = {
        "timestamp_utc": 0.0,
        "drone_lat": 37.5,
        "drone_lon": 127.0,
        "altitude_rel_m": 100.0,
        "heading_deg": 0.0,
        "gimbal_pitch_deg": -90.0,
        "camera_fov_deg": 84.0,
        "zoom_factor": 1.0,
        "rtk_fixed": True,
        "source_quality": SourceQuality.FULL,
    }
    base.update(kw)
    return NormalizedTelemetry(**base)


def _tel_kwargs(tel: NormalizedTelemetry) -> dict[str, Any]:
    """텔레메트리를 JSON 직렬화 가능한 dict 로 (enum → value)."""
    d = tel.model_dump()
    d["source_quality"] = tel.source_quality.value
    return d


def _gp_output(gp: Any) -> dict[str, Any]:
    return {
        "available": gp.available,
        "reason": gp.reason,
        "lat": gp.lat,
        "lon": gp.lon,
        "east_m": gp.east_m,
        "north_m": gp.north_m,
        "geo_confidence": gp.geo_confidence,
        "error_radius_m": gp.error_radius_m,
    }


def _foot_point_case(
    case_id: str,
    description: str,
    *,
    u_frac: float,
    v_frac: float,
    tel: NormalizedTelemetry,
    default_fov_deg: float = 84.0,
    fov_is_diagonal: bool = False,
) -> dict[str, Any]:
    u, v = u_frac * W, v_frac * H
    gp = project_foot_point(
        u, v, W, H, tel, default_fov_deg=default_fov_deg, fov_is_diagonal=fov_is_diagonal
    )
    return {
        "id": case_id,
        "api": "project_foot_point",
        "description": description,
        "input": {
            "u_px": u,
            "v_px": v,
            "width": W,
            "height": H,
            "telemetry": _tel_kwargs(tel),
            "default_fov_deg": default_fov_deg,
            "fov_is_diagonal": fov_is_diagonal,
        },
        "output": _gp_output(gp),
    }


def _zone(zone_id: str, zone_type: ZoneType, polygon: list[tuple[float, float]]) -> Zone:
    return Zone(zone_id=zone_id, zone_type=zone_type, polygon=polygon)


def _live_projector_case(
    case_id: str,
    description: str,
    *,
    tel: NormalizedTelemetry | None,
    zones: list[Zone],
) -> dict[str, Any]:
    det = Detection(
        klass=ObjectClass.PERSON,
        label="person",
        bbox=BBox(x1=W / 2 - 5, y1=H / 2 - 5, x2=W / 2 + 5, y2=H / 2 + 5),
        confidence=0.9,
    )
    image = np.zeros((H, W, 3), dtype=np.uint8)
    frame = NormalizedFrame(frame_id=0, timestamp_utc=0.0, image=image)
    proj = LiveGeoProjector(ZoneLayer(zones) if zones else None)
    res = proj.project(det, frame, tel)
    return {
        "id": case_id,
        "api": "LiveGeoProjector.project",
        "description": description,
        "input": {
            "telemetry": _tel_kwargs(tel) if tel is not None else None,
            "zones": [
                {"zone_id": z.zone_id, "zone_type": z.zone_type.value, "polygon": z.polygon}
                for z in zones
            ],
            "detection_bbox_xyxy": [W / 2 - 5, H / 2 - 5, W / 2 + 5, H / 2 + 5],
            "frame": {"width": W, "height": H},
        },
        "output": {
            "lat": res.lat,
            "lon": res.lon,
            "geo_confidence": res.geo_confidence,
            "position_error_radius_m": res.position_error_radius_m,
            "zone_decision": res.zone_decision.value,
            "zone_id": res.zone_id,
        },
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # ── project_foot_point() 직접 호출 (참고 tests/test_projection.py 의 known-answer 시나리오) ──
    cases.append(
        _foot_point_case(
            "nadir_center_directly_below",
            "짐벌 정수직(-90도) 중앙 픽셀 → 기체 직하방(east≈0, north≈0), 거리=고도.",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=100.0, gimbal_pitch_deg=-90.0),
        )
    )
    cases.append(
        _foot_point_case(
            "oblique45_north_heading0",
            "pitch=-45도, heading=0(정북) → 지면교차점이 북쪽 alt만큼 전방.",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=50.0, gimbal_pitch_deg=-45.0, heading_deg=0.0),
        )
    )
    cases.append(
        _foot_point_case(
            "heading90_rotates_north_to_east",
            "heading=90도 → 동일 pitch/alt에서 north 성분이 east 로 회전.",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=50.0, gimbal_pitch_deg=-45.0, heading_deg=90.0),
        )
    )
    cases.append(
        _foot_point_case(
            "right_edge_half_hfov",
            "우측 끝 픽셀(u=W) → east_m ≈ altitude·tan(hfov/2) (기하 검산).",
            u_frac=1.0, v_frac=0.5,
            tel=_tel(altitude_rel_m=100.0, gimbal_pitch_deg=-90.0, camera_fov_deg=84.0),
        )
    )
    cases.append(
        _foot_point_case(
            "missing_fov_degrades_confidence",
            "camera_fov_deg/zoom 결측 + PARTIAL quality + non-RTK → confidence 강등(정직성 P7).",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(
                altitude_rel_m=50.0, gimbal_pitch_deg=-45.0, camera_fov_deg=None, zoom_factor=None,
                rtk_fixed=False, gnss_accuracy_m=5.0, source_quality=SourceQuality.PARTIAL,
            ),
        )
    )
    cases.append(
        _foot_point_case(
            "near_horizontal_gimbal_low_confidence",
            "pitch=-2도(거의 수평) → 거리 폭발 + confidence/오차반경 저하(외삽 방지 경계).",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=100.0, gimbal_pitch_deg=-2.0),
        )
    )
    cases.append(
        _foot_point_case(
            "above_horizon_rejected",
            (
                "pitch=+5도(위를 봄) → 지면 비교차, available=False reason=horizon "
                "(외삽 금지, INV-023)."
            ),
            u_frac=0.5, v_frac=0.5,
            tel=_tel(gimbal_pitch_deg=5.0),
        )
    )
    cases.append(
        {
            "id": "no_telemetry_geo_capable_false",
            "api": "project_foot_point",
            "description": (
                "geo_capable 필수 필드 결측(위경도/고도/heading/pitch 전부 None) → 즉시 거부."
            ),
            "input": {
                "u_px": W / 2, "v_px": H / 2, "width": W, "height": H,
                "telemetry": _tel_kwargs(NormalizedTelemetry(timestamp_utc=0.0)),
                "default_fov_deg": 84.0, "fov_is_diagonal": False,
            },
            "output": _gp_output(
                project_foot_point(W / 2, H / 2, W, H, NormalizedTelemetry(timestamp_utc=0.0))
            ),
        }
    )
    cases.append(
        _foot_point_case(
            "altitude_zero_rejected",
            "altitude_rel_m=0(비정상) → G2 게이트에서 reason=altitude 로 거부(추측 금지).",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=0.0),
        )
    )
    cases.append(
        _foot_point_case(
            "altitude_negative_rejected",
            "altitude_rel_m<0(비정상 값) → reason=altitude 로 거부.",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=-5.0),
        )
    )
    cases.append(
        _foot_point_case(
            "gimbal_yaw_overrides_heading",
            "gimbal_yaw_deg 가 있으면 heading 과 달라도 gimbal_yaw 기준으로 계산(이중적용 방지).",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(
                altitude_rel_m=50.0, gimbal_pitch_deg=-45.0,
                heading_deg=200.0, gimbal_yaw_deg=90.0,
            ),
        )
    )
    cases.append(
        _foot_point_case(
            "roll_nonzero_rotates_ray",
            "gimbal_roll_deg=10도 → boresight 둘레 회전이 지면교차점을 옆으로 튼다.",
            u_frac=0.5, v_frac=0.5,
            tel=_tel(altitude_rel_m=80.0, gimbal_pitch_deg=-60.0, gimbal_roll_deg=10.0),
        )
    )
    cases.append(
        _foot_point_case(
            "zoom_2x_narrows_fov_reduces_offset",
            "zoom_factor=2.0 → 실효 FOV 축소로 동일 픽셀 오프셋의 지면 변위가 줄어듦.",
            u_frac=0.75, v_frac=0.5,
            tel=_tel(altitude_rel_m=100.0, gimbal_pitch_deg=-90.0, zoom_factor=2.0),
        )
    )
    cases.append(
        _foot_point_case(
            "non_rtk_gnss_accuracy_degrades_confidence_and_error",
            (
                "rtk_fixed=False + gnss_accuracy_m=8.0 → c_gnss 저하로 confidence 낮아지고 "
                "error_radius 커짐."
            ),
            u_frac=0.5, v_frac=0.5,
            tel=_tel(
                altitude_rel_m=100.0, gimbal_pitch_deg=-90.0,
                rtk_fixed=False, gnss_accuracy_m=8.0,
            ),
        )
    )
    cases.append(
        _foot_point_case(
            "diagonal_fov_focal_differs_from_horizontal",
            (
                "fov_is_diagonal=True → focal 산출 경로가 달라 동일 입력에도 "
                "east_m/confidence 가 달라짐."
            ),
            u_frac=1.0, v_frac=0.5,
            tel=_tel(altitude_rel_m=100.0, gimbal_pitch_deg=-90.0, camera_fov_deg=84.0),
            fov_is_diagonal=True,
        )
    )

    # ── LiveGeoProjector.project() — 구역 판정(ZoneDecision) 전 분기 ──
    cases.append(
        _live_projector_case(
            "zone_inside_large_hazard_zone",
            "투영점이 넓은 위험구역(경계까지 멀다) 내부 → INSIDE (경계까지 거리 >= 오차반경).",
            tel=_tel(),
            zones=[
                _zone(
                    "hz_in", ZoneType.RESTRICTED_ZONE,
                    [(37.4, 126.9), (37.4, 127.1), (37.6, 127.1), (37.6, 126.9)],
                )
            ],
        )
    )
    cases.append(
        _live_projector_case(
            "zone_outside_far_hazard_zone",
            "투영점이 어느 구역과도 무관(수백m 이상 이격) → OUTSIDE.",
            tel=_tel(),
            zones=[
                _zone(
                    "hz_out", ZoneType.RESTRICTED_ZONE,
                    [(38.0, 128.0), (38.0, 128.01), (38.01, 128.01), (38.01, 128.0)],
                )
            ],
        )
    )
    cases.append(
        _live_projector_case(
            "zone_near_boundary_within_error_radius",
            (
                "위험구역 경계가 오차반경(~1m) 이내로 가까운 내부점 → INSIDE 대신 "
                "NEAR_BOUNDARY(의심 유지)."
            ),
            tel=_tel(),
            zones=[
                _zone(
                    "hz_nb", ZoneType.RESTRICTED_ZONE,
                    [
                        (37.5 - 0.5 / 111320.0, 126.99),
                        (37.5 - 0.5 / 111320.0, 127.01),
                        (37.51, 127.01),
                        (37.51, 126.99),
                    ],
                )
            ],
        )
    )
    cases.append(
        _live_projector_case(
            "zone_geo_unavailable_no_telemetry",
            "telemetry=None → project() 최상단에서 즉시 GEO_UNAVAILABLE.",
            tel=None,
            zones=[],
        )
    )
    cases.append(
        _live_projector_case(
            "zone_geo_low_confidence_degraded_quality",
            (
                "source_quality=DEGRADED + non-RTK → confidence<tau_mid(0.35) → "
                "GEO_LOW_CONFIDENCE(구역판정 보류)."
            ),
            tel=_tel(rtk_fixed=False, gnss_accuracy_m=5.0, source_quality=SourceQuality.DEGRADED),
            zones=[],
        )
    )

    return cases


def main() -> None:
    cases = build_cases()
    doc = {
        "source": {
            "repo": "ksi-scout",
            "commit": "42ccc0db",
            "file": "ksi_scout/geo/projection.py",
        },
        "extraction": {
            "script": "tools/vector-extraction/capture_scout_projection.py",
            "runtime": {
                "language": "python",
                "version": sys.version.split()[0],
                "runner": (
                    "scratchpad venv (uv venv --python 3.12) — deps: "
                    f"numpy {np.__version__}, pydantic {pydantic.VERSION}, "
                    f"shapely {shapely.__version__}. "
                    "packages/test-vectors/pyproject.toml·uv.lock 미변경(별도 임시 venv)."
                ),
            },
        },
        "tolerance": {
            "abs": 1e-6,
            "rel": 1e-9,
            "rationale": (
                "이 벡터는 회전행렬 3개 합성(Rz_cw·Rx·R0·Rroll) 핀홀 투영이다. 필드별 근거: "
                "east_m/north_m/error_radius_m(거리, m) → abs 1e-4 m "
                "(references/repos/ksi-scout의 round-trip 테스트가 <0.01~1e-3m 편차를 통과 "
                "기준으로 삼는 것과 동일 스케일); "
                "lat/lon(도, WGS84) → abs 1e-9 deg (경위도 변환은 상수 나눗셈 1건뿐이라 "
                "부동소수 오차만 남고, 1e-9도≈0.0001m 수준이라 위치 정밀도를 해치지 않음); "
                "geo_confidence(무단위 [0,1] 스칼라, 여러 factor의 product) → abs 1e-9 "
                "(동일 정밀도의 double 연산 반복이라 rel 대신 절대오차가 적절). "
                "최상위 abs/rel 은 기본값(가장 보수적인 confidence 기준)이고, "
                "필드별 override 는 tolerance.by_field 를 본다."
            ),
            "by_field": {
                "east_m": {"abs": 1e-4, "rel": 0},
                "north_m": {"abs": 1e-4, "rel": 0},
                "error_radius_m": {"abs": 1e-4, "rel": 0},
                "position_error_radius_m": {"abs": 1e-4, "rel": 0},
                "lat": {"abs": 1e-9, "rel": 0},
                "lon": {"abs": 1e-9, "rel": 0},
                "geo_confidence": {"abs": 1e-9, "rel": 0},
            },
        },
        "cases": cases,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {OUT_PATH}")


if __name__ == "__main__":
    main()

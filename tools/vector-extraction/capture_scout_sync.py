"""Scout TelemetryInterpolator 골든 벡터 캡처 (P0-2).

원 구현(참고, 읽기전용): references/repos/ksi-scout/ksi_scout/dal/sync.py
                        @42ccc0db9a274db94746284bdfbf73db847f5afd (ksi-scout HEAD,
                        verify_reference_pins.sh 대상)

이 스크립트는 ``TelemetryInterpolator.add()``/``at()`` 을 **실제로 실행**해 입력→출력을
캡처한다(손 전사 금지, 대표자 반영사항 8). 출력은
packages/test-vectors/vectors/legacy_compat/telemetry_interpolation.json 에 쓴다.

실행 방법(재추출):
    <scratchpad>/.venv-scout-sync/bin/python tools/vector-extraction/capture_scout_sync.py
    (venv 재현: uv venv --python 3.12 <scratchpad>/.venv-scout-sync &&
     uv pip install --python <scratchpad>/.venv-scout-sync/bin/python \
       pydantic numpy opencv-python-headless
     — TelemetryInterpolator 자체는 threading/bisect(표준 라이브러리)+
     ksi_scout.contracts.telemetry(pydantic) 만 쓰지만, ``from ksi_scout.dal.sync import ...``
     가 부모 패키지 ksi_scout/dal/__init__.py 를 초기화시키며 그 안의 다른 DAL
     어댑터(dji/webcam/file_video/generic_stream)가 cv2 를 import 하므로
     opencv-python-headless 도 설치해야 import 체인이 끝까지 성립한다.
     numpy 는 ksi_scout.contracts.frame(NormalizedFrame)이 요구한다(contracts 패키지
     __init__ 체인). packages/test-vectors/pyproject.toml·uv.lock 은 미변경(별도 임시 venv).)

이 스크립트는 tools/vector-extraction/ 아래에 있어 scripts/check_no_reference_imports.sh
가드(CODE_DIRS=apps/services/edge/workers/packages/tests) 대상이 아니다 — tools/ 는
가드 제외 디렉토리로, references/ 를 직접 import 해도 되는 유일한 위치다(README.md 참고).

각 케이스에는 ``tag`` 가 있다:
- ``ok_within_gap``: 두 샘플 사이 gap이 max_gap_s 이내(Scout 기준 ``max_gap_s*2`` 이내이기도
  함) — Scout와 KSI 양쪽 모두 성공하고 보간값이 같아야 하는 구간.
- ``gap_exceeds``: gap이 max_gap_s(및 Scout 기준 ``max_gap_s*2``)를 넘는 구간. Scout는
  DEGRADED 품질로 값을 그대로 반환하지만, KSI는 INV-023(외삽 금지·fail-closed)에 따라
  GAP_EXCEEDED typed 실패를 반환한다 — 의도된 차이이며, 이 벡터의 ``output`` 은 Scout의
  실제 반환값(참고용)이지 KSI가 재현해야 할 목표값이 아니다.
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
    / "telemetry_interpolation.json"
)

sys.path.insert(0, str(SCOUT_ROOT))

import pydantic  # noqa: E402
from ksi_scout.contracts.telemetry import NormalizedTelemetry, SourceQuality  # noqa: E402
from ksi_scout.dal.sync import TelemetryInterpolator  # noqa: E402


def _tel(ts: float, **kw: Any) -> NormalizedTelemetry:
    base: dict[str, Any] = {
        "timestamp_utc": ts,
        "drone_lon": 127.0,
        "gimbal_pitch_deg": -90.0,
        "source_quality": SourceQuality.FULL,
    }
    base.update(kw)
    return NormalizedTelemetry(**base)


def _tel_kwargs(tel: NormalizedTelemetry) -> dict[str, Any]:
    """텔레메트리를 JSON 직렬화 가능한 dict 로 (enum → value)."""
    d = tel.model_dump()
    d["source_quality"] = tel.source_quality.value
    return d


def _run_case(
    case_id: str,
    description: str,
    *,
    tag: str,
    max_gap_s: float,
    add_order: list[NormalizedTelemetry],
    query_ts: float,
) -> dict[str, Any]:
    itp = TelemetryInterpolator(max_gap_s=max_gap_s)
    for tel in add_order:
        itp.add(tel)
    result = itp.at(query_ts)
    return {
        "id": case_id,
        "api": "TelemetryInterpolator.at",
        "description": description,
        "tag": tag,
        "input": {
            "config": {"max_gap_s": max_gap_s, "buffer_size": 600},
            "add_sequence": [
                {"order": i, "telemetry": _tel_kwargs(tel)} for i, tel in enumerate(add_order)
            ],
            "query_ts": query_ts,
        },
        "output": _tel_kwargs(result) if result is not None else None,
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    cases.append(
        _run_case(
            "linear_midpoint",
            "선형 보간 중간값(lat/alt) — t=0.5 정확성 기준.",
            tag="ok_within_gap",
            max_gap_s=2.0,
            add_order=[
                _tel(0.0, drone_lat=36.0000, altitude_rel_m=40.0),
                _tel(1.0, drone_lat=36.0010, altitude_rel_m=50.0),
            ],
            query_ts=0.5,
        )
    )
    cases.append(
        _run_case(
            "linear_nonmidpoint_out_of_order_insert",
            (
                "t=0.3 비대칭 보간 + rtk_fixed AND 결합 + gnss_accuracy_m 보간. "
                "add() 를 역순(hi 먼저)으로 호출해 bisect 정렬 삽입도 함께 검증."
            ),
            tag="ok_within_gap",
            max_gap_s=1.0,
            add_order=[
                _tel(1.0, drone_lat=36.0010, rtk_fixed=False, gnss_accuracy_m=0.8),
                _tel(0.0, drone_lat=36.0000, rtk_fixed=True, gnss_accuracy_m=1.2),
            ],
            query_ts=0.3,
        )
    )
    cases.append(
        _run_case(
            "heading_wrap_forward_350_to_10",
            "heading 350°→10° 최단호는 0°를 지난다(340° 쪽이 아님).",
            tag="ok_within_gap",
            max_gap_s=1.0,
            add_order=[
                _tel(0.0, drone_lat=36.0, heading_deg=350.0),
                _tel(1.0, drone_lat=36.0, heading_deg=10.0),
            ],
            query_ts=0.5,
        )
    )
    cases.append(
        _run_case(
            "heading_wrap_backward_10_to_350",
            "heading 10°→350° (역방향) — 정방향 케이스와 대칭인지 확인.",
            tag="ok_within_gap",
            max_gap_s=1.0,
            add_order=[
                _tel(0.0, drone_lat=36.0, heading_deg=10.0),
                _tel(1.0, drone_lat=36.0, heading_deg=350.0),
            ],
            query_ts=0.5,
        )
    )
    cases.append(
        _run_case(
            "gimbal_yaw_wrap_179_to_negative_179",
            "gimbal_yaw 179°→-179°(=181°) 최단호는 2°만 지나 t=0.5에서 ±180° 경계.",
            tag="ok_within_gap",
            max_gap_s=1.0,
            add_order=[
                _tel(0.0, drone_lat=36.0, gimbal_yaw_deg=179.0),
                _tel(1.0, drone_lat=36.0, gimbal_yaw_deg=-179.0),
            ],
            query_ts=0.5,
        )
    )
    cases.append(
        _run_case(
            "gap_within_threshold",
            "샘플 간 gap(0.4s) <= max_gap_s(0.5s) — 정상 보간, 품질 유지.",
            tag="ok_within_gap",
            max_gap_s=0.5,
            add_order=[
                _tel(0.0, drone_lat=36.0),
                _tel(0.4, drone_lat=36.001),
            ],
            query_ts=0.2,
        )
    )
    cases.append(
        _run_case(
            "gap_exceeds_threshold",
            (
                "샘플 간 gap(5.0s) > max_gap_s(0.5s) — Scout 는 DEGRADED 품질로 값을 그대로 "
                "반환하지만 KSI는 INV-023에 따라 GAP_EXCEEDED로 거부한다(의도된 차이, "
                "sync.py 모듈 docstring 참고)."
            ),
            tag="gap_exceeds",
            max_gap_s=0.5,
            add_order=[
                _tel(0.0, drone_lat=36.0),
                _tel(5.0, drone_lat=36.0),
            ],
            query_ts=2.5,
        )
    )

    return cases


def main() -> None:
    cases = build_cases()
    doc = {
        "source": {
            "repo": "KSI-Scout",
            "commit": "42ccc0db9a274db94746284bdfbf73db847f5afd",
            "file": "ksi_scout/dal/sync.py",
        },
        "extraction": {
            "script": "tools/vector-extraction/capture_scout_sync.py",
            "runtime": {
                "language": "python",
                "python": sys.version.split()[0],
                "runner": (
                    "scratchpad venv (uv venv --python 3.12) — deps: "
                    f"pydantic {pydantic.VERSION} (numpy/opencv-python-headless also "
                    "installed to satisfy ksi_scout.dal/contracts package __init__ import "
                    "chains, unused by TelemetryInterpolator itself). "
                    "packages/test-vectors/pyproject.toml·uv.lock 미변경(별도 임시 venv)."
                ),
            },
        },
        "tolerance": {
            "abs": 1e-9,
            "rel": 1e-9,
            "rationale": (
                "TelemetryInterpolator 는 순수 python float 사칙연산(lerp)과 mod 360 각도 "
                "wraparound뿐이다(numpy·행렬연산 없음) — 동일 IEEE-754 double 연산이면 "
                "플랫폼·인터프리터 사이에도 결정적으로 동일해야 한다. 1e-9 는 재현 시 발생할 "
                "수 있는 부동소수 표현/연산 순서 차이만 흡수하는 타이트한 허용오차다."
            ),
        },
        "cases": cases,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {OUT_PATH}")


if __name__ == "__main__":
    main()

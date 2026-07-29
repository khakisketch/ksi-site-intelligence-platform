"""pytest 세션 공통 훅 + 실모델 게이트 skip 정직성 anchor (감사 #19).

## 무음 전량 skip 문제 (2026-07-29 실측)

실모델 게이트 3파일(dfine detector · onnx conformance · recorded slice, 82건)은
[dfine] extra 와 모델 파일이 있을 때만 돈다 — 의도된 분리 게이트다. 문제는 그
skip 이 **무음**이라는 것: `uv sync --all-packages` 가 torch 를 지운 상태에서
전체 pytest 를 돌리면 82건이 전부 skip 인 채 "green" 으로 읽힌다(실측 재현).

해법: 로컬 완전 게이트는 ``KSI_REQUIRE_REAL_MODEL=1`` 로 실행한다 — 이 모드에서
실모델 게이트 테스트가 1건이라도 skip 되면 세션이 실패한다. CI(모델 없음)는
이 변수를 설정하지 않으므로 기존 분리 게이트 의미는 유지된다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 공유 헬퍼(tests/_real_model_gate.py)를 어디서든 flat import 가능하게 —
# hil/replay 테스트들의 기존 sys.path 주입 관행과 동일.
sys.path.insert(0, str(Path(__file__).resolve().parent))

REAL_MODEL_GATE_FILES = (
    "test_dfine_detector.py",
    "test_onnx_conformance.py",
    "test_recorded_slice.py",
)

_gate_skips: list[str] = []


def pytest_runtest_logreport(report) -> None:  # type: ignore[no-untyped-def]
    if (
        report.when == "setup"
        and report.skipped
        and any(name in report.nodeid for name in REAL_MODEL_GATE_FILES)
    ):
        _gate_skips.append(report.nodeid)


@pytest.hookimpl(wrapper=True)
def pytest_cmdline_main(config):  # type: ignore[no-untyped-def]
    """세션 종료코드 강제 — sessionfinish 의 session.exitstatus 대입은 최종
    종료코드에 반영되지 않음을 실측(2026-07-29)으로 확인해 wrapper 로 감싼다."""
    result = yield
    if os.environ.get("KSI_REQUIRE_REAL_MODEL") == "1" and _gate_skips:
        sys.stderr.write(
            f"\nKSI_REQUIRE_REAL_MODEL=1: 실모델 게이트 {len(_gate_skips)}건이 skip 됐다 — "
            "이 실행은 완전 게이트가 아니다. 복구: uv sync --all-packages --all-extras "
            "+ 모델 파일(tools/fetch_model.py) 확인\n"
        )
        return 1
    return result

"""pytest 세션 공통 훅 (감사 #19의 skip 정직성 anchor는 P3 Task 6에서 퇴역).

실모델 게이트 4파일(dfine detector · onnx conformance · recorded slice ·
recorded_pipeline)은 P3 Task 6에서 그 subject(``ksi_perception``)와 함께
``archive/acquisition-2026/`` 으로 blob-identical 이동했다 — 무음 skip을
재던 anchor도 함께 퇴역한다(RB-08: 명시적 분리, task-6-report 기록). 남은
``KSI_REQUIRE_REAL_MODEL`` 분기는 검증할 대상이 없으므로 항상 통과한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 공유 헬퍼(tests/_real_model_gate.py)를 어디서든 flat import 가능하게 —
# hil/replay 테스트들의 기존 sys.path 주입 관행과 동일.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# New contract fixtures follow the existing flat test-helper convention. Include this
# directory even when running a replay file alone, not only after contract collection.
sys.path.insert(0, str(Path(__file__).resolve().parent / "contract"))

# P3 Task 6: 실모델 게이트 파일이 아카이브로 이동해 anchor가 퇴역했다.
# 이름은 과거 nodeid 와의 혼동을 막기 위해 남기지 않고 비운다.
REAL_MODEL_GATE_FILES: tuple[str, ...] = ()

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
        # P3 Task 6: anchor 대상 파일이 전부 아카이브로 이동했다. 존재 단언은
        # 퇴역한다 — 검증할 실모델 게이트가 active tree에 없다. (부재 자체가
        # 분리 증거이며 task-6-report에 기록된다.)
        sys.stderr.write(
            f"\nKSI_REQUIRE_REAL_MODEL=1: {len(_gate_skips)}건이 skip 됐다 — "
            "이 실행은 완전 게이트가 아니다.\n"
        )
        return 1
    return result

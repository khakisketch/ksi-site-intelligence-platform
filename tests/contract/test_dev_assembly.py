"""dev 조립 지점(scripts/run_core_dev.py)의 CLI→생성자 변환 계약.

이 스크립트는 저장소에 존재하는 **유일한 조립 지점**이다 — 라이브러리 테스트가
전부 green 이어도 여기 배선이 틀리면 실제로 뜨는 서버만 잘못 조립된다. 독립
재검토가 "이 파일을 도는 테스트가 0건"으로 지적한 자리다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dev_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_core_dev", _REPO_ROOT / "scripts" / "run_core_dev.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, None), (1, 1), (500, 500), (64 * 1024 * 1024, 64 * 1024 * 1024)],
)
def test_zero_means_disabled_positive_passes_through(value: int, expected: int | None) -> None:
    """CLI 의 '0 = 없음' 규약이 생성자의 None 으로 정확히 옮겨진다."""
    module = _load_dev_module()
    assert module.cli_optional_positive(value, name="--x") is expected


def test_negative_is_rejected_with_the_cli_flag_name() -> None:
    """음수는 argparse 를 통과한다 — 생성자까지 흘리면 실패 메시지가 인자명을 잃는다."""
    module = _load_dev_module()
    with pytest.raises(ValueError, match="--journal-segment-bytes"):
        module.cli_optional_positive(-1, name="--journal-segment-bytes")


def test_defaults_are_within_constructor_contracts() -> None:
    """기본값이 생성자 규약(양수 또는 None)을 만족한다 — 기본 조립이 즉시 죽지 않게."""
    module = _load_dev_module()
    for default in (64 * 1024 * 1024, 500):
        converted = module.cli_optional_positive(default, name="--x")
        assert converted is not None and converted > 0

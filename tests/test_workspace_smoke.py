"""워크스페이스 멤버가 전부 설치·임포트 가능한지 검증하는 스모크 테스트.

P3 Task 6: 아카이브로 이동한 acquisition 멤버(ksi_mission_contracts,
ksi_perception, ksi_dji_gateway)는 이 목록에서 제외한다 — 제외 자체가 분리
증거이며 task-6-report에 기록된다(RB-08). 아카이브 absence는
tests/contract/test_acquisition_archive_boundary.py가 단정한다.
"""

import importlib

import pytest

WORKSPACE_MODULES = [
    "ksi_domain",
    "ksi_geo_core",
    "ksi_event_contracts",
    "ksi_test_vectors",
    "ksi_core",
    "ksi_processing_controller",
]


@pytest.mark.parametrize("module_name", WORKSPACE_MODULES)
def test_member_importable(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__version__

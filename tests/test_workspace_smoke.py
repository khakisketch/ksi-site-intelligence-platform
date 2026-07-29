"""워크스페이스 멤버가 전부 설치·임포트 가능한지 검증하는 스모크 테스트."""

import importlib

import pytest

WORKSPACE_MODULES = [
    "ksi_domain",
    "ksi_geo_core",
    "ksi_event_contracts",
    "ksi_mission_contracts",
    "ksi_perception",
    "ksi_test_vectors",
    "ksi_core",
    "ksi_dji_gateway",
    "ksi_processing_controller",
]


@pytest.mark.parametrize("module_name", WORKSPACE_MODULES)
def test_member_importable(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__version__

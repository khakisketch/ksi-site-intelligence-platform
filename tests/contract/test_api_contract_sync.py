"""API 계약 문서 ↔ 실구현 대조 게이트 (감사 #25·#34·#35).

권위 체인 4위(contracts/)가 구현보다 낡아도 CI 가 침묵하던 사각지대를 닫는다:
openapi-core.yaml 의 **비-planned 경로는 실제 FastAPI 앱에 존재해야 하고**,
asyncapi 의 $ref 는 존재하는 최신 세대 스키마 파일을 가리켜야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from ksi_core.app import create_app
from ksi_core.edge_sync import EdgeSyncStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENAPI = _REPO_ROOT / "contracts" / "api" / "openapi-core.yaml"
_ASYNCAPI = _REPO_ROOT / "contracts" / "api" / "asyncapi-edge.yaml"


def _implemented_paths(tmp_path: Path) -> set[str]:
    app = create_app(edge_sync_store=EdgeSyncStore(tmp_path / "journal.jsonl"))
    return set(app.openapi()["paths"])


def test_non_planned_openapi_paths_exist_in_implementation(tmp_path: Path) -> None:
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    implemented = _implemented_paths(tmp_path)
    documented = {
        path for path, spec in doc["paths"].items() if spec.get("x-status") != "planned"
    }
    missing = documented - implemented
    assert not missing, (
        f"openapi-core.yaml 이 구현에 없는 경로를 '구현된 계약'으로 문서화한다: {missing} "
        "— 미구현 설계는 x-status: planned 로 표기하라"
    )


def test_edge_sync_path_is_documented_as_implemented(tmp_path: Path) -> None:
    """역방향 — 핵심 구현 경로가 문서에서 빠지거나 planned 로 강등되면 실패."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    spec = doc["paths"].get("/v1/edge-sync/event-bundles")
    assert spec is not None and spec.get("x-status") != "planned"
    assert "/v1/edge-sync/event-bundles" in _implemented_paths(tmp_path)


def test_asyncapi_refs_point_to_existing_latest_schemas() -> None:
    text = _ASYNCAPI.read_text(encoding="utf-8")
    doc: dict[str, Any] = yaml.safe_load(text)
    refs: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    refs.append(value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(doc)
    assert refs, "asyncapi 에 스키마 $ref 가 없다"
    for ref in refs:
        target = (_ASYNCAPI.parent / ref).resolve()
        assert target.is_file(), f"asyncapi $ref 가 존재하지 않는 파일을 가리킨다: {ref}"
    # 최초 세대(v1)로의 회귀 방지 — 서명(INV-011)·분류 계보(INV-031)가 없는
    # 페이로드를 와이어 계약으로 안내하던 drift(감사 #34).
    assert "mission-contract.v1.json" not in text
    assert "event-bundle.v1.json" not in text and "event-bundle.v1.1.json" not in text

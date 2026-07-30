"""API 계약 문서 ↔ 실구현 대조 게이트 (감사 #25·#34·#35, 재검토 V2 P3/P5).

권위 체인 4위(contracts/)가 구현보다 낡아도 CI 가 침묵하던 사각지대를 닫는다:
openapi-core.yaml 의 **비-planned 경로는 실제 FastAPI 앱에 존재해야 하고**,
asyncapi 의 $ref 는 존재하는 최신 세대 스키마 파일을 가리켜야 한다.

경로 키만 대조하면 놓치는 사각지대(재검토 P3)를 추가로 닫는다:
① 문서가 선언한 메서드가 그 경로에 실제로 존재하는지, ② 구현에 있는 ``/v1/*``
경로가 문서에서 아예 빠지지 않았는지(경로 신설 후 문서 누락 방지), ③ 공개
allowlist(``/health``·``/capabilities``) 밖의 문서화된 경로가 전부
``security`` 를 선언하는지.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENAPI = _REPO_ROOT / "contracts" / "api" / "openapi-core.yaml"
_ASYNCAPI = _REPO_ROOT / "contracts" / "api" / "asyncapi-edge.yaml"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("contract-sync-test-token"),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})
_PUBLIC_PATHS = frozenset({"/health", "/capabilities"})


def _max_assembly(tmp_path: Path) -> Any:
    """최대 조립(모든 조건부 라우터 장착) 앱 — 문서는 구현 가능한 전체 표면을
    기술하므로, 부분 조립과 비교하면 조건부 라우터가 가짜 미구현이 된다."""
    return create_app(
        auth_registry=_auth_registry(),
        edge_sync_store=EdgeSyncStore(tmp_path / "journal.jsonl"),
        event_store=EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl")),
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="contract-sync-test-key",
    )


def _implemented_operations(tmp_path: Path) -> dict[str, set[str]]:
    """경로 → 실구현 HTTP 메서드 집합(최대 조립 기준)."""
    paths = _max_assembly(tmp_path).openapi()["paths"]
    return {path: {m for m in item if m in _HTTP_METHODS} for path, item in paths.items()}


def _implemented_paths(tmp_path: Path) -> set[str]:
    return set(_implemented_operations(tmp_path))


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


@pytest.mark.parametrize(
    "path",
    [
        "/v1/sites/{site_id}",
        "/v1/events/{event_key}",
        "/v1/missions/{mission_id}",
    ],
)
def test_query_paths_are_documented_as_implemented(path: str, tmp_path: Path) -> None:
    """역방향 anchor — 사이트·이벤트·미션 조회 경로가 문서에서 빠지거나 planned 로
    강등되면 실패(감사 #25·#35 사각지대: ADR-KSI-008 신규 조회 표면도 동일 게이트).

    ``event_key`` = ``{edgeDeviceId}::{eventId}`` — event_key 도입(P1 파급)으로
    구경로 ``{event_id}`` 는 더 이상 존재하지 않는다(events.py)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    spec = doc["paths"].get(path)
    assert spec is not None and spec.get("x-status") != "planned"
    assert path in _implemented_paths(tmp_path)


def test_documented_methods_exist_in_implementation(tmp_path: Path) -> None:
    """① 메서드 집합 대조 — 문서가 어떤 경로에 선언한 메서드는 실구현에도 있어야
    한다. 경로 키만 대조하면, 문서가 ``GET`` 뿐인 경로에 실구현에 없는 ``POST``
    를 얹어도 기존 게이트가 침묵했다(재검토 P3)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    implemented = _implemented_operations(tmp_path)

    missing: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned":
            continue
        doc_methods = {method for method in spec if method in _HTTP_METHODS}
        impl_methods = implemented.get(path, set())
        missing.extend(
            f"{method.upper()} {path}" for method in doc_methods if method not in impl_methods
        )

    assert not missing, (
        f"openapi-core.yaml 이 실구현에 없는 메서드를 문서화한다: {missing}"
    )


def test_implemented_v1_paths_are_documented(tmp_path: Path) -> None:
    """② 역방향 대조(전수) — 실구현의 ``/v1/*`` 경로가 문서에서 통째로 빠지면
    실패한다. 개별 anchor 테스트(위)는 알려진 경로만 지키므로, 신규 라우터가
    문서화 없이 조립되는 사각지대는 이 전수 검사만 잡는다(재검토 P3). FastAPI
    기본 문서 라우트(/openapi.json 등)는 OpenAPI ``paths`` 스키마 자체에 나타나지
    않으므로 allowlist가 불필요하다."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    documented = set(doc["paths"])
    implemented = _implemented_operations(tmp_path)

    undocumented = {
        path for path in implemented if path.startswith("/v1/") and path not in documented
    }
    assert not undocumented, (
        f"실구현에 있는 /v1/* 경로가 openapi-core.yaml 에 없다: {undocumented}"
    )


def test_protected_paths_declare_security_in_doc() -> None:
    """③ 보호 경로의 security 선언 검사(문서 측) — 공개 allowlist(/health·
    /capabilities) 밖의 non-planned 경로는 전부 ``security`` 를 선언해야 한다.
    실구현은 FastAPI 보안 유틸을 쓰지 않아(수동 Authorization 헤더 파싱) 앱
    OpenAPI 출력에 security 가 자동으로 실리지 않으므로, 이 검사는 문서 자체의
    자기일관성만 본다(재검토 P3)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))

    violations: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned" or path in _PUBLIC_PATHS:
            continue
        for method, operation in spec.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            if "security" not in operation:
                violations.append(f"{method.upper()} {path}")

    assert not violations, f"보호 경로인데 security 선언이 없다: {violations}"


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

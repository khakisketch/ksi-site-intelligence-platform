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
import re
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


class _NullEvidenceStorage:
    """포트 계약만 만족하는 조립용 스텁 — 이 게이트는 경로 존재만 본다.

    ``evidence_storage`` 를 주지 않으면 증거 라우터가 장착되지 않아(ADR-KSI-010 §1)
    "최대 조립"이라는 이름이 거짓이 된다 — 실제로 2026-08-04 에 증거 경로 2개가
    문서 대조 없이 통과했다.
    """

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _max_assembly(tmp_path: Path) -> Any:
    """최대 조립(모든 조건부 라우터 장착) 앱 — 문서는 구현 가능한 전체 표면을
    기술하므로, 부분 조립과 비교하면 조건부 라우터가 가짜 미구현이 된다."""
    return create_app(
        evidence_storage=_NullEvidenceStorage(),
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


# ── ④·⑤ 응답 본문 대조 (risk api-contract-response-schema-void) ─────────────
#
# 위 검사들은 경로·메서드·security 존재만 본다. 그래서 Core 가
# EventSummaryResponse 에 ``eventType`` 을 추가했을 때(2026-08-04) 게이트가
# 침묵했다 — 문서가 응답을 자유 문자열 description 으로만 적어 **대조할 정본
# 자체가 없었기** 때문이다. 소비자(apps/dashboard 의 types.ts)는 이 계약의 수동
# 복제본이라, 서버가 필드를 바꿔도 프런트 타입체크는 green 이고 런타임에서만
# 깨진다. 아래 둘이 그 구멍을 닫는다.


def _doc() -> dict[str, Any]:
    return yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))


def _implemented_spec(tmp_path: Path) -> dict[str, Any]:
    return _max_assembly(tmp_path).openapi()


def _ref_name(node: Any) -> str | None:
    """스키마 노드가 named 모델(또는 그 배열)을 가리키면 모델 이름을 준다.

    자유 형태 dict 응답(``/health``·서명된 MissionContract 등)은 None — 대조
    대상이 아니다. 그 응답들의 구조 정본은 ``contracts/schemas/*.json`` 이다.
    """
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    if node.get("type") == "array":
        return _ref_name(node.get("items"))
    return None


def _json_schema(response: Any) -> Any:
    if not isinstance(response, dict):
        return None
    return ((response.get("content") or {}).get("application/json") or {}).get("schema")


def test_documented_response_schemas_match_implementation_fields(tmp_path: Path) -> None:
    """④ 필드 집합 대조 — 문서 ``components/schemas`` 의 각 모델은 실구현과
    **필드 이름·필수 여부가 정확히 일치**해야 한다.

    타입까지는 보지 않는다(문서는 구현의 정밀도를 복제하지 않는다) — 잡으려는
    실패는 "한쪽에만 필드가 생기거나 사라지는 것"이다.
    """
    doc_schemas = (_doc().get("components") or {}).get("schemas") or {}
    assert doc_schemas, (
        "openapi-core.yaml 에 components/schemas 가 없다 — 응답 본문을 자유 문자열 "
        "description 으로만 적으면 대조할 정본이 사라진다(risk "
        "api-contract-response-schema-void 가 정확히 그 상태였다)"
    )
    impl_schemas = (_implemented_spec(tmp_path).get("components") or {}).get("schemas") or {}

    mismatches: list[str] = []
    for name, spec in doc_schemas.items():
        impl = impl_schemas.get(name)
        if impl is None:
            mismatches.append(f"{name}: 문서에만 있는 모델(구현에 없음)")
            continue
        doc_fields = set(spec.get("properties") or {})
        impl_fields = set(impl.get("properties") or {})
        if doc_fields != impl_fields:
            mismatches.append(
                f"{name}: 문서에만 {sorted(doc_fields - impl_fields)} / "
                f"구현에만 {sorted(impl_fields - doc_fields)}"
            )
        doc_required = set(spec.get("required") or [])
        impl_required = set(impl.get("required") or [])
        if doc_required != impl_required:
            mismatches.append(
                f"{name}.required: 문서에만 {sorted(doc_required - impl_required)} / "
                f"구현에만 {sorted(impl_required - doc_required)}"
            )

    assert not mismatches, (
        "openapi-core.yaml 의 응답 스키마가 실구현과 갈라졌다 — 구현을 바꿨으면 "
        f"계약도 같이 바꿔라: {mismatches}"
    )


def test_named_response_models_are_bound_in_doc(tmp_path: Path) -> None:
    """⑤ 바인딩 검사 — 실구현이 named 모델을 반환하는 operation 은 문서의 2xx
    응답 중 하나가 **같은 이름을 ``$ref``** 해야 한다.

    이게 없으면 ④는 이미 적힌 스키마만 지킬 뿐, 새 엔드포인트가 자유 문자열
    description 만 달고 들어오는 경로(원래의 실패 모드)를 막지 못한다.

    **상태코드까지 묶어서 본다.** 원래는 operation 의 2xx 집합만 비교했는데, 그건
    FastAPI 가 ``Response(status_code=...)`` 동적 지정을 OpenAPI 에 200 으로 남겨
    구현 선언이 실제 런타임과 달랐기 때문이다(POST /v1/sites 는 런타임 201·선언
    200). 그 원인을 라우터 쪽에서 고쳤으므로(``status_code=201`` 명시) 이제 코드
    단위 대조가 성립한다 — 문서와 구현이 서로 다른 코드를 말하면 실패한다.
    """
    doc = _doc()
    impl_paths = _implemented_spec(tmp_path)["paths"]

    violations: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned":
            continue
        for method, operation in spec.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            impl_op = (impl_paths.get(path) or {}).get(method) or {}
            impl_bindings = {
                (code, model)
                for code, response in (impl_op.get("responses") or {}).items()
                if code.startswith("2")
                for model in [_ref_name(_json_schema(response))]
                if model is not None
            }
            if not impl_bindings:
                continue
            doc_bindings = {
                (str(code), model)
                for code, response in (operation.get("responses") or {}).items()
                if str(code).startswith("2")
                for model in [_ref_name(_json_schema(response))]
                if model is not None
            }
            unbound = impl_bindings - doc_bindings
            if unbound:
                violations.append(
                    f"{method.upper()} {path}: {sorted(f'{c} {m}' for c, m in unbound)}"
                )

    assert not violations, (
        "실구현이 반환하는 응답 모델을 문서가 $ref 로 묶지 않았다 — 자유 문자열 "
        f"description 은 대조되지 않는다: {violations}"
    )


# ── ⑥ 소비자(대시보드) 대조 ────────────────────────────────────────────────
#
# ④·⑤ 는 Core ↔ 계약만 닫는다. 실제로 깨지는 자리는 하나 더 있다:
# ``apps/dashboard/src/lib/core-api/types.ts`` 는 이 계약의 **수동 복제본**이라,
# 서버가 필드를 바꿔도 프런트의 tsc 는 계속 green 이고 런타임에서만 undefined 가
# 흐른다. 계약과 이름이 같은 interface 는 필드 집합도 같아야 한다.

_DASHBOARD_TYPES = _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api" / "types.ts"

# 계약에 있지만 대시보드가 소비하지 않는 모델은 대조 대상이 아니다 —
# types.ts 에 같은 이름의 interface 가 있을 때만 본다(없는 것은 "아직 안 쓴다"는
# 정상 상태이지 drift 가 아니다).


def _parse_ts_interfaces(source: str) -> dict[str, tuple[set[str], str | None]]:
    """``export interface X extends Y { ... }`` → {X: (필드집합, 부모 or None)}.

    한 단계 중첩까지만 본다 — 이 파일의 모델은 전부 평면이고, 중첩이 생기면
    그 자체가 계약 형태를 벗어난 신호라 여기서 실패하는 편이 낫다.
    """
    result: dict[str, tuple[set[str], str | None]] = {}
    header = re.compile(r"^export interface (\w+)(?: extends (\w+))?\s*\{")
    field = re.compile(r"^\s{2}(\w+)\??:")
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        match = header.match(lines[index])
        if match is None:
            index += 1
            continue
        name, parent = match.group(1), match.group(2)
        fields: set[str] = set()
        depth = 1
        index += 1
        while index < len(lines) and depth > 0:
            line = lines[index]
            depth += line.count("{") - line.count("}")
            if depth > 0:
                found = field.match(line)
                if found is not None:
                    fields.add(found.group(1))
            index += 1
        result[name] = (fields, parent)
    return result


def test_dashboard_types_match_contract_schemas() -> None:
    """⑥ 소비자 대조 — types.ts 의 interface 가 계약 모델과 같은 이름이면 필드
    집합도 같아야 한다(상속은 펼쳐서 비교)."""
    doc_schemas = (_doc().get("components") or {}).get("schemas") or {}
    interfaces = _parse_ts_interfaces(_DASHBOARD_TYPES.read_text(encoding="utf-8"))
    assert interfaces, "types.ts 에서 interface 를 하나도 못 읽었다 — 파서가 깨졌다"

    def resolved(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        fields, parent = interfaces[name]
        if parent is None or parent in seen or parent not in interfaces:
            return set(fields)
        return set(fields) | resolved(parent, seen | {name})

    compared: list[str] = []
    mismatches: list[str] = []
    for name, spec in doc_schemas.items():
        if name not in interfaces:
            continue
        compared.append(name)
        contract_fields = set(spec.get("properties") or {})
        ts_fields = resolved(name)
        if contract_fields != ts_fields:
            mismatches.append(
                f"{name}: 계약에만 {sorted(contract_fields - ts_fields)} / "
                f"types.ts 에만 {sorted(ts_fields - contract_fields)}"
            )

    assert compared, (
        "계약 모델과 이름이 같은 interface 가 types.ts 에 하나도 없다 — 이름 규약이 "
        "바뀌었다면 이 게이트는 아무것도 지키지 못한다"
    )
    assert not mismatches, (
        "대시보드가 소비하는 타입이 계약과 갈라졌다 — 서버 필드가 바뀌면 프런트 "
        f"tsc 는 green 인 채 런타임에서만 깨진다: {mismatches}"
    )


# ── ⑥ 요청 본문 깊은 대조 (s2-residual-hardening #4) ────────────────────────
#
# ④/⑤가 닫은 것은 **응답** 쪽이다. 요청 본문은 문서에 인라인 object 로 적혀 있어
# 어떤 게이트도 실구현 요청 모델과 대조하지 않았다 — 서버가 새 필수 입력을
# 요구하기 시작해도(예: lawnmower 의 captureIntervalM) 계약은 조용히 낡는다.
# 클라이언트는 문서를 보고 만들므로, 이 방향의 drift 는 곧 통합 실패다.


def _resolve_ref(spec: dict[str, Any], node: Any) -> Any:
    """``$ref`` 를 실제 스키마로 펼친다(구현 spec 은 named 모델을 참조한다)."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node:
        seen += 1
        if seen > 32:  # 순환 참조 방어 — 무한 루프 대신 그대로 돌려준다
            return node
        pointer = node["$ref"]
        if not pointer.startswith("#/"):
            return node
        target: Any = spec
        for part in pointer[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
    return node


def _json_request_schema(spec: dict[str, Any], operation: dict[str, Any]) -> Any:
    body = operation.get("requestBody") or {}
    schema = ((body.get("content") or {}).get("application/json") or {}).get("schema")
    return _resolve_ref(spec, schema) if schema is not None else None


def _compare_object_fields(
    *,
    doc_spec: dict[str, Any],
    impl_spec: dict[str, Any],
    doc_node: Any,
    impl_node: Any,
    trail: str,
    mismatches: list[str],
) -> None:
    """두 스키마 트리의 object 계층을 필드 이름·필수 여부로 재귀 대조한다.

    타입까지는 보지 않는다 — ④와 같은 규약이다. 잡으려는 실패는 "한쪽에만
    필드가 생기거나 사라지는 것"과 "한쪽만 필수로 요구하는 것"이다.
    """
    doc_node = _resolve_ref(doc_spec, doc_node)
    impl_node = _resolve_ref(impl_spec, impl_node)
    if not isinstance(doc_node, dict) or not isinstance(impl_node, dict):
        return
    # anyOf/allOf(Optional 필드가 만드는 형태)는 object 분기 하나만 골라 내려간다.
    for combinator in ("anyOf", "allOf", "oneOf"):
        if combinator in impl_node and "properties" not in impl_node:
            for branch in impl_node[combinator]:
                resolved = _resolve_ref(impl_spec, branch)
                if isinstance(resolved, dict) and "properties" in resolved:
                    impl_node = resolved
                    break
    doc_props = doc_node.get("properties")
    impl_props = impl_node.get("properties")
    if not isinstance(doc_props, dict) or not isinstance(impl_props, dict):
        return

    doc_fields, impl_fields = set(doc_props), set(impl_props)
    if doc_fields != impl_fields:
        mismatches.append(
            f"{trail}: 문서에만 {sorted(doc_fields - impl_fields)} / "
            f"구현에만 {sorted(impl_fields - doc_fields)}"
        )
    doc_required = set(doc_node.get("required") or [])
    impl_required = set(impl_node.get("required") or [])
    if doc_required != impl_required:
        mismatches.append(
            f"{trail}.required: 문서에만 {sorted(doc_required - impl_required)} / "
            f"구현에만 {sorted(impl_required - doc_required)}"
        )
    for field in sorted(doc_fields & impl_fields):
        _compare_object_fields(
            doc_spec=doc_spec,
            impl_spec=impl_spec,
            doc_node=doc_props[field],
            impl_node=impl_props[field],
            trail=f"{trail}.{field}",
            mismatches=mismatches,
        )


def test_documented_request_bodies_match_implementation_fields(tmp_path: Path) -> None:
    """[핵심] 문서의 요청 본문 필드 집합·필수 여부가 실구현 요청 모델과 같아야 한다."""
    doc = _doc()
    impl = _implemented_spec(tmp_path)
    impl_paths = impl["paths"]

    mismatches: list[str] = []
    compared = 0
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            doc_schema = _json_request_schema(doc, operation)
            if doc_schema is None:
                continue
            impl_operation = (impl_paths.get(path) or {}).get(method)
            if not isinstance(impl_operation, dict):
                continue  # 경로·메서드 존재는 ①②가 이미 본다
            impl_schema = _json_request_schema(impl, impl_operation)
            if impl_schema is None:
                mismatches.append(f"{method.upper()} {path}: 구현에 JSON 요청 본문이 없다")
                continue
            compared += 1
            _compare_object_fields(
                doc_spec=doc,
                impl_spec=impl,
                doc_node=doc_schema,
                impl_node=impl_schema,
                trail=f"{method.upper()} {path}",
                mismatches=mismatches,
            )

    assert compared >= 3, (
        f"요청 본문을 가진 문서화 operation 이 너무 적다({compared}) — 게이트가 공허하다"
    )
    assert not mismatches, (
        "openapi-core.yaml 의 요청 본문이 실구현과 갈라졌다 — 구현이 새 입력을 "
        f"요구하기 시작했으면 계약도 같이 바꿔라: {mismatches}"
    )

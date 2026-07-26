"""ActionIntent 언어중립 계약 conformance — Python 측 (Stage C-4).

``contracts/conformance/action-intent-verdicts.v1.json`` 공유 벡터를 Python 참조
검증기로 실행한다. **같은 벡터를 C++ Control Plane도 각자 실행하며**
(``edge/manifold-runtime/tests/conformance_tests.cpp``), 두 실행 결과가 모두
``expectedVerdict``와 같아야 두 평면이 같은 계약을 같게 해석한다고 말할 수 있다.

한쪽만 통과하는 상황을 잡는 것이 이 테스트의 존재 이유다 — 판정 순서나 경계
처리가 언어별로 갈리면 여기서 드러난다.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_mission_contracts.action_intent import (
    ActionIntent,
    CommandVerdict,
    verify_action_intent,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VECTOR_PATH = _REPO_ROOT / "contracts" / "conformance" / "action-intent-verdicts.v1.json"
_SCHEMA_PATH = _REPO_ROOT / "contracts" / "schemas" / "action-intent.v1.json"
_GENERATED_HEADER = (
    _REPO_ROOT
    / "edge"
    / "manifold-runtime"
    / "tests"
    / "generated"
    / "action_intent_vectors.hpp"
)

_GENERATOR_PATH = _REPO_ROOT / "tools" / "generate_action_intent_vectors.py"

_VECTORS: dict[str, Any] = json.loads(_VECTOR_PATH.read_text(encoding="utf-8"))
_CASES: list[dict[str, Any]] = _VECTORS["cases"]


def _load_header_renderer() -> Callable[[dict[str, Any]], str]:
    """생성기를 파일 경로로 직접 로드한다.

    ``tools``는 설치 대상 패키지가 아니라 저장소 스크립트 디렉토리라 sys.path에
    있다는 보장이 없다 — 경로로 명시 로드해 실행 위치에 의존하지 않게 한다.
    """
    spec = importlib.util.spec_from_file_location(
        "ksi_action_intent_vector_generator", _GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    renderer: Callable[[dict[str, Any]], str] = module.render_header
    return renderer


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_python_verdict_matches_shared_vector(case: dict[str, Any]) -> None:
    verdict = verify_action_intent(
        case["intent"], _VECTORS["activeDigest"], case["nowUtcMs"]
    )
    assert verdict.value == case["expectedVerdict"], case["rationale"]


def test_all_verdict_values_are_known() -> None:
    """벡터가 참조하는 verdict가 전부 계약 enum에 존재해야 한다(오타 방지)."""
    known = {v.value for v in CommandVerdict}
    used = {case["expectedVerdict"] for case in _CASES}
    assert used <= known, f"계약에 없는 verdict: {used - known}"


def test_schema_file_is_valid_draft202012() -> None:
    Draft202012Validator.check_schema(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def test_wellformed_vector_intents_validate_against_schema() -> None:
    """MALFORMED/MISSING_AUTHORIZATION 케이스를 뺀 나머지는 스키마를 통과해야 한다.

    형식 위반 케이스는 **의도적으로** 스키마를 어기는 입력이므로 제외한다 — 그
    입력들이 스키마를 통과한다면 오히려 스키마가 느슨하다는 뜻이다(아래 별도 검증).
    """
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    wellformed = [
        c
        for c in _CASES
        if c["expectedVerdict"] not in {"MALFORMED", "MISSING_AUTHORIZATION"}
    ]
    assert wellformed, "정상 형식 케이스가 하나도 없다 — 벡터 구성 오류"
    for case in wellformed:
        validator.validate(case["intent"])


def test_malformed_vector_intents_are_rejected_by_schema() -> None:
    """형식 위반 케이스는 JSON Schema 단계에서도 걸러져야 한다(이중 방어)."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    malformed = [
        c
        for c in _CASES
        if c["expectedVerdict"] in {"MALFORMED", "MISSING_AUTHORIZATION"}
    ]
    assert malformed, "형식 위반 케이스가 없다 — 네거티브 커버리지 부족"
    for case in malformed:
        assert not validator.is_valid(case["intent"]), (
            f"{case['id']}: 런타임은 거부하는데 스키마는 통과시킨다 — 스키마가 느슨하다"
        )


def test_pydantic_model_accepts_valid_intent() -> None:
    valid = next(c for c in _CASES if c["expectedVerdict"] == "ACCEPTED")
    model = ActionIntent.model_validate(valid["intent"])
    assert model.command_id == valid["intent"]["commandId"]
    assert model.ttl_ms > 0


@pytest.mark.parametrize("bad_digest", ["", "sha256:xyz", "md5:" + "a" * 32, "a" * 64])
def test_pydantic_model_rejects_bad_digest_format(bad_digest: str) -> None:
    valid = next(c for c in _CASES if c["expectedVerdict"] == "ACCEPTED")
    data = dict(valid["intent"])
    data["authorizationDigest"] = bad_digest
    with pytest.raises(ValidationError):
        ActionIntent.model_validate(data)


def test_model_forbids_low_level_control_verbs() -> None:
    """[INV-001] 계약에 저수준 조종 동사가 새로 들어오지 않았는지 고정한다."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    kinds = set(schema["properties"]["kind"]["enum"])
    assert kinds == {"HOLD", "RETURN_TO_HOME", "GOTO_VIEWPOINT", "CAPTURE_IMAGE"}
    forbidden = {"SET_VELOCITY", "SET_ATTITUDE", "SET_THROTTLE", "ARM", "TAKEOFF"}
    assert kinds.isdisjoint(forbidden), "저수준 조종 동사가 계약에 추가됐다 — INV-001 위반"


def test_generated_cpp_header_is_up_to_date() -> None:
    """C++ 쪽 벡터 헤더가 JSON 원본과 동기 상태인지 확인한다(drift 차단).

    헤더는 ``tools/generate_action_intent_vectors.py`` 가 JSON에서 생성한다 —
    JSON만 고치고 헤더를 갱신하지 않으면 C++는 낡은 벡터로 통과해버리므로,
    여기서 재생성 결과와 커밋된 파일을 비교한다.
    """
    expected = _load_header_renderer()(_VECTORS)
    actual = _GENERATED_HEADER.read_text(encoding="utf-8")
    assert actual == expected, (
        "생성된 C++ 벡터 헤더가 JSON 원본과 다르다 — "
        "`uv run python tools/generate_action_intent_vectors.py` 로 재생성하라"
    )

#!/usr/bin/env python3
"""ActionIntent conformance 벡터(JSON) → C++ 헤더 생성기 (Stage C-4).

C++ Control Plane 테스트는 외부 JSON 파서 의존 없이 돌아야 하므로(네트워크 fetch
없는 CI 원칙), 공유 벡터를 컴파일 타임 상수 배열로 펼친 헤더를 생성한다.

**단일 진실원천은 JSON이다.** 생성된 헤더는 커밋되지만 손으로 고치지 않으며,
JSON만 고치고 헤더를 갱신하지 않는 drift는
``tests/contract/test_action_intent_conformance.py::test_generated_cpp_header_is_up_to_date``
가 잡는다.

사용:
    uv run python tools/generate_action_intent_vectors.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VECTOR_PATH = _REPO_ROOT / "contracts" / "conformance" / "action-intent-verdicts.v1.json"
_OUTPUT_PATH = (
    _REPO_ROOT
    / "edge"
    / "manifold-runtime"
    / "tests"
    / "generated"
    / "action_intent_vectors.hpp"
)

_KIND_TO_CPP = {
    "HOLD": "ActionIntentKind::kHold",
    "RETURN_TO_HOME": "ActionIntentKind::kReturnToHome",
    "GOTO_VIEWPOINT": "ActionIntentKind::kGotoViewpoint",
    "CAPTURE_IMAGE": "ActionIntentKind::kCaptureImage",
}

_VERDICT_TO_CPP = {
    "ACCEPTED": "CommandVerdict::kAccepted",
    "EXPIRED": "CommandVerdict::kExpired",
    "NOT_YET_VALID": "CommandVerdict::kNotYetValid",
    "MISSING_AUTHORIZATION": "CommandVerdict::kMissingAuthorization",
    "AUTHORIZATION_MISMATCH": "CommandVerdict::kAuthorizationMismatch",
    "MALFORMED": "CommandVerdict::kMalformed",
    "SUPERVISOR_NOT_READY": "CommandVerdict::kSupervisorNotReady",
}


def _cpp_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_header(vectors: dict[str, Any]) -> str:
    """벡터 dict → C++ 헤더 문자열. 결정적이어야 한다(테스트가 문자열 동치로 비교)."""
    lines: list[str] = [
        "// 자동 생성 파일 — 손으로 고치지 마시오.",
        "// 생성기: tools/generate_action_intent_vectors.py",
        "// 원본(SSOT): contracts/conformance/action-intent-verdicts.v1.json",
        "//",
        "// 이 헤더는 Python Intelligence Plane과 공유하는 conformance 벡터를 컴파일",
        "// 타임 상수로 펼친 것이다. 두 언어가 같은 입력에 같은 verdict를 내는지",
        "// 각자 검증하며, 어긋나면 계약 해석이 갈렸다는 뜻이다.",
        "",
        "#ifndef KSI_GENERATED_ACTION_INTENT_VECTORS_HPP",
        "#define KSI_GENERATED_ACTION_INTENT_VECTORS_HPP",
        "",
        "#include <cstdint>",
        "",
        '#include "ksi/control_plane/command.hpp"',
        "",
        "namespace ksi::conformance {",
        "",
        "struct ActionIntentVector {",
        "    const char* id;",
        "    const char* schema_version;",
        "    const char* command_id;",
        "    control_plane::ActionIntentKind kind;",
        "    const char* authorization_digest;",
        "    std::int64_t issued_at_utc_ms;",
        "    std::int64_t ttl_ms;",
        "    const char* target_viewpoint_id; // 빈 문자열 = 부재",
        "    std::int64_t now_utc_ms;",
        "    control_plane::CommandVerdict expected;",
        "};",
        "",
        f"inline constexpr const char* kActiveDigest = {_cpp_string(vectors['activeDigest'])};",
        "",
        "inline constexpr ActionIntentVector kActionIntentVectors[] = {",
    ]

    for case in vectors["cases"]:
        intent = case["intent"]
        kind = _KIND_TO_CPP[intent["kind"]]
        verdict = _VERDICT_TO_CPP[case["expectedVerdict"]]
        lines.append("    {")
        lines.append(f"        {_cpp_string(case['id'])},")
        lines.append(f"        {_cpp_string(intent['schemaVersion'])},")
        lines.append(f"        {_cpp_string(intent['commandId'])},")
        lines.append(f"        control_plane::{kind},")
        lines.append(f"        {_cpp_string(intent['authorizationDigest'])},")
        lines.append(f"        {intent['issuedAtUtcMs']},")
        lines.append(f"        {intent['ttlMs']},")
        lines.append(f"        {_cpp_string(intent.get('targetViewpointId', ''))},")
        lines.append(f"        {case['nowUtcMs']},")
        lines.append(f"        control_plane::{verdict},")
        lines.append("    },")

    lines.extend(
        [
            "};",
            "",
            "inline constexpr std::size_t kActionIntentVectorCount =",
            "    sizeof(kActionIntentVectors) / sizeof(kActionIntentVectors[0]);",
            "",
            "} // namespace ksi::conformance",
            "",
            "#endif // KSI_GENERATED_ACTION_INTENT_VECTORS_HPP",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    vectors = json.loads(_VECTOR_PATH.read_text(encoding="utf-8"))
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(render_header(vectors), encoding="utf-8")
    print(f"생성: {_OUTPUT_PATH.relative_to(_REPO_ROOT)} ({len(vectors['cases'])}개 케이스)")


if __name__ == "__main__":
    main()

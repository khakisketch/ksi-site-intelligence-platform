// ActionIntent 언어중립 계약 conformance — C++ 측 (Stage C-4).
//
// Python Intelligence Plane과 **같은 공유 벡터**를 실행해 동일한 verdict가 나오는지
// 확인한다. Python 측은 tests/contract/test_action_intent_conformance.py 가 같은
// JSON을 직접 읽어 실행하며, 이 파일은 그 JSON에서 생성된 헤더를 쓴다
// (생성기: tools/generate_action_intent_vectors.py, drift는 Python 테스트가 감시).
//
// 두 언어 중 한쪽만 통과하면 계약 해석이 갈렸다는 뜻이다 — 그것이 이 테스트의
// 존재 이유다.

#include <cstdio>
#include <string>

#include "generated/action_intent_vectors.hpp"
#include "ksi/control_plane/command.hpp"

int main() {
    using ksi::control_plane::ActionIntent;
    using ksi::control_plane::CommandVerdict;
    using ksi::control_plane::ToString;
    using ksi::control_plane::VerifyActionIntent;

    int failures = 0;
    const std::string active_digest = ksi::conformance::kActiveDigest;

    for (std::size_t i = 0; i < ksi::conformance::kActionIntentVectorCount; ++i) {
        const auto& vector = ksi::conformance::kActionIntentVectors[i];

        ActionIntent intent;
        intent.schema_version = vector.schema_version;
        intent.command_id = vector.command_id;
        intent.kind = vector.kind;
        intent.authorization_digest = vector.authorization_digest;
        intent.issued_at_utc_ms = vector.issued_at_utc_ms;
        intent.ttl_ms = vector.ttl_ms;
        intent.target_viewpoint_id = vector.target_viewpoint_id;

        const CommandVerdict actual =
            VerifyActionIntent(intent, active_digest, vector.now_utc_ms);
        if (actual != vector.expected) {
            ++failures;
            std::fprintf(stderr, "FAIL[%s]: expected=%s actual=%s\n", vector.id,
                         ToString(vector.expected), ToString(actual));
        }
    }

    if (ksi::conformance::kActionIntentVectorCount == 0) {
        // 벡터가 비면 "전부 통과"처럼 보이는 가짜 green이 된다 — 명시적으로 실패시킨다.
        std::fprintf(stderr, "FAIL: conformance 벡터가 비어 있다\n");
        ++failures;
    }

    std::printf("ActionIntent conformance: %zu개 벡터 중 %d개 실패\n",
                ksi::conformance::kActionIntentVectorCount, failures);
    return failures == 0 ? 0 : 1;
}

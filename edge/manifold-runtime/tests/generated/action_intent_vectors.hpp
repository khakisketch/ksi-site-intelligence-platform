// 자동 생성 파일 — 손으로 고치지 마시오.
// 생성기: tools/generate_action_intent_vectors.py
// 원본(SSOT): contracts/conformance/action-intent-verdicts.v1.json
//
// 이 헤더는 Python Intelligence Plane과 공유하는 conformance 벡터를 컴파일
// 타임 상수로 펼친 것이다. 두 언어가 같은 입력에 같은 verdict를 내는지
// 각자 검증하며, 어긋나면 계약 해석이 갈렸다는 뜻이다.

#ifndef KSI_GENERATED_ACTION_INTENT_VECTORS_HPP
#define KSI_GENERATED_ACTION_INTENT_VECTORS_HPP

#include <cstdint>

#include "ksi/control_plane/command.hpp"

namespace ksi::conformance {

struct ActionIntentVector {
    const char* id;
    const char* command_id;
    control_plane::ActionIntentKind kind;
    const char* authorization_digest;
    std::int64_t issued_at_utc_ms;
    std::int64_t ttl_ms;
    std::int64_t now_utc_ms;
    control_plane::CommandVerdict expected;
};

inline constexpr const char* kActiveDigest = "sha256:1111111111111111111111111111111111111111111111111111111111111111";

inline constexpr ActionIntentVector kActionIntentVectors[] = {
    {
        "valid_within_ttl",
        "cmd-1",
        control_plane::ActionIntentKind::kGotoViewpoint,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        1001000,
        control_plane::CommandVerdict::kAccepted,
    },
    {
        "ttl_boundary_is_expired",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        1005000,
        control_plane::CommandVerdict::kExpired,
    },
    {
        "just_before_ttl_still_valid",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        1004999,
        control_plane::CommandVerdict::kAccepted,
    },
    {
        "expired_well_past_ttl",
        "cmd-1",
        control_plane::ActionIntentKind::kCaptureImage,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        9999999,
        control_plane::CommandVerdict::kExpired,
    },
    {
        "future_issued_rejected",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        999999,
        control_plane::CommandVerdict::kNotYetValid,
    },
    {
        "missing_authorization",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "",
        1000000,
        5000,
        1001000,
        control_plane::CommandVerdict::kMissingAuthorization,
    },
    {
        "authorization_mismatch",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        1000000,
        5000,
        1001000,
        control_plane::CommandVerdict::kAuthorizationMismatch,
    },
    {
        "malformed_empty_command_id",
        "",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_zero_ttl",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        0,
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_negative_ttl",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        -1,
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_precedes_missing_authorization",
        "",
        control_plane::ActionIntentKind::kHold,
        "",
        1000000,
        5000,
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "authorization_checked_before_expiry",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        1000000,
        5000,
        9999999,
        control_plane::CommandVerdict::kAuthorizationMismatch,
    },
};

inline constexpr std::size_t kActionIntentVectorCount =
    sizeof(kActionIntentVectors) / sizeof(kActionIntentVectors[0]);

} // namespace ksi::conformance

#endif // KSI_GENERATED_ACTION_INTENT_VECTORS_HPP

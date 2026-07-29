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
    const char* schema_version;
    const char* command_id;
    control_plane::ActionIntentKind kind;
    const char* authorization_digest;
    std::int64_t issued_at_utc_ms;
    std::int64_t ttl_ms;
    const char* target_viewpoint_id; // 빈 문자열 = 부재
    std::int64_t now_utc_ms;
    control_plane::CommandVerdict expected;
};

inline constexpr const char* kActiveDigest = "sha256:1111111111111111111111111111111111111111111111111111111111111111";

inline constexpr ActionIntentVector kActionIntentVectors[] = {
    {
        "valid_within_ttl",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kGotoViewpoint,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "vp-001",
        1001000,
        control_plane::CommandVerdict::kAccepted,
    },
    {
        "ttl_boundary_is_expired",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        1005000,
        control_plane::CommandVerdict::kExpired,
    },
    {
        "just_before_ttl_still_valid",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        1004999,
        control_plane::CommandVerdict::kAccepted,
    },
    {
        "expired_well_past_ttl",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kCaptureImage,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        9999999,
        control_plane::CommandVerdict::kExpired,
    },
    {
        "future_issued_rejected",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        999999,
        control_plane::CommandVerdict::kNotYetValid,
    },
    {
        "missing_authorization",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMissingAuthorization,
    },
    {
        "authorization_mismatch",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kAuthorizationMismatch,
    },
    {
        "malformed_empty_command_id",
        "1.0",
        "",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_zero_ttl",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        0,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_negative_ttl",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        -1,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "malformed_precedes_missing_authorization",
        "1.0",
        "",
        control_plane::ActionIntentKind::kHold,
        "",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "authorization_checked_before_expiry",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        1000000,
        5000,
        "",
        9999999,
        control_plane::CommandVerdict::kAuthorizationMismatch,
    },
    {
        "unsupported_schema_version_rejected",
        "2.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "ttl_above_max_rejected",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        300001,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "ttl_at_max_still_valid",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        300000,
        "",
        1299999,
        control_plane::CommandVerdict::kAccepted,
    },
    {
        "issued_at_negative_rejected",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        -1,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "issued_at_extreme_no_overflow",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        -9000000000000000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "now_out_of_domain_rejected",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kHold,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        -5,
        control_plane::CommandVerdict::kMalformed,
    },
    {
        "goto_without_target_rejected",
        "1.0",
        "cmd-1",
        control_plane::ActionIntentKind::kGotoViewpoint,
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        1000000,
        5000,
        "",
        1001000,
        control_plane::CommandVerdict::kMalformed,
    },
};

inline constexpr std::size_t kActionIntentVectorCount =
    sizeof(kActionIntentVectors) / sizeof(kActionIntentVectors[0]);

} // namespace ksi::conformance

#endif // KSI_GENERATED_ACTION_INTENT_VECTORS_HPP

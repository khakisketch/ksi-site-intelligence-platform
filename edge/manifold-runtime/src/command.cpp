#include "ksi/control_plane/command.hpp"

namespace ksi::control_plane {

CommandVerdict VerifyActionIntent(const ActionIntent& intent,
                                  const std::string& active_digest,
                                  UtcMillis now_utc_ms) {
    // 형식 게이트(감사 #14·#16~#18 폐쇄) — 판정 순서는 Python 참조 검증기와
    // 동일해야 하며(schemaVersion → command_id → ttl → issued → now → kind별
    // 필수 필드), 어긋나면 conformance 벡터가 잡는다.
    if (intent.schema_version != "1.0") {
        return CommandVerdict::kMalformed;
    }
    if (intent.command_id.empty()) {
        return CommandVerdict::kMalformed;
    }
    if (intent.ttl_ms <= 0 || intent.ttl_ms > kMaxTtlMs) {
        return CommandVerdict::kMalformed;
    }
    // 시각 도메인 선검사 — 이후 now - issued 뺄셈이 int64 안에서 절대 넘치지
    // 않는다(도메인 폭 ±kMaxUtcMs). 선검사 없던 초판은 INT64_MIN 급 issued_at
    // 에서 signed overflow(UB)로 kAccepted 가 나올 수 있었다(감사 #14 실증).
    if (intent.issued_at_utc_ms < 0 || intent.issued_at_utc_ms > kMaxUtcMs) {
        return CommandVerdict::kMalformed;
    }
    if (now_utc_ms < 0 || now_utc_ms > kMaxUtcMs) {
        return CommandVerdict::kMalformed;
    }
    if (intent.kind == ActionIntentKind::kGotoViewpoint && intent.target_viewpoint_id.empty()) {
        // 목적지 없는 이동 의도 — 하류가 기본값을 지어내는 fail-open 을 계약이 차단.
        return CommandVerdict::kMalformed;
    }
    if (intent.authorization_digest.empty()) {
        return CommandVerdict::kMissingAuthorization;
    }
    // 활성 계약이 없으면(빈 digest) 어떤 명령도 인가할 수 없다 — 부팅 직후 상태.
    if (active_digest.empty() || intent.authorization_digest != active_digest) {
        return CommandVerdict::kAuthorizationMismatch;
    }
    if (intent.issued_at_utc_ms > now_utc_ms) {
        // 미래에 발행된 명령 — 시계 이상이거나 위조다. 낙관적으로 받아들이지 않는다.
        return CommandVerdict::kNotYetValid;
    }
    // TTL 경계는 배타적이다: issued_at + ttl 시점에 명령은 이미 만료된 것으로 본다
    // (경계에서 관대한 쪽이 아니라 보수적인 쪽을 택한다).
    if (now_utc_ms - intent.issued_at_utc_ms >= intent.ttl_ms) {
        return CommandVerdict::kExpired;
    }
    return CommandVerdict::kAccepted;
}

const char* ToString(CommandVerdict verdict) {
    switch (verdict) {
    case CommandVerdict::kAccepted:
        return "ACCEPTED";
    case CommandVerdict::kExpired:
        return "EXPIRED";
    case CommandVerdict::kNotYetValid:
        return "NOT_YET_VALID";
    case CommandVerdict::kMissingAuthorization:
        return "MISSING_AUTHORIZATION";
    case CommandVerdict::kAuthorizationMismatch:
        return "AUTHORIZATION_MISMATCH";
    case CommandVerdict::kMalformed:
        return "MALFORMED";
    case CommandVerdict::kSupervisorNotReady:
        return "SUPERVISOR_NOT_READY";
    }
    return "UNKNOWN";
}

} // namespace ksi::control_plane

#include "ksi/control_plane/command.hpp"

namespace ksi::control_plane {

CommandVerdict VerifyActionIntent(const ActionIntent& intent,
                                  const std::string& active_digest,
                                  UtcMillis now_utc_ms) {
    if (intent.command_id.empty() || intent.ttl_ms <= 0) {
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

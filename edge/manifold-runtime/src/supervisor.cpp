#include "ksi/control_plane/supervisor.hpp"

#include <stdexcept>

namespace ksi::control_plane {

FlightSupervisor::FlightSupervisor(std::int64_t degrade_after_ms,
                                   std::int64_t fail_closed_after_ms)
    : degrade_after_ms_(degrade_after_ms), fail_closed_after_ms_(fail_closed_after_ms) {
    if (degrade_after_ms <= 0 || fail_closed_after_ms <= 0) {
        throw std::invalid_argument("heartbeat 임계값은 양수여야 한다");
    }
    if (fail_closed_after_ms <= degrade_after_ms) {
        // degrade 없이 곧장 fail-closed로 가는 설정은 의도치 않은 오배선일 가능성이
        // 높다 — 조용히 받아들이지 않고 생성 시점에 거부한다.
        throw std::invalid_argument("fail_closed_after_ms 는 degrade_after_ms 보다 커야 한다");
    }
}

void FlightSupervisor::RecordHeartbeat(UtcMillis observed_at_utc_ms) {
    if (has_heartbeat_ && observed_at_utc_ms <= last_heartbeat_utc_ms_) {
        // 역행·중복 heartbeat는 무시한다 — 과거 heartbeat로 상태를 되살릴 수 없다.
        return;
    }
    has_heartbeat_ = true;
    last_heartbeat_utc_ms_ = observed_at_utc_ms;
}

SupervisorState FlightSupervisor::StateAt(UtcMillis now_utc_ms) const {
    if (!has_heartbeat_) {
        // 증거 없음 = 정상 아님. 부팅 직후 기본값이 fail-closed인 이유다.
        return SupervisorState::kFailClosed;
    }
    const std::int64_t elapsed = now_utc_ms - last_heartbeat_utc_ms_;
    if (elapsed < 0) {
        // 시계가 역행했다 — 경과 시간을 신뢰할 수 없으므로 보수적으로 판단한다.
        return SupervisorState::kFailClosed;
    }
    if (elapsed >= fail_closed_after_ms_) {
        return SupervisorState::kFailClosed;
    }
    if (elapsed >= degrade_after_ms_) {
        return SupervisorState::kDegraded;
    }
    return SupervisorState::kNominal;
}

bool FlightSupervisor::MayStartNewAction(UtcMillis now_utc_ms) const {
    return StateAt(now_utc_ms) == SupervisorState::kNominal;
}

CommandVerdict FlightSupervisor::Authorize(const ActionIntent& intent,
                                           const std::string& active_digest,
                                           UtcMillis now_utc_ms) const {
    const CommandVerdict verdict = VerifyActionIntent(intent, active_digest, now_utc_ms);
    if (verdict != CommandVerdict::kAccepted) {
        return verdict;
    }
    if (!MayStartNewAction(now_utc_ms)) {
        // 명령 자체는 유효하다 — 거부 사유는 인가가 아니라 Edge 상태다. 두 실패
        // 모드를 같은 verdict로 뭉개면 운영자가 "계약이 잘못됐다"고 오진단하므로
        // 별도 사유로 구분한다.
        return CommandVerdict::kSupervisorNotReady;
    }
    return CommandVerdict::kAccepted;
}

const char* ToString(SupervisorState state) {
    switch (state) {
    case SupervisorState::kFailClosed:
        return "FAIL_CLOSED";
    case SupervisorState::kNominal:
        return "NOMINAL";
    case SupervisorState::kDegraded:
        return "DEGRADED";
    }
    return "UNKNOWN";
}

} // namespace ksi::control_plane

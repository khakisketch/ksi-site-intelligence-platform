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

HeartbeatVerdict FlightSupervisor::RecordHeartbeat(UtcMillis observed_at_utc_ms,
                                                   UtcMillis now_utc_ms) {
    if (observed_at_utc_ms < 0 || observed_at_utc_ms > kMaxUtcMs || now_utc_ms < 0 ||
        now_utc_ms > kMaxUtcMs) {
        // 도메인 밖 시각 — 판정 불가는 기록 거부다. 도메인 안이면 아래 뺄셈·비교가
        // int64 에서 절대 넘치지 않는다(감사 #53 오버플로 가드와 같은 원리).
        return HeartbeatVerdict::kOutOfDomain;
    }
    if (observed_at_utc_ms > now_utc_ms + kHeartbeatFutureToleranceMs) {
        // NTP 점프·센서 타임스탬프 오류 — 기록하면 last_heartbeat 가 미래로 오염돼
        // 이후 모든 정상 heartbeat 가 역행으로 무시된다(영구 FAIL_CLOSED 래치,
        // 감사 #15). 거부하고 사유를 남긴다.
        return HeartbeatVerdict::kImplausibleFuture;
    }
    if (has_heartbeat_ && observed_at_utc_ms <= last_heartbeat_utc_ms_) {
        // 역행·중복 heartbeat — 과거 heartbeat로 상태를 되살릴 수 없다.
        return HeartbeatVerdict::kStaleIgnored;
    }
    has_heartbeat_ = true;
    last_heartbeat_utc_ms_ = observed_at_utc_ms;
    return HeartbeatVerdict::kRecorded;
}

void FlightSupervisor::ResetHeartbeatState() {
    has_heartbeat_ = false;
    last_heartbeat_utc_ms_ = 0;
}

SupervisorState FlightSupervisor::StateAt(UtcMillis now_utc_ms) const {
    if (!has_heartbeat_) {
        // 증거 없음 = 정상 아님. 부팅 직후 기본값이 fail-closed인 이유다.
        return SupervisorState::kFailClosed;
    }
    if (now_utc_ms < 0 || now_utc_ms > kMaxUtcMs) {
        // 도메인 밖 기준 시각 — 경과시간을 신뢰할 수 없다(극단값에서 뺄셈이
        // 오버플로해 fail-open 으로 뒤집히던 경로도 함께 차단, 감사 #53).
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

const char* ToString(HeartbeatVerdict verdict) {
    switch (verdict) {
    case HeartbeatVerdict::kRecorded:
        return "RECORDED";
    case HeartbeatVerdict::kStaleIgnored:
        return "STALE_IGNORED";
    case HeartbeatVerdict::kImplausibleFuture:
        return "IMPLAUSIBLE_FUTURE";
    case HeartbeatVerdict::kOutOfDomain:
        return "OUT_OF_DOMAIN";
    }
    return "UNKNOWN";
}

} // namespace ksi::control_plane

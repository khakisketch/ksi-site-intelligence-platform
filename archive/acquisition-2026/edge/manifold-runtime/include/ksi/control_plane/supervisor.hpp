// KSI Edge native control plane — heartbeat + fail-closed 상태전이 (Stage C-3).
//
// 이 헤더가 강제하는 제품 불변식:
//   INV-012 서버통신 단절 중에도 "유효 계약 + 안전조건"이 유지될 때만 임무를 계속한다.
//           단절 자체가 즉시 중단 사유는 아니지만(Core는 비행 중 필수 경로가 아니다),
//           Edge 내부 heartbeat 상실은 다르다 — 자기 자신의 인지·판단 루프가 살아있다는
//           증거가 끊긴 것이므로 새로운 조사 행동을 시작하지 않는다.
//   INV-001 저수준 비행 안전과 최종 RTH 권한은 DJI Flight Controller가 갖는다. 이
//           Supervisor는 "KSI가 새 행동을 요청해도 되는가"만 판단한다 — 기체를
//           직접 멈추거나 되돌리지 않는다.
//
// fail-closed 원칙: 상태가 불확실하면 항상 더 보수적인 쪽으로 간다. 부팅 직후는
// 아직 아무 증거가 없으므로 kFailClosed 에서 시작하며, 명시적으로 건강함이 관측될
// 때만 kNominal 로 올라간다("증거 없음"을 "정상"으로 해석하지 않는다).

#ifndef KSI_CONTROL_PLANE_SUPERVISOR_HPP
#define KSI_CONTROL_PLANE_SUPERVISOR_HPP

#include <cstdint>

#include "ksi/control_plane/command.hpp"

namespace ksi::control_plane {

/// Edge 제어 평면의 안전 상태.
enum class SupervisorState {
    kFailClosed, ///< 새 조사 행동 금지(부팅 직후 기본값, heartbeat 상실 시 복귀)
    kNominal,    ///< 계약·heartbeat 정상 — 승인된 범위에서 조사 행동 가능
    kDegraded,   ///< heartbeat 지연 경고 구간 — 진행 중 행동은 유지하되 신규 시작 금지
};

const char* ToString(SupervisorState state);

/// heartbeat 기록 판정 — 거부 사유가 typed 로 남아야 현장에서 진단 가능하다
/// (감사 #15: 조용한 무시/오염은 원인이 상태값에 드러나지 않아 오진단된다).
enum class HeartbeatVerdict {
    kRecorded,          ///< 정상 기록
    kRecordedClamped,   ///< 허용창 안 미래 시각 — now 로 클램프해 기록(재검토 C-1)
    kStaleIgnored,      ///< 역행·중복 — 최신 시각을 되돌리지 못한다
    kImplausibleFuture, ///< now 대비 허용창 초과 미래 시각 — 기록 거부(래치 방지)
    kOutOfDomain,       ///< 시각 도메인([0, kMaxUtcMs]) 밖 — 판정 불가 거부
};

const char* ToString(HeartbeatVerdict verdict);

/// 미래 heartbeat 허용창(ms) — 센서 타임스탬프의 미세한 선행은 흡수하되, NTP 점프
/// 급 미래 시각이 last_heartbeat 를 오염시켜 이후 모든 정상 heartbeat 가
/// kStaleIgnored 로 무시되는 영구 FAIL_CLOSED 래치(감사 #15)를 차단한다.
inline constexpr std::int64_t kHeartbeatFutureToleranceMs = 1'000;

/// heartbeat 관측과 시간 경과만으로 안전 상태를 결정하는 결정적 상태기.
///
/// 결정적(deterministic)이라는 점이 중요하다 — 내부에서 시계를 읽지 않고 호출자가
/// 넘긴 now 만 사용하므로, replay·HIL에서 동일 입력이 항상 동일 상태를 만든다
/// (P0-6 재현성 규약을 C++ 쪽에도 동일 적용).
class FlightSupervisor {
public:
    /// @param degrade_after_ms  마지막 heartbeat 후 이 시간이 지나면 kDegraded
    /// @param fail_closed_after_ms  이 시간이 지나면 kFailClosed (> degrade_after_ms)
    FlightSupervisor(std::int64_t degrade_after_ms, std::int64_t fail_closed_after_ms);

    /// heartbeat 1건을 기록 시도한다. 결과는 typed 로 반환된다(조용한 무시 금지).
    ///
    /// now 를 함께 받는 이유(감사 #15): 미래 시각 heartbeat 를 판별할 기준이
    /// 필요하다 — 기준 없이 기록하면 오염된 last_heartbeat 가 이후 모든 정상
    /// heartbeat 를 역행으로 무시하게 만들어 임무 내내 FAIL_CLOSED 에 갇힌다.
    /// 내부에서 시계를 읽지 않는 결정성 규약은 유지된다(호출자가 now 를 소유).
    HeartbeatVerdict RecordHeartbeat(UtcMillis observed_at_utc_ms, UtcMillis now_utc_ms);

    /// heartbeat 상태를 부팅 직후로 되돌린다(→ kFailClosed).
    ///
    /// '한 번 오염되면 영구 잠김'의 명시적 탈출구다 — Mission Contract 재로드
    /// 시점에 호출한다. 상태를 낮추는 방향만 있으므로(fail-closed 로 복귀)
    /// 이 리셋 자체가 안전 우회가 되지는 않는다.
    void ResetHeartbeatState();

    /// 현재 시각 기준 상태를 계산한다. heartbeat가 한 번도 없으면 항상 kFailClosed.
    SupervisorState StateAt(UtcMillis now_utc_ms) const;

    /// 새 조사 행동을 시작해도 되는지 — kNominal 에서만 참이다.
    ///
    /// kDegraded 에서 거짓인 것이 의도다: "진행 중 행동 유지"와 "신규 행동 시작"은
    /// 다른 판단이며, 후자는 더 강한 증거를 요구한다.
    bool MayStartNewAction(UtcMillis now_utc_ms) const;

    /// 명령 인가 검증(TTL·digest)과 안전 상태를 **모두** 통과해야 승인한다.
    ///
    /// 두 게이트는 AND 로 결합된다 — 유효한 계약에 귀속된 명령이라도 Edge가
    /// fail-closed 라면 거부하고, Edge가 정상이라도 만료·미인가 명령은 거부한다.
    /// 반환이 kAccepted 가 아니면 호출자는 어떤 행동도 개시하지 않는다.
    CommandVerdict Authorize(const ActionIntent& intent,
                             const std::string& active_digest,
                             UtcMillis now_utc_ms) const;

    bool has_heartbeat() const { return has_heartbeat_; }
    UtcMillis last_heartbeat_utc_ms() const { return last_heartbeat_utc_ms_; }

private:
    std::int64_t degrade_after_ms_;
    std::int64_t fail_closed_after_ms_;
    bool has_heartbeat_ = false;
    UtcMillis last_heartbeat_utc_ms_ = 0;
};

} // namespace ksi::control_plane

#endif // KSI_CONTROL_PLANE_SUPERVISOR_HPP

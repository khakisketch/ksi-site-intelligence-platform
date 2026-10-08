// REQ-ACQ-102 — 서명된 Mission/Capture Policy 안의 국소 촬영 보충 판정.
//
// 이 계층은 PSDK 명령을 호출하지 않는다. 품질 gap이 있어도 정책 서명, 활성
// Mission Contract 결합, 시도/시간/배터리/짐벌/사전승인 관측점 상한을 모두
// 통과해야만 adapter가 실행을 검토할 수 있는 kRecoveryAuthorized를 반환한다.

#ifndef KSI_EDGE_CAPTURE_QUALITY_POLICY_HPP
#define KSI_EDGE_CAPTURE_QUALITY_POLICY_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace ksi::edge {

enum class CaptureRecoveryAction {
    kRecaptureSamePose,
    kGimbalAdjust,
    kSelectPreauthorizedViewpoint,
};

enum class CaptureRecoveryVerdict {
    kAccepted,
    kPolicyNotVerified,
    kMissionContractNotVerified,
    kPolicyBindingMismatch,
    kInvalidMeasurement,
    kQualityGapNoRecoveryRequested,
    kActionNotAllowed,
    kAttemptLimitExceeded,
    kExtraTimeLimitExceeded,
    kBatteryReserveInsufficient,
    kGimbalAdjustmentExceeded,
    kViewpointNotPreauthorized,
    kRecoveryAuthorized,
};

const char* ToString(CaptureRecoveryVerdict verdict);

struct CapturePolicy {
    bool signature_verified = false;
    std::string policy_id;
    std::uint32_t max_attempts_per_target = 0;
    std::int64_t max_extra_time_ms = 0;
    double minimum_battery_reserve_percent = 100.0;
    double maximum_gsd_cm_per_px = 0.0;
    double minimum_overlap_ratio = 1.0;
    double maximum_blur_score = 0.0;
    double maximum_occlusion_ratio = 0.0;
    double maximum_gimbal_adjustment_deg = 0.0;
    std::vector<CaptureRecoveryAction> allowed_actions;
    std::vector<std::string> preauthorized_viewpoint_ids;
};

struct CaptureQualityObservation {
    double blur_score = 0.0;
    bool exposure_ok = false;
    double gsd_cm_per_px = 0.0;
    double overlap_ratio = 0.0;
    double occlusion_ratio = 0.0;
};

struct CaptureRecoveryRequest {
    bool active_mission_contract_verified = false;
    std::string mission_capture_policy_id;
    bool recovery_requested = false;
    CaptureRecoveryAction action = CaptureRecoveryAction::kRecaptureSamePose;
    std::uint32_t next_attempt = 0;
    std::int64_t projected_extra_time_ms = 0;
    double current_battery_percent = 0.0;
    double gimbal_adjustment_deg = 0.0;
    std::string viewpoint_id;
};

CaptureRecoveryVerdict AuthorizeCaptureRecovery(
    const CapturePolicy& policy,
    const CaptureQualityObservation& observation,
    const CaptureRecoveryRequest& request);

}  // namespace ksi::edge

#endif  // KSI_EDGE_CAPTURE_QUALITY_POLICY_HPP

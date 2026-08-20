#include "ksi/edge/capture_quality_policy.hpp"

#include <algorithm>
#include <cmath>

namespace ksi::edge {

namespace {

bool IsFinite(double value) { return std::isfinite(value); }

bool Contains(const std::vector<CaptureRecoveryAction>& values,
              CaptureRecoveryAction expected) {
    return std::find(values.begin(), values.end(), expected) != values.end();
}

bool Contains(const std::vector<std::string>& values, const std::string& expected) {
    return std::find(values.begin(), values.end(), expected) != values.end();
}

bool MeasurementIsValid(const CapturePolicy& policy,
                        const CaptureQualityObservation& observation,
                        const CaptureRecoveryRequest& request) {
    return !policy.policy_id.empty() && policy.max_extra_time_ms >= 0 &&
           IsFinite(policy.minimum_battery_reserve_percent) &&
           policy.minimum_battery_reserve_percent >= 0.0 &&
           policy.minimum_battery_reserve_percent <= 100.0 &&
           IsFinite(policy.maximum_gsd_cm_per_px) && policy.maximum_gsd_cm_per_px > 0.0 &&
           IsFinite(policy.minimum_overlap_ratio) && policy.minimum_overlap_ratio >= 0.0 &&
           policy.minimum_overlap_ratio <= 1.0 && IsFinite(policy.maximum_blur_score) &&
           policy.maximum_blur_score >= 0.0 && IsFinite(policy.maximum_occlusion_ratio) &&
           policy.maximum_occlusion_ratio >= 0.0 && policy.maximum_occlusion_ratio <= 1.0 &&
           IsFinite(policy.maximum_gimbal_adjustment_deg) &&
           policy.maximum_gimbal_adjustment_deg >= 0.0 && IsFinite(observation.blur_score) &&
           observation.blur_score >= 0.0 && IsFinite(observation.gsd_cm_per_px) &&
           observation.gsd_cm_per_px > 0.0 && IsFinite(observation.overlap_ratio) &&
           observation.overlap_ratio >= 0.0 && observation.overlap_ratio <= 1.0 &&
           IsFinite(observation.occlusion_ratio) && observation.occlusion_ratio >= 0.0 &&
           observation.occlusion_ratio <= 1.0 && request.projected_extra_time_ms >= 0 &&
           IsFinite(request.current_battery_percent) && request.current_battery_percent >= 0.0 &&
           request.current_battery_percent <= 100.0 && IsFinite(request.gimbal_adjustment_deg) &&
           request.gimbal_adjustment_deg >= 0.0;
}

bool HasQualityGap(const CapturePolicy& policy,
                   const CaptureQualityObservation& observation) {
    return observation.blur_score > policy.maximum_blur_score || !observation.exposure_ok ||
           observation.gsd_cm_per_px > policy.maximum_gsd_cm_per_px ||
           observation.overlap_ratio < policy.minimum_overlap_ratio ||
           observation.occlusion_ratio > policy.maximum_occlusion_ratio;
}

}  // namespace

const char* ToString(CaptureRecoveryVerdict verdict) {
    switch (verdict) {
        case CaptureRecoveryVerdict::kAccepted:
            return "ACCEPTED";
        case CaptureRecoveryVerdict::kPolicyNotVerified:
            return "POLICY_NOT_VERIFIED";
        case CaptureRecoveryVerdict::kMissionContractNotVerified:
            return "MISSION_CONTRACT_NOT_VERIFIED";
        case CaptureRecoveryVerdict::kPolicyBindingMismatch:
            return "POLICY_BINDING_MISMATCH";
        case CaptureRecoveryVerdict::kInvalidMeasurement:
            return "INVALID_MEASUREMENT";
        case CaptureRecoveryVerdict::kQualityGapNoRecoveryRequested:
            return "QUALITY_GAP_NO_RECOVERY_REQUESTED";
        case CaptureRecoveryVerdict::kActionNotAllowed:
            return "ACTION_NOT_ALLOWED";
        case CaptureRecoveryVerdict::kAttemptLimitExceeded:
            return "ATTEMPT_LIMIT_EXCEEDED";
        case CaptureRecoveryVerdict::kExtraTimeLimitExceeded:
            return "EXTRA_TIME_LIMIT_EXCEEDED";
        case CaptureRecoveryVerdict::kBatteryReserveInsufficient:
            return "BATTERY_RESERVE_INSUFFICIENT";
        case CaptureRecoveryVerdict::kGimbalAdjustmentExceeded:
            return "GIMBAL_ADJUSTMENT_EXCEEDED";
        case CaptureRecoveryVerdict::kViewpointNotPreauthorized:
            return "VIEWPOINT_NOT_PREAUTHORIZED";
        case CaptureRecoveryVerdict::kRecoveryAuthorized:
            return "RECOVERY_AUTHORIZED";
    }
    return "UNKNOWN";
}

CaptureRecoveryVerdict AuthorizeCaptureRecovery(
    const CapturePolicy& policy,
    const CaptureQualityObservation& observation,
    const CaptureRecoveryRequest& request) {
    if (!policy.signature_verified) {
        return CaptureRecoveryVerdict::kPolicyNotVerified;
    }
    if (!request.active_mission_contract_verified) {
        return CaptureRecoveryVerdict::kMissionContractNotVerified;
    }
    if (policy.policy_id != request.mission_capture_policy_id) {
        return CaptureRecoveryVerdict::kPolicyBindingMismatch;
    }
    if (!MeasurementIsValid(policy, observation, request)) {
        return CaptureRecoveryVerdict::kInvalidMeasurement;
    }
    if (!HasQualityGap(policy, observation)) {
        return CaptureRecoveryVerdict::kAccepted;
    }
    if (!request.recovery_requested) {
        return CaptureRecoveryVerdict::kQualityGapNoRecoveryRequested;
    }
    if (!Contains(policy.allowed_actions, request.action)) {
        return CaptureRecoveryVerdict::kActionNotAllowed;
    }
    if (request.next_attempt == 0 || request.next_attempt > policy.max_attempts_per_target) {
        return CaptureRecoveryVerdict::kAttemptLimitExceeded;
    }
    if (request.projected_extra_time_ms > policy.max_extra_time_ms) {
        return CaptureRecoveryVerdict::kExtraTimeLimitExceeded;
    }
    if (request.current_battery_percent < policy.minimum_battery_reserve_percent) {
        return CaptureRecoveryVerdict::kBatteryReserveInsufficient;
    }
    if (request.action == CaptureRecoveryAction::kGimbalAdjust &&
        request.gimbal_adjustment_deg > policy.maximum_gimbal_adjustment_deg) {
        return CaptureRecoveryVerdict::kGimbalAdjustmentExceeded;
    }
    if (request.action == CaptureRecoveryAction::kSelectPreauthorizedViewpoint &&
        !Contains(policy.preauthorized_viewpoint_ids, request.viewpoint_id)) {
        return CaptureRecoveryVerdict::kViewpointNotPreauthorized;
    }
    return CaptureRecoveryVerdict::kRecoveryAuthorized;
}

}  // namespace ksi::edge

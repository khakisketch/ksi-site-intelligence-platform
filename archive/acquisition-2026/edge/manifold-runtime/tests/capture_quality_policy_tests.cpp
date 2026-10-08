#include "ksi/edge/capture_quality_policy.hpp"

#include <cmath>
#include <cstdio>
#include <string>

namespace {

int g_checks = 0;
int g_failures = 0;

void Check(bool condition, const char* message) {
    ++g_checks;
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "[FAIL] %s\n", message);
    }
}

ksi::edge::CapturePolicy Policy() {
    return {
        true,
        "capture-policy-1",
        2,
        60000,
        25.0,
        2.0,
        0.75,
        0.20,
        0.30,
        15.0,
        {ksi::edge::CaptureRecoveryAction::kRecaptureSamePose,
         ksi::edge::CaptureRecoveryAction::kGimbalAdjust,
         ksi::edge::CaptureRecoveryAction::kSelectPreauthorizedViewpoint},
        {"viewpoint-2"},
    };
}

ksi::edge::CaptureQualityObservation Gap() {
    return {0.35, true, 1.5, 0.80, 0.10};
}

ksi::edge::CaptureRecoveryRequest Request() {
    return {true,
            "capture-policy-1",
            true,
            ksi::edge::CaptureRecoveryAction::kRecaptureSamePose,
            1,
            10000,
            60.0,
            0.0,
            ""};
}

void TestFailClosedBoundary() {
    auto policy = Policy();
    auto request = Request();
    policy.signature_verified = false;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kPolicyNotVerified,
          "unsigned policy must fail closed");
    policy = Policy();
    request.active_mission_contract_verified = false;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kMissionContractNotVerified,
          "unverified mission contract must fail closed");
    request = Request();
    request.mission_capture_policy_id = "different-policy";
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kPolicyBindingMismatch,
          "mission must bind the exact capture policy");
}

void TestQualityAndBounds() {
    auto policy = Policy();
    auto request = Request();
    const ksi::edge::CaptureQualityObservation accepted{0.10, true, 1.8, 0.80, 0.10};
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, accepted, request) ==
              ksi::edge::CaptureRecoveryVerdict::kAccepted,
          "adequate capture must not trigger extra flight action");
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kRecoveryAuthorized,
          "bounded same-pose recapture should be authorized");

    request.next_attempt = 3;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kAttemptLimitExceeded,
          "attempt budget is a hard bound");
    request = Request();
    request.projected_extra_time_ms = 60001;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kExtraTimeLimitExceeded,
          "extra time budget is a hard bound");
    request = Request();
    request.current_battery_percent = 24.9;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kBatteryReserveInsufficient,
          "battery reserve is a hard bound");
}

void TestActiveViewBoundsAndMalformedInputs() {
    auto policy = Policy();
    auto request = Request();
    request.action = ksi::edge::CaptureRecoveryAction::kGimbalAdjust;
    request.gimbal_adjustment_deg = 15.1;
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kGimbalAdjustmentExceeded,
          "gimbal adjustment beyond signed bound must be rejected");
    request = Request();
    request.action = ksi::edge::CaptureRecoveryAction::kSelectPreauthorizedViewpoint;
    request.viewpoint_id = "unknown";
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kViewpointNotPreauthorized,
          "dynamic coordinate generation must not pass the preauthorized viewpoint gate");
    request.viewpoint_id = "viewpoint-2";
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, Gap(), request) ==
              ksi::edge::CaptureRecoveryVerdict::kRecoveryAuthorized,
          "preauthorized viewpoint can pass all bounds");

    auto malformed = Gap();
    malformed.blur_score = std::nan("");
    Check(ksi::edge::AuthorizeCaptureRecovery(policy, malformed, request) ==
              ksi::edge::CaptureRecoveryVerdict::kInvalidMeasurement,
          "NaN measurements must fail closed");
}

}  // namespace

int main() {
    TestFailClosedBoundary();
    TestQualityAndBounds();
    TestActiveViewBoundsAndMalformedInputs();
    if (g_failures == 0) {
        std::printf("capture quality policy tests: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "capture quality policy tests: %d/%d checks failed\n", g_failures,
                 g_checks);
    return 1;
}

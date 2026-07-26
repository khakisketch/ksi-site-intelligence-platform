// Control plane 계약 테스트 (Stage C-3).
//
// green≠작동 초점: "빌드된다"가 아니라 **거부되어야 할 명령이 실제로 거부되는지**를
// 확인한다. TTL 만료·미인가·digest 불일치·미래 발행·heartbeat 상실 각각이 독립적으로
// 거부 사유가 되는지, 그리고 fail-closed 기본값이 실제로 fail-closed인지 검증한다.
//
// 외부 프레임워크 없이 단언 + 종료코드로만 동작한다(CMakeLists.txt 주석 참고).

#include <cstdio>
#include <string>

#include "ksi/control_plane/command.hpp"
#include "ksi/control_plane/supervisor.hpp"

namespace {

int g_failures = 0;
int g_checks = 0;

void Check(bool condition, const char* what) {
    ++g_checks;
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

using ksi::control_plane::ActionIntent;
using ksi::control_plane::ActionIntentKind;
using ksi::control_plane::CommandVerdict;
using ksi::control_plane::FlightSupervisor;
using ksi::control_plane::SupervisorState;
using ksi::control_plane::VerifyActionIntent;

const std::string kActiveDigest = "sha256:aaaa";
constexpr std::int64_t kIssuedAt = 1'000'000;
constexpr std::int64_t kTtl = 5'000;

ActionIntent ValidIntent() {
    ActionIntent intent;
    intent.command_id = "cmd-1";
    intent.kind = ActionIntentKind::kGotoViewpoint;
    intent.authorization_digest = kActiveDigest;
    intent.issued_at_utc_ms = kIssuedAt;
    intent.ttl_ms = kTtl;
    return intent;
}

void TestValidCommandAccepted() {
    const auto verdict = VerifyActionIntent(ValidIntent(), kActiveDigest, kIssuedAt + 1'000);
    Check(verdict == CommandVerdict::kAccepted, "유효 명령은 수락되어야 한다");
}

void TestExpiredCommandRejected() {
    // TTL 경계는 배타적 — 정확히 issued_at + ttl 시점에 이미 만료다.
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest, kIssuedAt + kTtl)
              == CommandVerdict::kExpired,
          "TTL 경계 시점 명령은 만료로 거부");
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest, kIssuedAt + kTtl + 1)
              == CommandVerdict::kExpired,
          "TTL 초과 명령은 만료로 거부");
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest, kIssuedAt + kTtl - 1)
              == CommandVerdict::kAccepted,
          "TTL 직전 명령은 여전히 유효");
}

void TestFutureCommandRejected() {
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest, kIssuedAt - 1)
              == CommandVerdict::kNotYetValid,
          "미래에 발행된 명령은 거부(시계 이상·위조 방어)");
}

void TestMissingAuthorizationRejected() {
    ActionIntent intent = ValidIntent();
    intent.authorization_digest.clear();
    Check(VerifyActionIntent(intent, kActiveDigest, kIssuedAt) == CommandVerdict::kMissingAuthorization,
          "digest 없는 명령은 거부");
}

void TestAuthorizationMismatchRejected() {
    ActionIntent intent = ValidIntent();
    intent.authorization_digest = "sha256:bbbb";
    Check(VerifyActionIntent(intent, kActiveDigest, kIssuedAt) == CommandVerdict::kAuthorizationMismatch,
          "다른 계약에 귀속된 명령은 거부");
}

void TestNoActiveContractRejectsEverything() {
    Check(VerifyActionIntent(ValidIntent(), "", kIssuedAt) == CommandVerdict::kAuthorizationMismatch,
          "활성 계약이 없으면 어떤 명령도 인가되지 않는다");
}

void TestMalformedCommandRejected() {
    ActionIntent no_id = ValidIntent();
    no_id.command_id.clear();
    Check(VerifyActionIntent(no_id, kActiveDigest, kIssuedAt) == CommandVerdict::kMalformed,
          "command_id 없는 명령은 거부");

    ActionIntent zero_ttl = ValidIntent();
    zero_ttl.ttl_ms = 0;
    Check(VerifyActionIntent(zero_ttl, kActiveDigest, kIssuedAt) == CommandVerdict::kMalformed,
          "TTL 0 명령은 거부");

    ActionIntent negative_ttl = ValidIntent();
    negative_ttl.ttl_ms = -1;
    Check(VerifyActionIntent(negative_ttl, kActiveDigest, kIssuedAt) == CommandVerdict::kMalformed,
          "음수 TTL 명령은 거부");
}

void TestSupervisorStartsFailClosed() {
    const FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.StateAt(0) == SupervisorState::kFailClosed,
          "heartbeat 없는 부팅 직후는 fail-closed");
    Check(!supervisor.MayStartNewAction(0), "fail-closed 상태에서 새 행동 금지");
    Check(!supervisor.has_heartbeat(), "초기에는 heartbeat 기록이 없다");
}

void TestSupervisorHeartbeatTransitions() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000);

    Check(supervisor.StateAt(10'000) == SupervisorState::kNominal, "직후는 nominal");
    Check(supervisor.StateAt(11'999) == SupervisorState::kNominal, "degrade 임계 직전은 nominal");
    Check(supervisor.StateAt(12'000) == SupervisorState::kDegraded, "degrade 임계에서 degraded");
    Check(supervisor.StateAt(14'999) == SupervisorState::kDegraded, "fail 임계 직전은 degraded");
    Check(supervisor.StateAt(15'000) == SupervisorState::kFailClosed, "fail 임계에서 fail-closed");
    Check(supervisor.StateAt(100'000) == SupervisorState::kFailClosed, "오래 지나면 fail-closed 유지");
}

void TestDegradedForbidsNewActions() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000);
    Check(supervisor.MayStartNewAction(11'000), "nominal에서는 새 행동 허용");
    Check(!supervisor.MayStartNewAction(12'000),
          "degraded에서는 신규 행동 금지(진행 중 행동 유지와는 다른 판단)");
    Check(!supervisor.MayStartNewAction(15'000), "fail-closed에서는 당연히 금지");
}

void TestBackwardHeartbeatIgnored() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000);
    supervisor.RecordHeartbeat(9'000); // 과거 heartbeat — 무시되어야 한다
    Check(supervisor.last_heartbeat_utc_ms() == 10'000,
          "역행 heartbeat는 최신 시각을 되돌리지 못한다");
    Check(supervisor.StateAt(15'000) == SupervisorState::kFailClosed,
          "역행 heartbeat로 fail-closed를 회피할 수 없다");
}

void TestClockRegressionIsFailClosed() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000);
    Check(supervisor.StateAt(9'000) == SupervisorState::kFailClosed,
          "시계 역행 시 경과시간을 신뢰할 수 없으므로 fail-closed");
}

void TestAuthorizeCombinesBothGates() {
    FlightSupervisor supervisor(2'000, 5'000);

    // 게이트 1: heartbeat 없음 → 명령이 유효해도 거부
    ActionIntent intent = ValidIntent();
    intent.issued_at_utc_ms = 10'000;
    Check(supervisor.Authorize(intent, kActiveDigest, 10'500) == CommandVerdict::kSupervisorNotReady,
          "supervisor 미준비 시 유효 명령도 거부되며 사유가 구분된다");

    // 게이트 2: heartbeat 정상이어도 만료 명령은 거부
    supervisor.RecordHeartbeat(10'000);
    Check(supervisor.Authorize(intent, kActiveDigest, 10'500) == CommandVerdict::kAccepted,
          "두 게이트 모두 통과하면 수락");
    Check(supervisor.Authorize(intent, kActiveDigest, 10'000 + kTtl + 1) == CommandVerdict::kExpired,
          "supervisor가 정상이어도 만료 명령은 거부");

    // 게이트 2: digest 불일치도 거부
    ActionIntent wrong_digest = intent;
    wrong_digest.authorization_digest = "sha256:cccc";
    Check(supervisor.Authorize(wrong_digest, kActiveDigest, 10'500)
              == CommandVerdict::kAuthorizationMismatch,
          "supervisor가 정상이어도 미인가 명령은 거부");
}

void TestVerdictStringsAreDistinct() {
    // 로그·증거 번들에서 사유를 구분할 수 있어야 한다.
    Check(std::string(ToString(CommandVerdict::kAccepted)) == "ACCEPTED", "verdict 문자열");
    Check(std::string(ToString(CommandVerdict::kSupervisorNotReady)) == "SUPERVISOR_NOT_READY",
          "supervisor 사유가 인가 사유와 다른 문자열");
    Check(std::string(ToString(SupervisorState::kFailClosed)) == "FAIL_CLOSED", "state 문자열");
}

} // namespace

int main() {
    TestValidCommandAccepted();
    TestExpiredCommandRejected();
    TestFutureCommandRejected();
    TestMissingAuthorizationRejected();
    TestAuthorizationMismatchRejected();
    TestNoActiveContractRejectsEverything();
    TestMalformedCommandRejected();
    TestSupervisorStartsFailClosed();
    TestSupervisorHeartbeatTransitions();
    TestDegradedForbidsNewActions();
    TestBackwardHeartbeatIgnored();
    TestClockRegressionIsFailClosed();
    TestAuthorizeCombinesBothGates();
    TestVerdictStringsAreDistinct();

    std::printf("control plane 계약 테스트: %d개 단언 중 %d개 실패\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

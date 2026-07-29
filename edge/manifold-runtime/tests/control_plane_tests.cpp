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
    intent.schema_version = "1.0";
    intent.command_id = "cmd-1";
    intent.kind = ActionIntentKind::kGotoViewpoint;
    intent.authorization_digest = kActiveDigest;
    intent.issued_at_utc_ms = kIssuedAt;
    intent.ttl_ms = kTtl;
    intent.target_viewpoint_id = "vp-1";
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
    supervisor.RecordHeartbeat(10'000, 10'000);

    Check(supervisor.StateAt(10'000) == SupervisorState::kNominal, "직후는 nominal");
    Check(supervisor.StateAt(11'999) == SupervisorState::kNominal, "degrade 임계 직전은 nominal");
    Check(supervisor.StateAt(12'000) == SupervisorState::kDegraded, "degrade 임계에서 degraded");
    Check(supervisor.StateAt(14'999) == SupervisorState::kDegraded, "fail 임계 직전은 degraded");
    Check(supervisor.StateAt(15'000) == SupervisorState::kFailClosed, "fail 임계에서 fail-closed");
    Check(supervisor.StateAt(100'000) == SupervisorState::kFailClosed, "오래 지나면 fail-closed 유지");
}

void TestDegradedForbidsNewActions() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000, 10'000);
    Check(supervisor.MayStartNewAction(11'000), "nominal에서는 새 행동 허용");
    Check(!supervisor.MayStartNewAction(12'000),
          "degraded에서는 신규 행동 금지(진행 중 행동 유지와는 다른 판단)");
    Check(!supervisor.MayStartNewAction(15'000), "fail-closed에서는 당연히 금지");
}

void TestBackwardHeartbeatIgnored() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000, 10'000);
    supervisor.RecordHeartbeat(9'000, 10'000); // 과거 heartbeat — 무시되어야 한다
    Check(supervisor.last_heartbeat_utc_ms() == 10'000,
          "역행 heartbeat는 최신 시각을 되돌리지 못한다");
    Check(supervisor.StateAt(15'000) == SupervisorState::kFailClosed,
          "역행 heartbeat로 fail-closed를 회피할 수 없다");
}

void TestClockRegressionIsFailClosed() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000, 10'000);
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
    supervisor.RecordHeartbeat(10'000, 10'000);
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

void TestSchemaVersionEnforced() {
    // 감사 #16: 버전 없는/미지 버전 명령은 v1 규칙으로 해석되지 않는다.
    ActionIntent unset = ValidIntent();
    unset.schema_version.clear();
    Check(VerifyActionIntent(unset, kActiveDigest, kIssuedAt + 1'000) == CommandVerdict::kMalformed,
          "schema_version 미설정 명령은 거부(fail-closed 기본값)");
    ActionIntent v2 = ValidIntent();
    v2.schema_version = "2.0";
    Check(VerifyActionIntent(v2, kActiveDigest, kIssuedAt + 1'000) == CommandVerdict::kMalformed,
          "미지 schema_version 명령은 거부");
}

void TestTtlUpperBoundEnforced() {
    // 감사 #17: 무기한 유효 명령(replay 가능한 인가 토큰) 금지.
    ActionIntent over = ValidIntent();
    over.ttl_ms = ksi::control_plane::kMaxTtlMs + 1;
    Check(VerifyActionIntent(over, kActiveDigest, kIssuedAt + 1'000) == CommandVerdict::kMalformed,
          "TTL 상한 초과 명령은 거부");
    ActionIntent at_max = ValidIntent();
    at_max.ttl_ms = ksi::control_plane::kMaxTtlMs;
    Check(VerifyActionIntent(at_max, kActiveDigest, kIssuedAt + 1'000) == CommandVerdict::kAccepted,
          "정확히 상한인 TTL 은 유효(경계 포함)");
}

void TestGotoRequiresTarget() {
    // 감사 #18: 목적지 없는 이동 의도는 계약이 끊는다.
    ActionIntent no_target = ValidIntent();
    no_target.target_viewpoint_id.clear();
    Check(VerifyActionIntent(no_target, kActiveDigest, kIssuedAt + 1'000)
              == CommandVerdict::kMalformed,
          "GOTO_VIEWPOINT 에 target 이 없으면 거부");
    ActionIntent hold = ValidIntent();
    hold.kind = ActionIntentKind::kHold;
    hold.target_viewpoint_id.clear();
    Check(VerifyActionIntent(hold, kActiveDigest, kIssuedAt + 1'000) == CommandVerdict::kAccepted,
          "HOLD 는 target 없이 유효(kind 별 조건부 필수)");
}

void TestTimeDomainGuardsPreventOverflow() {
    // 감사 #14: 도메인 선검사 없던 구현은 INT64_MIN 급 issued_at 에서 뺄셈
    // signed overflow(UB)로 kAccepted 가 나올 수 있었다 — fail-open 의 재현 입력.
    ActionIntent extreme = ValidIntent();
    extreme.issued_at_utc_ms = -9'000'000'000'000'000'000;
    Check(VerifyActionIntent(extreme, kActiveDigest, kIssuedAt + 1'000)
              == CommandVerdict::kMalformed,
          "int64 극단 issued_at 은 오버플로 없이 거부");
    ActionIntent negative = ValidIntent();
    negative.issued_at_utc_ms = -1;
    Check(VerifyActionIntent(negative, kActiveDigest, kIssuedAt + 1'000)
              == CommandVerdict::kMalformed,
          "음수 issued_at 거부");
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest, -5) == CommandVerdict::kMalformed,
          "도메인 밖 now 는 판정 불가로 거부");
    Check(VerifyActionIntent(ValidIntent(), kActiveDigest,
                             ksi::control_plane::kMaxUtcMs + 1) == CommandVerdict::kMalformed,
          "도메인 상한 초과 now 도 거부");
}

void TestFutureHeartbeatDoesNotLatch() {
    // 감사 #15: 미래 heartbeat 1건이 last 를 오염시키면 이후 모든 정상 heartbeat 가
    // 역행으로 무시돼 임무 내내 FAIL_CLOSED 에 갇힌다 — 기록 자체를 거부해야 한다.
    using ksi::control_plane::HeartbeatVerdict;
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(500'000, 10'000) == HeartbeatVerdict::kImplausibleFuture,
          "허용창 초과 미래 heartbeat 는 typed 거부");
    Check(!supervisor.has_heartbeat(), "거부된 heartbeat 는 상태를 오염시키지 않는다");
    Check(supervisor.RecordHeartbeat(10'000, 10'000) == HeartbeatVerdict::kRecorded,
          "이후 정상 heartbeat 가 그대로 기록된다(래치 없음)");
    Check(supervisor.StateAt(10'500) == SupervisorState::kNominal,
          "정상 heartbeat 후 nominal 도달 가능");
    Check(supervisor.RecordHeartbeat(-1, 10'000) == HeartbeatVerdict::kOutOfDomain,
          "도메인 밖 heartbeat 시각은 거부");
    Check(supervisor.RecordHeartbeat(9'000, 10'000) == HeartbeatVerdict::kStaleIgnored,
          "역행 heartbeat 는 typed 로 무시 사유가 남는다");
}

void TestHeartbeatResetReturnsToFailClosed() {
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000, 10'000);
    Check(supervisor.StateAt(10'500) == SupervisorState::kNominal, "리셋 전 nominal");
    supervisor.ResetHeartbeatState();
    Check(supervisor.StateAt(10'500) == SupervisorState::kFailClosed,
          "리셋은 부팅 직후(fail-closed)로만 되돌린다 — 상태를 올리는 우회가 아니다");
    Check(!supervisor.has_heartbeat(), "리셋 후 heartbeat 증거 없음");
}

void TestStateAtOutOfDomainIsFailClosed() {
    // 감사 #53: 극단 now 에서 뺄셈 오버플로로 fail-open 되던 경로.
    FlightSupervisor supervisor(2'000, 5'000);
    supervisor.RecordHeartbeat(10'000, 10'000);
    Check(supervisor.StateAt(-9'000'000'000'000'000'000) == SupervisorState::kFailClosed,
          "도메인 밖 now 는 fail-closed");
    Check(supervisor.StateAt(ksi::control_plane::kMaxUtcMs + 1) == SupervisorState::kFailClosed,
          "도메인 상한 초과 now 도 fail-closed");
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
    TestSchemaVersionEnforced();
    TestTtlUpperBoundEnforced();
    TestGotoRequiresTarget();
    TestTimeDomainGuardsPreventOverflow();
    TestFutureHeartbeatDoesNotLatch();
    TestHeartbeatResetReturnsToFailClosed();
    TestStateAtOutOfDomainIsFailClosed();
    TestVerdictStringsAreDistinct();

    std::printf("control plane 계약 테스트: %d개 단언 중 %d개 실패\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

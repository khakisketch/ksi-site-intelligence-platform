// Control plane 계약 테스트 (Stage C-3).
//
// green≠작동 초점: "빌드된다"가 아니라 **거부되어야 할 명령이 실제로 거부되는지**를
// 확인한다. TTL 만료·미인가·digest 불일치·미래 발행·heartbeat 상실 각각이 독립적으로
// 거부 사유가 되는지, 그리고 fail-closed 기본값이 실제로 fail-closed인지 검증한다.
//
// 외부 프레임워크 없이 단언 + 종료코드로만 동작한다(CMakeLists.txt 주석 참고).

#include <cstdint>
#include <cstdio>
#include <stdexcept>
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

    ActionIntent unknown_kind = ValidIntent();
    unknown_kind.kind = static_cast<ActionIntentKind>(99);
    Check(VerifyActionIntent(unknown_kind, kActiveDigest, kIssuedAt) == CommandVerdict::kMalformed,
          "정의되지 않은 고수준 의도 enum 은 거부");
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

void TestInWindowFutureHeartbeatDoesNotSoftLatch() {
    // [자율 재검토 C-1] 허용창 안(<=1000ms) 미래 heartbeat 를 그대로 기록하면
    // StateAt 의 elapsed<0 경로와 결합해 '주기 < skew' 에서 영구 FAIL_CLOSED —
    // 클램프 후에는 NOMINAL 이 유지되어야 한다.
    using ksi::control_plane::HeartbeatVerdict;
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(10'700, 10'000) == HeartbeatVerdict::kRecordedClamped,
          "허용창 안 미래 heartbeat 는 클램프 기록으로 typed 구분된다");
    Check(supervisor.last_heartbeat_utc_ms() == 10'000,
          "클램프 — 미래 성분은 기록되지 않는다");
    Check(supervisor.StateAt(10'000) == SupervisorState::kNominal,
          "기록 직후 같은 now 에서 nominal (수정 전: elapsed<0 → fail-closed)");
    Check(supervisor.RecordHeartbeat(11'200, 10'500) == HeartbeatVerdict::kRecordedClamped,
          "지속 skew 하의 후속 heartbeat 도 클램프 수용");
    Check(supervisor.StateAt(10'999) == SupervisorState::kNominal,
          "주기<skew 시나리오에서 영구 래치 없음 (수정 전: 영구 fail-closed)");
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

void TestStateAtDomainGuardIsLoadBearing() {
    // [mutation 재점검, 2026-08-07] 위 테스트는 **가드가 없어도 통과한다.**
    // last_heartbeat=10'000 에서 now=-9e18 이면 elapsed<0 가드가, now=kMaxUtcMs+1
    // 이면 elapsed>=fail_closed 가 각각 같은 답을 내기 때문이다 — 즉 그 값들로는
    // 도메인 가드의 유무를 구분할 수 없다. 수작업 변이(도메인 가드 제거)가 ctest 를
    // 통과해 이 사각지대가 드러났다.
    //
    // 가드를 실제로 지탱하는 값은 **경과가 작아지는 조합**이다: heartbeat 가 도메인
    // 상한 근처에 있고 now 가 그 바로 뒤면, 가드 없이는 elapsed=1 이라 NOMINAL 로
    // 뒤집힌다(fail-open) — 감사 #53 이 막으려던 바로 그 방향이다.
    FlightSupervisor supervisor(2'000, 5'000);
    const auto kDomainMax = ksi::control_plane::kMaxUtcMs;
    Check(supervisor.RecordHeartbeat(kDomainMax, kDomainMax) ==
              ksi::control_plane::HeartbeatVerdict::kRecorded,
          "도메인 상한 시각의 heartbeat 는 기록된다");
    Check(supervisor.StateAt(kDomainMax + 1) == SupervisorState::kFailClosed,
          "도메인 밖 now 는 경과가 1ms 여도 fail-closed (가드 없으면 NOMINAL 로 뒤집힌다)");
    Check(!supervisor.MayStartNewAction(kDomainMax + 1),
          "그 상태에서 신규 행동을 개시하지 않는다");

    // INT64_MIN 은 가드가 없으면 뺄셈 자체가 signed overflow(UB)다 — 가드가
    // 뺄셈 **전에** 걸러야 한다. 위 테스트의 -9e18 은 last=10'000 과 빼도 넘치지
    // 않아 이 경로를 건드리지 못했다.
    Check(supervisor.StateAt(INT64_MIN) == SupervisorState::kFailClosed,
          "INT64_MIN now 는 뺄셈 전에 걸러진다");
}

void TestDuplicateHeartbeatIsIgnored() {
    // [mutation 재점검, 2026-08-07] 역행 heartbeat 거부는 테스트가 있었지만
    // **같은 시각 재기록**은 없었다 — 경계가 `<=` 인지 `<` 인지를 아무도 고정하지
    // 않아, `<` 로 바꾸는 변이가 ctest 를 통과했다.
    //
    // 같은 시각 재기록을 허용하면 heartbeat 의 증거 가치가 흐려진다: "이 시점에
    // 루프가 살아있다"는 주장이 같은 타임스탬프로 몇 번이든 다시 제출될 수 있고,
    // 그러면 정지한 루프가 마지막 타임스탬프를 반복 전송해 NOMINAL 을 유지할 수 있다.
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(10'000, 10'000) ==
              ksi::control_plane::HeartbeatVerdict::kRecorded,
          "첫 heartbeat 는 기록된다");
    Check(supervisor.RecordHeartbeat(10'000, 10'500) ==
              ksi::control_plane::HeartbeatVerdict::kStaleIgnored,
          "같은 시각 heartbeat 재제출은 무시된다(경계 <=)");
    Check(supervisor.RecordHeartbeat(10'001, 10'500) ==
              ksi::control_plane::HeartbeatVerdict::kRecorded,
          "1ms 라도 전진한 heartbeat 는 기록된다(경계가 과잉 거부는 아니다)");
}

// ── reviewer 재검증(2026-08-07)이 지적한 사각지대 S1~S7 ────────────────────
//
// 1차 변이 실험은 16건 중 15건을 잡았지만, 그건 **내가 고른 16건에 한해서만** 참이었다.
// 독립 재검토가 어떤 단언으로도 판별되지 않는 절 7개를 더 찾아냈고, 실측으로 전부
// 생존이 확인됐다. 그중 S1 이 특히 뼈아프다 — 방금 고친 M15(StateAt 도메인 가드)와
// 같은 클래스·같은 감사번호(#53) 계열인데 RecordHeartbeat 쪽만 그대로 남아 있었다.

void TestRecordHeartbeatNowUpperDomainGuard() {
    // [S1] now 상한 가드가 없으면 now=INT64_MAX 에서
    // `now_utc_ms + kHeartbeatFutureToleranceMs` 가 signed overflow(UB)다.
    // 기존 테스트의 now 는 전부 10'000·10'500·kMaxUtcMs 라 이 경로를 못 건드렸다.
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(10'000, INT64_MAX) ==
              ksi::control_plane::HeartbeatVerdict::kOutOfDomain,
          "도메인 상한 밖 now 는 기록 거부 (가드 없으면 덧셈이 오버플로한다)");
    Check(supervisor.RecordHeartbeat(10'000, ksi::control_plane::kMaxUtcMs + 1) ==
              ksi::control_plane::HeartbeatVerdict::kOutOfDomain,
          "도메인 상한 바로 밖 now 도 거부");
    Check(supervisor.StateAt(10'000) == SupervisorState::kFailClosed,
          "거부된 heartbeat 는 상태를 바꾸지 않는다");
}

void TestObservedAtUpperDomainGuard() {
    // [S6] observed_at 상한 가드가 없으면 도메인 밖 시각이 kOutOfDomain 이 아니라
    // kImplausibleFuture 로 판정된다 — 두 사유는 운영자에게 다른 뜻이다(센서 시각
    // 오류 vs 입력 자체가 계약 밖).
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(ksi::control_plane::kMaxUtcMs + 1, 10'000) ==
              ksi::control_plane::HeartbeatVerdict::kOutOfDomain,
          "도메인 상한 밖 observed_at 은 OUT_OF_DOMAIN (IMPLAUSIBLE_FUTURE 가 아니다)");
}

void TestFirstHeartbeatAtEpochZeroIsRecorded() {
    // [S7] `has_heartbeat_ &&` 가 없으면 last_heartbeat_ 초기값 0 과 비교돼
    // **최초 heartbeat 가 observed_at==0 일 때 무시된다.** 그 상태의 supervisor 는
    // 영원히 FAIL_CLOSED 다(증거를 받아들이지 못한다).
    FlightSupervisor supervisor(2'000, 5'000);
    Check(supervisor.RecordHeartbeat(0, 0) == ksi::control_plane::HeartbeatVerdict::kRecorded,
          "epoch 0 의 최초 heartbeat 도 기록된다");
    Check(supervisor.StateAt(0) == SupervisorState::kNominal,
          "그 heartbeat 로 NOMINAL 이 된다");
}

void TestFutureToleranceBoundaryIsExact() {
    // [S4] 허용창 상수를 넓히는 변이가 통과했다 — 테스트의 delta 가 700(창 안)과
    // 490'000(창 밖)뿐이라 그 사이 어느 값으로 바꿔도 같은 답이 나왔다. 경계
    // 양쪽을 정확히 고정하면 상수 변경이 곧바로 드러난다.
    //
    // 창을 넓히면 far-future 타임스탬프가 kRecordedClamped 로 기록돼 **정지한
    // 루프가 NOMINAL 근거를 얻는다** — heartbeat 의 증거 가치가 무너지는 방향이다.
    const auto kTol = ksi::control_plane::kHeartbeatFutureToleranceMs;
    FlightSupervisor inside(2'000, 5'000);
    Check(inside.RecordHeartbeat(10'000 + kTol, 10'000) ==
              ksi::control_plane::HeartbeatVerdict::kRecordedClamped,
          "허용창 경계 정확히 위는 클램프 기록(포함 경계)");
    FlightSupervisor outside(2'000, 5'000);
    Check(outside.RecordHeartbeat(10'000 + kTol + 1, 10'000) ==
              ksi::control_plane::HeartbeatVerdict::kImplausibleFuture,
          "허용창을 1ms 넘으면 거부 — 상수를 넓히면 이 단언이 깨진다");
}

void TestIssuedAtEqualsNowIsAccepted() {
    // [S2] `issued_at > now` 의 경계. 같은 밀리초에 발행·평가되는 명령은 정상이고
    // 거부되면 안 된다 — 연산자를 >= 로 바꾸는 변이가 통과했다는 것은 그 경계를
    // 아무도 고정하지 않았다는 뜻이다. Python 참조 검증기와 갈려도 못 잡는다.
    ActionIntent intent = ValidIntent();
    Check(VerifyActionIntent(intent, kActiveDigest, kIssuedAt) == CommandVerdict::kAccepted,
          "issued_at == now 인 명령은 수락된다");
}

void TestIssuedAtUpperDomainGuard() {
    // [S5] issued_at 상한 가드 — 없으면 도메인 밖 발행 시각이 kMalformed 가 아니라
    // kNotYetValid 로 판정된다. 계약 위반과 시계 이상은 다른 사실이다.
    ActionIntent intent = ValidIntent();
    intent.issued_at_utc_ms = ksi::control_plane::kMaxUtcMs + 1;
    Check(VerifyActionIntent(intent, kActiveDigest, kIssuedAt) == CommandVerdict::kMalformed,
          "도메인 상한 밖 issued_at 은 MALFORMED (NOT_YET_VALID 가 아니다)");
}

void TestSupervisorRejectsInvertedThresholds() {
    // [S3] 생성자의 설정 가드 — degrade 없이 곧장 fail-closed 로 가는 조립은
    // 오배선일 가능성이 높아 생성 시점에 거부한다. 이 가드를 검증하는 단언이
    // 하나도 없어서 삭제 변이가 그대로 통과했다.
    bool rejected_equal = false;
    try {
        FlightSupervisor bad(5'000, 5'000);
        (void)bad;
    } catch (const std::invalid_argument&) {
        rejected_equal = true;
    }
    Check(rejected_equal, "fail_closed == degrade 는 생성 시점에 거부된다");

    bool rejected_inverted = false;
    try {
        FlightSupervisor bad(5'000, 2'000);
        (void)bad;
    } catch (const std::invalid_argument&) {
        rejected_inverted = true;
    }
    Check(rejected_inverted, "fail_closed < degrade 도 거부된다");

    bool rejected_nonpositive = false;
    try {
        FlightSupervisor bad(0, 5'000);
        (void)bad;
    } catch (const std::invalid_argument&) {
        rejected_nonpositive = true;
    }
    Check(rejected_nonpositive, "0 이하 임계값은 거부된다");
}

void TestVerdictStringsAreDistinct() {
    // 로그·증거 번들에서 사유를 구분할 수 있어야 한다.
    //
    // [R1, 2026-08-07 reviewer 2차] 예전엔 15개 enumerator 중 3개만 고정돼 있었다 —
    // `case kDegraded: return "NOMINAL"` 같은 오매핑 변이가 통과했다. 판정 로직이
    // 아무리 정확해도 **그 판정을 사람에게 옮기는 문자열이 거짓말하면** 운영자는
    // 틀린 사실을 본다(supervisor.hpp "typed 사유가 남아야 진단 가능", 감사 #15).
    // 특히 HeartbeatVerdict 5종은 전부 미고정이라 "거부"가 "기록"으로 보일 수 있었다.
    //
    // 전건을 리터럴로 고정한다 — 심볼 참조로 쓰면 enum 이름을 바꿔도 통과한다.
    Check(std::string(ToString(CommandVerdict::kAccepted)) == "ACCEPTED", "ACCEPTED");
    Check(std::string(ToString(CommandVerdict::kExpired)) == "EXPIRED", "EXPIRED");
    Check(std::string(ToString(CommandVerdict::kNotYetValid)) == "NOT_YET_VALID", "NOT_YET_VALID");
    Check(std::string(ToString(CommandVerdict::kMissingAuthorization)) == "MISSING_AUTHORIZATION",
          "MISSING_AUTHORIZATION");
    Check(std::string(ToString(CommandVerdict::kAuthorizationMismatch)) == "AUTHORIZATION_MISMATCH",
          "AUTHORIZATION_MISMATCH");
    Check(std::string(ToString(CommandVerdict::kMalformed)) == "MALFORMED", "MALFORMED");
    Check(std::string(ToString(CommandVerdict::kSupervisorNotReady)) == "SUPERVISOR_NOT_READY",
          "supervisor 사유가 인가 사유와 다른 문자열");

    Check(std::string(ToString(ActionIntentKind::kHold)) == "HOLD", "HOLD intent kind");
    Check(std::string(ToString(ActionIntentKind::kReturnToHome)) == "RETURN_TO_HOME",
          "RETURN_TO_HOME intent kind");
    Check(std::string(ToString(ActionIntentKind::kGotoViewpoint)) == "GOTO_VIEWPOINT",
          "GOTO_VIEWPOINT intent kind");
    Check(std::string(ToString(ActionIntentKind::kCaptureImage)) == "CAPTURE_IMAGE",
          "CAPTURE_IMAGE intent kind");

    Check(std::string(ToString(SupervisorState::kFailClosed)) == "FAIL_CLOSED", "FAIL_CLOSED");
    Check(std::string(ToString(SupervisorState::kNominal)) == "NOMINAL", "NOMINAL");
    Check(std::string(ToString(SupervisorState::kDegraded)) == "DEGRADED", "DEGRADED");

    using ksi::control_plane::HeartbeatVerdict;
    Check(std::string(ToString(HeartbeatVerdict::kRecorded)) == "RECORDED", "RECORDED");
    Check(std::string(ToString(HeartbeatVerdict::kRecordedClamped)) == "RECORDED_CLAMPED",
          "RECORDED_CLAMPED");
    Check(std::string(ToString(HeartbeatVerdict::kStaleIgnored)) == "STALE_IGNORED",
          "STALE_IGNORED");
    Check(std::string(ToString(HeartbeatVerdict::kImplausibleFuture)) == "IMPLAUSIBLE_FUTURE",
          "IMPLAUSIBLE_FUTURE");
    Check(std::string(ToString(HeartbeatVerdict::kOutOfDomain)) == "OUT_OF_DOMAIN",
          "OUT_OF_DOMAIN");
}

void TestSafetyConstantValuesAreFixed() {
    // [R2, 2026-08-07 reviewer 2차] 경계 테스트들이 상수를 **심볼로 참조**하면
    // 정의를 바꿔도 입력이 같이 움직여 통과한다 — TestFutureToleranceBoundaryIsExact
    // 가 고정한 것은 "경계가 정확하고 포함적"이라는 *관계*지 *값*이 아니었다.
    //
    // 이 값들은 그냥 숫자가 아니다: kMaxUtcMs 는 command.hpp 가 주장하는 "이후 뺄셈이
    // int64 안에서 절대 넘치지 않는다"의 **유일한 근거**고(도메인 폭이 int64 절반을
    // 넘으면 그 주장이 무너진다), kHeartbeatFutureToleranceMs 를 넓히면 far-future
    // 타임스탬프가 클램프 기록돼 정지한 루프가 NOMINAL 근거를 얻는다.
    // 그래서 리터럴로 못박는다 — 값을 바꾸려면 이 단언을 함께 고쳐야 하고, 그때
    // 위 근거를 다시 보게 된다.
    Check(ksi::control_plane::kMaxUtcMs == 4'102'444'800'000,
          "kMaxUtcMs = 2100-01-01 (int64 뺄셈 안전성의 근거)");
    Check(ksi::control_plane::kMaxUtcMs < INT64_MAX / 2,
          "도메인 폭이 int64 절반 미만 — 두 도메인 값의 뺄셈이 넘치지 않는다");
    Check(ksi::control_plane::kMaxTtlMs == 300'000, "kMaxTtlMs = 5분");
    Check(ksi::control_plane::kHeartbeatFutureToleranceMs == 1'000,
          "허용창 = 1초 (넓히면 far-future 가 NOMINAL 근거가 된다)");
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
    TestInWindowFutureHeartbeatDoesNotSoftLatch();
    TestHeartbeatResetReturnsToFailClosed();
    TestStateAtOutOfDomainIsFailClosed();
    TestStateAtDomainGuardIsLoadBearing();
    TestDuplicateHeartbeatIsIgnored();
    TestRecordHeartbeatNowUpperDomainGuard();
    TestObservedAtUpperDomainGuard();
    TestFirstHeartbeatAtEpochZeroIsRecorded();
    TestFutureToleranceBoundaryIsExact();
    TestIssuedAtEqualsNowIsAccepted();
    TestIssuedAtUpperDomainGuard();
    TestSupervisorRejectsInvertedThresholds();
    TestVerdictStringsAreDistinct();
    TestSafetyConstantValuesAreFixed();

    std::printf("control plane 계약 테스트: %d개 단언 중 %d개 실패\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

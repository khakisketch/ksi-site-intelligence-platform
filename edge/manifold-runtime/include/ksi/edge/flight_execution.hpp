// ADR-KSI-021 §5 — 온보드 임무 START 실행 전 10단계 순수 안전 판단.
//
// 이 파일에는 DJI PSDK 심볼이 0개다(ADR §2 "런타임 자물쇠"는 이 파일이 아니라
// edge/psdk-app/src/flight_execution/ 어댑터가 여는 대상이고, 그 어댑터는 이번
// 라운드에 만들지 않는다). 여기는 순수 로직 + 사설 파일 I/O(activation.hpp·
// mission_kmz.hpp 와 같은 관습)뿐이며, PSDK Action(START)을 호출하지 않는다 —
// [9] durable 기록 확정까지만 하고 멈춘다. [10] UploadKmzFile→Action(START) 은
// 실기 확인 후 별도 어댑터의 몫이다(ADR §5, §11).
//
// 자동 재시도 없음(ADR §5 전문): arming nonce 1개는 START 시도 최대 1회다.
// [3]에서 토큰이 유효로 판정되는 즉시 그 nonce 파일을 소비(삭제)한다 — 이후
// [4]~[8] 중 어느 단계가 실패해도 nonce 는 이미 죽어 있고, 재시도는 현장에서
// 새 arming 토큰을 다시 발급받아야만 가능하다.

#ifndef KSI_EDGE_FLIGHT_EXECUTION_HPP
#define KSI_EDGE_FLIGHT_EXECUTION_HPP

#include <cstdint>
#include <string>
#include <vector>

#include "ksi/edge/activation.hpp"
#include "ksi/edge/mission_kmz.hpp"
#include "ksi/edge/shadow.hpp"
#include "ksi/edge/store_forward.hpp"

namespace ksi::edge {

// ── 단계 (ADR §6 C2-S0~S4) ──────────────────────────────────────────────────

enum class FlightExecutionStage {
    kS0 = 0,  // 현재 — 임무 실행 전무
    kS1 = 1,  // 업로드만(Action 없음)
    kS2 = 2,  // 프로펠러 없는 START
    kS3 = 3,  // 사람 감시 실비행(빌드 자물쇠는 S2 와 동일 — ADR §2)
    kS4 = 4,  // 일상 운용
};

const char* ToString(FlightExecutionStage stage);

// 이 빌드의 안전 판단 로직이 인증할 수 있는 최상단 단계 — check_shadow_flight_
// boundary.py 의 심볼 allowlist(빌드 자물쇠)와는 **독립된 두 번째 자물쇠**다
// (ADR §2). 심볼 allowlist 가 더 열려 있어도 이 상수가 낮으면 [0]에서 거부된다.
// S2 로 고정하는 이유: 이번 라운드가 배선하는 것이 정확히 ADR §6 S2 행("§5
// 런타임 사전조건 전량 구현·호스트 CI 통과")이고, S2 든 그 이상이든 이 파일은
// 어떤 PSDK Action 도 호출하지 않으므로 실제 이륙 능력은 이 상수와 무관하게
// 여전히 0 이다.
inline constexpr FlightExecutionStage kCompiledFlightExecutionStage = FlightExecutionStage::kS2;

// ── 판정 ─────────────────────────────────────────────────────────────────

enum class FlightExecutionVerdict {
    // 성공 — [0]~[9] 전부 통과, durable 기록 확정. Action(START) 은 아직 호출되지
    // 않았다(이 파일의 책임 밖).
    kEligibleForStart,

    // 호출자가 준 now_utc_ms 자체가 음수 — activation·arming 어느 쪽 판정도 아직
    // 시작하지 않은 방어적 실패다. [1]의 kActivationInvalid 와 사유가 다르므로
    // 별도 verdict 로 분리한다(durable 진단 문자열이 원인을 정확히 가리키게).
    kInvalidClock,

    // [0]
    kStageBelowRequired,

    // [1]
    kActivationInvalid,

    // [2] — Core 서명 비행 인가(이번 라운드에 Core 발급기는 없다 — 순수 로직만).
    // 장비 클래스·기체 일련번호는 여기서 "봉투 자체가 값을 채웠는가"만 본다
    // (비어있으면 kCoreAuthorizationMalformed) — 실제 기체와의 대조는 [8]
    // (kAircraftSerialMismatch)이 관측값으로 한다. 대조 대상 없이 "불일치"를
    // 판정할 수는 없다(값을 지어내지 않는다).
    kCoreAuthorizationNotVerified,
    kCoreAuthorizationMalformed,
    kCoreAuthorizationStageMismatch,
    kCoreAuthorizationDeviceMismatch,
    kCoreAuthorizationMissionMismatch,
    kCoreAuthorizationDispatchMismatch,
    kCoreAuthorizationContractMismatch,
    kCoreAuthorizationTtlTooLong,
    kCoreAuthorizationNotYetValid,
    kCoreAuthorizationExpired,

    // [3] — 현장 arming 토큰(§2).
    kArmingTokenUnsafeStateDirectory,
    kArmingTokenMissing,
    kArmingTokenUnsafeFile,
    kArmingTokenUnreadable,
    kArmingTokenTooLarge,
    kArmingTokenMalformed,
    kArmingTokenTtlTooLong,
    kArmingTokenNotYetValid,
    kArmingTokenExpired,
    kArmingTokenStageMismatch,
    kArmingTokenDeviceMismatch,
    kArmingTokenMissionMismatch,
    kArmingTokenDispatchMismatch,
    kArmingTokenConsumeFailed,

    // [4] — KMZ digest(재사용: mission_kmz.hpp).
    kKmzUnavailable,

    // [5] — KMZ 파싱 후 봉투 재도출.
    kEnvelopeMalformed,
    kEnvelopeRederivationFailed,
    kEnvelopeAltitudeOutOfBounds,
    kEnvelopeExcludedVolumesPresent,
    kEnvelopeAllowedVolumesEmpty,

    // [6] — 보수적 상한 가드(§6.1).
    kCeilingGuardRejected,

    // [7] — 감독기 준비 + 시계 역행(ShadowFlightSupervisor 재사용).
    kSupervisorMissing,
    kSupervisorClockRollback,
    kSupervisorNotActivated,
    kSupervisorNotNominal,

    // [8] — 기체 사전조건.
    kAircraftFlightStatusMissing,
    kAircraftFlightStatusNotStopped,
    kAircraftSerialMismatch,
    kAircraftBatteryMissing,
    kAircraftBatteryInsufficient,
    kAircraftHomePointMissing,
    kAircraftHomePointNotSet,
    kAircraftPositionQualityMissing,
    kAircraftPositionQualityInsufficient,
    kAircraftFlightAnomalyMissing,
    kAircraftFlightAnomalyPresent,
    kAircraftTelemetryStale,

    // [9] — durable 기록.
    kJournalUnavailable,
    kJournalRejected,
};

const char* ToString(FlightExecutionVerdict verdict);

// ── [2] Core 서명 비행 인가 ──────────────────────────────────────────────────
//
// Core 발급기는 이번 라운드에 없다(risk 원장 참고). 이 구조체는 "그런 서명
// 봉투가 주어지면"이라는 전제의 순수 필드 집합이다 — Ed25519 서명 검증은 이
// 함수의 책임이 아니고, ``verified`` 는 호출자가 그 검증을 이미 통과시켰다는
// 것을 명시적으로 표시하는 게이트다(기본값 false = 항상 거부).
struct CoreFlightAuthorization {
    bool verified = false;
    FlightExecutionStage authorized_stage = FlightExecutionStage::kS0;
    std::string equipment_class;
    std::string aircraft_serial_number;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;  // "sha256:<hex>"
    std::int64_t issued_at_utc_ms = 0;
    std::int64_t expires_at_utc_ms = 0;
};

// ── [3] 현장 arming 토큰 ─────────────────────────────────────────────────────
//
// ADR §5[2]가 명시한 유일한 숫자값: TTL ≤ 10분. 그 밖의 "짧은 TTL"(Core 인가)은
// 정책값이라 호출자가 준다(FlightExecutionPolicy::maximum_core_authorization_
// ttl_ms) — 근거 없는 상수를 이 헤더에 박지 않는다.
inline constexpr std::int64_t kMaximumArmingTokenTtlMs = 10LL * 60LL * 1000LL;
inline constexpr char kFieldArmingTokenFilename[] = "flight-arm-token.v1";
inline constexpr std::size_t kMaximumArmingTokenBytes = 4U * 1024U;

struct FieldArmingToken {
    std::string nonce;
    std::string issuer;
    FlightExecutionStage stage = FlightExecutionStage::kS0;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::int64_t issued_at_utc_ms = 0;
    std::int64_t expires_at_utc_ms = 0;
};

enum class ArmingTokenWriteVerdict {
    kWritten,
    kUnsafeStateDirectory,
    kInvalidRequest,
    kWriteFailed,
};

const char* ToString(ArmingTokenWriteVerdict verdict);

// ksi_edge_flight_arm CLI 가 부른다. 원자적 쓰기(임시 파일 + rename + fsync,
// activation.hpp 관습과 동일한 사설 파일 성질: 소유자 전용, 심링크 아님).
ArmingTokenWriteVerdict WriteFieldArmingToken(const std::string& state_directory,
                                              const FieldArmingToken& token);

enum class ArmingTokenVerdict {
    kConsumed,
    kUnsafeStateDirectory,
    kMissing,
    kUnsafeFile,
    kUnreadable,
    kTooLarge,
    kMalformed,
    kTtlTooLong,
    kNotYetValid,
    kExpired,
    kStageMismatch,
    kDeviceMismatch,
    kMissionMismatch,
    kDispatchMismatch,
    kConsumeFailed,
};

const char* ToString(ArmingTokenVerdict verdict);

struct ArmingTokenConsumptionResult {
    ArmingTokenVerdict verdict = ArmingTokenVerdict::kMissing;
    FieldArmingToken token;
};

// 정확히 1회 소비한다: 검증이 kConsumed 에 도달하는 순간 파일을 즉시 unlink 한다
// (호출 전이 아니라 **호출 스스로**가 소비 시점이다 — ADR §5 "nonce 를 여기서
// 소비한다(호출 전, 후가 아니라)"). 검증이 실패하면(만료·불일치 등) 파일은
// 그대로 남는다 — 잘못 도착한 요청이 살아있는 arming 을 대신 태우지 않는다.
ArmingTokenConsumptionResult ConsumeFieldArmingToken(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_mission_id, const std::string& expected_dispatch_id,
    FlightExecutionStage expected_stage, std::int64_t now_utc_ms);

// ── §8 abort 프로토콜 — watchdog 이 관찰할 사설 상태파일 ────────────────────
//
// 5Hz 폴링 관찰자는 이번 라운드에 만들지 않는다(ADR 명시) — 파일 프로토콜만
// 정의하고 시험으로 고정한다. abort 는 임무 하나에 매인 nonce 소비가 아니다:
// "지금 이 상태파일에 요청이 있는가"가 전부이고, 관찰자가 처리 후 지운다.
inline constexpr char kFlightAbortRequestFilename[] = "flight-abort-request.v1";
inline constexpr std::size_t kMaximumAbortRequestBytes = 4U * 1024U;

struct AbortRequestRecord {
    std::string requested_by;
    std::string reason;
    std::int64_t requested_at_utc_ms = 0;
    // 비어 있을 수 있다 — abort 는 특정 임무에 매인 개념이 아니라(ADR §8 "우리가
    // 보장하는 것은 abort 트리거 수신 후 X ms 내 Action(STOP) 발행" 뿐이다),
    // 있으면 진단에 보탠다.
    std::string mission_id;
    std::string dispatch_id;
};

enum class AbortRequestWriteVerdict {
    kWritten,
    kUnsafeStateDirectory,
    kInvalidRequest,
    kWriteFailed,
};

const char* ToString(AbortRequestWriteVerdict verdict);

// ksi_edge_flight_abort CLI 가 부른다. 원자적 쓰기 — watchdog 이 절반만 쓰인
// 파일을 읽는 창을 만들지 않는다.
AbortRequestWriteVerdict WriteAbortRequest(const std::string& state_directory,
                                           const AbortRequestRecord& record);

enum class AbortRequestReadVerdict {
    kPresent,
    kAbsent,
    kUnsafeStateDirectory,
    kUnsafeFile,
    kUnreadable,
    kTooLarge,
    kMalformed,
};

const char* ToString(AbortRequestReadVerdict verdict);

struct AbortRequestReadResult {
    AbortRequestReadVerdict verdict = AbortRequestReadVerdict::kAbsent;
    AbortRequestRecord record;
};

// 이번 라운드의 유일한 소비자는 시험이다 — 실제 watchdog 은 별도 라운드다.
// 그래도 프로토콜 왕복(쓰기→읽기)을 여기서 고정해 둔다.
AbortRequestReadResult ReadAbortRequest(const std::string& state_directory);

// abort 요청을 지운다(watchdog 이 처리 후 부를 함수 — 이번 라운드는 시험 전용).
bool ClearAbortRequest(const std::string& state_directory);

// ── [5] KMZ 파싱 후 봉투 재도출 ──────────────────────────────────────────────
//
// FlightEnvelope.allowedVolumes/excludedVolumes 는 폴리곤이 아니라 volume ID
// 참조다(packages/mission-contracts FlightEnvelope 참고) — 실제 경계는 KMZ
// 안에 없다. 그래서 이 재도출은 고도 범위만 KMZ 원문(wpmz/waylines.wpml 의
// executeHeight 전량)에서 다시 구하고, volume 목록 자체의 정책 위반(배제구역
// 선언·허용구역 미선언)은 DeclaredFlightEnvelope 값을 직접 본다 — 폴리곤 포함
// 판정은 이번 라운드 범위 밖이다(값을 지어내지 않는다).
struct DeclaredFlightEnvelope {
    std::vector<std::string> allowed_volume_ids;
    std::vector<std::string> excluded_volume_ids;
    double min_altitude_m = 0.0;
    double max_altitude_m = 0.0;
};

enum class KmzEnvelopeRederivationVerdict {
    kDerived,
    kZipMalformed,
    kWaylinesEntryMissing,
    kWaylinesTooLarge,
    kInflateFailed,
    kCrcMismatch,
    kXmlMalformed,
    kNoWaypoints,
    kNonFiniteAltitude,
};

const char* ToString(KmzEnvelopeRederivationVerdict verdict);

struct KmzEnvelopeRederivationResult {
    KmzEnvelopeRederivationVerdict verdict = KmzEnvelopeRederivationVerdict::kZipMalformed;
    double observed_min_altitude_m = 0.0;
    double observed_max_altitude_m = 0.0;
    std::size_t waypoint_count = 0;
};

// wpmz/waylines.wpml 의 <wpml:executeHeight> 리터럴 태그 전량을 뽑아 관측 고도
// 범위를 재도출한다. **일반 XML 파서가 아니다** — wpml.py 가 실제로 내는 태그
// 문법만 겨냥한 경계 스캐너다(전체 WPML 스키마 검증은 범위 밖 — Core 서명 계약이
// 이미 이 KMZ 의 출처를 보증하고, 이 판독은 방어종심 목적의 고도 재도출로
// 한정한다). PK 로컬 파일 헤더를 순회하며 대상 항목을 찾고(데이터 디스크립터
// 사용 항목은 거부 — wpml.py 는 쓰지 않는다), DEFLATE(RFC1951)만 지원한다.
KmzEnvelopeRederivationResult RederiveKmzAltitudeEnvelope(const std::string& kmz_bytes);

// ── [6] 보수적 상한 가드(§6.1) ───────────────────────────────────────────────
//
// FlightEnvelope 나 계약 스키마는 고치지 않는다(ADR-KSI-022 선점 금지) — Edge
// 실행 가드로만 좁힌다. 10m·135m 는 물리 상수가 아니라 **정책값**이다(ADR §6.1
// 명시) — 그래서 헤더 상수로 고정한다(ADR 이 그 값 자체를 지정했다).
inline constexpr double kCeilingGuardMaxTerrainReliefM = 10.0;
inline constexpr double kCeilingGuardMaxEffectiveAltitudeM = 135.0;

enum class SiteDensityDeclaration {
    kUnspecified = 0,  // 미선언 — 거부(ADR "미선언 시 거부")
    kGeneralArea,
    kCongestedArea,  // "주변 최고 장애물 상단" 기준 미구현 — 이번 라운드는 항상 거부
};

const char* ToString(SiteDensityDeclaration declaration);

struct CeilingGuardInput {
    bool has_dtm_coverage = false;
    // AOI 안 DTM/DSM 표고 샘플(동일 기준면). 비어 있으면 평탄도 판정 불가.
    std::vector<double> aoi_terrain_elevation_samples_m;
    double takeoff_elevation_m = 0.0;
    // [5]에서 이미 재도출·검증된 FlightEnvelope.max_altitude_m 을 그대로 받는다
    // (재입력이 아니라 재사용 — 두 값이 갈리면 그 자체가 버그다).
    double declared_max_altitude_m = 0.0;
    SiteDensityDeclaration site_density = SiteDensityDeclaration::kUnspecified;
};

enum class CeilingGuardVerdict {
    kPassed,
    kNonFiniteInput,
    kNoDtmCoverage,
    kTerrainSamplesEmpty,
    kTerrainNotFlat,
    kTakeoffOutsideTerrainRange,
    kCeilingTooHigh,
    kDensityUnspecified,
    kDensityCongested,
};

const char* ToString(CeilingGuardVerdict verdict);

struct CeilingGuardResult {
    CeilingGuardVerdict verdict = CeilingGuardVerdict::kNoDtmCoverage;
    double observed_terrain_min_m = 0.0;
    double observed_terrain_max_m = 0.0;
    double observed_terrain_relief_m = 0.0;
};

CeilingGuardResult EvaluateFlightExecutionCeilingGuard(const CeilingGuardInput& input);

// ── [8] 기체 사전조건 ────────────────────────────────────────────────────────
//
// main.cpp 가 기존 6개 구독과 같은 방식으로 DjiFcSubscription_* 콜백에서 캐시한
// 최신값을 원자적 스냅샷으로 넘겨받는다. 이 파일은 PSDK 헤더를 모르므로 원시
// enum 값(E_DjiFcSubscriptionFlightStatus 등)을 그대로 받는다 — 이름을 다시
// 해석하지 않는다. ``*_present=false`` 는 "그 토픽 콜백을 한 번도 못 받았다"이지
// 0/false 를 안전값으로 대신하지 않는다.
struct AircraftPreconditionSnapshot {
    bool flight_status_present = false;
    std::uint8_t flight_status = 0;  // E_DjiFcSubscriptionFlightStatus 원시값(0=STOPED)
    std::int64_t flight_status_observed_utc_ms = 0;

    bool battery_present = false;
    std::uint8_t battery_percent_1pct = 0;
    std::int64_t battery_observed_utc_ms = 0;

    bool home_point_present = false;
    std::uint8_t home_point_set_status = 0;  // E_DjiFcSubscriptionHomePointSetStatus(1=SUCCESS)
    std::int64_t home_point_observed_utc_ms = 0;

    bool position_solution_present = false;
    std::uint8_t position_solution_property = 0;  // E_DjiFcSubscriptionPositionSolutionProperty
    std::int64_t position_solution_observed_utc_ms = 0;

    bool flight_anomaly_present = false;
    std::uint32_t flight_anomaly_bits = 0;  // T_DjiFcSubscriptionFlightAnomaly 원시 32비트, 0=이상없음
    std::int64_t flight_anomaly_observed_utc_ms = 0;

    // FC 구독 토픽에 기체 일련번호가 없다(조사 결과 — dji_fc_subscription.h 에
    // 그런 토픽이 없다) — 별도 경로가 채우기 전엔 항상 빈 문자열이고, 빈
    // 문자열은 kCoreAuthorization 의 비어있지 않은 일련번호와 절대 같을 수
    // 없어 자연히 fail-closed 로 귀결한다(값을 지어내지 않는다).
    std::string observed_aircraft_serial_number;
};

struct AircraftPreconditionPolicy {
    // 전부 호출자(main.cpp 설정/시험)가 주는 정책값이다 — ADR 이 구체 수치를
    // 지정하지 않았으므로 이 헤더는 어떤 기본값도 지어내지 않는다(0 은 "정책
    // 미설정"이 아니라 그 자체로 유효한 극단값일 수 있어, 호출자가 반드시
    // 실제 값을 채워야 한다).
    std::uint8_t minimum_battery_percent_1pct = 0;
    std::uint8_t minimum_position_solution_property = 0;
    // 반드시 양수. 0 을 "신선도 검사 생략"으로 쓰지 않는다 — 검사를 원치 않으면
    // 아주 큰 값을 명시적으로 넣어라(생략을 특수값으로 표현하면 그 생략이
    // 나중에 실수로 은폐된다).
    std::int64_t maximum_telemetry_age_ms = 0;
};

// ── 종합 판단 ────────────────────────────────────────────────────────────────

struct FlightExecutionRequest {
    FlightExecutionStage requested_stage = FlightExecutionStage::kS0;

    // [1] 이미 로드된 결과 — 이 함수가 파일을 다시 읽지 않는다.
    NativeActivationLoadResult activation;

    // [2]
    CoreFlightAuthorization core_authorization;
    std::int64_t maximum_core_authorization_ttl_ms = 0;  // 정책값(호출자가 채운다)

    // [3]
    std::string arming_state_directory;

    // [4]
    NativeMissionKmzLoadResult kmz;

    // [5]
    DeclaredFlightEnvelope declared_envelope;

    // [6] (declared_max_altitude_m 은 EvaluateFlightExecution 이 declared_envelope
    // 에서 채운다 — 호출자가 여기 넣은 값은 무시된다, 재입력 불일치를 원천 차단)
    CeilingGuardInput ceiling_guard_input;

    // [7]
    ShadowFlightSupervisor* supervisor = nullptr;

    // [8]
    AircraftPreconditionSnapshot aircraft;
    AircraftPreconditionPolicy aircraft_policy;

    // [9]
    SqliteStoreForward* journal = nullptr;
};

struct FlightExecutionDecision {
    FlightExecutionVerdict verdict = FlightExecutionVerdict::kStageBelowRequired;
    ArmingTokenVerdict arming_token_verdict = ArmingTokenVerdict::kMissing;
    KmzEnvelopeRederivationResult envelope_rederivation;
    CeilingGuardResult ceiling_guard;
    std::string flight_start_attempt_id;
    FlightStartAttemptJournalVerdict journal_verdict = FlightStartAttemptJournalVerdict::kBackendUnavailable;
};

// ADR-KSI-021 §5 의 10단계를 순서대로 실행한다. 콜백 컨텍스트에서 부르지 않는다
// (§3 blocking 금지 제약 상속 — 이 함수는 파일 I/O 를 한다). 성공이든 실패든
// [1] 활성화가 유효했던 시점 이후로는(§9) durable 기록을 시도한다 — request.
// journal 이 nullptr 이면 [9] 자체가 kJournalUnavailable 이다.
FlightExecutionVerdict EvaluateFlightExecution(const FlightExecutionRequest& request,
                                               std::int64_t now_utc_ms,
                                               FlightExecutionDecision* decision);

}  // namespace ksi::edge

#endif  // KSI_EDGE_FLIGHT_EXECUTION_HPP

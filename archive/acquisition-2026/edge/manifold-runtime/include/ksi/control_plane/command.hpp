// KSI Edge native control plane — command 계약 (Stage C-3).
//
// 범위 경계 (중요):
//   이 헤더는 **명령의 유효성 계약**만 정의한다. 실제 DJI PSDK 비행명령 발행은
//   이 단계 범위가 아니며(장비/HIL 증거 전까지 금지), 여기 어떤 타입도 기체를
//   움직이지 않는다. 검증을 통과한 ActionIntent가 이후 Flight Supervisor를 거쳐
//   DJI에 "고수준 의도"로 전달되는 구조를 위한 골격이다(INV-001: 저수준 비행
//   안전은 DJI Flight Controller 소유, Core는 프레임별 제어를 보내지 않는다).
//
// 시간축 규약: 모든 시각은 UTC epoch 기준 밀리초(int64). Python 쪽
// ksi_geo_core.timestamps 의 UTC 도메인과 같은 축이며, process-local monotonic
// 시계와 섞지 않는다(P0-2 반증 리뷰에서 확정된 규약을 C++ 쪽에도 동일 적용).

#ifndef KSI_CONTROL_PLANE_COMMAND_HPP
#define KSI_CONTROL_PLANE_COMMAND_HPP

#include <cstdint>
#include <string>

namespace ksi::control_plane {

using UtcMillis = std::int64_t;

/// TTL 상한(ms) — 무기한 유효한 명령(replay 가능한 인가 토큰) 금지. 값 5분은
/// 대표자 결정 대기 권고 기본값이며 Python MAX_TTL_MS·JSON 스키마 maximum 과
/// 항상 같아야 한다(갈리면 conformance 벡터가 잡는다).
inline constexpr std::int64_t kMaxTtlMs = 300'000;

/// 시각 도메인 상한 — 2100-01-01T00:00:00Z (UTC epoch ms). issued_at/now 가 이
/// 도메인을 벗어나면 판정 불가로 거부한다. 이 선검사가 아래 TTL 뺄셈의 int64
/// signed overflow(UB — 감사 #14 에서 fail-open 으로 실증)를 구조적으로 막는다.
inline constexpr UtcMillis kMaxUtcMs = 4'102'444'800'000;

/// 고수준 행동 의도의 종류. 저수준 조종 명령(자세·모터·속도)은 의도적으로 없다 —
/// 그런 명령은 DJI Flight Controller의 소유이며 KSI가 재구현하지 않는다(INV-001).
enum class ActionIntentKind {
    kHold,          ///< 현재 위치 유지
    kReturnToHome,  ///< RTH 요청(최종 실행 권한은 DJI FC)
    kGotoViewpoint, ///< 승인된 Flight Envelope 안의 관측점으로 이동 요청
    kCaptureImage,  ///< 촬영(비행 상태를 바꾸지 않음)
};

// Stable wire names for audit records.  This is intentionally separate from
// CommandVerdict::ToString: a shadow journal must say which high-level intent
// was judged without serializing an implementation enum ordinal.
const char* ToString(ActionIntentKind kind);

/// 명령 거부 사유. 성공은 kAccepted 하나뿐이고 나머지는 전부 거부다(fail-closed).
enum class CommandVerdict {
    kAccepted,
    kExpired,              ///< TTL 경과 — 낡은 명령은 실행하지 않는다
    kNotYetValid,          ///< issued_at 이 미래 — 시계 이상 또는 위조
    kMissingAuthorization, ///< Mission Contract digest 부재
    kAuthorizationMismatch,///< 현재 활성 계약과 digest 불일치
    kMalformed,            ///< 필수 필드 누락·비정상 TTL 등
    kSupervisorNotReady,   ///< 명령은 유효하나 Edge가 새 행동을 시작할 상태가 아님
};

/// Core가 서명한 Mission Contract에 귀속된 고수준 행동 의도.
///
/// authorization_digest 는 Python 쪽 ADR-KSI-002 의 계약 digest("sha256:<hex>")를
/// 그대로 옮긴 값이다 — Edge는 이 값이 현재 로드된 활성 계약과 일치할 때만 명령을
/// 받아들인다. Edge가 서명을 직접 재검증하지는 않는다(계약 로드 시점에 이미 검증된
/// 것을 전제로 하고, 여기서는 "어느 계약에 귀속된 명령인가"의 바인딩만 확인한다).
struct ActionIntent {
    /// 계약 스키마 버전. 기본값이 빈 문자열인 것은 의도다 — 명시적으로 "1.0"을
    /// 채우지 않은 명령은 kMalformed 로 거부된다(fail-closed 기본값, 감사 #16).
    std::string schema_version;
    std::string command_id;
    ActionIntentKind kind = ActionIntentKind::kHold;
    std::string authorization_digest; ///< "sha256:<hex>" — 빈 문자열이면 미인가
    UtcMillis issued_at_utc_ms = 0;
    std::int64_t ttl_ms = 0; ///< 0 < ttl <= kMaxTtlMs. 밖은 kMalformed.
    std::string target_viewpoint_id; ///< kGotoViewpoint 필수(빈 문자열=부재, 감사 #18)
};

/// 명령 유효성 판정 — TTL·인가·시계 이상을 순서대로 검사한다.
///
/// 판정 순서: 형식(malformed) → 인가 존재 → 인가 일치 → 미래 발행 → TTL 만료.
/// 어느 단계든 실패하면 그 사유를 반환하며, kAccepted 는 모든 검사를 통과했을
/// 때만 나온다. 예외를 던지지 않는다(fail-closed — 판정 불가 상황은 거부로 귀결).
///
/// @param intent          검사할 명령
/// @param active_digest   현재 Edge에 로드된 활성 Mission Contract digest
/// @param now_utc_ms      현재 UTC 시각(밀리초)
CommandVerdict VerifyActionIntent(const ActionIntent& intent,
                                  const std::string& active_digest,
                                  UtcMillis now_utc_ms);

/// 사람이 읽는 판정 사유(로그·증거 번들용).
const char* ToString(CommandVerdict verdict);

} // namespace ksi::control_plane

#endif // KSI_CONTROL_PLANE_COMMAND_HPP

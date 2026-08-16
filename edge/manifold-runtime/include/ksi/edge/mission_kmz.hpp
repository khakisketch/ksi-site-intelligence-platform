// Strict native reader for the verified mission KMZ handoff.
//
// The KMZ is the only artifact in this system that carries no signature of its
// own.  Its provenance comes entirely from ``kmzSha256`` inside the Core-signed
// MissionDispatchEnvelope, which Python verifies before it writes the bytes and
// their sidecar here (``ksi_mission_contracts.edge_activation``).  This reader
// therefore does not re-derive trust; it re-derives the *binding*: same device,
// same mission, same contract digest, same byte count, same sha256.
//
// Re-hashing on load is not redundant with Python's check.  Between activation
// and use, the file lives on disk across process restarts and possibly a
// reboot, and the consumer of these bytes hands them to the aircraft.  A local
// reader that trusts a filename is a reader that will one day fly a stale
// route.
//
// Like the other native handoffs, absence is a typed no-KMZ result rather than
// a fallback to whatever was there before, and this file contains no PSDK
// symbol of any kind.

#ifndef KSI_EDGE_MISSION_KMZ_HPP
#define KSI_EDGE_MISSION_KMZ_HPP

#include <cstddef>
#include <cstdint>
#include <string>

namespace ksi::edge {

inline constexpr char kActiveMissionKmzFilename[] = "active-mission.kmz";
inline constexpr char kNativeMissionKmzFilename[] = "active-mission-kmz.native.v1";

// KMZ 는 웨이라인 하나지 미디어가 아니다. 상한은 Python 컴패니언
// (``_MAX_MISSION_KMZ_BYTES``)과 같은 값을 **독립적으로** 강제한다 — 한쪽이
// 넓어져도 다른 쪽이 남는 것이 이 이중 상한의 목적이다.
inline constexpr std::size_t kMaximumMissionKmzBytes = 8U * 1024U * 1024U;

struct NativeMissionKmz {
    std::string dispatch_id;
    std::string edge_device_id;
    std::string mission_id;
    // "sha256:<hex>" — 활성화 스냅샷과 같은 표기로 대조된다.
    std::string mission_contract_digest;
    // bare hex — Core 발급 원장(``MissionRecord.kmzSha256``)의 표기 그대로다.
    std::string kmz_sha256;
    // 검증을 통과한 실제 바이트. 경로가 아니라 바이트를 돌려주는 이유: 경로를
    // 돌려주면 호출부가 다시 열게 되고, 그 사이에 파일이 바뀌면 검증한 것과
    // 쓰는 것이 달라진다(TOCTOU).
    std::string bytes;
};

enum class NativeMissionKmzVerdict {
    kLoaded,
    // 사이드카가 없다 = 이 활성화에 묶인 KMZ 가 없다. 이전 임무의 파일이 남아
    // 있더라도 그것으로 되돌아가지 않는다.
    kMissing,
    kUnsafeStateDirectory,
    kUnsafeSidecar,
    kUnsafeKmz,
    kUnreadable,
    kTooLarge,
    kMalformed,
    kDeviceMismatch,
    kMissionMismatch,
    kContractMismatch,
    kSizeMismatch,
    kDigestMismatch,
};

const char* ToString(NativeMissionKmzVerdict verdict);

struct NativeMissionKmzLoadResult {
    NativeMissionKmzVerdict verdict = NativeMissionKmzVerdict::kMissing;
    NativeMissionKmz kmz;
};

// Reads ``<state_directory>/active-mission-kmz.native.v1`` and the
// ``active-mission.kmz`` it describes.
//
// The state directory, the sidecar, and the KMZ must all be owned by the
// current effective user with no group/other permissions and no symlink in the
// way — the same checks the activation snapshot reader applies, for the same
// reason: a file another account can rewrite is not evidence of anything.
//
// ``expected_*`` binds the pair to the activation the caller already loaded
// (``LoadNativeActivationSnapshot``).  Passing values from anywhere else would
// make this function answer a question nobody asked.
NativeMissionKmzLoadResult LoadNativeMissionKmz(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_mission_id,
    const std::string& expected_mission_contract_digest);

}  // namespace ksi::edge

#endif  // KSI_EDGE_MISSION_KMZ_HPP

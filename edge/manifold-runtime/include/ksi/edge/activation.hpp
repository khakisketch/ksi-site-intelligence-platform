// Startup-only handoff from the verified Python Mission Dispatch consumer to
// the native Manifold runtime.
//
// The signed MissionDispatchEnvelope and Mission Contract are verified by
// ``ksi_mission_contracts.edge_activation`` before this file is written.  This
// native reader deliberately does not duplicate Ed25519 verification; it
// validates a private, atomically-written, fixed-format handoff and converts it
// to the ShadowFlightSupervisor activation context.  It is never used from a
// PSDK callback or frame worker.

#ifndef KSI_EDGE_ACTIVATION_HPP
#define KSI_EDGE_ACTIVATION_HPP

#include <cstdint>
#include <string>

#include "ksi/edge/risk.hpp"
#include "ksi/edge/shadow.hpp"

namespace ksi::edge {

inline constexpr char kNativeActivationFilename[] = "active-dispatch.native.v1";

struct NativeActivationSnapshot {
    std::string dispatch_id;
    std::string edge_device_id;
    std::string mission_id;
    ActivationContext context;
    // The policy values are copied out of the already verified signed dispatch
    // handoff.  They are not defaults: missing/invalid values make loading
    // fail, and ConservativeRiskEngine still requires measured dimensions and
    // covariance from the projector for every observation.
    RiskPolicyPack risk_policy_pack;
    std::int64_t activated_at_utc_ms = 0;
    std::string runtime_version;
};

enum class NativeActivationVerdict {
    kLoaded,
    kMissing,
    kUnsafeStateDirectory,
    kUnsafeSnapshot,
    kUnreadable,
    kTooLarge,
    kMalformed,
    kDeviceMismatch,
    kRuntimeMismatch,
    kNotYetValid,
    kExpired,
};

const char* ToString(NativeActivationVerdict verdict);

struct NativeActivationLoadResult {
    NativeActivationVerdict verdict = NativeActivationVerdict::kMissing;
    NativeActivationSnapshot snapshot;
};

// Reads ``<state_directory>/active-dispatch.native.v1``.
//
// The state directory and file must be owned by the current effective user,
// have no group/other permissions, and contain no symlink.  ``expected_*``
// binds a copied state file to the installed DPK identity.  A missing or stale
// handoff is a typed no-activation result, not a fallback to an older contract.
NativeActivationLoadResult LoadNativeActivationSnapshot(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_runtime_version, std::int64_t now_utc_ms);

}  // namespace ksi::edge

#endif  // KSI_EDGE_ACTIVATION_HPP

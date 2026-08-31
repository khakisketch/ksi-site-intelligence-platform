// Private, operator-mediated control records for the source-media conveyor.
//
// A Camera Manager file list alone must never turn into an upload job: it
// contains older SD-card files with no Mission attribution.  This protocol
// makes that boundary explicit:
//
//   operator prepare request -> pre-activation camera baseline -> verified
//   native activation -> operator one-shot trigger -> media conveyor
//
// All records live in a dedicated owner-only on-device directory.  They are
// deliberately local control evidence, not a substitute for the signed Mission
// Contract or an executable flight-control channel.

#ifndef KSI_EDGE_MEDIA_CONTROL_HPP
#define KSI_EDGE_MEDIA_CONTROL_HPP

#include <cstdint>
#include <string>
#include <vector>

#include "ksi/edge/activation.hpp"
#include "ksi/edge/media_offload.hpp"

namespace ksi::edge {

inline constexpr char kMediaBaselineRequestFilename[] = "source-media-baseline-request.v1";
inline constexpr char kMediaBaselineFilename[] = "source-media-baseline.v1";
inline constexpr char kMediaOperatorTriggerFilename[] = "source-media-operator-trigger.v1";
// A preparation or one-shot approval that is not consumed promptly is stale.
// The companion tools enforce this upper bound rather than leaving a broadly
// reusable consent file on an edge device.
inline constexpr std::int64_t kMaximumMediaControlTtlMs = 15LL * 60LL * 1000LL;

// Created by a local operator-facing companion before the verified activation
// receipt is written.  ``nonce`` is random and prevents a stale request from
// being confused with a new preparation of the same Mission.
struct MediaBaselineRequest {
    std::string operator_id;
    std::string nonce;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;
    std::int64_t requested_at_utc_ms = 0;
    std::int64_t expires_at_utc_ms = 0;
};

// Produced by the DPK only after it has obtained temporary download rights,
// listed the camera, and released the rights.  It never includes image bytes.
struct MediaBaselineRecord {
    MediaBaselineRequest request;
    std::int64_t observed_at_utc_ms = 0;
    // Canonical digest of ``request``.  A copied/edited baseline therefore
    // cannot be rebound to another preparation request.
    std::string request_digest;
    std::vector<SourceMediaFileHandle> files;
};

// Explicit one-shot consent to start source-media delivery.  It binds to an
// exact baseline, active dispatch, and Mission Contract digest; it has no
// camera/flight/gimbal command fields.
struct OperatorMediaOffloadTrigger {
    std::string operator_id;
    std::string nonce;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;
    std::string baseline_digest;
    std::int64_t issued_at_utc_ms = 0;
    std::int64_t expires_at_utc_ms = 0;
};

enum class MediaControlLoadVerdict {
    kLoaded,
    kMissing,
    kUnsafeStateDirectory,
    kUnsafeRecord,
    kUnreadable,
    kTooLarge,
    kMalformed,
    kNotYetValid,
    kExpired,
};

const char* ToString(MediaControlLoadVerdict verdict);

enum class MediaControlWriteVerdict {
    kWritten,
    // A new pre-activation request deliberately superseded an older baseline.
    // It is control metadata only; a trigger still has to bind the new digest.
    kReplaced,
    kDuplicate,
    kConflict,
    kUnsafeStateDirectory,
    kInvalidRecord,
    kStorageError,
};

const char* ToString(MediaControlWriteVerdict verdict);

struct MediaBaselineRequestLoadResult {
    MediaControlLoadVerdict verdict = MediaControlLoadVerdict::kMissing;
    MediaBaselineRequest request;
};

struct MediaBaselineRecordLoadResult {
    MediaControlLoadVerdict verdict = MediaControlLoadVerdict::kMissing;
    MediaBaselineRecord record;
};

struct OperatorMediaOffloadTriggerLoadResult {
    MediaControlLoadVerdict verdict = MediaControlLoadVerdict::kMissing;
    OperatorMediaOffloadTrigger trigger;
};

// These canonical SHA-256 values are persisted only as non-secret attestations
// of control records.  Raw filenames remain on the private device/control
// directory and are never sent to a log by this API.
std::string ComputeMediaBaselineRequestDigest(const MediaBaselineRequest& request);
std::string ComputeMediaBaselineRecordDigest(const MediaBaselineRecord& record);
std::string ComputeOperatorMediaOffloadTriggerDigest(
    const OperatorMediaOffloadTrigger& trigger);

MediaControlWriteVerdict WriteMediaBaselineRequest(const std::string& state_directory,
                                                    const MediaBaselineRequest& request);
MediaBaselineRequestLoadResult LoadMediaBaselineRequest(const std::string& state_directory,
                                                         std::int64_t now_utc_ms);

MediaControlWriteVerdict WriteMediaBaselineRecord(const std::string& state_directory,
                                                   const MediaBaselineRecord& record);
MediaBaselineRecordLoadResult LoadMediaBaselineRecord(const std::string& state_directory);

MediaControlWriteVerdict WriteOperatorMediaOffloadTrigger(
    const std::string& state_directory, const OperatorMediaOffloadTrigger& trigger);
OperatorMediaOffloadTriggerLoadResult LoadOperatorMediaOffloadTrigger(
    const std::string& state_directory, std::int64_t now_utc_ms);

enum class MediaControlSelectionVerdict {
    kReady,
    kInvalidActivation,
    kInvalidBaseline,
    kInvalidTrigger,
    kBaselineAfterActivation,
    kTriggerBeforeActivation,
    kBindingMismatch,
    kBaselineDigestMismatch,
};

const char* ToString(MediaControlSelectionVerdict verdict);

struct MediaControlSelectionResult {
    MediaControlSelectionVerdict verdict = MediaControlSelectionVerdict::kInvalidActivation;
    MissionMediaSelectionContext selection_context;
};

// Builds the only MissionMediaSelectionContext permitted for the v1 automatic
// path.  Failure is typed and returns no partially populated context.
MediaControlSelectionResult BuildOperatorMediaSelectionContext(
    const NativeActivationSnapshot& activation, const MediaBaselineRecord& baseline,
    const OperatorMediaOffloadTrigger& trigger, std::int64_t now_utc_ms);

}  // namespace ksi::edge

#endif  // KSI_EDGE_MEDIA_CONTROL_HPP

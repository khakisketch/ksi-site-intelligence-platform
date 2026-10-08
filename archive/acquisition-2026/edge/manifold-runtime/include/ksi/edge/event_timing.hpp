// Local, fail-closed timing evidence for the Edge candidate path.
//
// REQ-EVT-101 needs timestamped replay/HIL evidence, but the optional
// EventBundle.timing fields also cover a user-visible local alert and a Core
// user notification. This shadow slice owns neither of those products, so it
// must not populate them with unrelated pipeline timings. Instead this module
// records the one boundary it can state precisely: PSDK RGB callback receipt
// on CLOCK_MONOTONIC -> SQLite candidate/evidence transaction accepted.

#ifndef KSI_EDGE_EVENT_TIMING_HPP
#define KSI_EDGE_EVENT_TIMING_HPP

#include <cstdint>
#include <string>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/frame_queue.hpp"

namespace ksi::edge {

enum class CandidateTimingVerdict {
    kMeasured,
    // An idempotent SQLite duplicate is an old candidate/retry, not a new
    // candidate creation. Measuring its retry latency would corrupt the SLO
    // denominator, so it remains explicit and is not persisted as a sample.
    kDuplicateNotMeasured,
    kMissingCandidateId,
    kMissingFrameTimestamp,
    kClockUnavailable,
    kClockRollback,
};

const char* ToString(CandidateTimingVerdict verdict);

struct CandidateTimingObservation {
    std::string candidate_idempotency_key;
    MonotonicNs frame_received_monotonic_ns = 0;
    MonotonicNs candidate_durable_monotonic_ns = 0;
    CandidateTimingVerdict verdict = CandidateTimingVerdict::kClockUnavailable;
    // Defined only when verdict == kMeasured. It is an integer to keep the
    // evidence canonical across C++/Python float renderers.
    std::int64_t candidate_latency_ns = 0;

    bool has_candidate_latency() const { return verdict == CandidateTimingVerdict::kMeasured; }
};

// Builds one observation from timestamps in the same process-local
// CLOCK_MONOTONIC domain. It never substitutes realtime UTC, frame sensor time,
// or a retry timestamp. Invalid ordering is typed rather than wrapped through
// signed subtraction.
CandidateTimingObservation MeasureCandidateDurability(
    const std::string& candidate_idempotency_key, MonotonicNs frame_received_monotonic_ns,
    MonotonicNs candidate_durable_monotonic_ns, bool idempotent_duplicate);

enum class EventTimingArtifactVerdict {
    kPersisted,
    kDuplicate,
    kSkippedDuplicate,
    kInvalidObservation,
    kStorageError,
};

const char* ToString(EventTimingArtifactVerdict verdict);

struct EventTimingArtifactResult {
    EventTimingArtifactVerdict verdict = EventTimingArtifactVerdict::kStorageError;
    StoredArtifact artifact;
};

// Persists one immutable, private HIL/replay artifact per *new* durable
// candidate. The artifact is intentionally not appended to the EventBundle
// evidence list after its SQLite transaction: doing so would weaken the
// candidate/evidence atomicity contract. HIL collects these private artifacts
// separately and the validator rejects missing/invalid samples.
class EventTimingArtifactWriter {
public:
    explicit EventTimingArtifactWriter(ArtifactVault* artifact_vault);

    EventTimingArtifactResult PersistCandidateTiming(const CandidateTimingObservation& observation) const;

private:
    ArtifactVault* artifact_vault_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_EVENT_TIMING_HPP

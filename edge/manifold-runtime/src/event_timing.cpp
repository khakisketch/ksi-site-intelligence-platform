#include "ksi/edge/event_timing.hpp"

#include "ksi/edge/crypto.hpp"

#include <sstream>
#include <stdexcept>

namespace ksi::edge {

namespace {

std::string EscapeJson(const std::string& value) {
    std::ostringstream output;
    for (const char character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (static_cast<unsigned char>(character) < 0x20U) {
                    constexpr char kHex[] = "0123456789abcdef";
                    const unsigned char byte = static_cast<unsigned char>(character);
                    output << "\\u00" << kHex[(byte >> 4U) & 0x0FU] << kHex[byte & 0x0FU];
                } else {
                    output << character;
                }
                break;
        }
    }
    return output.str();
}

bool IsPersisted(const ArtifactVaultResult& result) {
    return result.verdict == ArtifactVaultVerdict::kPersisted ||
           result.verdict == ArtifactVaultVerdict::kDuplicate;
}

std::string ArtifactIdFor(const CandidateTimingObservation& observation) {
    const std::string hash = Sha256Hex(
        reinterpret_cast<const std::uint8_t*>(observation.candidate_idempotency_key.data()),
        observation.candidate_idempotency_key.size());
    if (hash.size() != 64U) {
        return {};
    }
    return "event-timing-" + hash + ".json";
}

std::string BuildArtifactJson(const CandidateTimingObservation& observation) {
    if (observation.candidate_idempotency_key.empty() ||
        observation.verdict == CandidateTimingVerdict::kDuplicateNotMeasured ||
        observation.verdict == CandidateTimingVerdict::kMissingCandidateId) {
        return {};
    }
    std::ostringstream output;
    // Integer nanoseconds avoid a C++ floating-point representation at this
    // safety/replay boundary. The verifier recomputes latency from timestamps.
    output << "{\"candidateIdempotencyKey\":\""
           << EscapeJson(observation.candidate_idempotency_key) << "\",\"clockDomain\":\"CLOCK_MONOTONIC\"";
    if (observation.candidate_durable_monotonic_ns > 0) {
        output << ",\"candidateDurableMonotonicNs\":"
               << observation.candidate_durable_monotonic_ns;
    }
    if (observation.frame_received_monotonic_ns > 0) {
        output << ",\"frameReceivedMonotonicNs\":"
               << observation.frame_received_monotonic_ns;
    }
    if (observation.has_candidate_latency()) {
        output << ",\"candidateLatencyNs\":" << observation.candidate_latency_ns
               << ",\"measurementStatus\":\"MEASURED\"";
    } else {
        output << ",\"measurementStatus\":\"NOT_MEASURED\",\"reason\":\""
               << ToString(observation.verdict) << "\"";
    }
    output << ",\"schemaVersion\":\"1.0\",\"stage\":\"FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE\"}";
    return output.str();
}

}  // namespace

const char* ToString(CandidateTimingVerdict verdict) {
    switch (verdict) {
        case CandidateTimingVerdict::kMeasured:
            return "MEASURED";
        case CandidateTimingVerdict::kDuplicateNotMeasured:
            return "DUPLICATE_NOT_MEASURED";
        case CandidateTimingVerdict::kMissingCandidateId:
            return "MISSING_CANDIDATE_ID";
        case CandidateTimingVerdict::kMissingFrameTimestamp:
            return "MISSING_FRAME_TIMESTAMP";
        case CandidateTimingVerdict::kClockUnavailable:
            return "CLOCK_UNAVAILABLE";
        case CandidateTimingVerdict::kClockRollback:
            return "CLOCK_ROLLBACK";
    }
    return "UNKNOWN";
}

CandidateTimingObservation MeasureCandidateDurability(
    const std::string& candidate_idempotency_key, MonotonicNs frame_received_monotonic_ns,
    MonotonicNs candidate_durable_monotonic_ns, bool idempotent_duplicate) {
    CandidateTimingObservation result;
    result.candidate_idempotency_key = candidate_idempotency_key;
    result.frame_received_monotonic_ns = frame_received_monotonic_ns;
    result.candidate_durable_monotonic_ns = candidate_durable_monotonic_ns;
    if (candidate_idempotency_key.empty()) {
        result.verdict = CandidateTimingVerdict::kMissingCandidateId;
        return result;
    }
    if (idempotent_duplicate) {
        result.verdict = CandidateTimingVerdict::kDuplicateNotMeasured;
        return result;
    }
    if (frame_received_monotonic_ns <= 0) {
        result.verdict = CandidateTimingVerdict::kMissingFrameTimestamp;
        return result;
    }
    if (candidate_durable_monotonic_ns <= 0) {
        result.verdict = CandidateTimingVerdict::kClockUnavailable;
        return result;
    }
    if (candidate_durable_monotonic_ns < frame_received_monotonic_ns) {
        result.verdict = CandidateTimingVerdict::kClockRollback;
        return result;
    }
    result.verdict = CandidateTimingVerdict::kMeasured;
    result.candidate_latency_ns =
        candidate_durable_monotonic_ns - frame_received_monotonic_ns;
    return result;
}

const char* ToString(EventTimingArtifactVerdict verdict) {
    switch (verdict) {
        case EventTimingArtifactVerdict::kPersisted:
            return "PERSISTED";
        case EventTimingArtifactVerdict::kDuplicate:
            return "DUPLICATE";
        case EventTimingArtifactVerdict::kSkippedDuplicate:
            return "SKIPPED_DUPLICATE";
        case EventTimingArtifactVerdict::kInvalidObservation:
            return "INVALID_OBSERVATION";
        case EventTimingArtifactVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

EventTimingArtifactWriter::EventTimingArtifactWriter(ArtifactVault* artifact_vault)
    : artifact_vault_(artifact_vault) {
    if (artifact_vault_ == nullptr) {
        throw std::invalid_argument("event timing writer requires an artifact vault");
    }
}

EventTimingArtifactResult EventTimingArtifactWriter::PersistCandidateTiming(
    const CandidateTimingObservation& observation) const {
    if (observation.verdict == CandidateTimingVerdict::kDuplicateNotMeasured) {
        return {EventTimingArtifactVerdict::kSkippedDuplicate, {}};
    }
    const std::string artifact_id = ArtifactIdFor(observation);
    const std::string payload = BuildArtifactJson(observation);
    if (artifact_id.empty() || !ArtifactVault::IsSafeArtifactId(artifact_id) || payload.empty()) {
        return {EventTimingArtifactVerdict::kInvalidObservation, {}};
    }
    const ArtifactVaultResult stored = artifact_vault_->Persist(
        artifact_id, reinterpret_cast<const std::uint8_t*>(payload.data()), payload.size());
    if (!IsPersisted(stored)) {
        return {EventTimingArtifactVerdict::kStorageError, stored.artifact};
    }
    return {stored.verdict == ArtifactVaultVerdict::kPersisted
                ? EventTimingArtifactVerdict::kPersisted
                : EventTimingArtifactVerdict::kDuplicate,
            stored.artifact};
}

}  // namespace ksi::edge

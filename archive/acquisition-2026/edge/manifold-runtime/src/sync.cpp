#include "ksi/edge/sync.hpp"

#include <algorithm>
#include <map>
#include <stdexcept>
#include <set>
#include <vector>

namespace ksi::edge {

namespace {

bool SameCandidate(const CandidateEventRecord& left, const CandidateEventRecord& right) {
    return left.idempotency_key == right.idempotency_key &&
           left.device_sequence == right.device_sequence &&
           left.edge_device_id == right.edge_device_id &&
           left.payload_digest == right.payload_digest && left.payload_json == right.payload_json &&
           left.expected_evidence_count == right.expected_evidence_count;
}

bool CandidateOrder(const CandidateEventRecord& left, const CandidateEventRecord& right) {
    if (left.edge_device_id != right.edge_device_id) {
        return left.edge_device_id < right.edge_device_id;
    }
    if (left.device_sequence != right.device_sequence) {
        return left.device_sequence < right.device_sequence;
    }
    return left.idempotency_key < right.idempotency_key;
}

}  // namespace

const char* ToString(CoreSyncVerdict verdict) {
    switch (verdict) {
        case CoreSyncVerdict::kAcknowledged:
            return "ACKNOWLEDGED";
        case CoreSyncVerdict::kRetryableFailure:
            return "RETRYABLE_FAILURE";
        case CoreSyncVerdict::kPermanentFailure:
            return "PERMANENT_FAILURE";
    }
    return "UNKNOWN";
}

StoreForwardSyncDriver::StoreForwardSyncDriver(SqliteStoreForward* store_forward)
    : store_forward_(store_forward) {
    if (store_forward_ == nullptr) {
        throw std::invalid_argument("store-forward sync requires a journal");
    }
}

StoreForwardSyncReport StoreForwardSyncDriver::SynchronizeOnce(IEdgeCoreSyncTransport* transport) {
    StoreForwardSyncReport report;
    if (transport == nullptr || !store_forward_->is_open()) {
        report.verdict = CoreSyncVerdict::kRetryableFailure;
        report.store_verdict = StoreForwardVerdict::kBackendUnavailable;
        return report;
    }

    // Build one durable work list before issuing a request.  It contains both
    // unacknowledged candidates and candidates left midway through evidence
    // work by a process restart.  Processing each candidate to completion
    // before the next sequence closes a subtle hole in the former phase-based
    // implementation: it ACKed *all* candidates before an earlier candidate
    // had registered or uploaded any evidence.
    std::map<std::string, CandidateEventRecord> candidates_by_key;
    std::set<std::string> candidates_needing_ack;
    const auto add_candidate = [&](const CandidateEventRecord& candidate, bool needs_ack) {
        const auto [iterator, inserted] = candidates_by_key.emplace(candidate.idempotency_key, candidate);
        if (!inserted && !SameCandidate(iterator->second, candidate)) {
            return false;
        }
        if (needs_ack) {
            candidates_needing_ack.insert(candidate.idempotency_key);
        }
        return true;
    };
    for (const CandidateEventRecord& candidate : store_forward_->PendingCandidates()) {
        if (!add_candidate(candidate, true)) {
            report.verdict = CoreSyncVerdict::kRetryableFailure;
            report.store_verdict = StoreForwardVerdict::kStorageError;
            return report;
        }
    }
    const auto add_evidence_parent = [&](const EvidenceRecord& evidence) {
        CandidateEventRecord candidate;
        const StoreForwardVerdict found =
            store_forward_->FindCandidate(evidence.event_idempotency_key, &candidate);
        if (found != StoreForwardVerdict::kAccepted) {
            report.verdict = CoreSyncVerdict::kRetryableFailure;
            report.store_verdict = found;
            return false;
        }
        if (!add_candidate(candidate, false)) {
            report.verdict = CoreSyncVerdict::kRetryableFailure;
            report.store_verdict = StoreForwardVerdict::kStorageError;
            return false;
        }
        return true;
    };
    for (const EvidenceRecord& evidence : store_forward_->PendingEvidenceRegistration()) {
        if (!add_evidence_parent(evidence)) {
            return report;
        }
    }
    for (const EvidenceRecord& evidence : store_forward_->PendingEvidenceUpload()) {
        if (!add_evidence_parent(evidence)) {
            return report;
        }
    }

    std::vector<CandidateEventRecord> ordered_candidates;
    ordered_candidates.reserve(candidates_by_key.size());
    for (const auto& item : candidates_by_key) {
        ordered_candidates.push_back(item.second);
    }
    std::sort(ordered_candidates.begin(), ordered_candidates.end(), CandidateOrder);

    for (const CandidateEventRecord& candidate : ordered_candidates) {
        if (candidates_needing_ack.find(candidate.idempotency_key) != candidates_needing_ack.end()) {
            const CoreSyncVerdict result = transport->UploadCandidate(candidate);
            if (result != CoreSyncVerdict::kAcknowledged) {
                report.verdict = result;
                return report;
            }
            const StoreForwardVerdict acknowledged =
                store_forward_->AcknowledgeCandidate(candidate.idempotency_key);
            if (acknowledged != StoreForwardVerdict::kAccepted &&
                acknowledged != StoreForwardVerdict::kDuplicate) {
                report.verdict = CoreSyncVerdict::kRetryableFailure;
                report.store_verdict = acknowledged;
                return report;
            }
            ++report.candidates_acked;
        }

        // A process may have died after a registration ACK. Finish this old
        // evidence first; a new artifact of the same candidate (or a later
        // candidate) must not overtake the retry. Re-register only this same
        // candidate to get a fresh short-lived URL; URLs and headers remain
        // transient rather than becoming durable replay credentials.
        for (const EvidenceRecord& evidence : store_forward_->PendingEvidenceUpload()) {
            if (evidence.event_idempotency_key != candidate.idempotency_key) {
                continue;
            }
            const EvidenceRegistrationResult registration =
                transport->RegisterEvidence(candidate, evidence);
            if (registration.verdict != CoreSyncVerdict::kAcknowledged) {
                report.verdict = registration.verdict;
                return report;
            }
            if (registration.upload_url.empty() || registration.required_upload_headers.empty()) {
                report.verdict = CoreSyncVerdict::kPermanentFailure;
                return report;
            }
            const CoreSyncVerdict put = transport->PutEvidence(evidence, registration);
            if (put != CoreSyncVerdict::kAcknowledged) {
                report.verdict = put;
                return report;
            }
            const StoreForwardVerdict completed =
                store_forward_->MarkEvidencePutComplete(evidence.event_idempotency_key,
                                                        evidence.artifact_id);
            if (completed != StoreForwardVerdict::kAccepted &&
                completed != StoreForwardVerdict::kDuplicate) {
                report.verdict = CoreSyncVerdict::kRetryableFailure;
                report.store_verdict = completed;
                return report;
            }
            ++report.puts_acked;
        }

        // Only after interrupted evidence is complete do new registrations
        // become durable and receive their matching PUT. The pending query is
        // refreshed per candidate so a later candidate cannot overtake this
        // candidate while any registration/PUT retry remains.
        for (const EvidenceRecord& evidence : store_forward_->PendingEvidenceRegistration()) {
            if (evidence.event_idempotency_key != candidate.idempotency_key) {
                continue;
            }
            const EvidenceRegistrationResult registration =
                transport->RegisterEvidence(candidate, evidence);
            if (registration.verdict != CoreSyncVerdict::kAcknowledged) {
                report.verdict = registration.verdict;
                return report;
            }
            if (registration.upload_url.empty() || registration.required_upload_headers.empty()) {
                // Never substitute a client-selected object path when Core fails to
                // return the authenticated upload capability. A bare URL is also
                // unsafe: the checksum header is part of the signed capability.
                report.verdict = CoreSyncVerdict::kPermanentFailure;
                return report;
            }
            const StoreForwardVerdict registered =
                store_forward_->MarkEvidenceRegistered(evidence.event_idempotency_key,
                                                        evidence.artifact_id);
            if (registered != StoreForwardVerdict::kAccepted &&
                registered != StoreForwardVerdict::kDuplicate) {
                report.verdict = CoreSyncVerdict::kRetryableFailure;
                report.store_verdict = registered;
                return report;
            }
            ++report.registrations_acked;
            const CoreSyncVerdict put = transport->PutEvidence(evidence, registration);
            if (put != CoreSyncVerdict::kAcknowledged) {
                report.verdict = put;
                return report;
            }
            const StoreForwardVerdict completed =
                store_forward_->MarkEvidencePutComplete(evidence.event_idempotency_key,
                                                        evidence.artifact_id);
            if (completed != StoreForwardVerdict::kAccepted &&
                completed != StoreForwardVerdict::kDuplicate) {
                report.verdict = CoreSyncVerdict::kRetryableFailure;
                report.store_verdict = completed;
                return report;
            }
            ++report.puts_acked;
        }
    }
    const StoreForwardVerdict pruned = store_forward_->PruneCompleted();
    if (pruned != StoreForwardVerdict::kAccepted) {
        report.verdict = CoreSyncVerdict::kRetryableFailure;
        report.store_verdict = pruned;
    }
    return report;
}

}  // namespace ksi::edge

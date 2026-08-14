// Transport-independent driver for the durable Edge→Core sync order.

#ifndef KSI_EDGE_SYNC_HPP
#define KSI_EDGE_SYNC_HPP

#include <cstddef>
#include <map>
#include <string>

#include "ksi/edge/store_forward.hpp"

namespace ksi::edge {

enum class CoreSyncVerdict {
    kAcknowledged,
    kRetryableFailure,
    kPermanentFailure,
};

const char* ToString(CoreSyncVerdict verdict);

// Core owns remote object names and creates a short-lived, device-bound upload
// URL only after it has authenticated the candidate/evidence relationship.
// URLs are intentionally not persisted in SQLite: a restart re-registers the
// evidence and gets a fresh URL rather than replaying a stale bearer URL.
struct EvidenceRegistrationResult {
    CoreSyncVerdict verdict = CoreSyncVerdict::kRetryableFailure;
    std::string upload_url;
    // Core returns checksum-bound headers as part of the bearer capability.
    // They are deliberately transient (like the URL) but must travel with the
    // PUT; substituting a client-computed header would weaken the binding.
    std::map<std::string, std::string> required_upload_headers;
};

// HTTPS/auth belongs in the app adapter.  Keeping it out of the journal means
// unit/replay tests can prove ordering and restart semantics without network
// credentials or a live Core.
class IEdgeCoreSyncTransport {
public:
    virtual ~IEdgeCoreSyncTransport() = default;
    virtual CoreSyncVerdict UploadCandidate(const CandidateEventRecord& candidate) = 0;
    // Evidence registration needs the acknowledged candidate context to derive
    // Core's device-scoped eventKey.  An idempotency key is deliberately not
    // assumed to be an EventBundle eventId.
    virtual EvidenceRegistrationResult RegisterEvidence(const CandidateEventRecord& candidate,
                                                        const EvidenceRecord& evidence) = 0;
    virtual CoreSyncVerdict PutEvidence(const EvidenceRecord& evidence,
                                        const EvidenceRegistrationResult& registration) = 0;
};

struct StoreForwardSyncReport {
    CoreSyncVerdict verdict = CoreSyncVerdict::kAcknowledged;
    std::size_t candidates_acked = 0;
    std::size_t registrations_acked = 0;
    std::size_t puts_acked = 0;
    StoreForwardVerdict store_verdict = StoreForwardVerdict::kAccepted;
};

class StoreForwardSyncDriver {
public:
    explicit StoreForwardSyncDriver(SqliteStoreForward* store_forward);

    // Stops at the first transport failure. For every device sequence it
    // completes Candidate ACK -> evidence registration -> PUT before sending
    // the next candidate, which keeps retries deterministic and never lets a
    // later candidate overtake an earlier candidate's outstanding evidence.
    // It also never prunes a candidate merely because a later operation
    // succeeded.
    StoreForwardSyncReport SynchronizeOnce(IEdgeCoreSyncTransport* transport);

private:
    SqliteStoreForward* store_forward_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_SYNC_HPP

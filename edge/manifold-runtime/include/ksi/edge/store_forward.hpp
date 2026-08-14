// SQLite WAL store-and-forward journal for Edge→Core candidate/evidence sync.

// The state transition is deliberately asymmetric:
//  durable local evidence plan -> Candidate EventBundle ACK -> Core evidence
//  registration -> PUT -> completion -> prune.
// The local plan is allowed before the ACK so a process restart cannot lose the
// artifact list, but a Core registration is impossible before the Candidate
// EventBundle has a durable ACK.  An ACK alone never deletes a candidate when
// planned evidence is outstanding.

#ifndef KSI_EDGE_STORE_FORWARD_HPP
#define KSI_EDGE_STORE_FORWARD_HPP

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace ksi::edge {

enum class StoreForwardVerdict {
    kAccepted,
    kDuplicate,
    kConflict,
    kNotFound,
    kAwaitingCandidateAck,
    kAwaitingEvidenceRegistration,
    kEvidencePlanOverflow,
    kBackendUnavailable,
    kStorageError,
};

const char* ToString(StoreForwardVerdict verdict);

struct CandidateEventRecord {
    std::string idempotency_key;
    std::int64_t device_sequence = 0;
    std::string edge_device_id;
    std::string payload_digest;
    std::string payload_json;
    std::uint32_t expected_evidence_count = 0;
};

struct EvidenceRecord {
    std::string event_idempotency_key;
    std::string artifact_id;
    std::string content_type;
    // Local immutable artifact path, not the Core object key.  Core derives the
    // remote object key after it has authenticated device ownership; accepting a
    // client-selected remote key would reopen cross-event/path traversal risk.
    std::string local_path;
    std::string content_digest;
};

class SqliteStoreForward {
public:
    explicit SqliteStoreForward(std::string database_path);
    ~SqliteStoreForward();
    SqliteStoreForward(const SqliteStoreForward&) = delete;
    SqliteStoreForward& operator=(const SqliteStoreForward&) = delete;

    StoreForwardVerdict Open();
    bool is_open() const;
    static bool sqlite_backend_compiled();

    StoreForwardVerdict EnqueueCandidate(const CandidateEventRecord& record);
    // Atomically persists a candidate and its local evidence plan.  A power loss
    // between those two facts would otherwise leave an ACK-able candidate with
    // an unrecoverable incomplete artifact plan.
    StoreForwardVerdict EnqueueCandidateWithEvidence(const CandidateEventRecord& record,
                                                      const std::vector<EvidenceRecord>& evidence);
    StoreForwardVerdict AcknowledgeCandidate(const std::string& idempotency_key);
    // Persist an artifact plan before sending it to Core.  This does not make a
    // network call and is safe before the Candidate EventBundle ACK.
    StoreForwardVerdict PlanEvidence(const EvidenceRecord& record);
    // Records that Core accepted the device-owned evidence registration/URL.
    // It is forbidden until the Candidate EventBundle ACK is durable.
    StoreForwardVerdict MarkEvidenceRegistered(const std::string& event_idempotency_key,
                                                const std::string& artifact_id);
    StoreForwardVerdict MarkEvidencePutComplete(const std::string& event_idempotency_key,
                                                const std::string& artifact_id);
    // Called by the single pipeline worker before it builds a CandidateEvent.
    // It derives the next durable sequence after restart; the subsequent atomic
    // enqueue remains the authority and rejects a concurrent collision.
    StoreForwardVerdict NextDeviceSequence(const std::string& edge_device_id,
                                           std::int64_t* next_sequence) const;
    // Resolves an evidence plan's stable idempotency key back to its durable
    // Candidate EventBundle.  The sync driver uses this rather than assuming
    // the idempotency key equals EventBundle.eventId.
    StoreForwardVerdict FindCandidate(const std::string& idempotency_key,
                                      CandidateEventRecord* record) const;
    std::vector<CandidateEventRecord> PendingCandidates() const;
    std::vector<EvidenceRecord> PendingEvidenceRegistration() const;
    std::vector<EvidenceRecord> PendingEvidenceUpload() const;
    StoreForwardVerdict PruneCompleted();
    std::size_t CandidateCount() const;

private:
    StoreForwardVerdict InitializeLocked();
    void CloseLocked();

    const std::string database_path_;
    mutable std::mutex mutex_;
    void* database_ = nullptr;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_STORE_FORWARD_HPP

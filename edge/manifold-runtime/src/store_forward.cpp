#include "ksi/edge/store_forward.hpp"

#include "ksi/edge/crypto.hpp"

#include <limits>
#include <map>
#include <utility>

#if KSI_EDGE_HAVE_SQLITE
#include <sqlite3.h>
#endif

namespace ksi::edge {

namespace {

struct EvidenceIdentity {
    std::string content_type;
    std::string local_path;
    std::string content_digest;

    bool operator==(const EvidenceIdentity& other) const {
        return content_type == other.content_type && local_path == other.local_path &&
               content_digest == other.content_digest;
    }
};

#if KSI_EDGE_HAVE_SQLITE
std::string ColumnText(sqlite3_stmt* statement, int column) {
    const auto* value = sqlite3_column_text(statement, column);
    return value == nullptr ? std::string{} : reinterpret_cast<const char*>(value);
}
#endif

}  // namespace

const char* ToString(StoreForwardVerdict verdict) {
    switch (verdict) {
        case StoreForwardVerdict::kAccepted:
            return "ACCEPTED";
        case StoreForwardVerdict::kDuplicate:
            return "DUPLICATE";
        case StoreForwardVerdict::kConflict:
            return "CONFLICT";
        case StoreForwardVerdict::kNotFound:
            return "NOT_FOUND";
        case StoreForwardVerdict::kAwaitingCandidateAck:
            return "AWAITING_CANDIDATE_ACK";
        case StoreForwardVerdict::kAwaitingEvidenceRegistration:
            return "AWAITING_EVIDENCE_REGISTRATION";
        case StoreForwardVerdict::kEvidencePlanOverflow:
            return "EVIDENCE_PLAN_OVERFLOW";
        case StoreForwardVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case StoreForwardVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

SqliteStoreForward::SqliteStoreForward(std::string database_path)
    : database_path_(std::move(database_path)) {}

SqliteStoreForward::~SqliteStoreForward() {
    std::lock_guard<std::mutex> lock(mutex_);
    CloseLocked();
}

bool SqliteStoreForward::sqlite_backend_compiled() {
#if KSI_EDGE_HAVE_SQLITE
    return true;
#else
    return false;
#endif
}

bool SqliteStoreForward::is_open() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return database_ != nullptr;
}

StoreForwardVerdict SqliteStoreForward::Open() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (database_ != nullptr) {
        return StoreForwardVerdict::kAccepted;
    }
    return InitializeLocked();
}

void SqliteStoreForward::CloseLocked() {
#if KSI_EDGE_HAVE_SQLITE
    if (database_ != nullptr) {
        (void)sqlite3_close(static_cast<sqlite3*>(database_));
        database_ = nullptr;
    }
#else
    database_ = nullptr;
#endif
}

StoreForwardVerdict SqliteStoreForward::InitializeLocked() {
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    sqlite3* database = nullptr;
    if (sqlite3_open_v2(database_path_.c_str(), &database,
                        SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                        nullptr) != SQLITE_OK) {
        if (database != nullptr) {
            (void)sqlite3_close(database);
        }
        return StoreForwardVerdict::kStorageError;
    }
    const char* schema =
        "PRAGMA journal_mode=WAL;"
        "PRAGMA synchronous=FULL;"
        "PRAGMA foreign_keys=ON;"
        "CREATE TABLE IF NOT EXISTS candidate_events ("
        " idempotency_key TEXT PRIMARY KEY,"
        " device_sequence INTEGER NOT NULL,"
        " edge_device_id TEXT NOT NULL,"
        " payload_digest TEXT NOT NULL,"
        " payload_json TEXT NOT NULL,"
        " expected_evidence_count INTEGER NOT NULL CHECK(expected_evidence_count >= 0),"
        " core_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK(core_acknowledged IN (0,1)),"
        " UNIQUE(edge_device_id, device_sequence)"
        ");"
        "CREATE TABLE IF NOT EXISTS evidence_uploads ("
        " event_idempotency_key TEXT NOT NULL,"
        " artifact_id TEXT NOT NULL,"
        " content_type TEXT NOT NULL,"
        " local_path TEXT NOT NULL,"
        " content_digest TEXT NOT NULL,"
        " core_registered INTEGER NOT NULL DEFAULT 0 CHECK(core_registered IN (0,1)),"
        " put_complete INTEGER NOT NULL DEFAULT 0 CHECK(put_complete IN (0,1)),"
        " PRIMARY KEY(event_idempotency_key, artifact_id),"
        " FOREIGN KEY(event_idempotency_key) REFERENCES candidate_events(idempotency_key)"
        "   ON DELETE CASCADE"
        ");";
    char* error = nullptr;
    if (sqlite3_exec(database, schema, nullptr, nullptr, &error) != SQLITE_OK) {
        sqlite3_free(error);
        (void)sqlite3_close(database);
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_busy_timeout(database, 2'000);
    database_ = database;
    return StoreForwardVerdict::kAccepted;
#endif
}

StoreForwardVerdict SqliteStoreForward::EnqueueCandidate(const CandidateEventRecord& record) {
    if (record.idempotency_key.empty() || record.device_sequence < 0 || record.edge_device_id.empty() ||
        !IsSha256Digest(record.payload_digest) || record.payload_json.empty() ||
        record.expected_evidence_count > static_cast<std::uint32_t>(std::numeric_limits<int>::max())) {
        return StoreForwardVerdict::kConflict;
    }
    // Any non-empty evidence plan must be persisted atomically with its
    // candidate.  Direct callers that need artifacts therefore use
    // EnqueueCandidateWithEvidence(), rather than create a candidate that a
    // crash could ACK before its artifacts are durable.
    if (record.expected_evidence_count != 0U) {
        return StoreForwardVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* existing = nullptr;
    const char* lookup_sql =
        "SELECT device_sequence, edge_device_id, payload_digest, payload_json, expected_evidence_count "
        "FROM candidate_events WHERE idempotency_key=?1";
    if (sqlite3_prepare_v2(database, lookup_sql, -1, &existing, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, record.idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    const int lookup_step = sqlite3_step(existing);
    if (lookup_step == SQLITE_ROW) {
        const bool same =
            sqlite3_column_int64(existing, 0) == record.device_sequence &&
            record.edge_device_id == ColumnText(existing, 1) &&
            record.payload_digest == ColumnText(existing, 2) &&
            record.payload_json == ColumnText(existing, 3) &&
            sqlite3_column_int(existing, 4) == static_cast<int>(record.expected_evidence_count);
        (void)sqlite3_finalize(existing);
        return same ? StoreForwardVerdict::kDuplicate : StoreForwardVerdict::kConflict;
    }
    if (lookup_step != SQLITE_DONE) {
        (void)sqlite3_finalize(existing);
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_finalize(existing);

    sqlite3_stmt* sequence = nullptr;
    const char* sequence_sql = "SELECT idempotency_key FROM candidate_events "
                               "WHERE edge_device_id=?1 AND device_sequence=?2";
    if (sqlite3_prepare_v2(database, sequence_sql, -1, &sequence, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(sequence, 1, record.edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(sequence, 2, record.device_sequence);
    const int sequence_step = sqlite3_step(sequence);
    (void)sqlite3_finalize(sequence);
    if (sequence_step == SQLITE_ROW) {
        return StoreForwardVerdict::kConflict;
    }
    if (sequence_step != SQLITE_DONE) {
        return StoreForwardVerdict::kStorageError;
    }

    sqlite3_stmt* insert = nullptr;
    const char* insert_sql =
        "INSERT INTO candidate_events(idempotency_key,device_sequence,edge_device_id,payload_digest,"
        "payload_json,expected_evidence_count) VALUES(?1,?2,?3,?4,?5,?6)";
    if (sqlite3_prepare_v2(database, insert_sql, -1, &insert, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(insert, 1, record.idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(insert, 2, record.device_sequence);
    (void)sqlite3_bind_text(insert, 3, record.edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 4, record.payload_digest.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 5, record.payload_json.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int(insert, 6, static_cast<int>(record.expected_evidence_count));
    const int step = sqlite3_step(insert);
    (void)sqlite3_finalize(insert);
    return step == SQLITE_DONE ? StoreForwardVerdict::kAccepted : StoreForwardVerdict::kStorageError;
#endif
}

StoreForwardVerdict SqliteStoreForward::EnqueueCandidateWithEvidence(
    const CandidateEventRecord& record, const std::vector<EvidenceRecord>& evidence) {
    if (record.idempotency_key.empty() || record.device_sequence < 0 || record.edge_device_id.empty() ||
        !IsSha256Digest(record.payload_digest) || record.payload_json.empty() ||
        record.expected_evidence_count != evidence.size() ||
        record.expected_evidence_count > static_cast<std::uint32_t>(std::numeric_limits<int>::max())) {
        return StoreForwardVerdict::kConflict;
    }
    std::map<std::string, EvidenceIdentity> expected_evidence;
    for (const EvidenceRecord& item : evidence) {
        if (item.event_idempotency_key != record.idempotency_key || item.artifact_id.empty() ||
            item.content_type.empty() || item.local_path.empty() || !IsSha256Digest(item.content_digest) ||
            !expected_evidence.emplace(item.artifact_id,
                                        EvidenceIdentity{item.content_type, item.local_path,
                                                         item.content_digest})
                 .second) {
            return StoreForwardVerdict::kConflict;
        }
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    char* begin_error = nullptr;
    if (sqlite3_exec(database, "BEGIN IMMEDIATE", nullptr, nullptr, &begin_error) != SQLITE_OK) {
        sqlite3_free(begin_error);
        return StoreForwardVerdict::kStorageError;
    }
    const auto rollback = [database]() { (void)sqlite3_exec(database, "ROLLBACK", nullptr, nullptr, nullptr); };
    const auto commit = [database]() {
        return sqlite3_exec(database, "COMMIT", nullptr, nullptr, nullptr) == SQLITE_OK;
    };

    sqlite3_stmt* existing = nullptr;
    const char* lookup_sql =
        "SELECT device_sequence,edge_device_id,payload_digest,payload_json,expected_evidence_count "
        "FROM candidate_events WHERE idempotency_key=?1";
    if (sqlite3_prepare_v2(database, lookup_sql, -1, &existing, nullptr) != SQLITE_OK) {
        rollback();
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, record.idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    const int existing_step = sqlite3_step(existing);
    if (existing_step == SQLITE_ROW) {
        const bool same_candidate =
            sqlite3_column_int64(existing, 0) == record.device_sequence &&
            ColumnText(existing, 1) == record.edge_device_id &&
            ColumnText(existing, 2) == record.payload_digest &&
            ColumnText(existing, 3) == record.payload_json &&
            sqlite3_column_int(existing, 4) == static_cast<int>(record.expected_evidence_count);
        (void)sqlite3_finalize(existing);
        if (!same_candidate) {
            rollback();
            return StoreForwardVerdict::kConflict;
        }
        sqlite3_stmt* planned = nullptr;
        const char* planned_sql = "SELECT artifact_id,content_type,local_path,content_digest FROM evidence_uploads "
                                  "WHERE event_idempotency_key=?1";
        if (sqlite3_prepare_v2(database, planned_sql, -1, &planned, nullptr) != SQLITE_OK) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        (void)sqlite3_bind_text(planned, 1, record.idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
        std::map<std::string, EvidenceIdentity> existing_evidence;
        int planned_step = SQLITE_ROW;
        while ((planned_step = sqlite3_step(planned)) == SQLITE_ROW) {
            const std::string artifact_id = ColumnText(planned, 0);
            const auto inserted = existing_evidence.emplace(
                artifact_id,
                EvidenceIdentity{ColumnText(planned, 1), ColumnText(planned, 2),
                                 ColumnText(planned, 3)});
            if (!inserted.second) {
                (void)sqlite3_finalize(planned);
                rollback();
                return StoreForwardVerdict::kStorageError;
            }
        }
        (void)sqlite3_finalize(planned);
        if (planned_step != SQLITE_DONE) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        for (const auto& existing_item : existing_evidence) {
            const auto expected_item = expected_evidence.find(existing_item.first);
            if (expected_item == expected_evidence.end() ||
                !(expected_item->second == existing_item.second)) {
                rollback();
                return StoreForwardVerdict::kConflict;
            }
        }
        if (existing_evidence == expected_evidence) {
            if (!commit()) {
                rollback();
                return StoreForwardVerdict::kStorageError;
            }
            return StoreForwardVerdict::kDuplicate;
        }
        // A previous process may have died after writing the candidate but before
        // all of its planned artifacts.  Complete the matching subset atomically
        // before the candidate can appear in PendingCandidates().
    } else if (existing_step == SQLITE_DONE) {
        (void)sqlite3_finalize(existing);
        sqlite3_stmt* sequence = nullptr;
        const char* sequence_sql = "SELECT 1 FROM candidate_events WHERE edge_device_id=?1 "
                                   "AND device_sequence=?2";
        if (sqlite3_prepare_v2(database, sequence_sql, -1, &sequence, nullptr) != SQLITE_OK) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        (void)sqlite3_bind_text(sequence, 1, record.edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_int64(sequence, 2, record.device_sequence);
        const int sequence_step = sqlite3_step(sequence);
        (void)sqlite3_finalize(sequence);
        if (sequence_step == SQLITE_ROW) {
            rollback();
            return StoreForwardVerdict::kConflict;
        }
        if (sequence_step != SQLITE_DONE) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        sqlite3_stmt* insert_candidate = nullptr;
        const char* candidate_sql =
            "INSERT INTO candidate_events(idempotency_key,device_sequence,edge_device_id,payload_digest,"
            "payload_json,expected_evidence_count) VALUES(?1,?2,?3,?4,?5,?6)";
        if (sqlite3_prepare_v2(database, candidate_sql, -1, &insert_candidate, nullptr) != SQLITE_OK) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        (void)sqlite3_bind_text(insert_candidate, 1, record.idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_int64(insert_candidate, 2, record.device_sequence);
        (void)sqlite3_bind_text(insert_candidate, 3, record.edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_candidate, 4, record.payload_digest.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_candidate, 5, record.payload_json.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_int(insert_candidate, 6, static_cast<int>(record.expected_evidence_count));
        const int insert_step = sqlite3_step(insert_candidate);
        (void)sqlite3_finalize(insert_candidate);
        if (insert_step != SQLITE_DONE) {
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
    } else {
        (void)sqlite3_finalize(existing);
        rollback();
        return StoreForwardVerdict::kStorageError;
    }

    sqlite3_stmt* insert_evidence = nullptr;
    const char* evidence_sql = "INSERT OR IGNORE INTO evidence_uploads(event_idempotency_key,artifact_id,"
                               "content_type,local_path,content_digest) VALUES(?1,?2,?3,?4,?5)";
    if (sqlite3_prepare_v2(database, evidence_sql, -1, &insert_evidence, nullptr) != SQLITE_OK) {
        rollback();
        return StoreForwardVerdict::kStorageError;
    }
    for (const EvidenceRecord& item : evidence) {
        if (sqlite3_reset(insert_evidence) != SQLITE_OK || sqlite3_clear_bindings(insert_evidence) != SQLITE_OK) {
            (void)sqlite3_finalize(insert_evidence);
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
        (void)sqlite3_bind_text(insert_evidence, 1, item.event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_evidence, 2, item.artifact_id.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_evidence, 3, item.content_type.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_evidence, 4, item.local_path.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(insert_evidence, 5, item.content_digest.c_str(), -1, SQLITE_TRANSIENT);
        if (sqlite3_step(insert_evidence) != SQLITE_DONE) {
            (void)sqlite3_finalize(insert_evidence);
            rollback();
            return StoreForwardVerdict::kStorageError;
        }
    }
    (void)sqlite3_finalize(insert_evidence);
    if (!commit()) {
        rollback();
        return StoreForwardVerdict::kStorageError;
    }
    return StoreForwardVerdict::kAccepted;
#endif
}

StoreForwardVerdict SqliteStoreForward::AcknowledgeCandidate(const std::string& idempotency_key) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)idempotency_key;
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* existing = nullptr;
    if (sqlite3_prepare_v2(database, "SELECT core_acknowledged,expected_evidence_count,"
                                     "(SELECT count(*) FROM evidence_uploads WHERE "
                                     "event_idempotency_key=candidate_events.idempotency_key) "
                                     "FROM candidate_events "
                                     "WHERE idempotency_key=?1", -1, &existing, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(existing) != SQLITE_ROW) {
        (void)sqlite3_finalize(existing);
        return StoreForwardVerdict::kNotFound;
    }
    const bool already_acknowledged = sqlite3_column_int(existing, 0) != 0;
    const int expected_evidence_count = sqlite3_column_int(existing, 1);
    const int planned_evidence_count = sqlite3_column_int(existing, 2);
    (void)sqlite3_finalize(existing);
    if (expected_evidence_count != planned_evidence_count) {
        return StoreForwardVerdict::kConflict;
    }
    if (already_acknowledged) {
        return StoreForwardVerdict::kDuplicate;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE candidate_events SET core_acknowledged=1 WHERE idempotency_key=?1";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    if (step != SQLITE_DONE) {
        return StoreForwardVerdict::kStorageError;
    }
    return StoreForwardVerdict::kAccepted;
#endif
}

StoreForwardVerdict SqliteStoreForward::PlanEvidence(const EvidenceRecord& record) {
    if (record.event_idempotency_key.empty() || record.artifact_id.empty() || record.content_type.empty() ||
        record.local_path.empty() || !IsSha256Digest(record.content_digest)) {
        return StoreForwardVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* capacity = nullptr;
    const char* capacity_sql =
        "SELECT expected_evidence_count,(SELECT count(*) FROM evidence_uploads WHERE "
        "event_idempotency_key=?1) FROM candidate_events WHERE idempotency_key=?1";
    if (sqlite3_prepare_v2(database, capacity_sql, -1, &capacity, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(capacity, 1, record.event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(capacity) != SQLITE_ROW) {
        (void)sqlite3_finalize(capacity);
        return StoreForwardVerdict::kNotFound;
    }
    const int expected = sqlite3_column_int(capacity, 0);
    const int count = sqlite3_column_int(capacity, 1);
    (void)sqlite3_finalize(capacity);

    sqlite3_stmt* existing = nullptr;
    const char* existing_sql = "SELECT content_type,local_path,content_digest FROM evidence_uploads "
                               "WHERE event_idempotency_key=?1 AND artifact_id=?2";
    if (sqlite3_prepare_v2(database, existing_sql, -1, &existing, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, record.event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(existing, 2, record.artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(existing) == SQLITE_ROW) {
        const bool same =
            record.content_type == ColumnText(existing, 0) && record.local_path == ColumnText(existing, 1) &&
            record.content_digest == ColumnText(existing, 2);
        (void)sqlite3_finalize(existing);
        return same ? StoreForwardVerdict::kDuplicate : StoreForwardVerdict::kConflict;
    }
    (void)sqlite3_finalize(existing);
    if (count >= expected) {
        return StoreForwardVerdict::kEvidencePlanOverflow;
    }
    sqlite3_stmt* insert = nullptr;
    const char* insert_sql = "INSERT INTO evidence_uploads(event_idempotency_key,artifact_id,content_type,"
                             "local_path,content_digest) VALUES(?1,?2,?3,?4,?5)";
    if (sqlite3_prepare_v2(database, insert_sql, -1, &insert, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(insert, 1, record.event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 2, record.artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 3, record.content_type.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 4, record.local_path.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 5, record.content_digest.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(insert);
    (void)sqlite3_finalize(insert);
    return step == SQLITE_DONE ? StoreForwardVerdict::kAccepted : StoreForwardVerdict::kStorageError;
#endif
}

StoreForwardVerdict SqliteStoreForward::MarkEvidenceRegistered(
    const std::string& event_idempotency_key, const std::string& artifact_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)event_idempotency_key;
    (void)artifact_id;
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* existing = nullptr;
    const char* existing_sql =
        "SELECT c.core_acknowledged,e.core_registered FROM evidence_uploads e "
        "JOIN candidate_events c ON c.idempotency_key=e.event_idempotency_key "
        "WHERE e.event_idempotency_key=?1 AND e.artifact_id=?2";
    if (sqlite3_prepare_v2(database, existing_sql, -1, &existing, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(existing, 2, artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(existing) != SQLITE_ROW) {
        (void)sqlite3_finalize(existing);
        return StoreForwardVerdict::kNotFound;
    }
    const bool candidate_acknowledged = sqlite3_column_int(existing, 0) != 0;
    const bool already_registered = sqlite3_column_int(existing, 1) != 0;
    (void)sqlite3_finalize(existing);
    if (!candidate_acknowledged) {
        return StoreForwardVerdict::kAwaitingCandidateAck;
    }
    if (already_registered) {
        return StoreForwardVerdict::kDuplicate;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE evidence_uploads SET core_registered=1 WHERE "
                      "event_idempotency_key=?1 AND artifact_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? StoreForwardVerdict::kAccepted : StoreForwardVerdict::kStorageError;
#endif
}

StoreForwardVerdict SqliteStoreForward::MarkEvidencePutComplete(
    const std::string& event_idempotency_key, const std::string& artifact_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)event_idempotency_key;
    (void)artifact_id;
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* existing = nullptr;
    if (sqlite3_prepare_v2(database, "SELECT core_registered,put_complete FROM evidence_uploads "
                                     "WHERE event_idempotency_key=?1 AND artifact_id=?2", -1,
                           &existing, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(existing, 2, artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(existing) != SQLITE_ROW) {
        (void)sqlite3_finalize(existing);
        return StoreForwardVerdict::kNotFound;
    }
    const bool registered = sqlite3_column_int(existing, 0) != 0;
    const bool already_complete = sqlite3_column_int(existing, 1) != 0;
    (void)sqlite3_finalize(existing);
    if (!registered) {
        return StoreForwardVerdict::kAwaitingEvidenceRegistration;
    }
    if (already_complete) {
        return StoreForwardVerdict::kDuplicate;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE evidence_uploads SET put_complete=1 WHERE event_idempotency_key=?1 "
                      "AND artifact_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, event_idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    if (step != SQLITE_DONE) {
        return StoreForwardVerdict::kStorageError;
    }
    return StoreForwardVerdict::kAccepted;
#endif
}

StoreForwardVerdict SqliteStoreForward::NextDeviceSequence(const std::string& edge_device_id,
                                                            std::int64_t* next_sequence) const {
    if (edge_device_id.empty() || next_sequence == nullptr) {
        return StoreForwardVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "SELECT max(device_sequence) FROM candidate_events WHERE edge_device_id=?1";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(statement) != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return StoreForwardVerdict::kStorageError;
    }
    if (sqlite3_column_type(statement, 0) == SQLITE_NULL) {
        *next_sequence = 0;
    } else {
        const std::int64_t previous = sqlite3_column_int64(statement, 0);
        if (previous < 0 || previous == std::numeric_limits<std::int64_t>::max()) {
            (void)sqlite3_finalize(statement);
            return StoreForwardVerdict::kConflict;
        }
        *next_sequence = previous + 1;
    }
    (void)sqlite3_finalize(statement);
    return StoreForwardVerdict::kAccepted;
#endif
}

std::vector<CandidateEventRecord> SqliteStoreForward::PendingCandidates() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<CandidateEventRecord> records;
#if KSI_EDGE_HAVE_SQLITE
    if (database_ == nullptr) {
        return records;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "SELECT idempotency_key,device_sequence,edge_device_id,payload_digest,payload_json,"
                      "expected_evidence_count FROM candidate_events WHERE core_acknowledged=0 "
                      "AND expected_evidence_count=(SELECT count(*) FROM evidence_uploads "
                      "WHERE event_idempotency_key=candidate_events.idempotency_key) "
                      "ORDER BY edge_device_id,device_sequence";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return records;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        records.push_back({ColumnText(statement, 0),
                           sqlite3_column_int64(statement, 1),
                           ColumnText(statement, 2), ColumnText(statement, 3),
                           ColumnText(statement, 4),
                           static_cast<std::uint32_t>(sqlite3_column_int(statement, 5))});
    }
    (void)sqlite3_finalize(statement);
#endif
    return records;
}

StoreForwardVerdict SqliteStoreForward::FindCandidate(const std::string& idempotency_key,
                                                       CandidateEventRecord* record) const {
    if (idempotency_key.empty() || record == nullptr) {
        return StoreForwardVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT idempotency_key,device_sequence,edge_device_id,payload_digest,payload_json,"
        "expected_evidence_count FROM candidate_events WHERE idempotency_key=?1";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return StoreForwardVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, idempotency_key.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(statement) != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return StoreForwardVerdict::kNotFound;
    }
    *record = {ColumnText(statement, 0), sqlite3_column_int64(statement, 1),
               ColumnText(statement, 2), ColumnText(statement, 3), ColumnText(statement, 4),
               static_cast<std::uint32_t>(sqlite3_column_int(statement, 5))};
    (void)sqlite3_finalize(statement);
    return StoreForwardVerdict::kAccepted;
#endif
}

std::vector<EvidenceRecord> SqliteStoreForward::PendingEvidenceRegistration() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<EvidenceRecord> records;
#if KSI_EDGE_HAVE_SQLITE
    if (database_ == nullptr) {
        return records;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT e.event_idempotency_key,e.artifact_id,e.content_type,e.local_path,e.content_digest "
        "FROM evidence_uploads e JOIN candidate_events c ON c.idempotency_key=e.event_idempotency_key "
        "WHERE c.core_acknowledged=1 AND e.core_registered=0 "
        "ORDER BY c.edge_device_id,c.device_sequence,e.artifact_id";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return records;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        records.push_back({ColumnText(statement, 0), ColumnText(statement, 1),
                           ColumnText(statement, 2), ColumnText(statement, 3),
                           ColumnText(statement, 4)});
    }
    (void)sqlite3_finalize(statement);
#endif
    return records;
}

std::vector<EvidenceRecord> SqliteStoreForward::PendingEvidenceUpload() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<EvidenceRecord> records;
#if KSI_EDGE_HAVE_SQLITE
    if (database_ == nullptr) {
        return records;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT e.event_idempotency_key,e.artifact_id,e.content_type,e.local_path,e.content_digest "
        "FROM evidence_uploads e JOIN candidate_events c ON c.idempotency_key=e.event_idempotency_key "
        "WHERE c.core_acknowledged=1 AND e.core_registered=1 AND e.put_complete=0 "
        "ORDER BY c.edge_device_id,c.device_sequence,e.artifact_id";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return records;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        records.push_back({ColumnText(statement, 0), ColumnText(statement, 1),
                           ColumnText(statement, 2), ColumnText(statement, 3),
                           ColumnText(statement, 4)});
    }
    (void)sqlite3_finalize(statement);
#endif
    return records;
}

StoreForwardVerdict SqliteStoreForward::PruneCompleted() {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return StoreForwardVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return StoreForwardVerdict::kBackendUnavailable;
    }
    const char* sql =
        "DELETE FROM candidate_events WHERE core_acknowledged=1 "
        "AND expected_evidence_count=(SELECT count(*) FROM evidence_uploads "
        "WHERE event_idempotency_key=candidate_events.idempotency_key) "
        "AND NOT EXISTS (SELECT 1 FROM evidence_uploads WHERE "
        "event_idempotency_key=candidate_events.idempotency_key "
        "AND (core_registered=0 OR put_complete=0))";
    char* error = nullptr;
    const int result = sqlite3_exec(static_cast<sqlite3*>(database_), sql, nullptr, nullptr, &error);
    sqlite3_free(error);
    return result == SQLITE_OK ? StoreForwardVerdict::kAccepted : StoreForwardVerdict::kStorageError;
#endif
}

std::size_t SqliteStoreForward::CandidateCount() const {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return 0;
#else
    if (database_ == nullptr) {
        return 0;
    }
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), "SELECT count(*) FROM candidate_events", -1,
                           &statement, nullptr) != SQLITE_OK) {
        return 0;
    }
    const std::size_t count = sqlite3_step(statement) == SQLITE_ROW
                                  ? static_cast<std::size_t>(sqlite3_column_int64(statement, 0))
                                  : 0U;
    (void)sqlite3_finalize(statement);
    return count;
#endif
}

}  // namespace ksi::edge

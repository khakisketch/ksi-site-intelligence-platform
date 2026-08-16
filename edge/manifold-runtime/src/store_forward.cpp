#include "ksi/edge/store_forward.hpp"

#include "ksi/edge/artifact_vault.hpp"
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

const char* ToString(SourceMediaJournalVerdict verdict) {
    switch (verdict) {
        case SourceMediaJournalVerdict::kAccepted:
            return "ACCEPTED";
        case SourceMediaJournalVerdict::kDuplicate:
            return "DUPLICATE";
        case SourceMediaJournalVerdict::kConflict:
            return "CONFLICT";
        case SourceMediaJournalVerdict::kNotFound:
            return "NOT_FOUND";
        case SourceMediaJournalVerdict::kBundleSealed:
            return "BUNDLE_SEALED";
        case SourceMediaJournalVerdict::kDiscoveryIncomplete:
            return "DISCOVERY_INCOMPLETE";
        case SourceMediaJournalVerdict::kIncompleteBundle:
            return "INCOMPLETE_BUNDLE";
        case SourceMediaJournalVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case SourceMediaJournalVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

const char* ToString(SourceMediaState state) {
    switch (state) {
        case SourceMediaState::kDiscovered:
            return "DISCOVERED";
        case SourceMediaState::kSpooled:
            return "SPOOLED";
        case SourceMediaState::kRegistered:
            return "REGISTERED";
        case SourceMediaState::kUploaded:
            return "UPLOADED";
        case SourceMediaState::kPurged:
            return "PURGED";
        case SourceMediaState::kQuarantined:
            return "QUARANTINED";
    }
    return "UNKNOWN";
}

const char* ToString(FlightStartAttemptJournalVerdict verdict) {
    switch (verdict) {
        case FlightStartAttemptJournalVerdict::kAccepted:
            return "ACCEPTED";
        case FlightStartAttemptJournalVerdict::kDuplicate:
            return "DUPLICATE";
        case FlightStartAttemptJournalVerdict::kConflict:
            return "CONFLICT";
        case FlightStartAttemptJournalVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case FlightStartAttemptJournalVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

bool ParseSourceMediaState(const std::string& text, SourceMediaState* state) {
    if (state == nullptr) {
        return false;
    }
    for (const SourceMediaState candidate :
         {SourceMediaState::kDiscovered, SourceMediaState::kSpooled, SourceMediaState::kRegistered,
          SourceMediaState::kUploaded, SourceMediaState::kPurged, SourceMediaState::kQuarantined}) {
        if (text == ToString(candidate)) {
            *state = candidate;
            return true;
        }
    }
    return false;
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
        ");"
        // 원본 사진 회수 테이블군 — 같은 DB·같은 연결·같은 뮤텍스(헤더 주석 참조).
        // discovered_count 가 NULL 인 동안은 "아직 다 못 봤다"는 뜻이고, 그동안
        // 봉인은 성립하지 않는다.
        "CREATE TABLE IF NOT EXISTS source_media_missions ("
        " mission_id TEXT PRIMARY KEY,"
        " edge_device_id TEXT NOT NULL,"
        " discovered_count INTEGER CHECK(discovered_count IS NULL OR discovered_count >= 0),"
        " sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1))"
        ");"
        "CREATE TABLE IF NOT EXISTS source_media_items ("
        " mission_id TEXT NOT NULL,"
        " media_id TEXT NOT NULL,"
        " camera_file_name TEXT NOT NULL,"
        " announced_bytes INTEGER NOT NULL CHECK(announced_bytes >= 0),"
        " state TEXT NOT NULL CHECK(state IN"
        "   ('DISCOVERED','SPOOLED','REGISTERED','UPLOADED','PURGED','QUARANTINED')),"
        " quarantine_reason TEXT,"
        " artifact_id TEXT,"
        " local_path TEXT,"
        " content_digest TEXT,"
        " byte_count INTEGER,"
        " width INTEGER,"
        " height INTEGER,"
        " content_type TEXT,"
        " PRIMARY KEY(mission_id, media_id),"
        " FOREIGN KEY(mission_id) REFERENCES source_media_missions(mission_id)"
        "   ON DELETE CASCADE"
        ");"
        // ADR-KSI-021 §3·§9 — flight-start-attempt 저널. media_offload 의
        // source_media 테이블군과 같은 DB·연결·뮤텍스(헤더 주석 참조). attempt_id
        // 는 arming nonce 유도값이라(nonce 1개 = 시도 1회) PK 로 자연 유일하다.
        "CREATE TABLE IF NOT EXISTS flight_start_attempts ("
        " attempt_id TEXT PRIMARY KEY,"
        " mission_id TEXT NOT NULL,"
        " dispatch_id TEXT NOT NULL,"
        " mission_contract_digest TEXT NOT NULL,"
        " kmz_sha256 TEXT NOT NULL,"
        " stage TEXT NOT NULL,"
        " precondition_verdicts_json TEXT NOT NULL,"
        " outcome TEXT NOT NULL,"
        " attempted_at_utc_ms INTEGER NOT NULL"
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

namespace {

// mission_id·media_id 는 Core 의 객체 키 구성요소가 된다
// (``sites/{siteId}/missions/{missionId}/source/{mediaId}``). 저널에 들어가는
// 순간 이미 그 문법을 만족해야 한다 — 안 그러면 전송 시점에야 거부당하고,
// 그때는 이미 다운로드·스풀 비용을 다 쓴 뒤다.
bool IsSafeSourceMediaIdentifier(const std::string& value) {
    return ArtifactVault::IsSafeArtifactId(value);
}

#if KSI_EDGE_HAVE_SQLITE

SourceMediaJournalVerdict ReadMissionLocked(sqlite3* database, const std::string& mission_id,
                                            SourceMediaMissionState* state) {
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT edge_device_id,discovered_count,sealed FROM source_media_missions WHERE mission_id=?1";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    if (step != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return step == SQLITE_DONE ? SourceMediaJournalVerdict::kNotFound
                                   : SourceMediaJournalVerdict::kStorageError;
    }
    state->mission_id = mission_id;
    state->edge_device_id = ColumnText(statement, 0);
    state->discovery_complete = sqlite3_column_type(statement, 1) != SQLITE_NULL;
    state->discovered_count =
        state->discovery_complete ? static_cast<std::uint32_t>(sqlite3_column_int64(statement, 1)) : 0U;
    state->sealed = sqlite3_column_int(statement, 2) != 0;
    (void)sqlite3_finalize(statement);
    return SourceMediaJournalVerdict::kAccepted;
}

SourceMediaJournalVerdict ReadItemStateLocked(sqlite3* database, const std::string& mission_id,
                                              const std::string& media_id, SourceMediaState* state) {
    sqlite3_stmt* statement = nullptr;
    const char* sql = "SELECT state FROM source_media_items WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    if (step != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return step == SQLITE_DONE ? SourceMediaJournalVerdict::kNotFound
                                   : SourceMediaJournalVerdict::kStorageError;
    }
    const std::string text = ColumnText(statement, 0);
    (void)sqlite3_finalize(statement);
    return ParseSourceMediaState(text, state) ? SourceMediaJournalVerdict::kAccepted
                                              : SourceMediaJournalVerdict::kStorageError;
}

// 상태 하나만 옮기는 전이. 봉인 여부·현재 상태를 모두 확인하고, 같은 전이를 두
// 번 요청하는 것(재기동 복구의 정상 경로)은 kDuplicate 로 받는다.
SourceMediaJournalVerdict TransitionLocked(sqlite3* database, const std::string& mission_id,
                                           const std::string& media_id, SourceMediaState from,
                                           SourceMediaState to) {
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict = ReadMissionLocked(database, mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    if (mission.sealed) {
        return SourceMediaJournalVerdict::kBundleSealed;
    }
    SourceMediaState current = SourceMediaState::kDiscovered;
    const SourceMediaJournalVerdict item_verdict =
        ReadItemStateLocked(database, mission_id, media_id, &current);
    if (item_verdict != SourceMediaJournalVerdict::kAccepted) {
        return item_verdict;
    }
    if (current == to) {
        return SourceMediaJournalVerdict::kDuplicate;
    }
    if (current != from) {
        return SourceMediaJournalVerdict::kConflict;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE source_media_items SET state=?3 WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 3, ToString(to), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
}

SourceMediaItemRecord ReadItemRow(sqlite3_stmt* statement) {
    SourceMediaItemRecord record;
    record.mission_id = ColumnText(statement, 0);
    record.media_id = ColumnText(statement, 1);
    record.camera_file_name = ColumnText(statement, 2);
    record.announced_bytes = static_cast<std::uint64_t>(sqlite3_column_int64(statement, 3));
    (void)ParseSourceMediaState(ColumnText(statement, 4), &record.state);
    record.quarantine_reason = ColumnText(statement, 5);
    record.artifact_id = ColumnText(statement, 6);
    record.local_path = ColumnText(statement, 7);
    record.content_digest = ColumnText(statement, 8);
    record.byte_count = static_cast<std::uint64_t>(sqlite3_column_int64(statement, 9));
    record.width = static_cast<std::uint32_t>(sqlite3_column_int64(statement, 10));
    record.height = static_cast<std::uint32_t>(sqlite3_column_int64(statement, 11));
    record.content_type = ColumnText(statement, 12);
    return record;
}

constexpr const char* kItemColumns =
    "mission_id,media_id,camera_file_name,announced_bytes,state,quarantine_reason,artifact_id,"
    "local_path,content_digest,byte_count,width,height,content_type";

#endif

}  // namespace

SourceMediaJournalVerdict SqliteStoreForward::BeginSourceMediaMission(
    const std::string& mission_id, const std::string& edge_device_id) {
    if (!IsSafeSourceMediaIdentifier(mission_id) || !IsSafeSourceMediaIdentifier(edge_device_id)) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState existing;
    const SourceMediaJournalVerdict found = ReadMissionLocked(database, mission_id, &existing);
    if (found == SourceMediaJournalVerdict::kAccepted) {
        // 같은 임무를 다른 장비가 이어받는 것은 회수 자체가 뜻을 잃는다 —
        // 발견 목록이 어느 기체의 SD 카드인지 알 수 없게 된다.
        return existing.edge_device_id == edge_device_id ? SourceMediaJournalVerdict::kDuplicate
                                                         : SourceMediaJournalVerdict::kConflict;
    }
    if (found != SourceMediaJournalVerdict::kNotFound) {
        return found;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "INSERT INTO source_media_missions(mission_id,edge_device_id) VALUES(?1,?2)";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, edge_device_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::RecordSourceMediaDiscovered(
    const std::string& mission_id, const std::string& media_id, const std::string& camera_file_name,
    std::uint64_t announced_bytes) {
    if (!IsSafeSourceMediaIdentifier(mission_id) || !IsSafeSourceMediaIdentifier(media_id) ||
        camera_file_name.empty() ||
        announced_bytes > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict = ReadMissionLocked(database, mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    if (mission.sealed) {
        return SourceMediaJournalVerdict::kBundleSealed;
    }
    sqlite3_stmt* existing = nullptr;
    const char* existing_sql =
        "SELECT camera_file_name,announced_bytes FROM source_media_items "
        "WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(database, existing_sql, -1, &existing, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(existing, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    const int existing_step = sqlite3_step(existing);
    if (existing_step == SQLITE_ROW) {
        // 같은 mediaId 가 **다른 카메라 파일**을 가리키면 두 장 중 하나가 조용히
        // 사라진다. 덮어쓰지 않고 거부한다 — 호출부가 규약대로 갈라놓아야 한다.
        const bool same = ColumnText(existing, 0) == camera_file_name &&
                          static_cast<std::uint64_t>(sqlite3_column_int64(existing, 1)) ==
                              announced_bytes;
        (void)sqlite3_finalize(existing);
        return same ? SourceMediaJournalVerdict::kDuplicate : SourceMediaJournalVerdict::kConflict;
    }
    (void)sqlite3_finalize(existing);
    if (existing_step != SQLITE_DONE) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    if (mission.discovery_complete) {
        // 목록을 닫은 뒤 새 장이 나타났다. 예산·봉인 판정이 전부 그 수를 근거로
        // 하므로 조용히 늘리지 않는다.
        return SourceMediaJournalVerdict::kConflict;
    }
    sqlite3_stmt* insert = nullptr;
    const char* insert_sql =
        "INSERT INTO source_media_items(mission_id,media_id,camera_file_name,announced_bytes,state)"
        " VALUES(?1,?2,?3,?4,'DISCOVERED')";
    if (sqlite3_prepare_v2(database, insert_sql, -1, &insert, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(insert, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 3, camera_file_name.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(insert, 4, static_cast<sqlite3_int64>(announced_bytes));
    const int step = sqlite3_step(insert);
    (void)sqlite3_finalize(insert);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceMediaDiscoveryComplete(
    const std::string& mission_id, std::uint32_t expected_count) {
    if (!IsSafeSourceMediaIdentifier(mission_id)) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)expected_count;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict = ReadMissionLocked(database, mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    sqlite3_stmt* counter = nullptr;
    if (sqlite3_prepare_v2(database, "SELECT count(*) FROM source_media_items WHERE mission_id=?1", -1,
                           &counter, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(counter, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(counter) != SQLITE_ROW) {
        (void)sqlite3_finalize(counter);
        return SourceMediaJournalVerdict::kStorageError;
    }
    const std::int64_t actual = sqlite3_column_int64(counter, 0);
    (void)sqlite3_finalize(counter);
    if (actual != static_cast<std::int64_t>(expected_count)) {
        return SourceMediaJournalVerdict::kConflict;
    }
    if (mission.discovery_complete) {
        return mission.discovered_count == expected_count ? SourceMediaJournalVerdict::kDuplicate
                                                          : SourceMediaJournalVerdict::kConflict;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE source_media_missions SET discovered_count=?2 WHERE mission_id=?1";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(statement, 2, static_cast<sqlite3_int64>(expected_count));
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceMediaSpooled(
    const SourceMediaItemRecord& measured) {
    // 실측값이 전부 있어야 한다. 하나라도 비면 Core 등록에서 거부당할 값을
    // 저널에 먼저 굳히는 셈이 된다.
    if (!IsSafeSourceMediaIdentifier(measured.mission_id) ||
        !IsSafeSourceMediaIdentifier(measured.media_id) ||
        !ArtifactVault::IsSafeArtifactId(measured.artifact_id) || measured.local_path.empty() ||
        !IsSha256Digest(measured.content_digest) || measured.byte_count == 0U ||
        measured.width == 0U || measured.height == 0U || measured.content_type.empty() ||
        measured.byte_count > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict =
        ReadMissionLocked(database, measured.mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    if (mission.sealed) {
        return SourceMediaJournalVerdict::kBundleSealed;
    }
    SourceMediaState current = SourceMediaState::kDiscovered;
    const SourceMediaJournalVerdict item_verdict =
        ReadItemStateLocked(database, measured.mission_id, measured.media_id, &current);
    if (item_verdict != SourceMediaJournalVerdict::kAccepted) {
        return item_verdict;
    }
    if (current == SourceMediaState::kSpooled) {
        SourceMediaItemRecord stored;
        sqlite3_stmt* existing = nullptr;
        const std::string existing_sql =
            std::string("SELECT ") + kItemColumns +
            " FROM source_media_items WHERE mission_id=?1 AND media_id=?2";
        if (sqlite3_prepare_v2(database, existing_sql.c_str(), -1, &existing, nullptr) != SQLITE_OK) {
            return SourceMediaJournalVerdict::kStorageError;
        }
        (void)sqlite3_bind_text(existing, 1, measured.mission_id.c_str(), -1, SQLITE_TRANSIENT);
        (void)sqlite3_bind_text(existing, 2, measured.media_id.c_str(), -1, SQLITE_TRANSIENT);
        if (sqlite3_step(existing) != SQLITE_ROW) {
            (void)sqlite3_finalize(existing);
            return SourceMediaJournalVerdict::kStorageError;
        }
        stored = ReadItemRow(existing);
        (void)sqlite3_finalize(existing);
        // 같은 장을 다시 받아 같은 값이 나왔다 — 재기동 복구의 정상 경로다.
        // 다른 값이 나왔으면 SD 카드 쪽이 바뀐 것이고, 그건 조용히 덮을 일이 아니다.
        return stored.content_digest == measured.content_digest &&
                       stored.byte_count == measured.byte_count && stored.width == measured.width &&
                       stored.height == measured.height &&
                       stored.artifact_id == measured.artifact_id
                   ? SourceMediaJournalVerdict::kDuplicate
                   : SourceMediaJournalVerdict::kConflict;
    }
    if (current != SourceMediaState::kDiscovered) {
        return SourceMediaJournalVerdict::kConflict;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "UPDATE source_media_items SET state='SPOOLED',artifact_id=?3,local_path=?4,"
        "content_digest=?5,byte_count=?6,width=?7,height=?8,content_type=?9 "
        "WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, measured.mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, measured.media_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 3, measured.artifact_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 4, measured.local_path.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 5, measured.content_digest.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(statement, 6, static_cast<sqlite3_int64>(measured.byte_count));
    (void)sqlite3_bind_int64(statement, 7, static_cast<sqlite3_int64>(measured.width));
    (void)sqlite3_bind_int64(statement, 8, static_cast<sqlite3_int64>(measured.height));
    (void)sqlite3_bind_text(statement, 9, measured.content_type.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceMediaRegistered(
    const std::string& mission_id, const std::string& media_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    (void)media_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    return TransitionLocked(static_cast<sqlite3*>(database_), mission_id, media_id,
                            SourceMediaState::kSpooled, SourceMediaState::kRegistered);
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceMediaUploaded(const std::string& mission_id,
                                                                       const std::string& media_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    (void)media_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    return TransitionLocked(static_cast<sqlite3*>(database_), mission_id, media_id,
                            SourceMediaState::kRegistered, SourceMediaState::kUploaded);
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceMediaPurged(const std::string& mission_id,
                                                                     const std::string& media_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    (void)media_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    return TransitionLocked(static_cast<sqlite3*>(database_), mission_id, media_id,
                            SourceMediaState::kUploaded, SourceMediaState::kPurged);
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::QuarantineSourceMedia(const std::string& mission_id,
                                                                     const std::string& media_id,
                                                                     const std::string& reason) {
    if (reason.empty()) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    (void)media_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict = ReadMissionLocked(database, mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    if (mission.sealed) {
        return SourceMediaJournalVerdict::kBundleSealed;
    }
    SourceMediaState current = SourceMediaState::kDiscovered;
    const SourceMediaJournalVerdict item_verdict =
        ReadItemStateLocked(database, mission_id, media_id, &current);
    if (item_verdict != SourceMediaJournalVerdict::kAccepted) {
        return item_verdict;
    }
    if (current == SourceMediaState::kQuarantined) {
        return SourceMediaJournalVerdict::kDuplicate;
    }
    // 이미 Core 로 넘어간 장을 격리하면 원장 두 곳의 뜻이 갈라진다.
    if (current == SourceMediaState::kPurged || current == SourceMediaState::kUploaded) {
        return SourceMediaJournalVerdict::kConflict;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "UPDATE source_media_items SET state='QUARANTINED',quarantine_reason=?3 "
                      "WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(database, sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 3, reason.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::MarkSourceBundleSealed(const std::string& mission_id) {
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    SourceMediaMissionState mission;
    const SourceMediaJournalVerdict mission_verdict = ReadMissionLocked(database, mission_id, &mission);
    if (mission_verdict != SourceMediaJournalVerdict::kAccepted) {
        return mission_verdict;
    }
    if (mission.sealed) {
        return SourceMediaJournalVerdict::kDuplicate;
    }
    if (!mission.discovery_complete) {
        return SourceMediaJournalVerdict::kDiscoveryIncomplete;
    }
    sqlite3_stmt* counter = nullptr;
    const char* counter_sql =
        "SELECT count(*),sum(CASE WHEN state='PURGED' THEN 1 ELSE 0 END) "
        "FROM source_media_items WHERE mission_id=?1";
    if (sqlite3_prepare_v2(database, counter_sql, -1, &counter, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(counter, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(counter) != SQLITE_ROW) {
        (void)sqlite3_finalize(counter);
        return SourceMediaJournalVerdict::kStorageError;
    }
    const std::int64_t total = sqlite3_column_int64(counter, 0);
    const std::int64_t purged =
        sqlite3_column_type(counter, 1) == SQLITE_NULL ? 0 : sqlite3_column_int64(counter, 1);
    (void)sqlite3_finalize(counter);
    // 세 값이 전부 같아야 한다: 확정된 발견 수 == 저장된 행 수 == PURGED 수.
    // 하나라도 어긋나면 봉인은 "전부 올렸다"라는 거짓말이 된다.
    if (total == 0 || total != static_cast<std::int64_t>(mission.discovered_count) ||
        purged != total) {
        return SourceMediaJournalVerdict::kIncompleteBundle;
    }
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(database, "UPDATE source_media_missions SET sealed=1 WHERE mission_id=?1",
                           -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    (void)sqlite3_finalize(statement);
    return step == SQLITE_DONE ? SourceMediaJournalVerdict::kAccepted
                               : SourceMediaJournalVerdict::kStorageError;
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::FindSourceMediaMission(
    const std::string& mission_id, SourceMediaMissionState* state) const {
    if (state == nullptr) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    return ReadMissionLocked(static_cast<sqlite3*>(database_), mission_id, state);
#endif
}

SourceMediaJournalVerdict SqliteStoreForward::FindSourceMediaItem(
    const std::string& mission_id, const std::string& media_id,
    SourceMediaItemRecord* record) const {
    if (record == nullptr) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    (void)media_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3_stmt* statement = nullptr;
    const std::string sql = std::string("SELECT ") + kItemColumns +
                            " FROM source_media_items WHERE mission_id=?1 AND media_id=?2";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql.c_str(), -1, &statement, nullptr) !=
        SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, media_id.c_str(), -1, SQLITE_TRANSIENT);
    const int step = sqlite3_step(statement);
    if (step != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return step == SQLITE_DONE ? SourceMediaJournalVerdict::kNotFound
                                   : SourceMediaJournalVerdict::kStorageError;
    }
    *record = ReadItemRow(statement);
    (void)sqlite3_finalize(statement);
    return SourceMediaJournalVerdict::kAccepted;
#endif
}

std::vector<SourceMediaItemRecord> SqliteStoreForward::SourceMediaItemsInState(
    const std::string& mission_id, SourceMediaState state) const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<SourceMediaItemRecord> records;
#if KSI_EDGE_HAVE_SQLITE
    if (database_ == nullptr) {
        return records;
    }
    sqlite3_stmt* statement = nullptr;
    // media_id 정렬은 다운로드·배출 순서를 재기동 너머로 결정론적으로 만든다.
    const std::string sql = std::string("SELECT ") + kItemColumns +
                            " FROM source_media_items WHERE mission_id=?1 AND state=?2 "
                            "ORDER BY media_id";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql.c_str(), -1, &statement, nullptr) !=
        SQLITE_OK) {
        return records;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(statement, 2, ToString(state), -1, SQLITE_TRANSIENT);
    while (sqlite3_step(statement) == SQLITE_ROW) {
        records.push_back(ReadItemRow(statement));
    }
    (void)sqlite3_finalize(statement);
#else
    (void)mission_id;
    (void)state;
#endif
    return records;
}

SourceMediaJournalVerdict SqliteStoreForward::SourceMediaSpoolUsage(const std::string& mission_id,
                                                                     std::uint64_t* spool_bytes,
                                                                     std::uint32_t* spool_items) const {
    if (spool_bytes == nullptr || spool_items == nullptr) {
        return SourceMediaJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    return SourceMediaJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return SourceMediaJournalVerdict::kBackendUnavailable;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT count(*),coalesce(sum(byte_count),0) FROM source_media_items "
        "WHERE mission_id=?1 AND state IN ('SPOOLED','REGISTERED','UPLOADED')";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return SourceMediaJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(statement) != SQLITE_ROW) {
        (void)sqlite3_finalize(statement);
        return SourceMediaJournalVerdict::kStorageError;
    }
    *spool_items = static_cast<std::uint32_t>(sqlite3_column_int64(statement, 0));
    *spool_bytes = static_cast<std::uint64_t>(sqlite3_column_int64(statement, 1));
    (void)sqlite3_finalize(statement);
    return SourceMediaJournalVerdict::kAccepted;
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

namespace {

// mission_kmz.cpp 의 IsBareSha256Hex 와 같은 문법(계약 발급 원장의 kmzSha256
// 표기 그대로, "sha256:" 접두사 없음) — 파일마다 자기 것을 갖는 이 디렉터리의
// 관습을 그대로 따른다(activation.cpp/mission_kmz.cpp 상단 주석 참조).
bool IsBareSha256HexOrEmpty(const std::string& value) {
    if (value.empty()) {
        return true;
    }
    if (value.size() != 64U) {
        return false;
    }
    for (const char character : value) {
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) {
            return false;
        }
    }
    return true;
}

}  // namespace

FlightStartAttemptJournalVerdict SqliteStoreForward::RecordFlightStartAttempt(
    const FlightStartAttemptRecord& record) {
    if (!IsSafeSourceMediaIdentifier(record.attempt_id) ||
        !IsSafeSourceMediaIdentifier(record.mission_id) ||
        !IsSafeSourceMediaIdentifier(record.dispatch_id) ||
        (!record.mission_contract_digest.empty() && !IsSha256Digest(record.mission_contract_digest)) ||
        !IsBareSha256HexOrEmpty(record.kmz_sha256) || record.stage.empty() ||
        record.precondition_verdicts_json.empty() || record.outcome.empty() ||
        record.attempted_at_utc_ms < 0) {
        return FlightStartAttemptJournalVerdict::kConflict;
    }
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    return FlightStartAttemptJournalVerdict::kBackendUnavailable;
#else
    if (database_ == nullptr) {
        return FlightStartAttemptJournalVerdict::kBackendUnavailable;
    }
    sqlite3* database = static_cast<sqlite3*>(database_);
    sqlite3_stmt* existing = nullptr;
    const char* existing_sql =
        "SELECT mission_id,dispatch_id,mission_contract_digest,kmz_sha256,stage,"
        "precondition_verdicts_json,outcome,attempted_at_utc_ms FROM flight_start_attempts "
        "WHERE attempt_id=?1";
    if (sqlite3_prepare_v2(database, existing_sql, -1, &existing, nullptr) != SQLITE_OK) {
        return FlightStartAttemptJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(existing, 1, record.attempt_id.c_str(), -1, SQLITE_TRANSIENT);
    const int existing_step = sqlite3_step(existing);
    if (existing_step == SQLITE_ROW) {
        // 같은 nonce(=attempt_id)가 다른 내용을 주장하면 조용히 덮어쓰지 않는다 —
        // "1 nonce = 시도 1회"가 저널에서도 깨지면 안 된다.
        const bool same = ColumnText(existing, 0) == record.mission_id &&
                          ColumnText(existing, 1) == record.dispatch_id &&
                          ColumnText(existing, 2) == record.mission_contract_digest &&
                          ColumnText(existing, 3) == record.kmz_sha256 &&
                          ColumnText(existing, 4) == record.stage &&
                          ColumnText(existing, 5) == record.precondition_verdicts_json &&
                          ColumnText(existing, 6) == record.outcome &&
                          sqlite3_column_int64(existing, 7) == record.attempted_at_utc_ms;
        (void)sqlite3_finalize(existing);
        return same ? FlightStartAttemptJournalVerdict::kDuplicate
                    : FlightStartAttemptJournalVerdict::kConflict;
    }
    (void)sqlite3_finalize(existing);
    if (existing_step != SQLITE_DONE) {
        return FlightStartAttemptJournalVerdict::kStorageError;
    }
    sqlite3_stmt* insert = nullptr;
    const char* insert_sql =
        "INSERT INTO flight_start_attempts(attempt_id,mission_id,dispatch_id,mission_contract_digest,"
        "kmz_sha256,stage,precondition_verdicts_json,outcome,attempted_at_utc_ms)"
        " VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)";
    if (sqlite3_prepare_v2(database, insert_sql, -1, &insert, nullptr) != SQLITE_OK) {
        return FlightStartAttemptJournalVerdict::kStorageError;
    }
    (void)sqlite3_bind_text(insert, 1, record.attempt_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 2, record.mission_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 3, record.dispatch_id.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 4, record.mission_contract_digest.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 5, record.kmz_sha256.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 6, record.stage.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 7, record.precondition_verdicts_json.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_text(insert, 8, record.outcome.c_str(), -1, SQLITE_TRANSIENT);
    (void)sqlite3_bind_int64(insert, 9, static_cast<sqlite3_int64>(record.attempted_at_utc_ms));
    const int step = sqlite3_step(insert);
    (void)sqlite3_finalize(insert);
    return step == SQLITE_DONE ? FlightStartAttemptJournalVerdict::kAccepted
                               : FlightStartAttemptJournalVerdict::kStorageError;
#endif
}

std::vector<FlightStartAttemptRecord> SqliteStoreForward::FlightStartAttempts(
    const std::string& mission_id) const {
    std::vector<FlightStartAttemptRecord> records;
    std::lock_guard<std::mutex> lock(mutex_);
#if !KSI_EDGE_HAVE_SQLITE
    (void)mission_id;
    return records;
#else
    if (database_ == nullptr || !IsSafeSourceMediaIdentifier(mission_id)) {
        return records;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT attempt_id,dispatch_id,mission_contract_digest,kmz_sha256,stage,"
        "precondition_verdicts_json,outcome,attempted_at_utc_ms FROM flight_start_attempts "
        "WHERE mission_id=?1 ORDER BY attempted_at_utc_ms ASC";
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(database_), sql, -1, &statement, nullptr) != SQLITE_OK) {
        return records;
    }
    (void)sqlite3_bind_text(statement, 1, mission_id.c_str(), -1, SQLITE_TRANSIENT);
    while (sqlite3_step(statement) == SQLITE_ROW) {
        FlightStartAttemptRecord record;
        record.attempt_id = ColumnText(statement, 0);
        record.mission_id = mission_id;
        record.dispatch_id = ColumnText(statement, 1);
        record.mission_contract_digest = ColumnText(statement, 2);
        record.kmz_sha256 = ColumnText(statement, 3);
        record.stage = ColumnText(statement, 4);
        record.precondition_verdicts_json = ColumnText(statement, 5);
        record.outcome = ColumnText(statement, 6);
        record.attempted_at_utc_ms = sqlite3_column_int64(statement, 7);
        records.push_back(std::move(record));
    }
    (void)sqlite3_finalize(statement);
    return records;
#endif
}

}  // namespace ksi::edge

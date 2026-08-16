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

// ── 원본 사진 회수(source media) ────────────────────────────────────────────
//
// EventBundle 계열과 **같은 DB·같은 연결·같은 뮤텍스**를 쓴다. 별도 DB 를 만들면
// 두 개의 WAL 이 같은 전원 손실을 서로 다른 시점에 견디게 되어, "사진은 올라갔는데
// 사건은 없다"거나 그 반대인 복구 상태가 생긴다. 테이블만 나눈다.
//
// 판정 어휘를 따로 두는 이유: 사진 회수에는 EventBundle 에 없는 상태(봉인·발견
// 미완)가 있고, EventBundle 에는 사진에 없는 상태(ACK 대기)가 있다. 한 enum 에
// 합치면 어느 쪽 호출부에서도 "여기서는 절대 안 나오는 값"을 다루게 된다.
enum class SourceMediaJournalVerdict {
    kAccepted,
    kDuplicate,
    kConflict,
    kNotFound,
    // 이미 봉인됐다 — 추가 등록·상태 전이를 받지 않는다.
    kBundleSealed,
    // 발견 목록이 아직 확정되지 않았다. 봉인은 전량 회수를 뜻하므로 목록이
    // 닫히기 전에는 성립하지 않는다.
    kDiscoveryIncomplete,
    // 전량 PURGED 가 아닌데 봉인하려 했다(격리된 장이 남은 경우 포함).
    // **부분 집합 봉인은 sourceBundleDigest 를 거짓으로 만든다** — Core 가
    // 그 digest 를 "이 임무의 원본 전부"라는 뜻으로 3D 처리 입력에 싣는다.
    // 상태기계 역행 시도는 이 값이 아니라 kConflict 다.
    kIncompleteBundle,
    kBackendUnavailable,
    kStorageError,
};

const char* ToString(SourceMediaJournalVerdict verdict);

// 장당 상태기계. 한 방향으로만 간다.
//
//   DISCOVERED → SPOOLED → REGISTERED → UPLOADED → PURGED
//                    └──────────┴───────────┴─→ QUARANTINED
//
// QUARANTINED 는 종착지다. 화소수를 못 읽은 장(jpeg_dimensions 참조)이 여기로
// 간다 — 값을 지어내 등록하는 대신 자동 경로에서 빼고, 그 임무의 봉인을 막는다.
// 원본은 기체 SD 카드에 그대로 있으므로 수동 경로로는 여전히 올릴 수 있다.
enum class SourceMediaState {
    kDiscovered,
    kSpooled,
    kRegistered,
    kUploaded,
    kPurged,
    kQuarantined,
};

const char* ToString(SourceMediaState state);
bool ParseSourceMediaState(const std::string& text, SourceMediaState* state);

struct SourceMediaItemRecord {
    std::string mission_id;
    std::string media_id;
    // 카메라가 준 원본 파일명(확장자 포함). mediaId 규약의 입력이자, 수동 경로와
    // 같은 사진을 가리키는지 사람이 대조할 수 있는 유일한 값이다.
    std::string camera_file_name;
    // 파일 목록이 **주장한** 크기. 다운로드 전 스풀 예산을 재는 데만 쓴다.
    std::uint64_t announced_bytes = 0;
    SourceMediaState state = SourceMediaState::kDiscovered;
    std::string quarantine_reason;
    // 아래는 kSpooled 이후에만 채워진다 — 전부 **실측**이다.
    std::string artifact_id;
    std::string local_path;
    std::string content_digest;
    std::uint64_t byte_count = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::string content_type;
};

struct SourceMediaMissionState {
    std::string mission_id;
    std::string edge_device_id;
    bool discovery_complete = false;
    std::uint32_t discovered_count = 0;
    bool sealed = false;
};

// ── flight-start-attempt 저널 (ADR-KSI-021 §3·§9) ───────────────────────────
enum class FlightStartAttemptJournalVerdict {
    kAccepted,
    kDuplicate,
    kConflict,
    kBackendUnavailable,
    kStorageError,
};

const char* ToString(FlightStartAttemptJournalVerdict verdict);

struct FlightStartAttemptRecord {
    std::string attempt_id;  // arming nonce 유도 — PK
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;  // "sha256:<hex>", 비어있을 수 있다([1] 실패 전이면)
    std::string kmz_sha256;                // bare hex, mission_kmz.hpp 표기 그대로. [4] 이전엔 빈 문자열.
    std::string stage;                     // FlightExecutionStage 의 ToString
    std::string precondition_verdicts_json;  // 각 단계 typed verdict — 이 저널만의 진단 필드
    std::string outcome;                    // "ELIGIBLE_FOR_START" 또는 "REFUSED_<verdict>"
    std::int64_t attempted_at_utc_ms = 0;
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

    // ── source media ────────────────────────────────────────────────────────
    SourceMediaJournalVerdict BeginSourceMediaMission(const std::string& mission_id,
                                                      const std::string& edge_device_id);
    SourceMediaJournalVerdict RecordSourceMediaDiscovered(const std::string& mission_id,
                                                          const std::string& media_id,
                                                          const std::string& camera_file_name,
                                                          std::uint64_t announced_bytes);
    // 발견 목록을 닫는다. ``expected_count`` 는 호출부가 센 값이고, 저널이 가진
    // 행 수와 다르면 거부한다 — 목록이 닫힌 뒤에 조용히 늘거나 주는 것을 막는다.
    SourceMediaJournalVerdict MarkSourceMediaDiscoveryComplete(const std::string& mission_id,
                                                                std::uint32_t expected_count);
    SourceMediaJournalVerdict MarkSourceMediaSpooled(const SourceMediaItemRecord& measured);
    SourceMediaJournalVerdict MarkSourceMediaRegistered(const std::string& mission_id,
                                                         const std::string& media_id);
    SourceMediaJournalVerdict MarkSourceMediaUploaded(const std::string& mission_id,
                                                       const std::string& media_id);
    SourceMediaJournalVerdict MarkSourceMediaPurged(const std::string& mission_id,
                                                     const std::string& media_id);
    SourceMediaJournalVerdict QuarantineSourceMedia(const std::string& mission_id,
                                                     const std::string& media_id,
                                                     const std::string& reason);
    // 전량 PURGED + 발견 목록 확정일 때만 받는다.
    SourceMediaJournalVerdict MarkSourceBundleSealed(const std::string& mission_id);
    SourceMediaJournalVerdict FindSourceMediaMission(const std::string& mission_id,
                                                      SourceMediaMissionState* state) const;
    SourceMediaJournalVerdict FindSourceMediaItem(const std::string& mission_id,
                                                   const std::string& media_id,
                                                   SourceMediaItemRecord* record) const;
    std::vector<SourceMediaItemRecord> SourceMediaItemsInState(const std::string& mission_id,
                                                                SourceMediaState state) const;
    // 지금 매니폴드 디스크를 실제로 점유하고 있는 양 — SPOOLED·REGISTERED·
    // UPLOADED 전부다. UPLOADED 는 "Core 가 받았다"이지 "지웠다"가 아니라서
    // 여전히 예산을 쓴다.
    SourceMediaJournalVerdict SourceMediaSpoolUsage(const std::string& mission_id,
                                                     std::uint64_t* spool_bytes,
                                                     std::uint32_t* spool_items) const;

    // ── flight-start-attempt 저널 (ADR-KSI-021 §3·§9) ─────────────────────────
    //
    // media_offload 의 source_media 테이블군과 같은 방식으로: **같은 DB·같은
    // 연결·같은 뮤텍스**를 재사용한다. 별도 DB 는 서로 다른 전원 손실 내구성을
    // 만든다(헤더 상단 주석과 같은 이유). attempt_id 는 arming nonce 에서
    // 유도되므로(nonce 1개 = 시도 1회) 자연히 유일하다 — 같은 attempt_id 재기록은
    // 중복이지 새 시도가 아니다.
    //
    // outcome 은 "ELIGIBLE_FOR_START" 하나 또는 "REFUSED_<FlightExecutionVerdict>"
    // 형식이다(ADR §9 "거부도 같은 형식으로 기록한다") — 이 문자열 자체의 문법을
    // 강제하지 않는다(그 스키마의 정본은 flight_execution.hpp 다); 이 저널은
    // 그 문자열을 불투명하게 durable 저장할 뿐이다.
    FlightStartAttemptJournalVerdict RecordFlightStartAttempt(const FlightStartAttemptRecord& record);
    std::vector<FlightStartAttemptRecord> FlightStartAttempts(const std::string& mission_id) const;

private:
    StoreForwardVerdict InitializeLocked();
    void CloseLocked();

    const std::string database_path_;
    mutable std::mutex mutex_;
    void* database_ = nullptr;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_STORE_FORWARD_HPP

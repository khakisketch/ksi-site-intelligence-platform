// Shadow-only ActionIntent acceptance gate.
//
// This is deliberately a journal of decisions, not a flight-command adapter.
// No DJI flight-control header or symbol belongs in this target.

#ifndef KSI_EDGE_SHADOW_HPP
#define KSI_EDGE_SHADOW_HPP

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "ksi/control_plane/supervisor.hpp"

namespace ksi::edge {

class ArtifactVault;

struct ActivationContext {
    std::string mission_contract_digest;
    std::string risk_policy_pack_digest;
    control_plane::UtcMillis valid_from_utc_ms = 0;
    control_plane::UtcMillis valid_until_utc_ms = 0;
};

enum class ShadowVerdict {
    kShadowAccepted,
    kNoActivation,
    kContractExpired,
    kClockRollback,
    kPolicyDigestMismatch,
    kControlPlaneRejected,
    kJournalUnavailable,
    kJournalRejected,
};

const char* ToString(ShadowVerdict verdict);

// A shadow acceptance is an assertion only after its local journal reports a
// durable/idempotent result.  Keep this outcome distinct from the control
// plane verdict so a storage failure cannot be mistaken for a safe decision.
enum class ShadowJournalVerdict {
    kRecorded,
    kDuplicate,
    kConflict,
    kUnavailable,
    kStorageError,
};

const char* ToString(ShadowJournalVerdict verdict);

struct ShadowDecision {
    ShadowVerdict verdict = ShadowVerdict::kNoActivation;
    control_plane::CommandVerdict control_plane_verdict =
        control_plane::CommandVerdict::kSupervisorNotReady;
    ShadowJournalVerdict journal_verdict = ShadowJournalVerdict::kUnavailable;
};

struct ShadowActionRecord {
    std::string decision = "SHADOW_ACCEPTED";
    std::string command_id;
    std::string action_kind;
    std::string mission_contract_digest;
    std::string risk_policy_pack_digest;
    control_plane::UtcMillis accepted_at_utc_ms = 0;
};

class IShadowActionJournal {
public:
    virtual ~IShadowActionJournal() = default;
    virtual ShadowJournalVerdict Record(const ShadowActionRecord& record) = 0;
};

// Small in-memory journal used by deterministic unit/replay tests.  The
// deployed PSDK application uses ArtifactVaultShadowActionJournal instead, so
// a process restart cannot turn a previously asserted shadow decision into an
// unobservable success.
class ShadowActionJournal final : public IShadowActionJournal {
public:
    ShadowJournalVerdict Record(const ShadowActionRecord& record) override;
    const std::vector<ShadowActionRecord>& records() const { return records_; }

private:
    std::vector<ShadowActionRecord> records_;
};

// Immutable local artifact journal for the deployment path.  Its artifact ID
// is derived from the command ID, so an exact replay is a duplicate and a
// divergent reuse is a conflict.  These records are local shadow diagnostics;
// they are deliberately not flight commands and are not promoted to Core
// evidence by this class.
class ArtifactVaultShadowActionJournal final : public IShadowActionJournal {
public:
    explicit ArtifactVaultShadowActionJournal(ArtifactVault* artifact_vault);
    ShadowJournalVerdict Record(const ShadowActionRecord& record) override;

private:
    ArtifactVault* artifact_vault_;
};

class ShadowFlightSupervisor {
public:
    ShadowFlightSupervisor(std::int64_t degrade_after_ms, std::int64_t fail_closed_after_ms);

    // Activation comes from the separately verified contract consumer, before the
    // frame loop begins. An invalid/expired context never replaces a prior context.
    bool Activate(const ActivationContext& context, control_plane::UtcMillis now_utc_ms);
    // A missing, replaced, or unsafe native activation handoff must not leave a
    // prior dispatch usable until its original TTL happens to expire.
    void Deactivate();
    control_plane::HeartbeatVerdict RecordHeartbeat(control_plane::UtcMillis observed_at_utc_ms,
                                                     control_plane::UtcMillis now_utc_ms);
    ShadowDecision Evaluate(const control_plane::ActionIntent& intent,
                            const std::string& risk_policy_pack_digest,
                            control_plane::UtcMillis now_utc_ms,
                            IShadowActionJournal* journal);

    // ── flight_execution.hpp [7] 재사용 지점(ADR-KSI-021 §5) ───────────────
    //
    // 읽기 전용이다 — last_wall_clock_utc_ms_ 를 갱신하지 않는다. 시계 역행은
    // 이 러닝타임 전체가 공유하는 워터마크로 이미 잡힌다(Evaluate 가 프레임
    // 루프의 매 heartbeat 마다 갱신한다); flight_execution 은 그 워터마크를
    // 다시 쓰지 않고 대조만 한다("그 판정 재사용" — 새 시계 추적을 만들지
    // 않는다).
    control_plane::UtcMillis LastWallClockUtcMs() const { return last_wall_clock_utc_ms_; }
    bool IsActivationUsable(control_plane::UtcMillis now_utc_ms) const {
        return IsContextUsable(now_utc_ms);
    }
    control_plane::SupervisorState ControlPlaneStateAt(control_plane::UtcMillis now_utc_ms) const {
        return control_plane_.StateAt(now_utc_ms);
    }

private:
    bool IsContextUsable(control_plane::UtcMillis now_utc_ms) const;

    control_plane::FlightSupervisor control_plane_;
    std::optional<ActivationContext> activation_;
    control_plane::UtcMillis last_wall_clock_utc_ms_ = 0;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_SHADOW_HPP

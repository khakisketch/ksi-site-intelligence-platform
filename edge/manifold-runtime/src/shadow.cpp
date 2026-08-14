#include "ksi/edge/shadow.hpp"

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/crypto.hpp"

#include <sstream>
#include <stdexcept>
#include <utility>

namespace ksi::edge {

namespace {

bool IsKnownActionKind(const std::string& action_kind) {
    return action_kind == "HOLD" || action_kind == "RETURN_TO_HOME" ||
           action_kind == "GOTO_VIEWPOINT" || action_kind == "CAPTURE_IMAGE";
}

bool IsValidRecord(const ShadowActionRecord& record) {
    return record.decision == "SHADOW_ACCEPTED" && !record.command_id.empty() &&
           IsKnownActionKind(record.action_kind) &&
           IsSha256Digest(record.mission_contract_digest) &&
           IsSha256Digest(record.risk_policy_pack_digest) && record.accepted_at_utc_ms >= 0 &&
           record.accepted_at_utc_ms <= control_plane::kMaxUtcMs;
}

bool SameRecord(const ShadowActionRecord& left, const ShadowActionRecord& right) {
    return left.decision == right.decision && left.command_id == right.command_id &&
           left.action_kind == right.action_kind &&
           left.mission_contract_digest == right.mission_contract_digest &&
           left.risk_policy_pack_digest == right.risk_policy_pack_digest &&
           left.accepted_at_utc_ms == right.accepted_at_utc_ms;
}

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

std::string ArtifactIdForRecord(const ShadowActionRecord& record) {
    const std::string command_hash =
        Sha256Hex(reinterpret_cast<const std::uint8_t*>(record.command_id.data()),
                  record.command_id.size());
    return command_hash.empty() ? std::string{} : "shadow-action-" + command_hash + ".json";
}

std::string SerializeRecord(const ShadowActionRecord& record) {
    if (!IsValidRecord(record)) {
        return {};
    }
    // Keys are lexicographically ordered so the immutable journal is stable
    // across replay.  This is a private local record, not a new Core wire
    // contract; its only producer is the fully-gated supervisor below.
    return "{\"acceptedAtUtcMs\":" + std::to_string(record.accepted_at_utc_ms) +
           ",\"actionKind\":\"" + EscapeJson(record.action_kind) +
           "\",\"commandId\":\"" + EscapeJson(record.command_id) +
           "\",\"decision\":\"SHADOW_ACCEPTED\",\"missionContractDigest\":\"" +
           EscapeJson(record.mission_contract_digest) +
           "\",\"riskPolicyPackDigest\":\"" + EscapeJson(record.risk_policy_pack_digest) +
           "\",\"schemaVersion\":\"1.0\"}";
}

}  // namespace

const char* ToString(ShadowVerdict verdict) {
    switch (verdict) {
        case ShadowVerdict::kShadowAccepted:
            return "SHADOW_ACCEPTED";
        case ShadowVerdict::kNoActivation:
            return "NO_ACTIVATION";
        case ShadowVerdict::kContractExpired:
            return "CONTRACT_EXPIRED";
        case ShadowVerdict::kClockRollback:
            return "CLOCK_ROLLBACK";
        case ShadowVerdict::kPolicyDigestMismatch:
            return "POLICY_DIGEST_MISMATCH";
        case ShadowVerdict::kControlPlaneRejected:
            return "CONTROL_PLANE_REJECTED";
        case ShadowVerdict::kJournalUnavailable:
            return "JOURNAL_UNAVAILABLE";
        case ShadowVerdict::kJournalRejected:
            return "JOURNAL_REJECTED";
    }
    return "UNKNOWN";
}

const char* ToString(ShadowJournalVerdict verdict) {
    switch (verdict) {
        case ShadowJournalVerdict::kRecorded:
            return "RECORDED";
        case ShadowJournalVerdict::kDuplicate:
            return "DUPLICATE";
        case ShadowJournalVerdict::kConflict:
            return "CONFLICT";
        case ShadowJournalVerdict::kUnavailable:
            return "UNAVAILABLE";
        case ShadowJournalVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

ShadowJournalVerdict ShadowActionJournal::Record(const ShadowActionRecord& record) {
    if (!IsValidRecord(record)) {
        return ShadowJournalVerdict::kConflict;
    }
    for (const ShadowActionRecord& existing : records_) {
        if (existing.command_id != record.command_id) {
            continue;
        }
        return SameRecord(existing, record) ? ShadowJournalVerdict::kDuplicate
                                            : ShadowJournalVerdict::kConflict;
    }
    records_.push_back(record);
    return ShadowJournalVerdict::kRecorded;
}

ArtifactVaultShadowActionJournal::ArtifactVaultShadowActionJournal(ArtifactVault* artifact_vault)
    : artifact_vault_(artifact_vault) {
    if (artifact_vault_ == nullptr) {
        throw std::invalid_argument("shadow action journal requires an artifact vault");
    }
}

ShadowJournalVerdict ArtifactVaultShadowActionJournal::Record(const ShadowActionRecord& record) {
    if (artifact_vault_ == nullptr) {
        return ShadowJournalVerdict::kUnavailable;
    }
    const std::string artifact_id = ArtifactIdForRecord(record);
    const std::string payload = SerializeRecord(record);
    if (artifact_id.empty() || payload.empty()) {
        return ShadowJournalVerdict::kConflict;
    }
    const ArtifactVaultResult persisted = artifact_vault_->Persist(
        artifact_id, reinterpret_cast<const std::uint8_t*>(payload.data()), payload.size());
    switch (persisted.verdict) {
        case ArtifactVaultVerdict::kPersisted:
            return ShadowJournalVerdict::kRecorded;
        case ArtifactVaultVerdict::kDuplicate:
            return ShadowJournalVerdict::kDuplicate;
        case ArtifactVaultVerdict::kConflict:
            return ShadowJournalVerdict::kConflict;
        case ArtifactVaultVerdict::kInvalidArtifactId:
        case ArtifactVaultVerdict::kTooLarge:
        case ArtifactVaultVerdict::kNotFound:
        case ArtifactVaultVerdict::kDigestMismatch:
        case ArtifactVaultVerdict::kStorageError:
            return ShadowJournalVerdict::kStorageError;
    }
    return ShadowJournalVerdict::kStorageError;
}

ShadowFlightSupervisor::ShadowFlightSupervisor(std::int64_t degrade_after_ms,
                                               std::int64_t fail_closed_after_ms)
    : control_plane_(degrade_after_ms, fail_closed_after_ms) {}

bool ShadowFlightSupervisor::Activate(const ActivationContext& context,
                                      control_plane::UtcMillis now_utc_ms) {
    if (!IsSha256Digest(context.mission_contract_digest) ||
        !IsSha256Digest(context.risk_policy_pack_digest) || context.valid_from_utc_ms < 0 ||
        context.valid_until_utc_ms <= context.valid_from_utc_ms ||
        now_utc_ms < context.valid_from_utc_ms || now_utc_ms > context.valid_until_utc_ms) {
        return false;
    }
    activation_ = context;
    last_wall_clock_utc_ms_ = now_utc_ms;
    control_plane_.ResetHeartbeatState();
    return true;
}

void ShadowFlightSupervisor::Deactivate() {
    activation_.reset();
    last_wall_clock_utc_ms_ = 0;
    control_plane_.ResetHeartbeatState();
}

control_plane::HeartbeatVerdict ShadowFlightSupervisor::RecordHeartbeat(
    control_plane::UtcMillis observed_at_utc_ms, control_plane::UtcMillis now_utc_ms) {
    return control_plane_.RecordHeartbeat(observed_at_utc_ms, now_utc_ms);
}

bool ShadowFlightSupervisor::IsContextUsable(control_plane::UtcMillis now_utc_ms) const {
    return activation_.has_value() && now_utc_ms >= activation_->valid_from_utc_ms &&
           now_utc_ms <= activation_->valid_until_utc_ms;
}

ShadowDecision ShadowFlightSupervisor::Evaluate(const control_plane::ActionIntent& intent,
                                                const std::string& risk_policy_pack_digest,
                                                control_plane::UtcMillis now_utc_ms,
                                                IShadowActionJournal* journal) {
    if (last_wall_clock_utc_ms_ != 0 && now_utc_ms < last_wall_clock_utc_ms_) {
        return {ShadowVerdict::kClockRollback, control_plane::CommandVerdict::kMalformed,
                ShadowJournalVerdict::kUnavailable};
    }
    last_wall_clock_utc_ms_ = now_utc_ms;
    if (!activation_.has_value()) {
        return {ShadowVerdict::kNoActivation,
                control_plane::CommandVerdict::kMissingAuthorization,
                ShadowJournalVerdict::kUnavailable};
    }
    if (!IsContextUsable(now_utc_ms)) {
        return {ShadowVerdict::kContractExpired, control_plane::CommandVerdict::kExpired,
                ShadowJournalVerdict::kUnavailable};
    }
    if (risk_policy_pack_digest != activation_->risk_policy_pack_digest) {
        return {ShadowVerdict::kPolicyDigestMismatch,
                control_plane::CommandVerdict::kAuthorizationMismatch,
                ShadowJournalVerdict::kUnavailable};
    }
    const control_plane::CommandVerdict authorized =
        control_plane_.Authorize(intent, activation_->mission_contract_digest, now_utc_ms);
    if (authorized != control_plane::CommandVerdict::kAccepted) {
        return {ShadowVerdict::kControlPlaneRejected, authorized,
                ShadowJournalVerdict::kUnavailable};
    }
    if (journal == nullptr) {
        return {ShadowVerdict::kJournalUnavailable, authorized, ShadowJournalVerdict::kUnavailable};
    }
    const ShadowActionRecord record = {
        "SHADOW_ACCEPTED", intent.command_id, control_plane::ToString(intent.kind),
        activation_->mission_contract_digest, activation_->risk_policy_pack_digest, now_utc_ms};
    const ShadowJournalVerdict journal_verdict = journal->Record(record);
    if (journal_verdict != ShadowJournalVerdict::kRecorded &&
        journal_verdict != ShadowJournalVerdict::kDuplicate) {
        return {ShadowVerdict::kJournalRejected, authorized, journal_verdict};
    }
    return {ShadowVerdict::kShadowAccepted, authorized, journal_verdict};
}

}  // namespace ksi::edge

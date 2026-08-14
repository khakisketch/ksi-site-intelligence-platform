#include "ksi/edge/evidence_builder.hpp"

#include "ksi/edge/crypto.hpp"

#include <cctype>
#include <cstdio>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace ksi::edge {

namespace {

bool IsPathSafeIdentifier(const std::string& value) {
    return ArtifactVault::IsSafeArtifactId(value);
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

std::string EpochMillisToRfc3339(std::int64_t epoch_millis) {
    if (epoch_millis <= 0) {
        return {};
    }
    const std::time_t seconds = static_cast<std::time_t>(epoch_millis / 1000);
    const int millis = static_cast<int>(epoch_millis % 1000);
    std::tm utc_time {};
    if (gmtime_r(&seconds, &utc_time) == nullptr) {
        return {};
    }
    char buffer[40] = {};
    const int written = std::snprintf(buffer, sizeof(buffer),
                                      "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                                      utc_time.tm_year + 1900, utc_time.tm_mon + 1,
                                      utc_time.tm_mday, utc_time.tm_hour, utc_time.tm_min,
                                      utc_time.tm_sec, millis);
    return written > 0 && static_cast<std::size_t>(written) < sizeof(buffer) ? buffer
                                                                                : std::string{};
}

bool IsPersisted(const ArtifactVaultResult& result) {
    return result.verdict == ArtifactVaultVerdict::kPersisted ||
           result.verdict == ArtifactVaultVerdict::kDuplicate;
}

std::string BuildPayloadJson(const NativeEvidenceConfig& config, const std::string& event_id,
                             const std::string& occurred_at, const TrackedWorldEntity& tracked,
                             const NativeWorldEntity& world, const EdgeRiskField& risk,
                             const std::string& risk_artifact_id,
                             const std::string& world_entity_artifact_id) {
    const std::string fingerprint = WorldEntityFingerprint(world);
    if (fingerprint.empty()) {
        return {};
    }
    // Every member is emitted in lexicographic order, matching Python's
    // canonical_json_bytes for this string/integer-only EventBundle.  Keep the
    // payload free of floats so C++/Python number rendering cannot drift the
    // SHA-256 idempotency digest.
    std::ostringstream output;
    output << "{\"entities\":[\"" << EscapeJson(world.entity_id)
           << "\"],\"eventId\":\"" << EscapeJson(event_id)
           << "\",\"eventType\":\"EQUIPMENT_RISK_OBSERVATION\",\"evidence\":{"
           << "\"riskFieldArtifact\":\"" << EscapeJson(risk_artifact_id)
           << "\"},\"lineage\":{\"calibrationProfileId\":\""
           << EscapeJson(world.calibration_profile_id) << "\",\"classification\":{\""
           << EscapeJson(world.entity_id) << "\":{\"entityClass\":\""
           << EscapeJson(world.entity_class) << "\",\"entityFingerprint\":\"" << fingerprint
           << "\",\"ontologyVersion\":\"" << EscapeJson(world.classification.ontology_version)
           << "\",\"source\":{\"sourceClassIds\":[" << world.classification.source_class_id
           << "],\"sourceClassNames\":[\"" << EscapeJson(world.classification.source_class_name)
           << "\"],\"taxonomy\":\"" << EscapeJson(world.classification.source_taxonomy)
           << "\"}}},\"edgeVersion\":\"" << EscapeJson(config.edge_version)
           << "\",\"modelVersions\":{";
    bool first_model = true;
    for (const auto& model : world.model_versions) {
        if (!first_model) {
            output << ',';
        }
        first_model = false;
        output << '"' << EscapeJson(model.first) << "\":\"" << EscapeJson(model.second) << '"';
    }
    output << "},\"policyVersion\":\"" << EscapeJson(risk.policy_id)
           << "\"},\"missionId\":\"" << EscapeJson(config.mission_id)
           << "\",\"occurredAt\":\"" << occurred_at
           << "\",\"reasoning\":{\"detectorClass\":\""
           << EscapeJson(tracked.detection.class_name) << "\",\"riskFieldId\":\""
           << EscapeJson(risk.risk_field_id) << "\",\"riskPolicyPackDigest\":\""
           << EscapeJson(risk.risk_policy_pack_digest) << "\"},\"schemaVersion\":\"1.2\""
           << ",\"siteId\":\"" << EscapeJson(config.site_id)
           << "\",\"spatialContext\":{\"alignment\":\""
           << EscapeJson(ToString(tracked.alignment_verdict)) << "\",\"riskFieldId\":\""
           << EscapeJson(risk.risk_field_id) << "\",\"worldEntityArtifact\":\""
           << EscapeJson(world_entity_artifact_id) << "\"},\"status\":\"CANDIDATE\"}";
    return output.str();
}

}  // namespace

NativeCandidateEvidenceBuilder::NativeCandidateEvidenceBuilder(NativeEvidenceConfig config,
                                                               ArtifactVault* artifact_vault,
                                                               SqliteStoreForward* store_forward)
    : config_(std::move(config)), artifact_vault_(artifact_vault), store_forward_(store_forward) {
    if (!IsPathSafeIdentifier(config_.edge_device_id) || !IsPathSafeIdentifier(config_.mission_id) ||
        !IsPathSafeIdentifier(config_.site_id) || config_.edge_version.empty() ||
        artifact_vault_ == nullptr || store_forward_ == nullptr) {
        throw std::invalid_argument("invalid native evidence builder configuration");
    }
}

CandidateEvidenceVerdict NativeCandidateEvidenceBuilder::Build(
    const FramePacket& frame, const TrackedWorldEntity& entity, const NativeWorldEntity& world_entity,
    const EdgeRiskField& risk_field, CandidateEvidenceDraft* draft) {
    if (draft == nullptr || frame.rgb.empty() || ValidateNativeWorldEntity(world_entity) != WorldEntityVerdict::kValid ||
        world_entity.entity_id != entity.entity_id || risk_field.source_entity_id != entity.entity_id ||
        risk_field.risk_policy_pack_digest.empty() ||
        !ArtifactVault::IsSafeArtifactId(risk_field.risk_field_id)) {
        return CandidateEvidenceVerdict::kInvalidInput;
    }
    std::int64_t sequence = -1;
    if (store_forward_->NextDeviceSequence(config_.edge_device_id, &sequence) != StoreForwardVerdict::kAccepted ||
        sequence < 0) {
        return CandidateEvidenceVerdict::kSequenceUnavailable;
    }
    const std::string token_input = config_.edge_device_id + "|" + world_entity.entity_id + "|" +
                                    std::to_string(frame.metadata.frame_id) + "|" +
                                    std::to_string(frame.metadata.received_monotonic_ns) + "|" +
                                    risk_field.risk_field_id + "|" + std::to_string(sequence);
    const std::string token_hash = Sha256Hex(reinterpret_cast<const std::uint8_t*>(token_input.data()),
                                             token_input.size());
    if (token_hash.size() < 24U) {
        return CandidateEvidenceVerdict::kSerializationFailed;
    }
    const std::string event_id = "evt-" + token_hash.substr(0, 24U);
    const std::string frame_artifact_id = "frame-" + token_hash.substr(0, 24U) + ".rgb";
    // Core's CRITICAL confirmation gate deliberately requires the EventBundle
    // reference to equal ``RiskField.riskFieldId``.  Giving the serialized
    // RiskField an unrelated storage token would make a semantically valid
    // risk artifact permanently unverifiable.  The field ID is already the
    // typed RiskField identity, so use it as the artifact identity as well.
    const std::string risk_artifact_id = risk_field.risk_field_id;
    const std::string world_artifact_id = "world-" + token_hash.substr(0, 24U) + ".json";
    const std::string risk_json = SerializeRiskFieldV11(risk_field);
    const std::string world_json = SerializeWorldEntityV10(world_entity);
    const std::string occurred_at = EpochMillisToRfc3339(world_entity.observed_at_utc_ms);
    if (risk_json.empty() || world_json.empty() || occurred_at.empty()) {
        return CandidateEvidenceVerdict::kSerializationFailed;
    }
    const ArtifactVaultResult frame_artifact =
        artifact_vault_->Persist(frame_artifact_id, frame.rgb.data(), frame.rgb.size());
    const ArtifactVaultResult risk_artifact = artifact_vault_->Persist(
        risk_artifact_id, reinterpret_cast<const std::uint8_t*>(risk_json.data()), risk_json.size());
    const ArtifactVaultResult world_artifact = artifact_vault_->Persist(
        world_artifact_id, reinterpret_cast<const std::uint8_t*>(world_json.data()), world_json.size());
    if (!IsPersisted(frame_artifact) || !IsPersisted(risk_artifact) || !IsPersisted(world_artifact)) {
        return CandidateEvidenceVerdict::kArtifactPersistFailed;
    }
    const std::string payload_json = BuildPayloadJson(config_, event_id, occurred_at, entity, world_entity,
                                                      risk_field, risk_artifact_id, world_artifact_id);
    const std::string payload_digest = Sha256Digest(payload_json);
    if (payload_json.empty() || !IsSha256Digest(payload_digest)) {
        return CandidateEvidenceVerdict::kSerializationFailed;
    }
    CandidateEvidenceDraft result;
    result.status = EdgeEventStatus::kCandidate;
    result.candidate = {event_id, sequence, config_.edge_device_id, payload_digest, payload_json, 3U};
    result.evidence = {
        {event_id, frame_artifact_id, "application/octet-stream", frame_artifact.artifact.local_path,
         frame_artifact.artifact.content_digest},
        {event_id, risk_artifact_id, "application/json", risk_artifact.artifact.local_path,
         risk_artifact.artifact.content_digest},
        {event_id, world_artifact_id, "application/json", world_artifact.artifact.local_path,
         world_artifact.artifact.content_digest},
    };
    *draft = std::move(result);
    return CandidateEvidenceVerdict::kBuilt;
}

}  // namespace ksi::edge

#include "ksi/edge/world_entity.hpp"

#include "ksi/edge/crypto.hpp"

#include <cmath>
#include <cstdio>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace ksi::edge {

namespace {

bool IsFinite(const Vec3& value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool IsLocalizationState(const std::string& value) {
    return value == "CONFIRMED" || value == "LIKELY" || value == "BOUNDARY_UNCERTAIN" ||
           value == "INSUFFICIENT_OBSERVATION" || value == "STALE" || value == "LOST";
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

std::string EpochMillisToUtc(std::int64_t epoch_millis, bool z_suffix) {
    if (epoch_millis <= 0) {
        return {};
    }
    const std::time_t seconds = static_cast<std::time_t>(epoch_millis / 1000);
    const int millis = static_cast<int>(epoch_millis % 1000);
    std::tm utc_time {};
    if (gmtime_r(&seconds, &utc_time) == nullptr) {
        return {};
    }
    char buffer[48] = {};
    // WorldEntity itself uses RFC 3339 milliseconds.  Python's
    // world_entity_fingerprint calls datetime.isoformat(): it omits a zero
    // fractional part, but expands a non-zero millisecond to six digits.
    // Keeping these two forms explicit prevents a native Edge event from
    // carrying a fingerprint Core cannot reproduce from the saved WorldEntity.
    const int written = z_suffix
                            ? std::snprintf(buffer, sizeof(buffer),
                                            "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                                            utc_time.tm_year + 1900, utc_time.tm_mon + 1,
                                            utc_time.tm_mday, utc_time.tm_hour,
                                            utc_time.tm_min, utc_time.tm_sec, millis)
                            : (millis == 0
                                   ? std::snprintf(buffer, sizeof(buffer),
                                                   "%04d-%02d-%02dT%02d:%02d:%02d+00:00",
                                                   utc_time.tm_year + 1900, utc_time.tm_mon + 1,
                                                   utc_time.tm_mday, utc_time.tm_hour,
                                                   utc_time.tm_min, utc_time.tm_sec)
                                   : std::snprintf(buffer, sizeof(buffer),
                                                   "%04d-%02d-%02dT%02d:%02d:%02d.%03d000+00:00",
                                                   utc_time.tm_year + 1900, utc_time.tm_mon + 1,
                                                   utc_time.tm_mday, utc_time.tm_hour,
                                                   utc_time.tm_min, utc_time.tm_sec, millis));
    if (written <= 0 || static_cast<std::size_t>(written) >= sizeof(buffer)) {
        return {};
    }
    return buffer;
}

void AppendDouble(std::ostringstream* output, double value, int precision) {
    *output << std::fixed << std::setprecision(precision) << value;
}

}  // namespace

const char* ToString(WorldEntityVerdict verdict) {
    switch (verdict) {
        case WorldEntityVerdict::kValid:
            return "VALID";
        case WorldEntityVerdict::kMissingRequiredField:
            return "MISSING_REQUIRED_FIELD";
        case WorldEntityVerdict::kMalformedNumeric:
            return "MALFORMED_NUMERIC";
        case WorldEntityVerdict::kInvalidLocalizationState:
            return "INVALID_LOCALIZATION_STATE";
        case WorldEntityVerdict::kInvalidClassificationLineage:
            return "INVALID_CLASSIFICATION_LINEAGE";
    }
    return "UNKNOWN";
}

WorldEntityVerdict ValidateNativeWorldEntity(const NativeWorldEntity& entity) {
    if (entity.entity_id.empty() || entity.entity_class.empty() || entity.observed_at_utc_ms <= 0 ||
        entity.site_frame.empty() || entity.track_id.empty() || entity.model_versions.empty() ||
        entity.calibration_profile_id.empty()) {
        return WorldEntityVerdict::kMissingRequiredField;
    }
    if (!IsFinite(entity.position_m) || !IsFinite(entity.velocity_mps) ||
        !std::isfinite(entity.classification_confidence) || entity.classification_confidence < 0.0 ||
        entity.classification_confidence > 1.0) {
        return WorldEntityVerdict::kMalformedNumeric;
    }
    for (const double value : entity.position_covariance) {
        if (!std::isfinite(value)) {
            return WorldEntityVerdict::kMalformedNumeric;
        }
    }
    if (entity.position_covariance[0] < 0.0 || entity.position_covariance[4] < 0.0 ||
        entity.position_covariance[8] < 0.0 ||
        std::fabs(entity.position_covariance[1] - entity.position_covariance[3]) > 1e-12 ||
        std::fabs(entity.position_covariance[2] - entity.position_covariance[6]) > 1e-12 ||
        std::fabs(entity.position_covariance[5] - entity.position_covariance[7]) > 1e-12) {
        return WorldEntityVerdict::kMalformedNumeric;
    }
    if (!IsLocalizationState(entity.localization_state)) {
        return WorldEntityVerdict::kInvalidLocalizationState;
    }
    if (entity.classification.ontology_version.empty() || entity.classification.source_taxonomy.empty() ||
        entity.classification.source_class_name.empty()) {
        return WorldEntityVerdict::kInvalidClassificationLineage;
    }
    for (const auto& model : entity.model_versions) {
        if (model.first.empty() || model.second.empty()) {
            return WorldEntityVerdict::kMissingRequiredField;
        }
    }
    for (const std::string& observation_id : entity.observation_ids) {
        if (observation_id.empty()) {
            return WorldEntityVerdict::kMissingRequiredField;
        }
    }
    return WorldEntityVerdict::kValid;
}

std::string WorldEntityFingerprint(const NativeWorldEntity& entity) {
    if (ValidateNativeWorldEntity(entity) != WorldEntityVerdict::kValid) {
        return {};
    }
    std::ostringstream canonical;
    canonical << entity.entity_class << '|' << entity.classification.ontology_version << '|'
              << entity.classification.source_taxonomy << '|'
              << entity.classification.source_class_id << '|'
              << entity.classification.source_class_name << '|' << entity.site_frame << '|'
              << entity.track_id << '|';
    AppendDouble(&canonical, entity.position_m.x, 9);
    canonical << ',';
    AppendDouble(&canonical, entity.position_m.y, 9);
    canonical << ',';
    AppendDouble(&canonical, entity.position_m.z, 9);
    canonical << '|';
    for (std::size_t index = 0; index < entity.position_covariance.size(); ++index) {
        if (index != 0U) {
            canonical << ',';
        }
        AppendDouble(&canonical, entity.position_covariance[index], 12);
    }
    canonical << '|' << entity.localization_state << '|';
    for (std::size_t index = 0; index < entity.observation_ids.size(); ++index) {
        if (index != 0U) {
            canonical << ',';
        }
        canonical << entity.observation_ids[index];
    }
    canonical << '|' << EpochMillisToUtc(entity.observed_at_utc_ms, false);
    const std::string canonical_string = canonical.str();
    const std::string hex = Sha256Hex(
        reinterpret_cast<const std::uint8_t*>(canonical_string.data()), canonical_string.size());
    return hex;
}

std::string SerializeWorldEntityV10(const NativeWorldEntity& entity) {
    if (ValidateNativeWorldEntity(entity) != WorldEntityVerdict::kValid) {
        return {};
    }
    const std::string timestamp = EpochMillisToUtc(entity.observed_at_utc_ms, true);
    if (timestamp.empty()) {
        return {};
    }
    std::ostringstream output;
    output << std::setprecision(17);
    output << "{\"schemaVersion\":\"1.0\",\"entityId\":\"" << EscapeJson(entity.entity_id)
           << "\",\"class\":\"" << EscapeJson(entity.entity_class)
           << "\",\"timestamp\":\"" << timestamp << "\",\"siteFrame\":\""
           << EscapeJson(entity.site_frame) << "\",\"pose\":{\"position\":["
           << entity.position_m.x << ',' << entity.position_m.y << ',' << entity.position_m.z
           << "],\"velocity\":[" << entity.velocity_mps.x << ',' << entity.velocity_mps.y << ','
           << entity.velocity_mps.z << "]},\"uncertainty\":{\"positionCovariance\":[";
    for (std::size_t index = 0; index < entity.position_covariance.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        output << entity.position_covariance[index];
    }
    output << "],\"classificationConfidence\":" << entity.classification_confidence
           << ",\"localizationState\":\"" << EscapeJson(entity.localization_state)
           << "\"},\"lineage\":{\"trackId\":\"" << EscapeJson(entity.track_id)
           << "\",\"modelVersions\":{";
    bool first_model = true;
    for (const auto& model : entity.model_versions) {
        if (!first_model) {
            output << ',';
        }
        first_model = false;
        output << '"' << EscapeJson(model.first) << "\":\"" << EscapeJson(model.second) << '"';
    }
    output << "},\"calibrationProfileId\":\"" << EscapeJson(entity.calibration_profile_id)
           << "\",\"observationIds\":[";
    for (std::size_t index = 0; index < entity.observation_ids.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        output << '"' << EscapeJson(entity.observation_ids[index]) << '"';
    }
    output << "],\"classificationOntologyVersion\":\""
           << EscapeJson(entity.classification.ontology_version)
           << "\",\"classificationSource\":{\"taxonomy\":\""
           << EscapeJson(entity.classification.source_taxonomy)
           << "\",\"sourceClassIds\":[" << entity.classification.source_class_id
           << "],\"sourceClassNames\":[\""
           << EscapeJson(entity.classification.source_class_name) << "\"]}}}";
    return output.str();
}

}  // namespace ksi::edge

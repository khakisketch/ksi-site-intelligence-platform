#include "ksi/edge/risk.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <cstdio>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace ksi::edge {

namespace {

bool IsFinite(const Vec3& value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool IsValidDimensions(const DimensionsM& value) {
    return std::isfinite(value.length) && std::isfinite(value.width) && std::isfinite(value.height) &&
           value.length > 0.0 && value.width > 0.0 && value.height >= 0.0;
}

bool IsValidCovariance(const PositionCovariance& value) {
    return std::isfinite(value.variance_x) && std::isfinite(value.variance_y) &&
           std::isfinite(value.variance_z) && value.variance_x >= 0.0 && value.variance_y >= 0.0 &&
           value.variance_z >= 0.0;
}

bool IsValidPolicy(const EquipmentRiskPolicy& policy) {
    return !policy.equipment_class.empty() && !policy.risk_field_policy_id.empty() &&
           !policy.calibration_profile_id.empty() && IsValidDimensions(policy.declared_footprint) &&
           std::isfinite(policy.prediction_horizon_s) &&
           std::isfinite(policy.sample_period_s) && std::isfinite(policy.covariance_sigma_multiplier) &&
           std::isfinite(policy.occlusion_expansion_m) && std::isfinite(policy.severity) &&
           policy.prediction_horizon_s > 0.0 && policy.sample_period_s > 0.0 &&
           policy.sample_period_s <= policy.prediction_horizon_s &&
           policy.covariance_sigma_multiplier >= 0.0 && policy.occlusion_expansion_m >= 0.0 &&
           policy.severity >= 0.0 && policy.severity <= 1.0;
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
    if (written <= 0 || static_cast<std::size_t>(written) >= sizeof(buffer)) {
        return {};
    }
    return buffer;
}

}  // namespace

const char* ToString(RiskBuildVerdict verdict) {
    switch (verdict) {
        case RiskBuildVerdict::kBuilt:
            return "BUILT";
        case RiskBuildVerdict::kUnknownEquipmentClass:
            return "UNKNOWN_EQUIPMENT_CLASS";
        case RiskBuildVerdict::kMissingDimensions:
            return "MISSING_DIMENSIONS";
        case RiskBuildVerdict::kMissingCovariance:
            return "MISSING_COVARIANCE";
        case RiskBuildVerdict::kMissingCalibration:
            return "MISSING_CALIBRATION";
        case RiskBuildVerdict::kCalibrationMismatch:
            return "CALIBRATION_MISMATCH";
        case RiskBuildVerdict::kMalformedObservation:
            return "MALFORMED_OBSERVATION";
        case RiskBuildVerdict::kMalformedPolicy:
            return "MALFORMED_POLICY";
    }
    return "UNKNOWN";
}

const char* ToString(RiskPolicyPackVerdict verdict) {
    switch (verdict) {
        case RiskPolicyPackVerdict::kValid:
            return "VALID";
        case RiskPolicyPackVerdict::kInvalidDigest:
            return "INVALID_DIGEST";
        case RiskPolicyPackVerdict::kMissingPackId:
            return "MISSING_PACK_ID";
        case RiskPolicyPackVerdict::kEmpty:
            return "EMPTY";
        case RiskPolicyPackVerdict::kMalformedPolicy:
            return "MALFORMED_POLICY";
        case RiskPolicyPackVerdict::kClassKeyMismatch:
            return "CLASS_KEY_MISMATCH";
    }
    return "UNKNOWN";
}

RiskPolicyPackVerdict ValidateRiskPolicyPack(const RiskPolicyPack& policy_pack) {
    if (!IsSha256Digest(policy_pack.digest)) {
        return RiskPolicyPackVerdict::kInvalidDigest;
    }
    if (policy_pack.risk_policy_pack_id.empty()) {
        return RiskPolicyPackVerdict::kMissingPackId;
    }
    if (policy_pack.by_equipment_class.empty()) {
        return RiskPolicyPackVerdict::kEmpty;
    }
    for (const auto& [equipment_class, policy] : policy_pack.by_equipment_class) {
        if (equipment_class != policy.equipment_class) {
            return RiskPolicyPackVerdict::kClassKeyMismatch;
        }
        if (!IsValidPolicy(policy)) {
            return RiskPolicyPackVerdict::kMalformedPolicy;
        }
    }
    return RiskPolicyPackVerdict::kValid;
}

ConservativeRiskEngine::ConservativeRiskEngine(RiskPolicyPack policy_pack)
    : policy_pack_(std::move(policy_pack)) {
    if (ValidateRiskPolicyPack(policy_pack_) != RiskPolicyPackVerdict::kValid) {
        throw std::invalid_argument("risk policy pack is not a complete valid native policy");
    }
}

RiskBuildResult ConservativeRiskEngine::Build(const EquipmentObservation& observation) const {
    if (observation.entity_id.empty() || observation.equipment_class.empty() ||
        observation.observed_at_utc_ms <= 0 || !IsFinite(observation.position_m) ||
        !IsFinite(observation.velocity_mps)) {
        return {RiskBuildVerdict::kMalformedObservation, std::nullopt};
    }
    const auto policy_it = policy_pack_.by_equipment_class.find(observation.equipment_class);
    if (policy_it == policy_pack_.by_equipment_class.end()) {
        return {RiskBuildVerdict::kUnknownEquipmentClass, std::nullopt};
    }
    const EquipmentRiskPolicy& policy = policy_it->second;
    if (!IsValidPolicy(policy)) {
        return {RiskBuildVerdict::kMalformedPolicy, std::nullopt};
    }
    if (!observation.measured_dimensions.has_value() ||
        !IsValidDimensions(*observation.measured_dimensions)) {
        return {RiskBuildVerdict::kMissingDimensions, std::nullopt};
    }
    if (!observation.position_covariance.has_value() ||
        !IsValidCovariance(*observation.position_covariance)) {
        return {RiskBuildVerdict::kMissingCovariance, std::nullopt};
    }
    if (observation.calibration_profile_id.empty()) {
        return {RiskBuildVerdict::kMissingCalibration, std::nullopt};
    }
    if (observation.calibration_profile_id != policy.calibration_profile_id) {
        return {RiskBuildVerdict::kCalibrationMismatch, std::nullopt};
    }

    // A measured footprint is mandatory, so this is not a policy default for a
    // missing observation.  Once a measurement exists, however, a smaller
    // transient box must not shrink a registered physical equipment envelope.
    // Taking the component-wise maximum preserves the observed geometry while
    // retaining the signed policy's conservative lower bound.
    const DimensionsM& measured_dimensions = *observation.measured_dimensions;
    const DimensionsM dimensions = {
        std::max(measured_dimensions.length, policy.declared_footprint.length),
        std::max(measured_dimensions.width, policy.declared_footprint.width),
        std::max(measured_dimensions.height, policy.declared_footprint.height),
    };
    const PositionCovariance& covariance = *observation.position_covariance;
    const double largest_variance = std::max(
        covariance.variance_x, std::max(covariance.variance_y, covariance.variance_z));
    const double covariance_margin = policy.covariance_sigma_multiplier * std::sqrt(largest_variance);
    const double occlusion_margin = observation.occluded ? policy.occlusion_expansion_m : 0.0;
    const double margin = covariance_margin + occlusion_margin;
    const Vec3 end_position = {
        observation.position_m.x + observation.velocity_mps.x * policy.prediction_horizon_s,
        observation.position_m.y + observation.velocity_mps.y * policy.prediction_horizon_s,
        observation.position_m.z + observation.velocity_mps.z * policy.prediction_horizon_s,
    };
    const double x_half = dimensions.length / 2.0;
    const double y_half = dimensions.width / 2.0;
    const double z_half = dimensions.height / 2.0;
    const double x_min = std::min(observation.position_m.x - x_half, end_position.x - x_half) - margin;
    const double x_max = std::max(observation.position_m.x + x_half, end_position.x + x_half) + margin;
    const double y_min = std::min(observation.position_m.y - y_half, end_position.y - y_half) - margin;
    const double y_max = std::max(observation.position_m.y + y_half, end_position.y + y_half) + margin;
    const double z_min = std::min(observation.position_m.z - z_half, end_position.z - z_half) - margin;
    const double z_max = std::max(observation.position_m.z + z_half, end_position.z + z_half) + margin;

    if (!std::isfinite(x_min) || !std::isfinite(x_max) || !std::isfinite(y_min) ||
        !std::isfinite(y_max) || !std::isfinite(z_min) || !std::isfinite(z_max)) {
        return {RiskBuildVerdict::kMalformedObservation, std::nullopt};
    }
    const std::int64_t horizon_ms =
        static_cast<std::int64_t>(policy.prediction_horizon_s * 1000.0);
    if (horizon_ms <= 0 ||
        observation.observed_at_utc_ms > std::numeric_limits<std::int64_t>::max() - horizon_ms) {
        return {RiskBuildVerdict::kMalformedPolicy, std::nullopt};
    }
    EdgeRiskField field;
    field.risk_field_id = "risk-" + observation.entity_id + "-" +
                          std::to_string(observation.observed_at_utc_ms);
    field.source_entity_id = observation.entity_id;
    field.hazard_type = "EQUIPMENT_FOOTPRINT";
    field.valid_from_utc_ms = observation.observed_at_utc_ms;
    field.valid_to_utc_ms = observation.observed_at_utc_ms + horizon_ms;
    field.geometry.vertices = {{{x_min, y_min}, {x_max, y_min}, {x_max, y_max}, {x_min, y_max}}};
    field.geometry.z_min_m = z_min;
    field.geometry.z_max_m = z_max;
    field.policy_id = policy.risk_field_policy_id;
    field.severity = policy.severity;
    field.prediction_horizon_s = policy.prediction_horizon_s;
    field.uncertainty_margin_m = margin;
    field.occlusion_expanded = observation.occluded;
    field.risk_policy_pack_digest = policy_pack_.digest;
    field.calibration_profile_id = policy.calibration_profile_id;
    field.source_timestamp_utc_ms = observation.observed_at_utc_ms;
    return {RiskBuildVerdict::kBuilt, field};
}

std::string SerializeRiskFieldV11(const EdgeRiskField& field) {
    const std::string valid_from = EpochMillisToRfc3339(field.valid_from_utc_ms);
    const std::string valid_to = EpochMillisToRfc3339(field.valid_to_utc_ms);
    const std::string source_timestamp = EpochMillisToRfc3339(field.source_timestamp_utc_ms);
    if (valid_from.empty() || valid_to.empty() || source_timestamp.empty()) {
        return {};
    }
    std::ostringstream output;
    output << std::setprecision(17);
    output << "{\"schemaVersion\":\"1.1\",\"riskFieldId\":\""
           << EscapeJson(field.risk_field_id) << "\",\"type\":\"PREDICTED\",\"hazardType\":\""
           << EscapeJson(field.hazard_type) << "\",\"sourceEntityIds\":[\""
           << EscapeJson(field.source_entity_id) << "\"],\"validity\":{\"from\":\""
           << valid_from << "\",\"to\":\"" << valid_to
           << "\"},\"geometry\":{\"format\":\"EXTRUDED_POLYGON\",\"payload\":{\"vertices\":[";
    for (std::size_t index = 0; index < field.geometry.vertices.size(); ++index) {
        const PolygonPoint& point = field.geometry.vertices[index];
        if (index != 0) {
            output << ',';
        }
        output << '[' << point.x << ',' << point.y << ']';
    }
    output << "],\"zMinM\":" << field.geometry.z_min_m << ",\"zMaxM\":"
           << field.geometry.z_max_m << "}},\"riskModel\":{\"policyId\":\""
           << EscapeJson(field.policy_id) << "\",\"severity\":" << field.severity
           << ",\"predictionHorizonSeconds\":" << field.prediction_horizon_s
           << "},\"uncertainty\":{\"marginM\":" << field.uncertainty_margin_m
           << ",\"occlusionExpanded\":" << (field.occlusion_expanded ? "true" : "false")
           << "},\"lineage\":{\"riskPolicyPackDigest\":\""
           << EscapeJson(field.risk_policy_pack_digest) << "\",\"calibrationProfileId\":\""
           << EscapeJson(field.calibration_profile_id) << "\",\"sourceTimestamp\":\""
           << source_timestamp << "\"}}";
    return output.str();
}

}  // namespace ksi::edge

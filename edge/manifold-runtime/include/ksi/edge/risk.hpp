// Conservative predicted Equipment RiskField v1.1 builder.

// Unknown equipment, absent measured dimensions/covariance/calibration, and
// mismatched policy calibration are typed failures. No geometric "default"
// exists: a smaller invented footprint would be an unsafe risk-field shrink.

#ifndef KSI_EDGE_RISK_HPP
#define KSI_EDGE_RISK_HPP

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "ksi/edge/telemetry.hpp"

namespace ksi::edge {

struct DimensionsM {
    double length = 0.0;
    double width = 0.0;
    double height = 0.0;
};

struct PositionCovariance {
    // Diagonal position covariance in square metres. A full covariance may be
    // reduced upstream only after PSD validation; missing/negative/nonfinite is rejected.
    double variance_x = 0.0;
    double variance_y = 0.0;
    double variance_z = 0.0;
};

struct EquipmentObservation {
    std::string entity_id;
    std::string equipment_class;
    Vec3 position_m;
    Vec3 velocity_mps;
    std::optional<DimensionsM> measured_dimensions;
    std::optional<PositionCovariance> position_covariance;
    std::string calibration_profile_id;
    std::int64_t observed_at_utc_ms = 0;
    bool occluded = false;
};

struct EquipmentRiskPolicy {
    std::string equipment_class;
    std::string risk_field_policy_id;
    std::string calibration_profile_id;
    // Contract-required declared footprint.  It is never substituted for a
    // missing per-observation measured dimension (that remains a typed
    // failure), but it is a conservative lower bound when a present
    // measurement is implausibly smaller than the registered equipment.
    DimensionsM declared_footprint;
    double prediction_horizon_s = 0.0;
    double sample_period_s = 0.0;
    double covariance_sigma_multiplier = 0.0;
    double occlusion_expansion_m = 0.0;
    double severity = 0.0;
};

struct RiskPolicyPack {
    std::string digest;
    std::string risk_policy_pack_id;
    std::map<std::string, EquipmentRiskPolicy> by_equipment_class;
};

enum class RiskPolicyPackVerdict {
    kValid,
    kInvalidDigest,
    kMissingPackId,
    kEmpty,
    kMalformedPolicy,
    kClassKeyMismatch,
};

const char* ToString(RiskPolicyPackVerdict verdict);
RiskPolicyPackVerdict ValidateRiskPolicyPack(const RiskPolicyPack& policy_pack);

struct PolygonPoint {
    double x = 0.0;
    double y = 0.0;
};

struct ExtrudedPolygon {
    std::array<PolygonPoint, 4> vertices;
    double z_min_m = 0.0;
    double z_max_m = 0.0;
};

struct EdgeRiskField {
    std::string risk_field_id;
    std::string source_entity_id;
    std::string hazard_type;
    std::int64_t valid_from_utc_ms = 0;
    std::int64_t valid_to_utc_ms = 0;
    ExtrudedPolygon geometry;
    std::string policy_id;
    double severity = 0.0;
    double prediction_horizon_s = 0.0;
    double uncertainty_margin_m = 0.0;
    bool occlusion_expanded = false;
    std::string risk_policy_pack_digest;
    std::string calibration_profile_id;
    std::int64_t source_timestamp_utc_ms = 0;
};

enum class RiskBuildVerdict {
    kBuilt,
    kUnknownEquipmentClass,
    kMissingDimensions,
    kMissingCovariance,
    kMissingCalibration,
    kCalibrationMismatch,
    kMalformedObservation,
    kMalformedPolicy,
};

const char* ToString(RiskBuildVerdict verdict);

struct RiskBuildResult {
    RiskBuildVerdict verdict = RiskBuildVerdict::kMalformedObservation;
    std::optional<EdgeRiskField> field;
};

class ConservativeRiskEngine {
public:
    explicit ConservativeRiskEngine(RiskPolicyPack policy_pack);

    RiskBuildResult Build(const EquipmentObservation& observation) const;

private:
    RiskPolicyPack policy_pack_;
};

// Deterministic RiskField v1.1 JSON. The caller persists it as evidence; this
// serializer intentionally emits only EXTRUDED_POLYGON and required lineage.
std::string SerializeRiskFieldV11(const EdgeRiskField& field);

}  // namespace ksi::edge

#endif  // KSI_EDGE_RISK_HPP

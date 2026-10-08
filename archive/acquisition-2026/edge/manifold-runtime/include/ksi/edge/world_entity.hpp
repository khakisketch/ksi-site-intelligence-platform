// Native producer for the WorldEntity v1.0 wire contract.

#ifndef KSI_EDGE_WORLD_ENTITY_HPP
#define KSI_EDGE_WORLD_ENTITY_HPP

#include <array>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "ksi/edge/telemetry.hpp"

namespace ksi::edge {

struct NativeClassificationLineage {
    std::string ontology_version;
    std::string source_taxonomy;
    std::uint32_t source_class_id = 0;
    std::string source_class_name;
};

struct NativeWorldEntity {
    std::string entity_id;
    std::string entity_class;
    std::int64_t observed_at_utc_ms = 0;
    std::string site_frame;
    Vec3 position_m;
    Vec3 velocity_mps;
    std::array<double, 9> position_covariance {};
    double classification_confidence = 0.0;
    // A native single-frame projection must not claim CONFIRMED.  A downstream
    // multi-view fusion stage may produce a stronger state under its own gate.
    std::string localization_state = "INSUFFICIENT_OBSERVATION";
    std::string track_id;
    std::map<std::string, std::string> model_versions;
    std::string calibration_profile_id;
    std::vector<std::string> observation_ids;
    NativeClassificationLineage classification;
};

enum class WorldEntityVerdict {
    kValid,
    kMissingRequiredField,
    kMalformedNumeric,
    kInvalidLocalizationState,
    kInvalidClassificationLineage,
};

const char* ToString(WorldEntityVerdict verdict);
WorldEntityVerdict ValidateNativeWorldEntity(const NativeWorldEntity& entity);

// Contract-shaped JSON (`world-entity.v1.json`). Empty output means validation
// failed; callers must emit a typed drop rather than send a partial entity.
std::string SerializeWorldEntityV10(const NativeWorldEntity& entity);

// Same purpose as Python world_entity_fingerprint: excludes entity_id but
// commits to class, lineage, site frame, position, covariance, state,
// observation lineage, and timestamp.
std::string WorldEntityFingerprint(const NativeWorldEntity& entity);

}  // namespace ksi::edge

#endif  // KSI_EDGE_WORLD_ENTITY_HPP

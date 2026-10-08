// Native EventBundle v1.2 + evidence artifact producer.

#ifndef KSI_EDGE_EVIDENCE_BUILDER_HPP
#define KSI_EDGE_EVIDENCE_BUILDER_HPP

#include <string>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/pipeline.hpp"

namespace ksi::edge {

struct NativeEvidenceConfig {
    std::string edge_device_id;
    std::string mission_id;
    std::string site_id;
    std::string edge_version;
};

// Produces only Edge-assertable EventBundle status `CANDIDATE`, stores immutable
// RGB/RiskField/WorldEntity bytes first, and then gives the SQLite journal an
// atomic candidate+artifact plan.  It does not call network code or make a
// CONFIRMED_EVENT claim.
class NativeCandidateEvidenceBuilder final : public ICandidateEvidenceBuilder {
public:
    NativeCandidateEvidenceBuilder(NativeEvidenceConfig config, ArtifactVault* artifact_vault,
                                   SqliteStoreForward* store_forward);

    CandidateEvidenceVerdict Build(const FramePacket& frame, const TrackedWorldEntity& entity,
                                   const NativeWorldEntity& world_entity,
                                   const EdgeRiskField& risk_field,
                                   CandidateEvidenceDraft* draft) override;

private:
    NativeEvidenceConfig config_;
    ArtifactVault* artifact_vault_;
    SqliteStoreForward* store_forward_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_EVIDENCE_BUILDER_HPP

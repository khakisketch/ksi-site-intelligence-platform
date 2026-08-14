// Signed-profile calibrated ground-plane projector.
//
// This adapter intentionally turns incomplete pose/calibration inputs into
// typed drops. It never synthesizes camera intrinsics, a site transform,
// equipment dimensions, covariance, or an occurrence timestamp.

#ifndef KSI_EDGE_CALIBRATED_PROJECTOR_HPP
#define KSI_EDGE_CALIBRATED_PROJECTOR_HPP

#include <string>

#include "ksi/edge/pipeline.hpp"
#include "ksi/edge/runtime_profile.hpp"

namespace ksi::edge {

class ProfiledGroundPlaneProjector final : public IWorldProjector {
public:
    explicit ProfiledGroundPlaneProjector(NativeRuntimeProfile profile);

    WorldProjectionVerdict Project(const TrackedWorldEntity& entity,
                                   ProjectedWorldEntity* projection) override;

private:
    NativeRuntimeProfile profile_;
    std::string site_frame_id_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_CALIBRATED_PROJECTOR_HPP

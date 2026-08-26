#include "waypoint_v3_upload_only.hpp"

#include <dji_error.h>
#include <dji_waypoint_v3.h>

#include <limits>

namespace ksi::edge::flight_execution {

WaypointUploadOnlyResult UploadKmzWithoutAction(const std::uint8_t* bytes,
                                                const std::size_t size) noexcept {
    WaypointUploadOnlyResult result;
    if (bytes == nullptr || size == 0U || size > std::numeric_limits<std::uint32_t>::max()) {
        return result;
    }

    result.init_code = DjiWaypointV3_Init();
    if (result.init_code != DJI_RETURN_CODE_OK) {
        return result;
    }

    result.upload_attempted = true;
    result.upload_code = DjiWaypointV3_UploadKmzFile(bytes, static_cast<std::uint32_t>(size));
    result.deinit_code = DjiWaypointV3_DeInit();
    return result;
}

}  // namespace ksi::edge::flight_execution

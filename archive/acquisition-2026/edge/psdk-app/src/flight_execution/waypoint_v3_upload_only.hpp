#pragma once

#include <cstddef>
#include <cstdint>

namespace ksi::edge::flight_execution {

struct WaypointUploadOnlyResult {
    static constexpr std::uint64_t kNotCalled = UINT64_MAX;

    std::uint64_t init_code{kNotCalled};
    std::uint64_t upload_code{kNotCalled};
    std::uint64_t deinit_code{kNotCalled};
    bool upload_attempted{false};
};

// HIL-only S1 surface. This function cannot start, stop, pause, or resume a mission.
WaypointUploadOnlyResult UploadKmzWithoutAction(const std::uint8_t* bytes,
                                                std::size_t size) noexcept;

}  // namespace ksi::edge::flight_execution

// Bounded telemetry timeline and frame alignment evidence.

#ifndef KSI_EDGE_TELEMETRY_HPP
#define KSI_EDGE_TELEMETRY_HPP

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <optional>
#include <vector>

#include "ksi/edge/frame_queue.hpp"

namespace ksi::edge {

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

// DJI PSDK's quaternion convention is Hamilton (w, x, y, z), rotating the
// aircraft body FRD frame into its ground NED frame.  This is deliberately a
// raw pose input: a calibrated projector must still establish the camera and
// site-frame transforms before it can produce a WorldEntity.
struct BodyFrdToGroundNedQuaternion {
    double w = 0.0;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

// Geographic and gimbal inputs remain raw PSDK measurements until the signed
// runtime profile maps them into the Mission Contract's site frame.  Keeping
// the source callback time prevents a worker from treating a stale cache value
// as a frame-synchronous pose.
struct Wgs84Position {
    double latitude_rad = 0.0;
    double longitude_rad = 0.0;
    double altitude_m = 0.0;
};

struct PositionAccuracy {
    double horizontal_sigma_m = 0.0;
    double vertical_sigma_m = 0.0;
};

struct GimbalNedEuler {
    double pitch_rad = 0.0;
    double roll_rad = 0.0;
    double yaw_rad = 0.0;
};

struct TimedWgs84Position {
    Wgs84Position value;
    MonotonicNs received_monotonic_ns = 0;
};

struct TimedPositionAccuracy {
    PositionAccuracy value;
    MonotonicNs received_monotonic_ns = 0;
};

struct TimedGimbalNedEuler {
    GimbalNedEuler value;
    MonotonicNs received_monotonic_ns = 0;
};

// The FC velocity topic arrives independently of HARD_SYNC.  Preserve its
// callback time so a stopped or stale velocity stream cannot silently shrink
// the predicted RiskField once an RGB sensor timestamp becomes available.
struct TimedVelocityMps {
    Vec3 value;
    MonotonicNs received_monotonic_ns = 0;
};

struct TelemetrySample {
    MonotonicNs received_monotonic_ns = 0;
    // 0 means no sensor/FC timestamp. It must never be substituted with receive time.
    MonotonicNs sensor_timestamp_ns = 0;
    Vec3 position_m;
    Vec3 velocity_mps;
    bool hard_sync = false;
    // Present only when the FC HardSync packet carried a finite, non-zero
    // quaternion.  Absence is allowed for non-pose telemetry consumers; it
    // must not be replaced with an identity pose by a projector.
    std::optional<BodyFrdToGroundNedQuaternion> body_frd_to_ground_ned;
    std::optional<TimedWgs84Position> wgs84_position;
    std::optional<TimedPositionAccuracy> position_accuracy;
    std::optional<TimedGimbalNedEuler> gimbal_ned_euler;
    std::optional<TimedVelocityMps> velocity_mps_measurement;
};

enum class TelemetryVerdict {
    kRecorded,
    // PSDK callbacks must not wait behind a worker's alignment scan.  A
    // contended callback therefore drops this telemetry sample explicitly
    // instead of blocking the PSDK root thread.
    kQueueBusy,
    kClockRollback,
    kMalformed,
};

enum class AlignmentVerdict {
    kSensorAligned,
    kReceiveTimeOnly,
    kNoTelemetry,
    kOutsideTolerance,
};

const char* ToString(TelemetryVerdict verdict);
const char* ToString(AlignmentVerdict verdict);

struct TelemetryAlignment {
    AlignmentVerdict verdict = AlignmentVerdict::kNoTelemetry;
    std::optional<TelemetrySample> sample;
    std::int64_t receive_delta_ns = 0;
    // Populated only when both sides supplied a sensor timestamp.  A receive
    // timestamp is never copied into this field, so HIL reports cannot mistake
    // transport timing for sensor alignment.
    std::int64_t sensor_delta_ns = 0;

    bool has_sensor_alignment() const { return verdict == AlignmentVerdict::kSensorAligned; }
};

class TelemetryTimeline {
public:
    explicit TelemetryTimeline(std::size_t capacity);

    TelemetryVerdict Record(const TelemetrySample& sample);
    // Callback-safe counterpart to Record(): it writes only into the
    // preallocated ring and never waits for the worker-side mutex.
    TelemetryVerdict RecordFromCallback(const TelemetrySample& sample) noexcept;
    // The same tolerance applies to the strongest clock available: sensor
    // timestamps when both sources provide them, otherwise receive timestamps.
    TelemetryAlignment Align(const FrameMetadata& frame, std::int64_t max_delta_ns) const;
    std::size_t size() const;

private:
    TelemetryVerdict RecordLocked(const TelemetrySample& sample) noexcept;

    const std::size_t capacity_;
    mutable std::mutex mutex_;
    std::vector<TelemetrySample> samples_;
    std::size_t next_index_ = 0;
    bool full_ = false;
    MonotonicNs last_received_monotonic_ns_ = 0;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_TELEMETRY_HPP

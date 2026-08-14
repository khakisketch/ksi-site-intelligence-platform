#include "ksi/edge/telemetry.hpp"

#include <cmath>
#include <limits>
#include <stdexcept>

namespace ksi::edge {

namespace {

bool IsFinite(const Vec3& value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool IsValidQuaternion(const BodyFrdToGroundNedQuaternion& value) {
    if (!std::isfinite(value.w) || !std::isfinite(value.x) || !std::isfinite(value.y) ||
        !std::isfinite(value.z)) {
        return false;
    }
    // Quaternion scale does not change its represented rotation, so the
    // timeline only rejects a zero/overflowed pose.  A calibrated projector
    // owns normalization and camera/site-frame validation; this ingress layer
    // must not invent a replacement identity pose.
    const double magnitude = std::hypot(std::hypot(value.w, value.x),
                                        std::hypot(value.y, value.z));
    return std::isfinite(magnitude) && magnitude > 0.0;
}

bool IsValidWgs84(const TimedWgs84Position& value) {
    return value.received_monotonic_ns > 0 && std::isfinite(value.value.latitude_rad) &&
           std::isfinite(value.value.longitude_rad) && std::isfinite(value.value.altitude_m) &&
           value.value.latitude_rad >= -1.5707963267948966 &&
           value.value.latitude_rad <= 1.5707963267948966 &&
           value.value.longitude_rad >= -3.141592653589793 &&
           value.value.longitude_rad <= 3.141592653589793;
}

bool IsValidAccuracy(const TimedPositionAccuracy& value) {
    return value.received_monotonic_ns > 0 &&
           std::isfinite(value.value.horizontal_sigma_m) &&
           std::isfinite(value.value.vertical_sigma_m) && value.value.horizontal_sigma_m >= 0.0 &&
           value.value.vertical_sigma_m >= 0.0;
}

bool IsValidGimbal(const TimedGimbalNedEuler& value) {
    return value.received_monotonic_ns > 0 && std::isfinite(value.value.pitch_rad) &&
           std::isfinite(value.value.roll_rad) && std::isfinite(value.value.yaw_rad);
}

bool IsValidVelocity(const TimedVelocityMps& value) {
    return value.received_monotonic_ns > 0 && IsFinite(value.value);
}

std::int64_t AbsoluteDifference(MonotonicNs left, MonotonicNs right) {
    // Both timestamps are positive monotonic values. Avoid signed subtraction overflow.
    return left >= right ? left - right : right - left;
}

}  // namespace

const char* ToString(TelemetryVerdict verdict) {
    switch (verdict) {
        case TelemetryVerdict::kRecorded:
            return "RECORDED";
        case TelemetryVerdict::kQueueBusy:
            return "QUEUE_BUSY";
        case TelemetryVerdict::kClockRollback:
            return "CLOCK_ROLLBACK";
        case TelemetryVerdict::kMalformed:
            return "MALFORMED";
    }
    return "UNKNOWN";
}

const char* ToString(AlignmentVerdict verdict) {
    switch (verdict) {
        case AlignmentVerdict::kSensorAligned:
            return "SENSOR_ALIGNED";
        case AlignmentVerdict::kReceiveTimeOnly:
            return "RECEIVE_TIME_ONLY";
        case AlignmentVerdict::kNoTelemetry:
            return "NO_TELEMETRY";
        case AlignmentVerdict::kOutsideTolerance:
            return "OUTSIDE_TOLERANCE";
    }
    return "UNKNOWN";
}

TelemetryTimeline::TelemetryTimeline(std::size_t capacity) : capacity_(capacity), samples_(capacity) {
    if (capacity == 0) {
        throw std::invalid_argument("telemetry timeline requires non-zero capacity");
    }
}

TelemetryVerdict TelemetryTimeline::RecordLocked(const TelemetrySample& sample) noexcept {
    if (sample.received_monotonic_ns <= 0 || !IsFinite(sample.position_m) ||
        !IsFinite(sample.velocity_mps) || sample.sensor_timestamp_ns < 0 ||
        (sample.body_frd_to_ground_ned.has_value() &&
         !IsValidQuaternion(*sample.body_frd_to_ground_ned)) ||
        (sample.wgs84_position.has_value() && !IsValidWgs84(*sample.wgs84_position)) ||
        (sample.position_accuracy.has_value() && !IsValidAccuracy(*sample.position_accuracy)) ||
        (sample.gimbal_ned_euler.has_value() && !IsValidGimbal(*sample.gimbal_ned_euler)) ||
        (sample.velocity_mps_measurement.has_value() &&
         !IsValidVelocity(*sample.velocity_mps_measurement))) {
        return TelemetryVerdict::kMalformed;
    }
    if (last_received_monotonic_ns_ != 0 &&
        sample.received_monotonic_ns < last_received_monotonic_ns_) {
        return TelemetryVerdict::kClockRollback;
    }
    samples_[next_index_] = sample;
    next_index_ = (next_index_ + 1U) % capacity_;
    full_ = full_ || next_index_ == 0;
    last_received_monotonic_ns_ = sample.received_monotonic_ns;
    return TelemetryVerdict::kRecorded;
}

TelemetryVerdict TelemetryTimeline::Record(const TelemetrySample& sample) {
    std::lock_guard<std::mutex> lock(mutex_);
    return RecordLocked(sample);
}

TelemetryVerdict TelemetryTimeline::RecordFromCallback(const TelemetrySample& sample) noexcept {
    if (!mutex_.try_lock()) {
        return TelemetryVerdict::kQueueBusy;
    }
    const TelemetryVerdict verdict = RecordLocked(sample);
    mutex_.unlock();
    return verdict;
}

TelemetryAlignment TelemetryTimeline::Align(const FrameMetadata& frame,
                                            std::int64_t max_delta_ns) const {
    if (frame.received_monotonic_ns <= 0 || frame.sensor_timestamp_ns < 0 || max_delta_ns < 0) {
        return {};
    }
    std::lock_guard<std::mutex> lock(mutex_);
    const std::size_t count = full_ ? capacity_ : next_index_;
    if (count == 0) {
        return {};
    }
    const TelemetrySample* closest_receive = nullptr;
    std::int64_t closest_receive_delta = std::numeric_limits<std::int64_t>::max();
    const TelemetrySample* closest_sensor = nullptr;
    std::int64_t closest_sensor_delta = std::numeric_limits<std::int64_t>::max();
    for (std::size_t index = 0; index < count; ++index) {
        const TelemetrySample& sample = samples_[index];
        const std::int64_t receive_delta =
            AbsoluteDifference(frame.received_monotonic_ns, sample.received_monotonic_ns);
        if (receive_delta < closest_receive_delta) {
            closest_receive = &sample;
            closest_receive_delta = receive_delta;
        }
        if (frame.sensor_timestamp_ns > 0 && sample.sensor_timestamp_ns > 0) {
            const std::int64_t sensor_delta =
                AbsoluteDifference(frame.sensor_timestamp_ns, sample.sensor_timestamp_ns);
            if (sensor_delta < closest_sensor_delta) {
                closest_sensor = &sample;
                closest_sensor_delta = sensor_delta;
            }
        }
    }
    if (closest_receive == nullptr) {
        return {};
    }
    if (closest_sensor != nullptr) {
        const std::int64_t receive_delta = AbsoluteDifference(
            frame.received_monotonic_ns, closest_sensor->received_monotonic_ns);
        if (closest_sensor_delta > max_delta_ns) {
            return {AlignmentVerdict::kOutsideTolerance, *closest_sensor, receive_delta,
                    closest_sensor_delta};
        }
        return {AlignmentVerdict::kSensorAligned, *closest_sensor, receive_delta,
                closest_sensor_delta};
    }
    if (closest_receive_delta > max_delta_ns) {
        return {AlignmentVerdict::kOutsideTolerance, *closest_receive, closest_receive_delta, 0};
    }
    // The PSDK RGB callback has no sensor timestamp today. Do not upgrade receive-time
    // proximity to sensor alignment; HIL p95 sensor timing uses this predicate only.
    return {AlignmentVerdict::kReceiveTimeOnly, *closest_receive, closest_receive_delta, 0};
}

std::size_t TelemetryTimeline::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return full_ ? capacity_ : next_index_;
}

}  // namespace ksi::edge

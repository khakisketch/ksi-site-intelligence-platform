#include "ksi/edge/calibrated_projector.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>

namespace ksi::edge {

namespace {

constexpr double kWgs84SemiMajorM = 6378137.0;
constexpr double kWgs84FirstEccentricitySquared = 6.6943799901413165e-3;
constexpr double kMinimumRayZ = 1e-9;

bool IsFinite(double value) { return std::isfinite(value); }

bool IsFinite(const Vec3& value) {
    return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
}

bool IsSafeText(const std::string& value) {
    if (value.empty()) return false;
    for (const unsigned char character : value) {
        if (character == 0U || character < 0x20U || character == 0x7FU) return false;
    }
    return true;
}

double QuaternionNorm(const NativeQuaternion& value) {
    return std::hypot(std::hypot(value.w, value.x), std::hypot(value.y, value.z));
}

Vec3 RotateQuaternion(const NativeQuaternion& quaternion, const Vec3& vector) {
    // q * v * q^-1 for a unit Hamilton quaternion. The profile parser and
    // constructor independently validate unit length before this is called.
    const Vec3 qv {quaternion.x, quaternion.y, quaternion.z};
    const Vec3 cross = {
        qv.y * vector.z - qv.z * vector.y,
        qv.z * vector.x - qv.x * vector.z,
        qv.x * vector.y - qv.y * vector.x,
    };
    const Vec3 second_cross = {
        qv.y * cross.z - qv.z * cross.y,
        qv.z * cross.x - qv.x * cross.z,
        qv.x * cross.y - qv.y * cross.x,
    };
    return {
        vector.x + 2.0 * (quaternion.w * cross.x + second_cross.x),
        vector.y + 2.0 * (quaternion.w * cross.y + second_cross.y),
        vector.z + 2.0 * (quaternion.w * cross.z + second_cross.z),
    };
}

Vec3 RotateGimbalNed(const GimbalNedEuler& angles, const Vec3& vector) {
    // DJI's subscribed NO_1 topic documents pitch/roll/yaw in a gimbal-attached
    // NED reference. The profile's cameraToGimbal is the other half of this
    // convention. HIL must still prove this exact M4D stream convention before
    // a deployable profile is claimed.
    const double cp = std::cos(angles.pitch_rad);
    const double sp = std::sin(angles.pitch_rad);
    const double cr = std::cos(angles.roll_rad);
    const double sr = std::sin(angles.roll_rad);
    const double cy = std::cos(angles.yaw_rad);
    const double sy = std::sin(angles.yaw_rad);
    // Rz(yaw) * Ry(pitch) * Rx(roll), mapping gimbal axes to NED.
    return {
        (cy * cp) * vector.x + (cy * sp * sr - sy * cr) * vector.y +
            (cy * sp * cr + sy * sr) * vector.z,
        (sy * cp) * vector.x + (sy * sp * sr + cy * cr) * vector.y +
            (sy * sp * cr - cy * sr) * vector.z,
        (-sp) * vector.x + (cp * sr) * vector.y + (cp * cr) * vector.z,
    };
}

Vec3 NedToEnu(const Vec3& value) { return {value.y, value.x, -value.z}; }

Vec3 RotateEnuToSite(const NativeCalibrationProfile& calibration, const Vec3& value) {
    const auto& r = calibration.enu_to_site_rotation;
    return {
        r[0] * value.x + r[1] * value.y + r[2] * value.z,
        r[3] * value.x + r[4] * value.y + r[5] * value.z,
        r[6] * value.x + r[7] * value.y + r[8] * value.z,
    };
}

Vec3 Add(const Vec3& left, const Vec3& right) {
    return {left.x + right.x, left.y + right.y, left.z + right.z};
}

Vec3 Scale(const Vec3& value, double scale) {
    return {value.x * scale, value.y * scale, value.z * scale};
}

Vec3 Wgs84ToEcef(const Wgs84Position& position) {
    const double sin_latitude = std::sin(position.latitude_rad);
    const double cos_latitude = std::cos(position.latitude_rad);
    const double sin_longitude = std::sin(position.longitude_rad);
    const double cos_longitude = std::cos(position.longitude_rad);
    const double radius = kWgs84SemiMajorM /
                          std::sqrt(1.0 - kWgs84FirstEccentricitySquared *
                                           sin_latitude * sin_latitude);
    return {
        (radius + position.altitude_m) * cos_latitude * cos_longitude,
        (radius + position.altitude_m) * cos_latitude * sin_longitude,
        (radius * (1.0 - kWgs84FirstEccentricitySquared) + position.altitude_m) * sin_latitude,
    };
}

Vec3 Wgs84ToEnu(const Wgs84Position& position, const NativeWgs84Origin& origin) {
    const Wgs84Position origin_position = {origin.latitude_rad, origin.longitude_rad, origin.altitude_m};
    const Vec3 delta = {
        Wgs84ToEcef(position).x - Wgs84ToEcef(origin_position).x,
        Wgs84ToEcef(position).y - Wgs84ToEcef(origin_position).y,
        Wgs84ToEcef(position).z - Wgs84ToEcef(origin_position).z,
    };
    const double sin_latitude = std::sin(origin.latitude_rad);
    const double cos_latitude = std::cos(origin.latitude_rad);
    const double sin_longitude = std::sin(origin.longitude_rad);
    const double cos_longitude = std::cos(origin.longitude_rad);
    return {
        -sin_longitude * delta.x + cos_longitude * delta.y,
        -sin_latitude * cos_longitude * delta.x - sin_latitude * sin_longitude * delta.y +
            cos_latitude * delta.z,
        cos_latitude * cos_longitude * delta.x + cos_latitude * sin_longitude * delta.y +
            sin_latitude * delta.z,
    };
}

bool IsFresh(MonotonicNs frame_time, MonotonicNs source_time, std::int64_t max_age_ms) {
    if (frame_time <= 0 || source_time <= 0 || max_age_ms <= 0) return false;
    const std::int64_t delta = frame_time >= source_time ? frame_time - source_time : source_time - frame_time;
    const std::int64_t max_age_ns = max_age_ms > std::numeric_limits<std::int64_t>::max() / 1'000'000LL
                                        ? std::numeric_limits<std::int64_t>::max()
                                        : max_age_ms * 1'000'000LL;
    return delta <= max_age_ns;
}

bool IsProperRotation(const std::array<double, 9>& rotation) {
    for (const double value : rotation) {
        if (!IsFinite(value)) return false;
    }
    const auto dot_rows = [&](std::size_t left, std::size_t right) {
        return rotation[left * 3U] * rotation[right * 3U] +
               rotation[left * 3U + 1U] * rotation[right * 3U + 1U] +
               rotation[left * 3U + 2U] * rotation[right * 3U + 2U];
    };
    const double determinant =
        rotation[0] * (rotation[4] * rotation[8] - rotation[5] * rotation[7]) -
        rotation[1] * (rotation[3] * rotation[8] - rotation[5] * rotation[6]) +
        rotation[2] * (rotation[3] * rotation[7] - rotation[4] * rotation[6]);
    return std::abs(dot_rows(0U, 0U) - 1.0) <= 1e-6 &&
           std::abs(dot_rows(1U, 1U) - 1.0) <= 1e-6 &&
           std::abs(dot_rows(2U, 2U) - 1.0) <= 1e-6 &&
           std::abs(dot_rows(0U, 1U)) <= 1e-6 && std::abs(dot_rows(0U, 2U)) <= 1e-6 &&
           std::abs(dot_rows(1U, 2U)) <= 1e-6 && std::abs(determinant - 1.0) <= 1e-6;
}

bool IsValidProfile(const NativeRuntimeProfile& profile) {
    const NativeModelProfile& model = profile.model;
    const NativeCalibrationProfile& calibration = profile.calibration;
    if (!IsSafeText(profile.dispatch_id) || !IsSafeText(profile.edge_device_id) ||
        !IsSafeText(profile.mission_id) || !IsSha256Digest(profile.mission_contract_digest) ||
        !IsSha256Digest(profile.risk_policy_pack_digest) ||
        !IsSha256Digest(profile.edge_runtime_profile_digest) ||
        !IsSafeText(profile.edge_runtime_profile_id) || !IsSafeText(profile.site_id) ||
        !IsSafeText(model.model_pack_id) || !IsSafeText(model.model_id) ||
        !IsSafeText(model.onnx_artifact_id) || !IsSha256Digest(model.registered_onnx_digest) ||
        !IsSafeText(model.engine_artifact_id) || model.max_onnx_bytes == 0U ||
        model.max_engine_bytes == 0U || model.workspace_bytes == 0U ||
        model.tensor_contract.input_width == 0U || model.tensor_contract.input_height == 0U ||
        model.tensor_contract.query_count == 0U || model.tensor_contract.class_count == 0U ||
        !std::isfinite(model.score_threshold) || model.score_threshold < 0.0F ||
        model.score_threshold > 1.0F || model.top_k == 0U || model.class_bindings.empty() ||
        !IsSafeText(model.ontology_version) || !IsSafeText(model.source_taxonomy) ||
        !IsSafeText(calibration.calibration_profile_id) || !IsSafeText(calibration.site_frame_crs) ||
        !IsSafeText(calibration.site_frame_vertical_datum) ||
        !IsSafeText(calibration.site_frame_transform_version) ||
        !IsFinite(calibration.wgs84_origin.latitude_rad) ||
        !IsFinite(calibration.wgs84_origin.longitude_rad) ||
        !IsFinite(calibration.wgs84_origin.altitude_m) ||
        std::abs(calibration.wgs84_origin.latitude_rad) > 1.5707963267948966 ||
        std::abs(calibration.wgs84_origin.longitude_rad) > 3.141592653589793 ||
        !IsProperRotation(calibration.enu_to_site_rotation) ||
        !IsFinite(calibration.enu_to_site_translation_m) || !IsFinite(calibration.ground_plane_up_m) ||
        calibration.intrinsics.reference_width == 0U || calibration.intrinsics.reference_height == 0U ||
        !IsFinite(calibration.intrinsics.focal_x_px) || !IsFinite(calibration.intrinsics.focal_y_px) ||
        calibration.intrinsics.focal_x_px <= 0.0 || calibration.intrinsics.focal_y_px <= 0.0 ||
        !IsFinite(calibration.intrinsics.principal_x_px) ||
        !IsFinite(calibration.intrinsics.principal_y_px) ||
        calibration.intrinsics.principal_x_px >= calibration.intrinsics.reference_width ||
        calibration.intrinsics.principal_y_px >= calibration.intrinsics.reference_height ||
        !std::isfinite(QuaternionNorm(calibration.camera_to_gimbal)) ||
        std::abs(QuaternionNorm(calibration.camera_to_gimbal) - 1.0) > 1e-6 ||
        !IsFinite(calibration.camera_offset_in_gimbal_m) || !IsFinite(calibration.position_sigma_m) ||
        !IsFinite(calibration.angular_sigma_rad) || !IsFinite(calibration.pixel_sigma_px) ||
        calibration.position_sigma_m < 0.0 || calibration.angular_sigma_rad < 0.0 ||
        calibration.pixel_sigma_px <= 0.0 || calibration.max_pose_age_ms <= 0 ||
        profile.max_alignment_ms <= 0) {
        return false;
    }
    if (model.tensor_contract.query_count >
            std::numeric_limits<std::size_t>::max() / model.tensor_contract.class_count ||
        model.top_k > model.tensor_contract.query_count * model.tensor_contract.class_count) {
        return false;
    }
    for (const auto& pair : model.class_bindings) {
        const NativeRegisteredEquipmentBinding& binding = pair.second;
        if (pair.first != binding.source_class_id || binding.source_class_id >= model.tensor_contract.class_count ||
            !IsSafeText(binding.source_class_name) || !IsSafeText(binding.equipment_class) ||
            !IsFinite(binding.measured_dimensions.length) || !IsFinite(binding.measured_dimensions.width) ||
            !IsFinite(binding.measured_dimensions.height) || binding.measured_dimensions.length <= 0.0 ||
            binding.measured_dimensions.width <= 0.0 || binding.measured_dimensions.height < 0.0) return false;
    }
    return true;
}

}  // namespace

ProfiledGroundPlaneProjector::ProfiledGroundPlaneProjector(NativeRuntimeProfile profile)
    : profile_(std::move(profile)),
      site_frame_id_(profile_.calibration.site_frame_crs + ":" +
                     profile_.calibration.site_frame_vertical_datum + ":" +
                     profile_.calibration.site_frame_transform_version) {
    if (!IsValidProfile(profile_) || !IsSafeText(site_frame_id_)) {
        throw std::invalid_argument("incomplete native runtime profile cannot create a projector");
    }
}

WorldProjectionVerdict ProfiledGroundPlaneProjector::Project(
    const TrackedWorldEntity& entity, ProjectedWorldEntity* projection) {
    if (projection == nullptr || entity.entity_id.empty() || !std::isfinite(entity.detection.confidence) ||
        entity.detection.confidence < 0.0F || entity.detection.confidence > 1.0F ||
        entity.frame_metadata.width == 0U || entity.frame_metadata.height == 0U ||
        entity.frame_metadata.received_monotonic_ns <= 0 || entity.frame_metadata.received_utc_ms <= 0 ||
        !std::isfinite(entity.detection.box.x_min) || !std::isfinite(entity.detection.box.x_max) ||
        !std::isfinite(entity.detection.box.y_min) || !std::isfinite(entity.detection.box.y_max) ||
        entity.detection.box.x_min < 0.0F || entity.detection.box.y_min < 0.0F ||
        entity.detection.box.x_max <= entity.detection.box.x_min ||
        entity.detection.box.y_max <= entity.detection.box.y_min ||
        entity.detection.box.x_max > entity.frame_metadata.width ||
        entity.detection.box.y_max > entity.frame_metadata.height) {
        return WorldProjectionVerdict::kMalformed;
    }
    if (entity.alignment_verdict != AlignmentVerdict::kSensorAligned ||
        entity.frame_metadata.sensor_timestamp_ns <= 0) {
        return WorldProjectionVerdict::kMissingTiming;
    }
    if (!entity.telemetry.body_frd_to_ground_ned.has_value() ||
        !entity.telemetry.wgs84_position.has_value() ||
        !entity.telemetry.position_accuracy.has_value() ||
        !entity.telemetry.gimbal_ned_euler.has_value() ||
        !entity.telemetry.velocity_mps_measurement.has_value()) {
        return WorldProjectionVerdict::kMissingPose;
    }
    const TimedWgs84Position& wgs84 = *entity.telemetry.wgs84_position;
    const TimedPositionAccuracy& accuracy = *entity.telemetry.position_accuracy;
    const TimedGimbalNedEuler& gimbal = *entity.telemetry.gimbal_ned_euler;
    const TimedVelocityMps& velocity_measurement = *entity.telemetry.velocity_mps_measurement;
    if (!IsFresh(entity.frame_metadata.received_monotonic_ns, wgs84.received_monotonic_ns,
                 profile_.calibration.max_pose_age_ms) ||
        !IsFresh(entity.frame_metadata.received_monotonic_ns, accuracy.received_monotonic_ns,
                 profile_.calibration.max_pose_age_ms) ||
        !IsFresh(entity.frame_metadata.received_monotonic_ns, gimbal.received_monotonic_ns,
                 profile_.calibration.max_pose_age_ms) ||
        !IsFresh(entity.frame_metadata.received_monotonic_ns,
                 velocity_measurement.received_monotonic_ns,
                 profile_.calibration.max_pose_age_ms)) {
        return WorldProjectionVerdict::kStalePose;
    }
    const auto binding_it = profile_.model.class_bindings.find(entity.detection.class_id);
    if (binding_it == profile_.model.class_bindings.end() ||
        binding_it->second.source_class_name != entity.detection.class_name) {
        return WorldProjectionVerdict::kMissingDimensions;
    }
    const NativeCameraIntrinsics& intrinsics = profile_.calibration.intrinsics;
    const double x_scale = static_cast<double>(entity.frame_metadata.width) /
                           static_cast<double>(intrinsics.reference_width);
    const double y_scale = static_cast<double>(entity.frame_metadata.height) /
                           static_cast<double>(intrinsics.reference_height);
    if (!std::isfinite(x_scale) || !std::isfinite(y_scale) || x_scale <= 0.0 || y_scale <= 0.0) {
        return WorldProjectionVerdict::kMissingCalibration;
    }
    const double focal_x = intrinsics.focal_x_px * x_scale;
    const double focal_y = intrinsics.focal_y_px * y_scale;
    const double principal_x = intrinsics.principal_x_px * x_scale;
    const double principal_y = intrinsics.principal_y_px * y_scale;
    const double foot_x = (static_cast<double>(entity.detection.box.x_min) +
                           static_cast<double>(entity.detection.box.x_max)) /
                          2.0;
    const double foot_y = static_cast<double>(entity.detection.box.y_max);
    const Vec3 camera_ray = { (foot_x - principal_x) / focal_x, (foot_y - principal_y) / focal_y, 1.0 };
    const double ray_norm = std::hypot(std::hypot(camera_ray.x, camera_ray.y), camera_ray.z);
    if (!std::isfinite(ray_norm) || ray_norm <= 0.0) return WorldProjectionVerdict::kMalformed;
    const Vec3 normalized_camera_ray = Scale(camera_ray, 1.0 / ray_norm);
    const Vec3 gimbal_ray = RotateQuaternion(profile_.calibration.camera_to_gimbal, normalized_camera_ray);
    const Vec3 ned_ray = RotateGimbalNed(gimbal.value, gimbal_ray);
    const Vec3 site_ray = RotateEnuToSite(profile_.calibration, NedToEnu(ned_ray));
    const Vec3 enu_position = Wgs84ToEnu(wgs84.value, profile_.calibration.wgs84_origin);
    const Vec3 site_drone_position = Add(
        RotateEnuToSite(profile_.calibration, enu_position),
        profile_.calibration.enu_to_site_translation_m);
    const Vec3 camera_offset_ned = RotateGimbalNed(
        gimbal.value, profile_.calibration.camera_offset_in_gimbal_m);
    const Vec3 site_camera_position = Add(
        site_drone_position, RotateEnuToSite(profile_.calibration, NedToEnu(camera_offset_ned)));
    if (!IsFinite(site_ray) || !IsFinite(site_camera_position) ||
        std::abs(site_ray.z) < kMinimumRayZ) return WorldProjectionVerdict::kNoGroundIntersection;
    const double distance = (profile_.calibration.ground_plane_up_m - site_camera_position.z) / site_ray.z;
    if (!std::isfinite(distance) || distance <= 0.0) return WorldProjectionVerdict::kNoGroundIntersection;
    const Vec3 position = Add(site_camera_position, Scale(site_ray, distance));
    const Vec3 velocity =
        RotateEnuToSite(profile_.calibration, NedToEnu(velocity_measurement.value));
    if (!IsFinite(position) || !IsFinite(velocity)) return WorldProjectionVerdict::kMalformed;
    const double pixel_angle_sigma = profile_.calibration.pixel_sigma_px /
                                     std::min(focal_x, focal_y);
    const double horizontal_sigma = accuracy.value.horizontal_sigma_m +
                                    profile_.calibration.position_sigma_m +
                                    distance * (profile_.calibration.angular_sigma_rad + pixel_angle_sigma);
    const double vertical_sigma = accuracy.value.vertical_sigma_m +
                                  profile_.calibration.position_sigma_m +
                                  distance * (profile_.calibration.angular_sigma_rad + pixel_angle_sigma);
    if (!std::isfinite(horizontal_sigma) || !std::isfinite(vertical_sigma) || horizontal_sigma < 0.0 ||
        vertical_sigma < 0.0) return WorldProjectionVerdict::kMissingCovariance;
    const std::string observation_id = "frame-" + std::to_string(entity.frame_metadata.frame_id);
    NativeWorldEntity world;
    world.entity_id = entity.entity_id;
    world.entity_class = binding_it->second.equipment_class;
    world.observed_at_utc_ms = entity.frame_metadata.received_utc_ms;
    world.site_frame = site_frame_id_;
    world.position_m = position;
    world.velocity_mps = velocity;
    world.position_covariance = {horizontal_sigma * horizontal_sigma, 0.0, 0.0,
                                 0.0, horizontal_sigma * horizontal_sigma, 0.0,
                                 0.0, 0.0, vertical_sigma * vertical_sigma};
    world.classification_confidence = entity.detection.confidence;
    world.localization_state = "INSUFFICIENT_OBSERVATION";
    world.track_id = entity.entity_id;
    world.model_versions = {{"detector", profile_.model.model_id}};
    world.calibration_profile_id = profile_.calibration.calibration_profile_id;
    world.observation_ids = {observation_id};
    world.classification = {profile_.model.ontology_version, profile_.model.source_taxonomy,
                            binding_it->second.source_class_id,
                            binding_it->second.source_class_name};
    EquipmentObservation risk;
    risk.entity_id = entity.entity_id;
    risk.equipment_class = binding_it->second.equipment_class;
    risk.position_m = position;
    risk.velocity_mps = velocity;
    risk.measured_dimensions = binding_it->second.measured_dimensions;
    risk.position_covariance = PositionCovariance{
        horizontal_sigma * horizontal_sigma, horizontal_sigma * horizontal_sigma,
        vertical_sigma * vertical_sigma};
    risk.calibration_profile_id = profile_.calibration.calibration_profile_id;
    risk.observed_at_utc_ms = entity.frame_metadata.received_utc_ms;
    risk.occluded = false;
    *projection = {std::move(world), std::move(risk)};
    return WorldProjectionVerdict::kProjected;
}

}  // namespace ksi::edge

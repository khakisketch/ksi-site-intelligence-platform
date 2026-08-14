// Strict native reader for the verified EdgeRuntimeProfile v1 handoff.
//
// Python verifies the signed MissionDispatchEnvelope and publishes this record
// before the active-dispatch marker.  The C++ worker never accepts an arbitrary
// ONNX path, camera identity transform, dimensions, or site frame.

#ifndef KSI_EDGE_RUNTIME_PROFILE_HPP
#define KSI_EDGE_RUNTIME_PROFILE_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <string>

#include "ksi/edge/risk.hpp"
#include "ksi/edge/tensorrt.hpp"
#include "ksi/edge/telemetry.hpp"

namespace ksi::edge {

inline constexpr char kNativeRuntimeProfileFilename[] = "active-edge-runtime-profile.native.v1";
inline constexpr char kTensorRtDfinePreprocessingContractV1[] =
    "rtdetr-rgb-bilinear-1over255-v1";
inline constexpr char kTensorRtDfineDifferentialProfileV1[] =
    "ksi-dfine-tensorrt-onnx-semantic-v1";

struct NativeRegisteredEquipmentBinding {
    std::uint32_t source_class_id = 0;
    std::string source_class_name;
    std::string equipment_class;
    DimensionsM measured_dimensions;
};

struct NativeWgs84Origin {
    double latitude_rad = 0.0;
    double longitude_rad = 0.0;
    double altitude_m = 0.0;
};

struct NativeCameraIntrinsics {
    std::uint32_t reference_width = 0;
    std::uint32_t reference_height = 0;
    double focal_x_px = 0.0;
    double focal_y_px = 0.0;
    double principal_x_px = 0.0;
    double principal_y_px = 0.0;
};

struct NativeQuaternion {
    double w = 0.0;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct NativeCalibrationProfile {
    std::string calibration_profile_id;
    std::string site_frame_crs;
    std::string site_frame_vertical_datum;
    std::string site_frame_transform_version;
    NativeWgs84Origin wgs84_origin;
    // Row-major proper rotation and translation mapping local WGS84-derived
    // ENU metres into the Mission Contract's declared site frame.
    std::array<double, 9> enu_to_site_rotation {};
    Vec3 enu_to_site_translation_m;
    double ground_plane_up_m = 0.0;
    NativeCameraIntrinsics intrinsics;
    NativeQuaternion camera_to_gimbal;
    Vec3 camera_offset_in_gimbal_m;
    double position_sigma_m = 0.0;
    double angular_sigma_rad = 0.0;
    double pixel_sigma_px = 0.0;
    std::int64_t max_pose_age_ms = 0;
};

struct NativeTensorRtDifferentialAttestation {
    std::string verification_profile_id;
    std::string evidence_digest;
    std::string registered_onnx_digest;
    std::string preprocessing_contract_id;
    std::string preprocessing_config_digest;
    std::string corpus_id;
    std::string corpus_digest;
    std::size_t sample_count = 0;
    double confidence_atol = 0.0;
    double bbox_atol_px = 0.0;
    bool status_passed = false;
};

struct NativeModelProfile {
    std::string model_pack_id;
    std::string model_id;
    std::string onnx_artifact_id;
    std::string registered_onnx_digest;
    std::string engine_artifact_id;
    std::size_t max_onnx_bytes = 0;
    std::size_t max_engine_bytes = 0;
    std::size_t workspace_bytes = 0;
    TensorRtDfineTensorContract tensor_contract;
    float score_threshold = 0.0F;
    std::size_t top_k = 0;
    std::string ontology_version;
    std::string source_taxonomy;
    NativeTensorRtDifferentialAttestation tensor_rt_differential;
    std::map<std::uint32_t, NativeRegisteredEquipmentBinding> class_bindings;
};

struct NativeRuntimeProfile {
    std::string dispatch_id;
    std::string edge_device_id;
    std::string mission_id;
    std::string mission_contract_digest;
    std::string risk_policy_pack_digest;
    std::string edge_runtime_profile_digest;
    std::string edge_runtime_profile_id;
    std::string site_id;
    NativeModelProfile model;
    NativeCalibrationProfile calibration;
    std::int64_t max_alignment_ms = 0;
};

enum class NativeRuntimeProfileVerdict {
    kLoaded,
    kMissing,
    kUnsafeStateDirectory,
    kUnsafeSnapshot,
    kUnreadable,
    kTooLarge,
    kMalformed,
    kDispatchMismatch,
};

const char* ToString(NativeRuntimeProfileVerdict verdict);

struct NativeRuntimeProfileLoadResult {
    NativeRuntimeProfileVerdict verdict = NativeRuntimeProfileVerdict::kMissing;
    NativeRuntimeProfile profile;
};

// The native parser and the PSDK activation path both use this explicit gate.
// It binds the only supported image preprocessing implementation to a signed
// ONNX/TensorRT semantic-comparison attestation; a manually assembled profile
// with merely matching tensor dimensions cannot start the perception pipeline.
bool HasAcceptedTensorRtDifferential(const NativeModelProfile& model) noexcept;

// A runtime profile is usable only when it binds byte-for-byte identity fields
// to the separately loaded native activation.  Reading the profile first then
// activation marker gives crash/replacement safety: an absent/mismatched pair
// is capture-only, never a partial old/new combination.
NativeRuntimeProfileLoadResult LoadNativeRuntimeProfile(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_dispatch_id, const std::string& expected_mission_id,
    const std::string& expected_mission_contract_digest,
    const std::string& expected_risk_policy_pack_digest);

}  // namespace ksi::edge

#endif  // KSI_EDGE_RUNTIME_PROFILE_HPP

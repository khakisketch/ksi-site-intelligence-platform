#include "ksi/edge/runtime_profile.hpp"

#include "ksi/edge/crypto.hpp"

#include <array>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

constexpr char kMagic[] = "KSI_EDGE_NATIVE_RUNTIME_PROFILE_V1";
constexpr std::size_t kMaximumProfileBytes = 256U * 1024U;
constexpr std::size_t kMaximumClassBindings = 256U;

constexpr std::array<const char*, 70> kRequiredBaseFields = {
    "dispatch_id_b64",
    "edge_device_id_b64",
    "mission_id_b64",
    "mission_contract_digest",
    "risk_policy_pack_digest",
    "edge_runtime_profile_digest",
    "edge_runtime_profile_id_b64",
    "site_id_b64",
    "model_pack_id_b64",
    "model_id_b64",
    "model_onnx_artifact_id_b64",
    "model_registered_onnx_digest",
    "model_tensorrt_differential_verification_profile_id_b64",
    "model_tensorrt_differential_evidence_digest",
    "model_tensorrt_differential_registered_onnx_digest",
    "model_tensorrt_differential_preprocessing_contract_id_b64",
    "model_tensorrt_differential_preprocessing_config_digest",
    "model_tensorrt_differential_corpus_id_b64",
    "model_tensorrt_differential_corpus_digest",
    "model_tensorrt_differential_sample_count",
    "model_tensorrt_differential_status",
    "model_tensorrt_differential_confidence_atol_bits",
    "model_tensorrt_differential_bbox_atol_px_bits",
    "model_engine_artifact_id_b64",
    "model_max_onnx_bytes",
    "model_max_engine_bytes",
    "model_workspace_bytes",
    "model_input_width",
    "model_input_height",
    "model_query_count",
    "model_class_count",
    "model_score_threshold_bits",
    "model_top_k",
    "model_ontology_version_b64",
    "model_source_taxonomy_b64",
    "model_class_binding_count",
    "calibration_profile_id_b64",
    "calibration_site_frame_crs_b64",
    "calibration_site_frame_vertical_datum_b64",
    "calibration_site_frame_transform_version_b64",
    "calibration_wgs84_latitude_rad_bits",
    "calibration_wgs84_longitude_rad_bits",
    "calibration_wgs84_altitude_m_bits",
    "calibration_enu_to_site_r00_bits",
    "calibration_enu_to_site_r01_bits",
    "calibration_enu_to_site_r02_bits",
    "calibration_enu_to_site_r10_bits",
    "calibration_enu_to_site_r11_bits",
    "calibration_enu_to_site_r12_bits",
    "calibration_enu_to_site_r20_bits",
    "calibration_enu_to_site_r21_bits",
    "calibration_enu_to_site_r22_bits",
    "calibration_enu_to_site_translation_x_m_bits",
    "calibration_enu_to_site_translation_y_m_bits",
    "calibration_enu_to_site_translation_z_m_bits",
    "calibration_ground_plane_up_m_bits",
    "calibration_reference_width",
    "calibration_reference_height",
    "calibration_focal_x_px_bits",
    "calibration_focal_y_px_bits",
    "calibration_principal_x_px_bits",
    "calibration_principal_y_px_bits",
    "calibration_camera_to_gimbal_w_bits",
    "calibration_camera_to_gimbal_x_bits",
    "calibration_camera_to_gimbal_y_bits",
    "calibration_camera_to_gimbal_z_bits",
    "calibration_camera_offset_x_m_bits",
    "calibration_camera_offset_y_m_bits",
    "calibration_camera_offset_z_m_bits",
    "calibration_position_sigma_m_bits",
    // Add these final four below through the exact-set length calculation to
    // keep the column layout readable on older GCC 9 builds.
};

constexpr std::array<const char*, 4> kRequiredTrailingFields = {
    "calibration_angular_sigma_rad_bits",
    "calibration_pixel_sigma_px_bits",
    "calibration_max_pose_age_ms",
    "timing_max_alignment_ms",
};

bool IsPrivateOwnedDirectory(const std::string& path) {
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISDIR(value.st_mode) &&
           !S_ISLNK(value.st_mode) && value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

enum class ReadResult { kRead, kMissing, kUnsafe, kUnreadable, kTooLarge };

ReadResult ReadPrivateFile(const std::string& path, std::string* output) {
    if (output == nullptr) {
        return ReadResult::kUnreadable;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return errno == ENOENT ? ReadResult::kMissing : ReadResult::kUnreadable;
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_nlink != 1 || before.st_size < 1) {
        return ReadResult::kUnsafe;
    }
    if (static_cast<std::uintmax_t>(before.st_size) > kMaximumProfileBytes) {
        return ReadResult::kTooLarge;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return errno == ENOENT ? ReadResult::kMissing : ReadResult::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_nlink == 1 &&
                           opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(descriptor);
        return ReadResult::kUnsafe;
    }
    std::string content(static_cast<std::size_t>(opened.st_size), '\0');
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < content.size()) {
        const ssize_t received = read(descriptor, content.data() + offset, content.size() - offset);
        if (received > 0) {
            offset += static_cast<std::size_t>(received);
            continue;
        }
        if (received < 0 && errno == EINTR) {
            continue;
        }
        read_ok = false;
        break;
    }
    const bool closed = close(descriptor) == 0;
    if (!read_ok || !closed || offset != content.size()) {
        return ReadResult::kUnreadable;
    }
    *output = std::move(content);
    return ReadResult::kRead;
}

bool ParseStrictLines(const std::string& input, std::map<std::string, std::string>* output) {
    if (output == nullptr || input.empty() || input.back() != '\n') {
        return false;
    }
    std::vector<std::string> lines;
    std::size_t start = 0U;
    for (std::size_t index = 0U; index < input.size(); ++index) {
        const char character = input[index];
        if (character == '\r' || character == '\0') {
            return false;
        }
        if (character == '\n') {
            lines.push_back(input.substr(start, index - start));
            start = index + 1U;
        }
    }
    if (start != input.size() || lines.size() < 2U || lines[0] != kMagic) {
        return false;
    }
    std::map<std::string, std::string> parsed;
    for (std::size_t index = 1U; index < lines.size(); ++index) {
        const std::size_t separator = lines[index].find('=');
        if (separator == std::string::npos || separator == 0U ||
            lines[index].find('=', separator + 1U) != std::string::npos) {
            return false;
        }
        const std::string key = lines[index].substr(0U, separator);
        const std::string value = lines[index].substr(separator + 1U);
        if (value.empty() || !parsed.emplace(key, value).second) {
            return false;
        }
    }
    for (const char* required : kRequiredBaseFields) {
        if (parsed.find(required) == parsed.end()) {
            return false;
        }
    }
    for (const char* required : kRequiredTrailingFields) {
        if (parsed.find(required) == parsed.end()) {
            return false;
        }
    }
    *output = std::move(parsed);
    return true;
}

bool ParseUnsigned(const std::string& input, std::size_t maximum, std::size_t* output) {
    if (output == nullptr || input.empty()) {
        return false;
    }
    for (const char character : input) {
        if (character < '0' || character > '9') {
            return false;
        }
    }
    std::size_t value = 0U;
    const auto [end, error] = std::from_chars(input.data(), input.data() + input.size(), value);
    if (error != std::errc{} || end != input.data() + input.size() || value > maximum) {
        return false;
    }
    *output = value;
    return true;
}

bool ParsePositive(const std::string& input, std::size_t maximum, std::size_t* output) {
    return ParseUnsigned(input, maximum, output) && *output > 0U;
}

bool ParseNonnegativeMillis(const std::string& input, std::int64_t* output) {
    std::size_t parsed = 0U;
    if (!ParsePositive(input, static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max()),
                       &parsed)) {
        return false;
    }
    *output = static_cast<std::int64_t>(parsed);
    return true;
}

int DecodeCharacter(char character) {
    if (character >= 'A' && character <= 'Z') return character - 'A';
    if (character >= 'a' && character <= 'z') return character - 'a' + 26;
    if (character >= '0' && character <= '9') return character - '0' + 52;
    if (character == '-') return 62;
    return character == '_' ? 63 : -1;
}

bool DecodeBase64Url(const std::string& input, std::string* output) {
    if (output == nullptr || input.empty() || input.size() % 4U == 1U) return false;
    const std::size_t remainder = input.size() % 4U;
    if (remainder == 2U && (DecodeCharacter(input.back()) & 0x0F) != 0) return false;
    if (remainder == 3U && (DecodeCharacter(input.back()) & 0x03) != 0) return false;
    std::string decoded;
    decoded.reserve((input.size() * 3U) / 4U);
    std::uint32_t accumulator = 0U;
    unsigned available_bits = 0U;
    for (const char character : input) {
        const int value = DecodeCharacter(character);
        if (value < 0) return false;
        accumulator = (accumulator << 6U) | static_cast<std::uint32_t>(value);
        available_bits += 6U;
        while (available_bits >= 8U) {
            available_bits -= 8U;
            decoded.push_back(static_cast<char>((accumulator >> available_bits) & 0xFFU));
        }
    }
    *output = std::move(decoded);
    return true;
}

bool IsSafeText(const std::string& value) {
    if (value.empty()) return false;
    for (const unsigned char character : value) {
        if (character == 0U || character < 0x20U || character == 0x7FU) return false;
    }
    return true;
}

bool DecodeFloat64Bits(const std::string& input, double* output) {
    if (output == nullptr || input.size() != 16U) return false;
    for (const char character : input) {
        if (!((character >= '0' && character <= '9') ||
              (character >= 'a' && character <= 'f'))) return false;
    }
    std::uint64_t bits = 0U;
    const auto [end, error] = std::from_chars(input.data(), input.data() + input.size(), bits, 16);
    if (error != std::errc{} || end != input.data() + input.size()) return false;
    double value = 0.0;
    static_assert(sizeof(value) == sizeof(bits), "runtime profile requires IEEE-754 double");
    std::memcpy(&value, &bits, sizeof(value));
    if (!std::isfinite(value)) return false;
    *output = value;
    return true;
}

std::string BindingFieldName(std::size_t index, const char* suffix) {
    return "model_class_binding_" + std::to_string(index) + "_" + suffix;
}

bool HasExactFieldSet(const std::map<std::string, std::string>& fields, std::size_t count) {
    constexpr std::array<const char*, 6> kBindingFields = {
        "source_class_id", "source_class_name_b64", "equipment_class_b64",
        "measured_length_bits", "measured_width_bits", "measured_height_bits",
    };
    const std::size_t base_count = kRequiredBaseFields.size() + kRequiredTrailingFields.size();
    if (fields.size() != base_count + count * kBindingFields.size()) return false;
    for (std::size_t index = 0U; index < count; ++index) {
        for (const char* suffix : kBindingFields) {
            if (fields.find(BindingFieldName(index, suffix)) == fields.end()) return false;
        }
    }
    return true;
}

bool DecodeTextField(const std::map<std::string, std::string>& fields, const char* key,
                     std::string* output) {
    const auto it = fields.find(key);
    return it != fields.end() && DecodeBase64Url(it->second, output) && IsSafeText(*output);
}

bool BuildProfile(const std::map<std::string, std::string>& fields, NativeRuntimeProfile* profile) {
    if (profile == nullptr) return false;
    NativeRuntimeProfile result;
    if (!DecodeTextField(fields, "dispatch_id_b64", &result.dispatch_id) ||
        !DecodeTextField(fields, "edge_device_id_b64", &result.edge_device_id) ||
        !DecodeTextField(fields, "mission_id_b64", &result.mission_id) ||
        !DecodeTextField(fields, "edge_runtime_profile_id_b64", &result.edge_runtime_profile_id) ||
        !DecodeTextField(fields, "site_id_b64", &result.site_id) ||
        !IsSha256Digest(fields.at("mission_contract_digest")) ||
        !IsSha256Digest(fields.at("risk_policy_pack_digest")) ||
        !IsSha256Digest(fields.at("edge_runtime_profile_digest"))) return false;
    result.mission_contract_digest = fields.at("mission_contract_digest");
    result.risk_policy_pack_digest = fields.at("risk_policy_pack_digest");
    result.edge_runtime_profile_digest = fields.at("edge_runtime_profile_digest");
    NativeModelProfile& model = result.model;
    if (!DecodeTextField(fields, "model_pack_id_b64", &model.model_pack_id) ||
        !DecodeTextField(fields, "model_id_b64", &model.model_id) ||
        !DecodeTextField(fields, "model_onnx_artifact_id_b64", &model.onnx_artifact_id) ||
        !DecodeTextField(fields, "model_engine_artifact_id_b64", &model.engine_artifact_id) ||
        !DecodeTextField(fields, "model_ontology_version_b64", &model.ontology_version) ||
        !DecodeTextField(fields, "model_source_taxonomy_b64", &model.source_taxonomy) ||
        !IsSha256Digest(fields.at("model_registered_onnx_digest")) ||
        !ParsePositive(fields.at("model_max_onnx_bytes"), 1024U * 1024U * 1024U,
                       &model.max_onnx_bytes) ||
        !ParsePositive(fields.at("model_max_engine_bytes"), 2U * 1024U * 1024U * 1024U,
                       &model.max_engine_bytes) ||
        !ParsePositive(fields.at("model_workspace_bytes"), 2U * 1024U * 1024U * 1024U,
                       &model.workspace_bytes) ||
        !ParsePositive(fields.at("model_query_count"), 10000U,
                       &model.tensor_contract.query_count) ||
        !ParsePositive(fields.at("model_class_count"), 1000U,
                       &model.tensor_contract.class_count) ||
        !ParsePositive(fields.at("model_top_k"), std::numeric_limits<std::size_t>::max(),
                       &model.top_k)) {
        return false;
    }
    // Parse through local values so the fixed handoff stays correct on both
    // 32-bit and 64-bit targets; never write a 32-bit field through a cast.
    double score = 0.0;
    std::size_t input_width = 0U;
    std::size_t input_height = 0U;
    if (!DecodeFloat64Bits(fields.at("model_score_threshold_bits"), &score) || score < 0.0 || score > 1.0 ||
        !ParsePositive(fields.at("model_input_width"), 8192U, &input_width) ||
        !ParsePositive(fields.at("model_input_height"), 8192U, &input_height) ||
        input_width > std::numeric_limits<std::uint32_t>::max() ||
        input_height > std::numeric_limits<std::uint32_t>::max()) return false;
    model.score_threshold = static_cast<float>(score);
    model.tensor_contract.input_width = static_cast<std::uint32_t>(input_width);
    model.tensor_contract.input_height = static_cast<std::uint32_t>(input_height);
    model.registered_onnx_digest = fields.at("model_registered_onnx_digest");
    NativeTensorRtDifferentialAttestation& differential = model.tensor_rt_differential;
    if (!DecodeTextField(fields, "model_tensorrt_differential_verification_profile_id_b64",
                         &differential.verification_profile_id) ||
        !IsSha256Digest(fields.at("model_tensorrt_differential_evidence_digest")) ||
        !IsSha256Digest(fields.at("model_tensorrt_differential_registered_onnx_digest")) ||
        !DecodeTextField(fields, "model_tensorrt_differential_preprocessing_contract_id_b64",
                         &differential.preprocessing_contract_id) ||
        !IsSha256Digest(fields.at("model_tensorrt_differential_preprocessing_config_digest")) ||
        !DecodeTextField(fields, "model_tensorrt_differential_corpus_id_b64",
                         &differential.corpus_id) ||
        !IsSha256Digest(fields.at("model_tensorrt_differential_corpus_digest")) ||
        !ParsePositive(fields.at("model_tensorrt_differential_sample_count"), 10000U,
                       &differential.sample_count) ||
        !DecodeFloat64Bits(fields.at("model_tensorrt_differential_confidence_atol_bits"),
                           &differential.confidence_atol) ||
        !DecodeFloat64Bits(fields.at("model_tensorrt_differential_bbox_atol_px_bits"),
                           &differential.bbox_atol_px) ||
        fields.at("model_tensorrt_differential_status") != "PASS") {
        return false;
    }
    differential.evidence_digest = fields.at("model_tensorrt_differential_evidence_digest");
    differential.registered_onnx_digest =
        fields.at("model_tensorrt_differential_registered_onnx_digest");
    differential.preprocessing_config_digest =
        fields.at("model_tensorrt_differential_preprocessing_config_digest");
    differential.corpus_digest = fields.at("model_tensorrt_differential_corpus_digest");
    differential.status_passed = true;
    if (!HasAcceptedTensorRtDifferential(model)) return false;
    if (model.top_k > model.tensor_contract.query_count * model.tensor_contract.class_count) return false;
    std::size_t binding_count = 0U;
    if (!ParsePositive(fields.at("model_class_binding_count"), kMaximumClassBindings, &binding_count) ||
        !HasExactFieldSet(fields, binding_count)) return false;
    for (std::size_t index = 0U; index < binding_count; ++index) {
        std::size_t source_id = 0U;
        NativeRegisteredEquipmentBinding binding;
        if (!ParseUnsigned(fields.at(BindingFieldName(index, "source_class_id")),
                           static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max()), &source_id) ||
            !DecodeBase64Url(fields.at(BindingFieldName(index, "source_class_name_b64")),
                             &binding.source_class_name) ||
            !DecodeBase64Url(fields.at(BindingFieldName(index, "equipment_class_b64")),
                             &binding.equipment_class) ||
            !IsSafeText(binding.source_class_name) || !IsSafeText(binding.equipment_class) ||
            !DecodeFloat64Bits(fields.at(BindingFieldName(index, "measured_length_bits")),
                               &binding.measured_dimensions.length) ||
            !DecodeFloat64Bits(fields.at(BindingFieldName(index, "measured_width_bits")),
                               &binding.measured_dimensions.width) ||
            !DecodeFloat64Bits(fields.at(BindingFieldName(index, "measured_height_bits")),
                               &binding.measured_dimensions.height)) return false;
        binding.source_class_id = static_cast<std::uint32_t>(source_id);
        if (binding.source_class_id >= model.tensor_contract.class_count ||
            binding.measured_dimensions.length <= 0.0 || binding.measured_dimensions.width <= 0.0 ||
            binding.measured_dimensions.height < 0.0 ||
            !model.class_bindings.emplace(binding.source_class_id, binding).second) return false;
    }
    NativeCalibrationProfile& calibration = result.calibration;
    if (!DecodeTextField(fields, "calibration_profile_id_b64", &calibration.calibration_profile_id) ||
        !DecodeTextField(fields, "calibration_site_frame_crs_b64", &calibration.site_frame_crs) ||
        !DecodeTextField(fields, "calibration_site_frame_vertical_datum_b64", &calibration.site_frame_vertical_datum) ||
        !DecodeTextField(fields, "calibration_site_frame_transform_version_b64", &calibration.site_frame_transform_version)) return false;
    std::size_t reference_width = 0U;
    std::size_t reference_height = 0U;
    if (!DecodeFloat64Bits(fields.at("calibration_wgs84_latitude_rad_bits"), &calibration.wgs84_origin.latitude_rad) ||
        !DecodeFloat64Bits(fields.at("calibration_wgs84_longitude_rad_bits"), &calibration.wgs84_origin.longitude_rad) ||
        !DecodeFloat64Bits(fields.at("calibration_wgs84_altitude_m_bits"), &calibration.wgs84_origin.altitude_m) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r00_bits"), &calibration.enu_to_site_rotation[0]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r01_bits"), &calibration.enu_to_site_rotation[1]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r02_bits"), &calibration.enu_to_site_rotation[2]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r10_bits"), &calibration.enu_to_site_rotation[3]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r11_bits"), &calibration.enu_to_site_rotation[4]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r12_bits"), &calibration.enu_to_site_rotation[5]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r20_bits"), &calibration.enu_to_site_rotation[6]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r21_bits"), &calibration.enu_to_site_rotation[7]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_r22_bits"), &calibration.enu_to_site_rotation[8]) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_translation_x_m_bits"), &calibration.enu_to_site_translation_m.x) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_translation_y_m_bits"), &calibration.enu_to_site_translation_m.y) ||
        !DecodeFloat64Bits(fields.at("calibration_enu_to_site_translation_z_m_bits"), &calibration.enu_to_site_translation_m.z) ||
        !DecodeFloat64Bits(fields.at("calibration_ground_plane_up_m_bits"), &calibration.ground_plane_up_m) ||
        !ParsePositive(fields.at("calibration_reference_width"), 16384U, &reference_width) ||
        !ParsePositive(fields.at("calibration_reference_height"), 16384U, &reference_height) ||
        !DecodeFloat64Bits(fields.at("calibration_focal_x_px_bits"), &calibration.intrinsics.focal_x_px) ||
        !DecodeFloat64Bits(fields.at("calibration_focal_y_px_bits"), &calibration.intrinsics.focal_y_px) ||
        !DecodeFloat64Bits(fields.at("calibration_principal_x_px_bits"), &calibration.intrinsics.principal_x_px) ||
        !DecodeFloat64Bits(fields.at("calibration_principal_y_px_bits"), &calibration.intrinsics.principal_y_px) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_to_gimbal_w_bits"), &calibration.camera_to_gimbal.w) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_to_gimbal_x_bits"), &calibration.camera_to_gimbal.x) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_to_gimbal_y_bits"), &calibration.camera_to_gimbal.y) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_to_gimbal_z_bits"), &calibration.camera_to_gimbal.z) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_offset_x_m_bits"), &calibration.camera_offset_in_gimbal_m.x) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_offset_y_m_bits"), &calibration.camera_offset_in_gimbal_m.y) ||
        !DecodeFloat64Bits(fields.at("calibration_camera_offset_z_m_bits"), &calibration.camera_offset_in_gimbal_m.z) ||
        !DecodeFloat64Bits(fields.at("calibration_position_sigma_m_bits"), &calibration.position_sigma_m) ||
        !DecodeFloat64Bits(fields.at("calibration_angular_sigma_rad_bits"), &calibration.angular_sigma_rad) ||
        !DecodeFloat64Bits(fields.at("calibration_pixel_sigma_px_bits"), &calibration.pixel_sigma_px) ||
        !ParseNonnegativeMillis(fields.at("calibration_max_pose_age_ms"), &calibration.max_pose_age_ms) ||
        !ParseNonnegativeMillis(fields.at("timing_max_alignment_ms"), &result.max_alignment_ms)) return false;
    calibration.intrinsics.reference_width = static_cast<std::uint32_t>(reference_width);
    calibration.intrinsics.reference_height = static_cast<std::uint32_t>(reference_height);
    const double quaternion_norm = std::hypot(std::hypot(calibration.camera_to_gimbal.w,
                                                         calibration.camera_to_gimbal.x),
                                              std::hypot(calibration.camera_to_gimbal.y,
                                                         calibration.camera_to_gimbal.z));
    const auto dot_rows = [&calibration](std::size_t first, std::size_t second) {
        return calibration.enu_to_site_rotation[first * 3U] *
                   calibration.enu_to_site_rotation[second * 3U] +
               calibration.enu_to_site_rotation[first * 3U + 1U] *
                   calibration.enu_to_site_rotation[second * 3U + 1U] +
               calibration.enu_to_site_rotation[first * 3U + 2U] *
                   calibration.enu_to_site_rotation[second * 3U + 2U];
    };
    const double determinant =
        calibration.enu_to_site_rotation[0] *
            (calibration.enu_to_site_rotation[4] * calibration.enu_to_site_rotation[8] -
             calibration.enu_to_site_rotation[5] * calibration.enu_to_site_rotation[7]) -
        calibration.enu_to_site_rotation[1] *
            (calibration.enu_to_site_rotation[3] * calibration.enu_to_site_rotation[8] -
             calibration.enu_to_site_rotation[5] * calibration.enu_to_site_rotation[6]) +
        calibration.enu_to_site_rotation[2] *
            (calibration.enu_to_site_rotation[3] * calibration.enu_to_site_rotation[7] -
             calibration.enu_to_site_rotation[4] * calibration.enu_to_site_rotation[6]);
    if (std::abs(calibration.wgs84_origin.latitude_rad) > 1.5707963267948966 ||
        std::abs(calibration.wgs84_origin.longitude_rad) > 3.141592653589793 ||
        std::abs(dot_rows(0U, 0U) - 1.0) > 1e-6 ||
        std::abs(dot_rows(1U, 1U) - 1.0) > 1e-6 ||
        std::abs(dot_rows(2U, 2U) - 1.0) > 1e-6 ||
        std::abs(dot_rows(0U, 1U)) > 1e-6 || std::abs(dot_rows(0U, 2U)) > 1e-6 ||
        std::abs(dot_rows(1U, 2U)) > 1e-6 || std::abs(determinant - 1.0) > 1e-6 ||
        calibration.intrinsics.focal_x_px <= 0.0 || calibration.intrinsics.focal_y_px <= 0.0 ||
        calibration.intrinsics.principal_x_px >= calibration.intrinsics.reference_width ||
        calibration.intrinsics.principal_y_px >= calibration.intrinsics.reference_height ||
        std::abs(quaternion_norm - 1.0) > 1e-6 || calibration.position_sigma_m < 0.0 ||
        calibration.angular_sigma_rad < 0.0 || calibration.pixel_sigma_px <= 0.0 ||
        calibration.max_pose_age_ms <= 0 || result.max_alignment_ms <= 0) return false;
    *profile = std::move(result);
    return true;
}

}  // namespace

bool HasAcceptedTensorRtDifferential(const NativeModelProfile& model) noexcept {
    const NativeTensorRtDifferentialAttestation& differential = model.tensor_rt_differential;
    return differential.status_passed &&
           differential.verification_profile_id == kTensorRtDfineDifferentialProfileV1 &&
           differential.preprocessing_contract_id == kTensorRtDfinePreprocessingContractV1 &&
           IsSha256Digest(model.registered_onnx_digest) &&
           differential.registered_onnx_digest == model.registered_onnx_digest &&
           IsSha256Digest(differential.evidence_digest) &&
           IsSha256Digest(differential.preprocessing_config_digest) &&
           IsSha256Digest(differential.corpus_digest) && differential.sample_count >= 10U &&
           differential.sample_count <= 10000U && std::isfinite(differential.confidence_atol) &&
           differential.confidence_atol > 0.0 && differential.confidence_atol <= 0.001 &&
           std::isfinite(differential.bbox_atol_px) && differential.bbox_atol_px > 0.0 &&
           differential.bbox_atol_px <= 0.5;
}

const char* ToString(NativeRuntimeProfileVerdict verdict) {
    switch (verdict) {
        case NativeRuntimeProfileVerdict::kLoaded: return "LOADED";
        case NativeRuntimeProfileVerdict::kMissing: return "MISSING";
        case NativeRuntimeProfileVerdict::kUnsafeStateDirectory: return "UNSAFE_STATE_DIRECTORY";
        case NativeRuntimeProfileVerdict::kUnsafeSnapshot: return "UNSAFE_SNAPSHOT";
        case NativeRuntimeProfileVerdict::kUnreadable: return "UNREADABLE";
        case NativeRuntimeProfileVerdict::kTooLarge: return "TOO_LARGE";
        case NativeRuntimeProfileVerdict::kMalformed: return "MALFORMED";
        case NativeRuntimeProfileVerdict::kDispatchMismatch: return "DISPATCH_MISMATCH";
    }
    return "UNKNOWN";
}

NativeRuntimeProfileLoadResult LoadNativeRuntimeProfile(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_dispatch_id, const std::string& expected_mission_id,
    const std::string& expected_mission_contract_digest,
    const std::string& expected_risk_policy_pack_digest) {
    NativeRuntimeProfileLoadResult result;
    if (state_directory.empty() || expected_edge_device_id.empty() || expected_dispatch_id.empty() ||
        expected_mission_id.empty() || !IsSha256Digest(expected_mission_contract_digest) ||
        !IsSha256Digest(expected_risk_policy_pack_digest) || !IsPrivateOwnedDirectory(state_directory)) {
        result.verdict = NativeRuntimeProfileVerdict::kUnsafeStateDirectory;
        return result;
    }
    std::string bytes;
    switch (ReadPrivateFile(state_directory + "/" + kNativeRuntimeProfileFilename, &bytes)) {
        case ReadResult::kRead: break;
        case ReadResult::kMissing: result.verdict = NativeRuntimeProfileVerdict::kMissing; return result;
        case ReadResult::kUnsafe: result.verdict = NativeRuntimeProfileVerdict::kUnsafeSnapshot; return result;
        case ReadResult::kUnreadable: result.verdict = NativeRuntimeProfileVerdict::kUnreadable; return result;
        case ReadResult::kTooLarge: result.verdict = NativeRuntimeProfileVerdict::kTooLarge; return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(bytes, &fields) || !BuildProfile(fields, &result.profile)) {
        result.verdict = NativeRuntimeProfileVerdict::kMalformed;
        return result;
    }
    if (result.profile.edge_device_id != expected_edge_device_id ||
        result.profile.dispatch_id != expected_dispatch_id ||
        result.profile.mission_id != expected_mission_id ||
        result.profile.mission_contract_digest != expected_mission_contract_digest ||
        result.profile.risk_policy_pack_digest != expected_risk_policy_pack_digest) {
        result.verdict = NativeRuntimeProfileVerdict::kDispatchMismatch;
        return result;
    }
    result.verdict = NativeRuntimeProfileVerdict::kLoaded;
    return result;
}

}  // namespace ksi::edge

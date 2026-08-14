#include "ksi/edge/activation.hpp"

#include "ksi/edge/crypto.hpp"

#include <array>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstddef>
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

constexpr char kMagic[] = "KSI_EDGE_NATIVE_ACTIVATION_V1";
constexpr std::size_t kMaximumSnapshotBytes = 128U * 1024U;
constexpr std::size_t kMaximumNativePolicies = 128U;

constexpr std::array<const char*, 12> kRequiredBaseFields = {
    "activated_at_utc_ms",       "dispatch_id_b64",          "edge_device_id_b64",
    "mission_contract_digest",   "mission_id_b64",           "risk_policy_pack_digest",
    "risk_policy_pack_id_b64",   "risk_policy_calibration_profile_id_b64",
    "risk_policy_count",          "runtime_version_b64",       "valid_from_utc_ms",
    "valid_until_utc_ms",
};

bool IsPrivateOwnedDirectory(const std::string& path) {
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISDIR(value.st_mode) &&
           !S_ISLNK(value.st_mode) && value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

enum class ReadSnapshotResult {
    kRead,
    kMissing,
    kUnsafe,
    kUnreadable,
    kTooLarge,
};

ReadSnapshotResult ReadPrivateSnapshot(const std::string& path, std::string* output) {
    if (output == nullptr) {
        return ReadSnapshotResult::kUnreadable;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return errno == ENOENT ? ReadSnapshotResult::kMissing : ReadSnapshotResult::kUnreadable;
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_size < 1 ||
        static_cast<std::uintmax_t>(before.st_size) > kMaximumSnapshotBytes) {
        return before.st_size > static_cast<off_t>(kMaximumSnapshotBytes)
                   ? ReadSnapshotResult::kTooLarge
                   : ReadSnapshotResult::kUnsafe;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return errno == ENOENT ? ReadSnapshotResult::kMissing : ReadSnapshotResult::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_size == before.st_size &&
                           opened.st_nlink == 1;
    if (!same_file) {
        (void)close(descriptor);
        return ReadSnapshotResult::kUnsafe;
    }
    const std::size_t size = static_cast<std::size_t>(opened.st_size);
    std::string content(size, '\0');
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < size) {
        const ssize_t received = read(descriptor, content.data() + offset, size - offset);
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
    if (!read_ok || !closed || offset != size) {
        return ReadSnapshotResult::kUnreadable;
    }
    *output = std::move(content);
    return ReadSnapshotResult::kRead;
}

bool ParseStrictLines(const std::string& input, std::map<std::string, std::string>* output) {
    if (output == nullptr || input.size() < sizeof(kMagic) || input.back() != '\n') {
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
    if (start != input.size() || lines.size() < kRequiredBaseFields.size() + 1U || lines[0] != kMagic) {
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
    *output = std::move(parsed);
    return true;
}

bool ParseNonnegativeMillis(const std::string& input, std::int64_t* output) {
    if (output == nullptr || input.empty()) {
        return false;
    }
    for (const char character : input) {
        if (character < '0' || character > '9') {
            return false;
        }
    }
    std::int64_t value = 0;
    const auto [end, error] = std::from_chars(input.data(), input.data() + input.size(), value);
    if (error != std::errc{} || end != input.data() + input.size() || value < 0) {
        return false;
    }
    *output = value;
    return true;
}

bool ParsePositivePolicyCount(const std::string& input, std::size_t* output) {
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
    if (error != std::errc{} || end != input.data() + input.size() || value == 0U ||
        value > kMaximumNativePolicies) {
        return false;
    }
    *output = value;
    return true;
}

int DecodeBase64UrlCharacter(char character) {
    if (character >= 'A' && character <= 'Z') {
        return character - 'A';
    }
    if (character >= 'a' && character <= 'z') {
        return character - 'a' + 26;
    }
    if (character >= '0' && character <= '9') {
        return character - '0' + 52;
    }
    if (character == '-') {
        return 62;
    }
    return character == '_' ? 63 : -1;
}

bool DecodeBase64Url(const std::string& input, std::string* output) {
    if (output == nullptr || input.empty() || input.size() % 4U == 1U) {
        return false;
    }
    const std::size_t remainder = input.size() % 4U;
    if (remainder == 2U && (DecodeBase64UrlCharacter(input.back()) & 0x0F) != 0) {
        return false;
    }
    if (remainder == 3U && (DecodeBase64UrlCharacter(input.back()) & 0x03) != 0) {
        return false;
    }
    std::string decoded;
    decoded.reserve((input.size() * 3U) / 4U);
    std::uint32_t accumulator = 0U;
    unsigned available_bits = 0U;
    for (const char character : input) {
        const int value = DecodeBase64UrlCharacter(character);
        if (value < 0) {
            return false;
        }
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
    if (value.empty()) {
        return false;
    }
    for (const unsigned char character : value) {
        if (character == 0U || character < 0x20U || character == 0x7FU) {
            return false;
        }
    }
    return true;
}

std::string PolicyFieldName(std::size_t index, const char* suffix) {
    return "risk_policy_" + std::to_string(index) + "_" + suffix;
}

bool HasExactPolicyFieldSet(const std::map<std::string, std::string>& fields,
                            std::size_t policy_count) {
    constexpr std::array<const char*, 10> kPolicyFields = {
        "equipment_class_b64",          "risk_field_policy_id_b64", "footprint_length_bits",
        "footprint_width_bits",          "footprint_height_bits",    "prediction_horizon_bits",
        "sample_period_bits",            "covariance_sigma_multiplier_bits",
        "occlusion_expansion_bits",      "severity_bits",
    };
    if (fields.size() != kRequiredBaseFields.size() + policy_count * kPolicyFields.size()) {
        return false;
    }
    for (const char* required : kRequiredBaseFields) {
        if (fields.find(required) == fields.end()) {
            return false;
        }
    }
    for (std::size_t index = 0U; index < policy_count; ++index) {
        for (const char* suffix : kPolicyFields) {
            if (fields.find(PolicyFieldName(index, suffix)) == fields.end()) {
                return false;
            }
        }
    }
    return true;
}

bool DecodeFloat64Bits(const std::string& input, double* output) {
    if (output == nullptr || input.size() != 16U) {
        return false;
    }
    for (const char character : input) {
        if (!((character >= '0' && character <= '9') ||
              (character >= 'a' && character <= 'f'))) {
            return false;
        }
    }
    std::uint64_t bits = 0U;
    const auto [end, error] =
        std::from_chars(input.data(), input.data() + input.size(), bits, 16);
    if (error != std::errc{} || end != input.data() + input.size()) {
        return false;
    }
    double value = 0.0;
    static_assert(sizeof(value) == sizeof(bits), "native activation requires IEEE-754 double");
    std::memcpy(&value, &bits, sizeof(value));
    if (!std::isfinite(value)) {
        return false;
    }
    *output = value;
    return true;
}

bool BuildNativeRiskPolicyPack(const std::map<std::string, std::string>& fields,
                               NativeActivationSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    std::size_t policy_count = 0U;
    if (!ParsePositivePolicyCount(fields.at("risk_policy_count"), &policy_count) ||
        !HasExactPolicyFieldSet(fields, policy_count)) {
        return false;
    }
    RiskPolicyPack pack;
    pack.digest = fields.at("risk_policy_pack_digest");
    if (!DecodeBase64Url(fields.at("risk_policy_pack_id_b64"), &pack.risk_policy_pack_id)) {
        return false;
    }
    std::string calibration_profile_id;
    if (!DecodeBase64Url(fields.at("risk_policy_calibration_profile_id_b64"),
                         &calibration_profile_id) ||
        !IsSafeText(pack.risk_policy_pack_id) || !IsSafeText(calibration_profile_id)) {
        return false;
    }
    for (std::size_t index = 0U; index < policy_count; ++index) {
        EquipmentRiskPolicy policy;
        if (!DecodeBase64Url(fields.at(PolicyFieldName(index, "equipment_class_b64")),
                             &policy.equipment_class) ||
            !DecodeBase64Url(fields.at(PolicyFieldName(index, "risk_field_policy_id_b64")),
                             &policy.risk_field_policy_id) ||
            !IsSafeText(policy.equipment_class) || !IsSafeText(policy.risk_field_policy_id) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "footprint_length_bits")),
                               &policy.declared_footprint.length) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "footprint_width_bits")),
                               &policy.declared_footprint.width) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "footprint_height_bits")),
                               &policy.declared_footprint.height) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "prediction_horizon_bits")),
                               &policy.prediction_horizon_s) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "sample_period_bits")),
                               &policy.sample_period_s) ||
            !DecodeFloat64Bits(
                fields.at(PolicyFieldName(index, "covariance_sigma_multiplier_bits")),
                &policy.covariance_sigma_multiplier) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "occlusion_expansion_bits")),
                               &policy.occlusion_expansion_m) ||
            !DecodeFloat64Bits(fields.at(PolicyFieldName(index, "severity_bits")),
                               &policy.severity)) {
            return false;
        }
        policy.calibration_profile_id = calibration_profile_id;
        if (!pack.by_equipment_class.emplace(policy.equipment_class, policy).second) {
            return false;
        }
    }
    if (ValidateRiskPolicyPack(pack) != RiskPolicyPackVerdict::kValid) {
        return false;
    }
    snapshot->risk_policy_pack = std::move(pack);
    return true;
}

}  // namespace

const char* ToString(NativeActivationVerdict verdict) {
    switch (verdict) {
        case NativeActivationVerdict::kLoaded:
            return "LOADED";
        case NativeActivationVerdict::kMissing:
            return "MISSING";
        case NativeActivationVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case NativeActivationVerdict::kUnsafeSnapshot:
            return "UNSAFE_SNAPSHOT";
        case NativeActivationVerdict::kUnreadable:
            return "UNREADABLE";
        case NativeActivationVerdict::kTooLarge:
            return "TOO_LARGE";
        case NativeActivationVerdict::kMalformed:
            return "MALFORMED";
        case NativeActivationVerdict::kDeviceMismatch:
            return "DEVICE_MISMATCH";
        case NativeActivationVerdict::kRuntimeMismatch:
            return "RUNTIME_MISMATCH";
        case NativeActivationVerdict::kNotYetValid:
            return "NOT_YET_VALID";
        case NativeActivationVerdict::kExpired:
            return "EXPIRED";
    }
    return "UNKNOWN";
}

NativeActivationLoadResult LoadNativeActivationSnapshot(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_runtime_version, std::int64_t now_utc_ms) {
    NativeActivationLoadResult result;
    if (state_directory.empty() || expected_edge_device_id.empty() || expected_runtime_version.empty() ||
        now_utc_ms < 0 || !IsPrivateOwnedDirectory(state_directory)) {
        result.verdict = NativeActivationVerdict::kUnsafeStateDirectory;
        return result;
    }
    const std::string path = state_directory + "/" + kNativeActivationFilename;
    std::string bytes;
    switch (ReadPrivateSnapshot(path, &bytes)) {
        case ReadSnapshotResult::kRead:
            break;
        case ReadSnapshotResult::kMissing:
            result.verdict = NativeActivationVerdict::kMissing;
            return result;
        case ReadSnapshotResult::kUnsafe:
            result.verdict = NativeActivationVerdict::kUnsafeSnapshot;
            return result;
        case ReadSnapshotResult::kUnreadable:
            result.verdict = NativeActivationVerdict::kUnreadable;
            return result;
        case ReadSnapshotResult::kTooLarge:
            result.verdict = NativeActivationVerdict::kTooLarge;
            return result;
    }

    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(bytes, &fields)) {
        result.verdict = NativeActivationVerdict::kMalformed;
        return result;
    }
    NativeActivationSnapshot snapshot;
    if (!DecodeBase64Url(fields["dispatch_id_b64"], &snapshot.dispatch_id) ||
        !DecodeBase64Url(fields["edge_device_id_b64"], &snapshot.edge_device_id) ||
        !DecodeBase64Url(fields["mission_id_b64"], &snapshot.mission_id) ||
        !DecodeBase64Url(fields["runtime_version_b64"], &snapshot.runtime_version) ||
        !ParseNonnegativeMillis(fields["activated_at_utc_ms"], &snapshot.activated_at_utc_ms) ||
        !ParseNonnegativeMillis(fields["valid_from_utc_ms"], &snapshot.context.valid_from_utc_ms) ||
        !ParseNonnegativeMillis(fields["valid_until_utc_ms"], &snapshot.context.valid_until_utc_ms) ||
        !IsSafeText(snapshot.dispatch_id) || !IsSafeText(snapshot.edge_device_id) ||
        !IsSafeText(snapshot.mission_id) || !IsSafeText(snapshot.runtime_version) ||
        !IsSha256Digest(fields["mission_contract_digest"]) ||
        !IsSha256Digest(fields["risk_policy_pack_digest"])) {
        result.verdict = NativeActivationVerdict::kMalformed;
        return result;
    }
    snapshot.context.mission_contract_digest = fields["mission_contract_digest"];
    snapshot.context.risk_policy_pack_digest = fields["risk_policy_pack_digest"];
    if (!BuildNativeRiskPolicyPack(fields, &snapshot)) {
        result.verdict = NativeActivationVerdict::kMalformed;
        return result;
    }
    if (snapshot.context.valid_until_utc_ms <= snapshot.context.valid_from_utc_ms ||
        snapshot.activated_at_utc_ms < snapshot.context.valid_from_utc_ms ||
        snapshot.activated_at_utc_ms > snapshot.context.valid_until_utc_ms) {
        result.verdict = NativeActivationVerdict::kMalformed;
        return result;
    }
    if (snapshot.edge_device_id != expected_edge_device_id) {
        result.verdict = NativeActivationVerdict::kDeviceMismatch;
        return result;
    }
    if (snapshot.runtime_version != expected_runtime_version) {
        result.verdict = NativeActivationVerdict::kRuntimeMismatch;
        return result;
    }
    if (now_utc_ms < snapshot.context.valid_from_utc_ms) {
        result.verdict = NativeActivationVerdict::kNotYetValid;
        return result;
    }
    if (now_utc_ms > snapshot.context.valid_until_utc_ms) {
        result.verdict = NativeActivationVerdict::kExpired;
        return result;
    }
    result.verdict = NativeActivationVerdict::kLoaded;
    result.snapshot = std::move(snapshot);
    return result;
}

}  // namespace ksi::edge

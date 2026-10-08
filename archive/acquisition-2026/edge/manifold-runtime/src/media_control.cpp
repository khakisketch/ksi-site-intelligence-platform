#include "ksi/edge/media_control.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

constexpr char kBaselineRequestMagic[] = "KSI_EDGE_MEDIA_BASELINE_REQUEST_V1";
constexpr char kBaselineMagic[] = "KSI_EDGE_MEDIA_BASELINE_V1";
constexpr char kOperatorTriggerMagic[] = "KSI_EDGE_MEDIA_OPERATOR_TRIGGER_V1";
constexpr std::size_t kMaximumRecordBytes = 8U * 1024U * 1024U;
constexpr std::size_t kMaximumTextBytes = 1024U;
constexpr std::size_t kMaximumFiles = 10'000U;
constexpr std::size_t kMaximumFileNameBytes = 255U;
constexpr std::int64_t kMaximumUtcMillis = 4'102'444'800'000LL;  // 2100-01-01

bool IsPrivateStateDirectory(const std::string& path) {
    if (path.empty() || path.front() != '/') {
        return false;
    }
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISDIR(value.st_mode) && !S_ISLNK(value.st_mode) &&
           value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

bool OpenPrivateStateDirectory(const std::string& path, int* descriptor) {
    if (descriptor == nullptr || !IsPrivateStateDirectory(path)) {
        return false;
    }
    const int opened = open(path.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (opened < 0) {
        return false;
    }
    struct stat value {};
    const bool safe = fstat(opened, &value) == 0 && S_ISDIR(value.st_mode) &&
                      value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
    if (!safe) {
        (void)close(opened);
        return false;
    }
    *descriptor = opened;
    return true;
}

bool FsyncDirectory(int descriptor) {
    return descriptor >= 0 && fsync(descriptor) == 0;
}

enum class PrivateReadVerdict {
    kRead,
    kMissing,
    kUnsafeStateDirectory,
    kUnsafe,
    kUnreadable,
    kTooLarge,
};

PrivateReadVerdict ReadPrivateRecord(const std::string& state_directory, const char* filename,
                                     std::string* output) {
    if (output == nullptr) {
        return PrivateReadVerdict::kUnreadable;
    }
    if (!IsPrivateStateDirectory(state_directory)) {
        return PrivateReadVerdict::kUnsafeStateDirectory;
    }
    int directory = -1;
    if (!OpenPrivateStateDirectory(state_directory, &directory)) {
        return PrivateReadVerdict::kUnsafeStateDirectory;
    }
    struct stat before {};
    if (fstatat(directory, filename, &before, AT_SYMLINK_NOFOLLOW) != 0) {
        const int error = errno;
        (void)close(directory);
        return error == ENOENT ? PrivateReadVerdict::kMissing : PrivateReadVerdict::kUnreadable;
    }
    if (!S_ISREG(before.st_mode) || before.st_uid != geteuid() || (before.st_mode & 0077) != 0 ||
        before.st_nlink != 1 || before.st_size < 1) {
        (void)close(directory);
        return PrivateReadVerdict::kUnsafe;
    }
    if (static_cast<std::uintmax_t>(before.st_size) > kMaximumRecordBytes) {
        (void)close(directory);
        return PrivateReadVerdict::kTooLarge;
    }
    const int file = openat(directory, filename, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (file < 0) {
        const int error = errno;
        (void)close(directory);
        return error == ENOENT ? PrivateReadVerdict::kMissing : PrivateReadVerdict::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(file, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           opened.st_uid == geteuid() && (opened.st_mode & 0077) == 0 &&
                           opened.st_nlink == 1 && opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(file);
        (void)close(directory);
        return PrivateReadVerdict::kUnsafe;
    }
    std::string content(static_cast<std::size_t>(opened.st_size), '\0');
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < content.size()) {
        const ssize_t received = read(file, content.data() + offset, content.size() - offset);
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
    const bool closed_file = close(file) == 0;
    const bool closed_directory = close(directory) == 0;
    if (!read_ok || !closed_file || !closed_directory || offset != content.size()) {
        return PrivateReadVerdict::kUnreadable;
    }
    *output = std::move(content);
    return PrivateReadVerdict::kRead;
}

bool WriteAll(int descriptor, const std::string& content) {
    std::size_t offset = 0U;
    while (offset < content.size()) {
        const ssize_t written = write(descriptor, content.data() + offset, content.size() - offset);
        if (written > 0) {
            offset += static_cast<std::size_t>(written);
            continue;
        }
        if (written < 0 && errno == EINTR) {
            continue;
        }
        return false;
    }
    return true;
}

MediaControlWriteVerdict WritePrivateRecord(const std::string& state_directory, const char* filename,
                                            const std::string& content) {
    if (!IsPrivateStateDirectory(state_directory)) {
        return MediaControlWriteVerdict::kUnsafeStateDirectory;
    }
    if (content.empty() || content.size() > kMaximumRecordBytes) {
        return MediaControlWriteVerdict::kInvalidRecord;
    }
    int directory = -1;
    if (!OpenPrivateStateDirectory(state_directory, &directory)) {
        return MediaControlWriteVerdict::kUnsafeStateDirectory;
    }
    const std::string base = std::string(".") + filename + ".tmp." + std::to_string(getpid()) + ".";
    int file = -1;
    std::string temporary;
    for (unsigned int attempt = 0U; attempt < 128U; ++attempt) {
        temporary = base + std::to_string(attempt);
        file = openat(directory, temporary.c_str(),
                      O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (file >= 0) {
            break;
        }
        if (errno != EEXIST) {
            (void)close(directory);
            return MediaControlWriteVerdict::kStorageError;
        }
    }
    if (file < 0) {
        (void)close(directory);
        return MediaControlWriteVerdict::kStorageError;
    }
    const bool written = WriteAll(file, content) && fchmod(file, 0600) == 0 && fsync(file) == 0;
    const bool closed = close(file) == 0;
    if (!written || !closed) {
        (void)unlinkat(directory, temporary.c_str(), 0);
        (void)FsyncDirectory(directory);
        (void)close(directory);
        return MediaControlWriteVerdict::kStorageError;
    }
    if (renameat(directory, temporary.c_str(), directory, filename) != 0 || !FsyncDirectory(directory)) {
        (void)unlinkat(directory, temporary.c_str(), 0);
        (void)FsyncDirectory(directory);
        (void)close(directory);
        return MediaControlWriteVerdict::kStorageError;
    }
    const bool directory_closed = close(directory) == 0;
    return directory_closed ? MediaControlWriteVerdict::kWritten
                            : MediaControlWriteVerdict::kStorageError;
}

bool IsPrintableText(const std::string& value, std::size_t maximum = kMaximumTextBytes) {
    if (value.empty() || value.size() > maximum) {
        return false;
    }
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x20U && character <= 0x7eU;
    });
}

bool IsNonce(const std::string& value) {
    return value.size() == 32U && std::all_of(value.begin(), value.end(), [](char character) {
        return (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f');
    });
}

bool IsNonnegativeMillis(std::int64_t value) {
    return value >= 0 && value <= kMaximumUtcMillis;
}

bool IsValidRequest(const MediaBaselineRequest& request) {
    return IsPrintableText(request.operator_id) && IsNonce(request.nonce) &&
           IsPrintableText(request.edge_device_id) && IsPrintableText(request.mission_id) &&
           IsPrintableText(request.dispatch_id) && IsSha256Digest(request.mission_contract_digest) &&
           IsNonnegativeMillis(request.requested_at_utc_ms) &&
           IsNonnegativeMillis(request.expires_at_utc_ms) &&
           request.expires_at_utc_ms > request.requested_at_utc_ms &&
           request.expires_at_utc_ms - request.requested_at_utc_ms <= kMaximumMediaControlTtlMs;
}

bool IsValidSourceFile(const SourceMediaFileHandle& file) {
    if (file.source_file_index < 0 || file.announced_bytes == 0U ||
        file.announced_bytes > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
        file.camera_file_name.empty() || file.camera_file_name.size() > kMaximumFileNameBytes) {
        return false;
    }
    return std::all_of(file.camera_file_name.begin(), file.camera_file_name.end(), [](unsigned char character) {
        return character >= 0x20U && character <= 0x7eU && character != '/' && character != '\\';
    });
}

bool HasValidUniqueSourceFiles(const std::vector<SourceMediaFileHandle>& files) {
    if (files.size() > kMaximumFiles) {
        return false;
    }
    std::set<std::int64_t> indices;
    std::set<std::string> names;
    for (const SourceMediaFileHandle& file : files) {
        if (!IsValidSourceFile(file) || !indices.insert(file.source_file_index).second ||
            !names.insert(file.camera_file_name).second) {
            return false;
        }
    }
    return true;
}

bool IsValidBaseline(const MediaBaselineRecord& record) {
    return IsValidRequest(record.request) && IsNonnegativeMillis(record.observed_at_utc_ms) &&
           record.observed_at_utc_ms >= record.request.requested_at_utc_ms &&
           record.observed_at_utc_ms <= record.request.expires_at_utc_ms &&
           IsSha256Digest(record.request_digest) &&
           record.request_digest == ComputeMediaBaselineRequestDigest(record.request) &&
           HasValidUniqueSourceFiles(record.files);
}

bool IsValidTrigger(const OperatorMediaOffloadTrigger& trigger) {
    return IsPrintableText(trigger.operator_id) && IsNonce(trigger.nonce) &&
           IsPrintableText(trigger.edge_device_id) && IsPrintableText(trigger.mission_id) &&
           IsPrintableText(trigger.dispatch_id) && IsSha256Digest(trigger.mission_contract_digest) &&
           IsSha256Digest(trigger.baseline_digest) && IsNonnegativeMillis(trigger.issued_at_utc_ms) &&
           IsNonnegativeMillis(trigger.expires_at_utc_ms) &&
           trigger.expires_at_utc_ms > trigger.issued_at_utc_ms &&
           trigger.expires_at_utc_ms - trigger.issued_at_utc_ms <= kMaximumMediaControlTtlMs;
}

bool IsValidActivation(const NativeActivationSnapshot& activation) {
    return IsPrintableText(activation.dispatch_id) && IsPrintableText(activation.edge_device_id) &&
           IsPrintableText(activation.mission_id) &&
           IsSha256Digest(activation.context.mission_contract_digest) &&
           IsNonnegativeMillis(activation.activated_at_utc_ms);
}

void AppendCanonicalField(const char* name, const std::string& value, std::string* output) {
    output->append(name);
    output->push_back('=');
    output->append(std::to_string(value.size()));
    output->push_back(':');
    output->append(value);
    output->push_back('\n');
}

void AppendCanonicalInteger(const char* name, std::int64_t value, std::string* output) {
    AppendCanonicalField(name, std::to_string(value), output);
}

std::string Base64UrlEncode(const std::string& input) {
    static constexpr char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string output;
    output.reserve((input.size() * 4U + 2U) / 3U);
    std::uint32_t accumulator = 0U;
    unsigned bits = 0U;
    for (const unsigned char character : input) {
        accumulator = (accumulator << 8U) | static_cast<std::uint32_t>(character);
        bits += 8U;
        while (bits >= 6U) {
            bits -= 6U;
            output.push_back(alphabet[(accumulator >> bits) & 0x3FU]);
        }
    }
    if (bits > 0U) {
        output.push_back(alphabet[(accumulator << (6U - bits)) & 0x3FU]);
    }
    return output;
}

int Base64UrlValue(char character) {
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

bool Base64UrlDecode(const std::string& input, std::string* output) {
    if (output == nullptr || input.empty() || input.size() % 4U == 1U) {
        return false;
    }
    const std::size_t remainder = input.size() % 4U;
    if ((remainder == 2U && (Base64UrlValue(input.back()) & 0x0F) != 0) ||
        (remainder == 3U && (Base64UrlValue(input.back()) & 0x03) != 0)) {
        return false;
    }
    std::string decoded;
    decoded.reserve((input.size() * 3U) / 4U);
    std::uint32_t accumulator = 0U;
    unsigned bits = 0U;
    for (const char character : input) {
        const int value = Base64UrlValue(character);
        if (value < 0) {
            return false;
        }
        accumulator = (accumulator << 6U) | static_cast<std::uint32_t>(value);
        bits += 6U;
        while (bits >= 8U) {
            bits -= 8U;
            decoded.push_back(static_cast<char>((accumulator >> bits) & 0xFFU));
        }
    }
    *output = std::move(decoded);
    return true;
}

bool ParseStrictLines(const std::string& content, const char* magic,
                      std::map<std::string, std::string>* fields) {
    if (fields == nullptr || content.empty() || content.back() != '\n') {
        return false;
    }
    std::vector<std::string> lines;
    std::size_t start = 0U;
    for (std::size_t index = 0U; index < content.size(); ++index) {
        const char character = content[index];
        if (character == '\r' || character == '\0') {
            return false;
        }
        if (character == '\n') {
            lines.push_back(content.substr(start, index - start));
            start = index + 1U;
        }
    }
    if (start != content.size() || lines.empty() || lines.front() != magic) {
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
    *fields = std::move(parsed);
    return true;
}

bool ParseInteger(const std::string& input, std::int64_t* output) {
    if (output == nullptr || input.empty()) {
        return false;
    }
    for (const char character : input) {
        if (character < '0' || character > '9') {
            return false;
        }
    }
    std::int64_t parsed = 0;
    const auto [end, error] = std::from_chars(input.data(), input.data() + input.size(), parsed);
    if (error != std::errc{} || end != input.data() + input.size() || !IsNonnegativeMillis(parsed)) {
        return false;
    }
    *output = parsed;
    return true;
}

bool ParseUnsigned(const std::string& input, std::uint64_t maximum, std::uint64_t* output) {
    if (output == nullptr || input.empty()) {
        return false;
    }
    for (const char character : input) {
        if (character < '0' || character > '9') {
            return false;
        }
    }
    std::uint64_t parsed = 0U;
    const auto [end, error] = std::from_chars(input.data(), input.data() + input.size(), parsed);
    if (error != std::errc{} || end != input.data() + input.size() || parsed > maximum) {
        return false;
    }
    *output = parsed;
    return true;
}

bool DecodeTextField(const std::map<std::string, std::string>& fields, const char* key,
                     std::string* output) {
    const auto found = fields.find(key);
    return found != fields.end() && Base64UrlDecode(found->second, output);
}

bool DecodeRequestFields(const std::map<std::string, std::string>& fields,
                         MediaBaselineRequest* request) {
    if (request == nullptr || !DecodeTextField(fields, "operator_id_b64", &request->operator_id) ||
        !DecodeTextField(fields, "nonce_b64", &request->nonce) ||
        !DecodeTextField(fields, "edge_device_id_b64", &request->edge_device_id) ||
        !DecodeTextField(fields, "mission_id_b64", &request->mission_id) ||
        !DecodeTextField(fields, "dispatch_id_b64", &request->dispatch_id) ||
        fields.find("mission_contract_digest") == fields.end() ||
        !ParseInteger(fields.at("requested_at_utc_ms"), &request->requested_at_utc_ms) ||
        !ParseInteger(fields.at("expires_at_utc_ms"), &request->expires_at_utc_ms)) {
        return false;
    }
    request->mission_contract_digest = fields.at("mission_contract_digest");
    return IsValidRequest(*request);
}

void AppendRequestFields(const MediaBaselineRequest& request, std::string* output) {
    output->append("operator_id_b64=");
    output->append(Base64UrlEncode(request.operator_id));
    output->push_back('\n');
    output->append("nonce_b64=");
    output->append(Base64UrlEncode(request.nonce));
    output->push_back('\n');
    output->append("edge_device_id_b64=");
    output->append(Base64UrlEncode(request.edge_device_id));
    output->push_back('\n');
    output->append("mission_id_b64=");
    output->append(Base64UrlEncode(request.mission_id));
    output->push_back('\n');
    output->append("dispatch_id_b64=");
    output->append(Base64UrlEncode(request.dispatch_id));
    output->push_back('\n');
    output->append("mission_contract_digest=");
    output->append(request.mission_contract_digest);
    output->push_back('\n');
    output->append("requested_at_utc_ms=");
    output->append(std::to_string(request.requested_at_utc_ms));
    output->push_back('\n');
    output->append("expires_at_utc_ms=");
    output->append(std::to_string(request.expires_at_utc_ms));
    output->push_back('\n');
}

std::string SerializeRequest(const MediaBaselineRequest& request) {
    std::string output(kBaselineRequestMagic);
    output.push_back('\n');
    AppendRequestFields(request, &output);
    return output;
}

std::string SerializeBaseline(const MediaBaselineRecord& record) {
    std::string output(kBaselineMagic);
    output.push_back('\n');
    AppendRequestFields(record.request, &output);
    output.append("observed_at_utc_ms=");
    output.append(std::to_string(record.observed_at_utc_ms));
    output.push_back('\n');
    output.append("request_digest=");
    output.append(record.request_digest);
    output.push_back('\n');
    output.append("file_count=");
    output.append(std::to_string(record.files.size()));
    output.push_back('\n');
    for (std::size_t index = 0U; index < record.files.size(); ++index) {
        const SourceMediaFileHandle& file = record.files[index];
        const std::string prefix = "file_" + std::to_string(index) + "_";
        output.append(prefix);
        output.append("index=");
        output.append(std::to_string(file.source_file_index));
        output.push_back('\n');
        output.append(prefix);
        output.append("name_b64=");
        output.append(Base64UrlEncode(file.camera_file_name));
        output.push_back('\n');
        output.append(prefix);
        output.append("bytes=");
        output.append(std::to_string(file.announced_bytes));
        output.push_back('\n');
    }
    return output;
}

std::string SerializeTrigger(const OperatorMediaOffloadTrigger& trigger) {
    std::string output(kOperatorTriggerMagic);
    output.push_back('\n');
    output.append("operator_id_b64=");
    output.append(Base64UrlEncode(trigger.operator_id));
    output.push_back('\n');
    output.append("nonce_b64=");
    output.append(Base64UrlEncode(trigger.nonce));
    output.push_back('\n');
    output.append("edge_device_id_b64=");
    output.append(Base64UrlEncode(trigger.edge_device_id));
    output.push_back('\n');
    output.append("mission_id_b64=");
    output.append(Base64UrlEncode(trigger.mission_id));
    output.push_back('\n');
    output.append("dispatch_id_b64=");
    output.append(Base64UrlEncode(trigger.dispatch_id));
    output.push_back('\n');
    output.append("mission_contract_digest=");
    output.append(trigger.mission_contract_digest);
    output.push_back('\n');
    output.append("baseline_digest=");
    output.append(trigger.baseline_digest);
    output.push_back('\n');
    output.append("issued_at_utc_ms=");
    output.append(std::to_string(trigger.issued_at_utc_ms));
    output.push_back('\n');
    output.append("expires_at_utc_ms=");
    output.append(std::to_string(trigger.expires_at_utc_ms));
    output.push_back('\n');
    return output;
}

MediaControlLoadVerdict MapReadVerdict(PrivateReadVerdict verdict) {
    switch (verdict) {
        case PrivateReadVerdict::kRead:
            return MediaControlLoadVerdict::kLoaded;
        case PrivateReadVerdict::kMissing:
            return MediaControlLoadVerdict::kMissing;
        case PrivateReadVerdict::kUnsafeStateDirectory:
            return MediaControlLoadVerdict::kUnsafeStateDirectory;
        case PrivateReadVerdict::kUnsafe:
            return MediaControlLoadVerdict::kUnsafeRecord;
        case PrivateReadVerdict::kUnreadable:
            return MediaControlLoadVerdict::kUnreadable;
        case PrivateReadVerdict::kTooLarge:
            return MediaControlLoadVerdict::kTooLarge;
    }
    return MediaControlLoadVerdict::kUnreadable;
}

bool SameRequestBinding(const MediaBaselineRequest& request, const NativeActivationSnapshot& activation) {
    return request.edge_device_id == activation.edge_device_id && request.mission_id == activation.mission_id &&
           request.dispatch_id == activation.dispatch_id &&
           request.mission_contract_digest == activation.context.mission_contract_digest;
}

bool SameTriggerBinding(const OperatorMediaOffloadTrigger& trigger,
                        const NativeActivationSnapshot& activation) {
    return trigger.edge_device_id == activation.edge_device_id && trigger.mission_id == activation.mission_id &&
           trigger.dispatch_id == activation.dispatch_id &&
           trigger.mission_contract_digest == activation.context.mission_contract_digest;
}

}  // namespace

const char* ToString(MediaControlLoadVerdict verdict) {
    switch (verdict) {
        case MediaControlLoadVerdict::kLoaded:
            return "LOADED";
        case MediaControlLoadVerdict::kMissing:
            return "MISSING";
        case MediaControlLoadVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case MediaControlLoadVerdict::kUnsafeRecord:
            return "UNSAFE_RECORD";
        case MediaControlLoadVerdict::kUnreadable:
            return "UNREADABLE";
        case MediaControlLoadVerdict::kTooLarge:
            return "TOO_LARGE";
        case MediaControlLoadVerdict::kMalformed:
            return "MALFORMED";
        case MediaControlLoadVerdict::kNotYetValid:
            return "NOT_YET_VALID";
        case MediaControlLoadVerdict::kExpired:
            return "EXPIRED";
    }
    return "UNKNOWN";
}

const char* ToString(MediaControlWriteVerdict verdict) {
    switch (verdict) {
        case MediaControlWriteVerdict::kWritten:
            return "WRITTEN";
        case MediaControlWriteVerdict::kReplaced:
            return "REPLACED";
        case MediaControlWriteVerdict::kDuplicate:
            return "DUPLICATE";
        case MediaControlWriteVerdict::kConflict:
            return "CONFLICT";
        case MediaControlWriteVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case MediaControlWriteVerdict::kInvalidRecord:
            return "INVALID_RECORD";
        case MediaControlWriteVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

std::string ComputeMediaBaselineRequestDigest(const MediaBaselineRequest& request) {
    if (!IsValidRequest(request)) {
        return {};
    }
    std::string canonical("KSI_EDGE_MEDIA_BASELINE_REQUEST_CANONICAL_V1\n");
    AppendCanonicalField("operator_id", request.operator_id, &canonical);
    AppendCanonicalField("nonce", request.nonce, &canonical);
    AppendCanonicalField("edge_device_id", request.edge_device_id, &canonical);
    AppendCanonicalField("mission_id", request.mission_id, &canonical);
    AppendCanonicalField("dispatch_id", request.dispatch_id, &canonical);
    AppendCanonicalField("mission_contract_digest", request.mission_contract_digest, &canonical);
    AppendCanonicalInteger("requested_at_utc_ms", request.requested_at_utc_ms, &canonical);
    AppendCanonicalInteger("expires_at_utc_ms", request.expires_at_utc_ms, &canonical);
    return Sha256Digest(reinterpret_cast<const std::uint8_t*>(canonical.data()), canonical.size());
}

std::string ComputeMediaBaselineRecordDigest(const MediaBaselineRecord& record) {
    if (!IsValidBaseline(record)) {
        return {};
    }
    std::vector<SourceMediaFileHandle> files = record.files;
    std::sort(files.begin(), files.end(), [](const SourceMediaFileHandle& left,
                                             const SourceMediaFileHandle& right) {
        if (left.source_file_index != right.source_file_index) {
            return left.source_file_index < right.source_file_index;
        }
        if (left.camera_file_name != right.camera_file_name) {
            return left.camera_file_name < right.camera_file_name;
        }
        return left.announced_bytes < right.announced_bytes;
    });
    std::string canonical("KSI_EDGE_MEDIA_BASELINE_CANONICAL_V1\n");
    AppendCanonicalField("request_digest", record.request_digest, &canonical);
    AppendCanonicalInteger("observed_at_utc_ms", record.observed_at_utc_ms, &canonical);
    AppendCanonicalInteger("file_count", static_cast<std::int64_t>(files.size()), &canonical);
    for (const SourceMediaFileHandle& file : files) {
        AppendCanonicalInteger("file_index", file.source_file_index, &canonical);
        AppendCanonicalField("file_name", file.camera_file_name, &canonical);
        AppendCanonicalInteger("file_bytes", static_cast<std::int64_t>(file.announced_bytes), &canonical);
    }
    return Sha256Digest(reinterpret_cast<const std::uint8_t*>(canonical.data()), canonical.size());
}

std::string ComputeOperatorMediaOffloadTriggerDigest(
    const OperatorMediaOffloadTrigger& trigger) {
    if (!IsValidTrigger(trigger)) {
        return {};
    }
    std::string canonical("KSI_EDGE_MEDIA_OPERATOR_TRIGGER_CANONICAL_V1\n");
    AppendCanonicalField("operator_id", trigger.operator_id, &canonical);
    AppendCanonicalField("nonce", trigger.nonce, &canonical);
    AppendCanonicalField("edge_device_id", trigger.edge_device_id, &canonical);
    AppendCanonicalField("mission_id", trigger.mission_id, &canonical);
    AppendCanonicalField("dispatch_id", trigger.dispatch_id, &canonical);
    AppendCanonicalField("mission_contract_digest", trigger.mission_contract_digest, &canonical);
    AppendCanonicalField("baseline_digest", trigger.baseline_digest, &canonical);
    AppendCanonicalInteger("issued_at_utc_ms", trigger.issued_at_utc_ms, &canonical);
    AppendCanonicalInteger("expires_at_utc_ms", trigger.expires_at_utc_ms, &canonical);
    return Sha256Digest(reinterpret_cast<const std::uint8_t*>(canonical.data()), canonical.size());
}

MediaControlWriteVerdict WriteMediaBaselineRequest(const std::string& state_directory,
                                                    const MediaBaselineRequest& request) {
    if (!IsValidRequest(request)) {
        return MediaControlWriteVerdict::kInvalidRecord;
    }
    return WritePrivateRecord(state_directory, kMediaBaselineRequestFilename, SerializeRequest(request));
}

MediaBaselineRequestLoadResult LoadMediaBaselineRequest(const std::string& state_directory,
                                                         std::int64_t now_utc_ms) {
    MediaBaselineRequestLoadResult result;
    if (!IsNonnegativeMillis(now_utc_ms)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    std::string content;
    const PrivateReadVerdict read =
        ReadPrivateRecord(state_directory, kMediaBaselineRequestFilename, &content);
    if (read != PrivateReadVerdict::kRead) {
        result.verdict = MapReadVerdict(read);
        return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(content, kBaselineRequestMagic, &fields) || fields.size() != 8U ||
        !DecodeRequestFields(fields, &result.request)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    if (now_utc_ms < result.request.requested_at_utc_ms) {
        result.verdict = MediaControlLoadVerdict::kNotYetValid;
    } else if (now_utc_ms > result.request.expires_at_utc_ms) {
        result.verdict = MediaControlLoadVerdict::kExpired;
    } else {
        result.verdict = MediaControlLoadVerdict::kLoaded;
    }
    return result;
}

MediaControlWriteVerdict WriteMediaBaselineRecord(const std::string& state_directory,
                                                   const MediaBaselineRecord& record) {
    if (!IsValidBaseline(record)) {
        return MediaControlWriteVerdict::kInvalidRecord;
    }
    const MediaBaselineRecordLoadResult existing = LoadMediaBaselineRecord(state_directory);
    if (existing.verdict == MediaControlLoadVerdict::kLoaded) {
        const std::string existing_digest = ComputeMediaBaselineRecordDigest(existing.record);
        const std::string desired_digest = ComputeMediaBaselineRecordDigest(record);
        if (existing_digest == desired_digest) {
            return MediaControlWriteVerdict::kDuplicate;
        }
        // This API is called only by the DPK while no activation is loaded.
        // A later trigger includes the new baseline digest, so an old trigger
        // cannot silently authorize the replacement. Retaining one stale
        // baseline forever would make the fixed private control directory
        // single-use and force operators into unsafe manual cleanup.
        const MediaControlWriteVerdict written =
            WritePrivateRecord(state_directory, kMediaBaselineFilename, SerializeBaseline(record));
        return written == MediaControlWriteVerdict::kWritten ? MediaControlWriteVerdict::kReplaced
                                                              : written;
    }
    if (existing.verdict != MediaControlLoadVerdict::kMissing) {
        return existing.verdict == MediaControlLoadVerdict::kUnsafeStateDirectory
                   ? MediaControlWriteVerdict::kUnsafeStateDirectory
                   : MediaControlWriteVerdict::kStorageError;
    }
    return WritePrivateRecord(state_directory, kMediaBaselineFilename, SerializeBaseline(record));
}

MediaBaselineRecordLoadResult LoadMediaBaselineRecord(const std::string& state_directory) {
    MediaBaselineRecordLoadResult result;
    std::string content;
    const PrivateReadVerdict read = ReadPrivateRecord(state_directory, kMediaBaselineFilename, &content);
    if (read != PrivateReadVerdict::kRead) {
        result.verdict = MapReadVerdict(read);
        return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(content, kBaselineMagic, &fields) || !DecodeRequestFields(fields, &result.record.request) ||
        fields.find("request_digest") == fields.end() || fields.find("observed_at_utc_ms") == fields.end() ||
        fields.find("file_count") == fields.end() ||
        !ParseInteger(fields.at("observed_at_utc_ms"), &result.record.observed_at_utc_ms)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    result.record.request_digest = fields.at("request_digest");
    std::uint64_t file_count = 0U;
    if (!ParseUnsigned(fields.at("file_count"), kMaximumFiles, &file_count) ||
        fields.size() != 11U + static_cast<std::size_t>(file_count) * 3U) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    result.record.files.reserve(static_cast<std::size_t>(file_count));
    for (std::size_t index = 0U; index < static_cast<std::size_t>(file_count); ++index) {
        const std::string prefix = "file_" + std::to_string(index) + "_";
        const auto index_field = fields.find(prefix + "index");
        const auto name_field = fields.find(prefix + "name_b64");
        const auto bytes_field = fields.find(prefix + "bytes");
        if (index_field == fields.end() || name_field == fields.end() || bytes_field == fields.end()) {
            result.verdict = MediaControlLoadVerdict::kMalformed;
            return result;
        }
        std::uint64_t file_index = 0U;
        std::uint64_t byte_count = 0U;
        SourceMediaFileHandle file;
        if (!ParseUnsigned(index_field->second, static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
                           &file_index) ||
            !ParseUnsigned(bytes_field->second,
                           static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
                           &byte_count) ||
            !Base64UrlDecode(name_field->second, &file.camera_file_name)) {
            result.verdict = MediaControlLoadVerdict::kMalformed;
            return result;
        }
        file.source_file_index = static_cast<std::int64_t>(file_index);
        file.announced_bytes = byte_count;
        result.record.files.push_back(std::move(file));
    }
    result.verdict = IsValidBaseline(result.record) ? MediaControlLoadVerdict::kLoaded
                                                     : MediaControlLoadVerdict::kMalformed;
    return result;
}

MediaControlWriteVerdict WriteOperatorMediaOffloadTrigger(
    const std::string& state_directory, const OperatorMediaOffloadTrigger& trigger) {
    if (!IsValidTrigger(trigger)) {
        return MediaControlWriteVerdict::kInvalidRecord;
    }
    return WritePrivateRecord(state_directory, kMediaOperatorTriggerFilename, SerializeTrigger(trigger));
}

OperatorMediaOffloadTriggerLoadResult LoadOperatorMediaOffloadTrigger(
    const std::string& state_directory, std::int64_t now_utc_ms) {
    OperatorMediaOffloadTriggerLoadResult result;
    if (!IsNonnegativeMillis(now_utc_ms)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    std::string content;
    const PrivateReadVerdict read =
        ReadPrivateRecord(state_directory, kMediaOperatorTriggerFilename, &content);
    if (read != PrivateReadVerdict::kRead) {
        result.verdict = MapReadVerdict(read);
        return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(content, kOperatorTriggerMagic, &fields) || fields.size() != 9U ||
        !DecodeTextField(fields, "operator_id_b64", &result.trigger.operator_id) ||
        !DecodeTextField(fields, "nonce_b64", &result.trigger.nonce) ||
        !DecodeTextField(fields, "edge_device_id_b64", &result.trigger.edge_device_id) ||
        !DecodeTextField(fields, "mission_id_b64", &result.trigger.mission_id) ||
        !DecodeTextField(fields, "dispatch_id_b64", &result.trigger.dispatch_id) ||
        fields.find("mission_contract_digest") == fields.end() ||
        fields.find("baseline_digest") == fields.end() || fields.find("issued_at_utc_ms") == fields.end() ||
        fields.find("expires_at_utc_ms") == fields.end() ||
        !ParseInteger(fields.at("issued_at_utc_ms"), &result.trigger.issued_at_utc_ms) ||
        !ParseInteger(fields.at("expires_at_utc_ms"), &result.trigger.expires_at_utc_ms)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
        return result;
    }
    result.trigger.mission_contract_digest = fields.at("mission_contract_digest");
    result.trigger.baseline_digest = fields.at("baseline_digest");
    if (!IsValidTrigger(result.trigger)) {
        result.verdict = MediaControlLoadVerdict::kMalformed;
    } else if (now_utc_ms < result.trigger.issued_at_utc_ms) {
        result.verdict = MediaControlLoadVerdict::kNotYetValid;
    } else if (now_utc_ms > result.trigger.expires_at_utc_ms) {
        result.verdict = MediaControlLoadVerdict::kExpired;
    } else {
        result.verdict = MediaControlLoadVerdict::kLoaded;
    }
    return result;
}

const char* ToString(MediaControlSelectionVerdict verdict) {
    switch (verdict) {
        case MediaControlSelectionVerdict::kReady:
            return "READY";
        case MediaControlSelectionVerdict::kInvalidActivation:
            return "INVALID_ACTIVATION";
        case MediaControlSelectionVerdict::kInvalidBaseline:
            return "INVALID_BASELINE";
        case MediaControlSelectionVerdict::kInvalidTrigger:
            return "INVALID_TRIGGER";
        case MediaControlSelectionVerdict::kBaselineAfterActivation:
            return "BASELINE_AFTER_ACTIVATION";
        case MediaControlSelectionVerdict::kBaselineExpiredBeforeActivation:
            return "BASELINE_EXPIRED_BEFORE_ACTIVATION";
        case MediaControlSelectionVerdict::kTriggerBeforeActivation:
            return "TRIGGER_BEFORE_ACTIVATION";
        case MediaControlSelectionVerdict::kBindingMismatch:
            return "BINDING_MISMATCH";
        case MediaControlSelectionVerdict::kBaselineDigestMismatch:
            return "BASELINE_DIGEST_MISMATCH";
    }
    return "UNKNOWN";
}

MediaControlSelectionResult BuildOperatorMediaSelectionContext(
    const NativeActivationSnapshot& activation, const MediaBaselineRecord& baseline,
    const OperatorMediaOffloadTrigger& trigger, std::int64_t now_utc_ms) {
    MediaControlSelectionResult result;
    if (!IsValidActivation(activation)) {
        result.verdict = MediaControlSelectionVerdict::kInvalidActivation;
        return result;
    }
    if (!IsValidBaseline(baseline)) {
        result.verdict = MediaControlSelectionVerdict::kInvalidBaseline;
        return result;
    }
    if (!IsValidTrigger(trigger) || !IsNonnegativeMillis(now_utc_ms) ||
        now_utc_ms < trigger.issued_at_utc_ms || now_utc_ms > trigger.expires_at_utc_ms) {
        result.verdict = MediaControlSelectionVerdict::kInvalidTrigger;
        return result;
    }
    if (!SameRequestBinding(baseline.request, activation) || !SameTriggerBinding(trigger, activation)) {
        result.verdict = MediaControlSelectionVerdict::kBindingMismatch;
        return result;
    }
    if (baseline.observed_at_utc_ms > activation.activated_at_utc_ms) {
        result.verdict = MediaControlSelectionVerdict::kBaselineAfterActivation;
        return result;
    }
    // A baseline request is deliberately short lived. It proves that the local
    // operator prepared this exact card state for this activation, not merely
    // that a matching list existed at some remote earlier time.
    if (activation.activated_at_utc_ms > baseline.request.expires_at_utc_ms) {
        result.verdict = MediaControlSelectionVerdict::kBaselineExpiredBeforeActivation;
        return result;
    }
    if (trigger.issued_at_utc_ms < activation.activated_at_utc_ms) {
        result.verdict = MediaControlSelectionVerdict::kTriggerBeforeActivation;
        return result;
    }
    const std::string baseline_digest = ComputeMediaBaselineRecordDigest(baseline);
    if (!IsSha256Digest(baseline_digest) || trigger.baseline_digest != baseline_digest) {
        result.verdict = MediaControlSelectionVerdict::kBaselineDigestMismatch;
        return result;
    }
    const std::string trigger_digest = ComputeOperatorMediaOffloadTriggerDigest(trigger);
    if (!IsSha256Digest(trigger_digest)) {
        result.verdict = MediaControlSelectionVerdict::kInvalidTrigger;
        return result;
    }
    MissionMediaSelectionContext context;
    context.mission_id = activation.mission_id;
    context.dispatch_id = activation.dispatch_id;
    context.mission_contract_digest = activation.context.mission_contract_digest;
    context.trigger_kind = MediaOffloadTriggerKind::kOperatorApprovedOneShot;
    context.trigger_evidence_digest = trigger_digest;
    context.baseline_observed_at_utc_ms = baseline.observed_at_utc_ms;
    context.activated_at_utc_ms = activation.activated_at_utc_ms;
    context.triggered_at_utc_ms = trigger.issued_at_utc_ms;
    context.baseline_files = baseline.files;
    result.verdict = MediaControlSelectionVerdict::kReady;
    result.selection_context = std::move(context);
    return result;
}

}  // namespace ksi::edge

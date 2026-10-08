#include "ksi/edge/mission_kmz.hpp"

#include "ksi/edge/crypto.hpp"

#include <array>
#include <cerrno>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

// 이 파일의 사설 파일 판독기는 activation.cpp / runtime_profile.cpp 와 같은
// 검사를 같은 순서로 한다(디렉터리 사설성 → lstat → O_NOFOLLOW open → fstat
// 재확인 → 짧은 read 반복). 공용 헤더로 뽑지 않고 각 판독기가 자기 것을 갖는
// 것이 이 디렉터리의 기존 관습이다 — 판독기마다 상한·필수 필드 집합·실패
// verdict 가 다르고, 공유 헬퍼가 한 곳의 요구에 맞춰 완화되면 나머지 판독기가
// 조용히 함께 느슨해진다. 검사 자체를 바꿀 일이 생기면 세 파일을 함께 바꾼다.

constexpr char kMagic[] = "KSI_EDGE_NATIVE_MISSION_KMZ_V1";
constexpr std::size_t kMaximumSidecarBytes = 8U * 1024U;

constexpr std::array<const char*, 6> kRequiredFields = {
    "dispatch_id_b64", "edge_device_id_b64",      "kmz_byte_count",
    "kmz_sha256",      "mission_contract_digest", "mission_id_b64",
};

bool IsPrivateOwnedDirectory(const std::string& path) {
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISDIR(value.st_mode) &&
           !S_ISLNK(value.st_mode) && value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

enum class ReadResult {
    kRead,
    kMissing,
    kUnsafe,
    kUnreadable,
    kTooLarge,
};

ReadResult ReadPrivateFile(const std::string& path, std::size_t maximum_bytes,
                           std::string* output) {
    if (output == nullptr) {
        return ReadResult::kUnreadable;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return errno == ENOENT ? ReadResult::kMissing : ReadResult::kUnreadable;
    }
    if (before.st_size > static_cast<off_t>(maximum_bytes)) {
        return ReadResult::kTooLarge;
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_size < 1) {
        return ReadResult::kUnsafe;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return errno == ENOENT ? ReadResult::kMissing : ReadResult::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_size == before.st_size &&
                           opened.st_nlink == 1;
    if (!same_file) {
        (void)close(descriptor);
        return ReadResult::kUnsafe;
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
        return ReadResult::kUnreadable;
    }
    *output = std::move(content);
    return ReadResult::kRead;
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
    if (start != input.size() || lines.size() != kRequiredFields.size() + 1U ||
        lines[0] != kMagic) {
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
    // 정확히 이 집합이어야 한다 — 모르는 필드를 조용히 무시하는 판독기는 새 안전
    // 필드가 생겼을 때 그것을 무시하는 다운그레이드 경로가 된다.
    for (const char* required : kRequiredFields) {
        if (parsed.find(required) == parsed.end()) {
            return false;
        }
    }
    *output = std::move(parsed);
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

// bare 64자리 소문자 hex. ``IsSha256Digest`` 는 "sha256:" 접두사 형태를 보므로
// 그 함수를 여기 쓸 수 없다 — 이 필드는 Core 발급 원장의 표기를 그대로 옮긴다.
bool IsBareSha256Hex(const std::string& value) {
    if (value.size() != 64U) {
        return false;
    }
    for (const char character : value) {
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool ParseByteCount(const std::string& input, std::size_t* output) {
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
        value > kMaximumMissionKmzBytes) {
        return false;
    }
    *output = value;
    return true;
}

NativeMissionKmzVerdict VerdictForSidecarRead(ReadResult result) {
    switch (result) {
        case ReadResult::kRead:
            return NativeMissionKmzVerdict::kLoaded;
        case ReadResult::kMissing:
            return NativeMissionKmzVerdict::kMissing;
        case ReadResult::kUnsafe:
            return NativeMissionKmzVerdict::kUnsafeSidecar;
        case ReadResult::kUnreadable:
            return NativeMissionKmzVerdict::kUnreadable;
        case ReadResult::kTooLarge:
            return NativeMissionKmzVerdict::kTooLarge;
    }
    return NativeMissionKmzVerdict::kMalformed;
}

NativeMissionKmzVerdict VerdictForKmzRead(ReadResult result) {
    switch (result) {
        case ReadResult::kRead:
            return NativeMissionKmzVerdict::kLoaded;
        // 사이드카가 가리키는 파일이 없는 것은 "KMZ 없음"이 아니라 **깨진 짝**이다.
        // 없다고 조용히 넘어가면 사이드카를 남긴 채 KMZ 만 지우는 것으로 대조를
        // 통과시킬 수 있다.
        case ReadResult::kMissing:
            return NativeMissionKmzVerdict::kUnsafeKmz;
        case ReadResult::kUnsafe:
            return NativeMissionKmzVerdict::kUnsafeKmz;
        case ReadResult::kUnreadable:
            return NativeMissionKmzVerdict::kUnreadable;
        case ReadResult::kTooLarge:
            return NativeMissionKmzVerdict::kTooLarge;
    }
    return NativeMissionKmzVerdict::kMalformed;
}

}  // namespace

const char* ToString(NativeMissionKmzVerdict verdict) {
    switch (verdict) {
        case NativeMissionKmzVerdict::kLoaded:
            return "LOADED";
        case NativeMissionKmzVerdict::kMissing:
            return "MISSING";
        case NativeMissionKmzVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case NativeMissionKmzVerdict::kUnsafeSidecar:
            return "UNSAFE_SIDECAR";
        case NativeMissionKmzVerdict::kUnsafeKmz:
            return "UNSAFE_KMZ";
        case NativeMissionKmzVerdict::kUnreadable:
            return "UNREADABLE";
        case NativeMissionKmzVerdict::kTooLarge:
            return "TOO_LARGE";
        case NativeMissionKmzVerdict::kMalformed:
            return "MALFORMED";
        case NativeMissionKmzVerdict::kDeviceMismatch:
            return "DEVICE_MISMATCH";
        case NativeMissionKmzVerdict::kMissionMismatch:
            return "MISSION_MISMATCH";
        case NativeMissionKmzVerdict::kContractMismatch:
            return "CONTRACT_MISMATCH";
        case NativeMissionKmzVerdict::kSizeMismatch:
            return "SIZE_MISMATCH";
        case NativeMissionKmzVerdict::kDigestMismatch:
            return "DIGEST_MISMATCH";
    }
    return "UNKNOWN";
}

NativeMissionKmzLoadResult LoadNativeMissionKmz(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_mission_id,
    const std::string& expected_mission_contract_digest) {
    NativeMissionKmzLoadResult result;
    if (state_directory.empty() || expected_edge_device_id.empty() ||
        expected_mission_id.empty() || !IsSha256Digest(expected_mission_contract_digest) ||
        !IsPrivateOwnedDirectory(state_directory)) {
        result.verdict = NativeMissionKmzVerdict::kUnsafeStateDirectory;
        return result;
    }

    std::string sidecar_bytes;
    const ReadResult sidecar_read = ReadPrivateFile(
        state_directory + "/" + kNativeMissionKmzFilename, kMaximumSidecarBytes, &sidecar_bytes);
    if (sidecar_read != ReadResult::kRead) {
        result.verdict = VerdictForSidecarRead(sidecar_read);
        return result;
    }

    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(sidecar_bytes, &fields)) {
        result.verdict = NativeMissionKmzVerdict::kMalformed;
        return result;
    }
    NativeMissionKmz kmz;
    std::size_t declared_byte_count = 0U;
    if (!DecodeBase64Url(fields["dispatch_id_b64"], &kmz.dispatch_id) ||
        !DecodeBase64Url(fields["edge_device_id_b64"], &kmz.edge_device_id) ||
        !DecodeBase64Url(fields["mission_id_b64"], &kmz.mission_id) ||
        !IsSafeText(kmz.dispatch_id) || !IsSafeText(kmz.edge_device_id) ||
        !IsSafeText(kmz.mission_id) || !IsSha256Digest(fields["mission_contract_digest"]) ||
        !IsBareSha256Hex(fields["kmz_sha256"]) ||
        !ParseByteCount(fields["kmz_byte_count"], &declared_byte_count)) {
        result.verdict = NativeMissionKmzVerdict::kMalformed;
        return result;
    }
    kmz.mission_contract_digest = fields["mission_contract_digest"];
    kmz.kmz_sha256 = fields["kmz_sha256"];

    // 신원 대조를 바이트 읽기 **앞**에 둔다 — 다른 장비/임무의 KMZ 를 읽어
    // 메모리에 올릴 이유가 없다.
    if (kmz.edge_device_id != expected_edge_device_id) {
        result.verdict = NativeMissionKmzVerdict::kDeviceMismatch;
        return result;
    }
    if (kmz.mission_id != expected_mission_id) {
        result.verdict = NativeMissionKmzVerdict::kMissionMismatch;
        return result;
    }
    if (kmz.mission_contract_digest != expected_mission_contract_digest) {
        result.verdict = NativeMissionKmzVerdict::kContractMismatch;
        return result;
    }

    std::string bytes;
    const ReadResult kmz_read = ReadPrivateFile(
        state_directory + "/" + kActiveMissionKmzFilename, kMaximumMissionKmzBytes, &bytes);
    if (kmz_read != ReadResult::kRead) {
        result.verdict = VerdictForKmzRead(kmz_read);
        return result;
    }
    if (bytes.size() != declared_byte_count) {
        result.verdict = NativeMissionKmzVerdict::kSizeMismatch;
        return result;
    }
    if (Sha256Hex(reinterpret_cast<const std::uint8_t*>(bytes.data()), bytes.size()) !=
        kmz.kmz_sha256) {
        result.verdict = NativeMissionKmzVerdict::kDigestMismatch;
        return result;
    }
    kmz.bytes = std::move(bytes);
    result.verdict = NativeMissionKmzVerdict::kLoaded;
    result.kmz = std::move(kmz);
    return result;
}

}  // namespace ksi::edge

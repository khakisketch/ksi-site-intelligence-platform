#include "ksi/edge/flight_execution.hpp"

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <map>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

// ── 사설 텍스트 규약(활성화/미션 KMZ 판독기와 같은 관습, 각 파일이 자기 것을
// 갖는다 — mission_kmz.cpp 상단 주석 참조) ──────────────────────────────────

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

std::string EncodeBase64Url(const std::string& input) {
    constexpr char kAlphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string output;
    output.reserve(((input.size() + 2U) / 3U) * 4U);
    std::size_t offset = 0U;
    while (offset + 3U <= input.size()) {
        const std::uint32_t value =
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset])) << 16U) |
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset + 1U])) << 8U) |
            static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset + 2U]));
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 6U) & 0x3FU]);
        output.push_back(kAlphabet[value & 0x3FU]);
        offset += 3U;
    }
    const std::size_t remaining = input.size() - offset;
    if (remaining == 1U) {
        const std::uint32_t value =
            static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset])) << 16U;
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
    } else if (remaining == 2U) {
        const std::uint32_t value =
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset])) << 16U) |
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset + 1U])) << 8U);
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 6U) & 0x3FU]);
    }
    return output;
}

bool ParseNonnegativeInt64(const std::string& input, std::int64_t* output) {
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

bool ParseStageDigit(const std::string& input, FlightExecutionStage* stage) {
    std::int64_t value = 0;
    if (stage == nullptr || !ParseNonnegativeInt64(input, &value) || value > 4) {
        return false;
    }
    *stage = static_cast<FlightExecutionStage>(value);
    return true;
}

bool IsPrivateOwnedDirectory(const std::string& path) {
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISDIR(value.st_mode) &&
           !S_ISLNK(value.st_mode) && value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

// media_offload.cpp 의 EnsurePrivateStateDirectory 와 같은 성질(사설 소유,
// group/other 권한 없음, 심링크 아님) — 각 파일이 자기 사본을 갖는 관습을 그대로
// 따른다.
bool EnsurePrivateStateDirectory(const std::string& path) {
    std::error_code error;
    if (!std::filesystem::create_directories(path, error) && error) {
        return false;
    }
    struct stat value {};
    if (lstat(path.c_str(), &value) != 0 || !S_ISDIR(value.st_mode) || S_ISLNK(value.st_mode) ||
        value.st_uid != geteuid()) {
        return false;
    }
    if ((value.st_mode & 0077) != 0 && chmod(path.c_str(), 0700) != 0) {
        return false;
    }
    return lstat(path.c_str(), &value) == 0 && (value.st_mode & 0077) == 0;
}

bool FsyncDirectoryBestEffort(const std::string& path) {
    const int descriptor = open(path.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return false;
    }
    const bool ok = fsync(descriptor) == 0;
    (void)close(descriptor);
    return ok;
}

enum class PrivateFileReadResult {
    kRead,
    kMissing,
    kUnsafe,
    kUnreadable,
    kTooLarge,
};

// activation.cpp/mission_kmz.cpp 와 같은 순서(디렉터리 사설성 → lstat → O_NOFOLLOW
// open → fstat 재확인 → 짧은 read 반복) — 판독기마다 자기 상한·verdict 를 갖는
// 이 디렉터리의 관습을 그대로 따른다.
PrivateFileReadResult ReadPrivateFile(const std::string& path, std::size_t maximum_bytes,
                                      std::string* output) {
    if (output == nullptr) {
        return PrivateFileReadResult::kUnreadable;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return errno == ENOENT ? PrivateFileReadResult::kMissing : PrivateFileReadResult::kUnreadable;
    }
    if (before.st_size > static_cast<off_t>(maximum_bytes)) {
        return PrivateFileReadResult::kTooLarge;
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_size < 1) {
        return PrivateFileReadResult::kUnsafe;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return errno == ENOENT ? PrivateFileReadResult::kMissing : PrivateFileReadResult::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_size == before.st_size &&
                           opened.st_nlink == 1;
    if (!same_file) {
        (void)close(descriptor);
        return PrivateFileReadResult::kUnsafe;
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
        return PrivateFileReadResult::kUnreadable;
    }
    *output = std::move(content);
    return PrivateFileReadResult::kRead;
}

enum class PrivateAtomicWriteResult {
    kWritten,
    kUnsafeDirectory,
    kWriteFailed,
};

// 원자적 쓰기(activation.hpp 관습): 임시 파일(O_EXCL, 0600) → fsync → rename →
// 디렉터리 fsync. rename 은 같은 파일시스템 안에서 원자적이라, 절반만 쓰인
// 내용이 최종 경로에 나타나는 창이 없다.
PrivateAtomicWriteResult WritePrivateFileAtomic(const std::string& directory,
                                                const std::string& filename,
                                                const std::string& contents) {
    if (!EnsurePrivateStateDirectory(directory)) {
        return PrivateAtomicWriteResult::kUnsafeDirectory;
    }
    const std::string final_path = directory + "/" + filename;
    const auto now_ns = std::chrono::steady_clock::now().time_since_epoch().count();
    const std::string temp_path = directory + "/." + filename + ".tmp-" +
                                  std::to_string(static_cast<long long>(getpid())) + "-" +
                                  std::to_string(static_cast<long long>(now_ns));
    const int descriptor =
        open(temp_path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0) {
        return PrivateAtomicWriteResult::kWriteFailed;
    }
    std::size_t written = 0U;
    bool ok = true;
    while (written < contents.size()) {
        const ssize_t result = write(descriptor, contents.data() + written, contents.size() - written);
        if (result > 0) {
            written += static_cast<std::size_t>(result);
            continue;
        }
        if (result < 0 && errno == EINTR) {
            continue;
        }
        ok = false;
        break;
    }
    ok = ok && fsync(descriptor) == 0;
    const bool closed = close(descriptor) == 0;
    if (!ok || !closed) {
        (void)unlink(temp_path.c_str());
        return PrivateAtomicWriteResult::kWriteFailed;
    }
    if (rename(temp_path.c_str(), final_path.c_str()) != 0) {
        (void)unlink(temp_path.c_str());
        return PrivateAtomicWriteResult::kWriteFailed;
    }
    return FsyncDirectoryBestEffort(directory) ? PrivateAtomicWriteResult::kWritten
                                               : PrivateAtomicWriteResult::kWriteFailed;
}

// 매직 라인 + key=value 라인만 파싱한다. 필수/선택 필드 집합 검사는 호출부가
// 한다(파일마다 그 집합이 다르다 — arming 토큰은 정확히 8개, abort 요청은
// 필수 3개 + 선택 2개).
bool ParseStrictLines(const std::string& input, const std::string& magic,
                      std::map<std::string, std::string>* output) {
    if (output == nullptr || input.size() < magic.size() + 1U || input.back() != '\n') {
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
    if (start != input.size() || lines.empty() || lines[0] != magic) {
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
    *output = std::move(parsed);
    return true;
}

bool FieldsMatchExactly(const std::map<std::string, std::string>& fields,
                        const std::vector<std::string>& required) {
    if (fields.size() != required.size()) {
        return false;
    }
    for (const std::string& key : required) {
        if (fields.find(key) == fields.end()) {
            return false;
        }
    }
    return true;
}

bool FieldsWithinAllowedSet(const std::map<std::string, std::string>& fields,
                            const std::vector<std::string>& required,
                            const std::vector<std::string>& optional) {
    for (const std::string& key : required) {
        if (fields.find(key) == fields.end()) {
            return false;
        }
    }
    for (const auto& entry : fields) {
        const bool is_required =
            std::find(required.begin(), required.end(), entry.first) != required.end();
        const bool is_optional =
            std::find(optional.begin(), optional.end(), entry.first) != optional.end();
        if (!is_required && !is_optional) {
            return false;
        }
    }
    return true;
}

// ── §2 arming 토큰 wire 규약 ─────────────────────────────────────────────────

const std::string kFieldArmingTokenMagic = "KSI_EDGE_FIELD_ARMING_TOKEN_V1";
const std::vector<std::string> kFieldArmingTokenRequiredFields = {
    "nonce_b64",  "issuer_b64",         "stage",       "edge_device_id_b64",
    "mission_id_b64", "dispatch_id_b64", "issued_at_utc_ms", "expires_at_utc_ms",
};

// ── §8 abort 요청 wire 규약 ──────────────────────────────────────────────────

const std::string kAbortRequestMagic = "KSI_EDGE_FLIGHT_ABORT_REQUEST_V1";
const std::vector<std::string> kAbortRequestRequiredFields = {
    "requested_by_b64", "reason_b64", "requested_at_utc_ms",
};
const std::vector<std::string> kAbortRequestOptionalFields = {
    "mission_id_b64",
    "dispatch_id_b64",
};

// ── CRC32 (IEEE 802.3, zlib 과 동일 다항식) — bit-at-a-time, 파일이 수 KB라
// 테이블화하지 않아도 비용이 문제되지 않는다 ──────────────────────────────────

std::uint32_t Crc32(const std::uint8_t* data, std::size_t size) {
    std::uint32_t crc = 0xFFFFFFFFU;
    for (std::size_t index = 0U; index < size; ++index) {
        crc ^= data[index];
        for (int bit = 0; bit < 8; ++bit) {
            const std::uint32_t mask = (crc & 1U) != 0U ? 0xFFFFFFFFU : 0U;
            crc = (crc >> 1U) ^ (0xEDB88320U & mask);
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

// ── DEFLATE (RFC1951) — puff.c(공개 도메인 참조 구현) 와 같은 구조의 최소
// 디코더. wpml.py 가 만드는 작은 XML 하나를 풀 목적이라 표 기반 최적화 없이
// bit-at-a-time 으로 짠다 — 명료함이 속도보다 우선이다 ────────────────────────

constexpr int kMaxBits = 15;

class BitReader {
public:
    BitReader(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}

    // count<=24 만 이 디코더가 실제로 요청한다(HLIT/HDIST/HCLEN 5/5/4비트,
    // 길이/거리 extra 최대 13비트, 심볼 디코딩은 1비트씩).
    int GetBits(int count) {
        if (count < 0 || count > 24) {
            return -1;
        }
        while (bit_count_ < static_cast<unsigned>(count)) {
            if (byte_pos_ >= size_) {
                return -1;
            }
            bit_buffer_ |= static_cast<std::uint32_t>(data_[byte_pos_]) << bit_count_;
            ++byte_pos_;
            bit_count_ += 8U;
        }
        const std::uint32_t mask = count == 0 ? 0U : ((1U << count) - 1U);
        const int value = static_cast<int>(bit_buffer_ & mask);
        bit_buffer_ >>= count;
        bit_count_ -= static_cast<unsigned>(count);
        return value;
    }

    void AlignToByte() {
        bit_buffer_ = 0U;
        bit_count_ = 0U;
    }

    bool ReadStoredLength(unsigned* length) {
        if (length == nullptr || byte_pos_ + 4U > size_) {
            return false;
        }
        const unsigned len_value = static_cast<unsigned>(data_[byte_pos_]) |
                                   (static_cast<unsigned>(data_[byte_pos_ + 1U]) << 8U);
        const unsigned nlen_value = static_cast<unsigned>(data_[byte_pos_ + 2U]) |
                                    (static_cast<unsigned>(data_[byte_pos_ + 3U]) << 8U);
        byte_pos_ += 4U;
        if ((len_value ^ 0xFFFFU) != nlen_value) {
            return false;
        }
        *length = len_value;
        return true;
    }

    bool CopyStoredBytes(unsigned length, std::size_t max_output_bytes,
                        std::vector<std::uint8_t>* output) {
        if (output == nullptr || byte_pos_ + length > size_ ||
            output->size() + length > max_output_bytes) {
            return false;
        }
        output->insert(output->end(), data_ + byte_pos_, data_ + byte_pos_ + length);
        byte_pos_ += length;
        return true;
    }

private:
    const std::uint8_t* data_;
    std::size_t size_;
    std::size_t byte_pos_ = 0U;
    std::uint32_t bit_buffer_ = 0U;
    unsigned bit_count_ = 0U;
};

struct HuffmanTable {
    std::array<std::uint16_t, kMaxBits + 1> count{};
    std::vector<std::uint16_t> symbols;
};

// 표준 canonical Huffman 구성(puff.c construct()). 완전하지 않은(incomplete)
// 코드는 심볼이 정확히 1개인 특수한 경우(RFC1951 §3.2.7, distance 코드 없음
// 표현)만 허용한다 — 그 외의 미완성/과다구독 코드는 손상된 스트림이다.
bool BuildHuffman(const std::vector<std::uint8_t>& lengths, HuffmanTable* table) {
    if (table == nullptr) {
        return false;
    }
    table->count.fill(0U);
    for (const std::uint8_t length : lengths) {
        if (length > kMaxBits) {
            return false;
        }
        ++table->count[length];
    }
    const std::size_t total_used =
        lengths.size() - static_cast<std::size_t>(table->count[0]);
    table->count[0] = 0U;
    if (total_used == 0U) {
        table->symbols.clear();
        return true;  // 빈 테이블 — 호출부가 이 테이블을 실제로 디코드하면 실패한다.
    }
    int left = 1;
    for (int length = 1; length <= kMaxBits; ++length) {
        left <<= 1;
        left -= table->count[length];
        if (left < 0) {
            return false;  // 과다구독 — 항상 거부.
        }
    }
    if (left != 0 && total_used != 1U) {
        return false;  // 미완성 코드 — 심볼 1개짜리 특례만 허용.
    }
    std::array<std::uint16_t, kMaxBits + 2> offsets{};
    offsets[1] = 0U;
    for (int length = 1; length < kMaxBits; ++length) {
        offsets[static_cast<std::size_t>(length) + 1U] =
            static_cast<std::uint16_t>(offsets[static_cast<std::size_t>(length)] + table->count[static_cast<std::size_t>(length)]);
    }
    table->symbols.assign(total_used, 0U);
    for (std::size_t symbol = 0U; symbol < lengths.size(); ++symbol) {
        if (lengths[symbol] != 0U) {
            table->symbols[offsets[lengths[symbol]]++] = static_cast<std::uint16_t>(symbol);
        }
    }
    return true;
}

int DecodeHuffmanSymbol(BitReader* reader, const HuffmanTable& table) {
    if (reader == nullptr || table.symbols.empty()) {
        return -1;
    }
    int code = 0;
    int first = 0;
    int index = 0;
    for (int length = 1; length <= kMaxBits; ++length) {
        const int bit = reader->GetBits(1);
        if (bit < 0) {
            return -1;
        }
        code |= bit;
        const int count = table.count[static_cast<std::size_t>(length)];
        if (code - first < count) {
            return table.symbols[static_cast<std::size_t>(index + (code - first))];
        }
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
    }
    return -1;
}

void BuildFixedTables(HuffmanTable* litlen, HuffmanTable* dist) {
    std::vector<std::uint8_t> litlen_lengths(288U, 0U);
    for (std::size_t symbol = 0U; symbol < 144U; ++symbol) {
        litlen_lengths[symbol] = 8U;
    }
    for (std::size_t symbol = 144U; symbol < 256U; ++symbol) {
        litlen_lengths[symbol] = 9U;
    }
    for (std::size_t symbol = 256U; symbol < 280U; ++symbol) {
        litlen_lengths[symbol] = 7U;
    }
    for (std::size_t symbol = 280U; symbol < 288U; ++symbol) {
        litlen_lengths[symbol] = 8U;
    }
    (void)BuildHuffman(litlen_lengths, litlen);
    const std::vector<std::uint8_t> dist_lengths(30U, 5U);
    (void)BuildHuffman(dist_lengths, dist);
}

bool ReadDynamicTables(BitReader* reader, HuffmanTable* litlen, HuffmanTable* dist) {
    if (reader == nullptr) {
        return false;
    }
    const int hlit = reader->GetBits(5);
    const int hdist = reader->GetBits(5);
    const int hclen = reader->GetBits(4);
    if (hlit < 0 || hdist < 0 || hclen < 0) {
        return false;
    }
    const std::size_t litlen_count = static_cast<std::size_t>(hlit) + 257U;
    const std::size_t dist_count = static_cast<std::size_t>(hdist) + 1U;
    const std::size_t clc_count = static_cast<std::size_t>(hclen) + 4U;
    constexpr std::array<int, 19> kOrder = {16, 17, 18, 0, 8, 7, 9, 6, 10,
                                            5,  11, 4,  12, 3, 13, 2, 14, 1, 15};
    std::vector<std::uint8_t> clc_lengths(19U, 0U);
    for (std::size_t index = 0U; index < clc_count; ++index) {
        const int value = reader->GetBits(3);
        if (value < 0) {
            return false;
        }
        clc_lengths[static_cast<std::size_t>(kOrder[index])] = static_cast<std::uint8_t>(value);
    }
    HuffmanTable clc_table;
    if (!BuildHuffman(clc_lengths, &clc_table) || clc_table.symbols.empty()) {
        return false;
    }
    std::vector<std::uint8_t> all_lengths(litlen_count + dist_count, 0U);
    std::size_t index = 0U;
    while (index < all_lengths.size()) {
        const int symbol = DecodeHuffmanSymbol(reader, clc_table);
        if (symbol < 0) {
            return false;
        }
        if (symbol < 16) {
            all_lengths[index++] = static_cast<std::uint8_t>(symbol);
            continue;
        }
        unsigned repeat_count = 0U;
        std::uint8_t repeat_value = 0U;
        if (symbol == 16) {
            if (index == 0U) {
                return false;
            }
            const int extra = reader->GetBits(2);
            if (extra < 0) {
                return false;
            }
            repeat_count = static_cast<unsigned>(extra) + 3U;
            repeat_value = all_lengths[index - 1U];
        } else if (symbol == 17) {
            const int extra = reader->GetBits(3);
            if (extra < 0) {
                return false;
            }
            repeat_count = static_cast<unsigned>(extra) + 3U;
            repeat_value = 0U;
        } else if (symbol == 18) {
            const int extra = reader->GetBits(7);
            if (extra < 0) {
                return false;
            }
            repeat_count = static_cast<unsigned>(extra) + 11U;
            repeat_value = 0U;
        } else {
            return false;
        }
        if (index + repeat_count > all_lengths.size()) {
            return false;
        }
        for (unsigned copy = 0U; copy < repeat_count; ++copy) {
            all_lengths[index++] = repeat_value;
        }
    }
    const std::vector<std::uint8_t> litlen_lengths(all_lengths.begin(),
                                                    all_lengths.begin() + static_cast<long>(litlen_count));
    const std::vector<std::uint8_t> dist_lengths(all_lengths.begin() + static_cast<long>(litlen_count),
                                                 all_lengths.end());
    return BuildHuffman(litlen_lengths, litlen) && BuildHuffman(dist_lengths, dist);
}

constexpr std::array<unsigned, 29> kLengthBase = {3,  4,  5,  6,  7,  8,  9,  10, 11, 13,
                                                  15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
                                                  67, 83, 99, 115, 131, 163, 195, 227, 258};
constexpr std::array<int, 29> kLengthExtra = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                                              2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
constexpr std::array<unsigned, 30> kDistBase = {
    1,    2,    3,    4,    5,    7,    9,    13,   17,   25,    33,    49,   65,
    97,   129,  193,  257,  385,  513,  769,  1025, 1537, 2049,  3073,  4097, 6145,
    8193, 12289, 16385, 24577};
constexpr std::array<int, 30> kDistExtra = {0, 0, 0, 0, 1, 1, 2,  2,  3,  3,  4,  4,  5,  5, 6,
                                            6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

bool InflateRaw(const std::uint8_t* data, std::size_t size, std::size_t max_output_bytes,
                std::vector<std::uint8_t>* output) {
    if (output == nullptr) {
        return false;
    }
    BitReader reader(data, size);
    bool final_block = false;
    while (!final_block) {
        const int bfinal = reader.GetBits(1);
        if (bfinal < 0) {
            return false;
        }
        final_block = bfinal != 0;
        const int btype = reader.GetBits(2);
        if (btype < 0) {
            return false;
        }
        if (btype == 0) {
            reader.AlignToByte();
            unsigned length = 0U;
            if (!reader.ReadStoredLength(&length) ||
                !reader.CopyStoredBytes(length, max_output_bytes, output)) {
                return false;
            }
            continue;
        }
        if (btype != 1 && btype != 2) {
            return false;  // btype==3 은 예약(오류)
        }
        HuffmanTable litlen_table;
        HuffmanTable dist_table;
        if (btype == 1) {
            BuildFixedTables(&litlen_table, &dist_table);
        } else if (!ReadDynamicTables(&reader, &litlen_table, &dist_table)) {
            return false;
        }
        for (;;) {
            const int symbol = DecodeHuffmanSymbol(&reader, litlen_table);
            if (symbol < 0) {
                return false;
            }
            if (symbol < 256) {
                if (output->size() + 1U > max_output_bytes) {
                    return false;
                }
                output->push_back(static_cast<std::uint8_t>(symbol));
                continue;
            }
            if (symbol == 256) {
                break;
            }
            const int length_index = symbol - 257;
            if (length_index < 0 || length_index >= static_cast<int>(kLengthBase.size())) {
                return false;
            }
            const int extra_len_bits = kLengthExtra[static_cast<std::size_t>(length_index)];
            const int extra_len = extra_len_bits > 0 ? reader.GetBits(extra_len_bits) : 0;
            if (extra_len < 0) {
                return false;
            }
            const unsigned match_length =
                kLengthBase[static_cast<std::size_t>(length_index)] + static_cast<unsigned>(extra_len);
            const int dist_symbol = DecodeHuffmanSymbol(&reader, dist_table);
            if (dist_symbol < 0 || dist_symbol >= static_cast<int>(kDistBase.size())) {
                return false;
            }
            const int extra_dist_bits = kDistExtra[static_cast<std::size_t>(dist_symbol)];
            const int extra_dist = extra_dist_bits > 0 ? reader.GetBits(extra_dist_bits) : 0;
            if (extra_dist < 0) {
                return false;
            }
            const unsigned distance =
                kDistBase[static_cast<std::size_t>(dist_symbol)] + static_cast<unsigned>(extra_dist);
            if (distance == 0U || distance > output->size() ||
                output->size() + match_length > max_output_bytes) {
                return false;
            }
            const std::size_t copy_from = output->size() - distance;
            for (unsigned copy = 0U; copy < match_length; ++copy) {
                const std::uint8_t byte_value = (*output)[copy_from + copy];
                output->push_back(byte_value);
            }
        }
    }
    return true;
}

// ── ZIP 로컬 파일 헤더 순회 — 중앙 디렉터리는 보지 않는다(로컬 헤더만으로
// wpml.py 산출물을 정확히 재구성할 수 있고, 그 이상은 이 방어종심 판독의
// 범위 밖이다) ────────────────────────────────────────────────────────────

constexpr std::uint32_t kZipLocalFileSignature = 0x04034B50U;
constexpr std::size_t kZipLocalHeaderSize = 30U;
constexpr std::size_t kMaximumZipEntriesScanned = 64U;
constexpr std::size_t kMaximumWaylinesUncompressedBytes = 4U * 1024U * 1024U;
const std::string kWaylinesEntryName = "wpmz/waylines.wpml";

struct ZipLocalFileHeader {
    std::uint16_t flags = 0U;
    std::uint16_t method = 0U;
    std::uint32_t crc32 = 0U;
    std::uint32_t compressed_size = 0U;
    std::uint32_t uncompressed_size = 0U;
    std::size_t data_offset = 0U;
};

std::uint32_t ReadLittleEndianU32(const std::string& bytes, std::size_t offset) {
    return static_cast<std::uint32_t>(static_cast<std::uint8_t>(bytes[offset])) |
          (static_cast<std::uint32_t>(static_cast<std::uint8_t>(bytes[offset + 1U])) << 8U) |
          (static_cast<std::uint32_t>(static_cast<std::uint8_t>(bytes[offset + 2U])) << 16U) |
          (static_cast<std::uint32_t>(static_cast<std::uint8_t>(bytes[offset + 3U])) << 24U);
}

std::uint16_t ReadLittleEndianU16(const std::string& bytes, std::size_t offset) {
    return static_cast<std::uint16_t>(static_cast<std::uint8_t>(bytes[offset]) |
                                      (static_cast<std::uint8_t>(bytes[offset + 1U]) << 8U));
}

bool ReadZipLocalFileHeader(const std::string& bytes, std::size_t offset, ZipLocalFileHeader* header,
                           std::string* filename) {
    if (header == nullptr || filename == nullptr || offset + kZipLocalHeaderSize > bytes.size()) {
        return false;
    }
    header->flags = ReadLittleEndianU16(bytes, offset + 6U);
    header->method = ReadLittleEndianU16(bytes, offset + 8U);
    header->crc32 = ReadLittleEndianU32(bytes, offset + 14U);
    header->compressed_size = ReadLittleEndianU32(bytes, offset + 18U);
    header->uncompressed_size = ReadLittleEndianU32(bytes, offset + 22U);
    const std::uint16_t filename_len = ReadLittleEndianU16(bytes, offset + 26U);
    const std::uint16_t extra_len = ReadLittleEndianU16(bytes, offset + 28U);
    const std::size_t name_offset = offset + kZipLocalHeaderSize;
    if (name_offset + filename_len > bytes.size()) {
        return false;
    }
    *filename = bytes.substr(name_offset, filename_len);
    const std::size_t extra_offset = name_offset + filename_len;
    if (extra_offset + extra_len > bytes.size()) {
        return false;
    }
    header->data_offset = extra_offset + extra_len;
    if (header->data_offset + header->compressed_size > bytes.size()) {
        return false;
    }
    return true;
}

bool ParseFiniteDouble(const std::string& text, double* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }
    for (const char character : text) {
        if (character == ' ' || character == '\t' || character == '\n' || character == '\r') {
            return false;
        }
    }
    errno = 0;
    char* end = nullptr;
    const double parsed = std::strtod(text.c_str(), &end);
    if (end != text.c_str() + text.size() || errno == ERANGE) {
        return false;
    }
    *value = parsed;
    return true;
}

// wpml.py 가 실제로 내는 <wpml:executeHeight>N</wpml:executeHeight> 리터럴
// 태그만 겨냥한 경계 스캐너다(일반 XML 파서가 아니다 — flight_execution.hpp
// 상단 주석 참조).
KmzEnvelopeRederivationResult ExtractAltitudeRangeFromWaylines(const std::string& xml) {
    KmzEnvelopeRederivationResult result;
    constexpr char kOpenTag[] = "<wpml:executeHeight>";
    constexpr char kCloseTag[] = "</wpml:executeHeight>";
    constexpr std::size_t kOpenTagLength = sizeof(kOpenTag) - 1U;
    constexpr std::size_t kCloseTagLength = sizeof(kCloseTag) - 1U;
    std::size_t search_from = 0U;
    double observed_min = 0.0;
    double observed_max = 0.0;
    std::size_t count = 0U;
    while (true) {
        const std::size_t open_pos = xml.find(kOpenTag, search_from);
        if (open_pos == std::string::npos) {
            break;
        }
        const std::size_t value_start = open_pos + kOpenTagLength;
        const std::size_t close_pos = xml.find(kCloseTag, value_start);
        if (close_pos == std::string::npos) {
            result.verdict = KmzEnvelopeRederivationVerdict::kXmlMalformed;
            return result;
        }
        const std::string value_text = xml.substr(value_start, close_pos - value_start);
        double value = 0.0;
        if (!ParseFiniteDouble(value_text, &value)) {
            result.verdict = KmzEnvelopeRederivationVerdict::kXmlMalformed;
            return result;
        }
        if (!std::isfinite(value)) {
            result.verdict = KmzEnvelopeRederivationVerdict::kNonFiniteAltitude;
            return result;
        }
        if (count == 0U) {
            observed_min = value;
            observed_max = value;
        } else {
            observed_min = std::min(observed_min, value);
            observed_max = std::max(observed_max, value);
        }
        ++count;
        search_from = close_pos + kCloseTagLength;
    }
    if (count == 0U) {
        result.verdict = KmzEnvelopeRederivationVerdict::kNoWaypoints;
        return result;
    }
    result.verdict = KmzEnvelopeRederivationVerdict::kDerived;
    result.observed_min_altitude_m = observed_min;
    result.observed_max_altitude_m = observed_max;
    result.waypoint_count = count;
    return result;
}

// ── [2]~[9] 오케스트레이션 보조 함수 ─────────────────────────────────────────

FlightExecutionVerdict MapArmingVerdict(ArmingTokenVerdict verdict) {
    switch (verdict) {
        case ArmingTokenVerdict::kConsumed:
            return FlightExecutionVerdict::kEligibleForStart;  // 호출부에서 나오지 않는다
        case ArmingTokenVerdict::kUnsafeStateDirectory:
            return FlightExecutionVerdict::kArmingTokenUnsafeStateDirectory;
        case ArmingTokenVerdict::kMissing:
            return FlightExecutionVerdict::kArmingTokenMissing;
        case ArmingTokenVerdict::kUnsafeFile:
            return FlightExecutionVerdict::kArmingTokenUnsafeFile;
        case ArmingTokenVerdict::kUnreadable:
            return FlightExecutionVerdict::kArmingTokenUnreadable;
        case ArmingTokenVerdict::kTooLarge:
            return FlightExecutionVerdict::kArmingTokenTooLarge;
        case ArmingTokenVerdict::kMalformed:
            return FlightExecutionVerdict::kArmingTokenMalformed;
        case ArmingTokenVerdict::kTtlTooLong:
            return FlightExecutionVerdict::kArmingTokenTtlTooLong;
        case ArmingTokenVerdict::kNotYetValid:
            return FlightExecutionVerdict::kArmingTokenNotYetValid;
        case ArmingTokenVerdict::kExpired:
            return FlightExecutionVerdict::kArmingTokenExpired;
        case ArmingTokenVerdict::kStageMismatch:
            return FlightExecutionVerdict::kArmingTokenStageMismatch;
        case ArmingTokenVerdict::kDeviceMismatch:
            return FlightExecutionVerdict::kArmingTokenDeviceMismatch;
        case ArmingTokenVerdict::kMissionMismatch:
            return FlightExecutionVerdict::kArmingTokenMissionMismatch;
        case ArmingTokenVerdict::kDispatchMismatch:
            return FlightExecutionVerdict::kArmingTokenDispatchMismatch;
        case ArmingTokenVerdict::kConsumeFailed:
            return FlightExecutionVerdict::kArmingTokenConsumeFailed;
    }
    return FlightExecutionVerdict::kArmingTokenMalformed;
}

FlightExecutionVerdict EvaluateCoreAuthorization(const FlightExecutionRequest& request,
                                                 const NativeActivationSnapshot& activation,
                                                 std::int64_t now_utc_ms) {
    const CoreFlightAuthorization& auth = request.core_authorization;
    if (!auth.verified) {
        return FlightExecutionVerdict::kCoreAuthorizationNotVerified;
    }
    if (auth.equipment_class.empty() || auth.aircraft_serial_number.empty() ||
        auth.edge_device_id.empty() || auth.mission_id.empty() || auth.dispatch_id.empty() ||
        !IsSha256Digest(auth.mission_contract_digest) || auth.issued_at_utc_ms < 0 ||
        auth.expires_at_utc_ms <= auth.issued_at_utc_ms) {
        return FlightExecutionVerdict::kCoreAuthorizationMalformed;
    }
    if (auth.authorized_stage != request.requested_stage) {
        return FlightExecutionVerdict::kCoreAuthorizationStageMismatch;
    }
    if (auth.edge_device_id != activation.edge_device_id) {
        return FlightExecutionVerdict::kCoreAuthorizationDeviceMismatch;
    }
    if (auth.mission_id != activation.mission_id) {
        return FlightExecutionVerdict::kCoreAuthorizationMissionMismatch;
    }
    if (auth.dispatch_id != activation.dispatch_id) {
        return FlightExecutionVerdict::kCoreAuthorizationDispatchMismatch;
    }
    if (auth.mission_contract_digest != activation.context.mission_contract_digest) {
        return FlightExecutionVerdict::kCoreAuthorizationContractMismatch;
    }
    if (request.maximum_core_authorization_ttl_ms <= 0 ||
        auth.expires_at_utc_ms - auth.issued_at_utc_ms > request.maximum_core_authorization_ttl_ms) {
        return FlightExecutionVerdict::kCoreAuthorizationTtlTooLong;
    }
    if (now_utc_ms < auth.issued_at_utc_ms) {
        return FlightExecutionVerdict::kCoreAuthorizationNotYetValid;
    }
    if (now_utc_ms > auth.expires_at_utc_ms) {
        return FlightExecutionVerdict::kCoreAuthorizationExpired;
    }
    return FlightExecutionVerdict::kEligibleForStart;
}

FlightExecutionVerdict EvaluateDeclaredEnvelope(const DeclaredFlightEnvelope& envelope,
                                                const std::string& kmz_bytes,
                                                KmzEnvelopeRederivationResult* rederivation) {
    if (rederivation == nullptr) {
        return FlightExecutionVerdict::kEnvelopeMalformed;
    }
    if (!std::isfinite(envelope.min_altitude_m) || !std::isfinite(envelope.max_altitude_m) ||
        envelope.min_altitude_m > envelope.max_altitude_m) {
        return FlightExecutionVerdict::kEnvelopeMalformed;
    }
    if (!envelope.excluded_volume_ids.empty()) {
        return FlightExecutionVerdict::kEnvelopeExcludedVolumesPresent;
    }
    if (envelope.allowed_volume_ids.empty()) {
        return FlightExecutionVerdict::kEnvelopeAllowedVolumesEmpty;
    }
    *rederivation = RederiveKmzAltitudeEnvelope(kmz_bytes);
    if (rederivation->verdict != KmzEnvelopeRederivationVerdict::kDerived) {
        return FlightExecutionVerdict::kEnvelopeRederivationFailed;
    }
    if (rederivation->observed_min_altitude_m < envelope.min_altitude_m ||
        rederivation->observed_max_altitude_m > envelope.max_altitude_m) {
        return FlightExecutionVerdict::kEnvelopeAltitudeOutOfBounds;
    }
    return FlightExecutionVerdict::kEligibleForStart;
}

FlightExecutionVerdict EvaluateAircraftPreconditions(const FlightExecutionRequest& request,
                                                      std::int64_t now_utc_ms) {
    const AircraftPreconditionSnapshot& aircraft = request.aircraft;
    const AircraftPreconditionPolicy& policy = request.aircraft_policy;
    if (policy.maximum_telemetry_age_ms <= 0) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    const auto stale = [&](std::int64_t observed_at_utc_ms) {
        return observed_at_utc_ms > now_utc_ms ||
              now_utc_ms - observed_at_utc_ms > policy.maximum_telemetry_age_ms;
    };

    if (!aircraft.flight_status_present) {
        return FlightExecutionVerdict::kAircraftFlightStatusMissing;
    }
    if (stale(aircraft.flight_status_observed_utc_ms)) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    constexpr std::uint8_t kFlightStatusStopped = 0U;  // E_DjiFcSubscriptionFlightStatus::STOPED
    if (aircraft.flight_status != kFlightStatusStopped) {
        return FlightExecutionVerdict::kAircraftFlightStatusNotStopped;
    }

    if (aircraft.observed_aircraft_serial_number.empty() ||
        aircraft.observed_aircraft_serial_number != request.core_authorization.aircraft_serial_number) {
        return FlightExecutionVerdict::kAircraftSerialMismatch;
    }

    if (!aircraft.battery_present) {
        return FlightExecutionVerdict::kAircraftBatteryMissing;
    }
    if (stale(aircraft.battery_observed_utc_ms)) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    if (aircraft.battery_percent_1pct < policy.minimum_battery_percent_1pct) {
        return FlightExecutionVerdict::kAircraftBatteryInsufficient;
    }

    if (!aircraft.home_point_present) {
        return FlightExecutionVerdict::kAircraftHomePointMissing;
    }
    if (stale(aircraft.home_point_observed_utc_ms)) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    constexpr std::uint8_t kHomePointSetSuccess = 1U;  // E_DjiFcSubscriptionHomePointSetStatus::SUCCESS
    if (aircraft.home_point_set_status != kHomePointSetSuccess) {
        return FlightExecutionVerdict::kAircraftHomePointNotSet;
    }

    if (!aircraft.position_solution_present) {
        return FlightExecutionVerdict::kAircraftPositionQualityMissing;
    }
    if (stale(aircraft.position_solution_observed_utc_ms)) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    if (aircraft.position_solution_property < policy.minimum_position_solution_property) {
        return FlightExecutionVerdict::kAircraftPositionQualityInsufficient;
    }

    if (!aircraft.flight_anomaly_present) {
        return FlightExecutionVerdict::kAircraftFlightAnomalyMissing;
    }
    if (stale(aircraft.flight_anomaly_observed_utc_ms)) {
        return FlightExecutionVerdict::kAircraftTelemetryStale;
    }
    if (aircraft.flight_anomaly_bits != 0U) {
        return FlightExecutionVerdict::kAircraftFlightAnomalyPresent;
    }

    return FlightExecutionVerdict::kEligibleForStart;
}

std::string DeriveAttemptId(const std::string& dispatch_id, const std::string& nonce,
                            std::int64_t now_utc_ms, FlightExecutionVerdict fallback_verdict) {
    const std::string seed = nonce.empty()
                                 ? ("no-nonce|" + dispatch_id + "|" + std::to_string(now_utc_ms) +
                                    "|" + ToString(fallback_verdict))
                                 : ("nonce|" + nonce);
    const std::string digest_hex =
        Sha256Hex(reinterpret_cast<const std::uint8_t*>(seed.data()), seed.size());
    return digest_hex.empty() ? std::string{} : "flight-start-" + digest_hex.substr(0U, 32U);
}

std::string PreconditionVerdictsJson(FlightExecutionVerdict verdict,
                                     ArmingTokenVerdict arming_verdict,
                                     const KmzEnvelopeRederivationResult& envelope,
                                     const CeilingGuardResult& ceiling) {
    // 진단 전용 JSON — Core 계약이 아니다(아무도 이 문법을 파싱하지 않는다).
    // 값이 전부 이 파일의 ToString() 상수라 이스케이프가 필요 없다.
    return std::string("{\"verdict\":\"") + ToString(verdict) + "\",\"armingTokenVerdict\":\"" +
          ToString(arming_verdict) + "\",\"kmzEnvelopeVerdict\":\"" + ToString(envelope.verdict) +
          "\",\"ceilingGuardVerdict\":\"" + ToString(ceiling.verdict) + "\"}";
}

}  // namespace

// ── ToString ─────────────────────────────────────────────────────────────

const char* ToString(FlightExecutionStage stage) {
    switch (stage) {
        case FlightExecutionStage::kS0:
            return "S0";
        case FlightExecutionStage::kS1:
            return "S1";
        case FlightExecutionStage::kS2:
            return "S2";
        case FlightExecutionStage::kS3:
            return "S3";
        case FlightExecutionStage::kS4:
            return "S4";
    }
    return "UNKNOWN";
}

const char* ToString(FlightExecutionVerdict verdict) {
    switch (verdict) {
        case FlightExecutionVerdict::kEligibleForStart:
            return "ELIGIBLE_FOR_START";
        case FlightExecutionVerdict::kInvalidClock:
            return "INVALID_CLOCK";
        case FlightExecutionVerdict::kStageBelowRequired:
            return "STAGE_BELOW_REQUIRED";
        case FlightExecutionVerdict::kActivationInvalid:
            return "ACTIVATION_INVALID";
        case FlightExecutionVerdict::kCoreAuthorizationNotVerified:
            return "CORE_AUTHORIZATION_NOT_VERIFIED";
        case FlightExecutionVerdict::kCoreAuthorizationMalformed:
            return "CORE_AUTHORIZATION_MALFORMED";
        case FlightExecutionVerdict::kCoreAuthorizationStageMismatch:
            return "CORE_AUTHORIZATION_STAGE_MISMATCH";
        case FlightExecutionVerdict::kCoreAuthorizationDeviceMismatch:
            return "CORE_AUTHORIZATION_DEVICE_MISMATCH";
        case FlightExecutionVerdict::kCoreAuthorizationMissionMismatch:
            return "CORE_AUTHORIZATION_MISSION_MISMATCH";
        case FlightExecutionVerdict::kCoreAuthorizationDispatchMismatch:
            return "CORE_AUTHORIZATION_DISPATCH_MISMATCH";
        case FlightExecutionVerdict::kCoreAuthorizationContractMismatch:
            return "CORE_AUTHORIZATION_CONTRACT_MISMATCH";
        case FlightExecutionVerdict::kCoreAuthorizationTtlTooLong:
            return "CORE_AUTHORIZATION_TTL_TOO_LONG";
        case FlightExecutionVerdict::kCoreAuthorizationNotYetValid:
            return "CORE_AUTHORIZATION_NOT_YET_VALID";
        case FlightExecutionVerdict::kCoreAuthorizationExpired:
            return "CORE_AUTHORIZATION_EXPIRED";
        case FlightExecutionVerdict::kArmingTokenUnsafeStateDirectory:
            return "ARMING_TOKEN_UNSAFE_STATE_DIRECTORY";
        case FlightExecutionVerdict::kArmingTokenMissing:
            return "ARMING_TOKEN_MISSING";
        case FlightExecutionVerdict::kArmingTokenUnsafeFile:
            return "ARMING_TOKEN_UNSAFE_FILE";
        case FlightExecutionVerdict::kArmingTokenUnreadable:
            return "ARMING_TOKEN_UNREADABLE";
        case FlightExecutionVerdict::kArmingTokenTooLarge:
            return "ARMING_TOKEN_TOO_LARGE";
        case FlightExecutionVerdict::kArmingTokenMalformed:
            return "ARMING_TOKEN_MALFORMED";
        case FlightExecutionVerdict::kArmingTokenTtlTooLong:
            return "ARMING_TOKEN_TTL_TOO_LONG";
        case FlightExecutionVerdict::kArmingTokenNotYetValid:
            return "ARMING_TOKEN_NOT_YET_VALID";
        case FlightExecutionVerdict::kArmingTokenExpired:
            return "ARMING_TOKEN_EXPIRED";
        case FlightExecutionVerdict::kArmingTokenStageMismatch:
            return "ARMING_TOKEN_STAGE_MISMATCH";
        case FlightExecutionVerdict::kArmingTokenDeviceMismatch:
            return "ARMING_TOKEN_DEVICE_MISMATCH";
        case FlightExecutionVerdict::kArmingTokenMissionMismatch:
            return "ARMING_TOKEN_MISSION_MISMATCH";
        case FlightExecutionVerdict::kArmingTokenDispatchMismatch:
            return "ARMING_TOKEN_DISPATCH_MISMATCH";
        case FlightExecutionVerdict::kArmingTokenConsumeFailed:
            return "ARMING_TOKEN_CONSUME_FAILED";
        case FlightExecutionVerdict::kKmzUnavailable:
            return "KMZ_UNAVAILABLE";
        case FlightExecutionVerdict::kEnvelopeMalformed:
            return "ENVELOPE_MALFORMED";
        case FlightExecutionVerdict::kEnvelopeRederivationFailed:
            return "ENVELOPE_REDERIVATION_FAILED";
        case FlightExecutionVerdict::kEnvelopeAltitudeOutOfBounds:
            return "ENVELOPE_ALTITUDE_OUT_OF_BOUNDS";
        case FlightExecutionVerdict::kEnvelopeExcludedVolumesPresent:
            return "ENVELOPE_EXCLUDED_VOLUMES_PRESENT";
        case FlightExecutionVerdict::kEnvelopeAllowedVolumesEmpty:
            return "ENVELOPE_ALLOWED_VOLUMES_EMPTY";
        case FlightExecutionVerdict::kCeilingGuardRejected:
            return "CEILING_GUARD_REJECTED";
        case FlightExecutionVerdict::kSupervisorMissing:
            return "SUPERVISOR_MISSING";
        case FlightExecutionVerdict::kSupervisorClockRollback:
            return "SUPERVISOR_CLOCK_ROLLBACK";
        case FlightExecutionVerdict::kSupervisorNotActivated:
            return "SUPERVISOR_NOT_ACTIVATED";
        case FlightExecutionVerdict::kSupervisorNotNominal:
            return "SUPERVISOR_NOT_NOMINAL";
        case FlightExecutionVerdict::kAircraftFlightStatusMissing:
            return "AIRCRAFT_FLIGHT_STATUS_MISSING";
        case FlightExecutionVerdict::kAircraftFlightStatusNotStopped:
            return "AIRCRAFT_FLIGHT_STATUS_NOT_STOPPED";
        case FlightExecutionVerdict::kAircraftSerialMismatch:
            return "AIRCRAFT_SERIAL_MISMATCH";
        case FlightExecutionVerdict::kAircraftBatteryMissing:
            return "AIRCRAFT_BATTERY_MISSING";
        case FlightExecutionVerdict::kAircraftBatteryInsufficient:
            return "AIRCRAFT_BATTERY_INSUFFICIENT";
        case FlightExecutionVerdict::kAircraftHomePointMissing:
            return "AIRCRAFT_HOME_POINT_MISSING";
        case FlightExecutionVerdict::kAircraftHomePointNotSet:
            return "AIRCRAFT_HOME_POINT_NOT_SET";
        case FlightExecutionVerdict::kAircraftPositionQualityMissing:
            return "AIRCRAFT_POSITION_QUALITY_MISSING";
        case FlightExecutionVerdict::kAircraftPositionQualityInsufficient:
            return "AIRCRAFT_POSITION_QUALITY_INSUFFICIENT";
        case FlightExecutionVerdict::kAircraftFlightAnomalyMissing:
            return "AIRCRAFT_FLIGHT_ANOMALY_MISSING";
        case FlightExecutionVerdict::kAircraftFlightAnomalyPresent:
            return "AIRCRAFT_FLIGHT_ANOMALY_PRESENT";
        case FlightExecutionVerdict::kAircraftTelemetryStale:
            return "AIRCRAFT_TELEMETRY_STALE";
        case FlightExecutionVerdict::kJournalUnavailable:
            return "JOURNAL_UNAVAILABLE";
        case FlightExecutionVerdict::kJournalRejected:
            return "JOURNAL_REJECTED";
    }
    return "UNKNOWN";
}

const char* ToString(ArmingTokenWriteVerdict verdict) {
    switch (verdict) {
        case ArmingTokenWriteVerdict::kWritten:
            return "WRITTEN";
        case ArmingTokenWriteVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case ArmingTokenWriteVerdict::kInvalidRequest:
            return "INVALID_REQUEST";
        case ArmingTokenWriteVerdict::kWriteFailed:
            return "WRITE_FAILED";
    }
    return "UNKNOWN";
}

const char* ToString(ArmingTokenVerdict verdict) {
    switch (verdict) {
        case ArmingTokenVerdict::kConsumed:
            return "CONSUMED";
        case ArmingTokenVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case ArmingTokenVerdict::kMissing:
            return "MISSING";
        case ArmingTokenVerdict::kUnsafeFile:
            return "UNSAFE_FILE";
        case ArmingTokenVerdict::kUnreadable:
            return "UNREADABLE";
        case ArmingTokenVerdict::kTooLarge:
            return "TOO_LARGE";
        case ArmingTokenVerdict::kMalformed:
            return "MALFORMED";
        case ArmingTokenVerdict::kTtlTooLong:
            return "TTL_TOO_LONG";
        case ArmingTokenVerdict::kNotYetValid:
            return "NOT_YET_VALID";
        case ArmingTokenVerdict::kExpired:
            return "EXPIRED";
        case ArmingTokenVerdict::kStageMismatch:
            return "STAGE_MISMATCH";
        case ArmingTokenVerdict::kDeviceMismatch:
            return "DEVICE_MISMATCH";
        case ArmingTokenVerdict::kMissionMismatch:
            return "MISSION_MISMATCH";
        case ArmingTokenVerdict::kDispatchMismatch:
            return "DISPATCH_MISMATCH";
        case ArmingTokenVerdict::kConsumeFailed:
            return "CONSUME_FAILED";
    }
    return "UNKNOWN";
}

const char* ToString(AbortRequestWriteVerdict verdict) {
    switch (verdict) {
        case AbortRequestWriteVerdict::kWritten:
            return "WRITTEN";
        case AbortRequestWriteVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case AbortRequestWriteVerdict::kInvalidRequest:
            return "INVALID_REQUEST";
        case AbortRequestWriteVerdict::kWriteFailed:
            return "WRITE_FAILED";
    }
    return "UNKNOWN";
}

const char* ToString(AbortRequestReadVerdict verdict) {
    switch (verdict) {
        case AbortRequestReadVerdict::kPresent:
            return "PRESENT";
        case AbortRequestReadVerdict::kAbsent:
            return "ABSENT";
        case AbortRequestReadVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case AbortRequestReadVerdict::kUnsafeFile:
            return "UNSAFE_FILE";
        case AbortRequestReadVerdict::kUnreadable:
            return "UNREADABLE";
        case AbortRequestReadVerdict::kTooLarge:
            return "TOO_LARGE";
        case AbortRequestReadVerdict::kMalformed:
            return "MALFORMED";
    }
    return "UNKNOWN";
}

const char* ToString(KmzEnvelopeRederivationVerdict verdict) {
    switch (verdict) {
        case KmzEnvelopeRederivationVerdict::kDerived:
            return "DERIVED";
        case KmzEnvelopeRederivationVerdict::kZipMalformed:
            return "ZIP_MALFORMED";
        case KmzEnvelopeRederivationVerdict::kWaylinesEntryMissing:
            return "WAYLINES_ENTRY_MISSING";
        case KmzEnvelopeRederivationVerdict::kWaylinesTooLarge:
            return "WAYLINES_TOO_LARGE";
        case KmzEnvelopeRederivationVerdict::kInflateFailed:
            return "INFLATE_FAILED";
        case KmzEnvelopeRederivationVerdict::kCrcMismatch:
            return "CRC_MISMATCH";
        case KmzEnvelopeRederivationVerdict::kXmlMalformed:
            return "XML_MALFORMED";
        case KmzEnvelopeRederivationVerdict::kNoWaypoints:
            return "NO_WAYPOINTS";
        case KmzEnvelopeRederivationVerdict::kNonFiniteAltitude:
            return "NON_FINITE_ALTITUDE";
    }
    return "UNKNOWN";
}

const char* ToString(SiteDensityDeclaration declaration) {
    switch (declaration) {
        case SiteDensityDeclaration::kUnspecified:
            return "UNSPECIFIED";
        case SiteDensityDeclaration::kGeneralArea:
            return "GENERAL_AREA";
        case SiteDensityDeclaration::kCongestedArea:
            return "CONGESTED_AREA";
    }
    return "UNKNOWN";
}

const char* ToString(CeilingGuardVerdict verdict) {
    switch (verdict) {
        case CeilingGuardVerdict::kPassed:
            return "PASSED";
        case CeilingGuardVerdict::kNonFiniteInput:
            return "NON_FINITE_INPUT";
        case CeilingGuardVerdict::kNoDtmCoverage:
            return "NO_DTM_COVERAGE";
        case CeilingGuardVerdict::kTerrainSamplesEmpty:
            return "TERRAIN_SAMPLES_EMPTY";
        case CeilingGuardVerdict::kTerrainNotFlat:
            return "TERRAIN_NOT_FLAT";
        case CeilingGuardVerdict::kTakeoffOutsideTerrainRange:
            return "TAKEOFF_OUTSIDE_TERRAIN_RANGE";
        case CeilingGuardVerdict::kCeilingTooHigh:
            return "CEILING_TOO_HIGH";
        case CeilingGuardVerdict::kDensityUnspecified:
            return "DENSITY_UNSPECIFIED";
        case CeilingGuardVerdict::kDensityCongested:
            return "DENSITY_CONGESTED";
    }
    return "UNKNOWN";
}

// ── §2 arming 토큰 ───────────────────────────────────────────────────────

ArmingTokenWriteVerdict WriteFieldArmingToken(const std::string& state_directory,
                                              const FieldArmingToken& token) {
    if (state_directory.empty() || !IsSafeText(token.nonce) || !IsSafeText(token.issuer) ||
        !IsSafeText(token.edge_device_id) || !IsSafeText(token.mission_id) ||
        !IsSafeText(token.dispatch_id) || token.issued_at_utc_ms < 0 ||
        token.expires_at_utc_ms <= token.issued_at_utc_ms ||
        token.expires_at_utc_ms - token.issued_at_utc_ms > kMaximumArmingTokenTtlMs) {
        return ArmingTokenWriteVerdict::kInvalidRequest;
    }
    const std::string contents =
        kFieldArmingTokenMagic + "\n" + "nonce_b64=" + EncodeBase64Url(token.nonce) + "\n" +
        "issuer_b64=" + EncodeBase64Url(token.issuer) + "\n" +
        "stage=" + std::to_string(static_cast<int>(token.stage)) + "\n" +
        "edge_device_id_b64=" + EncodeBase64Url(token.edge_device_id) + "\n" +
        "mission_id_b64=" + EncodeBase64Url(token.mission_id) + "\n" +
        "dispatch_id_b64=" + EncodeBase64Url(token.dispatch_id) + "\n" +
        "issued_at_utc_ms=" + std::to_string(token.issued_at_utc_ms) + "\n" +
        "expires_at_utc_ms=" + std::to_string(token.expires_at_utc_ms) + "\n";
    switch (WritePrivateFileAtomic(state_directory, kFieldArmingTokenFilename, contents)) {
        case PrivateAtomicWriteResult::kWritten:
            return ArmingTokenWriteVerdict::kWritten;
        case PrivateAtomicWriteResult::kUnsafeDirectory:
            return ArmingTokenWriteVerdict::kUnsafeStateDirectory;
        case PrivateAtomicWriteResult::kWriteFailed:
            return ArmingTokenWriteVerdict::kWriteFailed;
    }
    return ArmingTokenWriteVerdict::kWriteFailed;
}

ArmingTokenConsumptionResult ConsumeFieldArmingToken(
    const std::string& state_directory, const std::string& expected_edge_device_id,
    const std::string& expected_mission_id, const std::string& expected_dispatch_id,
    FlightExecutionStage expected_stage, std::int64_t now_utc_ms) {
    ArmingTokenConsumptionResult result;
    if (state_directory.empty() || expected_edge_device_id.empty() || expected_mission_id.empty() ||
        expected_dispatch_id.empty() || now_utc_ms < 0 || !IsPrivateOwnedDirectory(state_directory)) {
        result.verdict = ArmingTokenVerdict::kUnsafeStateDirectory;
        return result;
    }
    const std::string path = state_directory + "/" + std::string(kFieldArmingTokenFilename);
    std::string bytes;
    switch (ReadPrivateFile(path, kMaximumArmingTokenBytes, &bytes)) {
        case PrivateFileReadResult::kRead:
            break;
        case PrivateFileReadResult::kMissing:
            result.verdict = ArmingTokenVerdict::kMissing;
            return result;
        case PrivateFileReadResult::kUnsafe:
            result.verdict = ArmingTokenVerdict::kUnsafeFile;
            return result;
        case PrivateFileReadResult::kUnreadable:
            result.verdict = ArmingTokenVerdict::kUnreadable;
            return result;
        case PrivateFileReadResult::kTooLarge:
            result.verdict = ArmingTokenVerdict::kTooLarge;
            return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(bytes, kFieldArmingTokenMagic, &fields) ||
        !FieldsMatchExactly(fields, kFieldArmingTokenRequiredFields)) {
        result.verdict = ArmingTokenVerdict::kMalformed;
        return result;
    }
    FieldArmingToken token;
    if (!DecodeBase64Url(fields["nonce_b64"], &token.nonce) ||
        !DecodeBase64Url(fields["issuer_b64"], &token.issuer) ||
        !DecodeBase64Url(fields["edge_device_id_b64"], &token.edge_device_id) ||
        !DecodeBase64Url(fields["mission_id_b64"], &token.mission_id) ||
        !DecodeBase64Url(fields["dispatch_id_b64"], &token.dispatch_id) ||
        !IsSafeText(token.nonce) || !IsSafeText(token.issuer) || !IsSafeText(token.edge_device_id) ||
        !IsSafeText(token.mission_id) || !IsSafeText(token.dispatch_id) ||
        !ParseNonnegativeInt64(fields["issued_at_utc_ms"], &token.issued_at_utc_ms) ||
        !ParseNonnegativeInt64(fields["expires_at_utc_ms"], &token.expires_at_utc_ms) ||
        !ParseStageDigit(fields["stage"], &token.stage) ||
        token.expires_at_utc_ms <= token.issued_at_utc_ms) {
        result.verdict = ArmingTokenVerdict::kMalformed;
        return result;
    }
    if (token.expires_at_utc_ms - token.issued_at_utc_ms > kMaximumArmingTokenTtlMs) {
        result.verdict = ArmingTokenVerdict::kTtlTooLong;
        return result;
    }
    if (token.stage != expected_stage) {
        result.verdict = ArmingTokenVerdict::kStageMismatch;
        return result;
    }
    if (token.edge_device_id != expected_edge_device_id) {
        result.verdict = ArmingTokenVerdict::kDeviceMismatch;
        return result;
    }
    if (token.mission_id != expected_mission_id) {
        result.verdict = ArmingTokenVerdict::kMissionMismatch;
        return result;
    }
    if (token.dispatch_id != expected_dispatch_id) {
        result.verdict = ArmingTokenVerdict::kDispatchMismatch;
        return result;
    }
    if (now_utc_ms < token.issued_at_utc_ms) {
        result.verdict = ArmingTokenVerdict::kNotYetValid;
        return result;
    }
    if (now_utc_ms > token.expires_at_utc_ms) {
        result.verdict = ArmingTokenVerdict::kExpired;
        return result;
    }
    // 유효 판정에 도달한 이 호출 자체가 소비 시점이다(호출 전/후가 아니라) —
    // ADR-KSI-021 §5 "nonce 를 여기서 소비한다".
    if (unlink(path.c_str()) != 0 && errno != ENOENT) {
        result.verdict = ArmingTokenVerdict::kConsumeFailed;
        return result;
    }
    (void)FsyncDirectoryBestEffort(state_directory);
    result.verdict = ArmingTokenVerdict::kConsumed;
    result.token = token;
    return result;
}

// ── §8 abort 요청 ────────────────────────────────────────────────────────

AbortRequestWriteVerdict WriteAbortRequest(const std::string& state_directory,
                                           const AbortRequestRecord& record) {
    if (state_directory.empty() || !IsSafeText(record.requested_by) || !IsSafeText(record.reason) ||
        record.requested_at_utc_ms < 0 ||
        (!record.mission_id.empty() && !IsSafeText(record.mission_id)) ||
        (!record.dispatch_id.empty() && !IsSafeText(record.dispatch_id))) {
        return AbortRequestWriteVerdict::kInvalidRequest;
    }
    std::string contents = kAbortRequestMagic + "\n" +
                           "requested_by_b64=" + EncodeBase64Url(record.requested_by) + "\n" +
                           "reason_b64=" + EncodeBase64Url(record.reason) + "\n" +
                           "requested_at_utc_ms=" + std::to_string(record.requested_at_utc_ms) + "\n";
    if (!record.mission_id.empty()) {
        contents += "mission_id_b64=" + EncodeBase64Url(record.mission_id) + "\n";
    }
    if (!record.dispatch_id.empty()) {
        contents += "dispatch_id_b64=" + EncodeBase64Url(record.dispatch_id) + "\n";
    }
    switch (WritePrivateFileAtomic(state_directory, kFlightAbortRequestFilename, contents)) {
        case PrivateAtomicWriteResult::kWritten:
            return AbortRequestWriteVerdict::kWritten;
        case PrivateAtomicWriteResult::kUnsafeDirectory:
            return AbortRequestWriteVerdict::kUnsafeStateDirectory;
        case PrivateAtomicWriteResult::kWriteFailed:
            return AbortRequestWriteVerdict::kWriteFailed;
    }
    return AbortRequestWriteVerdict::kWriteFailed;
}

AbortRequestReadResult ReadAbortRequest(const std::string& state_directory) {
    AbortRequestReadResult result;
    if (state_directory.empty() || !IsPrivateOwnedDirectory(state_directory)) {
        result.verdict = AbortRequestReadVerdict::kUnsafeStateDirectory;
        return result;
    }
    const std::string path = state_directory + "/" + std::string(kFlightAbortRequestFilename);
    std::string bytes;
    switch (ReadPrivateFile(path, kMaximumAbortRequestBytes, &bytes)) {
        case PrivateFileReadResult::kRead:
            break;
        case PrivateFileReadResult::kMissing:
            result.verdict = AbortRequestReadVerdict::kAbsent;
            return result;
        case PrivateFileReadResult::kUnsafe:
            result.verdict = AbortRequestReadVerdict::kUnsafeFile;
            return result;
        case PrivateFileReadResult::kUnreadable:
            result.verdict = AbortRequestReadVerdict::kUnreadable;
            return result;
        case PrivateFileReadResult::kTooLarge:
            result.verdict = AbortRequestReadVerdict::kTooLarge;
            return result;
    }
    std::map<std::string, std::string> fields;
    if (!ParseStrictLines(bytes, kAbortRequestMagic, &fields) ||
        !FieldsWithinAllowedSet(fields, kAbortRequestRequiredFields, kAbortRequestOptionalFields)) {
        result.verdict = AbortRequestReadVerdict::kMalformed;
        return result;
    }
    AbortRequestRecord record;
    if (!DecodeBase64Url(fields["requested_by_b64"], &record.requested_by) ||
        !DecodeBase64Url(fields["reason_b64"], &record.reason) ||
        !IsSafeText(record.requested_by) || !IsSafeText(record.reason) ||
        !ParseNonnegativeInt64(fields["requested_at_utc_ms"], &record.requested_at_utc_ms)) {
        result.verdict = AbortRequestReadVerdict::kMalformed;
        return result;
    }
    if (fields.count("mission_id_b64") != 0U) {
        if (!DecodeBase64Url(fields["mission_id_b64"], &record.mission_id) ||
            !IsSafeText(record.mission_id)) {
            result.verdict = AbortRequestReadVerdict::kMalformed;
            return result;
        }
    }
    if (fields.count("dispatch_id_b64") != 0U) {
        if (!DecodeBase64Url(fields["dispatch_id_b64"], &record.dispatch_id) ||
            !IsSafeText(record.dispatch_id)) {
            result.verdict = AbortRequestReadVerdict::kMalformed;
            return result;
        }
    }
    result.verdict = AbortRequestReadVerdict::kPresent;
    result.record = std::move(record);
    return result;
}

bool ClearAbortRequest(const std::string& state_directory) {
    if (state_directory.empty() || !IsPrivateOwnedDirectory(state_directory)) {
        return false;
    }
    const std::string path = state_directory + "/" + std::string(kFlightAbortRequestFilename);
    if (unlink(path.c_str()) != 0 && errno != ENOENT) {
        return false;
    }
    return FsyncDirectoryBestEffort(state_directory);
}

// ── [5] KMZ 파싱 후 봉투 재도출 ──────────────────────────────────────────────

KmzEnvelopeRederivationResult RederiveKmzAltitudeEnvelope(const std::string& kmz_bytes) {
    KmzEnvelopeRederivationResult result;
    std::size_t offset = 0U;
    std::size_t entries_scanned = 0U;
    while (offset + 4U <= kmz_bytes.size() && entries_scanned < kMaximumZipEntriesScanned) {
        const std::uint32_t signature = ReadLittleEndianU32(kmz_bytes, offset);
        if (signature != kZipLocalFileSignature) {
            break;
        }
        ++entries_scanned;
        ZipLocalFileHeader header;
        std::string filename;
        if (!ReadZipLocalFileHeader(kmz_bytes, offset, &header, &filename)) {
            result.verdict = KmzEnvelopeRederivationVerdict::kZipMalformed;
            return result;
        }
        // 데이터 디스크립터 사용 항목(bit 3)은 거부한다 — wpml.py 는 고정
        // ZipInfo + writestr 만 쓰므로 절대 이 플래그를 세우지 않는다. 세워져
        // 있다면 이 판독기가 신뢰하는 전제(로컬 헤더에 실제 크기가 이미 있다)
        // 가 깨진다.
        if ((header.flags & 0x0008U) != 0U) {
            result.verdict = KmzEnvelopeRederivationVerdict::kZipMalformed;
            return result;
        }
        if (filename == kWaylinesEntryName) {
            std::string decompressed;
            if (header.method == 0U) {
                if (header.compressed_size != header.uncompressed_size ||
                    header.uncompressed_size > kMaximumWaylinesUncompressedBytes) {
                    result.verdict = KmzEnvelopeRederivationVerdict::kWaylinesTooLarge;
                    return result;
                }
                decompressed = kmz_bytes.substr(header.data_offset, header.compressed_size);
            } else if (header.method == 8U) {
                if (header.uncompressed_size > kMaximumWaylinesUncompressedBytes) {
                    result.verdict = KmzEnvelopeRederivationVerdict::kWaylinesTooLarge;
                    return result;
                }
                std::vector<std::uint8_t> output;
                output.reserve(header.uncompressed_size);
                const auto* compressed_start =
                    reinterpret_cast<const std::uint8_t*>(kmz_bytes.data()) + header.data_offset;
                if (!InflateRaw(compressed_start, header.compressed_size,
                                kMaximumWaylinesUncompressedBytes, &output) ||
                    output.size() != header.uncompressed_size) {
                    result.verdict = KmzEnvelopeRederivationVerdict::kInflateFailed;
                    return result;
                }
                decompressed.assign(reinterpret_cast<const char*>(output.data()), output.size());
            } else {
                result.verdict = KmzEnvelopeRederivationVerdict::kZipMalformed;
                return result;
            }
            const std::uint32_t computed_crc = Crc32(
                reinterpret_cast<const std::uint8_t*>(decompressed.data()), decompressed.size());
            if (computed_crc != header.crc32) {
                result.verdict = KmzEnvelopeRederivationVerdict::kCrcMismatch;
                return result;
            }
            return ExtractAltitudeRangeFromWaylines(decompressed);
        }
        offset = header.data_offset + header.compressed_size;
    }
    result.verdict = KmzEnvelopeRederivationVerdict::kWaylinesEntryMissing;
    return result;
}

// ── [6] 보수적 상한 가드 ─────────────────────────────────────────────────────

CeilingGuardResult EvaluateFlightExecutionCeilingGuard(const CeilingGuardInput& input) {
    CeilingGuardResult result;
    if (!std::isfinite(input.takeoff_elevation_m) || !std::isfinite(input.declared_max_altitude_m)) {
        result.verdict = CeilingGuardVerdict::kNonFiniteInput;
        return result;
    }
    for (const double sample : input.aoi_terrain_elevation_samples_m) {
        if (!std::isfinite(sample)) {
            result.verdict = CeilingGuardVerdict::kNonFiniteInput;
            return result;
        }
    }
    if (!input.has_dtm_coverage) {
        result.verdict = CeilingGuardVerdict::kNoDtmCoverage;
        return result;
    }
    if (input.aoi_terrain_elevation_samples_m.empty()) {
        result.verdict = CeilingGuardVerdict::kTerrainSamplesEmpty;
        return result;
    }
    double terrain_min = input.aoi_terrain_elevation_samples_m.front();
    double terrain_max = terrain_min;
    for (const double sample : input.aoi_terrain_elevation_samples_m) {
        terrain_min = std::min(terrain_min, sample);
        terrain_max = std::max(terrain_max, sample);
    }
    result.observed_terrain_min_m = terrain_min;
    result.observed_terrain_max_m = terrain_max;
    result.observed_terrain_relief_m = terrain_max - terrain_min;
    if (result.observed_terrain_relief_m > kCeilingGuardMaxTerrainReliefM) {
        result.verdict = CeilingGuardVerdict::kTerrainNotFlat;
        return result;
    }
    if (input.takeoff_elevation_m < terrain_min || input.takeoff_elevation_m > terrain_max) {
        result.verdict = CeilingGuardVerdict::kTakeoffOutsideTerrainRange;
        return result;
    }
    if (input.declared_max_altitude_m > kCeilingGuardMaxEffectiveAltitudeM) {
        result.verdict = CeilingGuardVerdict::kCeilingTooHigh;
        return result;
    }
    if (input.site_density == SiteDensityDeclaration::kUnspecified) {
        result.verdict = CeilingGuardVerdict::kDensityUnspecified;
        return result;
    }
    if (input.site_density == SiteDensityDeclaration::kCongestedArea) {
        result.verdict = CeilingGuardVerdict::kDensityCongested;
        return result;
    }
    result.verdict = CeilingGuardVerdict::kPassed;
    return result;
}

// ── 종합 판단 ────────────────────────────────────────────────────────────────

FlightExecutionVerdict EvaluateFlightExecution(const FlightExecutionRequest& request,
                                               std::int64_t now_utc_ms,
                                               FlightExecutionDecision* decision) {
    FlightExecutionDecision fallback_storage;
    FlightExecutionDecision& out = decision != nullptr ? *decision : fallback_storage;
    out = FlightExecutionDecision{};

    if (now_utc_ms < 0) {
        out.verdict = FlightExecutionVerdict::kInvalidClock;
        return out.verdict;
    }
    // [0]
    if (static_cast<int>(kCompiledFlightExecutionStage) < static_cast<int>(request.requested_stage)) {
        out.verdict = FlightExecutionVerdict::kStageBelowRequired;
        return out.verdict;
    }
    // [1]
    if (request.activation.verdict != NativeActivationVerdict::kLoaded) {
        out.verdict = FlightExecutionVerdict::kActivationInvalid;
        return out.verdict;
    }
    const NativeActivationSnapshot& activation = request.activation.snapshot;

    // 여기부터는 신원(activation)이 있다 — 이후 모든 종료 경로가 [9] durable
    // 기록을 시도한다(ADR §9 "거부도 같은 형식으로 기록한다").
    FlightExecutionVerdict verdict = EvaluateCoreAuthorization(request, activation, now_utc_ms);

    std::string nonce_for_attempt;
    if (verdict == FlightExecutionVerdict::kEligibleForStart) {
        const ArmingTokenConsumptionResult arming = ConsumeFieldArmingToken(
            request.arming_state_directory, activation.edge_device_id, activation.mission_id,
            activation.dispatch_id, request.requested_stage, now_utc_ms);
        out.arming_token_verdict = arming.verdict;
        if (arming.verdict == ArmingTokenVerdict::kConsumed) {
            nonce_for_attempt = arming.token.nonce;
        } else {
            verdict = MapArmingVerdict(arming.verdict);
        }
    }

    if (verdict == FlightExecutionVerdict::kEligibleForStart &&
        request.kmz.verdict != NativeMissionKmzVerdict::kLoaded) {
        verdict = FlightExecutionVerdict::kKmzUnavailable;
    }

    if (verdict == FlightExecutionVerdict::kEligibleForStart) {
        verdict = EvaluateDeclaredEnvelope(request.declared_envelope, request.kmz.kmz.bytes,
                                           &out.envelope_rederivation);
    }

    if (verdict == FlightExecutionVerdict::kEligibleForStart) {
        CeilingGuardInput ceiling_input = request.ceiling_guard_input;
        ceiling_input.declared_max_altitude_m = request.declared_envelope.max_altitude_m;
        out.ceiling_guard = EvaluateFlightExecutionCeilingGuard(ceiling_input);
        if (out.ceiling_guard.verdict != CeilingGuardVerdict::kPassed) {
            verdict = FlightExecutionVerdict::kCeilingGuardRejected;
        }
    }

    if (verdict == FlightExecutionVerdict::kEligibleForStart) {
        if (request.supervisor == nullptr) {
            verdict = FlightExecutionVerdict::kSupervisorMissing;
        } else if (request.supervisor->LastWallClockUtcMs() != 0 &&
                  now_utc_ms < request.supervisor->LastWallClockUtcMs()) {
            verdict = FlightExecutionVerdict::kSupervisorClockRollback;
        } else if (!request.supervisor->IsActivationUsable(now_utc_ms)) {
            verdict = FlightExecutionVerdict::kSupervisorNotActivated;
        } else if (request.supervisor->ControlPlaneStateAt(now_utc_ms) !=
                  control_plane::SupervisorState::kNominal) {
            verdict = FlightExecutionVerdict::kSupervisorNotNominal;
        }
    }

    if (verdict == FlightExecutionVerdict::kEligibleForStart) {
        verdict = EvaluateAircraftPreconditions(request, now_utc_ms);
    }

    // [9] durable 기록. 성공(kEligibleForStart)은 이 기록이 확정돼야만 성립한다
    // — 실패는 이미 확정된 거부 사유이므로 저널 실패가 그 사유를 덮지 않는다.
    const std::string attempt_id =
        DeriveAttemptId(activation.dispatch_id, nonce_for_attempt, now_utc_ms, verdict);
    out.flight_start_attempt_id = attempt_id;
    if (request.journal == nullptr) {
        out.journal_verdict = FlightStartAttemptJournalVerdict::kBackendUnavailable;
        if (verdict == FlightExecutionVerdict::kEligibleForStart) {
            verdict = FlightExecutionVerdict::kJournalUnavailable;
        }
        out.verdict = verdict;
        return verdict;
    }
    FlightStartAttemptRecord record;
    record.attempt_id = attempt_id;
    record.mission_id = activation.mission_id;
    record.dispatch_id = activation.dispatch_id;
    record.mission_contract_digest = activation.context.mission_contract_digest;
    record.kmz_sha256 = request.kmz.verdict == NativeMissionKmzVerdict::kLoaded
                            ? request.kmz.kmz.kmz_sha256
                            : std::string{};
    record.stage = ToString(request.requested_stage);
    record.precondition_verdicts_json = PreconditionVerdictsJson(
        verdict, out.arming_token_verdict, out.envelope_rederivation, out.ceiling_guard);
    record.outcome = verdict == FlightExecutionVerdict::kEligibleForStart
                         ? std::string("ELIGIBLE_FOR_START")
                         : std::string("REFUSED_") + ToString(verdict);
    record.attempted_at_utc_ms = now_utc_ms;
    out.journal_verdict = request.journal->RecordFlightStartAttempt(record);
    const bool journal_ok = out.journal_verdict == FlightStartAttemptJournalVerdict::kAccepted ||
                            out.journal_verdict == FlightStartAttemptJournalVerdict::kDuplicate;
    if (verdict == FlightExecutionVerdict::kEligibleForStart && !journal_ok) {
        verdict = out.journal_verdict == FlightStartAttemptJournalVerdict::kConflict
                     ? FlightExecutionVerdict::kJournalRejected
                     : FlightExecutionVerdict::kJournalUnavailable;
    }
    out.verdict = verdict;
    return verdict;
}

}  // namespace ksi::edge

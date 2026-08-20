#include "ksi/edge/core_sync_http.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cerrno>
#include <charconv>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

constexpr std::size_t kMaximumUrlBytes = 8192U;
constexpr std::size_t kMaximumJsonDepth = 64U;
constexpr std::size_t kMaximumHeaderCount = 32U;
constexpr std::size_t kMaximumHeaderNameBytes = 128U;
constexpr std::size_t kMaximumHeaderValueBytes = 4096U;

bool IsAsciiAlphaNumeric(unsigned char value) {
    return (value >= static_cast<unsigned char>('a') && value <= static_cast<unsigned char>('z')) ||
           (value >= static_cast<unsigned char>('A') && value <= static_cast<unsigned char>('Z')) ||
           (value >= static_cast<unsigned char>('0') && value <= static_cast<unsigned char>('9'));
}

bool IsPathSafeIdentifier(const std::string& value) {
    if (value.empty() || value == "." || value == ".." ||
        !IsAsciiAlphaNumeric(static_cast<unsigned char>(value.front()))) {
        return false;
    }
    for (const char character : value) {
        const unsigned char value_byte = static_cast<unsigned char>(character);
        if (!(IsAsciiAlphaNumeric(value_byte) || character == '.' || character == '_' ||
              character == '-')) {
            return false;
        }
    }
    return true;
}

bool IsValidBearerToken(const std::string& value) {
    if (value.empty() || value.size() > 4096U) {
        return false;
    }
    for (const char character : value) {
        const unsigned char byte = static_cast<unsigned char>(character);
        if (!(IsAsciiAlphaNumeric(byte) || character == '-' || character == '.' || character == '_' ||
              character == '~' || character == '+' || character == '/' || character == '=')) {
            return false;
        }
    }
    return true;
}

bool IsHeaderNameCharacter(unsigned char value) {
    return IsAsciiAlphaNumeric(value) || value == static_cast<unsigned char>('!') ||
           value == static_cast<unsigned char>('#') || value == static_cast<unsigned char>('$') ||
           value == static_cast<unsigned char>('%') || value == static_cast<unsigned char>('&') ||
           value == static_cast<unsigned char>('\'') || value == static_cast<unsigned char>('*') ||
           value == static_cast<unsigned char>('+') || value == static_cast<unsigned char>('-') ||
           value == static_cast<unsigned char>('.') || value == static_cast<unsigned char>('^') ||
           value == static_cast<unsigned char>('_') || value == static_cast<unsigned char>('`') ||
           value == static_cast<unsigned char>('|') || value == static_cast<unsigned char>('~');
}

bool IsValidHeaderName(const std::string& value) {
    if (value.empty() || value.size() > kMaximumHeaderNameBytes) {
        return false;
    }
    return std::all_of(value.begin(), value.end(), [](char character) {
        return IsHeaderNameCharacter(static_cast<unsigned char>(character));
    });
}

bool IsValidHeaderValue(const std::string& value) {
    if (value.empty() || value.size() > kMaximumHeaderValueBytes) {
        return false;
    }
    return std::all_of(value.begin(), value.end(), [](char character) {
        const unsigned char byte = static_cast<unsigned char>(character);
        return byte >= 0x20U && byte != 0x7FU;
    });
}

std::string LowerAscii(std::string value) {
    for (char& character : value) {
        const unsigned char byte = static_cast<unsigned char>(character);
        if (byte >= static_cast<unsigned char>('A') && byte <= static_cast<unsigned char>('Z')) {
            character = static_cast<char>(byte - static_cast<unsigned char>('A') +
                                           static_cast<unsigned char>('a'));
        }
    }
    return value;
}

bool IsUrlCharacterAllowed(unsigned char value) {
    return value >= 0x21U && value <= 0x7EU && value != static_cast<unsigned char>('\\');
}

bool IsHostnameCharacter(unsigned char value) {
    return IsAsciiAlphaNumeric(value) || value == static_cast<unsigned char>('-') ||
           value == static_cast<unsigned char>('.');
}

bool IsIpv6Character(unsigned char value) {
    return (value >= static_cast<unsigned char>('0') && value <= static_cast<unsigned char>('9')) ||
           (value >= static_cast<unsigned char>('a') && value <= static_cast<unsigned char>('f')) ||
           (value >= static_cast<unsigned char>('A') && value <= static_cast<unsigned char>('F')) ||
           value == static_cast<unsigned char>(':') || value == static_cast<unsigned char>('.');
}

struct ParsedHttpsUrl {
    std::string authority;
    std::string target;
};

bool ParseStrictHttpsUrl(const std::string& url, bool require_origin_only, ParsedHttpsUrl* parsed) {
    if (parsed == nullptr || url.size() <= 8U || url.size() > kMaximumUrlBytes ||
        url.compare(0U, 8U, "https://") != 0) {
        return false;
    }
    if (!std::all_of(url.begin(), url.end(), [](char character) {
            return IsUrlCharacterAllowed(static_cast<unsigned char>(character));
        })) {
        return false;
    }
    const std::size_t authority_start = 8U;
    const std::size_t authority_end = url.find_first_of("/?#", authority_start);
    const std::size_t bounded_authority_end =
        authority_end == std::string::npos ? url.size() : authority_end;
    if (bounded_authority_end == authority_start ||
        (url.find('@', authority_start) != std::string::npos &&
         url.find('@', authority_start) < bounded_authority_end)) {
        return false;
    }
    const std::string authority = url.substr(authority_start, bounded_authority_end - authority_start);
    std::string host;
    std::string port;
    if (authority.front() == '[') {
        const std::size_t close = authority.find(']');
        if (close == std::string::npos || close == 1U ||
            !std::all_of(authority.begin() + 1, authority.begin() + static_cast<std::ptrdiff_t>(close),
                         [](char character) {
                             return IsIpv6Character(static_cast<unsigned char>(character));
                         })) {
            return false;
        }
        host = authority.substr(1U, close - 1U);
        if (close + 1U < authority.size()) {
            if (authority[close + 1U] != ':') {
                return false;
            }
            port = authority.substr(close + 2U);
        }
    } else {
        const std::size_t colon = authority.find(':');
        if (colon != std::string::npos && authority.find(':', colon + 1U) != std::string::npos) {
            return false;
        }
        host = authority.substr(0U, colon);
        if (colon != std::string::npos) {
            port = authority.substr(colon + 1U);
        }
        if (host.empty() ||
            !std::all_of(host.begin(), host.end(), [](char character) {
                return IsHostnameCharacter(static_cast<unsigned char>(character));
            })) {
            return false;
        }
    }
    if (host.empty() || (!port.empty() &&
                         (!std::all_of(port.begin(), port.end(), [](char character) {
                              return character >= '0' && character <= '9';
                          }) ||
                          port.size() > 5U))) {
        return false;
    }
    if (!port.empty()) {
        unsigned int parsed_port = 0U;
        const auto [end, error] = std::from_chars(port.data(), port.data() + port.size(), parsed_port);
        if (error != std::errc{} || end != port.data() + port.size() || parsed_port == 0U ||
            parsed_port > 65535U) {
            return false;
        }
    }
    const std::string target = bounded_authority_end == url.size() ? std::string{} :
                                                                    url.substr(bounded_authority_end);
    if (target.find('#') != std::string::npos ||
        (!target.empty() && target.front() != '/' && target.front() != '?') ||
        (require_origin_only && !(target.empty() || target == "/"))) {
        return false;
    }
    *parsed = {authority, target};
    return true;
}

std::string EscapeJson(const std::string& value) {
    std::string output;
    output.reserve(value.size() + 8U);
    constexpr char kHex[] = "0123456789abcdef";
    for (const char character : value) {
        const unsigned char byte = static_cast<unsigned char>(character);
        switch (character) {
            case '"':
                output += "\\\"";
                break;
            case '\\':
                output += "\\\\";
                break;
            case '\b':
                output += "\\b";
                break;
            case '\f':
                output += "\\f";
                break;
            case '\n':
                output += "\\n";
                break;
            case '\r':
                output += "\\r";
                break;
            case '\t':
                output += "\\t";
                break;
            default:
                if (byte < 0x20U) {
                    output += "\\u00";
                    output.push_back(kHex[(byte >> 4U) & 0x0FU]);
                    output.push_back(kHex[byte & 0x0FU]);
                } else {
                    output.push_back(character);
                }
                break;
        }
    }
    return output;
}

std::string PercentEncodePathSegment(const std::string& value) {
    constexpr char kHex[] = "0123456789ABCDEF";
    std::string output;
    output.reserve(value.size() * 3U);
    for (const char character : value) {
        const unsigned char byte = static_cast<unsigned char>(character);
        if (IsAsciiAlphaNumeric(byte) || character == '-' || character == '.' || character == '_' ||
            character == '~') {
            output.push_back(character);
        } else {
            output.push_back('%');
            output.push_back(kHex[(byte >> 4U) & 0x0FU]);
            output.push_back(kHex[byte & 0x0FU]);
        }
    }
    return output;
}

enum class JsonType {
    kNull,
    kBoolean,
    kNumber,
    kString,
    kArray,
    kObject,
};

struct JsonValue {
    JsonType type = JsonType::kNull;
    bool boolean_value = false;
    std::string string_value;
    std::string number_value;
    std::vector<JsonValue> array_value;
    std::map<std::string, JsonValue> object_value;
};

class JsonParser {
public:
    explicit JsonParser(const std::string& input) : input_(input) {}

    bool Parse(JsonValue* output) {
        if (output == nullptr) {
            return false;
        }
        SkipWhitespace();
        JsonValue value;
        if (!ParseValue(&value, 0U)) {
            return false;
        }
        SkipWhitespace();
        if (position_ != input_.size()) {
            return false;
        }
        *output = std::move(value);
        return true;
    }

private:
    void SkipWhitespace() {
        while (position_ < input_.size()) {
            const char character = input_[position_];
            if (character != ' ' && character != '\n' && character != '\r' && character != '\t') {
                break;
            }
            ++position_;
        }
    }

    bool ParseValue(JsonValue* output, std::size_t depth) {
        if (output == nullptr || depth > kMaximumJsonDepth || position_ >= input_.size()) {
            return false;
        }
        const char character = input_[position_];
        if (character == '{') {
            return ParseObject(output, depth + 1U);
        }
        if (character == '[') {
            return ParseArray(output, depth + 1U);
        }
        if (character == '"') {
            output->type = JsonType::kString;
            return ParseString(&output->string_value);
        }
        if (character == 't') {
            if (!ConsumeLiteral("true")) {
                return false;
            }
            output->type = JsonType::kBoolean;
            output->boolean_value = true;
            return true;
        }
        if (character == 'f') {
            if (!ConsumeLiteral("false")) {
                return false;
            }
            output->type = JsonType::kBoolean;
            output->boolean_value = false;
            return true;
        }
        if (character == 'n') {
            if (!ConsumeLiteral("null")) {
                return false;
            }
            output->type = JsonType::kNull;
            return true;
        }
        if (character == '-' || (character >= '0' && character <= '9')) {
            output->type = JsonType::kNumber;
            return ParseNumber(&output->number_value);
        }
        return false;
    }

    bool ParseObject(JsonValue* output, std::size_t depth) {
        if (input_[position_] != '{') {
            return false;
        }
        ++position_;
        output->type = JsonType::kObject;
        SkipWhitespace();
        if (position_ < input_.size() && input_[position_] == '}') {
            ++position_;
            return true;
        }
        while (position_ < input_.size()) {
            std::string key;
            if (!ParseString(&key)) {
                return false;
            }
            SkipWhitespace();
            if (position_ >= input_.size() || input_[position_] != ':') {
                return false;
            }
            ++position_;
            SkipWhitespace();
            JsonValue value;
            if (!ParseValue(&value, depth)) {
                return false;
            }
            if (!output->object_value.emplace(std::move(key), std::move(value)).second) {
                return false;
            }
            SkipWhitespace();
            if (position_ >= input_.size()) {
                return false;
            }
            if (input_[position_] == '}') {
                ++position_;
                return true;
            }
            if (input_[position_] != ',') {
                return false;
            }
            ++position_;
            SkipWhitespace();
        }
        return false;
    }

    bool ParseArray(JsonValue* output, std::size_t depth) {
        if (input_[position_] != '[') {
            return false;
        }
        ++position_;
        output->type = JsonType::kArray;
        SkipWhitespace();
        if (position_ < input_.size() && input_[position_] == ']') {
            ++position_;
            return true;
        }
        while (position_ < input_.size()) {
            JsonValue value;
            if (!ParseValue(&value, depth)) {
                return false;
            }
            output->array_value.push_back(std::move(value));
            SkipWhitespace();
            if (position_ >= input_.size()) {
                return false;
            }
            if (input_[position_] == ']') {
                ++position_;
                return true;
            }
            if (input_[position_] != ',') {
                return false;
            }
            ++position_;
            SkipWhitespace();
        }
        return false;
    }

    bool ParseString(std::string* output) {
        if (output == nullptr || position_ >= input_.size() || input_[position_] != '"') {
            return false;
        }
        ++position_;
        output->clear();
        while (position_ < input_.size()) {
            const unsigned char byte = static_cast<unsigned char>(input_[position_]);
            if (byte == static_cast<unsigned char>('"')) {
                ++position_;
                return true;
            }
            if (byte < 0x20U) {
                return false;
            }
            if (byte == static_cast<unsigned char>('\\')) {
                ++position_;
                if (position_ >= input_.size()) {
                    return false;
                }
                const char escaped = input_[position_++];
                switch (escaped) {
                    case '"':
                    case '\\':
                    case '/':
                        output->push_back(escaped);
                        break;
                    case 'b':
                        output->push_back('\b');
                        break;
                    case 'f':
                        output->push_back('\f');
                        break;
                    case 'n':
                        output->push_back('\n');
                        break;
                    case 'r':
                        output->push_back('\r');
                        break;
                    case 't':
                        output->push_back('\t');
                        break;
                    case 'u': {
                        std::uint32_t code_point = 0U;
                        if (!ParseUnicodeEscape(&code_point)) {
                            return false;
                        }
                        if (code_point >= 0xD800U && code_point <= 0xDBFFU) {
                            if (position_ + 2U > input_.size() || input_[position_] != '\\' ||
                                input_[position_ + 1U] != 'u') {
                                return false;
                            }
                            position_ += 2U;
                            std::uint32_t low_surrogate = 0U;
                            if (!ParseUnicodeEscape(&low_surrogate) || low_surrogate < 0xDC00U ||
                                low_surrogate > 0xDFFFU) {
                                return false;
                            }
                            code_point = 0x10000U + ((code_point - 0xD800U) << 10U) +
                                         (low_surrogate - 0xDC00U);
                        } else if (code_point >= 0xDC00U && code_point <= 0xDFFFU) {
                            return false;
                        }
                        AppendUtf8(code_point, output);
                        break;
                    }
                    default:
                        return false;
                }
                continue;
            }
            if (byte < 0x80U) {
                output->push_back(static_cast<char>(byte));
                ++position_;
                continue;
            }
            const std::size_t start = position_;
            std::size_t bytes = 0U;
            if (byte >= 0xC2U && byte <= 0xDFU) {
                bytes = 2U;
            } else if (byte >= 0xE0U && byte <= 0xEFU) {
                bytes = 3U;
            } else if (byte >= 0xF0U && byte <= 0xF4U) {
                bytes = 4U;
            } else {
                return false;
            }
            if (position_ + bytes > input_.size()) {
                return false;
            }
            for (std::size_t index = 1U; index < bytes; ++index) {
                const unsigned char continuation = static_cast<unsigned char>(input_[position_ + index]);
                if (continuation < 0x80U || continuation > 0xBFU) {
                    return false;
                }
            }
            const unsigned char second = static_cast<unsigned char>(input_[position_ + 1U]);
            if ((byte == 0xE0U && second < 0xA0U) || (byte == 0xEDU && second > 0x9FU) ||
                (byte == 0xF0U && second < 0x90U) || (byte == 0xF4U && second > 0x8FU)) {
                return false;
            }
            output->append(input_, start, bytes);
            position_ += bytes;
        }
        return false;
    }

    bool ParseUnicodeEscape(std::uint32_t* value) {
        if (value == nullptr || position_ + 4U > input_.size()) {
            return false;
        }
        std::uint32_t result = 0U;
        for (std::size_t index = 0U; index < 4U; ++index) {
            const char character = input_[position_++];
            std::uint32_t digit = 0U;
            if (character >= '0' && character <= '9') {
                digit = static_cast<std::uint32_t>(character - '0');
            } else if (character >= 'a' && character <= 'f') {
                digit = static_cast<std::uint32_t>(character - 'a' + 10);
            } else if (character >= 'A' && character <= 'F') {
                digit = static_cast<std::uint32_t>(character - 'A' + 10);
            } else {
                return false;
            }
            result = (result << 4U) | digit;
        }
        *value = result;
        return true;
    }

    static void AppendUtf8(std::uint32_t code_point, std::string* output) {
        if (code_point <= 0x7FU) {
            output->push_back(static_cast<char>(code_point));
        } else if (code_point <= 0x7FFU) {
            output->push_back(static_cast<char>(0xC0U | (code_point >> 6U)));
            output->push_back(static_cast<char>(0x80U | (code_point & 0x3FU)));
        } else if (code_point <= 0xFFFFU) {
            output->push_back(static_cast<char>(0xE0U | (code_point >> 12U)));
            output->push_back(static_cast<char>(0x80U | ((code_point >> 6U) & 0x3FU)));
            output->push_back(static_cast<char>(0x80U | (code_point & 0x3FU)));
        } else {
            output->push_back(static_cast<char>(0xF0U | (code_point >> 18U)));
            output->push_back(static_cast<char>(0x80U | ((code_point >> 12U) & 0x3FU)));
            output->push_back(static_cast<char>(0x80U | ((code_point >> 6U) & 0x3FU)));
            output->push_back(static_cast<char>(0x80U | (code_point & 0x3FU)));
        }
    }

    bool ParseNumber(std::string* output) {
        if (output == nullptr) {
            return false;
        }
        const std::size_t start = position_;
        if (position_ < input_.size() && input_[position_] == '-') {
            ++position_;
        }
        if (position_ >= input_.size()) {
            return false;
        }
        if (input_[position_] == '0') {
            ++position_;
        } else if (input_[position_] >= '1' && input_[position_] <= '9') {
            do {
                ++position_;
            } while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9');
        } else {
            return false;
        }
        if (position_ < input_.size() && input_[position_] == '.') {
            ++position_;
            const std::size_t fraction_start = position_;
            while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') {
                ++position_;
            }
            if (position_ == fraction_start) {
                return false;
            }
        }
        if (position_ < input_.size() && (input_[position_] == 'e' || input_[position_] == 'E')) {
            ++position_;
            if (position_ < input_.size() && (input_[position_] == '+' || input_[position_] == '-')) {
                ++position_;
            }
            const std::size_t exponent_start = position_;
            while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') {
                ++position_;
            }
            if (position_ == exponent_start) {
                return false;
            }
        }
        *output = input_.substr(start, position_ - start);
        return true;
    }

    bool ConsumeLiteral(const char* literal) {
        const std::size_t length = std::strlen(literal);
        if (position_ + length > input_.size() || input_.compare(position_, length, literal) != 0) {
            return false;
        }
        position_ += length;
        return true;
    }

    const std::string& input_;
    std::size_t position_ = 0U;
};

bool ParseJsonObject(const std::string& input, std::size_t maximum_bytes, JsonValue* output) {
    if (output == nullptr || input.empty() || input.size() > maximum_bytes) {
        return false;
    }
    JsonParser parser(input);
    if (!parser.Parse(output) || output->type != JsonType::kObject) {
        return false;
    }
    return true;
}

bool IsCanonicalInteger(const std::string& value) {
    if (value.empty()) {
        return false;
    }
    std::size_t offset = 0U;
    if (value.front() == '-') {
        if (value.size() == 1U) {
            return false;
        }
        offset = 1U;
    }
    if (value[offset] == '0') {
        return value.size() == offset + 1U;
    }
    if (value[offset] < '1' || value[offset] > '9') {
        return false;
    }
    return std::all_of(value.begin() + static_cast<std::ptrdiff_t>(offset + 1U), value.end(),
                       [](char character) { return character >= '0' && character <= '9'; });
}

bool AppendCanonicalJson(const JsonValue& value, std::size_t depth, std::string* output) {
    if (output == nullptr || depth > kMaximumJsonDepth) {
        return false;
    }
    switch (value.type) {
        case JsonType::kNull:
            *output += "null";
            return true;
        case JsonType::kBoolean:
            *output += value.boolean_value ? "true" : "false";
            return true;
        case JsonType::kNumber:
            // The native EventBundle builder intentionally has no floating
            // values.  Accepting decimal/exponent spellings here would require
            // reproducing CPython's floating-point JSON representation to
            // calculate the same offline-sync digest; reject rather than guess.
            if (!IsCanonicalInteger(value.number_value)) {
                return false;
            }
            *output += value.number_value;
            return true;
        case JsonType::kString:
            *output += '"';
            *output += EscapeJson(value.string_value);
            *output += '"';
            return true;
        case JsonType::kArray:
            *output += '[';
            for (std::size_t index = 0U; index < value.array_value.size(); ++index) {
                if (index != 0U) {
                    *output += ',';
                }
                if (!AppendCanonicalJson(value.array_value[index], depth + 1U, output)) {
                    return false;
                }
            }
            *output += ']';
            return true;
        case JsonType::kObject:
            *output += '{';
            for (auto member = value.object_value.begin(); member != value.object_value.end(); ++member) {
                if (member != value.object_value.begin()) {
                    *output += ',';
                }
                *output += '"';
                *output += EscapeJson(member->first);
                *output += "\":";
                if (!AppendCanonicalJson(member->second, depth + 1U, output)) {
                    return false;
                }
            }
            *output += '}';
            return true;
    }
    return false;
}

bool IsNativeCanonicalPayload(const std::string& payload, const JsonValue& parsed) {
    std::string canonical;
    canonical.reserve(payload.size());
    return AppendCanonicalJson(parsed, 0U, &canonical) && canonical == payload;
}

const JsonValue* FindMember(const JsonValue& object, const std::string& key) {
    if (object.type != JsonType::kObject) {
        return nullptr;
    }
    const auto found = object.object_value.find(key);
    return found == object.object_value.end() ? nullptr : &found->second;
}

bool RequiredString(const JsonValue& object, const std::string& key, std::string* output) {
    const JsonValue* value = FindMember(object, key);
    if (output == nullptr || value == nullptr || value->type != JsonType::kString ||
        value->string_value.empty()) {
        return false;
    }
    *output = value->string_value;
    return true;
}

bool RequiredBoolean(const JsonValue& object, const std::string& key) {
    const JsonValue* value = FindMember(object, key);
    return value != nullptr && value->type == JsonType::kBoolean;
}

bool ExtractCandidateEventId(const CandidateEventRecord& candidate, std::size_t maximum_payload_bytes,
                             std::string* event_id) {
    if (event_id == nullptr || candidate.idempotency_key.empty() || candidate.device_sequence < 0 ||
        !IsPathSafeIdentifier(candidate.edge_device_id) || !IsSha256Digest(candidate.payload_digest)) {
        return false;
    }
    JsonValue payload;
    if (!ParseJsonObject(candidate.payload_json, maximum_payload_bytes, &payload) ||
        !IsNativeCanonicalPayload(candidate.payload_json, payload) ||
        Sha256Digest(candidate.payload_json) != candidate.payload_digest ||
        !RequiredString(payload, "eventId", event_id) || !IsPathSafeIdentifier(*event_id)) {
        return false;
    }
    return true;
}

struct CandidateEvidenceContext {
    std::string event_id;
    std::string site_id;
    std::string mission_id;
};

bool ExtractCandidateEvidenceContext(const CandidateEventRecord& candidate,
                                     std::size_t maximum_payload_bytes,
                                     CandidateEvidenceContext* context) {
    if (context == nullptr || candidate.idempotency_key.empty() || candidate.device_sequence < 0 ||
        !IsPathSafeIdentifier(candidate.edge_device_id) || !IsSha256Digest(candidate.payload_digest)) {
        return false;
    }
    JsonValue payload;
    if (!ParseJsonObject(candidate.payload_json, maximum_payload_bytes, &payload) ||
        !IsNativeCanonicalPayload(candidate.payload_json, payload) ||
        Sha256Digest(candidate.payload_json) != candidate.payload_digest ||
        !RequiredString(payload, "eventId", &context->event_id) ||
        !RequiredString(payload, "siteId", &context->site_id) ||
        !RequiredString(payload, "missionId", &context->mission_id) ||
        !IsPathSafeIdentifier(context->event_id) || !IsPathSafeIdentifier(context->site_id) ||
        !IsPathSafeIdentifier(context->mission_id)) {
        return false;
    }
    return true;
}

bool DecodeHexByte(char high, char low, std::uint8_t* output) {
    if (output == nullptr) {
        return false;
    }
    const auto decode = [](char character, std::uint8_t* value) {
        if (character >= '0' && character <= '9') {
            *value = static_cast<std::uint8_t>(character - '0');
            return true;
        }
        if (character >= 'a' && character <= 'f') {
            *value = static_cast<std::uint8_t>(character - 'a' + 10);
            return true;
        }
        return false;
    };
    std::uint8_t high_value = 0U;
    std::uint8_t low_value = 0U;
    if (!decode(high, &high_value) || !decode(low, &low_value)) {
        return false;
    }
    *output = static_cast<std::uint8_t>((high_value << 4U) | low_value);
    return true;
}

std::string DigestToBase64Checksum(const std::string& digest) {
    if (!IsSha256Digest(digest)) {
        return {};
    }
    std::array<std::uint8_t, 32> bytes {};
    for (std::size_t index = 0U; index < bytes.size(); ++index) {
        if (!DecodeHexByte(digest[7U + index * 2U], digest[8U + index * 2U], &bytes[index])) {
            return {};
        }
    }
    constexpr char kAlphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string output;
    output.reserve(44U);
    for (std::size_t index = 0U; index < 30U; index += 3U) {
        const std::uint32_t value = (static_cast<std::uint32_t>(bytes[index]) << 16U) |
                                    (static_cast<std::uint32_t>(bytes[index + 1U]) << 8U) |
                                    static_cast<std::uint32_t>(bytes[index + 2U]);
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 6U) & 0x3FU]);
        output.push_back(kAlphabet[value & 0x3FU]);
    }
    const std::uint32_t final = (static_cast<std::uint32_t>(bytes[30U]) << 16U) |
                                (static_cast<std::uint32_t>(bytes[31U]) << 8U);
    output.push_back(kAlphabet[(final >> 18U) & 0x3FU]);
    output.push_back(kAlphabet[(final >> 12U) & 0x3FU]);
    output.push_back(kAlphabet[(final >> 6U) & 0x3FU]);
    output.push_back('=');
    return output;
}

bool IsValidEvidenceHeaders(const std::map<std::string, std::string>& headers,
                            const EvidenceRecord& evidence) {
    if (headers.empty() || headers.size() > kMaximumHeaderCount || evidence.content_type.empty() ||
        !IsSha256Digest(evidence.content_digest)) {
        return false;
    }
    const std::string expected_checksum = DigestToBase64Checksum(evidence.content_digest);
    if (expected_checksum.empty()) {
        return false;
    }
    bool content_type_seen = false;
    bool checksum_seen = false;
    std::map<std::string, bool> normalized_names;
    for (const auto& header : headers) {
        if (!IsValidHeaderName(header.first) || !IsValidHeaderValue(header.second)) {
            return false;
        }
        const std::string normalized = LowerAscii(header.first);
        if (!normalized_names.emplace(normalized, true).second) {
            return false;
        }
        if (normalized == "content-type") {
            if (header.second != evidence.content_type) {
                return false;
            }
            content_type_seen = true;
        } else if (normalized == "x-amz-checksum-sha256") {
            if (header.second != expected_checksum) {
                return false;
            }
            checksum_seen = true;
        } else if (normalized.rfind("x-amz-", 0U) != 0U) {
            // Do not accept Authorization/Host/Content-Length or arbitrary
            // headers from a server response.  Extra x-amz-* values are a
            // bounded part of an S3 capability and travel only to its URL.
            return false;
        }
    }
    return content_type_seen && checksum_seen;
}

bool IsAllowedEvidenceContentType(const std::string& content_type) {
    return content_type == "application/json" || content_type == "image/jpeg" ||
           content_type == "image/png" || content_type == "image/webp" ||
           content_type == "video/mp4" || content_type == "video/webm" ||
           content_type == "application/octet-stream";
}

CoreSyncVerdict MapExecutorVerdict(HttpsRequestVerdict verdict) {
    switch (verdict) {
        case HttpsRequestVerdict::kCompleted:
            return CoreSyncVerdict::kAcknowledged;
        case HttpsRequestVerdict::kRetryableFailure:
            return CoreSyncVerdict::kRetryableFailure;
        case HttpsRequestVerdict::kPermanentFailure:
            return CoreSyncVerdict::kPermanentFailure;
    }
    return CoreSyncVerdict::kPermanentFailure;
}

bool IsRetryableStatus(int status_code) {
    return status_code == 408 || status_code == 425 || status_code == 429 || status_code >= 500;
}

CoreSyncVerdict ValidateCoreResponse(HttpsRequestVerdict executor_verdict,
                                     const HttpsResponse& response,
                                     std::size_t maximum_response_bytes) {
    if (executor_verdict != HttpsRequestVerdict::kCompleted) {
        return MapExecutorVerdict(executor_verdict);
    }
    if (response.body.size() > maximum_response_bytes) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    if (IsRetryableStatus(response.status_code)) {
        return CoreSyncVerdict::kRetryableFailure;
    }
    return CoreSyncVerdict::kAcknowledged;
}

bool IsCandidateAck(const HttpsResponse& response, std::size_t maximum_response_bytes) {
    if ((response.status_code != 200 && response.status_code != 201) ||
        response.body.size() > maximum_response_bytes) {
        return false;
    }
    JsonValue value;
    std::string verdict;
    return ParseJsonObject(response.body, maximum_response_bytes, &value) &&
           RequiredString(value, "verdict", &verdict) &&
           (verdict == "ACCEPTED" || verdict == "DUPLICATE_IGNORED");
}

EvidenceRegistrationResult ParseEvidenceRegistration(const HttpsResponse& response,
                                                      std::size_t maximum_response_bytes,
                                                      const EvidenceRecord& evidence) {
    if ((response.status_code != 200 && response.status_code != 201) ||
        response.body.size() > maximum_response_bytes) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    JsonValue value;
    if (!ParseJsonObject(response.body, maximum_response_bytes, &value)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    std::string artifact_id;
    std::string content_digest;
    std::string upload_url;
    std::string object_key;
    std::string expires_at;
    if (!RequiredString(value, "artifactId", &artifact_id) ||
        !RequiredString(value, "contentDigest", &content_digest) ||
        !RequiredString(value, "uploadUrl", &upload_url) ||
        !RequiredString(value, "objectKey", &object_key) ||
        !RequiredString(value, "expiresAt", &expires_at) || !RequiredBoolean(value, "reusedRegistration") ||
        artifact_id != evidence.artifact_id || content_digest != evidence.content_digest ||
        !IsStrictHttpsUrl(upload_url)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    const JsonValue* required_headers = FindMember(value, "requiredUploadHeaders");
    if (required_headers == nullptr || required_headers->type != JsonType::kObject ||
        required_headers->object_value.empty()) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    std::map<std::string, std::string> headers;
    for (const auto& member : required_headers->object_value) {
        if (member.second.type != JsonType::kString ||
            !headers.emplace(member.first, member.second.string_value).second) {
            return {CoreSyncVerdict::kPermanentFailure, {}, {}};
        }
    }
    if (!IsValidEvidenceHeaders(headers, evidence)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    return {CoreSyncVerdict::kAcknowledged, upload_url, std::move(headers)};
}

std::string JournalEntryJson(const CandidateEventRecord& candidate) {
    std::string output;
    output.reserve(candidate.payload_json.size() + 256U);
    output += "{\"idempotencyKey\":\"";
    output += EscapeJson(candidate.idempotency_key);
    output += "\",\"deviceSequence\":";
    output += std::to_string(candidate.device_sequence);
    output += ",\"edgeDeviceId\":\"";
    output += EscapeJson(candidate.edge_device_id);
    output += "\",\"payloadDigest\":\"";
    output += EscapeJson(candidate.payload_digest);
    output += "\",\"payload\":";
    output += candidate.payload_json;
    output += '}';
    return output;
}

bool IsCoreOrigin(const std::string& value) {
    ParsedHttpsUrl parsed;
    return ParseStrictHttpsUrl(value, true, &parsed);
}

// Core 의 source-media 는 ``^[0-9a-f]{64}$`` 를 요구한다(접두 없음). 우리 내부
// 표기는 "sha256:" 접두라 전송 직전에만 벗긴다 — 저널에는 접두를 유지해서
// 알고리즘이 값 안에 남아 있게 한다.
std::string BareSha256Hex(const std::string& digest) {
    return IsSha256Digest(digest) ? digest.substr(7U) : std::string{};
}

bool IsValidSourceMediaClaim(const SourceMediaUploadClaim& claim) {
    return ArtifactVault::IsSafeArtifactId(claim.media_id) &&
           IsAllowedEvidenceContentType(claim.content_type) && IsValidHeaderValue(claim.content_type) &&
           IsSha256Digest(claim.content_digest) && claim.byte_count > 0U && claim.width > 0U &&
           claim.height > 0U;
}

std::string SourceMediaBatchJson(const SourceMediaUploadClaim& claim) {
    std::string output = "{\"files\":[{\"mediaId\":\"";
    output += EscapeJson(claim.media_id);
    output += "\",\"sha256\":\"";
    output += BareSha256Hex(claim.content_digest);
    output += "\",\"bytes\":";
    output += std::to_string(claim.byte_count);
    output += ",\"width\":";
    output += std::to_string(claim.width);
    output += ",\"height\":";
    output += std::to_string(claim.height);
    output += ",\"contentType\":\"";
    output += EscapeJson(claim.content_type);
    output += "\"}]}";
    return output;
}

// 한 요청에 한 장만 싣는다. Core 는 200장까지 받지만, 배치 응답은 항목마다
// 판정이 갈리므로 장당 상태기계에 그대로 대응시키려면 1:1 이 맞다 — 부분 성공을
// 한 덩어리로 뭉개면 "무엇이 올라갔는가"가 저널과 어긋난다. 처리량이 문제로
// 드러나면 FIELD-0b U7 실측 뒤에 배치를 키운다.
SourceMediaRegistrationResult ParseSourceMediaRegistration(const HttpsResponse& response,
                                                           std::size_t maximum_response_bytes,
                                                           const SourceMediaUploadClaim& claim) {
    if (response.status_code != 201 || response.body.size() > maximum_response_bytes) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    JsonValue value;
    std::string batch_verdict;
    if (!ParseJsonObject(response.body, maximum_response_bytes, &value) ||
        !RequiredString(value, "verdict", &batch_verdict) || batch_verdict != "PROCESSED") {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    const JsonValue* results = FindMember(value, "results");
    if (results == nullptr || results->type != JsonType::kArray || results->array_value.size() != 1U) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    const JsonValue& item = results->array_value.front();
    std::string media_id;
    std::string item_verdict;
    if (!RequiredString(item, "mediaId", &media_id) || media_id != claim.media_id ||
        !RequiredString(item, "verdict", &item_verdict)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    if (item_verdict != "REGISTERED") {
        // STORAGE_UNAVAILABLE·JOURNAL_UNAVAILABLE 은 같은 신고값으로 다시 부르면
        // 멱등 재발급된다. CLAIM_CONFLICT·INVALID_MEDIA_ID 는 재시도로 풀리지
        // 않는다 — 그 구분을 여기서 유지해야 배출 루프가 헛돌지 않는다.
        return {item_verdict == "STORAGE_UNAVAILABLE" || item_verdict == "JOURNAL_UNAVAILABLE"
                    ? CoreSyncVerdict::kRetryableFailure
                    : CoreSyncVerdict::kPermanentFailure,
                {},
                {}};
    }
    std::string upload_url;
    if (!RequiredString(item, "uploadUrl", &upload_url) || !IsStrictHttpsUrl(upload_url)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    // 헤더는 응답에서 받지 않고 우리가 신고한 값으로 만든다(헤더 파일 주석).
    return {CoreSyncVerdict::kAcknowledged, upload_url, {{"Content-Type", claim.content_type}}};
}

bool IsSourceMediaUploadHeaders(const std::map<std::string, std::string>& headers,
                                const std::string& content_type) {
    return headers.size() == 1U && headers.begin()->first == "Content-Type" &&
           headers.begin()->second == content_type;
}

}  // namespace

const char* ToString(HttpsRequestVerdict verdict) {
    switch (verdict) {
        case HttpsRequestVerdict::kCompleted:
            return "COMPLETED";
        case HttpsRequestVerdict::kRetryableFailure:
            return "RETRYABLE_FAILURE";
        case HttpsRequestVerdict::kPermanentFailure:
            return "PERMANENT_FAILURE";
    }
    return "UNKNOWN";
}

const char* ToString(PrivateBearerTokenVerdict verdict) {
    switch (verdict) {
        case PrivateBearerTokenVerdict::kLoaded:
            return "LOADED";
        case PrivateBearerTokenVerdict::kNotFound:
            return "NOT_FOUND";
        case PrivateBearerTokenVerdict::kUnsafeFile:
            return "UNSAFE_FILE";
        case PrivateBearerTokenVerdict::kTooLarge:
            return "TOO_LARGE";
        case PrivateBearerTokenVerdict::kInvalidToken:
            return "INVALID_TOKEN";
        case PrivateBearerTokenVerdict::kReadFailed:
            return "READ_FAILED";
    }
    return "UNKNOWN";
}

PrivateBearerTokenLoadResult LoadPrivateBearerTokenFile(const std::string& path,
                                                        std::size_t maximum_bytes) {
    if (path.empty() || maximum_bytes == 0U || maximum_bytes > 4096U) {
        return {PrivateBearerTokenVerdict::kUnsafeFile, {}};
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return {errno == ENOENT ? PrivateBearerTokenVerdict::kNotFound
                                : PrivateBearerTokenVerdict::kReadFailed,
                {}};
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_nlink != 1 || before.st_size < 0 ||
        static_cast<std::uintmax_t>(before.st_size) > maximum_bytes + 2U) {
        return {static_cast<std::uintmax_t>(before.st_size) > maximum_bytes + 2U
                    ? PrivateBearerTokenVerdict::kTooLarge
                    : PrivateBearerTokenVerdict::kUnsafeFile,
                {}};
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return {errno == ENOENT ? PrivateBearerTokenVerdict::kNotFound
                                : PrivateBearerTokenVerdict::kReadFailed,
                {}};
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_nlink == 1 &&
                           opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(descriptor);
        return {PrivateBearerTokenVerdict::kUnsafeFile, {}};
    }
    std::string token;
    token.resize(static_cast<std::size_t>(opened.st_size));
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < token.size()) {
        const ssize_t received = read(descriptor, token.data() + offset, token.size() - offset);
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
    struct stat after {};
    const bool unchanged = fstat(descriptor, &after) == 0 && after.st_dev == opened.st_dev &&
                           after.st_ino == opened.st_ino && after.st_size == opened.st_size &&
                           after.st_uid == opened.st_uid && (after.st_mode & 0077) == 0 &&
                           after.st_nlink == 1;
    const bool close_ok = close(descriptor) == 0;
    if (!read_ok || !unchanged || !close_ok || offset != token.size()) {
        return {PrivateBearerTokenVerdict::kReadFailed, {}};
    }
    if (!token.empty() && token.back() == '\n') {
        token.pop_back();
        if (!token.empty() && token.back() == '\r') {
            token.pop_back();
        }
    }
    if (token.size() > maximum_bytes) {
        return {PrivateBearerTokenVerdict::kTooLarge, {}};
    }
    if (!IsValidBearerToken(token)) {
        return {PrivateBearerTokenVerdict::kInvalidToken, {}};
    }
    return {PrivateBearerTokenVerdict::kLoaded, std::move(token)};
}

bool IsStrictHttpsUrl(const std::string& url) {
    ParsedHttpsUrl parsed;
    return ParseStrictHttpsUrl(url, false, &parsed);
}

CoreRestSyncTransport::CoreRestSyncTransport(CoreRestSyncConfig config,
                                             IHttpsRequestExecutor* executor,
                                             ArtifactVault* artifact_vault)
    : config_(std::move(config)), executor_(executor), artifact_vault_(artifact_vault) {
    if (!IsCoreOrigin(config_.core_base_url) || !IsValidBearerToken(config_.bearer_token) ||
        executor_ == nullptr || artifact_vault_ == nullptr || config_.maximum_core_response_bytes == 0U ||
        config_.maximum_core_response_bytes > 1024U * 1024U ||
        config_.maximum_candidate_payload_bytes == 0U ||
        config_.maximum_candidate_payload_bytes > 8U * 1024U * 1024U) {
        throw std::invalid_argument("invalid Core REST sync transport configuration");
    }
    const bool attestation_key_id_present = !config_.evidence_attestation_key_id.empty();
    const bool attestation_path_present = !config_.evidence_attestation_private_key_path.empty();
    if (attestation_key_id_present != attestation_path_present) {
        throw std::invalid_argument("incomplete evidence attestation configuration");
    }
    if (attestation_key_id_present) {
        evidence_attestation_signer_ = std::make_unique<EvidenceAttestationSigner>(
            config_.evidence_attestation_key_id,
            config_.evidence_attestation_private_key_path);
    }
    if (config_.core_base_url.back() == '/') {
        config_.core_base_url.pop_back();
    }
}

CoreSyncVerdict CoreRestSyncTransport::UploadCandidate(const CandidateEventRecord& candidate) {
    std::string event_id;
    if (!ExtractCandidateEventId(candidate, config_.maximum_candidate_payload_bytes, &event_id)) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    const std::string body = JournalEntryJson(candidate);
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kCore;
    request.method = "POST";
    request.url = config_.core_base_url + "/v1/edge-sync/event-bundles";
    request.headers = {{"Authorization", "Bearer " + config_.bearer_token},
                       {"Content-Type", "application/json"}};
    request.body.assign(body.begin(), body.end());
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    const CoreSyncVerdict transport =
        ValidateCoreResponse(execution, response, config_.maximum_core_response_bytes);
    if (transport != CoreSyncVerdict::kAcknowledged) {
        return transport;
    }
    return IsCandidateAck(response, config_.maximum_core_response_bytes)
               ? CoreSyncVerdict::kAcknowledged
               : CoreSyncVerdict::kPermanentFailure;
}

EvidenceRegistrationResult CoreRestSyncTransport::RegisterEvidence(
    const CandidateEventRecord& candidate, const EvidenceRecord& evidence) {
    CandidateEvidenceContext context;
    if (!ExtractCandidateEvidenceContext(candidate, config_.maximum_candidate_payload_bytes,
                                         &context) ||
        evidence.event_idempotency_key != candidate.idempotency_key ||
        !ArtifactVault::IsSafeArtifactId(evidence.artifact_id) || !IsSha256Digest(evidence.content_digest) ||
        !IsAllowedEvidenceContentType(evidence.content_type) || !IsValidHeaderValue(evidence.content_type)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    const std::string event_key = candidate.edge_device_id + "::" + context.event_id;
    std::string body = "{\"artifactId\":\"" + EscapeJson(evidence.artifact_id) +
                       "\",\"contentType\":\"" + EscapeJson(evidence.content_type) +
                       "\",\"contentDigest\":\"" + EscapeJson(evidence.content_digest) + "\"";
    if (evidence_attestation_signer_ != nullptr) {
        const EvidenceAttestationResult attestation = evidence_attestation_signer_->Sign(
            candidate.edge_device_id, context.site_id, context.mission_id, event_key,
            evidence.artifact_id, evidence.content_type, evidence.content_digest);
        if (attestation.verdict != EvidenceAttestationVerdict::kSigned) {
            return {CoreSyncVerdict::kPermanentFailure, {}, {}};
        }
        body += ",\"attestation\":{\"keyId\":\"" + EscapeJson(attestation.key_id) +
                "\",\"algorithm\":\"Ed25519\",\"signature\":\"" +
                EscapeJson(attestation.signature_base64url) + "\"}";
    }
    body += '}';
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kCore;
    request.method = "POST";
    request.url = config_.core_base_url + "/v1/edge-sync/events/" +
                  PercentEncodePathSegment(event_key) + "/evidence";
    request.headers = {{"Authorization", "Bearer " + config_.bearer_token},
                       {"Content-Type", "application/json"}};
    request.body.assign(body.begin(), body.end());
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    const CoreSyncVerdict transport =
        ValidateCoreResponse(execution, response, config_.maximum_core_response_bytes);
    if (transport != CoreSyncVerdict::kAcknowledged) {
        return {transport, {}, {}};
    }
    return ParseEvidenceRegistration(response, config_.maximum_core_response_bytes, evidence);
}

CoreSyncVerdict CoreRestSyncTransport::PutEvidence(const EvidenceRecord& evidence,
                                                    const EvidenceRegistrationResult& registration) {
    if (registration.verdict != CoreSyncVerdict::kAcknowledged ||
        !IsStrictHttpsUrl(registration.upload_url) ||
        !IsValidEvidenceHeaders(registration.required_upload_headers, evidence) ||
        !ArtifactVault::IsSafeArtifactId(evidence.artifact_id) || evidence.local_path.empty()) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    std::vector<std::uint8_t> bytes;
    const ArtifactVaultResult read = artifact_vault_->ReadAndVerifyDigest(
        evidence.artifact_id, evidence.local_path, evidence.content_digest, &bytes);
    if (read.verdict != ArtifactVaultVerdict::kPersisted) {
        return read.verdict == ArtifactVaultVerdict::kStorageError
                   ? CoreSyncVerdict::kRetryableFailure
                   : CoreSyncVerdict::kPermanentFailure;
    }
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kEvidenceUpload;
    request.method = "PUT";
    request.url = registration.upload_url;
    request.headers = registration.required_upload_headers;
    request.body = std::move(bytes);
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    if (execution != HttpsRequestVerdict::kCompleted) {
        return MapExecutorVerdict(execution);
    }
    if (response.body.size() > config_.maximum_core_response_bytes) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    if (response.status_code >= 200 && response.status_code < 300) {
        return CoreSyncVerdict::kAcknowledged;
    }
    // A just-issued presigned URL can expire between registration and PUT or
    // be invalidated by a transient storage-side policy.  Retrying causes the
    // driver to re-register for a fresh capability; no bytes are deleted.
    if (response.status_code == 401 || response.status_code == 403 || IsRetryableStatus(response.status_code)) {
        return CoreSyncVerdict::kRetryableFailure;
    }
    return CoreSyncVerdict::kPermanentFailure;
}

CoreRestSourceMediaTransport::CoreRestSourceMediaTransport(CoreRestSourceMediaConfig config,
                                                           IHttpsRequestExecutor* executor,
                                                           ArtifactVault* spool)
    : config_(std::move(config)), executor_(executor), spool_(spool) {
    if (!IsCoreOrigin(config_.core_base_url) || !IsValidBearerToken(config_.bearer_token) ||
        executor_ == nullptr || spool_ == nullptr || config_.maximum_core_response_bytes == 0U ||
        config_.maximum_core_response_bytes > 1024U * 1024U) {
        throw std::invalid_argument("invalid Core REST source media transport configuration");
    }
    if (config_.core_base_url.back() == '/') {
        config_.core_base_url.pop_back();
    }
}

SourceMediaRegistrationResult CoreRestSourceMediaTransport::RegisterSourceMedia(
    const std::string& mission_id, const SourceMediaUploadClaim& claim) {
    if (!IsPathSafeIdentifier(mission_id) || !IsValidSourceMediaClaim(claim)) {
        return {CoreSyncVerdict::kPermanentFailure, {}, {}};
    }
    const std::string body = SourceMediaBatchJson(claim);
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kCore;
    request.method = "POST";
    request.url = config_.core_base_url + "/v1/missions/" + PercentEncodePathSegment(mission_id) +
                  "/source-media";
    request.headers = {{"Authorization", "Bearer " + config_.bearer_token},
                       {"Content-Type", "application/json"}};
    request.body.assign(body.begin(), body.end());
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    const CoreSyncVerdict transport =
        ValidateCoreResponse(execution, response, config_.maximum_core_response_bytes);
    if (transport != CoreSyncVerdict::kAcknowledged) {
        return {transport, {}, {}};
    }
    // 401(토큰 만료·회전)·403(권한 철회)·404(Core 가 아직 이 임무를 모름)는 요청
    // 자체가 구조적으로 잘못된 것이 아니다 — 외부 상태가 바뀌면(토큰 재발급,
    // Core 쪽 임무 등록 반영) 다음 시도에서 풀릴 수 있다. PutSourceMedia 가
    // 401/403 을 retryable 로 다루는 것과 같은 기준이다("어떤 경우에도 바이트를
    // 지우지 않는다"). 여기서 걸러야 ParseSourceMediaRegistration 의 "201 아니면
    // 전부 영구 실패" 판정에 섞여 PushItem 이 스풀 사본을 지우고 QUARANTINED 로
    // 보내는 일이 없다.
    if (response.status_code == 401 || response.status_code == 403 || response.status_code == 404) {
        return {CoreSyncVerdict::kRetryableFailure, {}, {}};
    }
    return ParseSourceMediaRegistration(response, config_.maximum_core_response_bytes, claim);
}

CoreSyncVerdict CoreRestSourceMediaTransport::PutSourceMedia(
    const SourceMediaItemRecord& item, const SourceMediaRegistrationResult& registration) {
    if (registration.verdict != CoreSyncVerdict::kAcknowledged ||
        !IsStrictHttpsUrl(registration.upload_url) ||
        !IsSourceMediaUploadHeaders(registration.required_upload_headers, item.content_type) ||
        !ArtifactVault::IsSafeArtifactId(item.artifact_id) || item.local_path.empty()) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    // 스풀 바이트를 digest 로 다시 확인하고 올린다. 다운로드 직후에 이미 쟀지만,
    // 그 사이에 재기동이 끼면 "저널이 말하는 그 파일"임을 다시 확인해야 한다.
    std::vector<std::uint8_t> bytes;
    const ArtifactVaultResult read = spool_->ReadAndVerifyDigest(item.artifact_id, item.local_path,
                                                                 item.content_digest, &bytes);
    if (read.verdict != ArtifactVaultVerdict::kPersisted) {
        return read.verdict == ArtifactVaultVerdict::kStorageError ? CoreSyncVerdict::kRetryableFailure
                                                                   : CoreSyncVerdict::kPermanentFailure;
    }
    if (bytes.size() != item.byte_count) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kEvidenceUpload;
    request.method = "PUT";
    request.url = registration.upload_url;
    request.headers = registration.required_upload_headers;
    request.body = std::move(bytes);
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    if (execution != HttpsRequestVerdict::kCompleted) {
        return MapExecutorVerdict(execution);
    }
    if (response.body.size() > config_.maximum_core_response_bytes) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    if (response.status_code >= 200 && response.status_code < 300) {
        return CoreSyncVerdict::kAcknowledged;
    }
    // 갓 발급된 presigned URL 도 만료·정책으로 거부될 수 있다. 재시도하면 배출
    // 루프가 재등록해 새 권한을 받는다 — 어떤 경우에도 바이트를 지우지 않는다.
    if (response.status_code == 401 || response.status_code == 403 ||
        IsRetryableStatus(response.status_code)) {
        return CoreSyncVerdict::kRetryableFailure;
    }
    return CoreSyncVerdict::kPermanentFailure;
}

CoreSyncVerdict CoreRestSourceMediaTransport::SealSourceMedia(const std::string& mission_id) {
    if (!IsPathSafeIdentifier(mission_id)) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    HttpsRequest request;
    request.endpoint = HttpsEndpoint::kCore;
    request.method = "POST";
    request.url = config_.core_base_url + "/v1/missions/" + PercentEncodePathSegment(mission_id) +
                  "/source-media/seal";
    request.headers = {{"Authorization", "Bearer " + config_.bearer_token}};
    request.maximum_response_bytes = config_.maximum_core_response_bytes;
    HttpsResponse response;
    const HttpsRequestVerdict execution = executor_->Execute(request, &response);
    const CoreSyncVerdict transport =
        ValidateCoreResponse(execution, response, config_.maximum_core_response_bytes);
    if (transport != CoreSyncVerdict::kAcknowledged) {
        return transport;
    }
    if (response.status_code != 200 && response.status_code != 201) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    JsonValue value;
    std::string verdict;
    if (!ParseJsonObject(response.body, config_.maximum_core_response_bytes, &value) ||
        !RequiredString(value, "verdict", &verdict)) {
        return CoreSyncVerdict::kPermanentFailure;
    }
    // ALREADY_SEALED 도 성공이다 — 재기동이 봉인 직후에 끼었다는 뜻이지, 우리가
    // 잘못 불렀다는 뜻이 아니다.
    return verdict == "SEALED" || verdict == "ALREADY_SEALED" ? CoreSyncVerdict::kAcknowledged
                                                              : CoreSyncVerdict::kPermanentFailure;
}

}  // namespace ksi::edge

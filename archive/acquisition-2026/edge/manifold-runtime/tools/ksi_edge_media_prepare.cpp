// Creates one private request for an M4D source-media baseline.
//
// This utility has no PSDK symbols and does not list, download, delete, format,
// capture, gimbal, motor, or fly.  The active DPK later reads the request and
// may perform a read-only Camera Manager list only before activation.

#include "ksi/edge/media_control.hpp"

#include <cerrno>
#include <charconv>
#include <cstdio>
#include <ctime>
#include <map>
#include <string>
#include <utility>

#include <fcntl.h>
#include <unistd.h>

namespace {

constexpr char kToolVersion[] = "ksi-edge-media-prepare-v1";

void PrintUsage(const char* executable) {
    std::fprintf(stderr,
                 "usage: %s --state-dir PATH --operator ID --edge-device-id ID --mission-id ID "
                 "--dispatch-id ID --mission-contract-digest sha256:<hex> --ttl-ms N "
                 "[--now-utc-ms N]\n"
                 "       %s --version\n",
                 executable, executable);
}

bool ParseNonnegative(const std::string& input, std::int64_t maximum, std::int64_t* output) {
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
    if (error != std::errc{} || end != input.data() + input.size() || value < 0 || value > maximum) {
        return false;
    }
    *output = value;
    return true;
}

bool GenerateNonce(std::string* nonce) {
    if (nonce == nullptr) {
        return false;
    }
    const int descriptor = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (descriptor < 0) {
        return false;
    }
    unsigned char bytes[16] = {};
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < sizeof(bytes)) {
        const ssize_t received = read(descriptor, bytes + offset, sizeof(bytes) - offset);
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
    (void)close(descriptor);
    if (!read_ok) {
        return false;
    }
    static constexpr char kHex[] = "0123456789abcdef";
    std::string output;
    output.reserve(sizeof(bytes) * 2U);
    for (const unsigned char byte : bytes) {
        output.push_back(kHex[(byte >> 4U) & 0x0FU]);
        output.push_back(kHex[byte & 0x0FU]);
    }
    *nonce = std::move(output);
    return true;
}

std::int64_t RealtimeNowUtcMs() {
    timespec value {};
    if (clock_gettime(CLOCK_REALTIME, &value) != 0 || value.tv_sec < 0 || value.tv_nsec < 0) {
        return -1;
    }
    return static_cast<std::int64_t>(value.tv_sec) * 1000LL +
           static_cast<std::int64_t>(value.tv_nsec) / 1'000'000LL;
}

struct Options {
    std::string state_directory;
    std::string operator_id;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;
    std::int64_t ttl_ms = 0;
    std::int64_t now_utc_ms = -1;
};

bool ParseOptions(int argc, char** argv, Options* output) {
    if (output == nullptr) {
        return false;
    }
    std::map<std::string, std::string> fields;
    for (int index = 1; index < argc; ++index) {
        const std::string option(argv[index]);
        if (index + 1 >= argc) {
            return false;
        }
        const std::string value(argv[++index]);
        const bool known = option == "--state-dir" || option == "--operator" ||
                           option == "--edge-device-id" || option == "--mission-id" ||
                           option == "--dispatch-id" || option == "--mission-contract-digest" ||
                           option == "--ttl-ms" || option == "--now-utc-ms";
        if (!known || value.empty() || !fields.emplace(option, value).second) {
            return false;
        }
    }
    constexpr const char* required[] = {"--state-dir", "--operator", "--edge-device-id", "--mission-id",
                                        "--dispatch-id", "--mission-contract-digest", "--ttl-ms"};
    for (const char* field : required) {
        if (fields.find(field) == fields.end()) {
            return false;
        }
    }
    Options result;
    result.state_directory = fields.at("--state-dir");
    result.operator_id = fields.at("--operator");
    result.edge_device_id = fields.at("--edge-device-id");
    result.mission_id = fields.at("--mission-id");
    result.dispatch_id = fields.at("--dispatch-id");
    result.mission_contract_digest = fields.at("--mission-contract-digest");
    if (!ParseNonnegative(fields.at("--ttl-ms"), ksi::edge::kMaximumMediaControlTtlMs,
                          &result.ttl_ms) ||
        result.ttl_ms <= 0) {
        return false;
    }
    if (fields.count("--now-utc-ms") != 0U &&
        !ParseNonnegative(fields.at("--now-utc-ms"), 4'102'444'800'000LL, &result.now_utc_ms)) {
        return false;
    }
    *output = std::move(result);
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--version") {
        std::printf("%s\n", kToolVersion);
        return 0;
    }
    Options options;
    if (!ParseOptions(argc, argv, &options)) {
        PrintUsage(argv[0]);
        return 2;
    }
    const std::int64_t now_utc_ms =
        options.now_utc_ms >= 0 ? options.now_utc_ms : RealtimeNowUtcMs();
    if (now_utc_ms < 0 || now_utc_ms > 4'102'444'800'000LL - options.ttl_ms) {
        std::fputs("[ksi-edge-media-prepare] clock unavailable or expiry overflow\n", stderr);
        return 1;
    }
    std::string nonce;
    if (!GenerateNonce(&nonce)) {
        std::fputs("[ksi-edge-media-prepare] secure nonce unavailable\n", stderr);
        return 1;
    }
    ksi::edge::MediaBaselineRequest request;
    request.operator_id = std::move(options.operator_id);
    request.nonce = std::move(nonce);
    request.edge_device_id = std::move(options.edge_device_id);
    request.mission_id = std::move(options.mission_id);
    request.dispatch_id = std::move(options.dispatch_id);
    request.mission_contract_digest = std::move(options.mission_contract_digest);
    request.requested_at_utc_ms = now_utc_ms;
    request.expires_at_utc_ms = now_utc_ms + options.ttl_ms;
    const ksi::edge::MediaControlWriteVerdict verdict =
        ksi::edge::WriteMediaBaselineRequest(options.state_directory, request);
    std::printf("%s\n", ksi::edge::ToString(verdict));
    return verdict == ksi::edge::MediaControlWriteVerdict::kWritten ? 0 : 1;
}

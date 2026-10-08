// Creates an explicit, short-lived operator approval for source-media egress.
//
// It does not touch DJI APIs.  Instead it reads the already-verified native
// activation and the DPK-created pre-activation baseline, verifies their exact
// binding, and writes a private one-shot trigger for the DPK worker.

#include "ksi/edge/activation.hpp"
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

constexpr char kToolVersion[] = "ksi-edge-media-trigger-v1";

void PrintUsage(const char* executable) {
    std::fprintf(stderr,
                 "usage: %s --activation-state-dir PATH --control-state-dir PATH --operator ID "
                 "--edge-device-id ID --runtime-version VERSION --ttl-ms N [--now-utc-ms N]\n"
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
    std::string activation_state_directory;
    std::string control_state_directory;
    std::string operator_id;
    std::string edge_device_id;
    std::string runtime_version;
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
        const bool known = option == "--activation-state-dir" || option == "--control-state-dir" ||
                           option == "--operator" || option == "--edge-device-id" ||
                           option == "--runtime-version" || option == "--ttl-ms" ||
                           option == "--now-utc-ms";
        if (!known || value.empty() || !fields.emplace(option, value).second) {
            return false;
        }
    }
    constexpr const char* required[] = {"--activation-state-dir", "--control-state-dir", "--operator",
                                        "--edge-device-id", "--runtime-version", "--ttl-ms"};
    for (const char* field : required) {
        if (fields.find(field) == fields.end()) {
            return false;
        }
    }
    Options result;
    result.activation_state_directory = fields.at("--activation-state-dir");
    result.control_state_directory = fields.at("--control-state-dir");
    result.operator_id = fields.at("--operator");
    result.edge_device_id = fields.at("--edge-device-id");
    result.runtime_version = fields.at("--runtime-version");
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
    if (now_utc_ms < 0 || now_utc_ms > 4'102'444'800'000'000LL / 1000LL - options.ttl_ms) {
        std::fputs("[ksi-edge-media-trigger] clock unavailable or expiry overflow\n", stderr);
        return 1;
    }
    const ksi::edge::NativeActivationLoadResult activation = ksi::edge::LoadNativeActivationSnapshot(
        options.activation_state_directory, options.edge_device_id, options.runtime_version, now_utc_ms);
    if (activation.verdict != ksi::edge::NativeActivationVerdict::kLoaded) {
        std::printf("ACTIVATION_%s\n", ksi::edge::ToString(activation.verdict));
        return 1;
    }
    const ksi::edge::MediaBaselineRecordLoadResult baseline =
        ksi::edge::LoadMediaBaselineRecord(options.control_state_directory);
    if (baseline.verdict != ksi::edge::MediaControlLoadVerdict::kLoaded) {
        std::printf("BASELINE_%s\n", ksi::edge::ToString(baseline.verdict));
        return 1;
    }
    std::string nonce;
    if (!GenerateNonce(&nonce)) {
        std::fputs("[ksi-edge-media-trigger] secure nonce unavailable\n", stderr);
        return 1;
    }
    ksi::edge::OperatorMediaOffloadTrigger trigger;
    trigger.operator_id = std::move(options.operator_id);
    trigger.nonce = std::move(nonce);
    trigger.edge_device_id = activation.snapshot.edge_device_id;
    trigger.mission_id = activation.snapshot.mission_id;
    trigger.dispatch_id = activation.snapshot.dispatch_id;
    trigger.mission_contract_digest = activation.snapshot.context.mission_contract_digest;
    trigger.baseline_digest = ksi::edge::ComputeMediaBaselineRecordDigest(baseline.record);
    trigger.issued_at_utc_ms = now_utc_ms;
    trigger.expires_at_utc_ms = now_utc_ms + options.ttl_ms;
    const ksi::edge::MediaControlSelectionResult selection =
        ksi::edge::BuildOperatorMediaSelectionContext(activation.snapshot, baseline.record, trigger,
                                                       now_utc_ms);
    if (selection.verdict != ksi::edge::MediaControlSelectionVerdict::kReady) {
        std::printf("SELECTION_%s\n", ksi::edge::ToString(selection.verdict));
        return 1;
    }
    const ksi::edge::MediaControlWriteVerdict written =
        ksi::edge::WriteOperatorMediaOffloadTrigger(options.control_state_directory, trigger);
    std::printf("%s\n", ksi::edge::ToString(written));
    return written == ksi::edge::MediaControlWriteVerdict::kWritten ? 0 : 1;
}

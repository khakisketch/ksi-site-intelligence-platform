// ADR-KSI-021 §2/§5[3] — 현장 arming CLI.
//
// C++ 인 이유: 매니폴드 Python 은 3.8.10 이고 우리 도구는 3.12 문법이며 관리자
// 권한이 없다(risk mission-dispatch-cli-python312-runtime-provisioning-undecided,
// open) — 안전 경로를 3.12 컴패니언 가용성에 걸면 필요한 순간에 없다.
//
// 이 CLI 는 nonce 를 생성해 사설 arming 토큰 파일을 원자적으로 쓸 뿐이다.
// 그 nonce 를 소비(=1회 시도 확정)하는 것은 flight_execution.hpp 의
// ConsumeFieldArmingToken 이지 이 CLI 가 아니다 — 이 CLI 를 두 번 부르면
// 이전 nonce 를 덮어써 새 arming 이 되고(파일 하나뿐이라 "여러 토큰 대기"는
// 없다), 이미 소비된 이전 nonce 를 되살리지 않는다.

#include "ksi/edge/flight_execution.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <map>
#include <string>
#include <utility>

#include <fcntl.h>
#include <unistd.h>

namespace {

constexpr char kToolVersion[] = "ksi-edge-flight-arm-v1";

void PrintUsage(const char* executable) {
    std::fprintf(stderr,
                 "usage: %s --state-dir PATH --issuer NAME --stage 0..4 "
                 "--edge-device-id ID --mission-id ID --dispatch-id ID --ttl-ms N "
                 "[--now-utc-ms N]\n"
                 "       %s --version\n",
                 executable, executable);
}

// /dev/urandom 에서 16바이트를 읽어 32자 hex 로 인코딩한다 — PSDK 심볼 없이
// 이 프로세스 안에서 끝나는 로컬 CSPRNG 소비다.
bool GenerateNonceHex(std::string* nonce) {
    if (nonce == nullptr) {
        return false;
    }
    const int descriptor = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (descriptor < 0) {
        return false;
    }
    unsigned char bytes[16];
    std::size_t offset = 0U;
    bool ok = true;
    while (offset < sizeof(bytes)) {
        const ssize_t received = read(descriptor, bytes + offset, sizeof(bytes) - offset);
        if (received > 0) {
            offset += static_cast<std::size_t>(received);
            continue;
        }
        if (received < 0 && errno == EINTR) {
            continue;
        }
        ok = false;
        break;
    }
    (void)close(descriptor);
    if (!ok) {
        return false;
    }
    static constexpr char kHex[] = "0123456789abcdef";
    std::string hex;
    hex.reserve(sizeof(bytes) * 2U);
    for (const unsigned char byte_value : bytes) {
        hex.push_back(kHex[(byte_value >> 4U) & 0x0FU]);
        hex.push_back(kHex[byte_value & 0x0FU]);
    }
    *nonce = std::move(hex);
    return true;
}

bool ParseNonnegative(const std::string& value, std::int64_t maximum, std::int64_t* output) {
    if (output == nullptr || value.empty()) {
        return false;
    }
    for (const char character : value) {
        if (character < '0' || character > '9') {
            return false;
        }
    }
    std::int64_t parsed = 0;
    for (const char character : value) {
        if (parsed > (maximum - (character - '0')) / 10) {
            return false;
        }
        parsed = parsed * 10 + (character - '0');
    }
    *output = parsed;
    return true;
}

std::int64_t RealtimeNowUtcMs() {
    timespec value{};
    if (clock_gettime(CLOCK_REALTIME, &value) != 0 || value.tv_sec < 0) {
        return -1;
    }
    return static_cast<std::int64_t>(value.tv_sec) * 1000LL +
          static_cast<std::int64_t>(value.tv_nsec) / 1000000LL;
}

struct Options {
    std::string state_directory;
    std::string issuer;
    ksi::edge::FlightExecutionStage stage = ksi::edge::FlightExecutionStage::kS0;
    std::string edge_device_id;
    std::string mission_id;
    std::string dispatch_id;
    std::int64_t ttl_ms = 0;
    std::int64_t now_utc_ms = -1;  // -1 이면 실시간 시계를 쓴다.
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
        const bool known = option == "--state-dir" || option == "--issuer" || option == "--stage" ||
                           option == "--edge-device-id" || option == "--mission-id" ||
                           option == "--dispatch-id" || option == "--ttl-ms" ||
                           option == "--now-utc-ms";
        if (!known || value.empty() || !fields.emplace(option, value).second) {
            return false;
        }
    }
    constexpr const char* kRequired[] = {
        "--state-dir", "--issuer",     "--stage",       "--edge-device-id",
        "--mission-id", "--dispatch-id", "--ttl-ms",
    };
    for (const char* required : kRequired) {
        if (fields.find(required) == fields.end()) {
            return false;
        }
    }
    Options result;
    result.state_directory = fields.at("--state-dir");
    result.issuer = fields.at("--issuer");
    result.edge_device_id = fields.at("--edge-device-id");
    result.mission_id = fields.at("--mission-id");
    result.dispatch_id = fields.at("--dispatch-id");
    std::int64_t stage_value = 0;
    if (!ParseNonnegative(fields.at("--stage"), 4, &stage_value) ||
        !ParseNonnegative(fields.at("--ttl-ms"), ksi::edge::kMaximumArmingTokenTtlMs,
                          &result.ttl_ms) ||
        result.ttl_ms <= 0) {
        return false;
    }
    result.stage = static_cast<ksi::edge::FlightExecutionStage>(stage_value);
    if (fields.count("--now-utc-ms") != 0U &&
        !ParseNonnegative(fields.at("--now-utc-ms"), 4102444800000LL, &result.now_utc_ms)) {
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
    const std::int64_t issued_at_utc_ms =
        options.now_utc_ms >= 0 ? options.now_utc_ms : RealtimeNowUtcMs();
    if (issued_at_utc_ms < 0) {
        std::fprintf(stderr, "[ksi-edge-flight-arm] system clock unavailable\n");
        return 1;
    }
    std::string nonce;
    if (!GenerateNonceHex(&nonce)) {
        std::fprintf(stderr, "[ksi-edge-flight-arm] failed to read a nonce from /dev/urandom\n");
        return 1;
    }
    ksi::edge::FieldArmingToken token;
    token.nonce = nonce;
    token.issuer = options.issuer;
    token.stage = options.stage;
    token.edge_device_id = options.edge_device_id;
    token.mission_id = options.mission_id;
    token.dispatch_id = options.dispatch_id;
    token.issued_at_utc_ms = issued_at_utc_ms;
    token.expires_at_utc_ms = issued_at_utc_ms + options.ttl_ms;
    const ksi::edge::ArmingTokenWriteVerdict verdict =
        ksi::edge::WriteFieldArmingToken(options.state_directory, token);
    std::printf("%s\n", ksi::edge::ToString(verdict));
    if (verdict != ksi::edge::ArmingTokenWriteVerdict::kWritten) {
        return 1;
    }
    std::fprintf(stderr,
                 "[ksi-edge-flight-arm] armed stage=%s mission=%s dispatch=%s expiresAtUtcMs=%lld\n",
                 ksi::edge::ToString(options.stage), options.mission_id.c_str(),
                 options.dispatch_id.c_str(), static_cast<long long>(token.expires_at_utc_ms));
    return 0;
}

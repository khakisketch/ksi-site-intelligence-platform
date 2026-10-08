// ADR-KSI-021 §8 — abort 요청 CLI.
//
// 이 CLI 는 watchdog 이 관찰할 사설 상태파일에 abort 요청을 즉시 기록할
// 뿐이다. 5Hz 폴링 관찰자·실제 Action(STOP) 발행은 이번 라운드 범위 밖이다
// (ADR 명시) — 여기서 확정하는 것은 파일 프로토콜 자체와 그 왕복 뿐이다.
//
// C++ 인 이유는 ksi_edge_flight_arm.cpp 와 같다(매니폴드 Python 3.8.10 vs
// 3.12 문법 — risk mission-dispatch-cli-python312-runtime-provisioning-undecided).

#include "ksi/edge/flight_execution.hpp"

#include <cstdio>
#include <cstring>
#include <ctime>
#include <map>
#include <string>
#include <utility>

namespace {

constexpr char kToolVersion[] = "ksi-edge-flight-abort-v1";

void PrintUsage(const char* executable) {
    std::fprintf(stderr,
                 "usage: %s --state-dir PATH --requested-by NAME --reason TEXT "
                 "[--mission-id ID] [--dispatch-id ID] [--now-utc-ms N]\n"
                 "       %s --version\n",
                 executable, executable);
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
    std::string requested_by;
    std::string reason;
    std::string mission_id;
    std::string dispatch_id;
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
        const bool known = option == "--state-dir" || option == "--requested-by" ||
                           option == "--reason" || option == "--mission-id" ||
                           option == "--dispatch-id" || option == "--now-utc-ms";
        if (!known || value.empty() || !fields.emplace(option, value).second) {
            return false;
        }
    }
    constexpr const char* kRequired[] = {"--state-dir", "--requested-by", "--reason"};
    for (const char* required : kRequired) {
        if (fields.find(required) == fields.end()) {
            return false;
        }
    }
    Options result;
    result.state_directory = fields.at("--state-dir");
    result.requested_by = fields.at("--requested-by");
    result.reason = fields.at("--reason");
    if (fields.count("--mission-id") != 0U) {
        result.mission_id = fields.at("--mission-id");
    }
    if (fields.count("--dispatch-id") != 0U) {
        result.dispatch_id = fields.at("--dispatch-id");
    }
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
    const std::int64_t requested_at_utc_ms =
        options.now_utc_ms >= 0 ? options.now_utc_ms : RealtimeNowUtcMs();
    if (requested_at_utc_ms < 0) {
        std::fprintf(stderr, "[ksi-edge-flight-abort] system clock unavailable\n");
        return 1;
    }
    ksi::edge::AbortRequestRecord record;
    record.requested_by = options.requested_by;
    record.reason = options.reason;
    record.requested_at_utc_ms = requested_at_utc_ms;
    record.mission_id = options.mission_id;
    record.dispatch_id = options.dispatch_id;
    const ksi::edge::AbortRequestWriteVerdict verdict =
        ksi::edge::WriteAbortRequest(options.state_directory, record);
    std::printf("%s\n", ksi::edge::ToString(verdict));
    if (verdict != ksi::edge::AbortRequestWriteVerdict::kWritten) {
        return 1;
    }
    std::fprintf(stderr, "[ksi-edge-flight-abort] abort request recorded — this process does not poll for or issue Action(STOP) itself (ADR-KSI-021 §8, this round)\n");
    return 0;
}

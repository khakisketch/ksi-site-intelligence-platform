// Offline TensorRT side of the D-FINE semantic differential gate.
//
// This is deliberately a host/HIL helper, not a PSDK callback or a CPU
// fallback.  Python owns corpus and ONNX-oracle validation, then supplies a
// private, exact raw-RGB sample list.  This process uses the same native
// TensorRT adapter as the DPK, emits only deterministic postprocess results,
// and exits non-zero for every build/load/inference failure.

#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/crypto.hpp"
#include "ksi/edge/dfine.hpp"
#include "ksi/edge/runtime_profile.hpp"
#include "ksi/edge/tensorrt.hpp"

namespace {

constexpr char kRunnerVersion[] = "ksi-tensorrt-dfine-runner-v1";
constexpr char kSampleMagic[] = "KSI_TENSORRT_RAW_RGB_SAMPLES_V1";
constexpr std::size_t kMaximumSampleListBytes = 2U * 1024U * 1024U;
constexpr std::size_t kMaximumRgbBytes = 512U * 1024U * 1024U;

struct RawSample {
    std::string sample_id;
    std::uint32_t width = 0U;
    std::uint32_t height = 0U;
    std::string rgb_path;
    std::string rgb_digest;
};

struct Options {
    std::string onnx_path;
    std::string registered_onnx_digest;
    std::string engine_artifact_id;
    std::string engine_vault_directory;
    std::string sample_list_path;
    std::size_t max_onnx_bytes = 0U;
    std::size_t max_engine_bytes = 0U;
    std::size_t workspace_bytes = 0U;
    ksi::edge::TensorRtDfineTensorContract tensor_contract;
    float score_threshold = 0.0F;
    std::size_t top_k = 0U;
    std::map<std::uint32_t, std::string> taxonomy;
};

void PrintUsage(const char* executable) {
    std::fprintf(
        stderr,
        "usage: %s --onnx PATH --registered-onnx-digest sha256:... "
        "--engine-artifact-id ID --engine-vault-dir PATH --max-onnx-bytes N "
        "--max-engine-bytes N --workspace-bytes N --input-width N --input-height N "
        "--query-count N --class-count N --score-threshold F --top-k N "
        "--class-binding CLASS_ID:BASE64URL_NAME [--class-binding ...] "
        "--samples PATH\n",
        executable);
}

bool ParseUnsigned(const std::string& value, std::size_t maximum, std::size_t* output) {
    if (output == nullptr || value.empty()) return false;
    for (const char character : value) {
        if (character < '0' || character > '9') return false;
    }
    std::size_t parsed = 0U;
    const auto [end, error] =
        std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (error != std::errc{} || end != value.data() + value.size() || parsed > maximum) {
        return false;
    }
    *output = parsed;
    return true;
}

bool ParsePositive(const std::string& value, std::size_t maximum, std::size_t* output) {
    return ParseUnsigned(value, maximum, output) && *output > 0U;
}

bool ParseFiniteFloat(const std::string& value, float* output) {
    if (output == nullptr || value.empty()) return false;
    try {
        std::size_t consumed = 0U;
        const float parsed = std::stof(value, &consumed);
        if (consumed != value.size() || !std::isfinite(parsed)) return false;
        *output = parsed;
        return true;
    } catch (...) {
        return false;
    }
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
        const int digit = DecodeCharacter(character);
        if (digit < 0) return false;
        accumulator = (accumulator << 6U) | static_cast<std::uint32_t>(digit);
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

bool ReadOwnedRegularFile(const std::string& path, std::size_t maximum_size,
                          std::vector<std::uint8_t>* output) {
    if (path.empty() || output == nullptr || maximum_size == 0U) return false;
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0 || !S_ISREG(before.st_mode) ||
        S_ISLNK(before.st_mode) || before.st_uid != geteuid() || before.st_nlink != 1 ||
        before.st_size < 0 || static_cast<std::uintmax_t>(before.st_size) > maximum_size) {
        return false;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) return false;
    struct stat opened {};
    const bool same_file =
        fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
        opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) && !S_ISLNK(opened.st_mode) &&
        opened.st_uid == geteuid() && opened.st_nlink == 1 && opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(descriptor);
        return false;
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(opened.st_size));
    std::size_t offset = 0U;
    bool success = true;
    while (offset < bytes.size()) {
        const ssize_t received = read(descriptor, bytes.data() + offset, bytes.size() - offset);
        if (received > 0) {
            offset += static_cast<std::size_t>(received);
            continue;
        }
        if (received < 0 && errno == EINTR) continue;
        success = false;
        break;
    }
    const bool closed = close(descriptor) == 0;
    if (!success || !closed || offset != bytes.size()) return false;
    *output = std::move(bytes);
    return true;
}

bool ParseClassBinding(const std::string& value, std::map<std::uint32_t, std::string>* output) {
    if (output == nullptr) return false;
    const std::size_t separator = value.find(':');
    if (separator == std::string::npos || separator == 0U ||
        value.find(':', separator + 1U) != std::string::npos) {
        return false;
    }
    std::size_t class_id = 0U;
    std::string class_name;
    if (!ParseUnsigned(value.substr(0U, separator),
                       static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max()),
                       &class_id) ||
        !DecodeBase64Url(value.substr(separator + 1U), &class_name) || !IsSafeText(class_name)) {
        return false;
    }
    return output->emplace(static_cast<std::uint32_t>(class_id), std::move(class_name)).second;
}

bool ParseOptions(int argc, char** argv, Options* output) {
    if (output == nullptr) return false;
    std::map<std::string, std::string> fields;
    std::vector<std::string> bindings;
    for (int index = 1; index < argc; ++index) {
        const std::string option(argv[index]);
        if (option == "--help" || option == "--version") return false;
        if (index + 1 >= argc) return false;
        const std::string value(argv[++index]);
        if (option == "--class-binding") {
            bindings.push_back(value);
            continue;
        }
        const bool known = option == "--onnx" || option == "--registered-onnx-digest" ||
                           option == "--engine-artifact-id" || option == "--engine-vault-dir" ||
                           option == "--max-onnx-bytes" || option == "--max-engine-bytes" ||
                           option == "--workspace-bytes" || option == "--input-width" ||
                           option == "--input-height" || option == "--query-count" ||
                           option == "--class-count" || option == "--score-threshold" ||
                           option == "--top-k" || option == "--samples";
        if (!known || value.empty() || !fields.emplace(option, value).second) return false;
    }
    constexpr const char* kRequired[] = {
        "--onnx",          "--registered-onnx-digest", "--engine-artifact-id",
        "--engine-vault-dir", "--max-onnx-bytes",       "--max-engine-bytes",
        "--workspace-bytes", "--input-width",           "--input-height",
        "--query-count",   "--class-count",             "--score-threshold",
        "--top-k",         "--samples",
    };
    for (const char* required : kRequired) {
        if (fields.find(required) == fields.end()) return false;
    }
    Options result;
    result.onnx_path = fields.at("--onnx");
    result.registered_onnx_digest = fields.at("--registered-onnx-digest");
    result.engine_artifact_id = fields.at("--engine-artifact-id");
    result.engine_vault_directory = fields.at("--engine-vault-dir");
    result.sample_list_path = fields.at("--samples");
    std::size_t input_width = 0U;
    std::size_t input_height = 0U;
    if (!ksi::edge::IsSha256Digest(result.registered_onnx_digest) ||
        !ksi::edge::ArtifactVault::IsSafeArtifactId(result.engine_artifact_id) ||
        result.engine_vault_directory.empty() ||
        !ParsePositive(fields.at("--max-onnx-bytes"), 1024U * 1024U * 1024U,
                       &result.max_onnx_bytes) ||
        !ParsePositive(fields.at("--max-engine-bytes"), 2U * 1024U * 1024U * 1024U,
                       &result.max_engine_bytes) ||
        !ParsePositive(fields.at("--workspace-bytes"), 2U * 1024U * 1024U * 1024U,
                       &result.workspace_bytes) ||
        !ParsePositive(fields.at("--input-width"), 8192U, &input_width) ||
        !ParsePositive(fields.at("--input-height"), 8192U, &input_height) ||
        !ParsePositive(fields.at("--query-count"), 10000U,
                       &result.tensor_contract.query_count) ||
        !ParsePositive(fields.at("--class-count"), 1000U,
                       &result.tensor_contract.class_count) ||
        !ParsePositive(fields.at("--top-k"), std::numeric_limits<std::size_t>::max(),
                       &result.top_k) ||
        !ParseFiniteFloat(fields.at("--score-threshold"), &result.score_threshold) ||
        result.score_threshold < 0.0F || result.score_threshold > 1.0F || bindings.empty() ||
        input_width > std::numeric_limits<std::uint32_t>::max() ||
        input_height > std::numeric_limits<std::uint32_t>::max()) {
        return false;
    }
    result.tensor_contract.input_width = static_cast<std::uint32_t>(input_width);
    result.tensor_contract.input_height = static_cast<std::uint32_t>(input_height);
    if (result.top_k > result.tensor_contract.query_count * result.tensor_contract.class_count) {
        return false;
    }
    for (const std::string& binding : bindings) {
        if (!ParseClassBinding(binding, &result.taxonomy)) return false;
    }
    for (const auto& binding : result.taxonomy) {
        if (binding.first >= result.tensor_contract.class_count) return false;
    }
    *output = std::move(result);
    return true;
}

bool ParseSamples(const std::string& path, std::vector<RawSample>* output) {
    if (output == nullptr) return false;
    std::vector<std::uint8_t> bytes;
    if (!ReadOwnedRegularFile(path, kMaximumSampleListBytes, &bytes) || bytes.empty() ||
        bytes.back() != static_cast<std::uint8_t>('\n')) {
        return false;
    }
    const std::string input(bytes.begin(), bytes.end());
    std::size_t line_start = 0U;
    bool first_line = true;
    std::map<std::string, bool> sample_ids;
    std::vector<RawSample> samples;
    for (std::size_t index = 0U; index < input.size(); ++index) {
        const char character = input[index];
        if (character == '\r' || character == '\0') return false;
        if (character != '\n') continue;
        const std::string line = input.substr(line_start, index - line_start);
        line_start = index + 1U;
        if (first_line) {
            first_line = false;
            if (line != kSampleMagic) return false;
            continue;
        }
        std::vector<std::string> values;
        std::size_t field_start = 0U;
        for (std::size_t field = 0U; field <= line.size(); ++field) {
            if (field == line.size() || line[field] == '\t') {
                values.push_back(line.substr(field_start, field - field_start));
                field_start = field + 1U;
            }
        }
        if (values.size() != 5U) return false;
        RawSample sample;
        std::size_t width = 0U;
        std::size_t height = 0U;
        if (!DecodeBase64Url(values[0], &sample.sample_id) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(sample.sample_id) ||
            !ParsePositive(values[1], 16384U, &width) || !ParsePositive(values[2], 16384U, &height) ||
            !DecodeBase64Url(values[3], &sample.rgb_path) || !IsSafeText(sample.rgb_path) ||
            !ksi::edge::IsSha256Digest(values[4]) ||
            width > std::numeric_limits<std::uint32_t>::max() ||
            height > std::numeric_limits<std::uint32_t>::max() ||
            !sample_ids.emplace(sample.sample_id, true).second) {
            return false;
        }
        sample.width = static_cast<std::uint32_t>(width);
        sample.height = static_cast<std::uint32_t>(height);
        sample.rgb_digest = values[4];
        samples.push_back(std::move(sample));
    }
    if (first_line || samples.empty()) return false;
    *output = std::move(samples);
    return true;
}

bool LoadRgb(const RawSample& sample, std::vector<std::uint8_t>* output) {
    if (output == nullptr || sample.width == 0U || sample.height == 0U) return false;
    const std::size_t width = sample.width;
    const std::size_t height = sample.height;
    if (width > std::numeric_limits<std::size_t>::max() / height ||
        width * height > std::numeric_limits<std::size_t>::max() / 3U) {
        return false;
    }
    const std::size_t expected_size = width * height * 3U;
    std::vector<std::uint8_t> bytes;
    if (expected_size > kMaximumRgbBytes ||
        !ReadOwnedRegularFile(sample.rgb_path, expected_size, &bytes) || bytes.size() != expected_size ||
        ksi::edge::Sha256Digest(bytes.data(), bytes.size()) != sample.rgb_digest) {
        return false;
    }
    *output = std::move(bytes);
    return true;
}

void AppendJsonString(std::ostringstream* output, const std::string& value) {
    *output << '"';
    for (const unsigned char character : value) {
        switch (character) {
            case '"': *output << "\\\""; break;
            case '\\': *output << "\\\\"; break;
            case '\b': *output << "\\b"; break;
            case '\f': *output << "\\f"; break;
            case '\n': *output << "\\n"; break;
            case '\r': *output << "\\r"; break;
            case '\t': *output << "\\t"; break;
            default:
                if (character < 0x20U) {
                    *output << "\\u00" << std::hex << std::setw(2) << std::setfill('0')
                            << static_cast<unsigned int>(character) << std::dec << std::setfill(' ');
                } else {
                    *output << static_cast<char>(character);
                }
        }
    }
    *output << '"';
}

std::uint64_t DropCount(const ksi::edge::DfinePostprocessReport& report,
                        ksi::edge::DfineDropReason reason) {
    const auto found = report.drops.find(reason);
    return found == report.drops.end() ? 0U : found->second;
}

bool AppendSampleJson(std::ostringstream* json, const RawSample& sample,
                      const ksi::edge::DfinePostprocessReport& report,
                      const std::string& preprocessed_input_digest) {
    if (json == nullptr || !ksi::edge::IsSha256Digest(preprocessed_input_digest)) return false;
    *json << "{\"sampleId\":";
    AppendJsonString(json, sample.sample_id);
    *json << ",\"width\":" << sample.width << ",\"height\":" << sample.height
          << ",\"rgbDigest\":";
    AppendJsonString(json, sample.rgb_digest);
    *json << ",\"preprocessedInputDigest\":";
    AppendJsonString(json, preprocessed_input_digest);
    *json << ",\"detections\":[";
    for (std::size_t index = 0U; index < report.detections.size(); ++index) {
        const ksi::edge::Detection& detection = report.detections[index];
        if (!std::isfinite(detection.confidence) || !std::isfinite(detection.box.x_min) ||
            !std::isfinite(detection.box.y_min) || !std::isfinite(detection.box.x_max) ||
            !std::isfinite(detection.box.y_max)) {
            return false;
        }
        if (index != 0U) *json << ',';
        *json << "{\"queryIndex\":" << detection.query_index << ",\"classId\":"
              << detection.class_id << ",\"className\":";
        AppendJsonString(json, detection.class_name);
        *json << ",\"confidence\":" << detection.confidence << ",\"box\":["
              << detection.box.x_min << ',' << detection.box.y_min << ',' << detection.box.x_max
              << ',' << detection.box.y_max << "]}";
    }
    *json << "],\"drops\":{\"SCORE_BELOW_THRESHOLD\":"
          << DropCount(report, ksi::edge::DfineDropReason::kScoreBelowThreshold)
          << ",\"UNKNOWN_CLASS\":" << DropCount(report, ksi::edge::DfineDropReason::kUnknownClass)
          << ",\"NON_FINITE_TENSOR\":" << DropCount(report, ksi::edge::DfineDropReason::kNonFiniteTensor)
          << ",\"MALFORMED_TENSOR\":" << DropCount(report, ksi::edge::DfineDropReason::kMalformedTensor)
          << "}}";
    return true;
}

int Fail(const char* verdict) {
    std::fprintf(stderr, "%s\n", verdict);
    return 1;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--version") {
        std::printf("%s\n", kRunnerVersion);
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--help") {
        PrintUsage(argv[0]);
        return 0;
    }
    std::locale::global(std::locale::classic());
    Options options;
    if (!ParseOptions(argc, argv, &options)) {
        PrintUsage(argv[0]);
        return 2;
    }
    if (!ksi::edge::TensorRtBackendCompiled()) return Fail("TENSORRT_BACKEND_UNAVAILABLE");
    std::vector<RawSample> samples;
    if (!ParseSamples(options.sample_list_path, &samples) || samples.size() < 10U ||
        samples.size() > 10000U) {
        return Fail("SAMPLE_LIST_REJECTED");
    }
    try {
        ksi::edge::ArtifactVault engine_vault(options.engine_vault_directory, options.max_engine_bytes);
        const ksi::edge::TensorRtEngineBuildResult built = ksi::edge::BuildTensorRtDfineEngine(
            {options.onnx_path, options.registered_onnx_digest, options.engine_artifact_id,
             &engine_vault, options.tensor_contract, options.max_onnx_bytes, options.workspace_bytes});
        if (built.verdict != ksi::edge::TensorRtBuildVerdict::kBuilt) {
            return Fail(ksi::edge::ToString(built.verdict));
        }
        ksi::edge::TensorRtDfineInference::LoadResult loaded = ksi::edge::TensorRtDfineInference::Load(
            {built.binding, options.tensor_contract, options.max_engine_bytes});
        if (loaded.verdict != ksi::edge::TensorRtLoadVerdict::kLoaded || loaded.inference == nullptr) {
            return Fail(ksi::edge::ToString(loaded.verdict));
        }
        const ksi::edge::DfinePostprocessor postprocessor(
            options.taxonomy, options.score_threshold, options.top_k);
        std::ostringstream json;
        json.imbue(std::locale::classic());
        // JSON distinguishes 0 from 0.0.  Keep every float syntactically a
        // JSON float so the strict Python report schema never has to relax its
        // integer/type boundary merely because a valid bbox coordinate is 0.
        json << std::showpoint << std::setprecision(9);
        json << "{\"schemaVersion\":\"1.0\",\"runnerVersion\":\"" << kRunnerVersion
             << "\",\"registeredOnnxDigest\":";
        AppendJsonString(&json, options.registered_onnx_digest);
        json << ",\"preprocessingContractId\":";
        AppendJsonString(&json, ksi::edge::kTensorRtDfinePreprocessingContractV1);
        json << ",\"tensorContract\":{\"inputWidth\":" << options.tensor_contract.input_width
             << ",\"inputHeight\":" << options.tensor_contract.input_height
             << ",\"queryCount\":" << options.tensor_contract.query_count
             << ",\"classCount\":" << options.tensor_contract.class_count << "}"
             << ",\"scoreThreshold\":" << options.score_threshold << ",\"topK\":"
             << options.top_k << ",\"samples\":[";
        for (std::size_t index = 0U; index < samples.size(); ++index) {
            std::vector<std::uint8_t> rgb;
            if (!LoadRgb(samples[index], &rgb)) return Fail("RGB_SAMPLE_REJECTED");
            ksi::edge::FramePacket frame;
            frame.metadata = {samples[index].width, samples[index].height,
                              static_cast<std::uint32_t>(index + 1U), 0, 0, 0};
            frame.rgb = std::move(rgb);
            ksi::edge::InferenceTensorOutput tensors;
            if (loaded.inference->Infer(frame, &tensors) != ksi::edge::InferenceVerdict::kCompleted ||
                !tensors.IsWellFormed()) {
                return Fail("TENSORRT_INFERENCE_FAILED");
            }
            const ksi::edge::DfinePostprocessReport report = postprocessor.Process(
                tensors.View(), samples[index].width, samples[index].height);
            if (index != 0U) json << ',';
            if (!AppendSampleJson(&json, samples[index], report,
                                  loaded.inference->LastPreprocessedInputDigest())) {
                return Fail("TENSORRT_REPORT_REJECTED");
            }
        }
        json << "]}";
        if (!std::cout.good()) return Fail("REPORT_WRITE_FAILED");
        std::cout << json.str() << '\n';
        return std::cout.good() ? 0 : Fail("REPORT_WRITE_FAILED");
    } catch (...) {
        return Fail("TENSORRT_DIFFERENTIAL_RUNNER_FAILED");
    }
}

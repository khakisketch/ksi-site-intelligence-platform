#include "ksi/edge/tensorrt.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <cerrno>
#include <cmath>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef KSI_EDGE_HAVE_TENSORRT
#define KSI_EDGE_HAVE_TENSORRT 0
#endif

#if KSI_EDGE_HAVE_TENSORRT
#include <NvInfer.h>
#include <NvOnnxParser.h>
#include <cuda_runtime_api.h>
#endif

namespace ksi::edge {

const char* ToString(TensorRtBuildVerdict verdict) {
    switch (verdict) {
        case TensorRtBuildVerdict::kBuilt:
            return "BUILT";
        case TensorRtBuildVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case TensorRtBuildVerdict::kInvalidRequest:
            return "INVALID_REQUEST";
        case TensorRtBuildVerdict::kOnnxUnreadable:
            return "ONNX_UNREADABLE";
        case TensorRtBuildVerdict::kOnnxDigestMismatch:
            return "ONNX_DIGEST_MISMATCH";
        case TensorRtBuildVerdict::kOnnxParseFailed:
            return "ONNX_PARSE_FAILED";
        case TensorRtBuildVerdict::kEngineBuildFailed:
            return "ENGINE_BUILD_FAILED";
        case TensorRtBuildVerdict::kTensorContractMismatch:
            return "TENSOR_CONTRACT_MISMATCH";
        case TensorRtBuildVerdict::kArtifactPersistFailed:
            return "ARTIFACT_PERSIST_FAILED";
    }
    return "UNKNOWN";
}

const char* ToString(TensorRtLoadVerdict verdict) {
    switch (verdict) {
        case TensorRtLoadVerdict::kLoaded:
            return "LOADED";
        case TensorRtLoadVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case TensorRtLoadVerdict::kBindingRejected:
            return "BINDING_REJECTED";
        case TensorRtLoadVerdict::kEngineUnreadable:
            return "ENGINE_UNREADABLE";
        case TensorRtLoadVerdict::kEngineDigestMismatch:
            return "ENGINE_DIGEST_MISMATCH";
        case TensorRtLoadVerdict::kEngineDeserializeFailed:
            return "ENGINE_DESERIALIZE_FAILED";
        case TensorRtLoadVerdict::kTensorContractMismatch:
            return "TENSOR_CONTRACT_MISMATCH";
        case TensorRtLoadVerdict::kCudaAllocationFailed:
            return "CUDA_ALLOCATION_FAILED";
    }
    return "UNKNOWN";
}

bool TensorRtBackendCompiled() {
#if KSI_EDGE_HAVE_TENSORRT
    return true;
#else
    return false;
#endif
}

namespace {

bool IsValidTensorContract(const TensorRtDfineTensorContract& contract) {
    if (contract.input_width == 0U || contract.input_height == 0U || contract.query_count == 0U ||
        contract.class_count == 0U ||
        contract.input_width > static_cast<std::uint32_t>(std::numeric_limits<int>::max()) ||
        contract.input_height > static_cast<std::uint32_t>(std::numeric_limits<int>::max()) ||
        contract.query_count > static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
        contract.class_count > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        return false;
    }
    const std::size_t width = contract.input_width;
    const std::size_t height = contract.input_height;
    return width <= std::numeric_limits<std::size_t>::max() / height &&
           width * height <= std::numeric_limits<std::size_t>::max() / 3U &&
           width * height <=
               std::numeric_limits<std::size_t>::max() / (3U * sizeof(float)) &&
           contract.query_count <= std::numeric_limits<std::size_t>::max() / contract.class_count &&
           contract.query_count <= std::numeric_limits<std::size_t>::max() / 4U;
}

bool HasLittleEndianFloat32() {
    static_assert(sizeof(float) == 4U, "TensorRT D-FINE requires IEEE-754 float32");
    if (!std::numeric_limits<float>::is_iec559) {
        return false;
    }
    const std::uint32_t probe = 1U;
    std::uint8_t first_byte = 0U;
    std::memcpy(&first_byte, &probe, sizeof(first_byte));
    return first_byte == 1U;
}

}  // namespace

const char* ToString(TensorRtDfinePreprocessVerdict verdict) {
    switch (verdict) {
        case TensorRtDfinePreprocessVerdict::kPreprocessed:
            return "PREPROCESSED";
        case TensorRtDfinePreprocessVerdict::kMalformedFrame:
            return "MALFORMED_FRAME";
        case TensorRtDfinePreprocessVerdict::kResourceExhausted:
            return "RESOURCE_EXHAUSTED";
        case TensorRtDfinePreprocessVerdict::kUnsupportedPlatform:
            return "UNSUPPORTED_PLATFORM";
    }
    return "UNKNOWN";
}

TensorRtDfinePreprocessVerdict PreprocessTensorRtDfineRgb(
    const FramePacket& frame, const TensorRtDfineTensorContract& contract,
    std::vector<float>* pixel_values, std::string* input_digest) {
    if (pixel_values == nullptr || input_digest == nullptr) {
        return TensorRtDfinePreprocessVerdict::kMalformedFrame;
    }
    pixel_values->clear();
    input_digest->clear();
    if (!HasLittleEndianFloat32()) {
        return TensorRtDfinePreprocessVerdict::kUnsupportedPlatform;
    }
    if (frame.metadata.width == 0U || frame.metadata.height == 0U ||
        !IsValidTensorContract(contract)) {
        return TensorRtDfinePreprocessVerdict::kMalformedFrame;
    }
    const std::size_t source_width = frame.metadata.width;
    const std::size_t source_height = frame.metadata.height;
    if (source_width > static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
        source_height > static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
        source_width > std::numeric_limits<std::size_t>::max() / source_height ||
        source_width * source_height > std::numeric_limits<std::size_t>::max() / 3U ||
        frame.rgb.size() != source_width * source_height * 3U) {
        return TensorRtDfinePreprocessVerdict::kMalformedFrame;
    }
    const std::size_t target_width = contract.input_width;
    const std::size_t target_height = contract.input_height;
    const std::size_t plane = target_width * target_height;
    try {
        pixel_values->assign(plane * 3U, 0.0F);
        const double scale_x = static_cast<double>(source_width) / static_cast<double>(target_width);
        const double scale_y = static_cast<double>(source_height) / static_cast<double>(target_height);
        for (std::size_t y = 0U; y < target_height; ++y) {
            const double source_y = (static_cast<double>(y) + 0.5) * scale_y - 0.5;
            const int y_floor = static_cast<int>(std::floor(source_y));
            const int y0 = std::max(0, std::min(y_floor, static_cast<int>(source_height) - 1));
            const int y1 = std::max(0, std::min(y_floor + 1, static_cast<int>(source_height) - 1));
            const double wy = source_y - static_cast<double>(y_floor);
            for (std::size_t x = 0U; x < target_width; ++x) {
                const double source_x = (static_cast<double>(x) + 0.5) * scale_x - 0.5;
                const int x_floor = static_cast<int>(std::floor(source_x));
                const int x0 = std::max(0, std::min(x_floor, static_cast<int>(source_width) - 1));
                const int x1 = std::max(0, std::min(x_floor + 1, static_cast<int>(source_width) - 1));
                const double wx = source_x - static_cast<double>(x_floor);
                const std::size_t destination = y * target_width + x;
                for (std::size_t channel = 0U; channel < 3U; ++channel) {
                    const auto value_at = [&](int sample_x, int sample_y) {
                        return static_cast<double>(frame.rgb[
                            (static_cast<std::size_t>(sample_y) * source_width +
                             static_cast<std::size_t>(sample_x)) *
                                3U +
                            channel]);
                    };
                    const double upper = value_at(x0, y0) * (1.0 - wx) + value_at(x1, y0) * wx;
                    const double lower = value_at(x0, y1) * (1.0 - wx) + value_at(x1, y1) * wx;
                    (*pixel_values)[channel * plane + destination] =
                        static_cast<float>((upper * (1.0 - wy) + lower * wy) / 255.0);
                }
            }
        }
        *input_digest = Sha256Digest(reinterpret_cast<const std::uint8_t*>(pixel_values->data()),
                                     pixel_values->size() * sizeof(float));
    } catch (const std::bad_alloc&) {
        pixel_values->clear();
        input_digest->clear();
        return TensorRtDfinePreprocessVerdict::kResourceExhausted;
    } catch (const std::length_error&) {
        pixel_values->clear();
        input_digest->clear();
        return TensorRtDfinePreprocessVerdict::kResourceExhausted;
    }
    if (input_digest->empty()) {
        pixel_values->clear();
        return TensorRtDfinePreprocessVerdict::kMalformedFrame;
    }
    return TensorRtDfinePreprocessVerdict::kPreprocessed;
}

#if KSI_EDGE_HAVE_TENSORRT

namespace {

constexpr std::size_t kMaximumBindingCount = 3U;

class TensorRtLogger final : public nvinfer1::ILogger {
public:
    void log(Severity severity, const char* message) noexcept override {
        // TensorRT may emit verbose parser/build diagnostics containing model
        // paths.  The runtime returns a typed verdict instead of forwarding
        // unbounded vendor text from a safety process into application logs.
        (void)severity;
        (void)message;
    }
};

template <typename T>
struct TensorRtDestroy {
    void operator()(T* value) const noexcept {
        if (value != nullptr) {
            value->destroy();
        }
    }
};

using RuntimePtr = std::unique_ptr<nvinfer1::IRuntime, TensorRtDestroy<nvinfer1::IRuntime>>;
using EnginePtr = std::unique_ptr<nvinfer1::ICudaEngine, TensorRtDestroy<nvinfer1::ICudaEngine>>;
using ContextPtr =
    std::unique_ptr<nvinfer1::IExecutionContext, TensorRtDestroy<nvinfer1::IExecutionContext>>;
using BuilderPtr = std::unique_ptr<nvinfer1::IBuilder, TensorRtDestroy<nvinfer1::IBuilder>>;
using NetworkPtr =
    std::unique_ptr<nvinfer1::INetworkDefinition, TensorRtDestroy<nvinfer1::INetworkDefinition>>;
using BuilderConfigPtr =
    std::unique_ptr<nvinfer1::IBuilderConfig, TensorRtDestroy<nvinfer1::IBuilderConfig>>;
using ParserPtr =
    std::unique_ptr<nvonnxparser::IParser, TensorRtDestroy<nvonnxparser::IParser>>;
using HostMemoryPtr = std::unique_ptr<nvinfer1::IHostMemory, TensorRtDestroy<nvinfer1::IHostMemory>>;

struct BindingIndices {
    int input = -1;
    int logits = -1;
    int boxes = -1;
};

bool IsExactDims(const nvinfer1::Dims& dimensions, const std::vector<int>& expected) {
    if (dimensions.nbDims != static_cast<int>(expected.size())) {
        return false;
    }
    for (int index = 0; index < dimensions.nbDims; ++index) {
        if (dimensions.d[index] != expected[static_cast<std::size_t>(index)]) {
            return false;
        }
    }
    return true;
}

bool ValidateEngineTensorContract(const nvinfer1::ICudaEngine& engine,
                                  const TensorRtDfineTensorContract& contract,
                                  BindingIndices* indices) {
    if (indices == nullptr || !IsValidTensorContract(contract) ||
        engine.getNbBindings() != static_cast<int>(kMaximumBindingCount)) {
        return false;
    }
    const int input = engine.getBindingIndex("pixel_values");
    const int logits = engine.getBindingIndex("logits");
    const int boxes = engine.getBindingIndex("pred_boxes");
    if (input < 0 || logits < 0 || boxes < 0 || input == logits || input == boxes || logits == boxes ||
        !engine.bindingIsInput(input) || engine.bindingIsInput(logits) || engine.bindingIsInput(boxes) ||
        engine.getBindingDataType(input) != nvinfer1::DataType::kFLOAT ||
        engine.getBindingDataType(logits) != nvinfer1::DataType::kFLOAT ||
        engine.getBindingDataType(boxes) != nvinfer1::DataType::kFLOAT) {
        return false;
    }
    if (!IsExactDims(engine.getBindingDimensions(input),
                     {1, 3, static_cast<int>(contract.input_height),
                      static_cast<int>(contract.input_width)}) ||
        !IsExactDims(engine.getBindingDimensions(logits),
                     {1, static_cast<int>(contract.query_count),
                      static_cast<int>(contract.class_count)}) ||
        !IsExactDims(engine.getBindingDimensions(boxes),
                     {1, static_cast<int>(contract.query_count), 4})) {
        return false;
    }
    *indices = {input, logits, boxes};
    return true;
}

enum class BoundedReadVerdict {
    kRead,
    kUnreadable,
};

BoundedReadVerdict ReadRegularFile(const std::string& path, std::size_t maximum_size,
                                   std::vector<std::uint8_t>* output) {
    if (path.empty() || maximum_size == 0U || output == nullptr) {
        return BoundedReadVerdict::kUnreadable;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0 || !S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) ||
        before.st_uid != geteuid() || (before.st_mode & 0077) != 0 || before.st_nlink != 1 ||
        before.st_size <= 0 || static_cast<std::uintmax_t>(before.st_size) > maximum_size) {
        return BoundedReadVerdict::kUnreadable;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return BoundedReadVerdict::kUnreadable;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_nlink == 1 &&
                           opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(descriptor);
        return BoundedReadVerdict::kUnreadable;
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(opened.st_size));
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < bytes.size()) {
        const ssize_t received = read(descriptor, bytes.data() + offset, bytes.size() - offset);
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
    if (!read_ok || !closed || offset != bytes.size()) {
        return BoundedReadVerdict::kUnreadable;
    }
    *output = std::move(bytes);
    return BoundedReadVerdict::kRead;
}

}  // namespace

struct TensorRtDfineInference::Impl {
    TensorRtLogger logger;
    RuntimePtr runtime;
    EnginePtr engine;
    ContextPtr context;
    cudaStream_t stream = nullptr;
    void* device_input = nullptr;
    void* device_logits = nullptr;
    void* device_boxes = nullptr;
    BindingIndices indices;
    TensorRtDfineTensorContract tensor_contract;
    std::vector<float> host_input;
    std::vector<float> host_logits;
    std::vector<float> host_boxes;
    std::string last_preprocessed_input_digest;

    ~Impl() {
        if (device_boxes != nullptr) {
            (void)cudaFree(device_boxes);
        }
        if (device_logits != nullptr) {
            (void)cudaFree(device_logits);
        }
        if (device_input != nullptr) {
            (void)cudaFree(device_input);
        }
        if (stream != nullptr) {
            (void)cudaStreamDestroy(stream);
        }
    }
};

TensorRtEngineBuildResult BuildTensorRtDfineEngine(const TensorRtEngineBuildRequest& request) {
    TensorRtEngineBuildResult result;
    if (request.onnx_path.empty() || !IsSha256Digest(request.registered_onnx_digest) ||
        request.engine_artifact_id.empty() || request.engine_vault == nullptr ||
        !IsValidTensorContract(request.tensor_contract) || request.max_onnx_bytes == 0U ||
        request.workspace_bytes == 0U) {
        result.verdict = TensorRtBuildVerdict::kInvalidRequest;
        return result;
    }
    std::vector<std::uint8_t> onnx_bytes;
    if (ReadRegularFile(request.onnx_path, request.max_onnx_bytes, &onnx_bytes) !=
        BoundedReadVerdict::kRead) {
        result.verdict = TensorRtBuildVerdict::kOnnxUnreadable;
        return result;
    }
    const std::string source_digest = Sha256Digest(onnx_bytes.data(), onnx_bytes.size());
    if (source_digest != request.registered_onnx_digest) {
        result.verdict = TensorRtBuildVerdict::kOnnxDigestMismatch;
        return result;
    }
    TensorRtLogger logger;
    BuilderPtr builder(nvinfer1::createInferBuilder(logger));
    if (!builder) {
        result.verdict = TensorRtBuildVerdict::kEngineBuildFailed;
        return result;
    }
    const std::uint32_t explicit_batch =
        1U << static_cast<std::uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
    NetworkPtr network(builder->createNetworkV2(explicit_batch));
    ParserPtr parser(nvonnxparser::createParser(*network, logger));
    if (!network || !parser || !parser->parse(onnx_bytes.data(), onnx_bytes.size())) {
        result.verdict = TensorRtBuildVerdict::kOnnxParseFailed;
        return result;
    }
    BuilderConfigPtr config(builder->createBuilderConfig());
    if (!config) {
        result.verdict = TensorRtBuildVerdict::kEngineBuildFailed;
        return result;
    }
    config->setMaxWorkspaceSize(request.workspace_bytes);
    EnginePtr engine(builder->buildEngineWithConfig(*network, *config));
    BindingIndices indices;
    if (!engine) {
        result.verdict = TensorRtBuildVerdict::kEngineBuildFailed;
        return result;
    }
    if (!ValidateEngineTensorContract(*engine, request.tensor_contract, &indices)) {
        result.verdict = TensorRtBuildVerdict::kTensorContractMismatch;
        return result;
    }
    HostMemoryPtr serialized(engine->serialize());
    if (!serialized || serialized->size() == 0U) {
        result.verdict = TensorRtBuildVerdict::kEngineBuildFailed;
        return result;
    }
    const auto persisted = request.engine_vault->Persist(
        request.engine_artifact_id, static_cast<const std::uint8_t*>(serialized->data()), serialized->size());
    if (persisted.verdict != ArtifactVaultVerdict::kPersisted &&
        persisted.verdict != ArtifactVaultVerdict::kDuplicate) {
        result.verdict = TensorRtBuildVerdict::kArtifactPersistFailed;
        return result;
    }
    result.verdict = TensorRtBuildVerdict::kBuilt;
    result.binding = {request.registered_onnx_digest, source_digest, persisted.artifact.local_path,
                      persisted.artifact.content_digest};
    return result;
}

TensorRtDfineInference::TensorRtDfineInference(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}

TensorRtDfineInference::~TensorRtDfineInference() = default;

TensorRtDfineInference::LoadResult TensorRtDfineInference::Load(
    const TensorRtDfineLoadRequest& request) {
    LoadResult result;
    if (ValidateTensorRtBinding(request.binding) != TensorRtBindingVerdict::kReady ||
        !IsValidTensorContract(request.tensor_contract) || request.max_engine_bytes == 0U) {
        result.verdict = TensorRtLoadVerdict::kBindingRejected;
        return result;
    }
    std::vector<std::uint8_t> engine_bytes;
    if (ReadRegularFile(request.binding.engine_path, request.max_engine_bytes, &engine_bytes) !=
        BoundedReadVerdict::kRead) {
        result.verdict = TensorRtLoadVerdict::kEngineUnreadable;
        return result;
    }
    if (Sha256Digest(engine_bytes.data(), engine_bytes.size()) != request.binding.engine_digest) {
        result.verdict = TensorRtLoadVerdict::kEngineDigestMismatch;
        return result;
    }
    try {
        auto impl = std::make_unique<Impl>();
        impl->runtime.reset(nvinfer1::createInferRuntime(impl->logger));
        if (!impl->runtime) {
            result.verdict = TensorRtLoadVerdict::kEngineDeserializeFailed;
            return result;
        }
        impl->engine.reset(impl->runtime->deserializeCudaEngine(engine_bytes.data(), engine_bytes.size()));
        if (!impl->engine ||
            !ValidateEngineTensorContract(*impl->engine, request.tensor_contract, &impl->indices)) {
            result.verdict = impl->engine ? TensorRtLoadVerdict::kTensorContractMismatch
                                          : TensorRtLoadVerdict::kEngineDeserializeFailed;
            return result;
        }
        impl->context.reset(impl->engine->createExecutionContext());
        if (!impl->context || cudaStreamCreate(&impl->stream) != cudaSuccess) {
            result.verdict = TensorRtLoadVerdict::kCudaAllocationFailed;
            return result;
        }
        impl->tensor_contract = request.tensor_contract;
        const std::size_t input_count =
            static_cast<std::size_t>(request.tensor_contract.input_width) * request.tensor_contract.input_height * 3U;
        const std::size_t logits_count = request.tensor_contract.query_count * request.tensor_contract.class_count;
        const std::size_t boxes_count = request.tensor_contract.query_count * 4U;
        if (cudaMalloc(&impl->device_input, input_count * sizeof(float)) != cudaSuccess ||
            cudaMalloc(&impl->device_logits, logits_count * sizeof(float)) != cudaSuccess ||
            cudaMalloc(&impl->device_boxes, boxes_count * sizeof(float)) != cudaSuccess) {
            result.verdict = TensorRtLoadVerdict::kCudaAllocationFailed;
            return result;
        }
        impl->host_input.reserve(input_count);
        impl->host_logits.resize(logits_count);
        impl->host_boxes.resize(boxes_count);
        result.verdict = TensorRtLoadVerdict::kLoaded;
        result.inference = std::unique_ptr<TensorRtDfineInference>(
            new TensorRtDfineInference(std::move(impl)));
        return result;
    } catch (...) {
        result.verdict = TensorRtLoadVerdict::kCudaAllocationFailed;
        return result;
    }
}

InferenceVerdict TensorRtDfineInference::Infer(const FramePacket& frame, InferenceTensorOutput* output) {
    if (!impl_) {
        return InferenceVerdict::kBackendUnavailable;
    }
    impl_->last_preprocessed_input_digest.clear();
    if (output == nullptr ||
        PreprocessTensorRtDfineRgb(frame, impl_->tensor_contract, &impl_->host_input,
                                   &impl_->last_preprocessed_input_digest) !=
            TensorRtDfinePreprocessVerdict::kPreprocessed) {
        return InferenceVerdict::kMalformedOutput;
    }
    const std::size_t input_bytes = impl_->host_input.size() * sizeof(float);
    const std::size_t logits_bytes = impl_->host_logits.size() * sizeof(float);
    const std::size_t boxes_bytes = impl_->host_boxes.size() * sizeof(float);
    std::vector<void*> bindings(static_cast<std::size_t>(impl_->engine->getNbBindings()), nullptr);
    bindings[static_cast<std::size_t>(impl_->indices.input)] = impl_->device_input;
    bindings[static_cast<std::size_t>(impl_->indices.logits)] = impl_->device_logits;
    bindings[static_cast<std::size_t>(impl_->indices.boxes)] = impl_->device_boxes;
    if (cudaMemcpyAsync(impl_->device_input, impl_->host_input.data(), input_bytes,
                        cudaMemcpyHostToDevice, impl_->stream) != cudaSuccess ||
        !impl_->context->enqueueV2(bindings.data(), impl_->stream, nullptr) ||
        cudaMemcpyAsync(impl_->host_logits.data(), impl_->device_logits, logits_bytes,
                        cudaMemcpyDeviceToHost, impl_->stream) != cudaSuccess ||
        cudaMemcpyAsync(impl_->host_boxes.data(), impl_->device_boxes, boxes_bytes,
                        cudaMemcpyDeviceToHost, impl_->stream) != cudaSuccess ||
        cudaStreamSynchronize(impl_->stream) != cudaSuccess) {
        return InferenceVerdict::kBackendUnavailable;
    }
    output->query_count = impl_->tensor_contract.query_count;
    output->class_count = impl_->tensor_contract.class_count;
    output->logits = impl_->host_logits;
    output->boxes_cxcywh = impl_->host_boxes;
    return InferenceVerdict::kCompleted;
}

std::string TensorRtDfineInference::LastPreprocessedInputDigest() const {
    return impl_ ? impl_->last_preprocessed_input_digest : std::string{};
}

#else

struct TensorRtDfineInference::Impl {};

TensorRtEngineBuildResult BuildTensorRtDfineEngine(const TensorRtEngineBuildRequest&) {
    return {TensorRtBuildVerdict::kBackendUnavailable, {}};
}

TensorRtDfineInference::TensorRtDfineInference(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}

TensorRtDfineInference::~TensorRtDfineInference() = default;

TensorRtDfineInference::LoadResult TensorRtDfineInference::Load(const TensorRtDfineLoadRequest&) {
    return {TensorRtLoadVerdict::kBackendUnavailable, nullptr};
}

InferenceVerdict TensorRtDfineInference::Infer(const FramePacket&, InferenceTensorOutput*) {
    return InferenceVerdict::kBackendUnavailable;
}

std::string TensorRtDfineInference::LastPreprocessedInputDigest() const {
    return {};
}

#endif

}  // namespace ksi::edge

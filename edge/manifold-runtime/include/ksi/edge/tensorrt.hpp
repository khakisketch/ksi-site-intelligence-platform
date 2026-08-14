// Optional native TensorRT D-FINE adapter.
//
// The default C++17 runtime deliberately compiles without NVIDIA headers so
// replay/ASan gates remain portable.  A Manifold build must explicitly enable
// the adapter and provide the device TensorRT/CUDA headers and shared libraries;
// no fallback CPU inference path is hidden behind this interface.

#ifndef KSI_EDGE_TENSORRT_HPP
#define KSI_EDGE_TENSORRT_HPP

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/pipeline.hpp"

namespace ksi::edge {

// The registered D-FINE-S export is static NCHW [1,3,640,640] and emits
// logits [1,300,80] plus pred_boxes [1,300,4].  These are explicit deployment
// inputs so a different model cannot silently masquerade as the approved one.
struct TensorRtDfineTensorContract {
    std::uint32_t input_width = 640U;
    std::uint32_t input_height = 640U;
    std::size_t query_count = 300U;
    std::size_t class_count = 80U;
};

// The only approved RGB input transform for the registered static D-FINE
// export.  This is deliberately a native worker/offline helper, not an
// inference fallback: it allocates/resizes and therefore must never run from a
// PSDK image callback.  Keeping it available without TensorRT lets portable
// tests pin the exact input bytes that a TensorRT-enabled worker will send.
enum class TensorRtDfinePreprocessVerdict {
    kPreprocessed,
    kMalformedFrame,
    kResourceExhausted,
    kUnsupportedPlatform,
};

const char* ToString(TensorRtDfinePreprocessVerdict verdict);

// Center-bilinear RGB HWC -> float32 NCHW, with each channel divided by 255.
// On success, `pixel_values` contains [1, 3, input_height, input_width] and
// `input_digest` is SHA-256 of its IEEE-754 little-endian bytes.  Both outputs
// are cleared for every non-success verdict.  The caller may pre-reserve
// `pixel_values` on its worker thread to avoid steady-state reallocations.
TensorRtDfinePreprocessVerdict PreprocessTensorRtDfineRgb(
    const FramePacket& frame, const TensorRtDfineTensorContract& contract,
    std::vector<float>* pixel_values, std::string* input_digest);

struct TensorRtEngineBuildRequest {
    std::string onnx_path;
    std::string registered_onnx_digest;
    std::string engine_artifact_id;
    ArtifactVault* engine_vault = nullptr;
    TensorRtDfineTensorContract tensor_contract;
    std::size_t max_onnx_bytes = 512U * 1024U * 1024U;
    std::size_t workspace_bytes = 512U * 1024U * 1024U;
};

enum class TensorRtBuildVerdict {
    kBuilt,
    kBackendUnavailable,
    kInvalidRequest,
    kOnnxUnreadable,
    kOnnxDigestMismatch,
    kOnnxParseFailed,
    kEngineBuildFailed,
    kTensorContractMismatch,
    kArtifactPersistFailed,
};

const char* ToString(TensorRtBuildVerdict verdict);

struct TensorRtEngineBuildResult {
    TensorRtBuildVerdict verdict = TensorRtBuildVerdict::kBackendUnavailable;
    TensorRtEngineBinding binding;
};

// Builds only from an ONNX byte stream whose actual SHA-256 equals the
// registry-provided digest, then stores the serialized engine through the
// crash-safe artifact vault.  The returned engine digest is required again at
// load time; a path alone is never a model identity.
TensorRtEngineBuildResult BuildTensorRtDfineEngine(const TensorRtEngineBuildRequest& request);

struct TensorRtDfineLoadRequest {
    TensorRtEngineBinding binding;
    TensorRtDfineTensorContract tensor_contract;
    std::size_t max_engine_bytes = 1024U * 1024U * 1024U;
};

enum class TensorRtLoadVerdict {
    kLoaded,
    kBackendUnavailable,
    kBindingRejected,
    kEngineUnreadable,
    kEngineDigestMismatch,
    kEngineDeserializeFailed,
    kTensorContractMismatch,
    kCudaAllocationFailed,
};

const char* ToString(TensorRtLoadVerdict verdict);

bool TensorRtBackendCompiled();

class TensorRtDfineInference final : public IFrameInference {
public:
    struct LoadResult {
        TensorRtLoadVerdict verdict = TensorRtLoadVerdict::kBackendUnavailable;
        std::unique_ptr<TensorRtDfineInference> inference;
    };

    ~TensorRtDfineInference() override;

    TensorRtDfineInference(const TensorRtDfineInference&) = delete;
    TensorRtDfineInference& operator=(const TensorRtDfineInference&) = delete;

    static LoadResult Load(const TensorRtDfineLoadRequest& request);

    // Worker-thread only.  It resizes RGB HWC to the registered fixed input,
    // rescales each channel by 1/255 (the pinned RTDetrImageProcessor contract),
    // executes TensorRT, and returns raw tensors for the shared deterministic
    // D-FINE postprocessor.  CUDA/TensorRT errors are typed backend failures.
    InferenceVerdict Infer(const FramePacket& frame, InferenceTensorOutput* output) override;

    // Worker-thread diagnostic for the offline differential runner.  This is
    // the SHA-256 of the exact IEEE-754 float32 little-endian NCHW tensor sent
    // to TensorRT on the most recent successful preprocessing step.  It lets
    // the Python ONNX oracle distinguish a model divergence from an RGB
    // resize/rescale divergence without exposing a CPU inference fallback.
    std::string LastPreprocessedInputDigest() const;

private:
    struct Impl;
    explicit TensorRtDfineInference(std::unique_ptr<Impl> impl);

    std::unique_ptr<Impl> impl_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_TENSORRT_HPP

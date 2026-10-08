// TensorRT-independent D-FINE output contract and postprocessor.
//
// TensorRT owns execution; this module owns the deterministic transformation of
// logits/boxes into typed detections. It mirrors the host ONNX oracle's sigmoid,
// flattened top-k, cxcywh-to-xyxy, and strict score-threshold semantics.

#ifndef KSI_EDGE_DFINE_HPP
#define KSI_EDGE_DFINE_HPP

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace ksi::edge {

struct BoundingBox {
    float x_min = 0.0F;
    float y_min = 0.0F;
    float x_max = 0.0F;
    float y_max = 0.0F;
};

struct Detection {
    std::uint32_t query_index = 0;
    std::uint32_t class_id = 0;
    std::string class_name;
    float confidence = 0.0F;
    BoundingBox box;
};

struct DfineRawOutput {
    const float* logits = nullptr;  // [query_count, class_count]
    const float* boxes_cxcywh = nullptr;  // [query_count, 4], normalized
    std::size_t query_count = 0;
    std::size_t class_count = 0;
};

enum class DfineDropReason {
    kScoreBelowThreshold,
    kUnknownClass,
    kNonFiniteTensor,
    kMalformedTensor,
};

const char* ToString(DfineDropReason reason);

struct DfinePostprocessReport {
    std::vector<Detection> detections;
    std::map<DfineDropReason, std::uint64_t> drops;
};

struct TensorRtEngineBinding {
    std::string registered_onnx_digest;
    std::string source_onnx_digest;
    std::string engine_path;
    std::string engine_digest;
};

enum class TensorRtBindingVerdict {
    kReady,
    kMissingDigest,
    kMalformedDigest,
    kDigestMismatch,
    kMissingEnginePath,
    kMissingEngineDigest,
};

const char* ToString(TensorRtBindingVerdict verdict);
TensorRtBindingVerdict ValidateTensorRtBinding(const TensorRtEngineBinding& binding);

class DfinePostprocessor {
public:
    DfinePostprocessor(std::map<std::uint32_t, std::string> class_taxonomy,
                       float score_threshold, std::size_t top_k);

    DfinePostprocessReport Process(const DfineRawOutput& output, std::uint32_t image_width,
                                   std::uint32_t image_height) const;

private:
    std::map<std::uint32_t, std::string> class_taxonomy_;
    float score_threshold_;
    std::size_t top_k_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_DFINE_HPP

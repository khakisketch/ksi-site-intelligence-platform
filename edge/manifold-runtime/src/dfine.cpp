#include "ksi/edge/dfine.hpp"

#include "ksi/edge/crypto.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace ksi::edge {

namespace {

struct ScoredIndex {
    float score = 0.0F;
    std::size_t flattened_index = 0;
};

float Sigmoid(float value) {
    if (value >= 0.0F) {
        const float exp_value = std::exp(-value);
        return 1.0F / (1.0F + exp_value);
    }
    const float exp_value = std::exp(value);
    return exp_value / (1.0F + exp_value);
}

bool IsFiniteBox(const float* box) {
    return std::isfinite(box[0]) && std::isfinite(box[1]) && std::isfinite(box[2]) &&
           std::isfinite(box[3]);
}

}  // namespace

const char* ToString(DfineDropReason reason) {
    switch (reason) {
        case DfineDropReason::kScoreBelowThreshold:
            return "SCORE_BELOW_THRESHOLD";
        case DfineDropReason::kUnknownClass:
            return "UNKNOWN_CLASS";
        case DfineDropReason::kNonFiniteTensor:
            return "NON_FINITE_TENSOR";
        case DfineDropReason::kMalformedTensor:
            return "MALFORMED_TENSOR";
    }
    return "UNKNOWN";
}

const char* ToString(TensorRtBindingVerdict verdict) {
    switch (verdict) {
        case TensorRtBindingVerdict::kReady:
            return "READY";
        case TensorRtBindingVerdict::kMissingDigest:
            return "MISSING_DIGEST";
        case TensorRtBindingVerdict::kMalformedDigest:
            return "MALFORMED_DIGEST";
        case TensorRtBindingVerdict::kDigestMismatch:
            return "ONNX_DIGEST_MISMATCH";
        case TensorRtBindingVerdict::kMissingEnginePath:
            return "MISSING_ENGINE_PATH";
        case TensorRtBindingVerdict::kMissingEngineDigest:
            return "MISSING_ENGINE_DIGEST";
    }
    return "UNKNOWN";
}

TensorRtBindingVerdict ValidateTensorRtBinding(const TensorRtEngineBinding& binding) {
    if (binding.registered_onnx_digest.empty() || binding.source_onnx_digest.empty()) {
        return TensorRtBindingVerdict::kMissingDigest;
    }
    if (!IsSha256Digest(binding.registered_onnx_digest) ||
        !IsSha256Digest(binding.source_onnx_digest)) {
        return TensorRtBindingVerdict::kMalformedDigest;
    }
    if (binding.registered_onnx_digest != binding.source_onnx_digest) {
        return TensorRtBindingVerdict::kDigestMismatch;
    }
    if (binding.engine_path.empty()) {
        return TensorRtBindingVerdict::kMissingEnginePath;
    }
    if (binding.engine_digest.empty()) {
        return TensorRtBindingVerdict::kMissingEngineDigest;
    }
    if (!IsSha256Digest(binding.engine_digest)) {
        return TensorRtBindingVerdict::kMalformedDigest;
    }
    return TensorRtBindingVerdict::kReady;
}

DfinePostprocessor::DfinePostprocessor(std::map<std::uint32_t, std::string> class_taxonomy,
                                       float score_threshold, std::size_t top_k)
    : class_taxonomy_(std::move(class_taxonomy)),
      score_threshold_(score_threshold),
      top_k_(top_k) {
    if (!std::isfinite(score_threshold_) || score_threshold_ < 0.0F || score_threshold_ > 1.0F ||
        top_k_ == 0) {
        throw std::invalid_argument("invalid D-FINE postprocessor configuration");
    }
}

DfinePostprocessReport DfinePostprocessor::Process(const DfineRawOutput& output,
                                                    std::uint32_t image_width,
                                                    std::uint32_t image_height) const {
    DfinePostprocessReport report;
    if (output.logits == nullptr || output.boxes_cxcywh == nullptr || output.query_count == 0 ||
        output.class_count == 0 || image_width == 0 || image_height == 0) {
        ++report.drops[DfineDropReason::kMalformedTensor];
        return report;
    }
    if (output.query_count > std::numeric_limits<std::size_t>::max() / output.class_count) {
        ++report.drops[DfineDropReason::kMalformedTensor];
        return report;
    }
    const std::size_t score_count = output.query_count * output.class_count;
    std::vector<ScoredIndex> candidates;
    candidates.reserve(score_count);
    for (std::size_t index = 0; index < score_count; ++index) {
        const float logit = output.logits[index];
        if (!std::isfinite(logit)) {
            ++report.drops[DfineDropReason::kNonFiniteTensor];
            continue;
        }
        candidates.push_back({Sigmoid(logit), index});
    }
    std::sort(candidates.begin(), candidates.end(), [](const ScoredIndex& left, const ScoredIndex& right) {
        if (left.score != right.score) {
            return left.score > right.score;
        }
        return left.flattened_index < right.flattened_index;
    });
    const std::size_t take = std::min(top_k_, candidates.size());
    for (std::size_t candidate_index = 0; candidate_index < take; ++candidate_index) {
        const ScoredIndex& candidate = candidates[candidate_index];
        if (candidate.score <= score_threshold_) {
            ++report.drops[DfineDropReason::kScoreBelowThreshold];
            continue;
        }
        const std::size_t query = candidate.flattened_index / output.class_count;
        const std::size_t class_id = candidate.flattened_index % output.class_count;
        const auto taxonomy = class_taxonomy_.find(static_cast<std::uint32_t>(class_id));
        if (taxonomy == class_taxonomy_.end()) {
            ++report.drops[DfineDropReason::kUnknownClass];
            continue;
        }
        const float* box = output.boxes_cxcywh + (query * 4U);
        if (!IsFiniteBox(box)) {
            ++report.drops[DfineDropReason::kNonFiniteTensor];
            continue;
        }
        const float x_center = box[0] * static_cast<float>(image_width);
        const float y_center = box[1] * static_cast<float>(image_height);
        const float width = box[2] * static_cast<float>(image_width);
        const float height = box[3] * static_cast<float>(image_height);
        report.detections.push_back({static_cast<std::uint32_t>(query),
                                     static_cast<std::uint32_t>(class_id), taxonomy->second,
                                     candidate.score,
                                     {x_center - width / 2.0F, y_center - height / 2.0F,
                                      x_center + width / 2.0F, y_center + height / 2.0F}});
    }
    return report;
}

}  // namespace ksi::edge

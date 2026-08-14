#include "ksi/edge/pipeline.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace ksi::edge {

namespace {

float IntersectionOverUnion(const BoundingBox& left, const BoundingBox& right) {
    const float intersection_x_min = std::max(left.x_min, right.x_min);
    const float intersection_y_min = std::max(left.y_min, right.y_min);
    const float intersection_x_max = std::min(left.x_max, right.x_max);
    const float intersection_y_max = std::min(left.y_max, right.y_max);
    const float intersection_width = std::max(0.0F, intersection_x_max - intersection_x_min);
    const float intersection_height = std::max(0.0F, intersection_y_max - intersection_y_min);
    const float intersection = intersection_width * intersection_height;
    const float left_area = std::max(0.0F, left.x_max - left.x_min) *
                            std::max(0.0F, left.y_max - left.y_min);
    const float right_area = std::max(0.0F, right.x_max - right.x_min) *
                             std::max(0.0F, right.y_max - right.y_min);
    const float union_area = left_area + right_area - intersection;
    return union_area > 0.0F ? intersection / union_area : 0.0F;
}

bool IsFiniteDetection(const Detection& detection) {
    const BoundingBox& box = detection.box;
    return std::isfinite(detection.confidence) && std::isfinite(box.x_min) &&
           std::isfinite(box.y_min) && std::isfinite(box.x_max) && std::isfinite(box.y_max) &&
           box.x_max >= box.x_min && box.y_max >= box.y_min;
}

}  // namespace

const char* ToString(InferenceVerdict verdict) {
    switch (verdict) {
        case InferenceVerdict::kCompleted:
            return "COMPLETED";
        case InferenceVerdict::kBackendUnavailable:
            return "BACKEND_UNAVAILABLE";
        case InferenceVerdict::kMalformedOutput:
            return "MALFORMED_OUTPUT";
    }
    return "UNKNOWN";
}

bool InferenceTensorOutput::IsWellFormed() const {
    if (query_count == 0 || class_count == 0 ||
        query_count > std::numeric_limits<std::size_t>::max() / class_count ||
        query_count > std::numeric_limits<std::size_t>::max() / 4U) {
        return false;
    }
    return logits.size() == query_count * class_count && boxes_cxcywh.size() == query_count * 4U;
}

DfineRawOutput InferenceTensorOutput::View() const {
    return {logits.data(), boxes_cxcywh.data(), query_count, class_count};
}

WorldStateTracker::WorldStateTracker(float association_iou_threshold, std::size_t max_tracks)
    : association_iou_threshold_(association_iou_threshold), max_tracks_(max_tracks) {
    if (!std::isfinite(association_iou_threshold_) || association_iou_threshold_ < 0.0F ||
        association_iou_threshold_ > 1.0F || max_tracks_ == 0) {
        throw std::invalid_argument("invalid world tracker configuration");
    }
}

std::vector<TrackedWorldEntity> WorldStateTracker::Update(
    const std::vector<Detection>& detections, const TelemetryAlignment& alignment,
    const FrameMetadata& frame_metadata) {
    std::vector<TrackedWorldEntity> updated;
    if (!alignment.sample.has_value()) {
        return updated;
    }
    std::vector<bool> assigned(tracks_.size(), false);
    for (const Detection& detection : detections) {
        if (!IsFiniteDetection(detection)) {
            continue;
        }
        std::size_t best_index = tracks_.size();
        float best_iou = association_iou_threshold_;
        for (std::size_t index = 0; index < tracks_.size(); ++index) {
            const Track& candidate = tracks_[index];
            if (assigned[index] || candidate.entity.detection.class_id != detection.class_id) {
                continue;
            }
            const float iou = IntersectionOverUnion(candidate.entity.detection.box, detection.box);
            if (iou > best_iou ||
                (iou == best_iou && best_index != tracks_.size() &&
                 candidate.entity.entity_id < tracks_[best_index].entity.entity_id)) {
                best_index = index;
                best_iou = iou;
            }
        }
        if (best_index == tracks_.size()) {
            if (tracks_.size() >= max_tracks_) {
                continue;
            }
            TrackedWorldEntity entity;
            entity.entity_id = "edge-track-" + std::to_string(detection.class_id) + "-" +
                               std::to_string(next_entity_number_++);
            entity.detection = detection;
            entity.frame_metadata = frame_metadata;
            entity.telemetry = *alignment.sample;
            entity.alignment_verdict = alignment.verdict;
            entity.observation_count = 1;
            tracks_.push_back({entity});
            assigned.push_back(true);
            updated.push_back(entity);
            continue;
        }
        Track& track = tracks_[best_index];
        track.entity.detection = detection;
        track.entity.frame_metadata = frame_metadata;
        track.entity.telemetry = *alignment.sample;
        track.entity.alignment_verdict = alignment.verdict;
        ++track.entity.observation_count;
        assigned[best_index] = true;
        updated.push_back(track.entity);
    }
    return updated;
}

const char* ToString(WorldProjectionVerdict verdict) {
    switch (verdict) {
        case WorldProjectionVerdict::kProjected:
            return "PROJECTED";
        case WorldProjectionVerdict::kMissingPose:
            return "MISSING_POSE";
        case WorldProjectionVerdict::kMissingDimensions:
            return "MISSING_DIMENSIONS";
        case WorldProjectionVerdict::kMissingCovariance:
            return "MISSING_COVARIANCE";
        case WorldProjectionVerdict::kMissingCalibration:
            return "MISSING_CALIBRATION";
        case WorldProjectionVerdict::kMissingTiming:
            return "MISSING_TIMING";
        case WorldProjectionVerdict::kStalePose:
            return "STALE_POSE";
        case WorldProjectionVerdict::kNoGroundIntersection:
            return "NO_GROUND_INTERSECTION";
        case WorldProjectionVerdict::kMalformed:
            return "MALFORMED";
    }
    return "UNKNOWN";
}

const char* ToString(EdgeEventStatus status) {
    switch (status) {
        case EdgeEventStatus::kObservation:
            return "OBSERVATION";
        case EdgeEventStatus::kCandidate:
            return "CANDIDATE";
        case EdgeEventStatus::kEvidenceCollection:
            return "EVIDENCE_COLLECTION";
    }
    return "UNKNOWN";
}

const char* ToString(CandidateEvidenceVerdict verdict) {
    switch (verdict) {
        case CandidateEvidenceVerdict::kBuilt:
            return "BUILT";
        case CandidateEvidenceVerdict::kInvalidInput:
            return "INVALID_INPUT";
        case CandidateEvidenceVerdict::kSequenceUnavailable:
            return "SEQUENCE_UNAVAILABLE";
        case CandidateEvidenceVerdict::kArtifactPersistFailed:
            return "ARTIFACT_PERSIST_FAILED";
        case CandidateEvidenceVerdict::kSerializationFailed:
            return "SERIALIZATION_FAILED";
    }
    return "UNKNOWN";
}

const char* ToString(PipelineVerdict verdict) {
    switch (verdict) {
        case PipelineVerdict::kProcessed:
            return "PROCESSED";
        case PipelineVerdict::kNoFrame:
            return "NO_FRAME";
        case PipelineVerdict::kTelemetryUnavailable:
            return "TELEMETRY_UNAVAILABLE";
        case PipelineVerdict::kSensorAlignmentRequired:
            return "SENSOR_ALIGNMENT_REQUIRED";
        case PipelineVerdict::kInferenceUnavailable:
            return "INFERENCE_UNAVAILABLE";
        case PipelineVerdict::kInferenceMalformed:
            return "INFERENCE_MALFORMED";
        case PipelineVerdict::kNoSupportedDetections:
            return "NO_SUPPORTED_DETECTIONS";
        case PipelineVerdict::kNoDurableCandidate:
            return "NO_DURABLE_CANDIDATE";
    }
    return "UNKNOWN";
}

EdgePipeline::EdgePipeline(BoundedFrameQueue* frame_queue, TelemetryTimeline* telemetry,
                           DfinePostprocessor postprocessor, WorldStateTracker* tracker,
                           ConservativeRiskEngine* risk_engine, SqliteStoreForward* store_forward,
                           std::int64_t alignment_tolerance_ns, bool require_sensor_alignment,
                           MonotonicNow monotonic_now)
    : frame_queue_(frame_queue),
      telemetry_(telemetry),
      postprocessor_(std::move(postprocessor)),
      tracker_(tracker),
      risk_engine_(risk_engine),
      store_forward_(store_forward),
      alignment_tolerance_ns_(alignment_tolerance_ns),
      require_sensor_alignment_(require_sensor_alignment),
      monotonic_now_(monotonic_now) {
    if (frame_queue_ == nullptr || telemetry_ == nullptr || tracker_ == nullptr ||
        risk_engine_ == nullptr || store_forward_ == nullptr || alignment_tolerance_ns_ < 0) {
        throw std::invalid_argument("edge pipeline requires valid bounded components");
    }
}

bool EdgePipeline::IsDraftWellFormed(const CandidateEvidenceDraft& draft) {
    const CandidateEventRecord& candidate = draft.candidate;
    if (candidate.idempotency_key.empty() || candidate.device_sequence < 0 ||
        candidate.edge_device_id.empty() || candidate.payload_digest.empty() ||
        candidate.payload_json.empty() || candidate.expected_evidence_count != draft.evidence.size()) {
        return false;
    }
    for (const EvidenceRecord& evidence : draft.evidence) {
        if (evidence.event_idempotency_key != candidate.idempotency_key || evidence.artifact_id.empty() ||
            evidence.content_type.empty() || evidence.local_path.empty() ||
            evidence.content_digest.empty()) {
            return false;
        }
    }
    return true;
}

PipelineReport EdgePipeline::ProcessOne(IFrameInference* inference, IWorldProjector* projector,
                                        ICandidateEvidenceBuilder* evidence_builder) {
    PipelineReport report;
    if (inference == nullptr || projector == nullptr || evidence_builder == nullptr) {
        report.verdict = PipelineVerdict::kInferenceUnavailable;
        return report;
    }
    FramePacket frame;
    if (!frame_queue_->TryPop(&frame)) {
        report.verdict = PipelineVerdict::kNoFrame;
        return report;
    }
    const TelemetryAlignment alignment = telemetry_->Align(frame.metadata, alignment_tolerance_ns_);
    report.alignment_verdict = alignment.verdict;
    if (!alignment.sample.has_value() || alignment.verdict == AlignmentVerdict::kNoTelemetry ||
        alignment.verdict == AlignmentVerdict::kOutsideTolerance) {
        report.verdict = PipelineVerdict::kTelemetryUnavailable;
        return report;
    }
    if (require_sensor_alignment_ && !alignment.has_sensor_alignment()) {
        report.verdict = PipelineVerdict::kSensorAlignmentRequired;
        return report;
    }
    InferenceTensorOutput tensors;
    const InferenceVerdict inference_verdict = inference->Infer(frame, &tensors);
    if (inference_verdict == InferenceVerdict::kBackendUnavailable) {
        report.verdict = PipelineVerdict::kInferenceUnavailable;
        return report;
    }
    if (inference_verdict != InferenceVerdict::kCompleted || !tensors.IsWellFormed()) {
        report.verdict = PipelineVerdict::kInferenceMalformed;
        return report;
    }
    const DfinePostprocessReport detection_report =
        postprocessor_.Process(tensors.View(), frame.metadata.width, frame.metadata.height);
    report.dfine_drops = detection_report.drops;
    report.detection_count = detection_report.detections.size();
    if (detection_report.detections.empty()) {
        report.verdict = PipelineVerdict::kNoSupportedDetections;
        return report;
    }
    const std::vector<TrackedWorldEntity> entities =
        tracker_->Update(detection_report.detections, alignment, frame.metadata);
    report.tracked_entity_count = entities.size();
    for (const TrackedWorldEntity& entity : entities) {
        ProjectedWorldEntity projection_output;
        const WorldProjectionVerdict projection = projector->Project(entity, &projection_output);
        if (projection != WorldProjectionVerdict::kProjected) {
            ++report.projection_drops[projection];
            continue;
        }
        const WorldEntityVerdict world_entity =
            ValidateNativeWorldEntity(projection_output.world_entity);
        if (world_entity != WorldEntityVerdict::kValid ||
            (entity.observation_count < 2U &&
             projection_output.world_entity.localization_state == "CONFIRMED")) {
            ++report.world_entity_drops[world_entity == WorldEntityVerdict::kValid
                                            ? WorldEntityVerdict::kInvalidLocalizationState
                                            : world_entity];
            continue;
        }
        ++report.world_entity_count;
        const RiskBuildResult risk = risk_engine_->Build(projection_output.risk_observation);
        if (risk.verdict != RiskBuildVerdict::kBuilt || !risk.field.has_value()) {
            ++report.risk_drops[risk.verdict];
            continue;
        }
        ++report.risk_field_count;
        CandidateEvidenceDraft draft;
        const CandidateEvidenceVerdict evidence =
            evidence_builder->Build(frame, entity, projection_output.world_entity, *risk.field, &draft);
        if (evidence != CandidateEvidenceVerdict::kBuilt || !IsDraftWellFormed(draft)) {
            ++report.evidence_drops[evidence];
            continue;
        }
        const StoreForwardVerdict stored =
            store_forward_->EnqueueCandidateWithEvidence(draft.candidate, draft.evidence);
        if (stored != StoreForwardVerdict::kAccepted && stored != StoreForwardVerdict::kDuplicate) {
            ++report.store_drops[stored];
            continue;
        }
        // The observation is taken immediately after the SQLite transaction
        // reports success. An idempotent duplicate is intentionally not a
        // fresh candidate sample: retry latency must not enter REQ-EVT-101's
        // candidate-creation denominator.
        const CandidateTimingObservation candidate_timing = MeasureCandidateDurability(
            draft.candidate.idempotency_key, frame.metadata.received_monotonic_ns,
            stored == StoreForwardVerdict::kAccepted && monotonic_now_ != nullptr ? monotonic_now_() : 0,
            stored == StoreForwardVerdict::kDuplicate);
        ++report.candidate_timing_observations[candidate_timing.verdict];
        // Preserve only the non-sensitive causal IDs the shadow owner needs.
        // Keeping this after the durable enqueue prevents a shadow action from
        // being associated with a candidate that was never crash-safely
        // journalled.
        report.durable_candidates.push_back(
            {draft.candidate.idempotency_key, risk.field->risk_policy_pack_digest, candidate_timing});
        ++report.durable_candidate_count;
    }
    report.verdict = report.durable_candidate_count > 0 ? PipelineVerdict::kProcessed
                                                         : PipelineVerdict::kNoDurableCandidate;
    return report;
}

}  // namespace ksi::edge

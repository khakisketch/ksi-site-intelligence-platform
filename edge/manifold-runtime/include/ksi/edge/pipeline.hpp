// Bounded native Edge perception pipeline.
//
// This is intentionally an orchestration layer, not a second implementation of
// TensorRT, geo projection, or the signed EventBundle contract.  It makes the
// ownership boundary explicit: PSDK feeds a bounded queue; a worker invokes a
// native inference adapter; world projection supplies measured uncertainty; the
// conservative risk engine produces a RiskField; then an EventBundle/evidence
// builder hands one durable candidate to the store-and-forward journal.

#ifndef KSI_EDGE_PIPELINE_HPP
#define KSI_EDGE_PIPELINE_HPP

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "ksi/edge/dfine.hpp"
#include "ksi/edge/event_timing.hpp"
#include "ksi/edge/frame_queue.hpp"
#include "ksi/edge/risk.hpp"
#include "ksi/edge/store_forward.hpp"
#include "ksi/edge/telemetry.hpp"
#include "ksi/edge/world_entity.hpp"

namespace ksi::edge {

enum class InferenceVerdict {
    kCompleted,
    kBackendUnavailable,
    kMalformedOutput,
};

const char* ToString(InferenceVerdict verdict);

// Owning version of DfineRawOutput.  An inference adapter fills these vectors;
// ProcessOne constructs the non-owning view only while they remain alive.
struct InferenceTensorOutput {
    std::vector<float> logits;
    std::vector<float> boxes_cxcywh;
    std::size_t query_count = 0;
    std::size_t class_count = 0;

    bool IsWellFormed() const;
    DfineRawOutput View() const;
};

class IFrameInference {
public:
    virtual ~IFrameInference() = default;
    // Called only on the worker thread, never from the PSDK callback.
    virtual InferenceVerdict Infer(const FramePacket& frame, InferenceTensorOutput* output) = 0;
};

struct TrackedWorldEntity {
    std::string entity_id;
    Detection detection;
    // The exact RGB metadata that produced ``detection``. It is carried into
    // the projector so occurrence time and intrinsics scale cannot drift to a
    // later frame on the same tracker ID.
    FrameMetadata frame_metadata;
    TelemetrySample telemetry;
    AlignmentVerdict alignment_verdict = AlignmentVerdict::kNoTelemetry;
    std::uint64_t observation_count = 0;
};

// Deterministic IoU tracker.  It gives perception a stable local entity ID but
// does not assert that a one-frame detection is a confirmed domain event.
class WorldStateTracker {
public:
    WorldStateTracker(float association_iou_threshold, std::size_t max_tracks);

    std::vector<TrackedWorldEntity> Update(const std::vector<Detection>& detections,
                                           const TelemetryAlignment& alignment,
                                           const FrameMetadata& frame_metadata);
    std::size_t track_count() const { return tracks_.size(); }

private:
    struct Track {
        TrackedWorldEntity entity;
    };

    float association_iou_threshold_;
    std::size_t max_tracks_;
    std::uint64_t next_entity_number_ = 1;
    std::vector<Track> tracks_;
};

enum class WorldProjectionVerdict {
    kProjected,
    kMissingPose,
    kMissingDimensions,
    kMissingCovariance,
    kMissingCalibration,
    kMissingTiming,
    kStalePose,
    kNoGroundIntersection,
    kMalformed,
};

const char* ToString(WorldProjectionVerdict verdict);

// Projection is hardware/calibration specific.  The interface deliberately
// cannot return an invented default pose, dimensions, covariance, or profile.
class IWorldProjector {
public:
    virtual ~IWorldProjector() = default;
    virtual WorldProjectionVerdict Project(const TrackedWorldEntity& entity,
                                           struct ProjectedWorldEntity* projection) = 0;
};

// One projection must produce both products from the same calibrated state:
// WorldEntity v1.0 for lineage/evidence and EquipmentObservation for the risk
// engine.  Splitting them would let a caller attach a RiskField to a different
// coordinate, covariance, or calibration identity than the WorldEntity.
struct ProjectedWorldEntity {
    NativeWorldEntity world_entity;
    EquipmentObservation risk_observation;
};

enum class EdgeEventStatus {
    kObservation,
    kCandidate,
    kEvidenceCollection,
};

const char* ToString(EdgeEventStatus status);

struct CandidateEvidenceDraft {
    EdgeEventStatus status = EdgeEventStatus::kCandidate;
    CandidateEventRecord candidate;
    std::vector<EvidenceRecord> evidence;
};

enum class CandidateEvidenceVerdict {
    kBuilt,
    kInvalidInput,
    kSequenceUnavailable,
    kArtifactPersistFailed,
    kSerializationFailed,
};

const char* ToString(CandidateEvidenceVerdict verdict);

// The builder owns EventBundle v1.2 construction and the stable payload digest.
// It is called after a RiskField exists, and is prohibited from producing a
// CONFIRMED_EVENT state by EdgeEventStatus' closed enum.
class ICandidateEvidenceBuilder {
public:
    virtual ~ICandidateEvidenceBuilder() = default;
    virtual CandidateEvidenceVerdict Build(const FramePacket& frame,
                                           const TrackedWorldEntity& entity,
                                           const NativeWorldEntity& world_entity,
                                           const EdgeRiskField& risk_field,
                                           CandidateEvidenceDraft* draft) = 0;
};

enum class PipelineVerdict {
    kProcessed,
    kNoFrame,
    kTelemetryUnavailable,
    kSensorAlignmentRequired,
    kInferenceUnavailable,
    kInferenceMalformed,
    kNoSupportedDetections,
    kNoDurableCandidate,
};

const char* ToString(PipelineVerdict verdict);

struct PipelineReport {
    PipelineVerdict verdict = PipelineVerdict::kNoFrame;
    AlignmentVerdict alignment_verdict = AlignmentVerdict::kNoTelemetry;
    std::size_t detection_count = 0;
    std::size_t tracked_entity_count = 0;
    std::size_t world_entity_count = 0;
    std::size_t risk_field_count = 0;
    std::size_t durable_candidate_count = 0;
    // A candidate enters this list only after the SQLite candidate/evidence
    // transaction returned ACCEPTED or its exact idempotent DUPLICATE.  The
    // PSDK owner uses it to construct a *shadow-only* high-level intent; the
    // pipeline itself deliberately has no flight-control or policy-execution
    // dependency.
    struct DurableCandidate {
        std::string idempotency_key;
        std::string risk_policy_pack_digest;
        // This is a local CLOCK_MONOTONIC observation for REQ-EVT-101 replay/
        // HIL evidence. It is deliberately separate from EventBundle.timing:
        // the shadow slice owns neither a user-visible local alert nor a
        // server-to-user notification stage.
        CandidateTimingObservation candidate_timing;
    };
    std::vector<DurableCandidate> durable_candidates;
    std::map<CandidateTimingVerdict, std::uint64_t> candidate_timing_observations;
    std::map<DfineDropReason, std::uint64_t> dfine_drops;
    std::map<WorldProjectionVerdict, std::uint64_t> projection_drops;
    std::map<WorldEntityVerdict, std::uint64_t> world_entity_drops;
    std::map<RiskBuildVerdict, std::uint64_t> risk_drops;
    std::map<CandidateEvidenceVerdict, std::uint64_t> evidence_drops;
    std::map<StoreForwardVerdict, std::uint64_t> store_drops;
};

class EdgePipeline {
public:
    // The callback's FrameMetadata timestamp and this clock must both be the
    // same process-local CLOCK_MONOTONIC domain. A null clock is accepted only
    // so the pipeline can keep detection fail-closed while emitting an explicit
    // CLOCK_UNAVAILABLE timing observation instead of an invented duration.
    using MonotonicNow = MonotonicNs (*)() noexcept;

    EdgePipeline(BoundedFrameQueue* frame_queue, TelemetryTimeline* telemetry,
                 DfinePostprocessor postprocessor, WorldStateTracker* tracker,
                 ConservativeRiskEngine* risk_engine, SqliteStoreForward* store_forward,
                 std::int64_t alignment_tolerance_ns, bool require_sensor_alignment,
                 MonotonicNow monotonic_now = nullptr);

    // Bounded single-worker step.  Callers run this in a worker thread; it has
    // no access to DJI Flight Control and cannot emit a flight command.
    PipelineReport ProcessOne(IFrameInference* inference, IWorldProjector* projector,
                              ICandidateEvidenceBuilder* evidence_builder);

private:
    static bool IsDraftWellFormed(const CandidateEvidenceDraft& draft);

    BoundedFrameQueue* frame_queue_;
    TelemetryTimeline* telemetry_;
    DfinePostprocessor postprocessor_;
    WorldStateTracker* tracker_;
    ConservativeRiskEngine* risk_engine_;
    SqliteStoreForward* store_forward_;
    std::int64_t alignment_tolerance_ns_;
    bool require_sensor_alignment_;
    MonotonicNow monotonic_now_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_PIPELINE_HPP

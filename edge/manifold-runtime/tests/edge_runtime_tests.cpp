// Native Edge runtime contract tests — no external test framework or network.

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

#include "ksi/control_plane/command.hpp"
#include "ksi/edge/activation.hpp"
#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/calibrated_projector.hpp"
#include "ksi/edge/core_sync_http.hpp"
#include "ksi/edge/crypto.hpp"
#include "ksi/edge/dfine.hpp"
#include "ksi/edge/event_timing.hpp"
#include "ksi/edge/evidence_builder.hpp"
#include "ksi/edge/frame_queue.hpp"
#include "ksi/edge/pipeline.hpp"
#include "ksi/edge/risk.hpp"
#include "ksi/edge/runtime_profile.hpp"
#include "ksi/edge/shadow.hpp"
#include "ksi/edge/store_forward.hpp"
#include "ksi/edge/sync.hpp"
#include "ksi/edge/tensorrt.hpp"
#include "ksi/edge/telemetry.hpp"
#include "ksi/edge/world_entity.hpp"

#ifndef KSI_EDGE_HAVE_CURL_TRANSPORT
#define KSI_EDGE_HAVE_CURL_TRANSPORT 0
#endif

#if KSI_EDGE_HAVE_CURL_TRANSPORT
#include "ksi/edge/curl_https_executor.hpp"
#endif

namespace {

int g_failures = 0;
int g_checks = 0;

void Check(bool condition, const char* what) {
    ++g_checks;
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

constexpr std::int64_t kUtcMs = 1'725'000'000'000LL;
const std::string kDigest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const std::string kPayloadDigest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const std::string kArtifactDigest = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

std::int64_t g_pipeline_monotonic_now_ns = 0;

std::int64_t PipelineMonotonicNowNs() noexcept {
    return g_pipeline_monotonic_now_ns;
}

ksi::edge::FrameMetadata FrameMeta(std::uint32_t frame_id = 1U, std::int64_t receive_ns = 1'000'000LL,
                                   std::int64_t sensor_ns = 0) {
    return {2U, 2U, frame_id, receive_ns, sensor_ns};
}

ksi::edge::TelemetrySample Telemetry(std::int64_t receive_ns = 1'000'000LL,
                                     std::int64_t sensor_ns = 0) {
    return {receive_ns, sensor_ns, {1.0, 2.0, 3.0}, {0.5, 0.0, 0.0}, true, std::nullopt,
            std::nullopt, std::nullopt, std::nullopt, std::nullopt};
}

ksi::edge::RiskPolicyPack RiskPack() {
    ksi::edge::EquipmentRiskPolicy policy;
    policy.equipment_class = "Vehicle_Truck";
    policy.risk_field_policy_id = "risk-truck-v1";
    policy.calibration_profile_id = "cal-v1";
    policy.declared_footprint = {4.0, 2.0, 2.0};
    policy.prediction_horizon_s = 2.0;
    policy.sample_period_s = 0.2;
    policy.covariance_sigma_multiplier = 2.0;
    policy.occlusion_expansion_m = 1.0;
    policy.severity = 0.7;
    return {kDigest, "risk-pack-test", {{policy.equipment_class, policy}}};
}

ksi::edge::EquipmentObservation Observation() {
    ksi::edge::EquipmentObservation observation;
    observation.entity_id = "edge-track-7-1";
    observation.equipment_class = "Vehicle_Truck";
    observation.position_m = {10.0, 20.0, 5.0};
    observation.velocity_mps = {2.0, 1.0, 0.0};
    observation.measured_dimensions = ksi::edge::DimensionsM{4.0, 2.0, 2.0};
    observation.position_covariance = ksi::edge::PositionCovariance{1.0, 4.0, 0.25};
    observation.calibration_profile_id = "cal-v1";
    observation.observed_at_utc_ms = kUtcMs;
    return observation;
}

ksi::edge::NativeWorldEntity WorldEntity(const std::string& entity_id = "edge-track-7-1") {
    ksi::edge::NativeWorldEntity entity;
    entity.entity_id = entity_id;
    entity.entity_class = "Vehicle_Truck";
    entity.observed_at_utc_ms = kUtcMs;
    entity.site_frame = "site-frame-v1";
    entity.position_m = {10.0, 20.0, 5.0};
    entity.velocity_mps = {2.0, 1.0, 0.0};
    entity.position_covariance = {1.0, 0.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.25};
    entity.classification_confidence = 0.9;
    entity.localization_state = "INSUFFICIENT_OBSERVATION";
    entity.track_id = entity_id;
    entity.model_versions = {{"dfine", "sha256:model"}};
    entity.calibration_profile_id = "cal-v1";
    entity.observation_ids = {"obs-1"};
    entity.classification = {"ksi-ontology-v1", "COCO-2017", 7U, "truck"};
    return entity;
}

ksi::edge::NativeRuntimeProfile RuntimeProfile() {
    ksi::edge::NativeRuntimeProfile profile;
    profile.dispatch_id = "dispatch-001";
    profile.edge_device_id = "edge-001";
    profile.mission_id = "mission-edge-001";
    profile.mission_contract_digest = kPayloadDigest;
    profile.risk_policy_pack_digest = kDigest;
    profile.edge_runtime_profile_digest = kArtifactDigest;
    profile.edge_runtime_profile_id = "runtime-profile-test";
    profile.site_id = "site-001";
    profile.model.model_pack_id = "model-pack-test";
    profile.model.model_id = "dfine-test";
    profile.model.onnx_artifact_id = "dfine.onnx";
    profile.model.registered_onnx_digest = kDigest;
    profile.model.engine_artifact_id = "dfine.engine";
    profile.model.max_onnx_bytes = 1024U;
    profile.model.max_engine_bytes = 2048U;
    profile.model.workspace_bytes = 1024U;
    profile.model.tensor_contract = {640U, 640U, 300U, 80U};
    profile.model.score_threshold = 0.5F;
    profile.model.top_k = 10U;
    profile.model.ontology_version = "ksi-ontology-v1";
    profile.model.source_taxonomy = "COCO-2017";
    profile.model.tensor_rt_differential.verification_profile_id =
        ksi::edge::kTensorRtDfineDifferentialProfileV1;
    profile.model.tensor_rt_differential.evidence_digest = kPayloadDigest;
    profile.model.tensor_rt_differential.registered_onnx_digest = kDigest;
    profile.model.tensor_rt_differential.preprocessing_contract_id =
        ksi::edge::kTensorRtDfinePreprocessingContractV1;
    profile.model.tensor_rt_differential.preprocessing_config_digest = kArtifactDigest;
    profile.model.tensor_rt_differential.corpus_id = "dfine-onnx-corpus-v1";
    profile.model.tensor_rt_differential.corpus_digest = kPayloadDigest;
    profile.model.tensor_rt_differential.sample_count = 10U;
    profile.model.tensor_rt_differential.confidence_atol = 0.001;
    profile.model.tensor_rt_differential.bbox_atol_px = 0.5;
    profile.model.tensor_rt_differential.status_passed = true;
    profile.model.class_bindings.emplace(
        7U, ksi::edge::NativeRegisteredEquipmentBinding{7U, "truck", "Vehicle_Truck", {4.0, 2.0, 2.0}});
    profile.calibration.calibration_profile_id = "cal-v1";
    profile.calibration.site_frame_crs = "EPSG:5186";
    profile.calibration.site_frame_vertical_datum = "KNGeoid2018";
    profile.calibration.site_frame_transform_version = "1.0.0";
    profile.calibration.wgs84_origin = {0.0, 0.0, 0.0};
    profile.calibration.enu_to_site_rotation = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
    profile.calibration.enu_to_site_translation_m = {0.0, 0.0, 0.0};
    profile.calibration.ground_plane_up_m = 0.0;
    profile.calibration.intrinsics = {2U, 2U, 1.0, 1.0, 1.0, 1.0};
    // Camera optical +Z maps to gimbal forward +X. A -90° pitch below then
    // maps the center ray to NED down for this deterministic software fixture.
    profile.calibration.camera_to_gimbal = {0.7071067811865476, 0.0, 0.7071067811865476, 0.0};
    profile.calibration.camera_offset_in_gimbal_m = {0.0, 0.0, 0.0};
    profile.calibration.position_sigma_m = 1.0;
    profile.calibration.angular_sigma_rad = 0.01;
    profile.calibration.pixel_sigma_px = 0.5;
    profile.calibration.max_pose_age_ms = 100;
    profile.max_alignment_ms = 50;
    return profile;
}

ksi::edge::TrackedWorldEntity ProjectableTrackedEntity() {
    ksi::edge::TrackedWorldEntity entity;
    entity.entity_id = "edge-track-7-1";
    entity.detection = {0U, 7U, "truck", 0.9F, {0.5F, 0.5F, 1.5F, 1.5F}};
    entity.frame_metadata = {2U, 2U, 7U, 10'000'000LL, 20'000'000LL, kUtcMs};
    entity.telemetry = Telemetry(10'000'000LL, 20'000'000LL);
    entity.telemetry.body_frd_to_ground_ned = {1.0, 0.0, 0.0, 0.0};
    entity.telemetry.wgs84_position = ksi::edge::TimedWgs84Position{{0.0, 0.0, 10.0}, 10'000'000LL};
    entity.telemetry.position_accuracy = ksi::edge::TimedPositionAccuracy{{0.5, 0.5}, 10'000'000LL};
    entity.telemetry.gimbal_ned_euler = ksi::edge::TimedGimbalNedEuler{
        {-1.5707963267948966, 0.0, 0.0}, 10'000'000LL};
    entity.telemetry.velocity_mps_measurement = ksi::edge::TimedVelocityMps{
        {0.5, 0.0, 0.0}, 10'000'000LL};
    entity.alignment_verdict = ksi::edge::AlignmentVerdict::kSensorAligned;
    entity.observation_count = 1U;
    return entity;
}

std::filesystem::path UniqueTestDirectory(const char* suffix);

std::string Base64UrlEncode(const std::string& input) {
    constexpr char kAlphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string output;
    output.reserve(((input.size() + 2U) / 3U) * 4U);
    std::size_t offset = 0U;
    while (offset + 3U <= input.size()) {
        const std::uint32_t value = (static_cast<std::uint32_t>(
                                        static_cast<unsigned char>(input[offset]))
                                    << 16U) |
                                    (static_cast<std::uint32_t>(
                                         static_cast<unsigned char>(input[offset + 1U]))
                                     << 8U) |
                                    static_cast<std::uint32_t>(
                                        static_cast<unsigned char>(input[offset + 2U]));
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 6U) & 0x3FU]);
        output.push_back(kAlphabet[value & 0x3FU]);
        offset += 3U;
    }
    const std::size_t remaining = input.size() - offset;
    if (remaining == 1U) {
        const std::uint32_t value =
            static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset])) << 16U;
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
    } else if (remaining == 2U) {
        const std::uint32_t value =
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset])) << 16U) |
            (static_cast<std::uint32_t>(static_cast<unsigned char>(input[offset + 1U])) << 8U);
        output.push_back(kAlphabet[(value >> 18U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 12U) & 0x3FU]);
        output.push_back(kAlphabet[(value >> 6U) & 0x3FU]);
    }
    return output;
}

std::string NativeActivationBytes() {
    return "KSI_EDGE_NATIVE_ACTIVATION_V1\n"
           "activated_at_utc_ms=" +
           std::to_string(kUtcMs) + "\n" +
           "dispatch_id_b64=" + Base64UrlEncode("dispatch-001") + "\n" +
           "edge_device_id_b64=" + Base64UrlEncode("edge-001") + "\n" +
           "mission_contract_digest=" + kPayloadDigest + "\n" +
           "mission_id_b64=" + Base64UrlEncode("mission-edge-001") + "\n" +
           "risk_policy_pack_digest=" + kDigest + "\n" +
           "risk_policy_pack_id_b64=" + Base64UrlEncode("risk-pack-test") + "\n" +
           "risk_policy_calibration_profile_id_b64=" + Base64UrlEncode("cal-v1") + "\n" +
           "risk_policy_count=1\n" +
           "risk_policy_0_equipment_class_b64=" + Base64UrlEncode("Vehicle_Truck") + "\n" +
           "risk_policy_0_risk_field_policy_id_b64=" + Base64UrlEncode("risk-truck-v1") + "\n" +
           "risk_policy_0_footprint_length_bits=4010000000000000\n"
           "risk_policy_0_footprint_width_bits=4000000000000000\n"
           "risk_policy_0_footprint_height_bits=4000000000000000\n"
           "risk_policy_0_prediction_horizon_bits=4000000000000000\n"
           "risk_policy_0_sample_period_bits=3fc999999999999a\n"
           "risk_policy_0_covariance_sigma_multiplier_bits=4000000000000000\n"
           "risk_policy_0_occlusion_expansion_bits=3ff0000000000000\n"
           "risk_policy_0_severity_bits=3fe6666666666666\n"
           "runtime_version_b64=" + Base64UrlEncode("edge-runtime-0.1") + "\n" +
           "valid_from_utc_ms=" + std::to_string(kUtcMs - 1000LL) + "\n" +
           "valid_until_utc_ms=" + std::to_string(kUtcMs + 1000LL) + "\n";
}

bool WritePrivateTextFile(const std::filesystem::path& path, const std::string& contents) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output << contents;
    output.close();
    return output.good() && chmod(path.c_str(), 0600) == 0;
}

void TestNativeActivationHandoff() {
    const std::filesystem::path directory = UniqueTestDirectory("activation");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    Check(std::filesystem::create_directories(directory) && chmod(directory.c_str(), 0700) == 0,
          "native activation test state directory is private");
    const std::filesystem::path snapshot = directory / ksi::edge::kNativeActivationFilename;
    const auto absent = ksi::edge::LoadNativeActivationSnapshot(
        directory.string(), "edge-001", "edge-runtime-0.1", kUtcMs);
    Check(absent.verdict == ksi::edge::NativeActivationVerdict::kMissing,
          "missing native activation remains capture-only");
    Check(WritePrivateTextFile(snapshot, NativeActivationBytes()),
          "private native activation fixture writes");
    const auto loaded = ksi::edge::LoadNativeActivationSnapshot(
        directory.string(), "edge-001", "edge-runtime-0.1", kUtcMs);
    Check(loaded.verdict == ksi::edge::NativeActivationVerdict::kLoaded &&
              loaded.snapshot.dispatch_id == "dispatch-001" &&
              loaded.snapshot.mission_id == "mission-edge-001" &&
              loaded.snapshot.context.mission_contract_digest == kPayloadDigest &&
              loaded.snapshot.context.risk_policy_pack_digest == kDigest &&
              loaded.snapshot.risk_policy_pack.risk_policy_pack_id == "risk-pack-test" &&
              loaded.snapshot.risk_policy_pack.by_equipment_class.at("Vehicle_Truck")
                      .declared_footprint.length ==
                  4.0,
          "private handoff binds dispatch, mission, policy values, and contract digests");
    Check(ksi::edge::LoadNativeActivationSnapshot(directory.string(), "edge-other", "edge-runtime-0.1",
                                                   kUtcMs)
              .verdict == ksi::edge::NativeActivationVerdict::kDeviceMismatch,
          "copied native activation cannot cross device boundary");
    Check(ksi::edge::LoadNativeActivationSnapshot(directory.string(), "edge-001", "edge-runtime-other",
                                                   kUtcMs)
              .verdict == ksi::edge::NativeActivationVerdict::kRuntimeMismatch,
          "native activation is bound to the installed runtime version");
    Check(ksi::edge::LoadNativeActivationSnapshot(directory.string(), "edge-001", "edge-runtime-0.1",
                                                   kUtcMs + 1001LL)
              .verdict == ksi::edge::NativeActivationVerdict::kExpired,
          "native activation TTL expires fail-closed");
    Check(WritePrivateTextFile(snapshot, NativeActivationBytes() + "unexpected=field\n"),
          "malformed native activation fixture writes");
    Check(ksi::edge::LoadNativeActivationSnapshot(directory.string(), "edge-001", "edge-runtime-0.1",
                                                   kUtcMs)
              .verdict == ksi::edge::NativeActivationVerdict::kMalformed,
          "unknown native activation field is not silently ignored");
    Check(WritePrivateTextFile(snapshot, NativeActivationBytes()) && chmod(snapshot.c_str(), 0644) == 0,
          "loose-permission native activation fixture writes");
    Check(ksi::edge::LoadNativeActivationSnapshot(directory.string(), "edge-001", "edge-runtime-0.1",
                                                   kUtcMs)
              .verdict == ksi::edge::NativeActivationVerdict::kUnsafeSnapshot,
          "group-readable native activation cannot authorize shadow state");
    std::filesystem::remove_all(directory, cleanup_error);
}

void TestSha256() {
    const std::string abc = "abc";
    Check(ksi::edge::Sha256Hex(reinterpret_cast<const std::uint8_t*>(abc.data()), abc.size()) ==
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "SHA-256 abc test vector");
    Check(ksi::edge::IsSha256Digest(kDigest), "sha256 digest pattern accepted");
    Check(!ksi::edge::IsSha256Digest("sha256:ABC"), "malformed digest rejected");
}

void TestFrameQueue() {
    ksi::edge::BoundedFrameQueue queue(2U, 16U);
    const std::uint8_t pixels[] = {1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U, 9U, 10U, 11U, 12U};
    Check(queue.PushFromCallback(nullptr, sizeof(pixels), FrameMeta()) ==
              ksi::edge::FrameDropReason::kMalformed,
          "null frame is a typed malformed drop");
    Check(queue.PushFromCallback(pixels, sizeof(pixels), FrameMeta(1U)) ==
              ksi::edge::FrameDropReason::kAccepted,
          "first preallocated frame accepted");
    Check(queue.PushFromCallback(pixels, sizeof(pixels), FrameMeta(2U)) ==
              ksi::edge::FrameDropReason::kAccepted,
          "second preallocated frame accepted");
    Check(queue.PushFromCallback(pixels, sizeof(pixels), FrameMeta(3U)) ==
              ksi::edge::FrameDropReason::kQueueFull,
          "bounded queue drops full frame without overwrite");
    ksi::edge::FramePacket output;
    Check(queue.TryPop(&output) && output.metadata.frame_id == 1U && output.rgb.size() == sizeof(pixels),
          "worker receives oldest queued frame copy");
    Check(queue.stats().accepted == 2U && queue.stats().queue_full == 1U &&
              queue.stats().malformed == 1U,
          "frame queue reports typed drop counters");
}

void TestTelemetryAlignment() {
    ksi::edge::TelemetryTimeline timeline(4U);
    Check(timeline.Record(Telemetry(1'000'000LL)) == ksi::edge::TelemetryVerdict::kRecorded,
          "telemetry records valid sample");
    Check(timeline.RecordFromCallback(Telemetry(1'000'001LL)) ==
              ksi::edge::TelemetryVerdict::kRecorded,
          "callback telemetry writes the preallocated timeline without a worker wait");
    Check(timeline.Record(Telemetry(999'999LL)) == ksi::edge::TelemetryVerdict::kClockRollback,
          "telemetry receive clock rollback rejected");
    const auto receive_only = timeline.Align(FrameMeta(1U, 1'020'000LL), 50'000LL);
    Check(receive_only.verdict == ksi::edge::AlignmentVerdict::kReceiveTimeOnly &&
              !receive_only.has_sensor_alignment(),
          "receive proximity does not upgrade sensor alignment");

    ksi::edge::TelemetryTimeline pose_timeline(4U);
    ksi::edge::TelemetrySample pose = Telemetry(1'500'000LL);
    pose.body_frd_to_ground_ned = {1.0, 0.0, 0.0, 0.0};
    Check(pose_timeline.Record(pose) == ksi::edge::TelemetryVerdict::kRecorded,
          "finite nonzero body-to-NED quaternion records with telemetry");
    const auto pose_alignment = pose_timeline.Align(FrameMeta(4U, 1'500'000LL), 1LL);
    Check(pose_alignment.sample.has_value() &&
              pose_alignment.sample->body_frd_to_ground_ned.has_value() &&
              pose_alignment.sample->body_frd_to_ground_ned->w == 1.0,
          "aligned telemetry preserves the raw body-to-NED quaternion for a calibrated projector");
    ksi::edge::TelemetrySample zero_pose = Telemetry(1'500'001LL);
    zero_pose.body_frd_to_ground_ned = {0.0, 0.0, 0.0, 0.0};
    Check(pose_timeline.Record(zero_pose) == ksi::edge::TelemetryVerdict::kMalformed,
          "zero quaternion is a typed malformed telemetry drop instead of an identity pose");

    ksi::edge::TelemetryTimeline sensor_timeline(4U);
    Check(sensor_timeline.Record(Telemetry(2'000'000LL, 8'000'000LL)) ==
              ksi::edge::TelemetryVerdict::kRecorded,
          "sensor timestamp sample records");
    const auto aligned = sensor_timeline.Align(FrameMeta(2U, 2'100'000LL, 8'020'000LL), 50'000LL);
    Check(aligned.verdict == ksi::edge::AlignmentVerdict::kSensorAligned &&
              aligned.sensor_delta_ns == 20'000LL,
          "sensor timestamp delta controls sensor alignment");
    const auto outside = sensor_timeline.Align(FrameMeta(3U, 2'001'000LL, 9'000'000LL), 50'000LL);
    Check(outside.verdict == ksi::edge::AlignmentVerdict::kOutsideTolerance &&
              outside.sensor_delta_ns == 1'000'000LL,
          "near receive time cannot hide bad sensor timestamp alignment");
}

void TestDfineAndWorldEntity() {
    ksi::edge::FramePacket rgb_fixture;
    rgb_fixture.metadata = FrameMeta();
    rgb_fixture.rgb = {0U,  10U,  20U,  30U, 40U, 50U,
                       60U, 70U,  80U,  90U, 100U, 110U};
    std::vector<float> preprocessed;
    std::string preprocessing_digest;
    const ksi::edge::TensorRtDfinePreprocessVerdict preprocessing_verdict =
        ksi::edge::PreprocessTensorRtDfineRgb(rgb_fixture, {3U, 3U, 2U, 2U},
                                               &preprocessed, &preprocessing_digest);
    Check(preprocessing_verdict == ksi::edge::TensorRtDfinePreprocessVerdict::kPreprocessed &&
              preprocessed.size() == 27U &&
              std::fabs(preprocessed[0U] - 0.0F) < 0.000001F &&
              std::fabs(preprocessed[4U] - (45.0F / 255.0F)) < 0.000001F &&
              std::fabs(preprocessed[26U] - (110.0F / 255.0F)) < 0.000001F,
          "TensorRT RGB preprocessor pins center-bilinear HWC-to-NCHW 1/255 bytes");
    Check(preprocessing_digest ==
              "sha256:89404ce71651f46204dd0e348107d07979ba204c0610313539582653566aeb18",
          "TensorRT RGB preprocessor float32 bytes match the independent ONNX-oracle fixture");
    rgb_fixture.rgb.pop_back();
    Check(ksi::edge::PreprocessTensorRtDfineRgb(rgb_fixture, {3U, 3U, 2U, 2U},
                                                 &preprocessed, &preprocessing_digest) ==
                  ksi::edge::TensorRtDfinePreprocessVerdict::kMalformedFrame &&
              preprocessed.empty() && preprocessing_digest.empty(),
          "malformed RGB bytes are a typed preprocessor drop with no stale tensor or digest");
    rgb_fixture.rgb.push_back(110U);
    Check(ksi::edge::PreprocessTensorRtDfineRgb(
              rgb_fixture,
              {3U, 3U, static_cast<std::size_t>(std::numeric_limits<int>::max()) + 1U, 2U},
              &preprocessed, &preprocessing_digest) ==
                  ksi::edge::TensorRtDfinePreprocessVerdict::kMalformedFrame &&
              preprocessed.empty() && preprocessing_digest.empty(),
          "unrepresentable TensorRT binding dimensions fail before RGB allocation or hashing");

    const float logits[] = {4.0F, 3.0F, -4.0F, -4.0F};
    const float boxes[] = {0.5F, 0.5F, 0.5F, 0.5F, 0.25F, 0.25F, 0.1F, 0.1F};
    ksi::edge::DfinePostprocessor postprocessor({{1U, "Vehicle_Truck"}}, 0.5F, 2U);
    const auto report = postprocessor.Process({logits, boxes, 2U, 2U}, 100U, 80U);
    Check(report.detections.size() == 1U && report.detections[0].class_id == 1U &&
              report.detections[0].box.x_min == 25.0F && report.detections[0].box.y_max == 60.0F,
          "D-FINE top-k sigmoid and cxcywh conversion are deterministic");
    Check(report.drops.at(ksi::edge::DfineDropReason::kUnknownClass) == 1U,
          "unknown D-FINE class remains typed drop");
    Check(ksi::edge::ValidateTensorRtBinding(
              {kDigest, kDigest, "/models/dfine.engine", kPayloadDigest}) ==
              ksi::edge::TensorRtBindingVerdict::kReady,
          "TensorRT engine binding requires registered ONNX and engine digests");
    Check(ksi::edge::ValidateTensorRtBinding({"sha256:not-a-digest", "sha256:not-a-digest",
                                              "/models/dfine.engine", kPayloadDigest}) ==
              ksi::edge::TensorRtBindingVerdict::kMalformedDigest,
          "TensorRT cannot accept an untyped ONNX digest even when both strings match");
    Check(ksi::edge::HasAcceptedTensorRtDifferential(RuntimeProfile().model),
          "TensorRT starts only from a profile-bound ONNX semantic differential attestation");
    ksi::edge::NativeRuntimeProfile unbound_differential = RuntimeProfile();
    unbound_differential.model.tensor_rt_differential.registered_onnx_digest = kPayloadDigest;
    Check(!ksi::edge::HasAcceptedTensorRtDifferential(unbound_differential.model),
          "a differential attestation for another ONNX digest cannot activate TensorRT");
    unbound_differential = RuntimeProfile();
    unbound_differential.model.tensor_rt_differential.sample_count = 9U;
    Check(!ksi::edge::HasAcceptedTensorRtDifferential(unbound_differential.model),
          "fewer than ten TensorRT corpus samples cannot activate TensorRT");
    if (!ksi::edge::TensorRtBackendCompiled()) {
        ksi::edge::TensorRtDfineLoadRequest load_request;
        load_request.binding = {kDigest, kDigest, "/models/dfine.engine", kPayloadDigest};
        Check(ksi::edge::TensorRtDfineInference::Load(load_request).verdict ==
                  ksi::edge::TensorRtLoadVerdict::kBackendUnavailable,
              "default build fails closed instead of silently substituting CPU inference");
        Check(ksi::edge::BuildTensorRtDfineEngine({}).verdict ==
                  ksi::edge::TensorRtBuildVerdict::kBackendUnavailable,
              "default build cannot create an unapproved TensorRT engine");
    }
    const ksi::edge::NativeWorldEntity entity = WorldEntity();
    Check(ksi::edge::ValidateNativeWorldEntity(entity) == ksi::edge::WorldEntityVerdict::kValid,
          "native WorldEntity validates all lineage fields");
    const std::string serialized = ksi::edge::SerializeWorldEntityV10(entity);
    Check(!serialized.empty() && serialized.find("\"schemaVersion\":\"1.0\"") != std::string::npos &&
              serialized.find("\"classificationSource\"") != std::string::npos,
          "native WorldEntity serializes contract shaped JSON");
    Check(ksi::edge::WorldEntityFingerprint(entity) ==
              "d8d01c89319674efa0701cae2c1c1f3d20926dc6573b9f15a9af0d6c2563a08c",
          "WorldEntity fingerprint matches the Python replay canonical form");
    ksi::edge::NativeWorldEntity fractional = entity;
    fractional.observed_at_utc_ms += 123;
    Check(ksi::edge::WorldEntityFingerprint(fractional) ==
              "01d554fbd86713d3b6ab241db03aad431cd67a7162ebbd46e438e329ecdbc9ba",
          "nonzero milliseconds use Python isoformat microsecond canonical form");
}

void TestProfiledGroundPlaneProjector() {
    ksi::edge::NativeRuntimeProfile reflected_profile = RuntimeProfile();
    reflected_profile.calibration.enu_to_site_rotation[0] = -1.0;
    bool rejected_reflection = false;
    try {
        ksi::edge::ProfiledGroundPlaneProjector invalid(std::move(reflected_profile));
        (void)invalid;
    } catch (const std::invalid_argument&) {
        rejected_reflection = true;
    }
    Check(rejected_reflection,
          "projector independently rejects a reflected ENU-to-site transform from any caller");
    ksi::edge::ProfiledGroundPlaneProjector projector(RuntimeProfile());
    const ksi::edge::TrackedWorldEntity entity = ProjectableTrackedEntity();
    ksi::edge::ProjectedWorldEntity projected;
    const auto verdict = projector.Project(entity, &projected);
    Check(verdict == ksi::edge::WorldProjectionVerdict::kProjected &&
              projected.world_entity.localization_state == "INSUFFICIENT_OBSERVATION" &&
              projected.world_entity.observed_at_utc_ms == kUtcMs &&
              projected.world_entity.entity_class == "Vehicle_Truck" &&
              projected.risk_observation.measured_dimensions.has_value() &&
              projected.risk_observation.position_covariance.has_value() &&
              projected.risk_observation.calibration_profile_id == "cal-v1",
          "signed profile projects a sensor-aligned calibrated frame into one nonterminal WorldEntity/Risk input");
    Check(ksi::edge::ValidateNativeWorldEntity(projected.world_entity) ==
              ksi::edge::WorldEntityVerdict::kValid,
          "profiled projector emits a contract-valid WorldEntity with conservative covariance");
    ksi::edge::TrackedWorldEntity unknown_class = entity;
    unknown_class.detection.class_id = 8U;
    Check(projector.Project(unknown_class, &projected) ==
              ksi::edge::WorldProjectionVerdict::kMissingDimensions,
          "unregistered detector class has no default physical dimensions");
    ksi::edge::TrackedWorldEntity stale_pose = entity;
    stale_pose.frame_metadata.received_monotonic_ns = 200'000'000LL;
    Check(projector.Project(stale_pose, &projected) == ksi::edge::WorldProjectionVerdict::kStalePose,
          "stale geographic pose cannot be reused for a later image frame");
    ksi::edge::TrackedWorldEntity stale_velocity = entity;
    stale_velocity.telemetry.velocity_mps_measurement->received_monotonic_ns = 200'000'000LL;
    Check(projector.Project(stale_velocity, &projected) == ksi::edge::WorldProjectionVerdict::kStalePose,
          "stale FC velocity cannot shrink a future predicted RiskField");
    ksi::edge::TrackedWorldEntity receive_time_only = entity;
    receive_time_only.alignment_verdict = ksi::edge::AlignmentVerdict::kReceiveTimeOnly;
    Check(projector.Project(receive_time_only, &projected) ==
              ksi::edge::WorldProjectionVerdict::kMissingTiming,
          "receive-time proximity cannot produce a calibrated candidate observation");
}

void TestRiskAndShadow() {
    ksi::edge::ConservativeRiskEngine engine(RiskPack());
    ksi::edge::EquipmentObservation observation = Observation();
    const auto built = engine.Build(observation);
    Check(built.verdict == ksi::edge::RiskBuildVerdict::kBuilt && built.field.has_value(),
          "complete measured equipment produces risk field");
    const double normal_margin = built.field->uncertainty_margin_m;
    observation.occluded = true;
    const auto occluded = engine.Build(observation);
    Check(occluded.verdict == ksi::edge::RiskBuildVerdict::kBuilt &&
              occluded.field->uncertainty_margin_m > normal_margin,
          "occlusion expands rather than shrinks risk footprint");
    ksi::edge::EquipmentObservation undersized = Observation();
    undersized.measured_dimensions = ksi::edge::DimensionsM{1.0, 0.5, 0.5};
    const auto undersized_result = engine.Build(undersized);
    const bool policy_floor_applied =
        built.field.has_value() && undersized_result.field.has_value() &&
        undersized_result.field->geometry.vertices[0].x == built.field->geometry.vertices[0].x &&
        undersized_result.field->geometry.vertices[2].x == built.field->geometry.vertices[2].x &&
        undersized_result.field->geometry.z_min_m == built.field->geometry.z_min_m &&
        undersized_result.field->geometry.z_max_m == built.field->geometry.z_max_m;
    Check(undersized_result.verdict == ksi::edge::RiskBuildVerdict::kBuilt && policy_floor_applied,
          "registered equipment footprint is a lower bound, never a risk-field shrink");
    observation.measured_dimensions.reset();
    Check(engine.Build(observation).verdict == ksi::edge::RiskBuildVerdict::kMissingDimensions,
          "missing dimensions do not use policy default");
    const std::string risk_json = ksi::edge::SerializeRiskFieldV11(*built.field);
    Check(risk_json.find("\"schemaVersion\":\"1.1\"") != std::string::npos &&
              risk_json.find("\"EXTRUDED_POLYGON\"") != std::string::npos,
          "risk field v1.1 is extruded with required lineage");

    ksi::edge::ShadowFlightSupervisor malformed_shadow(1'000, 2'000);
    Check(!malformed_shadow.Activate({"sha256:active", kDigest, 10'000, 20'000}, 10'000),
          "noncanonical activation digest cannot make a shadow supervisor usable");
    ksi::edge::ShadowFlightSupervisor shadow(1'000, 2'000);
    Check(shadow.Activate({kPayloadDigest, kDigest, 10'000, 20'000}, 10'000),
          "valid activation context accepted");
    Check(shadow.RecordHeartbeat(10'000, 10'000) == ksi::control_plane::HeartbeatVerdict::kRecorded,
          "shadow heartbeat recorded");
    ksi::control_plane::ActionIntent intent;
    intent.schema_version = "1.0";
    intent.command_id = "intent-1";
    intent.kind = ksi::control_plane::ActionIntentKind::kHold;
    intent.authorization_digest = kPayloadDigest;
    intent.issued_at_utc_ms = 10'000;
    intent.ttl_ms = 5'000;
    ksi::edge::ShadowActionJournal journal;
    Check(shadow.Evaluate(intent, kDigest, 10'100, &journal).verdict ==
              ksi::edge::ShadowVerdict::kShadowAccepted && journal.records().size() == 1U &&
              journal.records()[0].action_kind == "HOLD",
          "only fully gated action becomes SHADOW_ACCEPTED");
    Check(shadow.Evaluate(intent, kDigest, 10'100, &journal).verdict ==
              ksi::edge::ShadowVerdict::kShadowAccepted && journal.records().size() == 1U,
          "exact shadow replay is idempotent rather than a second accepted record");
    Check(shadow.Evaluate(intent, "sha256:wrong", 10'200, &journal).verdict ==
              ksi::edge::ShadowVerdict::kPolicyDigestMismatch && journal.records().size() == 1U,
          "policy digest mismatch emits no shadow acceptance");
    shadow.Deactivate();
    Check(shadow.Evaluate(intent, kDigest, 10'300, &journal).verdict ==
              ksi::edge::ShadowVerdict::kNoActivation &&
              journal.records().size() == 1U,
          "removed native handoff cannot leave a prior shadow activation usable");

    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-edge-runtime-shadow-journal-" +
         std::to_string(static_cast<long long>(getpid())));
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    ksi::edge::ArtifactVault vault(directory.string(), 4096U);
    ksi::edge::ArtifactVaultShadowActionJournal durable_journal(&vault);
    ksi::edge::ShadowFlightSupervisor durable_shadow(1'000, 2'000);
    Check(durable_shadow.Activate({kPayloadDigest, kDigest, 10'000, 20'000}, 10'000) &&
              durable_shadow.RecordHeartbeat(10'000, 10'000) ==
                  ksi::control_plane::HeartbeatVerdict::kRecorded &&
              durable_shadow.Evaluate(intent, kDigest, 10'100, &durable_journal).verdict ==
                  ksi::edge::ShadowVerdict::kShadowAccepted,
          "deployed shadow journal fsyncs the fully gated decision as an immutable artifact");
    const std::string command_hash = ksi::edge::Sha256Hex(
        reinterpret_cast<const std::uint8_t*>(intent.command_id.data()), intent.command_id.size());
    std::ifstream durable_record(directory / ("shadow-action-" + command_hash + ".json"));
    std::string durable_record_json((std::istreambuf_iterator<char>(durable_record)),
                                    std::istreambuf_iterator<char>());
    Check(durable_record_json.find("\"actionKind\":\"HOLD\"") != std::string::npos &&
              durable_record_json.find("\"missionContractDigest\":\"" + kPayloadDigest + "\"") !=
                  std::string::npos &&
              durable_record_json.find("\"riskPolicyPackDigest\":\"" + kDigest + "\"") !=
                  std::string::npos,
          "durable shadow record carries action kind and contract/policy lineage");
    Check(durable_shadow.Evaluate(intent, kDigest, 10'200, &durable_journal).verdict ==
              ksi::edge::ShadowVerdict::kJournalRejected,
          "a later replay of one command ID cannot overwrite its durable shadow record");
    ksi::edge::ShadowFlightSupervisor no_journal_shadow(1'000, 2'000);
    Check(no_journal_shadow.Activate({kPayloadDigest, kDigest, 10'000, 20'000}, 10'000) &&
              no_journal_shadow.RecordHeartbeat(10'000, 10'000) ==
                  ksi::control_plane::HeartbeatVerdict::kRecorded &&
              no_journal_shadow.Evaluate(intent, kDigest, 10'100, nullptr).verdict ==
                  ksi::edge::ShadowVerdict::kJournalUnavailable,
          "a valid action without a journal is not reported as SHADOW_ACCEPTED");
    std::filesystem::remove_all(directory, cleanup_error);
}

class FakeInference final : public ksi::edge::IFrameInference {
public:
    ksi::edge::InferenceVerdict Infer(const ksi::edge::FramePacket&, ksi::edge::InferenceTensorOutput* output) override {
        output->query_count = 1U;
        output->class_count = 1U;
        output->logits = {4.0F};
        output->boxes_cxcywh = {0.5F, 0.5F, 0.25F, 0.25F};
        return ksi::edge::InferenceVerdict::kCompleted;
    }
};

class FakeProjector final : public ksi::edge::IWorldProjector {
public:
    ksi::edge::WorldProjectionVerdict Project(const ksi::edge::TrackedWorldEntity& tracked,
                                               ksi::edge::ProjectedWorldEntity* projection) override {
        if (projection == nullptr) {
            return ksi::edge::WorldProjectionVerdict::kMalformed;
        }
        projection->world_entity = WorldEntity(tracked.entity_id);
        projection->world_entity.entity_class = tracked.detection.class_name;
        projection->world_entity.track_id = tracked.entity_id;
        projection->risk_observation = Observation();
        projection->risk_observation.entity_id = tracked.entity_id;
        return ksi::edge::WorldProjectionVerdict::kProjected;
    }
};

class FakeEvidenceBuilder final : public ksi::edge::ICandidateEvidenceBuilder {
public:
    ksi::edge::CandidateEvidenceVerdict Build(const ksi::edge::FramePacket&,
                                              const ksi::edge::TrackedWorldEntity& entity,
                                              const ksi::edge::NativeWorldEntity&,
                                              const ksi::edge::EdgeRiskField&,
                                              ksi::edge::CandidateEvidenceDraft* draft) override {
        if (draft == nullptr) {
            return ksi::edge::CandidateEvidenceVerdict::kInvalidInput;
        }
        draft->status = ksi::edge::EdgeEventStatus::kCandidate;
        draft->candidate = {"evt-" + entity.entity_id, 0, "edge-1", kPayloadDigest,
                            "{\"schemaVersion\":\"1.2\"}", 1U};
        draft->evidence = {{draft->candidate.idempotency_key, "artifact-1", "application/octet-stream",
                            "/tmp/edge-artifact-1", kArtifactDigest}};
        return ksi::edge::CandidateEvidenceVerdict::kBuilt;
    }
};

class RecordingTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::vector<std::string> operations;
    ksi::edge::CoreSyncVerdict UploadCandidate(const ksi::edge::CandidateEventRecord&) override {
        operations.push_back("candidate");
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
    ksi::edge::EvidenceRegistrationResult RegisterEvidence(const ksi::edge::CandidateEventRecord&,
                                                           const ksi::edge::EvidenceRecord&) override {
        operations.push_back("register");
        return {ksi::edge::CoreSyncVerdict::kAcknowledged, "https://core.invalid/upload",
                {{"Content-Type", "application/octet-stream"},
                 {"x-amz-checksum-sha256", "test-checksum"}}};
    }
    ksi::edge::CoreSyncVerdict PutEvidence(const ksi::edge::EvidenceRecord&,
                                           const ksi::edge::EvidenceRegistrationResult& registration) override {
        operations.push_back("put");
        return registration.upload_url == "https://core.invalid/upload" &&
                       registration.required_upload_headers.at("Content-Type") == "application/octet-stream" &&
                       registration.required_upload_headers.at("x-amz-checksum-sha256") == "test-checksum"
                   ? ksi::edge::CoreSyncVerdict::kAcknowledged
                   : ksi::edge::CoreSyncVerdict::kPermanentFailure;
    }
};

class RetryUploadTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::vector<std::string> operations;
    std::vector<std::string> put_urls;
    std::size_t registrations = 0U;
    std::size_t puts = 0U;

    ksi::edge::CoreSyncVerdict UploadCandidate(const ksi::edge::CandidateEventRecord&) override {
        operations.push_back("candidate");
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
    ksi::edge::EvidenceRegistrationResult RegisterEvidence(const ksi::edge::CandidateEventRecord&,
                                                           const ksi::edge::EvidenceRecord&) override {
        operations.push_back("register");
        ++registrations;
        return {ksi::edge::CoreSyncVerdict::kAcknowledged,
                "https://core.invalid/upload/" + std::to_string(registrations),
                {{"Content-Type", "application/octet-stream"},
                 {"x-amz-checksum-sha256", "test-checksum"}}};
    }
    ksi::edge::CoreSyncVerdict PutEvidence(const ksi::edge::EvidenceRecord&,
                                           const ksi::edge::EvidenceRegistrationResult& registration) override {
        operations.push_back("put");
        put_urls.push_back(registration.upload_url);
        if (registration.required_upload_headers.at("Content-Type") != "application/octet-stream" ||
            registration.required_upload_headers.at("x-amz-checksum-sha256") != "test-checksum") {
            return ksi::edge::CoreSyncVerdict::kPermanentFailure;
        }
        ++puts;
        return puts == 1U ? ksi::edge::CoreSyncVerdict::kRetryableFailure
                          : ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
};

class OrderedFailureTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::vector<std::string> operations;
    bool fail_first_registration = true;

    ksi::edge::CoreSyncVerdict UploadCandidate(
        const ksi::edge::CandidateEventRecord& candidate) override {
        operations.push_back("candidate:" + candidate.idempotency_key);
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }

    ksi::edge::EvidenceRegistrationResult RegisterEvidence(
        const ksi::edge::CandidateEventRecord& candidate,
        const ksi::edge::EvidenceRecord&) override {
        operations.push_back("register:" + candidate.idempotency_key);
        if (fail_first_registration && candidate.idempotency_key == "evt-order-0") {
            fail_first_registration = false;
            return {ksi::edge::CoreSyncVerdict::kRetryableFailure, {}, {}};
        }
        return {ksi::edge::CoreSyncVerdict::kAcknowledged,
                "https://core.invalid/upload/" + candidate.idempotency_key,
                {{"Content-Type", "application/octet-stream"},
                 {"x-amz-checksum-sha256", "test-checksum"}}};
    }

    ksi::edge::CoreSyncVerdict PutEvidence(
        const ksi::edge::EvidenceRecord& evidence,
        const ksi::edge::EvidenceRegistrationResult& registration) override {
        operations.push_back("put:" + evidence.event_idempotency_key);
        return registration.upload_url ==
                       "https://core.invalid/upload/" + evidence.event_idempotency_key &&
                       registration.required_upload_headers.at("Content-Type") ==
                           "application/octet-stream" &&
                       registration.required_upload_headers.at("x-amz-checksum-sha256") ==
                           "test-checksum"
                   ? ksi::edge::CoreSyncVerdict::kAcknowledged
                   : ksi::edge::CoreSyncVerdict::kPermanentFailure;
    }
};

class ArtifactOrderedTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::vector<std::string> operations;

    ksi::edge::CoreSyncVerdict UploadCandidate(
        const ksi::edge::CandidateEventRecord& candidate) override {
        operations.push_back("candidate:" + candidate.idempotency_key);
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }

    ksi::edge::EvidenceRegistrationResult RegisterEvidence(
        const ksi::edge::CandidateEventRecord& candidate,
        const ksi::edge::EvidenceRecord& evidence) override {
        operations.push_back("register:" + candidate.idempotency_key + ":" + evidence.artifact_id);
        return {ksi::edge::CoreSyncVerdict::kAcknowledged,
                "https://core.invalid/upload/" + candidate.idempotency_key + "/" +
                    evidence.artifact_id,
                {{"Content-Type", "application/octet-stream"},
                 {"x-amz-checksum-sha256", "test-checksum"}}};
    }

    ksi::edge::CoreSyncVerdict PutEvidence(
        const ksi::edge::EvidenceRecord& evidence,
        const ksi::edge::EvidenceRegistrationResult& registration) override {
        operations.push_back("put:" + evidence.event_idempotency_key + ":" + evidence.artifact_id);
        return registration.required_upload_headers.at("Content-Type") == "application/octet-stream" &&
                       registration.required_upload_headers.at("x-amz-checksum-sha256") == "test-checksum"
                   ? ksi::edge::CoreSyncVerdict::kAcknowledged
                   : ksi::edge::CoreSyncVerdict::kPermanentFailure;
    }
};

class EmptyUrlTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::size_t put_calls = 0U;

    ksi::edge::CoreSyncVerdict UploadCandidate(const ksi::edge::CandidateEventRecord&) override {
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
    ksi::edge::EvidenceRegistrationResult RegisterEvidence(const ksi::edge::CandidateEventRecord&,
                                                           const ksi::edge::EvidenceRecord&) override {
        return {ksi::edge::CoreSyncVerdict::kAcknowledged, "", {{"Content-Type", "application/octet-stream"}}};
    }
    ksi::edge::CoreSyncVerdict PutEvidence(const ksi::edge::EvidenceRecord&,
                                           const ksi::edge::EvidenceRegistrationResult&) override {
        ++put_calls;
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
};

class EmptyHeadersTransport final : public ksi::edge::IEdgeCoreSyncTransport {
public:
    std::size_t put_calls = 0U;

    ksi::edge::CoreSyncVerdict UploadCandidate(const ksi::edge::CandidateEventRecord&) override {
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
    ksi::edge::EvidenceRegistrationResult RegisterEvidence(const ksi::edge::CandidateEventRecord&,
                                                           const ksi::edge::EvidenceRecord&) override {
        return {ksi::edge::CoreSyncVerdict::kAcknowledged, "https://core.invalid/upload", {}};
    }
    ksi::edge::CoreSyncVerdict PutEvidence(const ksi::edge::EvidenceRecord&,
                                           const ksi::edge::EvidenceRegistrationResult&) override {
        ++put_calls;
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }
};

class RecordingHttpsExecutor final : public ksi::edge::IHttpsRequestExecutor {
public:
    std::vector<ksi::edge::HttpsRequest> requests;
    std::vector<ksi::edge::HttpsResponse> responses;
    std::vector<ksi::edge::HttpsRequestVerdict> verdicts;

    ksi::edge::HttpsRequestVerdict Execute(const ksi::edge::HttpsRequest& request,
                                           ksi::edge::HttpsResponse* response) override {
        requests.push_back(request);
        if (response == nullptr || responses.empty() || verdicts.empty()) {
            return ksi::edge::HttpsRequestVerdict::kPermanentFailure;
        }
        const ksi::edge::HttpsRequestVerdict verdict = verdicts.front();
        verdicts.erase(verdicts.begin());
        *response = responses.front();
        responses.erase(responses.begin());
        return verdict;
    }
};

std::string ToString(const std::vector<std::uint8_t>& bytes) {
    return std::string(bytes.begin(), bytes.end());
}

std::string CoreCandidatePayload(const std::string& event_id = "evt-wire-1") {
    return "{\"entities\":[\"edge-track-1\"],\"eventId\":\"" + event_id +
           "\",\"eventType\":\"EQUIPMENT_RISK_OBSERVATION\",\"evidence\":{},"
           "\"lineage\":{\"calibrationProfileId\":\"cal-v1\",\"classification\":{},"
           "\"edgeVersion\":\"test\",\"modelVersions\":{},\"policyVersion\":\"risk-v1\"},"
           "\"missionId\":\"mission-1\",\"occurredAt\":\"2024-01-01T00:00:00.000Z\","
           "\"reasoning\":{},\"schemaVersion\":\"1.2\",\"siteId\":\"site-1\","
           "\"spatialContext\":{},\"status\":\"CANDIDATE\"}";
}

const std::string kWireArtifactBytes = "edge-evidence";
const std::string kWireArtifactDigest =
    "sha256:612ca33bed05215ca89dff4b3a1e74a692be1b24278a626b5c97357c19ef0b38";
const std::string kWireArtifactChecksum = "YSyjO+0FIVyonf9LOh50ppK+GyQnimJrXJc1fBnvCzg=";

std::string EvidenceRegistrationJson(
    const std::string& upload_url =
        "https://storage.example.test/upload?X-Amz-Algorithm=AWS4-HMAC-SHA256",
    const std::string& extra_headers_json = {}) {
    return "{\"artifactId\":\"frame-wire.rgb\",\"objectKey\":\"sites/site-1/events/edge-1/"
           "evt-wire-1/frame-wire.rgb\",\"uploadUrl\":\"" + upload_url +
           "\",\"expiresAt\":\"2024-01-01T00:15:00Z\",\"reusedRegistration\":false,"
           "\"contentDigest\":\"" + kWireArtifactDigest +
           "\",\"requiredUploadHeaders\":{\"Content-Type\":\"application/octet-stream\","
           "\"x-amz-checksum-sha256\":\"" + kWireArtifactChecksum + "\"" +
           extra_headers_json + "}}";
}

std::filesystem::path UniqueTestDirectory(const char* suffix) {
    return std::filesystem::temp_directory_path() /
           (std::string("ksi-edge-runtime-") + suffix + "-" + std::to_string(static_cast<long long>(getpid())));
}

void TestArtifactVaultAndStoreForward() {
    const std::filesystem::path directory = UniqueTestDirectory("vault");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    ksi::edge::ArtifactVault vault(directory.string(), 1024U);
    const std::uint8_t bytes[] = {1U, 2U, 3U, 4U};
    const auto persisted = vault.Persist("frame-1.rgb", bytes, sizeof(bytes));
    Check(persisted.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted,
          "artifact vault fsyncs first artifact");
    Check(vault.Persist("frame-1.rgb", bytes, sizeof(bytes)).verdict ==
              ksi::edge::ArtifactVaultVerdict::kDuplicate,
          "artifact vault keeps identical retry idempotent");
    const std::uint8_t changed[] = {9U};
    Check(vault.Persist("frame-1.rgb", changed, sizeof(changed)).verdict ==
              ksi::edge::ArtifactVaultVerdict::kConflict,
          "artifact vault rejects divergent artifact retry");
    struct stat vault_directory_stat {};
    struct stat artifact_stat {};
    Check(stat(directory.c_str(), &vault_directory_stat) == 0 &&
              (vault_directory_stat.st_mode & 0077) == 0 &&
              stat(persisted.artifact.local_path.c_str(), &artifact_stat) == 0 &&
              S_ISREG(artifact_stat.st_mode) && (artifact_stat.st_mode & 0077) == 0 &&
              artifact_stat.st_nlink == 1,
          "artifact vault makes its directory and immutable artifacts private");
    std::vector<std::uint8_t> read;
    Check(vault.ReadAndVerify(persisted.artifact, &read).verdict == ksi::edge::ArtifactVaultVerdict::kPersisted &&
              read.size() == sizeof(bytes),
          "artifact vault verifies bytes and digest before upload");
    Check(vault.ReadAndVerifyDigest(persisted.artifact.artifact_id, persisted.artifact.local_path,
                                   persisted.artifact.content_digest, &read)
                  .verdict == ksi::edge::ArtifactVaultVerdict::kPersisted &&
              read.size() == sizeof(bytes),
          "artifact vault exposes a digest-verified replay read without inventing a byte count");
    ksi::edge::StoredArtifact redirected = persisted.artifact;
    redirected.local_path = "/not-the-vault/frame-1.rgb";
    Check(vault.ReadAndVerify(redirected, &read).verdict ==
              ksi::edge::ArtifactVaultVerdict::kDigestMismatch,
          "artifact vault rejects a journal path redirected outside its private root");

    const std::filesystem::path database = UniqueTestDirectory("store").string() + ".sqlite";
    std::filesystem::remove(database, cleanup_error);
    ksi::edge::SqliteStoreForward store(database.string());
    const auto opened = store.Open();
    if (!ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        Check(opened == ksi::edge::StoreForwardVerdict::kBackendUnavailable,
              "host without SQLite headers fails closed rather than memory fallback");
        std::filesystem::remove_all(directory, cleanup_error);
        return;
    }
    Check(opened == ksi::edge::StoreForwardVerdict::kAccepted, "SQLite WAL journal opens");
    const ksi::edge::CandidateEventRecord candidate = {
        "evt-store-1", 0, "edge-1", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord evidence = {
        "evt-store-1", "frame-1.rgb", "application/octet-stream", persisted.artifact.local_path,
        persisted.artifact.content_digest};
    Check(store.EnqueueCandidateWithEvidence(candidate, {evidence}) == ksi::edge::StoreForwardVerdict::kAccepted,
          "candidate and evidence plan persist atomically");
    Check(store.EnqueueCandidateWithEvidence(candidate, {evidence}) == ksi::edge::StoreForwardVerdict::kDuplicate,
          "candidate/evidence exact replay is idempotent");
    Check(store.MarkEvidenceRegistered(candidate.idempotency_key, evidence.artifact_id) ==
              ksi::edge::StoreForwardVerdict::kAwaitingCandidateAck,
          "evidence Core registration cannot precede Candidate ACK");
    Check(store.AcknowledgeCandidate(candidate.idempotency_key) == ksi::edge::StoreForwardVerdict::kAccepted,
          "candidate ACK is durable");
    Check(store.PendingEvidenceRegistration().size() == 1U,
          "only ACKed candidate enters evidence registration queue");
    Check(store.MarkEvidencePutComplete(candidate.idempotency_key, evidence.artifact_id) ==
              ksi::edge::StoreForwardVerdict::kAwaitingEvidenceRegistration,
          "PUT cannot precede Core evidence registration");
    Check(store.MarkEvidenceRegistered(candidate.idempotency_key, evidence.artifact_id) ==
              ksi::edge::StoreForwardVerdict::kAccepted && store.PendingEvidenceUpload().size() == 1U,
          "registration ACK exposes upload work");
    Check(store.MarkEvidencePutComplete(candidate.idempotency_key, evidence.artifact_id) ==
              ksi::edge::StoreForwardVerdict::kAccepted,
          "PUT completion persists before prune");
    Check(store.PruneCompleted() == ksi::edge::StoreForwardVerdict::kAccepted && store.CandidateCount() == 0U,
          "only fully registered and uploaded candidate is pruned");

    const ksi::edge::CandidateEventRecord sync_candidate = {
        "evt-store-2", 1, "edge-1", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord sync_evidence = {
        "evt-store-2", "frame-2.rgb", "application/octet-stream", persisted.artifact.local_path,
        persisted.artifact.content_digest};
    Check(store.EnqueueCandidateWithEvidence(sync_candidate, {sync_evidence}) ==
              ksi::edge::StoreForwardVerdict::kAccepted,
          "second candidate queued for ordering test");
    RecordingTransport transport;
    ksi::edge::StoreForwardSyncDriver driver(&store);
    const auto report = driver.SynchronizeOnce(&transport);
    Check(report.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              transport.operations == std::vector<std::string>({"candidate", "register", "put"}) &&
              store.CandidateCount() == 0U,
          "sync preserves candidate ACK then registration then PUT order");

    const ksi::edge::CandidateEventRecord restart_candidate = {
        "evt-store-restart", 2, "edge-1", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord restart_evidence = {
        "evt-store-restart", "frame-restart.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    Check(store.EnqueueCandidateWithEvidence(restart_candidate, {restart_evidence}) ==
              ksi::edge::StoreForwardVerdict::kAccepted,
          "restart evidence plan queued");
    RetryUploadTransport retry_transport;
    const auto failed_put = driver.SynchronizeOnce(&retry_transport);
    Check(failed_put.verdict == ksi::edge::CoreSyncVerdict::kRetryableFailure &&
              store.PendingEvidenceUpload().size() == 1U && store.CandidateCount() == 1U,
          "lost PUT ACK leaves registered evidence durable for restart");
    const auto recovered_put = driver.SynchronizeOnce(&retry_transport);
    Check(recovered_put.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              retry_transport.operations ==
                  std::vector<std::string>({"candidate", "register", "put", "register", "put"}) &&
              retry_transport.put_urls.size() == 2U &&
              retry_transport.put_urls[0] != retry_transport.put_urls[1] && store.CandidateCount() == 0U,
          "restart re-registers for a fresh upload URL before retrying PUT");

    // Two candidates expose the historical phase-order bug: the old driver
    // ACKed both candidates before it attempted the first evidence
    // registration. A retryable failure for sequence 0 must therefore leave
    // sequence 1 completely untouched until sequence 0 is registered and PUT.
    const std::filesystem::path strict_order_database =
        UniqueTestDirectory("store-strict-order").string() + ".sqlite";
    std::filesystem::remove(strict_order_database, cleanup_error);
    ksi::edge::SqliteStoreForward strict_order_store(strict_order_database.string());
    Check(strict_order_store.Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "separate journal opens for strict per-candidate ordering");
    const ksi::edge::CandidateEventRecord first_order_candidate = {
        "evt-order-0", 0, "edge-order", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::CandidateEventRecord second_order_candidate = {
        "evt-order-1", 1, "edge-order", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord first_order_evidence = {
        first_order_candidate.idempotency_key, "frame-order-0.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    const ksi::edge::EvidenceRecord second_order_evidence = {
        second_order_candidate.idempotency_key, "frame-order-1.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    Check(strict_order_store.EnqueueCandidateWithEvidence(first_order_candidate, {first_order_evidence}) ==
              ksi::edge::StoreForwardVerdict::kAccepted &&
              strict_order_store.EnqueueCandidateWithEvidence(second_order_candidate,
                                                              {second_order_evidence}) ==
                  ksi::edge::StoreForwardVerdict::kAccepted,
          "two ordered candidates and evidence plans persist before sync");
    OrderedFailureTransport ordered_failure_transport;
    ksi::edge::StoreForwardSyncDriver strict_order_driver(&strict_order_store);
    const auto strict_order_failed = strict_order_driver.SynchronizeOnce(&ordered_failure_transport);
    Check(strict_order_failed.verdict == ksi::edge::CoreSyncVerdict::kRetryableFailure &&
              ordered_failure_transport.operations ==
                  std::vector<std::string>({"candidate:evt-order-0", "register:evt-order-0"}) &&
              strict_order_store.PendingCandidates().size() == 1U &&
              strict_order_store.PendingEvidenceRegistration().size() == 1U,
          "first evidence retry prevents a later candidate ACK");
    const auto strict_order_recovered = strict_order_driver.SynchronizeOnce(&ordered_failure_transport);
    Check(strict_order_recovered.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              ordered_failure_transport.operations ==
                  std::vector<std::string>({"candidate:evt-order-0", "register:evt-order-0",
                                            "register:evt-order-0", "put:evt-order-0",
                                            "candidate:evt-order-1", "register:evt-order-1",
                                            "put:evt-order-1"}) &&
              strict_order_store.CandidateCount() == 0U,
          "restart completes earlier evidence before later candidate ACK");

    // Close and reopen the actual WAL journal after Core has registered the
    // first artifact but before its PUT completion. The restarted driver must
    // preserve the artifact and retry that registered item before it registers
    // a later item from the same candidate.
    const std::filesystem::path wal_restart_database =
        UniqueTestDirectory("store-wal-restart").string() + ".sqlite";
    std::filesystem::remove(wal_restart_database, cleanup_error);
    const ksi::edge::CandidateEventRecord wal_restart_candidate = {
        "evt-wal-restart", 0, "edge-wal", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 2U};
    const ksi::edge::EvidenceRecord wal_restart_first = {
        wal_restart_candidate.idempotency_key, "frame-wal-a.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    const ksi::edge::EvidenceRecord wal_restart_second = {
        wal_restart_candidate.idempotency_key, "frame-wal-b.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    {
        ksi::edge::SqliteStoreForward before_restart(wal_restart_database.string());
        Check(before_restart.Open() == ksi::edge::StoreForwardVerdict::kAccepted &&
                  before_restart.EnqueueCandidateWithEvidence(
                      wal_restart_candidate, {wal_restart_first, wal_restart_second}) ==
                      ksi::edge::StoreForwardVerdict::kAccepted &&
                  before_restart.AcknowledgeCandidate(wal_restart_candidate.idempotency_key) ==
                      ksi::edge::StoreForwardVerdict::kAccepted &&
                  before_restart.MarkEvidenceRegistered(wal_restart_candidate.idempotency_key,
                                                        wal_restart_first.artifact_id) ==
                      ksi::edge::StoreForwardVerdict::kAccepted,
              "WAL persists registered-but-unuploaded evidence before process restart");
    }
    ksi::edge::SqliteStoreForward after_restart(wal_restart_database.string());
    Check(after_restart.Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "WAL journal reopens after simulated process restart");
    ArtifactOrderedTransport wal_restart_transport;
    ksi::edge::StoreForwardSyncDriver wal_restart_driver(&after_restart);
    const auto wal_restart_report = wal_restart_driver.SynchronizeOnce(&wal_restart_transport);
    Check(wal_restart_report.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              wal_restart_transport.operations ==
                  std::vector<std::string>({"register:evt-wal-restart:frame-wal-a.rgb",
                                            "put:evt-wal-restart:frame-wal-a.rgb",
                                            "register:evt-wal-restart:frame-wal-b.rgb",
                                            "put:evt-wal-restart:frame-wal-b.rgb"}) &&
              after_restart.CandidateCount() == 0U &&
              vault.ReadAndVerify(persisted.artifact, &read).verdict ==
                  ksi::edge::ArtifactVaultVerdict::kPersisted,
          "WAL restart retries the earlier artifact first and preserves local bytes");

    const std::filesystem::path missing_headers_database =
        UniqueTestDirectory("store-no-headers").string() + ".sqlite";
    std::filesystem::remove(missing_headers_database, cleanup_error);
    ksi::edge::SqliteStoreForward missing_headers_store(missing_headers_database.string());
    Check(missing_headers_store.Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "separate journal opens for missing-header capability test");
    const ksi::edge::CandidateEventRecord missing_headers_candidate = {
        "evt-store-no-headers", 3, "edge-1", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord missing_headers_evidence = {
        "evt-store-no-headers", "frame-no-headers.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    Check(missing_headers_store.EnqueueCandidateWithEvidence(
              missing_headers_candidate, {missing_headers_evidence}) ==
              ksi::edge::StoreForwardVerdict::kAccepted,
          "missing-header registration candidate queued");
    EmptyHeadersTransport empty_headers_transport;
    ksi::edge::StoreForwardSyncDriver missing_headers_driver(&missing_headers_store);
    const auto empty_headers = missing_headers_driver.SynchronizeOnce(&empty_headers_transport);
    Check(empty_headers.verdict == ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              empty_headers_transport.put_calls == 0U &&
              missing_headers_store.PendingEvidenceRegistration().size() == 1U,
          "missing Core checksum headers never permit a bare upload URL");

    const ksi::edge::CandidateEventRecord malformed_url_candidate = {
        "evt-store-no-url", 3, "edge-1", kPayloadDigest, "{\"schemaVersion\":\"1.2\"}", 1U};
    const ksi::edge::EvidenceRecord malformed_url_evidence = {
        "evt-store-no-url", "frame-no-url.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    Check(store.EnqueueCandidateWithEvidence(malformed_url_candidate, {malformed_url_evidence}) ==
              ksi::edge::StoreForwardVerdict::kAccepted,
          "empty-URL registration candidate queued");
    EmptyUrlTransport empty_url_transport;
    const auto empty_url = driver.SynchronizeOnce(&empty_url_transport);
    Check(empty_url.verdict == ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              empty_url_transport.put_calls == 0U && store.PendingEvidenceRegistration().size() == 1U,
          "missing Core upload URL never falls back to a client-selected object path");
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove(missing_headers_database, cleanup_error);
    std::filesystem::remove(strict_order_database, cleanup_error);
    std::filesystem::remove(wal_restart_database, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

void TestCoreRestSyncWire() {
    const std::filesystem::path directory = UniqueTestDirectory("core-rest-wire-vault");
    const std::filesystem::path database = UniqueTestDirectory("core-rest-wire-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
    ksi::edge::ArtifactVault vault(directory.string(), 1024U);
    const auto persisted = vault.Persist(
        "frame-wire.rgb", reinterpret_cast<const std::uint8_t*>(kWireArtifactBytes.data()),
        kWireArtifactBytes.size());
    Check(persisted.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted &&
              persisted.artifact.content_digest == kWireArtifactDigest,
          "Core REST wire fixture persists checksum-bound evidence bytes");
    const std::string payload = CoreCandidatePayload();
    const ksi::edge::CandidateEventRecord candidate = {
        "journal-key-1", 7, "edge-1", ksi::edge::Sha256Digest(payload), payload, 1U};
    const ksi::edge::EvidenceRecord evidence = {
        candidate.idempotency_key, "frame-wire.rgb", "application/octet-stream",
        persisted.artifact.local_path, persisted.artifact.content_digest};
    RecordingHttpsExecutor executor;
    executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted,
                         ksi::edge::HttpsRequestVerdict::kCompleted,
                         ksi::edge::HttpsRequestVerdict::kCompleted};
    executor.responses = {{201, "{\"verdict\":\"ACCEPTED\"}"},
                          {201, EvidenceRegistrationJson()},
                          {200, ""}};
    ksi::edge::CoreRestSyncTransport transport(
        {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &executor, &vault);
    const auto candidate_ack = transport.UploadCandidate(candidate);
    const auto registration = transport.RegisterEvidence(candidate, evidence);
    const auto put = transport.PutEvidence(evidence, registration);
    Check(candidate_ack == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              registration.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              put == ksi::edge::CoreSyncVerdict::kAcknowledged,
          "Core REST transport performs candidate ACK, evidence registration, and checksum-bound PUT");
    Check(executor.requests.size() == 3U &&
              executor.requests[0].endpoint == ksi::edge::HttpsEndpoint::kCore &&
              executor.requests[0].method == "POST" &&
              executor.requests[0].url == "https://core.example.test/v1/edge-sync/event-bundles" &&
              executor.requests[0].headers.at("Authorization") == "Bearer edgeToken_123" &&
              executor.requests[0].headers.at("Content-Type") == "application/json" &&
              ToString(executor.requests[0].body).find("\"idempotencyKey\":\"journal-key-1\"") !=
                  std::string::npos &&
              ToString(executor.requests[0].body).find("\"payload\":" + payload) != std::string::npos,
          "Core REST candidate request is exactly a JournalEntry with Core bearer authorization");
    Check(executor.requests.size() == 3U &&
              executor.requests[1].endpoint == ksi::edge::HttpsEndpoint::kCore &&
              executor.requests[1].method == "POST" &&
              executor.requests[1].url ==
                  "https://core.example.test/v1/edge-sync/events/edge-1%3A%3Aevt-wire-1/evidence" &&
              executor.requests[1].headers.at("Authorization") == "Bearer edgeToken_123" &&
              ToString(executor.requests[1].body).find("\"contentDigest\":\"" +
                                                        kWireArtifactDigest + "\"") != std::string::npos,
          "evidence registration derives device-scoped eventKey from durable EventBundle eventId");
    Check(executor.requests.size() == 3U &&
              executor.requests[2].endpoint == ksi::edge::HttpsEndpoint::kEvidenceUpload &&
              executor.requests[2].method == "PUT" &&
              executor.requests[2].url.find("https://storage.example.test/") == 0U &&
              executor.requests[2].headers.find("Authorization") == executor.requests[2].headers.end() &&
              executor.requests[2].headers.at("Content-Type") == "application/octet-stream" &&
              executor.requests[2].headers.at("x-amz-checksum-sha256") == kWireArtifactChecksum &&
              ToString(executor.requests[2].body) == kWireArtifactBytes,
          "presigned evidence PUT carries only Core-issued checksum headers and never the Core bearer");

    if (ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        ksi::edge::SqliteStoreForward store(database.string());
        Check(store.Open() == ksi::edge::StoreForwardVerdict::kAccepted,
              "Core REST wire fixture opens SQLite journal");
        Check(store.EnqueueCandidateWithEvidence(candidate, {evidence}) ==
                  ksi::edge::StoreForwardVerdict::kAccepted,
              "Core REST wire fixture atomically records candidate and evidence");
        RecordingHttpsExecutor journal_executor;
        journal_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted,
                                     ksi::edge::HttpsRequestVerdict::kCompleted,
                                     ksi::edge::HttpsRequestVerdict::kCompleted};
        journal_executor.responses = {{201, "{\"verdict\":\"ACCEPTED\"}"},
                                      {201, EvidenceRegistrationJson()},
                                      {200, ""}};
        ksi::edge::CoreRestSyncTransport journal_transport(
            {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &journal_executor, &vault);
        ksi::edge::StoreForwardSyncDriver driver(&store);
        const auto report = driver.SynchronizeOnce(&journal_transport);
        Check(report.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
                  report.candidates_acked == 1U && report.registrations_acked == 1U &&
                  report.puts_acked == 1U && store.CandidateCount() == 0U,
              "store-forward driver resolves durable candidate context for the Core REST transport");
    }

    RecordingHttpsExecutor rejected_executor;
    rejected_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
    rejected_executor.responses = {{201, "{\"verdict\":\"ACCEPTED\"}"}};
    ksi::edge::CoreRestSyncTransport rejected_transport(
        {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &rejected_executor, &vault);
    ksi::edge::CandidateEventRecord malformed = candidate;
    malformed.payload_json = "{\"eventId\":\"../other-device\"}";
    malformed.payload_digest = ksi::edge::Sha256Digest(malformed.payload_json);
    Check(rejected_transport.UploadCandidate(malformed) == ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              rejected_executor.requests.empty(),
          "malformed EventBundle eventId is rejected before any Core request");

    RecordingHttpsExecutor noncanonical_executor;
    noncanonical_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
    noncanonical_executor.responses = {{201, "{\"verdict\":\"ACCEPTED\"}"}};
    ksi::edge::CoreRestSyncTransport noncanonical_transport(
        {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &noncanonical_executor, &vault);
    ksi::edge::CandidateEventRecord noncanonical = candidate;
    noncanonical.payload_json = "{ \"eventId\": \"evt-wire-1\"}";
    noncanonical.payload_digest = ksi::edge::Sha256Digest(noncanonical.payload_json);
    Check(noncanonical_transport.UploadCandidate(noncanonical) ==
                  ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              noncanonical_executor.requests.empty(),
          "non-canonical payload/digest pair is rejected locally before Core could calculate a different digest");

    RecordingHttpsExecutor capability_executor;
    capability_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
    capability_executor.responses = {{201, EvidenceRegistrationJson(
        "https://storage.example.test/upload#fragment-not-allowed")}};
    ksi::edge::CoreRestSyncTransport capability_transport(
        {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &capability_executor, &vault);
    const auto bad_capability = capability_transport.RegisterEvidence(candidate, evidence);
    Check(bad_capability.verdict == ksi::edge::CoreSyncVerdict::kPermanentFailure,
          "malformed presigned upload URL is fail-closed before any PUT");

    RecordingHttpsExecutor bearer_capability_executor;
    bearer_capability_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
    bearer_capability_executor.responses = {{
        201,
        EvidenceRegistrationJson("https://storage.example.test/upload",
                                 ",\"Authorization\":\"Bearer injected\"")}};
    ksi::edge::CoreRestSyncTransport bearer_capability_transport(
        {"https://core.example.test", "edgeToken_123", 4096U, 4096U}, &bearer_capability_executor,
        &vault);
    Check(bearer_capability_transport.RegisterEvidence(candidate, evidence).verdict ==
                  ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              bearer_capability_executor.requests.size() == 1U,
          "Core REST transport rejects a hostile upload capability that carries Authorization");

    const std::filesystem::path token_path = UniqueTestDirectory("edge-bearer-token");
    {
        std::ofstream token_file(token_path);
        token_file << "edgeToken_123\n";
    }
    (void)chmod(token_path.c_str(), 0600);
    const auto loaded_token = ksi::edge::LoadPrivateBearerTokenFile(token_path.string());
    Check(loaded_token.verdict == ksi::edge::PrivateBearerTokenVerdict::kLoaded &&
              loaded_token.bearer_token == "edgeToken_123",
          "private bearer loader accepts only a private regular deployment file");
    (void)chmod(token_path.c_str(), 0644);
    Check(ksi::edge::LoadPrivateBearerTokenFile(token_path.string()).verdict ==
              ksi::edge::PrivateBearerTokenVerdict::kUnsafeFile,
          "private bearer loader rejects group/world-readable token file");
    std::filesystem::remove(token_path, cleanup_error);
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

#if KSI_EDGE_HAVE_CURL_TRANSPORT
void TestCurlExecutorGuards() {
    const std::string pin = "sha256//" + std::string(43U, 'A') + "=";
    bool rejected_invalid_config = false;
    try {
        ksi::edge::CurlHttpsRequestExecutor invalid(
            {"http://core.example.test", pin, pin, "/private/ca.pem"});
        (void)invalid;
    } catch (const std::invalid_argument&) {
        rejected_invalid_config = true;
    }
    Check(rejected_invalid_config,
          "curl executor rejects an unencrypted Core origin before it can issue a request");
    ksi::edge::CurlHttpsRequestExecutor executor(
        {"https://core.example.test", pin, pin, "/private/ca.pem"});
    ksi::edge::HttpsRequest wrong_origin;
    wrong_origin.endpoint = ksi::edge::HttpsEndpoint::kCore;
    wrong_origin.method = "POST";
    wrong_origin.url = "https://other.example.test/v1/edge-sync/event-bundles";
    wrong_origin.maximum_response_bytes = 1024U;
    ksi::edge::HttpsResponse response;
    Check(executor.Execute(wrong_origin, &response) == ksi::edge::HttpsRequestVerdict::kPermanentFailure,
          "curl executor rejects a Core request whose authority differs from the pinned deployment origin");
    ksi::edge::HttpsRequest injected_header;
    injected_header.endpoint = ksi::edge::HttpsEndpoint::kEvidenceUpload;
    injected_header.method = "PUT";
    injected_header.url = "https://storage.example.test/upload";
    injected_header.headers = {{"Content-Type", "application/octet-stream\r\nAuthorization: leaked"}};
    injected_header.maximum_response_bytes = 1024U;
    Check(executor.Execute(injected_header, &response) == ksi::edge::HttpsRequestVerdict::kPermanentFailure,
          "curl executor rejects a header injection attempt before a TLS connection");
    ksi::edge::HttpsRequest leaked_bearer;
    leaked_bearer.endpoint = ksi::edge::HttpsEndpoint::kEvidenceUpload;
    leaked_bearer.method = "PUT";
    leaked_bearer.url = "https://storage.example.test/upload";
    leaked_bearer.headers = {{"Authorization", "Bearer edgeToken_123"}};
    leaked_bearer.maximum_response_bytes = 1024U;
    Check(executor.Execute(leaked_bearer, &response) == ksi::edge::HttpsRequestVerdict::kPermanentFailure,
          "curl executor refuses a Core bearer header on an evidence upload before a TLS connection");
}
#endif

void TestCandidateTimingArtifacts() {
    const ksi::edge::CandidateTimingObservation measured = ksi::edge::MeasureCandidateDurability(
        "evt-timing-1", 1'000'000LL, 1'750'000LL, false);
    Check(measured.verdict == ksi::edge::CandidateTimingVerdict::kMeasured &&
              measured.has_candidate_latency() && measured.candidate_latency_ns == 750'000LL,
          "candidate timing measures callback receipt through durable SQLite acceptance");
    const ksi::edge::CandidateTimingObservation rollback = ksi::edge::MeasureCandidateDurability(
        "evt-timing-rollback", 2'000'000LL, 1'999'999LL, false);
    Check(rollback.verdict == ksi::edge::CandidateTimingVerdict::kClockRollback &&
              !rollback.has_candidate_latency(),
          "candidate timing rejects a monotonic clock rollback rather than underflowing latency");
    const ksi::edge::CandidateTimingObservation unavailable = ksi::edge::MeasureCandidateDurability(
        "evt-timing-unavailable", 2'000'000LL, 0, false);
    Check(unavailable.verdict == ksi::edge::CandidateTimingVerdict::kClockUnavailable &&
              !unavailable.has_candidate_latency(),
          "candidate timing never substitutes a missing worker clock");
    const ksi::edge::CandidateTimingObservation duplicate = ksi::edge::MeasureCandidateDurability(
        "evt-timing-duplicate", 2'000'000LL, 9'000'000LL, true);
    Check(duplicate.verdict == ksi::edge::CandidateTimingVerdict::kDuplicateNotMeasured &&
              !duplicate.has_candidate_latency(),
          "SQLite duplicate retry cannot become a new candidate-latency sample");

    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-edge-runtime-event-timing-" + std::to_string(static_cast<long long>(getpid())));
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    ksi::edge::ArtifactVault vault(directory.string(), 4096U);
    ksi::edge::EventTimingArtifactWriter writer(&vault);
    const ksi::edge::EventTimingArtifactResult persisted = writer.PersistCandidateTiming(measured);
    Check(persisted.verdict == ksi::edge::EventTimingArtifactVerdict::kPersisted &&
              !persisted.artifact.local_path.empty(),
          "new candidate timing is fsync-backed in a private immutable artifact");
    std::vector<std::uint8_t> bytes;
    const ksi::edge::ArtifactVaultResult read = vault.ReadAndVerify(persisted.artifact, &bytes);
    const std::string timing_json(bytes.begin(), bytes.end());
    Check(read.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted &&
              timing_json.find("\"measurementStatus\":\"MEASURED\"") != std::string::npos &&
              timing_json.find("\"candidateLatencyNs\":750000") != std::string::npos &&
              timing_json.find("FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE") != std::string::npos,
          "timing artifact preserves typed stage and integer latency for replay validation");
    Check(writer.PersistCandidateTiming(measured).verdict ==
              ksi::edge::EventTimingArtifactVerdict::kDuplicate,
          "re-persisting identical timing evidence is idempotent");
    const ksi::edge::EventTimingArtifactResult unmeasured = writer.PersistCandidateTiming(rollback);
    Check(unmeasured.verdict == ksi::edge::EventTimingArtifactVerdict::kPersisted,
          "clock rollback becomes a durable NOT_MEASURED record instead of disappearing");
    std::vector<std::uint8_t> rollback_bytes;
    const ksi::edge::ArtifactVaultResult rollback_read =
        vault.ReadAndVerify(unmeasured.artifact, &rollback_bytes);
    const std::string rollback_json(rollback_bytes.begin(), rollback_bytes.end());
    Check(rollback_read.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted &&
              rollback_json.find("\"measurementStatus\":\"NOT_MEASURED\"") != std::string::npos &&
              rollback_json.find("\"reason\":\"CLOCK_ROLLBACK\"") != std::string::npos &&
              rollback_json.find("candidateLatencyNs") == std::string::npos,
          "unmeasured timing artifact cannot be mistaken for a bounded latency");
    Check(writer.PersistCandidateTiming(duplicate).verdict ==
              ksi::edge::EventTimingArtifactVerdict::kSkippedDuplicate,
          "duplicate retry does not overwrite or fabricate a timing artifact");
    std::filesystem::remove_all(directory, cleanup_error);
}

void TestPipeline() {
    ksi::edge::BoundedFrameQueue queue(2U, 64U);
    ksi::edge::TelemetryTimeline timeline(4U);
    const std::uint8_t frame[] = {1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U, 9U, 10U, 11U, 12U};
    Check(queue.PushFromCallback(frame, sizeof(frame), FrameMeta(1U, 2'000'000LL)) ==
              ksi::edge::FrameDropReason::kAccepted,
          "pipeline test frame queued");
    Check(timeline.Record(Telemetry(2'000'000LL)) == ksi::edge::TelemetryVerdict::kRecorded,
          "pipeline test telemetry queued");
    const std::filesystem::path database = UniqueTestDirectory("pipeline").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove(database, cleanup_error);
    ksi::edge::SqliteStoreForward store(database.string());
    (void)store.Open();
    ksi::edge::DfinePostprocessor postprocessor({{0U, "Vehicle_Truck"}}, 0.5F, 1U);
    ksi::edge::WorldStateTracker tracker(0.2F, 8U);
    ksi::edge::ConservativeRiskEngine risk(RiskPack());
    g_pipeline_monotonic_now_ns = 2'750'000LL;
    ksi::edge::EdgePipeline pipeline(&queue, &timeline, postprocessor, &tracker, &risk, &store, 50'000LL,
                                     false, &PipelineMonotonicNowNs);
    FakeInference inference;
    FakeProjector projector;
    FakeEvidenceBuilder evidence;
    const auto report = pipeline.ProcessOne(&inference, &projector, &evidence);
    if (ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        Check(report.verdict == ksi::edge::PipelineVerdict::kProcessed && report.world_entity_count == 1U &&
                  report.risk_field_count == 1U && report.durable_candidate_count == 1U &&
                  report.durable_candidates.size() == 1U &&
                  report.durable_candidates[0].idempotency_key == "evt-edge-track-0-1" &&
                  report.durable_candidates[0].risk_policy_pack_digest == kDigest &&
                  report.durable_candidates[0].candidate_timing.verdict ==
                      ksi::edge::CandidateTimingVerdict::kMeasured &&
                  report.durable_candidates[0].candidate_timing.candidate_latency_ns == 750'000LL,
              "bounded worker connects inference, WorldEntity, risk, and durable candidate");
    } else {
        Check(report.verdict == ksi::edge::PipelineVerdict::kNoDurableCandidate &&
                  report.world_entity_count == 1U && report.risk_field_count == 1U,
              "without SQLite backend pipeline keeps perception but refuses nondurable candidate");
    }
    std::filesystem::remove(database, cleanup_error);
}

std::string BuildNativeEventPayloadForOracle(
    std::vector<ksi::edge::EvidenceRecord>* evidence_output = nullptr,
    std::string* risk_field_id_output = nullptr) {
    if (!ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        return {};
    }
    const std::filesystem::path directory = UniqueTestDirectory("native-evidence");
    const std::filesystem::path database = UniqueTestDirectory("native-evidence-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
    std::string payload;
    {
        ksi::edge::ArtifactVault vault(directory.string(), 4096U);
        ksi::edge::SqliteStoreForward store(database.string());
        if (store.Open() != ksi::edge::StoreForwardVerdict::kAccepted) {
            return {};
        }
        ksi::edge::NativeCandidateEvidenceBuilder builder(
            {"edge-1", "mission-1", "site-1", "edge-runtime-test"}, &vault, &store);
        ksi::edge::TrackedWorldEntity tracked;
        tracked.entity_id = "edge-track-7-1";
        tracked.detection = {0U, 7U, "Vehicle_Truck", 0.9F, {10.0F, 20.0F, 30.0F, 40.0F}};
        tracked.telemetry = Telemetry(2'000'000LL);
        tracked.alignment_verdict = ksi::edge::AlignmentVerdict::kReceiveTimeOnly;
        tracked.observation_count = 1U;
        ksi::edge::ConservativeRiskEngine risk_engine(RiskPack());
        const auto risk = risk_engine.Build(Observation());
        if (risk.verdict != ksi::edge::RiskBuildVerdict::kBuilt || !risk.field.has_value()) {
            return {};
        }
        ksi::edge::FramePacket frame;
        frame.metadata = FrameMeta(7U, 2'000'000LL);
        frame.rgb = {1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U, 9U, 10U, 11U, 12U};
        ksi::edge::CandidateEvidenceDraft draft;
        if (builder.Build(frame, tracked, WorldEntity(), *risk.field, &draft) !=
            ksi::edge::CandidateEvidenceVerdict::kBuilt) {
            return {};
        }
        if (draft.candidate.payload_digest != ksi::edge::Sha256Digest(draft.candidate.payload_json)) {
            return {};
        }
        payload = draft.candidate.payload_json;
        if (evidence_output != nullptr) {
            *evidence_output = draft.evidence;
        }
        if (risk_field_id_output != nullptr) {
            *risk_field_id_output = risk.field->risk_field_id;
        }
        if (store.EnqueueCandidateWithEvidence(draft.candidate, draft.evidence) !=
            ksi::edge::StoreForwardVerdict::kAccepted) {
            return {};
        }
        if (store.PendingCandidates().size() != 1U || store.PendingCandidates()[0].payload_json != payload) {
            return {};
        }
    }
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
    return payload;
}

std::string BuildNativeArtifactsForOracle() {
    const ksi::edge::NativeWorldEntity entity = WorldEntity();
    const std::string world_json = ksi::edge::SerializeWorldEntityV10(entity);
    ksi::edge::ConservativeRiskEngine risk_engine(RiskPack());
    const auto risk = risk_engine.Build(Observation());
    if (world_json.empty() || risk.verdict != ksi::edge::RiskBuildVerdict::kBuilt ||
        !risk.field.has_value()) {
        return {};
    }
    const std::string risk_json = ksi::edge::SerializeRiskFieldV11(*risk.field);
    if (risk_json.empty()) {
        return {};
    }
    return "{\"worldEntity\":" + world_json + ",\"riskField\":" + risk_json + "}";
}

void TestNativeArtifactWire() {
    const std::string payload = BuildNativeArtifactsForOracle();
    Check(!payload.empty() && payload.find("\"worldEntity\"") != std::string::npos &&
              payload.find("\"riskField\"") != std::string::npos,
          "native WorldEntity and RiskField oracle payload is serializable");
}

void TestNativeEvidenceBuilder() {
    std::vector<ksi::edge::EvidenceRecord> evidence;
    std::string risk_field_id;
    const std::string payload = BuildNativeEventPayloadForOracle(&evidence, &risk_field_id);
    if (!ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        Check(payload.empty(), "native evidence oracle is unavailable without durable SQLite backend");
        return;
    }
    Check(!payload.empty() && payload.find("\"schemaVersion\":\"1.2\"") != std::string::npos &&
              payload.find("\"status\":\"CANDIDATE\"") != std::string::npos &&
              payload.find("CONFIRMED_EVENT") == std::string::npos,
          "native builder emits only contract-shaped nonterminal EventBundle candidate");
    const auto risk_evidence = std::find_if(
        evidence.begin(), evidence.end(), [&risk_field_id](const ksi::edge::EvidenceRecord& item) {
            return item.artifact_id == risk_field_id;
        });
    Check(risk_evidence != evidence.end() && risk_evidence->content_type == "application/json" &&
              payload.find("\"riskFieldArtifact\":\"" + risk_field_id + "\"") != std::string::npos,
          "RiskField evidence uses its contract ID and JSON type for Core CRITICAL verification");
    Check(ksi::edge::Sha256Digest(payload) ==
              "sha256:b1902be08ea8975a97a992541b07126eb30511688ed17f08087d4acf34c6211b",
          "native EventBundle bytes match Python canonical digest oracle");
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 6 && std::string(argv[1]) == "--inspect-native-activation") {
        std::int64_t now_utc_ms = 0;
        const std::string now_argument(argv[5]);
        const auto [end, error] = std::from_chars(now_argument.data(),
                                                   now_argument.data() + now_argument.size(),
                                                   now_utc_ms);
        if (error != std::errc{} || end != now_argument.data() + now_argument.size() ||
            now_utc_ms < 0) {
            std::fprintf(stderr, "invalid native activation timestamp\n");
            return 2;
        }
        const auto loaded = ksi::edge::LoadNativeActivationSnapshot(
            argv[2], argv[3], argv[4], now_utc_ms);
        std::printf("%s\n", ksi::edge::ToString(loaded.verdict));
        return 0;
    }
    if (argc == 8 && std::string(argv[1]) == "--inspect-native-runtime-profile") {
        const auto loaded = ksi::edge::LoadNativeRuntimeProfile(
            argv[2], argv[3], argv[4], argv[5], argv[6], argv[7]);
        std::printf("%s\n", ksi::edge::ToString(loaded.verdict));
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--emit-native-event") {
        const std::string payload = BuildNativeEventPayloadForOracle();
        if (payload.empty()) {
            std::fprintf(stderr, "native event oracle requires SQLite backend\n");
            return 2;
        }
        std::printf("%s\n", payload.c_str());
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--emit-native-artifacts") {
        const std::string payload = BuildNativeArtifactsForOracle();
        if (payload.empty()) {
            std::fprintf(stderr, "native artifact oracle could not build contract payload\n");
            return 2;
        }
        std::printf("%s\n", payload.c_str());
        return 0;
    }
    if (argc != 1) {
        std::fprintf(stderr,
                     "usage: %s [--emit-native-event|--emit-native-artifacts|"
                     "--inspect-native-activation <dir> <device> <runtime> <utc-ms>|"
                     "--inspect-native-runtime-profile <dir> <device> <dispatch> <mission> "
                     "<contract-digest> <policy-digest>]\n",
                     argv[0]);
        return 2;
    }
    TestSha256();
    TestNativeActivationHandoff();
    TestFrameQueue();
    TestTelemetryAlignment();
    TestDfineAndWorldEntity();
    TestProfiledGroundPlaneProjector();
    TestRiskAndShadow();
    TestArtifactVaultAndStoreForward();
    TestCoreRestSyncWire();
#if KSI_EDGE_HAVE_CURL_TRANSPORT
    TestCurlExecutorGuards();
#endif
    TestCandidateTimingArtifacts();
    TestPipeline();
    TestNativeArtifactWire();
    TestNativeEvidenceBuilder();
    if (g_failures == 0) {
        std::printf("edge runtime tests: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "edge runtime tests: %d/%d checks failed\n", g_failures, g_checks);
    return 1;
}

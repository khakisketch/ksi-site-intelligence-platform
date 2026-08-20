// Native Edge runtime contract tests — no external test framework or network.

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
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
#include "ksi/edge/flight_execution.hpp"
#include "ksi/edge/frame_queue.hpp"
#include "ksi/edge/jpeg_dimensions.hpp"
#include "ksi/edge/media_offload.hpp"
#include "ksi/edge/mission_kmz.hpp"
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

#ifndef KSI_EDGE_HAVE_OPENSSL_ATTESTATION
#define KSI_EDGE_HAVE_OPENSSL_ATTESTATION 0
#endif

#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
#include <openssl/evp.h>
#include <openssl/pem.h>
#endif

namespace {

int g_failures = 0;
int g_checks = 0;
int g_skipped_groups = 0;

void Check(bool condition, const char* what) {
    ++g_checks;
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

// SQLite 를 컴파일해 넣지 않은 호스트에서 통째로 건너뛰는 계약 묶음을 집계한다.
// 조용한 skip 은 "실패 0건"과 종료코드로 구분되지 않아, 초록불이 아무것도 주장하지
// 않는 상태를 만든다(tests/conftest.py 의 KSI_REQUIRE_REAL_MODEL 앵커와 같은 문제).
// 예전에는 다섯 자리가 Check(true, "... skipped on this host") 라는 위약 단언까지
// 넣어 skip 을 통과 카운트로 둔갑시켰다.
bool SqliteBackendReady(const char* what) {
    if (ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        return true;
    }
    ++g_skipped_groups;
    std::fprintf(stderr, "[SKIP] %s — SQLite 백엔드가 이 빌드에 없다\n", what);
    return false;
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

// KMZ 는 zip 이라 내용이 무엇이든 이 판독기에는 불투명한 바이트다 — 골든 입력은
// "zip 처럼 생겼는가"가 아니라 "digest 대조가 실제로 작동하는가"만 겨냥한다.
const std::string kMissionKmzBody = std::string("PK\x03\x04", 4) + "ksi-golden-wayline-bytes";

std::string MissionKmzSidecarBytes(const std::string& kmz_body,
                                   const std::string& device_id = "edge-001",
                                   const std::string& mission_id = "mission-edge-001",
                                   const std::string& contract_digest = kPayloadDigest) {
    return std::string("KSI_EDGE_NATIVE_MISSION_KMZ_V1\n") +
           "dispatch_id_b64=" + Base64UrlEncode("dispatch-001") + "\n" +
           "edge_device_id_b64=" + Base64UrlEncode(device_id) + "\n" +
           "kmz_byte_count=" + std::to_string(kmz_body.size()) + "\n" +
           "kmz_sha256=" +
           ksi::edge::Sha256Hex(reinterpret_cast<const std::uint8_t*>(kmz_body.data()),
                                kmz_body.size()) +
           "\n" + "mission_contract_digest=" + contract_digest + "\n" +
           "mission_id_b64=" + Base64UrlEncode(mission_id) + "\n";
}

void TestNativeMissionKmzHandoff() {
    const std::filesystem::path directory = UniqueTestDirectory("mission-kmz");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    Check(std::filesystem::create_directories(directory) && chmod(directory.c_str(), 0700) == 0,
          "mission KMZ test state directory is private");
    const std::filesystem::path sidecar = directory / ksi::edge::kNativeMissionKmzFilename;
    const std::filesystem::path kmz = directory / ksi::edge::kActiveMissionKmzFilename;

    const auto absent = ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001",
                                                        "mission-edge-001", kPayloadDigest);
    Check(absent.verdict == ksi::edge::NativeMissionKmzVerdict::kMissing,
          "absent sidecar means this activation bound no route, not an older one");

    Check(WritePrivateTextFile(kmz, kMissionKmzBody) &&
              WritePrivateTextFile(sidecar, MissionKmzSidecarBytes(kMissionKmzBody)),
          "private mission KMZ fixture writes");
    const auto loaded = ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001",
                                                        "mission-edge-001", kPayloadDigest);
    Check(loaded.verdict == ksi::edge::NativeMissionKmzVerdict::kLoaded &&
              loaded.kmz.dispatch_id == "dispatch-001" &&
              loaded.kmz.mission_id == "mission-edge-001" &&
              loaded.kmz.mission_contract_digest == kPayloadDigest &&
              loaded.kmz.bytes == kMissionKmzBody,
          "sidecar binds the route to one dispatch, mission, and contract digest");

    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-other", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kDeviceMismatch,
          "a copied route cannot cross the device boundary");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-other",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kMissionMismatch,
          "the route of a different mission is refused, not flown");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kContractMismatch,
          "a route left by a previous contract of the same mission is refused");

    // 길이는 그대로 두고 한 바이트만 바꾼다 — 크기 검사만으로는 절대 잡히지 않는
    // 변조이고, 이 판독기가 재해싱하는 유일한 이유다.
    std::string tampered = kMissionKmzBody;
    tampered.back() = static_cast<char>(tampered.back() ^ 0x01);
    Check(WritePrivateTextFile(kmz, tampered), "tampered mission KMZ fixture writes");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kDigestMismatch,
          "a single flipped byte in the route is caught by re-hashing on load");

    Check(WritePrivateTextFile(kmz, kMissionKmzBody.substr(0U, kMissionKmzBody.size() - 1U)),
          "truncated mission KMZ fixture writes");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kSizeMismatch,
          "a truncated route fails on the declared byte count before hashing");

    Check(std::filesystem::remove(kmz, cleanup_error),
          "mission KMZ removal for the orphaned-sidecar case");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kUnsafeKmz,
          "a sidecar without its route is a broken pair, not an absent route");

    Check(WritePrivateTextFile(kmz, kMissionKmzBody) &&
              WritePrivateTextFile(sidecar,
                                   MissionKmzSidecarBytes(kMissionKmzBody) + "unexpected=field\n"),
          "malformed mission KMZ sidecar fixture writes");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kMalformed,
          "an unknown sidecar field is not silently ignored");

    Check(WritePrivateTextFile(sidecar, MissionKmzSidecarBytes(kMissionKmzBody)) &&
              chmod(sidecar.c_str(), 0644) == 0,
          "loose-permission sidecar fixture writes");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kUnsafeSidecar,
          "a group-writable sidecar cannot describe the route this device flies");

    Check(WritePrivateTextFile(sidecar, MissionKmzSidecarBytes(kMissionKmzBody)) &&
              chmod(kmz.c_str(), 0644) == 0,
          "loose-permission mission KMZ fixture writes");
    Check(ksi::edge::LoadNativeMissionKmz(directory.string(), "edge-001", "mission-edge-001",
                                          kPayloadDigest)
                  .verdict == ksi::edge::NativeMissionKmzVerdict::kUnsafeKmz,
          "a group-writable route is refused even when its digest still matches");

    std::filesystem::remove_all(directory, cleanup_error);
}

// ── ADR-KSI-021 — flight_execution 픽스처 ────────────────────────────────────
//
// kSampleKmzBytesArray 는 실제 ksi_mission_planning.wpml.build_kmz() 산출물의
// 바이트 그대로다(uv run python3 로 생성, 3 웨이포인트·고도 40m 균일·
// wpml.py 의 DEFLATE 압축). 손으로 만든 zip 이 아니라 짝 구현이 실제로 내는
// 바이트를 쓰는 이유는 mission_kmz.hpp 재사용 원칙과 같다 — 판독기가 스스로
// 만든 입력이 아니라 실제 생산자의 산출물을 통과해야 한다.
constexpr unsigned char kSampleKmzBytesArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x21, 0x5c, 0xd8, 0xe6,
    0xd0, 0x56, 0xe3, 0x03, 0x00, 0x00, 0x80, 0x15, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x74, 0x65, 0x6d, 0x70, 0x6c, 0x61, 0x74, 0x65, 0x2e, 0x6b, 0x6d, 0x6c, 0xed,
    0x58, 0x4d, 0x73, 0xdb, 0x36, 0x10, 0xbd, 0xf7, 0x57, 0x64, 0x72, 0xf1, 0xa5, 0x11, 0x25, 0x35,
    0xcd, 0x87, 0x47, 0x46, 0xc6, 0x71, 0xfc, 0x35, 0xe3, 0x4e, 0x34, 0x91, 0x52, 0x4f, 0x8e, 0x30,
    0xb9, 0x14, 0x51, 0x83, 0x00, 0x0b, 0x82, 0x96, 0xd4, 0x5f, 0x5f, 0x90, 0x80, 0x28, 0x7c, 0x31,
    0x56, 0x3a, 0x9d, 0xc9, 0xc1, 0xbe, 0x49, 0xfb, 0xde, 0xdb, 0x05, 0x81, 0xc5, 0x5b, 0x0e, 0x67,
    0x1f, 0x36, 0x25, 0x7d, 0xf1, 0x00, 0xa2, 0x26, 0x9c, 0x9d, 0x1c, 0x4d, 0x46, 0xe3, 0xa3, 0x17,
    0xc0, 0x52, 0x9e, 0x11, 0xb6, 0x3a, 0x39, 0xfa, 0xba, 0xbc, 0x78, 0xf5, 0xee, 0xe8, 0x03, 0xfa,
    0x65, 0x76, 0xaf, 0x58, 0x8a, 0xc9, 0xea, 0x93, 0x97, 0x85, 0x94, 0xd5, 0x71, 0x92, 0xac, 0xd7,
    0xeb, 0x11, 0xaf, 0x80, 0xad, 0x48, 0x3d, 0x62, 0x20, 0x13, 0xc5, 0x48, 0xa6, 0xa3, 0xe9, 0x4b,
    0x4d, 0x3b, 0x5e, 0x57, 0x25, 0x75, 0xb8, 0xd9, 0x5f, 0x64, 0x94, 0xf2, 0x32, 0x51, 0xc0, 0x3f,
    0x89, 0xaa, 0xa3, 0xa8, 0x68, 0xf6, 0x89, 0xa7, 0x4d, 0x09, 0x4c, 0xa2, 0x59, 0xcb, 0x3f, 0x2e,
    0x49, 0xdd, 0xae, 0xe3, 0x8c, 0xb3, 0x9c, 0xac, 0x4c, 0x2c, 0xa7, 0xdb, 0x25, 0xbf, 0xc5, 0x5b,
    0x4a, 0x18, 0xfc, 0xc1, 0x33, 0x40, 0x35, 0xce, 0x81, 0x6e, 0x67, 0x49, 0x1c, 0x35, 0x22, 0xc2,
    0x48, 0x5d, 0x9c, 0xa6, 0x52, 0x65, 0x43, 0x2b, 0x7e, 0xc5, 0x4b, 0xd8, 0x09, 0x6c, 0x44, 0x93,
    0x61, 0x43, 0xe4, 0x67, 0xf6, 0xe5, 0xec, 0x86, 0xd7, 0x12, 0xc1, 0x06, 0xd2, 0x46, 0x42, 0xfb,
    0x5b, 0x93, 0x8c, 0xce, 0x21, 0xed, 0x74, 0x1d, 0x55, 0xc7, 0xfa, 0x5a, 0x1f, 0x71, 0x7a, 0xdf,
    0x6b, 0x42, 0x82, 0x96, 0x4a, 0x7c, 0x0f, 0x9f, 0xf3, 0x7c, 0xa1, 0x70, 0x41, 0xe4, 0xf6, 0x0a,
    0xc8, 0xaa, 0x90, 0x68, 0x3a, 0x36, 0xc2, 0x38, 0xac, 0xa5, 0x2b, 0xca, 0xef, 0x30, 0x5d, 0x0a,
    0xcc, 0x6a, 0xd2, 0x66, 0xc4, 0x74, 0x51, 0x01, 0x64, 0x68, 0xb2, 0x13, 0x0f, 0x11, 0xb4, 0x3c,
    0x13, 0x9c, 0xc1, 0x35, 0xcb, 0xb9, 0xfd, 0xff, 0x9c, 0x35, 0xe5, 0x9f, 0x98, 0x36, 0x80, 0xde,
    0x4f, 0x4c, 0x16, 0x2f, 0x6e, 0x91, 0x17, 0xcd, 0xdd, 0x3e, 0xee, 0xd0, 0x1d, 0xc4, 0x06, 0xac,
    0x7a, 0x95, 0x3a, 0x2b, 0x8e, 0xb3, 0x30, 0xb2, 0x57, 0xbe, 0x79, 0x63, 0xb4, 0x01, 0xe2, 0x08,
    0xe6, 0x5c, 0x3f, 0xdf, 0x35, 0xcb, 0x60, 0x83, 0xc6, 0xae, 0xc6, 0x05, 0x5d, 0x4c, 0xd7, 0x4e,
    0x62, 0x1d, 0x77, 0xc1, 0x69, 0x06, 0x62, 0x77, 0x48, 0x50, 0x56, 0x14, 0x4b, 0x58, 0x6e, 0x2b,
    0x40, 0x6b, 0xbc, 0xad, 0x38, 0x61, 0x72, 0x77, 0x42, 0x36, 0xe6, 0xd2, 0xaf, 0xb3, 0x7e, 0x31,
    0x56, 0x48, 0x73, 0xd6, 0xba, 0x53, 0xcf, 0x38, 0x17, 0xea, 0x86, 0x29, 0x64, 0xb1, 0xad, 0xe7,
    0x58, 0xe0, 0xd2, 0xe0, 0x69, 0x0f, 0x74, 0xcd, 0x7c, 0x7b, 0xb9, 0x78, 0xf7, 0xda, 0xe4, 0xf2,
    0x20, 0xcd, 0x2f, 0xba, 0xce, 0xe8, 0x02, 0x02, 0x54, 0x25, 0xf2, 0x00, 0x4b, 0xbe, 0x90, 0x58,
    0xc8, 0xb9, 0xb5, 0x58, 0x8b, 0x65, 0x22, 0x8f, 0xad, 0x03, 0x37, 0x92, 0x5f, 0xd0, 0x56, 0xa5,
    0x7b, 0xe7, 0x77, 0xa3, 0xf3, 0xe3, 0x76, 0x4b, 0x9a, 0x2e, 0x7d, 0xed, 0xf6, 0x61, 0xa4, 0x77,
    0x6f, 0xcd, 0x56, 0x2e, 0x1b, 0xc1, 0xba, 0x45, 0x49, 0xde, 0xad, 0xf6, 0x94, 0x65, 0x0b, 0xc9,
    0xab, 0x5b, 0x22, 0x8b, 0x4f, 0xa4, 0x4e, 0x39, 0x93, 0x84, 0x35, 0xaa, 0xfd, 0xcf, 0x1a, 0xf1,
    0x80, 0x65, 0x23, 0xc0, 0x49, 0x1c, 0x64, 0xb1, 0x4b, 0x7c, 0xad, 0x61, 0x21, 0x05, 0x6e, 0x4b,
    0xdf, 0xa8, 0xe7, 0x44, 0xee, 0x9a, 0x7c, 0xd4, 0x28, 0x49, 0xa9, 0xb0, 0x39, 0x91, 0x69, 0xd1,
    0xe5, 0x2b, 0x31, 0x6b, 0x30, 0xdd, 0x09, 0x3d, 0x30, 0xf6, 0x3c, 0x57, 0x80, 0x5b, 0xdb, 0xb4,
    0xf7, 0x71, 0xed, 0x42, 0x9d, 0x34, 0xe7, 0x94, 0xf2, 0xb5, 0xf1, 0xac, 0xfd, 0x79, 0x04, 0xbc,
    0x68, 0x86, 0x39, 0x96, 0x85, 0x95, 0xe5, 0x23, 0xce, 0x4e, 0x45, 0x1a, 0x4f, 0xd2, 0x53, 0xa3,
    0xdb, 0xe6, 0x2e, 0x76, 0x4e, 0x71, 0x0a, 0x25, 0x16, 0xf7, 0xea, 0x67, 0x8b, 0xa2, 0xd9, 0xbe,
    0xdd, 0x6a, 0x34, 0x99, 0xbe, 0xfd, 0xf5, 0xb7, 0xb7, 0x23, 0xd5, 0x04, 0x76, 0x74, 0x96, 0x18,
    0x6a, 0x97, 0x9d, 0x38, 0xb7, 0x50, 0xff, 0xd3, 0x48, 0x53, 0xc3, 0xa5, 0xdd, 0x0a, 0x3b, 0xcb,
    0xf0, 0xe3, 0x1e, 0xdb, 0xb8, 0x9a, 0x4f, 0xb6, 0xfb, 0xce, 0xca, 0x60, 0x3d, 0x4c, 0x24, 0x7f,
    0x70, 0x2e, 0x3d, 0xd6, 0x76, 0xcf, 0x80, 0x6c, 0x0f, 0x99, 0x3b, 0xd1, 0x19, 0xf8, 0xa5, 0xe0,
    0x4d, 0x15, 0x46, 0xac, 0x4b, 0xef, 0x46, 0x03, 0x66, 0x77, 0x3b, 0x5d, 0xcf, 0x8a, 0xa3, 0x81,
    0xf2, 0x9c, 0x65, 0x83, 0xba, 0x1e, 0x0b, 0x54, 0x7a, 0x66, 0xc2, 0xdf, 0x8d, 0x1a, 0xeb, 0x10,
    0x0a, 0xad, 0x56, 0xd3, 0xd1, 0xa5, 0x20, 0xab, 0x55, 0xef, 0x81, 0x4e, 0xac, 0x33, 0x3b, 0x01,
    0x38, 0x2d, 0x6c, 0x77, 0x09, 0x29, 0x31, 0xc0, 0xc9, 0xe7, 0xfc, 0x09, 0xb6, 0xce, 0xdb, 0x35,
    0x35, 0x38, 0x1b, 0x2c, 0xb9, 0xb8, 0x68, 0x58, 0x8a, 0xf4, 0x3d, 0xfc, 0xc2, 0xa5, 0x6a, 0x41,
    0x47, 0xe4, 0xb0, 0x86, 0xe4, 0xf6, 0x71, 0xfe, 0x87, 0x29, 0x62, 0x39, 0x81, 0xe9, 0xa9, 0x6f,
    0x58, 0x5d, 0xc1, 0x1a, 0x10, 0xe3, 0x42, 0x16, 0x8e, 0x55, 0x78, 0x04, 0x5b, 0xab, 0x57, 0xdf,
    0x6d, 0x3c, 0xbe, 0xab, 0x39, 0x55, 0xaf, 0x08, 0xa7, 0x6c, 0x45, 0xc1, 0xd1, 0x5b, 0xa4, 0xc0,
    0x9e, 0x34, 0x76, 0xce, 0xf0, 0x1d, 0xdd, 0x4f, 0xe0, 0x21, 0x7c, 0x40, 0xdd, 0x55, 0x44, 0xaf,
    0xde, 0x8f, 0x87, 0xe4, 0x9a, 0xe0, 0xae, 0x9b, 0x52, 0x27, 0xf5, 0xd8, 0x5b, 0xb1, 0x07, 0xc7,
    0xb5, 0x3a, 0xef, 0x90, 0x34, 0xac, 0xaa, 0x76, 0xf0, 0x3b, 0x45, 0x7d, 0x34, 0xaa, 0x8c, 0x95,
    0xf4, 0xc0, 0xf0, 0x7c, 0x96, 0xa4, 0x1c, 0x7a, 0x4e, 0x0f, 0x8e, 0x6b, 0x07, 0x55, 0x68, 0xb0,
    0x6f, 0x4d, 0x7b, 0x26, 0x43, 0x37, 0xc5, 0xbf, 0x36, 0x93, 0x83, 0xaf, 0x4d, 0xfb, 0x42, 0x39,
    0x2f, 0xb8, 0xe4, 0x3f, 0xe7, 0xce, 0xe4, 0x84, 0xaa, 0x97, 0xc3, 0x3c, 0x27, 0x1b, 0x74, 0x5f,
    0x93, 0xfe, 0x4d, 0xbc, 0x0f, 0x3a, 0xd9, 0x6f, 0x80, 0xd5, 0x5a, 0xbc, 0x26, 0x19, 0xb8, 0xc9,
    0xf7, 0x98, 0xe7, 0xe3, 0x73, 0x1f, 0x1f, 0xfb, 0x76, 0x1e, 0x30, 0x7e, 0xec, 0x18, 0x02, 0xe3,
    0x6c, 0xe7, 0x9f, 0x35, 0x35, 0x0f, 0x1a, 0xa0, 0xe3, 0xf1, 0xe4, 0xf1, 0x19, 0xba, 0x3b, 0xd5,
    0xa7, 0x38, 0x43, 0x27, 0xe1, 0x3e, 0x3f, 0x32, 0x43, 0x23, 0x8a, 0x83, 0x66, 0x68, 0x44, 0xf7,
    0x54, 0x66, 0xe8, 0xb3, 0x19, 0xfc, 0x6c, 0x33, 0x18, 0x8d, 0x95, 0x13, 0x1c, 0xee, 0x08, 0xd3,
    0x27, 0xec, 0x08, 0xd3, 0x1f, 0x76, 0x84, 0x88, 0xe2, 0x20, 0x47, 0x88, 0xe8, 0x9e, 0x1d, 0xe1,
    0xd9, 0x11, 0xfe, 0x17, 0x47, 0x48, 0x76, 0x1f, 0x96, 0x92, 0xfd, 0x17, 0xcf, 0xf6, 0x8b, 0x29,
    0xfa, 0x17, 0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x21, 0x5c,
    0x5a, 0xed, 0x6e, 0xbb, 0xa6, 0x03, 0x00, 0x00, 0x88, 0x16, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00,
    0x77, 0x70, 0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70,
    0x6d, 0x6c, 0xed, 0x58, 0x4d, 0x8f, 0xdb, 0x36, 0x10, 0xbd, 0xf7, 0x57, 0x04, 0xb9, 0xec, 0xa5,
    0xb1, 0x64, 0xb7, 0xcd, 0xc7, 0xc2, 0xcb, 0x60, 0xb3, 0x1f, 0xd9, 0x05, 0x52, 0xc4, 0x88, 0x9d,
    0x04, 0x3d, 0x72, 0xa5, 0x91, 0xc4, 0x9a, 0xe2, 0xa8, 0x14, 0xb5, 0xb6, 0xfb, 0xeb, 0x43, 0x89,
    0xb2, 0x4c, 0x4a, 0x54, 0xe3, 0x04, 0x01, 0x72, 0xa8, 0x6f, 0xf6, 0xbc, 0xf7, 0x86, 0x43, 0x72,
    0x66, 0x38, 0xd0, 0xfc, 0xf5, 0x36, 0xe7, 0x4f, 0x1e, 0x41, 0x96, 0x0c, 0xc5, 0xc5, 0xd9, 0x74,
    0x12, 0x9e, 0x3d, 0x01, 0x11, 0x61, 0xcc, 0x44, 0x7a, 0x71, 0xf6, 0x71, 0x75, 0xfb, 0xec, 0xe5,
    0xd9, 0x6b, 0xf2, 0xcb, 0x7c, 0xad, 0x59, 0x9a, 0x29, 0xca, 0x8b, 0xa7, 0x99, 0x52, 0xc5, 0x79,
    0x10, 0x6c, 0x36, 0x9b, 0x09, 0x16, 0x20, 0x52, 0x56, 0x4e, 0x04, 0xa8, 0x40, 0x33, 0x82, 0xd9,
    0x64, 0xf6, 0xd4, 0xd0, 0xce, 0x37, 0x45, 0xce, 0x1d, 0x6e, 0xfc, 0x37, 0x9b, 0x44, 0x98, 0x07,
    0x1a, 0xf8, 0x37, 0xd0, 0xeb, 0x68, 0x2a, 0x99, 0x5f, 0x63, 0x54, 0xe5, 0x20, 0x14, 0x99, 0xd7,
    0xfc, 0xf3, 0x9c, 0x95, 0x75, 0x1c, 0x57, 0x28, 0x12, 0x96, 0xb6, 0xb6, 0x84, 0xef, 0x56, 0xf8,
    0x99, 0xee, 0x38, 0x13, 0xf0, 0x27, 0xc6, 0x40, 0x4a, 0x9a, 0x00, 0xdf, 0xcd, 0x03, 0x3f, 0xda,
    0x8a, 0x98, 0x60, 0x65, 0x76, 0x19, 0x29, 0xed, 0x8d, 0xa4, 0x78, 0x87, 0x39, 0xec, 0x05, 0x36,
    0x62, 0xc8, 0xb0, 0x65, 0xea, 0xbd, 0xf8, 0x70, 0xf5, 0x0e, 0x4b, 0x45, 0x60, 0x0b, 0x51, 0xa5,
    0xa0, 0xfe, 0x6d, 0x48, 0xad, 0xce, 0x21, 0xed, 0x75, 0x0d, 0xd5, 0xd8, 0xba, 0xb5, 0xde, 0xd0,
    0x68, 0xdd, 0x69, 0x86, 0x04, 0x23, 0x55, 0x74, 0x0d, 0xef, 0x93, 0x64, 0xa9, 0x71, 0xc9, 0xd4,
    0xee, 0x0e, 0x58, 0x9a, 0x29, 0x32, 0x0b, 0x5b, 0xa1, 0x1f, 0x36, 0xd2, 0x94, 0xe3, 0x03, 0xe5,
    0x2b, 0x49, 0x45, 0xc9, 0x6a, 0x8f, 0x94, 0x2f, 0x0b, 0x80, 0x98, 0x4c, 0xf7, 0xe2, 0x31, 0x82,
    0x91, 0xc7, 0x12, 0x05, 0xdc, 0x8b, 0x04, 0xed, 0xff, 0x37, 0xa2, 0xca, 0x3f, 0x51, 0x5e, 0x01,
    0x79, 0x35, 0x6d, 0xbd, 0xf4, 0xec, 0x16, 0x79, 0x59, 0x3d, 0x1c, 0xec, 0x0e, 0xdd, 0x41, 0x6c,
    0xc0, 0x5a, 0xaf, 0xd0, 0x77, 0x85, 0x34, 0x1e, 0x5a, 0x0e, 0xca, 0xe7, 0xcf, 0x5b, 0xed, 0x00,
    0x71, 0x04, 0x0b, 0x34, 0xfb, 0xbb, 0x17, 0x31, 0x6c, 0x49, 0xe8, 0x6a, 0x5c, 0xd0, 0xc5, 0xcc,
    0xda, 0x81, 0x2f, 0xe3, 0x6e, 0x91, 0xc7, 0x20, 0xf7, 0x97, 0x04, 0x79, 0xc1, 0xa9, 0x82, 0xfb,
    0xb8, 0xf3, 0x6e, 0x99, 0x9c, 0x1c, 0x30, 0x37, 0xd4, 0x24, 0xa0, 0x04, 0x4d, 0x60, 0x8f, 0xb0,
    0xc2, 0xa5, 0xa2, 0x52, 0x2d, 0x90, 0x09, 0xe5, 0xe6, 0x83, 0x45, 0x36, 0x4e, 0x36, 0x26, 0x7f,
    0xad, 0x75, 0x0e, 0x16, 0xc3, 0xa0, 0x95, 0xc2, 0x5b, 0x5e, 0xcb, 0xcc, 0x5d, 0xfe, 0xd1, 0xf2,
    0xfa, 0xf6, 0xf9, 0x82, 0xd3, 0x08, 0x72, 0x2a, 0xd7, 0xfa, 0x67, 0xbd, 0x32, 0x99, 0x47, 0x88,
    0x52, 0x57, 0xb3, 0x0e, 0xba, 0x24, 0xd3, 0xd9, 0x8b, 0x5f, 0x7f, 0x7b, 0x31, 0xd1, 0x6a, 0xdb,
    0x3a, 0x0f, 0x5a, 0x6a, 0xe3, 0x92, 0x39, 0xc7, 0x69, 0xfe, 0x79, 0xf6, 0x4a, 0x7e, 0x0f, 0x7d,
    0xbb, 0x3a, 0xec, 0xa8, 0xa8, 0x7d, 0xba, 0xd1, 0xba, 0x56, 0x97, 0x79, 0x07, 0xb4, 0xee, 0x39,
    0x0b, 0x2a, 0x69, 0xee, 0x87, 0x9a, 0x03, 0x4b, 0x90, 0x73, 0xdc, 0xb4, 0x05, 0xdf, 0x73, 0x6b,
    0xf3, 0x46, 0x9c, 0xab, 0xcc, 0xf2, 0xf2, 0x86, 0xc6, 0x97, 0x32, 0xf2, 0x3b, 0xe9, 0xa8, 0x63,
    0xf0, 0x30, 0xcc, 0x55, 0x25, 0xc5, 0x98, 0xbd, 0x71, 0xa5, 0xb0, 0x39, 0xe7, 0x4b, 0x11, 0x2f,
    0x15, 0x16, 0x9f, 0x99, 0xca, 0xae, 0x59, 0x19, 0xa1, 0x50, 0x4c, 0x54, 0xba, 0xca, 0xaf, 0x2a,
    0xf9, 0x48, 0x55, 0x25, 0xfb, 0xdb, 0xea, 0xf4, 0x43, 0xb7, 0xd7, 0x34, 0x2f, 0x74, 0x34, 0xda,
    0x8d, 0xb2, 0x53, 0xc7, 0x8b, 0x7b, 0x60, 0x3b, 0x5a, 0xda, 0xb4, 0xa7, 0xb7, 0x12, 0xab, 0x62,
    0x68, 0xb1, 0x32, 0xd3, 0xb5, 0x0e, 0x98, 0x4d, 0xce, 0xbb, 0x15, 0xe9, 0x47, 0x07, 0xca, 0x1b,
    0x11, 0x8f, 0xea, 0x3a, 0x6c, 0xa0, 0x32, 0x2f, 0x02, 0xfc, 0x53, 0xe9, 0x47, 0x0b, 0x86, 0x42,
    0xeb, 0xdc, 0x8c, 0x75, 0x25, 0x59, 0x9a, 0x76, 0x15, 0xee, 0xd8, 0x56, 0xbb, 0xa2, 0xae, 0x5e,
    0x1a, 0x65, 0x76, 0xcd, 0x0e, 0x29, 0x3e, 0xc0, 0xf1, 0xe7, 0xfc, 0x19, 0x1c, 0x5d, 0xef, 0xd4,
    0xf4, 0xb3, 0x50, 0x51, 0x85, 0xf2, 0xb6, 0x12, 0x11, 0x49, 0x59, 0xae, 0x5b, 0xf7, 0x07, 0x54,
    0xba, 0x2e, 0x1d, 0x91, 0xc3, 0x1a, 0x93, 0xdb, 0xd7, 0xf9, 0x1d, 0x3d, 0xd2, 0x3c, 0x1e, 0x4d,
    0x04, 0x6d, 0x96, 0xff, 0x45, 0x75, 0x8d, 0x94, 0x40, 0x04, 0x4a, 0x95, 0xed, 0x5f, 0x17, 0x1f,
    0xc1, 0xd6, 0x9a, 0xe8, 0x9b, 0x83, 0xa7, 0x0f, 0x25, 0x72, 0xdd, 0x1a, 0x2e, 0x45, 0xca, 0xc1,
    0xd1, 0x5b, 0x24, 0x5b, 0xbb, 0x60, 0x2a, 0xca, 0x0c, 0x76, 0x23, 0xe8, 0x03, 0x3f, 0xbc, 0x2f,
    0x63, 0xf8, 0x88, 0xba, 0x59, 0x91, 0x3c, 0x7b, 0x15, 0x8e, 0xc9, 0x0d, 0xc1, 0x8d, 0x9b, 0x73,
    0xc7, 0x75, 0xd8, 0x8b, 0xb8, 0x07, 0xfb, 0xb5, 0xc6, 0xef, 0x98, 0x74, 0xb8, 0xaa, 0x3e, 0xc1,
    0xff, 0x58, 0xb4, 0x8f, 0x7a, 0x95, 0xbe, 0x25, 0x7b, 0xe0, 0xf0, 0x7e, 0x56, 0x2c, 0x1f, 0xdb,
    0x67, 0x0f, 0xf6, 0x6b, 0x47, 0x55, 0x64, 0x34, 0x6f, 0xdb, 0xf4, 0x0c, 0xc6, 0x2a, 0xa5, 0x5f,
    0x36, 0xd3, 0xa3, 0xcb, 0xa6, 0x1e, 0x97, 0x16, 0x19, 0x2a, 0xfc, 0x39, 0x35, 0x93, 0x30, 0xae,
    0x47, 0x9f, 0x24, 0x61, 0x5b, 0xb2, 0x2e, 0x59, 0x37, 0x67, 0x76, 0x46, 0xc7, 0xfb, 0x3b, 0x10,
    0xa5, 0x11, 0x6f, 0x58, 0x0c, 0xae, 0xf3, 0x03, 0x66, 0x24, 0x55, 0x09, 0x6f, 0x9b, 0x61, 0x6e,
    0xd1, 0xc7, 0xf7, 0x51, 0x8d, 0x33, 0xbe, 0xed, 0x1a, 0x06, 0x8d, 0xb3, 0x1e, 0x0a, 0xac, 0x51,
    0xe2, 0xa8, 0xa9, 0x22, 0x0c, 0xa7, 0x5f, 0x1f, 0x2c, 0xf6, 0xb7, 0x7a, 0x1a, 0x2c, 0x4e, 0x83,
    0x45, 0x33, 0x42, 0x4c, 0x87, 0xc9, 0xf7, 0x95, 0xc1, 0xc2, 0xa3, 0x38, 0x6a, 0xb0, 0xf0, 0xe8,
    0xfe, 0x2f, 0x83, 0xc5, 0xa9, 0x43, 0xfe, 0xec, 0x0e, 0x39, 0x09, 0x75, 0x7b, 0x3c, 0xbe, 0x4d,
    0xce, 0x4e, 0x6d, 0xf2, 0xd4, 0x26, 0xed, 0x86, 0x38, 0xfb, 0xe6, 0x36, 0xe9, 0x51, 0x1c, 0xd5,
    0x26, 0x3d, 0xba, 0x53, 0x9b, 0x3c, 0xb5, 0xc9, 0x1f, 0xd2, 0x26, 0x83, 0xfd, 0x07, 0xb6, 0xe0,
    0xf0, 0xe5, 0xb7, 0xfe, 0x72, 0x4c, 0xbe, 0x00, 0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x21, 0x5c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x77, 0x70, 0x6d, 0x7a, 0x2f, 0x72, 0x65, 0x73, 0x2f, 0x50,
    0x4b, 0x01, 0x02, 0x14, 0x03, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x21, 0x5c, 0xd8,
    0xe6, 0xd0, 0x56, 0xe3, 0x03, 0x00, 0x00, 0x80, 0x15, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x01, 0x00, 0x00, 0x00, 0x00, 0x77, 0x70, 0x6d,
    0x7a, 0x2f, 0x74, 0x65, 0x6d, 0x70, 0x6c, 0x61, 0x74, 0x65, 0x2e, 0x6b, 0x6d, 0x6c, 0x50, 0x4b,
    0x01, 0x02, 0x14, 0x03, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x21, 0x5c, 0x5a, 0xed,
    0x6e, 0xbb, 0xa6, 0x03, 0x00, 0x00, 0x88, 0x16, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x01, 0x12, 0x04, 0x00, 0x00, 0x77, 0x70, 0x6d, 0x7a,
    0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c, 0x50, 0x4b,
    0x01, 0x02, 0x14, 0x03, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x21, 0x5c, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x01, 0xe8, 0x07, 0x00, 0x00, 0x77, 0x70, 0x6d, 0x7a,
    0x2f, 0x72, 0x65, 0x73, 0x2f, 0x50, 0x4b, 0x05, 0x06, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x03,
    0x00, 0xb6, 0x00, 0x00, 0x00, 0x0f, 0x08, 0x00, 0x00, 0x00, 0x00,
};

// 아래 다섯은 손으로 만든 최소 zip 이다(STORED, method=0) — DEFLATE 를 안 써서
// wpml.py 짝 없이도 zlib.crc32 로 CRC 를 계산할 수 있다(파이썬 스크립트로 생성,
// 값은 kmz_probe 로 직접 검증했다). STORED 경로 자체(method==0 분기)를
// 검증하는 유일한 픽스처이기도 하다 — 실제 KMZ 는 항상 DEFLATE 다.
constexpr unsigned char kStoredValidWaylinesArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x90, 0x49,
    0x6b, 0x9f, 0x61, 0x00, 0x00, 0x00, 0x61, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c,
    0x3c, 0x6b, 0x6d, 0x6c, 0x3e, 0x3c, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75,
    0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e, 0x31, 0x30, 0x3c, 0x2f, 0x77, 0x70, 0x6d,
    0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75, 0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e,
    0x3c, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75, 0x74, 0x65, 0x48, 0x65, 0x69,
    0x67, 0x68, 0x74, 0x3e, 0x35, 0x30, 0x3c, 0x2f, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65,
    0x63, 0x75, 0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e, 0x3c, 0x2f, 0x6b, 0x6d, 0x6c,
    0x3e,
};

constexpr unsigned char kStoredNoWaypointsArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x6a, 0x33,
    0x44, 0x4a, 0x30, 0x00, 0x00, 0x00, 0x30, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c,
    0x3c, 0x6b, 0x6d, 0x6c, 0x3e, 0x3c, 0x44, 0x6f, 0x63, 0x75, 0x6d, 0x65, 0x6e, 0x74, 0x3e, 0x6e,
    0x6f, 0x20, 0x61, 0x6c, 0x74, 0x69, 0x74, 0x75, 0x64, 0x65, 0x20, 0x68, 0x65, 0x72, 0x65, 0x3c,
    0x2f, 0x44, 0x6f, 0x63, 0x75, 0x6d, 0x65, 0x6e, 0x74, 0x3e, 0x3c, 0x2f, 0x6b, 0x6d, 0x6c, 0x3e,
};

constexpr unsigned char kStoredMalformedValueArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x53, 0x87,
    0x00, 0x7f, 0x37, 0x00, 0x00, 0x00, 0x37, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c,
    0x3c, 0x6b, 0x6d, 0x6c, 0x3e, 0x3c, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75,
    0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e, 0x61, 0x62, 0x63, 0x3c, 0x2f, 0x77, 0x70,
    0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75, 0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74,
    0x3e, 0x3c, 0x2f, 0x6b, 0x6d, 0x6c, 0x3e,
};

constexpr unsigned char kStoredUnterminatedArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2c, 0x45,
    0x01, 0x24, 0x1b, 0x00, 0x00, 0x00, 0x1b, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c,
    0x3c, 0x6b, 0x6d, 0x6c, 0x3e, 0x3c, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75,
    0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e, 0x31, 0x30,
};

constexpr unsigned char kStoredNonFiniteArray[] = {
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x87, 0xba,
    0x91, 0x5d, 0x37, 0x00, 0x00, 0x00, 0x37, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x77, 0x70,
    0x6d, 0x7a, 0x2f, 0x77, 0x61, 0x79, 0x6c, 0x69, 0x6e, 0x65, 0x73, 0x2e, 0x77, 0x70, 0x6d, 0x6c,
    0x3c, 0x6b, 0x6d, 0x6c, 0x3e, 0x3c, 0x77, 0x70, 0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75,
    0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74, 0x3e, 0x6e, 0x61, 0x6e, 0x3c, 0x2f, 0x77, 0x70,
    0x6d, 0x6c, 0x3a, 0x65, 0x78, 0x65, 0x63, 0x75, 0x74, 0x65, 0x48, 0x65, 0x69, 0x67, 0x68, 0x74,
    0x3e, 0x3c, 0x2f, 0x6b, 0x6d, 0x6c, 0x3e,
};

const std::string kSampleKmzBytes(reinterpret_cast<const char*>(kSampleKmzBytesArray),
                                  sizeof(kSampleKmzBytesArray));
// bare hex — mission_kmz.hpp/NativeMissionKmz.kmz_sha256 표기 그대로. python3 -c
// "import hashlib;print(hashlib.sha256(open('sample.kmz','rb').read()).hexdigest())"
// 로 독립 계산해 대조했다.
const std::string kSampleKmzSha256 = "55c1015feadc617466550ce10c90fdfa7a83936f8f2b610748fb01dd92039708";
const std::string kStoredValidWaylinesBytes(reinterpret_cast<const char*>(kStoredValidWaylinesArray),
                                            sizeof(kStoredValidWaylinesArray));
const std::string kStoredNoWaypointsBytes(reinterpret_cast<const char*>(kStoredNoWaypointsArray),
                                          sizeof(kStoredNoWaypointsArray));
const std::string kStoredMalformedValueBytes(reinterpret_cast<const char*>(kStoredMalformedValueArray),
                                             sizeof(kStoredMalformedValueArray));
const std::string kStoredUnterminatedBytes(reinterpret_cast<const char*>(kStoredUnterminatedArray),
                                           sizeof(kStoredUnterminatedArray));
const std::string kStoredNonFiniteBytes(reinterpret_cast<const char*>(kStoredNonFiniteArray),
                                        sizeof(kStoredNonFiniteArray));

std::string FieldArmingTokenRawBytes(const std::string& nonce, const std::string& issuer, int stage,
                                     const std::string& device, const std::string& mission,
                                     const std::string& dispatch, std::int64_t issued_at,
                                     std::int64_t expires_at) {
    return "KSI_EDGE_FIELD_ARMING_TOKEN_V1\n"
           "nonce_b64=" +
           Base64UrlEncode(nonce) + "\n" + "issuer_b64=" + Base64UrlEncode(issuer) + "\n" +
           "stage=" + std::to_string(stage) + "\n" +
           "edge_device_id_b64=" + Base64UrlEncode(device) + "\n" +
           "mission_id_b64=" + Base64UrlEncode(mission) + "\n" +
           "dispatch_id_b64=" + Base64UrlEncode(dispatch) + "\n" +
           "issued_at_utc_ms=" + std::to_string(issued_at) + "\n" +
           "expires_at_utc_ms=" + std::to_string(expires_at) + "\n";
}

std::string AbortRequestRawBytes(const std::string& requested_by, const std::string& reason,
                                 std::int64_t requested_at, const std::string& mission_id = "",
                                 const std::string& dispatch_id = "") {
    std::string bytes = "KSI_EDGE_FLIGHT_ABORT_REQUEST_V1\n"
                        "requested_by_b64=" +
                        Base64UrlEncode(requested_by) + "\n" + "reason_b64=" +
                        Base64UrlEncode(reason) + "\n" + "requested_at_utc_ms=" +
                        std::to_string(requested_at) + "\n";
    if (!mission_id.empty()) {
        bytes += "mission_id_b64=" + Base64UrlEncode(mission_id) + "\n";
    }
    if (!dispatch_id.empty()) {
        bytes += "dispatch_id_b64=" + Base64UrlEncode(dispatch_id) + "\n";
    }
    return bytes;
}

constexpr std::int64_t kFlightUtcMs = 2'000'000'000'000LL;  // kUtcMs 와 겹치지 않는 별도 시간축.
const std::string kFlightMissionId = "mission-fx-001";
const std::string kFlightDispatchId = "dispatch-fx-001";
const std::string kFlightEdgeDeviceId = "edge-fx-001";
const std::string kFlightAircraftSerial = "AC-FX-0001";

ksi::edge::NativeActivationLoadResult FlightGoldenActivation() {
    ksi::edge::NativeActivationLoadResult result;
    result.verdict = ksi::edge::NativeActivationVerdict::kLoaded;
    result.snapshot.dispatch_id = kFlightDispatchId;
    result.snapshot.edge_device_id = kFlightEdgeDeviceId;
    result.snapshot.mission_id = kFlightMissionId;
    result.snapshot.context.mission_contract_digest = kPayloadDigest;
    result.snapshot.context.risk_policy_pack_digest = kDigest;
    result.snapshot.context.valid_from_utc_ms = kFlightUtcMs - 1000;
    result.snapshot.context.valid_until_utc_ms = kFlightUtcMs + 10'000'000LL;
    result.snapshot.activated_at_utc_ms = kFlightUtcMs;
    result.snapshot.runtime_version = "edge-runtime-flight-test";
    return result;
}

ksi::edge::CoreFlightAuthorization FlightGoldenCoreAuthorization(std::int64_t now_utc_ms) {
    ksi::edge::CoreFlightAuthorization auth;
    auth.verified = true;
    auth.authorized_stage = ksi::edge::FlightExecutionStage::kS2;
    auth.equipment_class = "M4D";
    auth.aircraft_serial_number = kFlightAircraftSerial;
    auth.edge_device_id = kFlightEdgeDeviceId;
    auth.mission_id = kFlightMissionId;
    auth.dispatch_id = kFlightDispatchId;
    auth.mission_contract_digest = kPayloadDigest;
    auth.issued_at_utc_ms = now_utc_ms - 10;
    auth.expires_at_utc_ms = now_utc_ms + 100'000LL;
    return auth;
}

ksi::edge::NativeMissionKmzLoadResult FlightGoldenKmz() {
    ksi::edge::NativeMissionKmzLoadResult result;
    result.verdict = ksi::edge::NativeMissionKmzVerdict::kLoaded;
    result.kmz.dispatch_id = kFlightDispatchId;
    result.kmz.edge_device_id = kFlightEdgeDeviceId;
    result.kmz.mission_id = kFlightMissionId;
    result.kmz.mission_contract_digest = kPayloadDigest;
    result.kmz.kmz_sha256 = kSampleKmzSha256;
    result.kmz.bytes = kSampleKmzBytes;
    return result;
}

ksi::edge::DeclaredFlightEnvelope FlightGoldenEnvelope() {
    ksi::edge::DeclaredFlightEnvelope envelope;
    envelope.allowed_volume_ids = {"vol-1"};
    envelope.min_altitude_m = 35.0;
    envelope.max_altitude_m = 45.0;  // kSampleKmzBytes 실측 고도(40m) 를 포함한다.
    return envelope;
}

ksi::edge::CeilingGuardInput FlightGoldenCeilingGuardInput() {
    ksi::edge::CeilingGuardInput input;
    input.has_dtm_coverage = true;
    input.aoi_terrain_elevation_samples_m = {100.0, 102.0, 105.0};
    input.takeoff_elevation_m = 101.0;
    input.site_density = ksi::edge::SiteDensityDeclaration::kGeneralArea;
    return input;
}

ksi::edge::AircraftPreconditionSnapshot FlightGoldenAircraft(std::int64_t now_utc_ms) {
    ksi::edge::AircraftPreconditionSnapshot aircraft;
    aircraft.flight_status_present = true;
    aircraft.flight_status = 0U;  // E_DjiFcSubscriptionFlightStatus::STOPED
    aircraft.flight_status_observed_utc_ms = now_utc_ms;
    aircraft.battery_present = true;
    aircraft.battery_percent_1pct = 80U;
    aircraft.battery_observed_utc_ms = now_utc_ms;
    aircraft.home_point_present = true;
    aircraft.home_point_set_status = 1U;  // SUCCESS
    aircraft.home_point_observed_utc_ms = now_utc_ms;
    aircraft.position_solution_present = true;
    aircraft.position_solution_property = 50U;
    aircraft.position_solution_observed_utc_ms = now_utc_ms;
    aircraft.flight_anomaly_present = true;
    aircraft.flight_anomaly_bits = 0U;
    aircraft.flight_anomaly_observed_utc_ms = now_utc_ms;
    aircraft.observed_aircraft_serial_number = kFlightAircraftSerial;
    return aircraft;
}

ksi::edge::AircraftPreconditionPolicy FlightGoldenAircraftPolicy() {
    ksi::edge::AircraftPreconditionPolicy policy;
    policy.minimum_battery_percent_1pct = 20U;
    policy.minimum_position_solution_property = 16U;
    policy.maximum_telemetry_age_ms = 5000;
    return policy;
}

ksi::edge::FlightExecutionRequest BuildGoldenFlightRequest(const std::string& arm_state_directory,
                                                           std::int64_t now_utc_ms,
                                                           ksi::edge::ShadowFlightSupervisor* supervisor,
                                                           ksi::edge::SqliteStoreForward* journal) {
    ksi::edge::FlightExecutionRequest request;
    request.requested_stage = ksi::edge::FlightExecutionStage::kS2;
    request.activation = FlightGoldenActivation();
    request.core_authorization = FlightGoldenCoreAuthorization(now_utc_ms);
    request.maximum_core_authorization_ttl_ms = 200'000;
    request.arming_state_directory = arm_state_directory;
    request.kmz = FlightGoldenKmz();
    request.declared_envelope = FlightGoldenEnvelope();
    request.ceiling_guard_input = FlightGoldenCeilingGuardInput();
    request.supervisor = supervisor;
    request.aircraft = FlightGoldenAircraft(now_utc_ms);
    request.aircraft_policy = FlightGoldenAircraftPolicy();
    request.journal = journal;
    return request;
}

void ArmForFlightTest(const std::string& state_directory, ksi::edge::FlightExecutionStage stage,
                      std::int64_t now_utc_ms, std::int64_t ttl_ms = 60'000) {
    static int counter = 0;
    ksi::edge::FieldArmingToken token;
    token.nonce = "test-nonce-" + std::to_string(++counter) + "-" + std::to_string(now_utc_ms);
    token.issuer = "test-issuer";
    token.stage = stage;
    token.edge_device_id = kFlightEdgeDeviceId;
    token.mission_id = kFlightMissionId;
    token.dispatch_id = kFlightDispatchId;
    token.issued_at_utc_ms = now_utc_ms;
    token.expires_at_utc_ms = now_utc_ms + ttl_ms;
    Check(ksi::edge::WriteFieldArmingToken(state_directory, token) ==
              ksi::edge::ArmingTokenWriteVerdict::kWritten,
          "flight execution arming fixture writes");
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

    // 부정형으로 바꿔 return 하면 안 된다 — 이 블록 뒤에는 SQLite 와 무관한 검사
    // (malformed eventId 거부·non-canonical digest 거부·presigned URL fail-closed·
    // Bearer 주입 거부)가 계속 이어진다. 감싸기만 하고 흐름은 그대로 둔다.
    if (SqliteBackendReady("Core REST wire + store-forward 저널 연동")) {
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

#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
void TestEvidenceAttestationSigner() {
    const std::filesystem::path directory = UniqueTestDirectory("evidence-attestation");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    Check(std::filesystem::create_directories(directory) && chmod(directory.c_str(), 0700) == 0,
          "attestation test directory is private");
    const std::filesystem::path key_path = directory / "device-attestation.pem";

    EVP_PKEY_CTX* key_context = EVP_PKEY_CTX_new_id(EVP_PKEY_ED25519, nullptr);
    EVP_PKEY* key = nullptr;
    const bool generated = key_context != nullptr && EVP_PKEY_keygen_init(key_context) == 1 &&
                           EVP_PKEY_keygen(key_context, &key) == 1;
    if (key_context != nullptr) {
        EVP_PKEY_CTX_free(key_context);
    }
    FILE* key_file = generated ? std::fopen(key_path.c_str(), "wb") : nullptr;
    const bool written = key_file != nullptr && PEM_write_PrivateKey(
                                                  key_file, key, nullptr, nullptr, 0, nullptr, nullptr) == 1;
    if (key_file != nullptr) {
        std::fclose(key_file);
    }
    Check(generated && written && chmod(key_path.c_str(), 0600) == 0,
          "test creates an ephemeral owner-only Ed25519 key, not a repository fixture");

    try {
        ksi::edge::EvidenceAttestationSigner signer("edge-key-1", key_path.string());
        const auto result = signer.Sign(
            "edge-1", "site-1", "mission-1", "edge-1::evt-wire-1", "frame-wire.rgb",
            "application/octet-stream", kWireArtifactDigest);
        Check(result.verdict == ksi::edge::EvidenceAttestationVerdict::kSigned &&
                  result.key_id == "edge-key-1" && result.signature_base64url.size() == 86U &&
                  result.signature_base64url.find('=') == std::string::npos &&
                  result.signature_base64url.find('+') == std::string::npos &&
                  result.signature_base64url.find('/') == std::string::npos,
              "Ed25519 evidence signature is unpadded base64url");

        RecordingHttpsExecutor executor;
        executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
        executor.responses = {{201, EvidenceRegistrationJson()}};
        ksi::edge::ArtifactVault vault((directory / "vault").string(), 1024U);
        const std::string payload = CoreCandidatePayload();
        const ksi::edge::CandidateEventRecord candidate = {
            "journal-key-attested", 8, "edge-1", ksi::edge::Sha256Digest(payload), payload, 1U};
        const ksi::edge::EvidenceRecord evidence = {
            candidate.idempotency_key, "frame-wire.rgb", "application/octet-stream",
            "unused-for-registration", kWireArtifactDigest};
        ksi::edge::CoreRestSyncTransport transport(
            {"https://core.example.test", "edgeToken_123", 4096U, 4096U, "edge-key-1",
             key_path.string()},
            &executor, &vault);
        const auto registration = transport.RegisterEvidence(candidate, evidence);
        const std::string request_body = executor.requests.empty()
                                             ? std::string{}
                                             : ToString(executor.requests.front().body);
        Check(registration.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
                  request_body.find("\"attestation\":{\"keyId\":\"edge-key-1\",") !=
                      std::string::npos &&
                  request_body.find("\"algorithm\":\"Ed25519\"") != std::string::npos,
              "Core evidence registration carries device attestation without private key material");
    } catch (const std::exception&) {
        Check(false, "owner-only Ed25519 attestation key loads and signs");
    }

    Check(chmod(key_path.c_str(), 0644) == 0, "test loosens key permissions for negative gate");
    bool loose_rejected = false;
    try {
        ksi::edge::EvidenceAttestationSigner rejected("edge-key-1", key_path.string());
    } catch (const std::exception&) {
        loose_rejected = true;
    }
    Check(loose_rejected, "group/world-readable attestation key is rejected");
    if (key != nullptr) {
        EVP_PKEY_free(key);
    }
    std::filesystem::remove_all(directory, cleanup_error);
}
#endif

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

void TestWorldStateTrackerEviction() {
    // max_tracks=1 forces the eviction question immediately: without it, once
    // the single slot is taken, a genuinely new, non-overlapping detection is
    // silently dropped for the rest of the mission.
    ksi::edge::WorldStateTracker tracker(0.5F, 1U, 2U);
    ksi::edge::TelemetryTimeline timeline(4U);
    Check(timeline.Record(Telemetry(1'000'000LL)) == ksi::edge::TelemetryVerdict::kRecorded,
          "eviction test telemetry queued");
    const auto alignment = timeline.Align(FrameMeta(1U, 1'020'000LL), 50'000LL);
    Check(alignment.sample.has_value(), "eviction test alignment carries a sample");

    ksi::edge::Detection first;
    first.class_id = 0U;
    first.class_name = "Person";
    first.confidence = 0.9F;
    first.box = {0.0F, 0.0F, 10.0F, 10.0F};
    const auto first_update = tracker.Update({first}, alignment, FrameMeta(1U));
    Check(first_update.size() == 1U && tracker.track_count() == 1U,
          "first detection occupies the only track slot");
    const std::string first_track_id = first_update.front().entity_id;

    // Two frames with nothing to match keeps the stale track alive (missed
    // count has not yet exceeded max_missed_frames=2).
    Check(tracker.Update({}, alignment, FrameMeta(2U)).empty() && tracker.track_count() == 1U,
          "one missed frame does not evict yet");
    Check(tracker.Update({}, alignment, FrameMeta(3U)).empty() && tracker.track_count() == 1U,
          "two missed frames does not evict yet (boundary is exclusive)");

    // A different, non-overlapping detection on the frame that pushes the
    // stale track past max_missed_frames: it must be evicted and replaced,
    // not silently dropped because the tracker was "full".
    ksi::edge::Detection second;
    second.class_id = 1U;
    second.class_name = "Vehicle";
    second.confidence = 0.9F;
    second.box = {100.0F, 100.0F, 110.0F, 110.0F};
    const auto second_update = tracker.Update({second}, alignment, FrameMeta(4U));
    Check(second_update.size() == 1U && tracker.track_count() == 1U,
          "a genuinely new detection registers once the stale track is evicted");
    Check(second_update.front().entity_id != first_track_id,
          "the evicted track's id is not silently reused for the new detection");
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
    // 이 헬퍼와 아래 TestNativeEvidenceOracle 의 단언은 한 쌍이다 — 여기서 빈 문자열을
    // 돌려주고 저쪽이 "비었다"를 단언하면, 제품 코드는 한 번도 안 불리고 테스트가 자기
    // 픽스처를 확인하는 자기참조가 된다. 그래서 skip 집계는 여기 한 번만 올린다.
    if (!SqliteBackendReady("native evidence oracle 계약")) {
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
        // 단언하지 않는다 — payload 는 위 헬퍼가 무조건 {} 를 돌려준 결과이고
        // 제품 코드(NativeCandidateEvidenceBuilder)는 이 경로에서 불리지 않는다.
        // 그것을 Check 로 세면 통과 카운트만 늘고 아무것도 주장하지 않는다.
        // skip 집계는 헬퍼 쪽에서 이미 올렸다.
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

// ── 원본 사진 자동 회수 (트랙 C) ────────────────────────────────────────────

// 최소 JPEG. APP0/JFIF 를 앞에 두어 SOF 앞 세그먼트를 제대로 건너뛰는지도 본다.
std::vector<std::uint8_t> MakeJpeg(std::uint8_t start_of_frame, std::uint32_t width,
                                   std::uint32_t height, bool with_app0 = true) {
    std::vector<std::uint8_t> bytes = {0xFFU, 0xD8U};
    if (with_app0) {
        const std::vector<std::uint8_t> app0 = {
            0xFFU, 0xE0U, 0x00U, 0x10U, 'J',   'F',   'I',   'F',   0x00U,
            0x01U, 0x01U, 0x00U, 0x00U, 0x01U, 0x00U, 0x01U, 0x00U, 0x00U};
        bytes.insert(bytes.end(), app0.begin(), app0.end());
    }
    const std::vector<std::uint8_t> frame_header = {0xFFU, start_of_frame, 0x00U, 0x11U, 0x08U};
    bytes.insert(bytes.end(), frame_header.begin(), frame_header.end());
    bytes.push_back(static_cast<std::uint8_t>((height >> 8U) & 0xFFU));
    bytes.push_back(static_cast<std::uint8_t>(height & 0xFFU));
    bytes.push_back(static_cast<std::uint8_t>((width >> 8U) & 0xFFU));
    bytes.push_back(static_cast<std::uint8_t>(width & 0xFFU));
    bytes.push_back(0x03U);
    for (std::uint8_t component = 1U; component <= 3U; ++component) {
        bytes.push_back(component);
        bytes.push_back(0x11U);
        bytes.push_back(0x00U);
    }
    bytes.push_back(0xFFU);
    bytes.push_back(0xD9U);
    return bytes;
}

void TestJpegDimensionGolden() {
    using ksi::edge::JpegDimensionsVerdict;
    const auto baseline = MakeJpeg(0xC0U, 5472U, 3648U);
    const auto parsed = ksi::edge::ReadJpegDimensions(baseline.data(), baseline.size());
    Check(parsed.verdict == JpegDimensionsVerdict::kParsed && parsed.dimensions.width == 5472U &&
              parsed.dimensions.height == 3648U,
          "JPEG SOF0 golden yields the exact declared pixel dimensions past APP0");
    const auto progressive = MakeJpeg(0xC2U, 4000U, 3000U, false);
    const auto progressive_parsed =
        ksi::edge::ReadJpegDimensions(progressive.data(), progressive.size());
    Check(progressive_parsed.verdict == JpegDimensionsVerdict::kParsed &&
              progressive_parsed.dimensions.width == 4000U &&
              progressive_parsed.dimensions.height == 3000U,
          "JPEG SOF2 progressive golden parses without an APP0 segment");
    const auto extended = MakeJpeg(0xC1U, 1U, 1U);
    Check(ksi::edge::ReadJpegDimensions(extended.data(), extended.size()).verdict ==
              JpegDimensionsVerdict::kParsed,
          "JPEG SOF1 extended sequential is accepted");
    const auto lossless = MakeJpeg(0xC3U, 100U, 100U);
    Check(ksi::edge::ReadJpegDimensions(lossless.data(), lossless.size()).verdict ==
              JpegDimensionsVerdict::kUnsupportedFrame,
          "SOF3 lossless is refused rather than read at the same offsets we never measured");
    const std::vector<std::uint8_t> not_jpeg = {'P', 'N', 'G', 0x00U, 0x01U};
    Check(ksi::edge::ReadJpegDimensions(not_jpeg.data(), not_jpeg.size()).verdict ==
              JpegDimensionsVerdict::kNotJpeg,
          "non-JPEG bytes are refused, never guessed");
    std::vector<std::uint8_t> truncated = baseline;
    truncated.resize(truncated.size() - 12U);
    Check(ksi::edge::ReadJpegDimensions(truncated.data(), truncated.size()).verdict ==
              JpegDimensionsVerdict::kTruncated,
          "a frame header cut short is TRUNCATED, not a partially read dimension");
    const std::vector<std::uint8_t> scan_first = {0xFFU, 0xD8U, 0xFFU, 0xDAU, 0x00U, 0x03U, 0x00U};
    Check(ksi::edge::ReadJpegDimensions(scan_first.data(), scan_first.size()).verdict ==
              JpegDimensionsVerdict::kMalformed,
          "entropy scan reached before any frame header is a typed failure");
    const auto zero_height = MakeJpeg(0xC0U, 640U, 0U);
    Check(ksi::edge::ReadJpegDimensions(zero_height.data(), zero_height.size()).verdict ==
              JpegDimensionsVerdict::kMalformed,
          "DNL-deferred height of zero is refused instead of reported as zero pixels");
}

void TestMediaIdConvention() {
    // ═══════════════════════════════════════════════════════════════════════
    // mediaId 유도 골든 — **두 구현이 이 표를 함께 만족해야 한다.**
    //
    //   자동 경로  edge/manifold-runtime/.../media_offload.cpp :: DeriveMediaId
    //   수동 경로  apps/dashboard/src/lib/source-upload.ts     :: deriveMediaId
    //
    // 아래 11행은 apps/dashboard/test/source-upload.test.ts 의 MEDIA_ID_GOLDEN
    // 과 **같은 입력·같은 기대값**이다. 한쪽만 고치면 이 시험이나 저쪽 vitest 중
    // 하나가 반드시 깨진다 — 자동/수동이 같은 사진을 다른 이름으로 부르는 순간
    // Core 번들에 같은 장이 두 벌 쌓이고 sourceBundleDigest 가 장수를 거짓으로
    // 말하기 때문이다.
    // ═══════════════════════════════════════════════════════════════════════
    const std::vector<std::pair<std::string, std::string>> media_id_golden = {
        {"DJI_0001.JPG", "DJI_0001"},
        {"DJI_0001.jpg", "DJI_0001"},
        {"DJI_0001.DNG", "DJI_0001"},
        {"DJI_20260816120000_0042_D.JPG", "DJI_20260816120000_0042_D"},
        {"noextension", "noextension"},
        {"a.b.jpg", "a.b"},
        {".hidden", "hidden"},
        {"사진 001 (1).jpg", "001-1-"},
        {"__leading.jpg", "leading"},
        {"！！！.jpg", "media"},
        {"!!!", "media"},
    };
    bool golden_matches = true;
    for (const auto& row : media_id_golden) {
        if (ksi::edge::DeriveMediaId(row.first) != row.second) {
            golden_matches = false;
            std::fprintf(stderr, "  mediaId golden mismatch: %s -> %s (expected %s)\n",
                         row.first.c_str(), ksi::edge::DeriveMediaId(row.first).c_str(),
                         row.second.c_str());
        }
    }
    Check(golden_matches,
          "DeriveMediaId matches the dashboard's shared mediaId golden table row for row");
    Check(ksi::edge::DeriveMediaId(std::string(200U, 'x') + ".JPG").size() == 120U,
          "mediaId is truncated to the shared 120 byte bound");
    Check(ksi::edge::DeriveMediaId("DJI_0007.JPG") == ksi::edge::DeriveMediaId("DJI_0007.jpeg"),
          "the same photo spelled JPG or jpeg derives one mediaId, as the manual path asserts");

    // ═══════════════════════════════════════════════════════════════════════
    // mediaId 충돌 접미사 골든 — **두 구현이 이 표를 함께 만족해야 한다.**
    //
    //   자동 경로  edge/manifold-runtime/.../media_offload.cpp :: AssignMediaIds
    //   수동 경로  apps/dashboard/src/lib/source-upload.ts     :: assignUniqueMediaIds
    //
    // 접미사는 카메라 원본 파일명(확장자 포함) **문자열 자체**의 sha256 앞 8 hex
    // 다(파일 바이트가 아니다) — 그래서 목록 순서·선택 순서와 무관하다. 아래 값은
    // 이 파일의 Sha256Digest·Python hashlib·Node crypto 세 구현으로 각각 계산해
    // 손으로 대조했다. source-upload.test.ts 의 MEDIA_ID_ASSIGN_GOLDEN 과
    // **같은 표**다 — 한쪽만 고치면 이 시험이나 저쪽 vitest 중 하나가 반드시
    // 깨진다.
    // ═══════════════════════════════════════════════════════════════════════
    const std::vector<std::pair<std::vector<std::string>, std::vector<std::string>>>
        media_id_assign_golden = {
            // 충돌 없음 — 접미사가 붙지 않는다.
            {{"DJI_0001.JPG", "DJI_0002.JPG"}, {"DJI_0001", "DJI_0002"}},
            // 2건 충돌 — RAW+JPEG 동시 저장.
            {{"DJI_0001.JPG", "DJI_0001.DNG"}, {"DJI_0001-1bb98f97", "DJI_0001-4dbbd212"}},
            // 3건 이상 충돌 — RAW+JPEG+독자 포맷 동시 저장.
            {{"DJI_0002.JPG", "DJI_0002.DNG", "DJI_0002.RAW"},
             {"DJI_0002-4dce79c7", "DJI_0002-f17a8db3", "DJI_0002-f7bbac27"}},
            // 확장자 대소문자만 다른 충돌.
            {{"DJI_0003.jpg", "DJI_0003.JPG"}, {"DJI_0003-4a4d0317", "DJI_0003-e48ae859"}},
            // 비ASCII 파일명 충돌 — 둘 다 유도 결과가 "media" 로 무너진 뒤 갈라진다.
            {{"사진.jpg", "사진.png"}, {"media-a3b204f6", "media-66df4728"}},
        };
    bool assign_golden_matches = true;
    for (const auto& [names, expected] : media_id_assign_golden) {
        std::vector<std::string> actual;
        const bool ok = ksi::edge::AssignMediaIds(names, &actual);
        if (!ok || actual != expected) {
            assign_golden_matches = false;
            std::fprintf(stderr, "  mediaId assign golden mismatch for list starting %s (ok=%d)\n",
                         names.front().c_str(), ok);
        }
    }
    Check(assign_golden_matches,
          "AssignMediaIds matches the dashboard's shared assign-golden table row for row");

    std::vector<std::string> ids;
    Check(ksi::edge::AssignMediaIds({"DJI_0001.JPG", "DJI_0002.JPG"}, &ids) && ids.size() == 2U &&
              ids[0] == "DJI_0001" && ids[1] == "DJI_0002",
          "a list without collisions keeps the plain derived ids");
    std::vector<std::string> raw_pair;
    Check(ksi::edge::AssignMediaIds({"DJI_0001.JPG", "DJI_0001.DNG"}, &raw_pair) &&
              raw_pair[0] != raw_pair[1] && raw_pair[0].rfind("DJI_0001-", 0U) == 0U &&
              raw_pair[1].rfind("DJI_0001-", 0U) == 0U,
          "RAW+JPEG pairs that share a stem are split by a suffix instead of silently merging");
    std::vector<std::string> reordered;
    Check(ksi::edge::AssignMediaIds({"DJI_0001.DNG", "DJI_0001.JPG"}, &reordered) &&
              reordered[0] == raw_pair[1] && reordered[1] == raw_pair[0],
          "the collision suffix is derived from the file name, so list order never changes it");
    std::vector<std::string> three_way;
    Check(ksi::edge::AssignMediaIds({"DJI_0002.RAW", "DJI_0002.JPG", "DJI_0002.DNG"}, &three_way) &&
              three_way[0] == "DJI_0002-f7bbac27" && three_way[1] == "DJI_0002-4dce79c7" &&
              three_way[2] == "DJI_0002-f17a8db3",
          "a 3-way collision reordered still matches the golden table row by row");
    std::vector<std::string> rejected;
    Check(!ksi::edge::AssignMediaIds({"DJI_0001.JPG", "DJI_0001.JPG"}, &rejected),
          "a duplicated camera file name is refused rather than assigned an invented id");
    Check(!ksi::edge::AssignMediaIds({""}, &rejected),
          "an empty camera file name is refused rather than turned into the fallback id");

    // ═══════════════════════════════════════════════════════════════════════
    // NFC/NFD 경계 - DeriveMediaId 와 대시보드의 deriveMediaId 동치는 **ASCII
    // 파일명 한정**이다(media_offload.hpp 상단 주석). 카메라 파일명은 ASCII 라
    // 실무 영향은 없지만, 그 경계를 명시 케이스로 남긴다 - 아래 두 문자열은
    // 화면에는 똑같이 보이는 서로 다른 정규화 형태다: 하나는 완성형 e-acute
    // 한 코드포인트(U+00E9), 하나는 자모분리형 e + 결합 억음부호(U+0065 U+0301).
    // \u 이스케이프로 명시했다 - 소스에 두 형태를 직접 타이핑하면 편집기·터미널이
    // 조용히 한쪽으로 정규화할 위험이 있어서다.
    // ═══════════════════════════════════════════════════════════════════════
    Check(ksi::edge::DeriveMediaId("café.jpg") == "caf-",
          "precomposed e-acute (1 codepoint, 2 UTF-8 bytes) collapses whole into one dash");
    Check(ksi::edge::DeriveMediaId("café.jpg") == "cafe-",
          "decomposed e + combining accent keeps the ASCII e - this diverges from the dashboard "
          "(which normalizes to NFC first) and from the precomposed form above; both are correct "
          "per this function's byte-level rule, the divergence is the documented ASCII-only boundary");
}

void TestArtifactVaultRemoval() {
    const std::filesystem::path directory = UniqueTestDirectory("vault-remove");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    ksi::edge::ArtifactVault vault(directory.string(), 4096U);
    const std::uint8_t bytes[] = {7U, 7U, 7U};
    const auto persisted = vault.Persist("spooled-1.jpg", bytes, sizeof(bytes));
    Check(persisted.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted,
          "removal fixture persists a spool artifact");
    Check(vault.Remove("spooled-1.jpg") == ksi::edge::ArtifactRemovalVerdict::kRemoved &&
              !std::filesystem::exists(persisted.artifact.local_path),
          "vault removal frees the file so the conveyor can keep moving");
    Check(vault.Remove("spooled-1.jpg") == ksi::edge::ArtifactRemovalVerdict::kAlreadyAbsent,
          "removing an already absent artifact is idempotent for restart recovery");
    Check(vault.Remove("../escape") == ksi::edge::ArtifactRemovalVerdict::kInvalidArtifactId,
          "vault removal never accepts a traversing artifact id");
    const std::filesystem::path outside = UniqueTestDirectory("vault-remove-outside");
    std::filesystem::remove_all(outside, cleanup_error);
    Check(std::filesystem::create_directories(outside), "removal fixture creates an outside file");
    {
        std::ofstream victim(outside / "victim");
        victim << "not ours";
    }
    std::filesystem::create_symlink(outside / "victim", directory / "linked.jpg", cleanup_error);
    Check(vault.Remove("linked.jpg") == ksi::edge::ArtifactRemovalVerdict::kUnsafeArtifact &&
              std::filesystem::exists(outside / "victim"),
          "vault removal refuses a symlink and leaves its target intact");
    std::filesystem::remove_all(directory, cleanup_error);
    std::filesystem::remove_all(outside, cleanup_error);
}

class FakeSourceMediaTransport final : public ksi::edge::IEdgeSourceMediaTransport {
public:
    ksi::edge::CoreSyncVerdict register_verdict = ksi::edge::CoreSyncVerdict::kAcknowledged;
    ksi::edge::CoreSyncVerdict put_verdict = ksi::edge::CoreSyncVerdict::kAcknowledged;
    ksi::edge::CoreSyncVerdict seal_verdict = ksi::edge::CoreSyncVerdict::kAcknowledged;
    std::vector<std::string> registered;
    std::vector<std::string> uploaded;
    std::map<std::string, std::string> issued_urls;
    int register_calls = 0;
    int seal_calls = 0;
    // 시험 전용 관찰 훅 — 설정돼 있으면 PutSourceMedia(네트워크 배출)가 실제로
    // 불리는 그 순간 카메라 권한 상태를 본다. 저널·스풀과 달리 전송은
    // 인터페이스라 이 관찰이 가능하다.
    const ksi::edge::FakeMediaSourcePort* rights_observer = nullptr;
    bool put_observed = false;
    bool rights_held_during_any_put = false;

    ksi::edge::SourceMediaRegistrationResult RegisterSourceMedia(
        const std::string& mission_id, const ksi::edge::SourceMediaUploadClaim& claim) override {
        (void)mission_id;
        ++register_calls;
        if (register_verdict != ksi::edge::CoreSyncVerdict::kAcknowledged) {
            return {register_verdict, {}, {}};
        }
        registered.push_back(claim.media_id);
        const std::string url = "https://storage.example.test/" + claim.media_id + "?sig=" +
                                std::to_string(register_calls);
        issued_urls[claim.media_id] = url;
        return {ksi::edge::CoreSyncVerdict::kAcknowledged, url, {{"Content-Type", claim.content_type}}};
    }

    ksi::edge::CoreSyncVerdict PutSourceMedia(
        const ksi::edge::SourceMediaItemRecord& item,
        const ksi::edge::SourceMediaRegistrationResult& registration) override {
        if (rights_observer != nullptr) {
            put_observed = true;
            rights_held_during_any_put = rights_held_during_any_put || rights_observer->rights_held;
        }
        if (put_verdict != ksi::edge::CoreSyncVerdict::kAcknowledged) {
            return put_verdict;
        }
        // 저널이 URL 을 보관했다면 재기동 뒤에 낡은 값이 실린다. 방금 발급한
        // 그 URL 이 아니면 실패로 낸다 — 이 단언이 "URL 을 저장하지 않는다"를 잡는다.
        const auto issued = issued_urls.find(item.media_id);
        if (issued == issued_urls.end() || issued->second != registration.upload_url) {
            return ksi::edge::CoreSyncVerdict::kPermanentFailure;
        }
        uploaded.push_back(item.media_id);
        return ksi::edge::CoreSyncVerdict::kAcknowledged;
    }

    ksi::edge::CoreSyncVerdict SealSourceMedia(const std::string& mission_id) override {
        (void)mission_id;
        ++seal_calls;
        return seal_verdict;
    }
};

// marker 를 Obtain **전에** 쓰는지 직접 본다 — 순서가 뒤집히면 SIGKILL 이 났을 때
// 앨범이 잠긴 채 아무 증거도 남지 않는다.
class MarkerObservingSourcePort final : public ksi::edge::FakeMediaSourcePort {
public:
    std::filesystem::path marker_path;
    bool marker_present_on_obtain = false;

    ksi::edge::MediaSourceVerdict ObtainRights() override {
        marker_present_on_obtain = std::filesystem::exists(marker_path);
        return ksi::edge::FakeMediaSourcePort::ObtainRights();
    }
};

void TestSourceMediaRightsMarker() {
    const std::filesystem::path state = UniqueTestDirectory("media-rights-state");
    std::error_code cleanup_error;
    std::filesystem::remove_all(state, cleanup_error);
    Check(std::filesystem::create_directories(state) && chmod(state.c_str(), 0700) == 0,
          "rights marker fixture creates a private state directory");
    const std::filesystem::path marker = state / ksi::edge::kSourceMediaRightsMarkerFilename;

    ksi::edge::FakeMediaSourcePort absent_source;
    Check(ksi::edge::ReconcileSourceMediaRightsMarker(state.string(), &absent_source) ==
                  ksi::edge::MediaRightsVerdict::kNotHeld &&
              absent_source.release_calls == 0,
          "startup with no marker does not issue a rights release");

    Check(WritePrivateTextFile(marker, "KSI_EDGE_SOURCE_MEDIA_RIGHTS_HELD_V1\n"),
          "rights marker fixture simulates a process killed while holding rights");
    ksi::edge::FakeMediaSourcePort stale_source;
    Check(ksi::edge::ReconcileSourceMediaRightsMarker(state.string(), &stale_source) ==
                  ksi::edge::MediaRightsVerdict::kReleased &&
              stale_source.release_calls == 1 && stale_source.obtain_calls == 0 &&
              !std::filesystem::exists(marker),
          "a surviving marker makes startup release rights before it ever obtains them");

    MarkerObservingSourcePort ordered_source;
    ordered_source.marker_path = marker;
    {
        ksi::edge::MediaSourceRightsGuard guard(state.string(), &ordered_source);
        Check(guard.Acquire() == ksi::edge::MediaRightsVerdict::kHeld &&
                  ordered_source.marker_present_on_obtain && std::filesystem::exists(marker),
              "the marker is durable before rights are obtained, never after");
        Check(guard.Release() == ksi::edge::MediaRightsVerdict::kReleased &&
                  !std::filesystem::exists(marker) && !ordered_source.rights_held,
              "a clean release removes the marker so the next startup has nothing to undo");
    }

    ksi::edge::FakeMediaSourcePort refusing_source;
    refusing_source.obtain_verdict = ksi::edge::MediaSourceVerdict::kRightsUnavailable;
    {
        ksi::edge::MediaSourceRightsGuard guard(state.string(), &refusing_source);
        Check(guard.Acquire() == ksi::edge::MediaRightsVerdict::kSourceRefused &&
                  !std::filesystem::exists(marker),
              "a refused obtain leaves no marker behind to strand the next startup");
    }

    ksi::edge::FakeMediaSourcePort stuck_source;
    stuck_source.release_verdict = ksi::edge::MediaSourceVerdict::kTransientFailure;
    {
        ksi::edge::MediaSourceRightsGuard guard(state.string(), &stuck_source);
        Check(guard.Acquire() == ksi::edge::MediaRightsVerdict::kHeld, "stuck fixture holds rights");
        Check(guard.Release() == ksi::edge::MediaRightsVerdict::kSourceRefused &&
                  std::filesystem::exists(marker),
              "a release that failed keeps the marker so the next startup retries it");
    }
    Check(std::filesystem::exists(marker),
          "the destructor of a guard whose release keeps failing does not erase the evidence");
    std::filesystem::remove_all(state, cleanup_error);
}

void TestCoreRestSourceMediaWire() {
    const std::filesystem::path directory = UniqueTestDirectory("source-media-wire-spool");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    ksi::edge::ArtifactVault spool(directory.string(), 64U * 1024U);
    const std::vector<std::uint8_t> photo = MakeJpeg(0xC0U, 5472U, 3648U);
    const auto persisted = spool.Persist("srcmedia-mission1-DJI_0001", photo.data(), photo.size());
    Check(persisted.verdict == ksi::edge::ArtifactVaultVerdict::kPersisted,
          "source media wire fixture spools a photo");

    ksi::edge::SourceMediaItemRecord item;
    item.mission_id = "mission1";
    item.media_id = "DJI_0001";
    item.camera_file_name = "DJI_0001.JPG";
    item.state = ksi::edge::SourceMediaState::kSpooled;
    item.artifact_id = persisted.artifact.artifact_id;
    item.local_path = persisted.artifact.local_path;
    item.content_digest = persisted.artifact.content_digest;
    item.byte_count = persisted.artifact.byte_count;
    item.width = 5472U;
    item.height = 3648U;
    item.content_type = "image/jpeg";

    ksi::edge::SourceMediaUploadClaim claim;
    claim.media_id = item.media_id;
    claim.content_type = item.content_type;
    claim.content_digest = item.content_digest;
    claim.byte_count = item.byte_count;
    claim.width = item.width;
    claim.height = item.height;

    RecordingHttpsExecutor executor;
    executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted,
                         ksi::edge::HttpsRequestVerdict::kCompleted,
                         ksi::edge::HttpsRequestVerdict::kCompleted};
    // 응답에 적대적인 헤더 묶음을 넣어도 우리는 응답에서 헤더를 받지 않는다.
    executor.responses = {
        {201,
         "{\"verdict\":\"PROCESSED\",\"detail\":null,\"results\":[{\"mediaId\":\"DJI_0001\","
         "\"verdict\":\"REGISTERED\",\"objectKey\":\"sites/s/missions/mission1/source/DJI_0001\","
         "\"uploadUrl\":\"https://storage.example.test/put?sig=abc\","
         "\"requiredUploadHeaders\":{\"Authorization\":\"Bearer injected\"},"
         "\"expiresAt\":\"2026-08-16T00:00:00Z\",\"detail\":null}]}"},
        {200, ""},
        {201, "{\"verdict\":\"SEALED\",\"detail\":null,\"bundle\":null}"}};
    ksi::edge::CoreRestSourceMediaTransport transport(
        {"https://core.example.test", "edgeToken_123", 4096U}, &executor, &spool);
    const auto registration = transport.RegisterSourceMedia("mission1", claim);
    const auto put = transport.PutSourceMedia(item, registration);
    const auto sealed = transport.SealSourceMedia("mission1");
    Check(registration.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              put == ksi::edge::CoreSyncVerdict::kAcknowledged &&
              sealed == ksi::edge::CoreSyncVerdict::kAcknowledged,
          "Core REST source media transport registers, uploads, and seals a mission bundle");
    Check(executor.requests.size() == 3U &&
              executor.requests[0].endpoint == ksi::edge::HttpsEndpoint::kCore &&
              executor.requests[0].url ==
                  "https://core.example.test/v1/missions/mission1/source-media" &&
              executor.requests[0].headers.at("Authorization") == "Bearer edgeToken_123" &&
              ToString(executor.requests[0].body)
                      .find("\"sha256\":\"" + item.content_digest.substr(7U) + "\"") !=
                  std::string::npos &&
              ToString(executor.requests[0].body).find("sha256:") == std::string::npos &&
              ToString(executor.requests[0].body).find("\"width\":5472,\"height\":3648") !=
                  std::string::npos,
          "registration claims the measured pixel size and Core's bare 64 hex digest spelling");
    Check(executor.requests.size() == 3U &&
              executor.requests[1].endpoint == ksi::edge::HttpsEndpoint::kEvidenceUpload &&
              executor.requests[1].method == "PUT" &&
              executor.requests[1].url == "https://storage.example.test/put?sig=abc" &&
              executor.requests[1].headers.size() == 1U &&
              executor.requests[1].headers.count("Authorization") == 0U &&
              executor.requests[1].headers.at("Content-Type") == "image/jpeg" &&
              executor.requests[1].body.size() == photo.size(),
          "the presigned source media PUT carries only Content-Type and never the Core bearer");
    Check(executor.requests.size() == 3U &&
              executor.requests[2].url ==
                  "https://core.example.test/v1/missions/mission1/source-media/seal" &&
              executor.requests[2].headers.at("Authorization") == "Bearer edgeToken_123",
          "sealing is a Core-authenticated call on the mission bundle route");

    RecordingHttpsExecutor sealed_executor;
    sealed_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted};
    sealed_executor.responses = {{409, "{\"detail\":\"BUNDLE_SEALED\"}"}};
    ksi::edge::CoreRestSourceMediaTransport sealed_transport(
        {"https://core.example.test", "edgeToken_123", 4096U}, &sealed_executor, &spool);
    Check(sealed_transport.RegisterSourceMedia("mission1", claim).verdict ==
              ksi::edge::CoreSyncVerdict::kPermanentFailure,
          "registering into an already sealed bundle is a permanent failure, not a retry loop");

    RecordingHttpsExecutor conflict_executor;
    conflict_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted,
                                  ksi::edge::HttpsRequestVerdict::kCompleted};
    conflict_executor.responses = {
        {201, "{\"verdict\":\"PROCESSED\",\"results\":[{\"mediaId\":\"DJI_0001\","
              "\"verdict\":\"CLAIM_CONFLICT\",\"detail\":\"already registered\"}]}"},
        {201, "{\"verdict\":\"PROCESSED\",\"results\":[{\"mediaId\":\"DJI_0001\","
              "\"verdict\":\"STORAGE_UNAVAILABLE\",\"detail\":null}]}"}};
    ksi::edge::CoreRestSourceMediaTransport conflict_transport(
        {"https://core.example.test", "edgeToken_123", 4096U}, &conflict_executor, &spool);
    Check(conflict_transport.RegisterSourceMedia("mission1", claim).verdict ==
                  ksi::edge::CoreSyncVerdict::kPermanentFailure &&
              conflict_transport.RegisterSourceMedia("mission1", claim).verdict ==
                  ksi::edge::CoreSyncVerdict::kRetryableFailure,
          "item verdicts keep the retryable/permanent distinction the drain loop depends on");

    // 401(토큰 만료·회전)·403(권한 철회)·404(Core 가 아직 이 임무를 모름)는 요청
    // 자체가 구조적으로 틀린 게 아니다 — 외부 상태가 바뀌면 다음 시도에서 풀릴
    // 수 있다. PushItem 이 이걸 QUARANTINED(스풀 사본 삭제, 종착 상태)로 보내지
    // 않도록, 셋 다 kRetryableFailure 로 분류되는지와 Core 가 나중에 정상
    // 등록을 돌려주면 실제로 회복돼 진행되는지를 함께 고정한다.
    for (const int blocked_status : {401, 403, 404}) {
        RecordingHttpsExecutor blocked_executor;
        blocked_executor.verdicts = {ksi::edge::HttpsRequestVerdict::kCompleted,
                                     ksi::edge::HttpsRequestVerdict::kCompleted};
        blocked_executor.responses = {
            {blocked_status, "{\"detail\":\"blocked\"}"},
            {201, "{\"verdict\":\"PROCESSED\",\"results\":[{\"mediaId\":\"DJI_0001\","
                  "\"verdict\":\"REGISTERED\",\"uploadUrl\":"
                  "\"https://storage.example.test/put?sig=recovered\",\"detail\":null}]}"}};
        ksi::edge::CoreRestSourceMediaTransport blocked_transport(
            {"https://core.example.test", "edgeToken_123", 4096U}, &blocked_executor, &spool);
        const auto first = blocked_transport.RegisterSourceMedia("mission1", claim);
        const std::string first_label =
            "HTTP " + std::to_string(blocked_status) +
            " on registration is recoverable, not a terminal quarantine";
        Check(first.verdict == ksi::edge::CoreSyncVerdict::kRetryableFailure, first_label.c_str());
        const auto second = blocked_transport.RegisterSourceMedia("mission1", claim);
        const std::string second_label =
            "registration recovers once Core answers normally after a blocking HTTP " +
            std::to_string(blocked_status);
        Check(second.verdict == ksi::edge::CoreSyncVerdict::kAcknowledged &&
                  second.upload_url == "https://storage.example.test/put?sig=recovered",
              second_label.c_str());
    }
    std::filesystem::remove_all(directory, cleanup_error);
}

void TestSourceMediaJournalGuards() {
    if (!SqliteBackendReady("source media journal 가드 계약")) {
        return;
    }
    const std::filesystem::path database =
        UniqueTestDirectory("source-media-journal-guards").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove(database, cleanup_error);
    auto journal = std::make_unique<ksi::edge::SqliteStoreForward>(database.string());
    Check(journal->Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "journal guard fixture opens the sqlite backend");

    // (b) BeginSourceMediaMission — 같은 임무를 다른 장비가 이어받으면 발견 목록이
    // 어느 기체의 SD 카드인지 알 수 없게 된다. 거부돼야 한다.
    Check(journal->BeginSourceMediaMission("missiong", "edge-a") ==
              ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(b) fixture opens a mission under edge-a");
    Check(journal->BeginSourceMediaMission("missiong", "edge-a") ==
              ksi::edge::SourceMediaJournalVerdict::kDuplicate,
          "guard(b) re-beginning under the same device is idempotent, not an error");
    Check(journal->BeginSourceMediaMission("missiong", "edge-b") ==
              ksi::edge::SourceMediaJournalVerdict::kConflict,
          "guard(b) a different device may not take over an in-flight mission");

    // (d) RecordSourceMediaDiscovered — 목록이 닫힌 뒤에 나타난 장은 예산·봉인
    // 판정의 근거인 discovered_count 를 조용히 어긋나게 만든다. 거부돼야 한다.
    // guard(c) 의 깨진-실측값 사례 4 개도 여기서 같이 discover 해 둔다 — 저마다
    // 별도 media_id 를 써서, 어느 한 사례가 (진짜 결함으로) 잘못 통과하더라도
    // 다른 사례의 판정과 서로 물들지 않게 한다.
    Check(journal->RecordSourceMediaDiscovered("missiong", "DJI_0001", "DJI_0001.JPG", 100U) ==
              ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(d) fixture discovers the photo used by guard(a)/guard(c)'s clean path");
    for (const char* broken_media_id : {"DJI_c1", "DJI_c2", "DJI_c3", "DJI_c4"}) {
        Check(journal->RecordSourceMediaDiscovered("missiong", broken_media_id,
                                                    std::string(broken_media_id) + ".JPG", 100U) ==
                  ksi::edge::SourceMediaJournalVerdict::kAccepted,
              "guard(d) fixture discovers a standalone photo for one guard(c) broken-field case");
    }
    Check(journal->MarkSourceMediaDiscoveryComplete("missiong", 5U) ==
              ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(d) fixture closes the discovery list at five photos");
    Check(journal->RecordSourceMediaDiscovered("missiong", "DJI_0002", "DJI_0002.JPG", 100U) ==
              ksi::edge::SourceMediaJournalVerdict::kConflict,
          "guard(d) a photo that appears after the list closes is rejected, not silently added");

    // (a) TransitionLocked — 건너뛴 전이(바이트 한 번도 안 보내고 REGISTERED·
    // UPLOADED 로 점프)는 current != from 가드가 막는다.
    Check(journal->MarkSourceMediaRegistered("missiong", "DJI_0001") ==
              ksi::edge::SourceMediaJournalVerdict::kConflict,
          "guard(a) DISCOVERED cannot jump straight to REGISTERED, skipping SPOOLED");
    Check(journal->MarkSourceMediaUploaded("missiong", "DJI_0001") ==
              ksi::edge::SourceMediaJournalVerdict::kConflict,
          "guard(a) DISCOVERED cannot jump straight to UPLOADED, skipping SPOOLED and REGISTERED");

    // (c) MarkSourceMediaSpooled — 실측값이 하나라도 비면 Core 등록에서 거부당할
    // 값을 저널에 먼저 굳히는 셈이라 거부돼야 한다. 각 사례는 자기 자신만의
    // media_id(DJI_c1..c4, 위에서 discover 해 둠)를 써서 서로의 저널 상태에
    // 영향을 주지 않는다 — 이 가드가 실제로 빠지면(진짜 결함) 어떤 사례가
    // 잘못 SPOOLED 로 넘어가더라도 다른 사례의 판정은 그대로 유효하다.
    ksi::edge::SourceMediaItemRecord measured;
    measured.mission_id = "missiong";
    measured.media_id = "DJI_0001";
    measured.artifact_id = "srcmedia-8.missiong-DJI_0001";
    measured.local_path = "/tmp/does-not-need-to-exist-for-this-check";
    measured.content_digest = kDigest;
    measured.byte_count = 12345U;
    measured.width = 100U;
    measured.height = 100U;
    measured.content_type = "image/jpeg";
    {
        ksi::edge::SourceMediaItemRecord broken = measured;
        broken.media_id = "DJI_c1";
        broken.artifact_id = "srcmedia-8.missiong-DJI_c1";
        broken.width = 0U;
        Check(journal->MarkSourceMediaSpooled(broken) == ksi::edge::SourceMediaJournalVerdict::kConflict,
              "guard(c) a spooled record with no measured width is rejected");
    }
    {
        ksi::edge::SourceMediaItemRecord broken = measured;
        broken.media_id = "DJI_c2";
        broken.artifact_id = "srcmedia-8.missiong-DJI_c2";
        broken.height = 0U;
        Check(journal->MarkSourceMediaSpooled(broken) == ksi::edge::SourceMediaJournalVerdict::kConflict,
              "guard(c) a spooled record with no measured height is rejected");
    }
    {
        ksi::edge::SourceMediaItemRecord broken = measured;
        broken.media_id = "DJI_c3";
        broken.artifact_id = "srcmedia-8.missiong-DJI_c3";
        broken.byte_count = 0U;
        Check(journal->MarkSourceMediaSpooled(broken) == ksi::edge::SourceMediaJournalVerdict::kConflict,
              "guard(c) a spooled record with no measured byte count is rejected");
    }
    {
        ksi::edge::SourceMediaItemRecord broken = measured;
        broken.media_id = "DJI_c4";
        broken.artifact_id = "srcmedia-8.missiong-DJI_c4";
        broken.content_digest = "not-a-sha256-digest";
        Check(journal->MarkSourceMediaSpooled(broken) == ksi::edge::SourceMediaJournalVerdict::kConflict,
              "guard(c) a spooled record with no measured content digest is rejected");
    }
    Check(journal->MarkSourceMediaSpooled(measured) == ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(c) fixture: a fully measured record on its own untouched media_id is accepted, so the "
          "reverse-transition guard below has SPOOLED/REGISTERED/UPLOADED to test against");

    // (a) 역방향 전이 — 봉인은커녕 REGISTERED 로도 되돌아갈 수 없다.
    Check(journal->MarkSourceMediaRegistered("missiong", "DJI_0001") ==
              ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(a) fixture: SPOOLED -> REGISTERED is the legitimate forward step");
    Check(journal->MarkSourceMediaUploaded("missiong", "DJI_0001") ==
              ksi::edge::SourceMediaJournalVerdict::kAccepted,
          "guard(a) fixture: REGISTERED -> UPLOADED is the legitimate forward step");
    Check(journal->MarkSourceMediaRegistered("missiong", "DJI_0001") ==
              ksi::edge::SourceMediaJournalVerdict::kConflict,
          "guard(a) an item already UPLOADED cannot be walked back to REGISTERED — sealing without ever "
          "sending bytes must stay unreachable");

    std::filesystem::remove(database, cleanup_error);
}

std::size_t CountSpoolFiles(const std::filesystem::path& directory) {
    std::size_t count = 0U;
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(directory, error)) {
        if (entry.is_regular_file(error)) {
            ++count;
        }
    }
    return count;
}

void FillFakeSource(ksi::edge::FakeMediaSourcePort* source, const std::vector<std::string>& names,
                    std::uint32_t base_width) {
    std::uint32_t width = base_width;
    for (const std::string& name : names) {
        ksi::edge::FakeMediaSourcePort::Entry entry;
        entry.handle.camera_file_name = name;
        entry.bytes = MakeJpeg(0xC0U, width, 3000U);
        entry.handle.announced_bytes = entry.bytes.size();
        source->entries.push_back(entry);
        ++width;
    }
}

void TestMediaOffloadConveyor() {
    if (!SqliteBackendReady("media offload 컨베이어 계약")) {
        return;
    }
    const std::filesystem::path spool_directory = UniqueTestDirectory("media-offload-spool");
    const std::filesystem::path state_directory = UniqueTestDirectory("media-offload-state");
    const std::filesystem::path database =
        UniqueTestDirectory("media-offload-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);

    ksi::edge::MediaOffloadPolicy policy;
    policy.state_directory = state_directory.string();
    policy.spool_high_water_bytes = 512U * 1024U * 1024U;
    policy.spool_high_water_items = 2U;

    const auto open_journal = [&database]() {
        auto journal = std::make_unique<ksi::edge::SqliteStoreForward>(database.string());
        return journal->Open() == ksi::edge::StoreForwardVerdict::kAccepted ? std::move(journal)
                                                                            : nullptr;
    };

    // ① 고수위 초과 시 다운로드가 멈추고 배출이 먼저다.
    {
        ksi::edge::ArtifactVault spool(spool_directory.string(), 1U * 1024U * 1024U);
        auto journal = open_journal();
        Check(journal != nullptr, "media offload journal opens");
        ksi::edge::FakeMediaSourcePort source;
        FillFakeSource(&source, {"DJI_0001.JPG", "DJI_0002.JPG", "DJI_0003.JPG", "DJI_0004.JPG"},
                       4000U);
        FakeSourceMediaTransport transport;
        transport.register_verdict = ksi::edge::CoreSyncVerdict::kRetryableFailure;
        ksi::edge::MediaOffloadWorker worker(policy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionhw", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kSpoolHighWater &&
                  report.download_paused_for_spool && report.spooled == 2U &&
                  report.pending_download == 2U,
              "the conveyor stops downloading at the spool high-water mark instead of buffering");
        Check(source.download_calls == 2 && CountSpoolFiles(spool_directory) == 2U &&
                  report.spool_items_in_use == 2U,
              "exactly the high-water number of photos ever reach the manifold disk");
        Check(!source.touched_without_rights && source.release_calls == source.obtain_calls &&
                  source.obtain_calls > 0 && !source.rights_held,
              "download rights are obtained for the camera phase and handed back before it returns");

        transport.register_verdict = ksi::edge::CoreSyncVerdict::kAcknowledged;
        const auto drained = worker.RunOnce("missionhw", "edge1");
        Check(drained.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && drained.sealed &&
                  transport.uploaded.size() == 4U && drained.spool_bytes_in_use == 0U,
              "once the drain works the same conveyor finishes every discovered photo and seals");
        Check(CountSpoolFiles(spool_directory) == 0U,
              "PURGED leaves zero bytes of the mission on the manifold");
    }

    // ② 각 단계 직후 강제 종료 후 재기동 복구 6종.
    ksi::edge::ArtifactVault spool(spool_directory.string(), 1U * 1024U * 1024U);
    const std::vector<std::string> names = {"DJI_1001.JPG", "DJI_1002.JPG", "DJI_1003.JPG"};
    ksi::edge::MediaOffloadPolicy roomy = policy;
    roomy.spool_high_water_items = 8U;

    {  // (1) DISCOVERED 직후 종료
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FillFakeSource(&source, names, 5000U);
        source.download_script = {ksi::edge::MediaSourceVerdict::kTransientFailure};
        FakeSourceMediaTransport transport;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kSourceFailure &&
                  report.discovered == 3U && report.spooled == 0U &&
                  journal->SourceMediaItemsInState("missionr",
                                                    ksi::edge::SourceMediaState::kDiscovered)
                          .size() == 3U,
              "restart case 1: the discovery list survives a download failure with nothing spooled");
    }
    {  // (2) SPOOLED 직후 종료 — 등록이 재시도 가능하게 실패
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FillFakeSource(&source, names, 5000U);
        FakeSourceMediaTransport transport;
        transport.register_verdict = ksi::edge::CoreSyncVerdict::kRetryableFailure;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kTransportFailure &&
                  report.spooled == 3U && report.discovered == 0U &&
                  journal->SourceMediaItemsInState("missionr", ksi::edge::SourceMediaState::kSpooled)
                          .size() == 3U &&
                  CountSpoolFiles(spool_directory) == 3U,
              "restart case 2: a reopened journal resumes from SPOOLED without re-listing the camera");
    }
    std::string uploaded_before_purge;
    {  // (3) REGISTERED 직후 종료 — PUT 이 재시도 가능하게 실패
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FakeSourceMediaTransport transport;
        transport.put_verdict = ksi::edge::CoreSyncVerdict::kRetryableFailure;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        const auto registered =
            journal->SourceMediaItemsInState("missionr", ksi::edge::SourceMediaState::kRegistered);
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kTransportFailure &&
                  registered.size() == 1U &&
                  journal->SourceMediaItemsInState("missionr", ksi::edge::SourceMediaState::kSpooled)
                          .size() == 2U &&
                  source.download_calls == 0,
              "restart case 3: the drain stops at the first transport failure and never re-downloads "
              "photos that are already spooled");
        if (!registered.empty()) {
            uploaded_before_purge = registered.front().media_id;
        }
    }
    {  // (4) UPLOADED 직후 종료 — 저널은 굳었고 스풀 사본이 남아 있다
        auto journal = open_journal();
        Check(journal->MarkSourceMediaUploaded("missionr", uploaded_before_purge) ==
                  ksi::edge::SourceMediaJournalVerdict::kAccepted,
              "restart fixture records a durable upload before the purge could run");
        ksi::edge::FakeMediaSourcePort source;
        FakeSourceMediaTransport transport;
        transport.seal_verdict = ksi::edge::CoreSyncVerdict::kRetryableFailure;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.purged == 3U && CountSpoolFiles(spool_directory) == 0U &&
                  report.spool_bytes_in_use == 0U &&
                  std::find(transport.registered.begin(), transport.registered.end(),
                            uploaded_before_purge) == transport.registered.end(),
              "restart case 4: a photo already recorded as UPLOADED is purged without being sent to "
              "Core a second time");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kTransportFailure && !report.sealed,
              "a seal that Core refused leaves the bundle unsealed rather than assumed");
    }
    {  // (5) PURGED 직후 종료 — 남은 일은 봉인뿐이다
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FakeSourceMediaTransport transport;
        transport.seal_verdict = ksi::edge::CoreSyncVerdict::kRetryableFailure;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kTransportFailure &&
                  transport.seal_calls == 1 && transport.register_calls == 0 &&
                  source.download_calls == 0,
              "restart case 5: an all-purged bundle retries only the seal");
    }
    {  // 봉인 성공
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FakeSourceMediaTransport transport;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && report.sealed &&
                  transport.seal_calls == 1,
              "Core seals the bundle before the journal marks it sealed");
    }
    {  // (6) SEALED 직후 종료
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FakeSourceMediaTransport transport;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionr", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && report.sealed &&
                  transport.seal_calls == 0 && source.list_calls == 0 && source.obtain_calls == 0,
              "restart case 6: a sealed bundle touches neither the camera nor Core again");
    }

    // ③ 부분 집합 봉인 거부 — 화소수를 못 읽은 장은 격리되고 봉인을 막는다.
    {
        auto journal = open_journal();
        ksi::edge::FakeMediaSourcePort source;
        FillFakeSource(&source, {"DJI_2001.JPG", "DJI_2002.JPG"}, 6000U);
        ksi::edge::FakeMediaSourcePort::Entry broken;
        broken.handle.camera_file_name = "DJI_2003.JPG";
        broken.bytes = {'n', 'o', 't', ' ', 'a', ' ', 'j', 'p', 'e', 'g'};
        broken.handle.announced_bytes = broken.bytes.size();
        source.entries.push_back(broken);
        FakeSourceMediaTransport transport;
        ksi::edge::MediaOffloadWorker worker(roomy, journal.get(), &spool, &source, &transport);
        const auto report = worker.RunOnce("missionq", "edge1");
        Check(report.verdict == ksi::edge::MediaOffloadVerdict::kQuarantineBlocked &&
                  report.quarantined == 1U && report.purged == 2U && !report.sealed &&
                  transport.seal_calls == 0,
              "a photo whose pixel size cannot be read is quarantined and the bundle is not sealed");
        Check(journal->MarkSourceBundleSealed("missionq") ==
                  ksi::edge::SourceMediaJournalVerdict::kIncompleteBundle,
              "the journal itself refuses a subset seal that would make sourceBundleDigest a lie");
        ksi::edge::SourceMediaItemRecord quarantined;
        Check(journal->FindSourceMediaItem("missionq", "DJI_2003", &quarantined) ==
                      ksi::edge::SourceMediaJournalVerdict::kAccepted &&
                  quarantined.state == ksi::edge::SourceMediaState::kQuarantined &&
                  !quarantined.quarantine_reason.empty() && CountSpoolFiles(spool_directory) == 0U,
              "quarantine records why and still frees the transit copy so the conveyor keeps moving");
    }

    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

void TestMediaOffloadUploadDurableBeforePurge() {
    if (!SqliteBackendReady("purge 이전 durable 기록 순서 계약")) {
        return;
    }
    const std::filesystem::path spool_directory = UniqueTestDirectory("media-offload-order-spool");
    const std::filesystem::path state_directory = UniqueTestDirectory("media-offload-order-state");
    const std::filesystem::path database =
        UniqueTestDirectory("media-offload-order-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);

    ksi::edge::ArtifactVault spool(spool_directory.string(), 1U * 1024U * 1024U);
    auto journal = std::make_unique<ksi::edge::SqliteStoreForward>(database.string());
    Check(journal->Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "durable-before-purge fixture opens the journal");

    ksi::edge::MediaOffloadPolicy policy;
    policy.state_directory = state_directory.string();
    policy.spool_high_water_bytes = 512U * 1024U * 1024U;
    policy.spool_high_water_items = 8U;

    ksi::edge::FakeMediaSourcePort source;
    FillFakeSource(&source, {"DJI_6001.JPG"}, 6000U);
    FakeSourceMediaTransport transport;
    ksi::edge::MediaOffloadWorker worker(policy, journal.get(), &spool, &source, &transport);

    int hook_calls = 0;
    bool spool_present_at_hook = false;
    bool journal_uploaded_at_hook = false;
    worker.test_only_after_uploaded_before_purge_hook =
        [&](const ksi::edge::SourceMediaItemRecord& item) {
            ++hook_calls;
            spool_present_at_hook = !item.local_path.empty() && std::filesystem::exists(item.local_path);
            ksi::edge::SourceMediaItemRecord stored;
            journal_uploaded_at_hook =
                journal->FindSourceMediaItem(item.mission_id, item.media_id, &stored) ==
                    ksi::edge::SourceMediaJournalVerdict::kAccepted &&
                stored.state == ksi::edge::SourceMediaState::kUploaded;
        };

    const auto report = worker.RunOnce("missionorder", "edge1");

    Check(hook_calls == 1, "the durable-before-purge hook fires exactly once for the one photo in this "
                          "mission");
    // 이 두 단언이 실제 결함(검토자가 MarkSourceMediaUploaded 직전에 spool_->Remove()
    // 를 끼워 순서를 뒤집는 돌연변이)을 잡는다: 뒤집혔다면 훅이 불릴 때 이미
    // 스풀 사본이 사라져 있다.
    Check(journal_uploaded_at_hook,
          "at the moment the hook fires the journal already durably shows UPLOADED — the durable write "
          "happens first, never after the spool copy is gone");
    Check(spool_present_at_hook,
          "at the moment the hook fires the spool copy is still on disk — PurgeItem has not run yet, so "
          "a crash exactly here still has bytes to recover from");
    Check(report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && report.sealed &&
              CountSpoolFiles(spool_directory) == 0U,
          "durable-before-purge fixture: the mission still completes normally end to end");

    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

void TestMediaOffloadRightsReleasedDuringOffload() {
    if (!SqliteBackendReady("offload 중 권한 보유 구간 계약")) {
        return;
    }
    const std::filesystem::path spool_directory = UniqueTestDirectory("media-offload-rights-spool");
    const std::filesystem::path state_directory = UniqueTestDirectory("media-offload-rights-state");
    const std::filesystem::path database =
        UniqueTestDirectory("media-offload-rights-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);

    ksi::edge::ArtifactVault spool(spool_directory.string(), 1U * 1024U * 1024U);
    auto journal = std::make_unique<ksi::edge::SqliteStoreForward>(database.string());
    Check(journal->Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "rights-during-offload fixture opens the journal");

    ksi::edge::MediaOffloadPolicy policy;
    policy.state_directory = state_directory.string();
    policy.spool_high_water_bytes = 512U * 1024U * 1024U;
    policy.spool_high_water_items = 8U;

    ksi::edge::FakeMediaSourcePort source;
    FillFakeSource(&source, {"DJI_5001.JPG", "DJI_5002.JPG"}, 5000U);
    FakeSourceMediaTransport transport;
    transport.rights_observer = &source;
    ksi::edge::MediaOffloadWorker worker(policy, journal.get(), &spool, &source, &transport);
    const auto report = worker.RunOnce("missionrights", "edge1");

    Check(report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && report.sealed,
          "rights-during-offload fixture completes the mission normally");
    Check(transport.put_observed, "rights-during-offload fixture actually reaches the network PUT step "
                                 "the guard is meant to protect");
    // media_offload.hpp/cpp 의 설계 근거: "권한은 카메라를 만지는 구간에서만
    // 잡는다. 배출(네트워크)은 권한 없이 진행되므로, 통신이 느린 동안 운영자의
    // 앨범이 잠기지 않는다." 가드를 RunOnce 전체로 넓히는 돌연변이는 Obtain/
    // Release 횟수와 종료 시점 rights_held 만으로는 잡히지 않는다(둘 다 여전히
    // 맞다) — PutSourceMedia 가 불리는 그 순간의 상태를 직접 봐야 한다.
    Check(!transport.rights_held_during_any_put,
          "camera rights are released before every network PutSourceMedia call, not just by the time "
          "RunOnce returns — widening the guard to span the whole RunOnce would hold them through the "
          "slow network call and lock the operator out of the album, and would still pass a test that "
          "only checks the final state");

    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

void TestMediaOffloadReconcilesRightsAtStartup() {
    if (!SqliteBackendReady("기동 시 권한 재조정 계약")) {
        return;
    }
    const std::filesystem::path spool_directory = UniqueTestDirectory("media-offload-startup-spool");
    const std::filesystem::path state_directory = UniqueTestDirectory("media-offload-startup-state");
    const std::filesystem::path database =
        UniqueTestDirectory("media-offload-startup-store").string() + ".sqlite";
    std::error_code cleanup_error;
    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
    Check(std::filesystem::create_directories(state_directory) &&
              chmod(state_directory.c_str(), 0700) == 0,
          "startup reconciliation fixture creates a private state directory");
    const std::filesystem::path marker = state_directory / ksi::edge::kSourceMediaRightsMarkerFilename;
    Check(WritePrivateTextFile(marker, "KSI_EDGE_SOURCE_MEDIA_RIGHTS_HELD_V1\n"),
          "startup reconciliation fixture simulates a previous process killed while holding rights");

    ksi::edge::ArtifactVault spool(spool_directory.string(), 1U * 1024U * 1024U);
    auto journal = std::make_unique<ksi::edge::SqliteStoreForward>(database.string());
    Check(journal->Open() == ksi::edge::StoreForwardVerdict::kAccepted,
          "startup reconciliation fixture opens the journal");

    ksi::edge::MediaOffloadPolicy policy;
    policy.state_directory = state_directory.string();
    policy.spool_high_water_bytes = 512U * 1024U * 1024U;
    policy.spool_high_water_items = 8U;

    ksi::edge::FakeMediaSourcePort source;
    FillFakeSource(&source, {"DJI_7001.JPG"}, 7000U);
    FakeSourceMediaTransport transport;
    ksi::edge::MediaOffloadWorker worker(policy, journal.get(), &spool, &source, &transport);

    const auto report = worker.RunOnce("missionstartup1", "edge1");
    // 정상적으로 짝지어지는 Acquire/Release 말고 정확히 하나 더 많은 Release —
    // 그 하나가 기동 시 정리한 남은 marker 다. MediaOffloadWorker 가 이 함수를
    // 부르지 않으면(배선 누락) 이 여분이 생기지 않는다.
    Check(source.release_calls == source.obtain_calls + 1,
          "MediaOffloadWorker actually calls ReconcileSourceMediaRightsMarker at startup — a stale "
          "marker costs exactly one unpaired ReleaseRights before any real camera work begins");
    Check(!std::filesystem::exists(marker),
          "the leftover marker is gone once startup reconciliation has run");
    Check(report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && report.sealed,
          "startup reconciliation fixture: reconciling a stale marker does not block the mission from "
          "completing normally");

    const int release_calls_after_first = source.release_calls;
    const int obtain_calls_after_first = source.obtain_calls;
    FillFakeSource(&source, {"DJI_7002.JPG"}, 7100U);
    const auto second_report = worker.RunOnce("missionstartup2", "edge1");
    Check(second_report.verdict == ksi::edge::MediaOffloadVerdict::kCompleted && second_report.sealed,
          "a second mission on the same worker still completes normally");
    Check(source.release_calls - release_calls_after_first == source.obtain_calls - obtain_calls_after_first,
          "a second RunOnce on the same worker does not reconcile again — startup reconciliation runs "
          "exactly once per worker lifetime, not once per mission");

    std::filesystem::remove_all(spool_directory, cleanup_error);
    std::filesystem::remove_all(state_directory, cleanup_error);
    std::filesystem::remove(database, cleanup_error);
}

void TestSpoolArtifactIdUnambiguous() {
    // mission_id·media_id 둘 다 IsSafeArtifactId 가 '-' 를 허용한다. 길이
    // 프리픽스가 없으면 ("m", "1-x") 와 ("m-1", "x") 가 같은 문자열로 뭉개진다.
    const std::string collided_a = ksi::edge::MediaOffloadWorker::SpoolArtifactId("m", "1-x");
    const std::string collided_b = ksi::edge::MediaOffloadWorker::SpoolArtifactId("m-1", "x");
    Check(!collided_a.empty() && !collided_b.empty() && collided_a != collided_b,
          "two distinct (mission_id, media_id) pairs that would collide under naive concatenation get "
          "distinct spool artifact ids");
    Check(ksi::edge::ArtifactVault::IsSafeArtifactId(collided_a) &&
              ksi::edge::ArtifactVault::IsSafeArtifactId(collided_b),
          "the length-prefixed spool artifact id is still a safe artifact id");
    Check(ksi::edge::MediaOffloadWorker::SpoolArtifactId("mission1", "DJI_0001") ==
              ksi::edge::MediaOffloadWorker::SpoolArtifactId("mission1", "DJI_0001"),
          "the encoding is deterministic for the same pair");
}

}  // namespace

void TestFlightExecutionKmzEnvelopeRederivation() {
    const auto derived = ksi::edge::RederiveKmzAltitudeEnvelope(kSampleKmzBytes);
    Check(derived.verdict == ksi::edge::KmzEnvelopeRederivationVerdict::kDerived &&
              derived.observed_min_altitude_m == 40.0 && derived.observed_max_altitude_m == 40.0 &&
              derived.waypoint_count == 3U,
          "a real Python-built KMZ (DEFLATE) rederives its exact altitude range");

    const auto stored_valid = ksi::edge::RederiveKmzAltitudeEnvelope(kStoredValidWaylinesBytes);
    Check(stored_valid.verdict == ksi::edge::KmzEnvelopeRederivationVerdict::kDerived &&
              stored_valid.observed_min_altitude_m == 10.0 &&
              stored_valid.observed_max_altitude_m == 50.0 && stored_valid.waypoint_count == 2U,
          "a STORED (uncompressed) zip entry is also read correctly");

    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kMissionKmzBody).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kZipMalformed,
          "bytes too short for a zip local file header are rejected, not parsed as empty");

    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kSampleKmzBytes.substr(0U, 1042U)).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kWaylinesEntryMissing,
          "a KMZ truncated before its waylines entry cannot claim an altitude range");

    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kStoredNoWaypointsBytes).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kNoWaypoints,
          "a waylines entry with zero executeHeight tags is refused, not treated as a zero-waypoint route");
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kStoredMalformedValueBytes).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kXmlMalformed,
          "a non-numeric executeHeight value is refused, not coerced to zero");
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kStoredUnterminatedBytes).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kXmlMalformed,
          "an unterminated executeHeight tag is refused");
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(kStoredNonFiniteBytes).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kNonFiniteAltitude,
          "a non-finite executeHeight value (nan) is refused");

    // 실제 zip 로컬 헤더 필드를 변조한 세 방어종심 사례 — 오프셋은 이 고정
    // 픽스처(kSampleKmzBytes)의 실측 레이아웃이다(python3 -m zipfile 로 직접
    // 확인: waylines.wpml 로컬 헤더는 바이트 1042에서 시작한다).
    constexpr std::size_t kWaylinesHeaderOffset = 1042U;
    constexpr std::size_t kCrc32FieldOffset = kWaylinesHeaderOffset + 14U;
    constexpr std::size_t kCompressedSizeFieldOffset = kWaylinesHeaderOffset + 18U;
    constexpr std::size_t kUncompressedSizeFieldOffset = kWaylinesHeaderOffset + 22U;

    std::string crc_corrupted = kSampleKmzBytes;
    crc_corrupted[kCrc32FieldOffset] = static_cast<char>(crc_corrupted[kCrc32FieldOffset] ^ 0x01);
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(crc_corrupted).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kCrcMismatch,
          "a corrupted stored CRC-32 is caught even though decompression itself succeeds");

    std::string shrunk_compressed = kSampleKmzBytes;
    shrunk_compressed[kCompressedSizeFieldOffset] = static_cast<char>(5);
    shrunk_compressed[kCompressedSizeFieldOffset + 1U] = static_cast<char>(0);
    shrunk_compressed[kCompressedSizeFieldOffset + 2U] = static_cast<char>(0);
    shrunk_compressed[kCompressedSizeFieldOffset + 3U] = static_cast<char>(0);
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(shrunk_compressed).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kInflateFailed,
          "a truncated DEFLATE stream fails closed instead of returning a partial route");

    std::string huge_uncompressed = kSampleKmzBytes;
    huge_uncompressed[kUncompressedSizeFieldOffset] = static_cast<char>(0xFF);
    huge_uncompressed[kUncompressedSizeFieldOffset + 1U] = static_cast<char>(0xFF);
    huge_uncompressed[kUncompressedSizeFieldOffset + 2U] = static_cast<char>(0xFF);
    huge_uncompressed[kUncompressedSizeFieldOffset + 3U] = static_cast<char>(0xFF);
    Check(ksi::edge::RederiveKmzAltitudeEnvelope(huge_uncompressed).verdict ==
              ksi::edge::KmzEnvelopeRederivationVerdict::kWaylinesTooLarge,
          "a claimed uncompressed size beyond the bound is refused before any allocation");
}

void TestFlightExecutionCeilingGuardDirect() {
    ksi::edge::CeilingGuardInput input;
    input.has_dtm_coverage = true;
    input.aoi_terrain_elevation_samples_m = {100.0, 102.0, 105.0};
    input.takeoff_elevation_m = 101.0;
    input.declared_max_altitude_m = 45.0;
    input.site_density = ksi::edge::SiteDensityDeclaration::kGeneralArea;

    const auto passed = ksi::edge::EvaluateFlightExecutionCeilingGuard(input);
    Check(passed.verdict == ksi::edge::CeilingGuardVerdict::kPassed &&
              passed.observed_terrain_relief_m == 5.0,
          "a flat, general-area, low-ceiling site passes the ceiling guard");

    ksi::edge::CeilingGuardInput non_finite = input;
    non_finite.takeoff_elevation_m = std::numeric_limits<double>::quiet_NaN();
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(non_finite).verdict ==
              ksi::edge::CeilingGuardVerdict::kNonFiniteInput,
          "a non-finite takeoff elevation is rejected before any comparison");

    ksi::edge::CeilingGuardInput no_dtm = input;
    no_dtm.has_dtm_coverage = false;
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(no_dtm).verdict ==
              ksi::edge::CeilingGuardVerdict::kNoDtmCoverage,
          "absent DTM coverage refuses (flatness cannot be judged without terrain data)");

    ksi::edge::CeilingGuardInput empty_samples = input;
    empty_samples.aoi_terrain_elevation_samples_m.clear();
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(empty_samples).verdict ==
              ksi::edge::CeilingGuardVerdict::kTerrainSamplesEmpty,
          "DTM coverage claimed with zero samples is refused");

    ksi::edge::CeilingGuardInput not_flat = input;
    not_flat.aoi_terrain_elevation_samples_m = {90.0, 105.0};  // relief 15m > 10m
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(not_flat).verdict ==
              ksi::edge::CeilingGuardVerdict::kTerrainNotFlat,
          "terrain relief beyond 10m is refused");

    ksi::edge::CeilingGuardInput outside_range = input;
    outside_range.takeoff_elevation_m = 200.0;
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(outside_range).verdict ==
              ksi::edge::CeilingGuardVerdict::kTakeoffOutsideTerrainRange,
          "a takeoff elevation outside the AOI terrain range is refused");

    ksi::edge::CeilingGuardInput too_high = input;
    too_high.declared_max_altitude_m = 140.0;  // > 135m
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(too_high).verdict ==
              ksi::edge::CeilingGuardVerdict::kCeilingTooHigh,
          "a declared ceiling above 135m is refused");

    ksi::edge::CeilingGuardInput unspecified_density = input;
    unspecified_density.site_density = ksi::edge::SiteDensityDeclaration::kUnspecified;
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(unspecified_density).verdict ==
              ksi::edge::CeilingGuardVerdict::kDensityUnspecified,
          "an undeclared site density is refused (no silent 'general' default)");

    ksi::edge::CeilingGuardInput congested = input;
    congested.site_density = ksi::edge::SiteDensityDeclaration::kCongestedArea;
    Check(ksi::edge::EvaluateFlightExecutionCeilingGuard(congested).verdict ==
              ksi::edge::CeilingGuardVerdict::kDensityCongested,
          "a declared congested area is refused this round (no obstacle-top ceiling model yet)");
}

void TestFlightExecutionArmingTokenDirect() {
    const std::filesystem::path directory = UniqueTestDirectory("flight-arm-direct");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    Check(std::filesystem::create_directories(directory) && chmod(directory.c_str(), 0700) == 0,
          "arming token direct test state directory is private");
    const std::filesystem::path token_path = directory / ksi::edge::kFieldArmingTokenFilename;

    const auto missing = ksi::edge::ConsumeFieldArmingToken(
        directory.string(), "edge-a", "mission-a", "dispatch-a", ksi::edge::FlightExecutionStage::kS2,
        kUtcMs);
    Check(missing.verdict == ksi::edge::ArmingTokenVerdict::kMissing,
          "a missing arming token is a typed no-arming result");

    ksi::edge::FieldArmingToken good;
    good.nonce = "nonce-direct-1";
    good.issuer = "ops";
    good.stage = ksi::edge::FlightExecutionStage::kS2;
    good.edge_device_id = "edge-a";
    good.mission_id = "mission-a";
    good.dispatch_id = "dispatch-a";
    good.issued_at_utc_ms = kUtcMs;
    good.expires_at_utc_ms = kUtcMs + 60'000LL;
    Check(ksi::edge::WriteFieldArmingToken(directory.string(), good) ==
              ksi::edge::ArmingTokenWriteVerdict::kWritten,
          "a valid arming token writes");

    ksi::edge::FieldArmingToken invalid_ttl = good;
    invalid_ttl.expires_at_utc_ms = good.issued_at_utc_ms + ksi::edge::kMaximumArmingTokenTtlMs + 1;
    Check(ksi::edge::WriteFieldArmingToken(directory.string(), invalid_ttl) ==
              ksi::edge::ArmingTokenWriteVerdict::kInvalidRequest,
          "the writer itself refuses a TTL beyond the 10-minute ceiling");

    ksi::edge::FieldArmingToken empty_issuer = good;
    empty_issuer.issuer.clear();
    Check(ksi::edge::WriteFieldArmingToken(directory.string(), empty_issuer) ==
              ksi::edge::ArmingTokenWriteVerdict::kInvalidRequest,
          "the writer refuses an empty issuer");

    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS3, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kStageMismatch,
          "an arming token issued for a different stage is refused");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-other", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kDeviceMismatch,
          "an arming token issued for a different edge device is refused");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-other", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kMissionMismatch,
          "an arming token issued for a different mission is refused");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-other",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kDispatchMismatch,
          "an arming token issued for a different dispatch is refused");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs - 1LL)
                  .verdict == ksi::edge::ArmingTokenVerdict::kNotYetValid,
          "an arming token is not usable before its issued_at");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs + 60'001LL)
                  .verdict == ksi::edge::ArmingTokenVerdict::kExpired,
          "an arming token expires fail-closed");

    // 손수 만든 TTL 초과 토큰 — 작성기 자체 검사를 우회해 소비기의 독립적인
    // 방어를 직접 시험한다.
    Check(WritePrivateTextFile(token_path,
                               FieldArmingTokenRawBytes("nonce-ttl", "ops", 2, "edge-a", "mission-a",
                                                       "dispatch-a", kUtcMs,
                                                       kUtcMs + ksi::edge::kMaximumArmingTokenTtlMs + 1)),
          "hand-crafted overlong-TTL arming token fixture writes");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kTtlTooLong,
          "the consumer independently rejects a TTL beyond the 10-minute ceiling");

    Check(WritePrivateTextFile(token_path,
                               FieldArmingTokenRawBytes("nonce-x", "ops", 2, "edge-a", "mission-a",
                                                       "dispatch-a", kUtcMs, kUtcMs + 60'000LL) +
                                   "unexpected=field\n"),
          "malformed arming token fixture writes");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kMalformed,
          "an unknown arming token field is not silently ignored");

    Check(WritePrivateTextFile(token_path,
                               FieldArmingTokenRawBytes("nonce-loose", "ops", 2, "edge-a", "mission-a",
                                                       "dispatch-a", kUtcMs, kUtcMs + 60'000LL)) &&
              chmod(token_path.c_str(), 0644) == 0,
          "loose-permission arming token fixture writes");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kUnsafeFile,
          "a group-readable arming token cannot authorize a start attempt");

    // 단발성: 유효 토큰을 소비하면 파일이 사라지고, 같은 nonce 를 다시 쓸 수 없다.
    Check(WritePrivateTextFile(token_path,
                               FieldArmingTokenRawBytes("nonce-single-use", "ops", 2, "edge-a",
                                                       "mission-a", "dispatch-a", kUtcMs,
                                                       kUtcMs + 60'000LL)),
          "single-use arming token fixture writes");
    const auto consumed = ksi::edge::ConsumeFieldArmingToken(
        directory.string(), "edge-a", "mission-a", "dispatch-a", ksi::edge::FlightExecutionStage::kS2,
        kUtcMs);
    Check(consumed.verdict == ksi::edge::ArmingTokenVerdict::kConsumed &&
              consumed.token.nonce == "nonce-single-use",
          "a valid arming token is consumed exactly once");
    Check(!std::filesystem::exists(token_path), "a consumed arming token file no longer exists (nonce burned)");
    Check(ksi::edge::ConsumeFieldArmingToken(directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kMissing,
          "a burned nonce cannot be replayed for a second attempt");

    // 작성기: 상태 경로에 이미 일반 파일이 있으면(사설 디렉터리로 만들 수 없다) 거부한다.
    const std::filesystem::path blocked_path = UniqueTestDirectory("flight-arm-blocked");
    std::filesystem::remove_all(blocked_path, cleanup_error);
    Check(WritePrivateTextFile(blocked_path, "not a directory\n"),
          "a plain file blocks the arming-token state directory for the writer test");
    Check(ksi::edge::WriteFieldArmingToken(blocked_path.string(), good) ==
              ksi::edge::ArmingTokenWriteVerdict::kUnsafeStateDirectory,
          "the arming token writer refuses a state path that cannot become a private directory");
    std::filesystem::remove(blocked_path, cleanup_error);

    // 소비기: group 권한이 남은 디렉터리는 복구하지 않고 그대로 거부한다(읽기
    // 쪽은 activation.cpp 와 같은 강한 규율 — 존재 확인만, 복구는 없다).
    const std::filesystem::path loose_directory = UniqueTestDirectory("flight-arm-loose-dir");
    std::filesystem::remove_all(loose_directory, cleanup_error);
    Check(std::filesystem::create_directories(loose_directory) && chmod(loose_directory.c_str(), 0755) == 0,
          "group-readable state directory fixture for the arming token consumer unsafe-directory case");
    Check(ksi::edge::ConsumeFieldArmingToken(loose_directory.string(), "edge-a", "mission-a", "dispatch-a",
                                             ksi::edge::FlightExecutionStage::kS2, kUtcMs)
                  .verdict == ksi::edge::ArmingTokenVerdict::kUnsafeStateDirectory,
          "the arming token consumer refuses a non-private state directory");
    std::filesystem::remove_all(loose_directory, cleanup_error);

    std::filesystem::remove_all(directory, cleanup_error);
}

void TestFlightExecutionAbortRequestDirect() {
    const std::filesystem::path directory = UniqueTestDirectory("flight-abort-direct");
    std::error_code cleanup_error;
    std::filesystem::remove_all(directory, cleanup_error);
    Check(std::filesystem::create_directories(directory) && chmod(directory.c_str(), 0700) == 0,
          "abort request direct test state directory is private");
    const std::filesystem::path abort_path = directory / ksi::edge::kFlightAbortRequestFilename;

    Check(ksi::edge::ReadAbortRequest(directory.string()).verdict ==
              ksi::edge::AbortRequestReadVerdict::kAbsent,
          "no abort request is a typed absent result, not a fabricated default");

    ksi::edge::AbortRequestRecord record;
    record.requested_by = "operator-1";
    record.reason = "unexpected obstacle";
    record.requested_at_utc_ms = kUtcMs;
    record.mission_id = "mission-a";
    record.dispatch_id = "dispatch-a";
    Check(ksi::edge::WriteAbortRequest(directory.string(), record) ==
              ksi::edge::AbortRequestWriteVerdict::kWritten,
          "a valid abort request writes");

    const auto present = ksi::edge::ReadAbortRequest(directory.string());
    Check(present.verdict == ksi::edge::AbortRequestReadVerdict::kPresent &&
              present.record.requested_by == "operator-1" &&
              present.record.reason == "unexpected obstacle" &&
              present.record.requested_at_utc_ms == kUtcMs && present.record.mission_id == "mission-a" &&
              present.record.dispatch_id == "dispatch-a",
          "the abort request round-trips exactly");

    ksi::edge::AbortRequestRecord no_optional;
    no_optional.requested_by = "operator-2";
    no_optional.reason = "battery critical";
    no_optional.requested_at_utc_ms = kUtcMs + 1;
    Check(ksi::edge::WriteAbortRequest(directory.string(), no_optional) ==
              ksi::edge::AbortRequestWriteVerdict::kWritten,
          "an abort request without mission/dispatch binding writes");
    const auto present_no_optional = ksi::edge::ReadAbortRequest(directory.string());
    Check(present_no_optional.verdict == ksi::edge::AbortRequestReadVerdict::kPresent &&
              present_no_optional.record.mission_id.empty() &&
              present_no_optional.record.dispatch_id.empty(),
          "abort request optional fields are genuinely absent, not empty-but-present");

    ksi::edge::AbortRequestRecord invalid;
    invalid.requested_by.clear();
    invalid.reason = "x";
    invalid.requested_at_utc_ms = kUtcMs;
    Check(ksi::edge::WriteAbortRequest(directory.string(), invalid) ==
              ksi::edge::AbortRequestWriteVerdict::kInvalidRequest,
          "an empty requested_by is refused at write time");

    Check(WritePrivateTextFile(abort_path, AbortRequestRawBytes("op", "reason", kUtcMs) + "unexpected=field\n"),
          "malformed abort request fixture writes");
    Check(ksi::edge::ReadAbortRequest(directory.string()).verdict ==
              ksi::edge::AbortRequestReadVerdict::kMalformed,
          "an unknown abort request field is not silently ignored");

    Check(ksi::edge::ClearAbortRequest(directory.string()), "clearing an abort request succeeds");
    Check(ksi::edge::ReadAbortRequest(directory.string()).verdict ==
              ksi::edge::AbortRequestReadVerdict::kAbsent,
          "a cleared abort request is absent");
    Check(ksi::edge::ClearAbortRequest(directory.string()),
          "clearing an already-absent abort request is a harmless no-op");

    std::filesystem::remove_all(directory, cleanup_error);
}

void TestFlightExecutionPipeline() {
    const std::filesystem::path arm_directory = UniqueTestDirectory("flight-pipeline-arm");
    std::error_code cleanup_error;
    std::filesystem::remove_all(arm_directory, cleanup_error);

    const std::string db_path = UniqueTestDirectory("flight-pipeline-journal").string() + ".sqlite";
    ksi::edge::SqliteStoreForward journal(db_path);
    const auto opened = journal.Open();
    if (!ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
        Check(opened == ksi::edge::StoreForwardVerdict::kBackendUnavailable,
              "flight execution journal fixture without sqlite reports typed unavailable");
        return;
    }
    Check(opened == ksi::edge::StoreForwardVerdict::kAccepted, "flight execution journal opens");

    ksi::edge::ShadowFlightSupervisor supervisor(1'000, 2'000);
    ksi::edge::ActivationContext activation_context;
    activation_context.mission_contract_digest = kPayloadDigest;
    activation_context.risk_policy_pack_digest = kDigest;
    activation_context.valid_from_utc_ms = kFlightUtcMs - 1000;
    activation_context.valid_until_utc_ms = kFlightUtcMs + 10'000'000LL;
    Check(supervisor.Activate(activation_context, kFlightUtcMs), "flight execution supervisor activates");
    Check(supervisor.RecordHeartbeat(kFlightUtcMs, kFlightUtcMs) ==
              ksi::control_plane::HeartbeatVerdict::kRecorded,
          "flight execution supervisor heartbeat records");

    const std::int64_t now = kFlightUtcMs;
    const std::string arm_dir_string = arm_directory.string();

    const auto check_request = [&](const char* what,
                                   const std::function<void(ksi::edge::FlightExecutionRequest*)>& break_it,
                                   ksi::edge::FlightExecutionVerdict expected) {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        break_it(&request);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) == expected, what);
    };

    // ── golden path: 전량 통과 → ELIGIBLE_FOR_START, durable 기록 확정 ────────
    ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
    {
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        const ksi::edge::FlightExecutionVerdict verdict =
            ksi::edge::EvaluateFlightExecution(request, now, &decision);
        Check(verdict == ksi::edge::FlightExecutionVerdict::kEligibleForStart,
              "golden flight execution request is eligible for start");
        Check(decision.arming_token_verdict == ksi::edge::ArmingTokenVerdict::kConsumed,
              "golden path consumes the arming nonce");
        Check(decision.envelope_rederivation.verdict == ksi::edge::KmzEnvelopeRederivationVerdict::kDerived &&
                  decision.envelope_rederivation.observed_min_altitude_m == 40.0 &&
                  decision.envelope_rederivation.observed_max_altitude_m == 40.0 &&
                  decision.envelope_rederivation.waypoint_count == 3U,
              "golden path rederives the real KMZ altitude range");
        Check(decision.ceiling_guard.verdict == ksi::edge::CeilingGuardVerdict::kPassed,
              "golden path passes the ceiling guard");
        Check(decision.journal_verdict == ksi::edge::FlightStartAttemptJournalVerdict::kAccepted,
              "golden path durably records the attempt");
        const std::vector<ksi::edge::FlightStartAttemptRecord> attempts =
            journal.FlightStartAttempts(kFlightMissionId);
        Check(!attempts.empty() && attempts.back().outcome == "ELIGIBLE_FOR_START" &&
                  attempts.back().attempt_id == decision.flight_start_attempt_id &&
                  attempts.back().kmz_sha256 == kSampleKmzSha256,
              "flight start attempt journal row records eligibility with the KMZ digest");
    }
    Check(ksi::edge::ConsumeFieldArmingToken(arm_dir_string, kFlightEdgeDeviceId, kFlightMissionId,
                                             kFlightDispatchId, ksi::edge::FlightExecutionStage::kS2, now)
                  .verdict == ksi::edge::ArmingTokenVerdict::kMissing,
          "a consumed arming nonce cannot be reused for a second start attempt");

    // 방어적 실패: 호출자가 음수 시계를 준 것은 activation 무효(kActivationInvalid,
    // [1])와 사유가 다르다 — durable 진단 문자열이 원인을 정확히 가리켜야 한다
    // (독립 검토가 지적한 오분류를 회귀 시험으로 고정).
    {
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, -1, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kInvalidClock,
              "a negative caller clock is refused as INVALID_CLOCK, not misattributed to activation");
        Check(std::string(ksi::edge::ToString(decision.verdict)) == "INVALID_CLOCK",
              "the diagnostic string for a negative clock is INVALID_CLOCK");
    }

    // [0] 요청 단계가 컴파일 상한을 넘으면 arming 을 건드리지 않고 즉시 거부한다.
    {
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        request.requested_stage = ksi::edge::FlightExecutionStage::kS3;
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kStageBelowRequired,
              "a stage beyond the compiled ceiling is refused before any file I/O");
        Check(decision.journal_verdict == ksi::edge::FlightStartAttemptJournalVerdict::kBackendUnavailable,
              "a stage-0 refusal never reaches the durable journal (no trusted identity yet)");
    }

    // [1] 활성화 무효.
    {
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        request.activation.verdict = ksi::edge::NativeActivationVerdict::kExpired;
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kActivationInvalid,
              "an invalid native activation snapshot is refused before arming");
    }

    // [2] Core 서명 비행 인가 — 거부 사례 전량(정상은 golden path 에서 확인했다).
    check_request("unverified Core authorization is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->core_authorization.verified = false; },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationNotVerified);
    check_request("Core authorization missing an aircraft serial is malformed",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.aircraft_serial_number.clear();
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationMalformed);
    check_request("Core authorization for a different stage is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.authorized_stage = ksi::edge::FlightExecutionStage::kS1;
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationStageMismatch);
    check_request("Core authorization for a different edge device is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.edge_device_id = "edge-other";
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationDeviceMismatch);
    check_request("Core authorization for a different mission is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.mission_id = "mission-other";
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationMissionMismatch);
    check_request("Core authorization for a different dispatch is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.dispatch_id = "dispatch-other";
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationDispatchMismatch);
    check_request("Core authorization for a different mission contract is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.mission_contract_digest = kDigest;
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationContractMismatch);
    check_request("an overlong Core authorization TTL is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.expires_at_utc_ms =
                          r->core_authorization.issued_at_utc_ms + 10'000'000LL;
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationTtlTooLong);
    check_request("a not-yet-valid Core authorization is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.issued_at_utc_ms += 1'000'000LL;
                      r->core_authorization.expires_at_utc_ms += 1'000'000LL;
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationNotYetValid);
    check_request("an expired Core authorization is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->core_authorization.issued_at_utc_ms -= 1'000'000LL;
                      r->core_authorization.expires_at_utc_ms -= 1'000'000LL;
                  },
                  ksi::edge::FlightExecutionVerdict::kCoreAuthorizationExpired);

    // [3] arming — 정상은 golden path 에서 확인했다. 거부 사례.
    {
        // 위 [2] 시험들은 코어 인가 실패 전에 arming 을 먼저 써 둔다(check_request
        // 의 규약) — 그 인가가 실패하면 토큰은 소비되지 않은 채 남는다. 이
        // 시험은 "토큰 자체가 없다"를 보려는 것이므로 그 잔여 파일을 명시적으로
        // 지운다.
        std::filesystem::remove(arm_directory / ksi::edge::kFieldArmingTokenFilename, cleanup_error);
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        // arming 파일을 일부러 다시 쓰지 않는다.
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kArmingTokenMissing,
              "a missing arming token is refused at the pipeline level");
    }
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS1, now);  // 단계 불일치
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kArmingTokenStageMismatch,
              "an arming token issued for a different stage is refused at the pipeline level");
    }

    // [4] KMZ 미가용.
    check_request("a missing mission KMZ handoff is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->kmz.verdict = ksi::edge::NativeMissionKmzVerdict::kMissing;
                  },
                  ksi::edge::FlightExecutionVerdict::kKmzUnavailable);

    // [5] 봉투 재도출.
    check_request("an inverted declared envelope is malformed",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->declared_envelope.min_altitude_m = 100.0;
                      r->declared_envelope.max_altitude_m = 10.0;
                  },
                  ksi::edge::FlightExecutionVerdict::kEnvelopeMalformed);
    check_request("a declared excluded volume is refused (route geometry cannot guarantee avoidance)",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->declared_envelope.excluded_volume_ids = {"vol-hazard"};
                  },
                  ksi::edge::FlightExecutionVerdict::kEnvelopeExcludedVolumesPresent);
    check_request("an empty allowed-volume list is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->declared_envelope.allowed_volume_ids.clear(); },
                  ksi::edge::FlightExecutionVerdict::kEnvelopeAllowedVolumesEmpty);
    check_request("a KMZ that fails to re-parse is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->kmz.kmz.bytes = kMissionKmzBody; },
                  ksi::edge::FlightExecutionVerdict::kEnvelopeRederivationFailed);
    check_request("a declared altitude window below the KMZ's real altitude is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->declared_envelope.min_altitude_m = 10.0;
                      r->declared_envelope.max_altitude_m = 30.0;  // KMZ 실측은 40m
                  },
                  ksi::edge::FlightExecutionVerdict::kEnvelopeAltitudeOutOfBounds);

    // [6] 상한 가드.
    check_request("missing DTM coverage is refused by the ceiling guard",
                  [](ksi::edge::FlightExecutionRequest* r) { r->ceiling_guard_input.has_dtm_coverage = false; },
                  ksi::edge::FlightExecutionVerdict::kCeilingGuardRejected);
    check_request("undeclared site density is refused by the ceiling guard",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->ceiling_guard_input.site_density = ksi::edge::SiteDensityDeclaration::kUnspecified;
                  },
                  ksi::edge::FlightExecutionVerdict::kCeilingGuardRejected);

    // [7] 감독기.
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, &journal);
        request.supervisor = nullptr;
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kSupervisorMissing,
              "a missing supervisor pointer is refused");
    }
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::ShadowFlightSupervisor unactivated_supervisor(1'000, 2'000);
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &unactivated_supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kSupervisorNotActivated,
              "an unactivated supervisor is refused");
    }
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::ShadowFlightSupervisor cold_supervisor(1'000, 2'000);
        Check(cold_supervisor.Activate(activation_context, now),
              "cold supervisor activates for the not-nominal test");
        // heartbeat 를 한 번도 기록하지 않는다 — supervisor.hpp 의 "부팅 직후는
        // kFailClosed" 계약을 그대로 재사용한다.
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &cold_supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kSupervisorNotNominal,
              "a supervisor with no recorded heartbeat is fail-closed, not nominal");
    }
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::ShadowFlightSupervisor rollback_supervisor(1'000, 2'000);
        ksi::edge::ActivationContext rollback_context = activation_context;
        rollback_context.valid_until_utc_ms = now + 10'000'000LL;
        const std::int64_t later = now + 5000;
        Check(rollback_supervisor.Activate(rollback_context, later) &&
                  rollback_supervisor.RecordHeartbeat(later, later) ==
                      ksi::control_plane::HeartbeatVerdict::kRecorded,
              "rollback supervisor activates in the future for the clock-rollback test");
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &rollback_supervisor, &journal);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kSupervisorClockRollback,
              "a now_utc_ms behind the supervisor's last observed wall clock is refused");
    }

    // [8] 기체 사전조건.
    check_request("missing STATUS_FLIGHT telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.flight_status_present = false; },
                  ksi::edge::FlightExecutionVerdict::kAircraftFlightStatusMissing);
    check_request("an airborne aircraft (STATUS_FLIGHT != STOPED) is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.flight_status = 2U; },
                  ksi::edge::FlightExecutionVerdict::kAircraftFlightStatusNotStopped);
    check_request("an aircraft serial mismatch is refused",
                  [](ksi::edge::FlightExecutionRequest* r) {
                      r->aircraft.observed_aircraft_serial_number = "AC-WRONG";
                  },
                  ksi::edge::FlightExecutionVerdict::kAircraftSerialMismatch);
    check_request("missing battery telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.battery_present = false; },
                  ksi::edge::FlightExecutionVerdict::kAircraftBatteryMissing);
    check_request("insufficient battery is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.battery_percent_1pct = 5U; },
                  ksi::edge::FlightExecutionVerdict::kAircraftBatteryInsufficient);
    check_request("missing home point telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.home_point_present = false; },
                  ksi::edge::FlightExecutionVerdict::kAircraftHomePointMissing);
    check_request("an unset home point is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.home_point_set_status = 0U; },
                  ksi::edge::FlightExecutionVerdict::kAircraftHomePointNotSet);
    check_request("missing position-solution telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.position_solution_present = false; },
                  ksi::edge::FlightExecutionVerdict::kAircraftPositionQualityMissing);
    check_request("an insufficient RTK/GPS position solution is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.position_solution_property = 1U; },
                  ksi::edge::FlightExecutionVerdict::kAircraftPositionQualityInsufficient);
    check_request("missing flight-anomaly telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.flight_anomaly_present = false; },
                  ksi::edge::FlightExecutionVerdict::kAircraftFlightAnomalyMissing);
    check_request("any set flight-anomaly bit is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.flight_anomaly_bits = 1U; },
                  ksi::edge::FlightExecutionVerdict::kAircraftFlightAnomalyPresent);
    check_request("stale aircraft telemetry is refused",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft.battery_observed_utc_ms -= 60'000LL; },
                  ksi::edge::FlightExecutionVerdict::kAircraftTelemetryStale);
    check_request("an unset telemetry-freshness policy is refused (never treated as 'skip')",
                  [](ksi::edge::FlightExecutionRequest* r) { r->aircraft_policy.maximum_telemetry_age_ms = 0; },
                  ksi::edge::FlightExecutionVerdict::kAircraftTelemetryStale);

    // [9] durable 기록 — journal 부재면 성공은 성립하지 않는다.
    {
        ArmForFlightTest(arm_dir_string, ksi::edge::FlightExecutionStage::kS2, now);
        ksi::edge::FlightExecutionRequest request =
            BuildGoldenFlightRequest(arm_dir_string, now, &supervisor, nullptr);
        ksi::edge::FlightExecutionDecision decision;
        Check(ksi::edge::EvaluateFlightExecution(request, now, &decision) ==
                  ksi::edge::FlightExecutionVerdict::kJournalUnavailable,
              "an otherwise-eligible attempt without a journal is not eligible "
              "(durable record is required for success)");
    }

    // 거부도 같은 형식으로 기록된다(ADR §9) — 위 ceiling-guard 거부 하나를 저널에서 확인.
    {
        const std::vector<ksi::edge::FlightStartAttemptRecord> attempts =
            journal.FlightStartAttempts(kFlightMissionId);
        const bool has_refused_ceiling_guard = std::any_of(
            attempts.begin(), attempts.end(), [](const ksi::edge::FlightStartAttemptRecord& record) {
                return record.outcome == "REFUSED_CEILING_GUARD_REJECTED";
            });
        Check(has_refused_ceiling_guard,
              "a refused attempt is durably recorded with a REFUSED_<verdict> outcome, not silently dropped");
    }

    std::filesystem::remove_all(arm_directory, cleanup_error);
}

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
    TestNativeMissionKmzHandoff();
    TestFrameQueue();
    TestTelemetryAlignment();
    TestDfineAndWorldEntity();
    TestProfiledGroundPlaneProjector();
    TestRiskAndShadow();
    TestArtifactVaultAndStoreForward();
    TestCoreRestSyncWire();
#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
    TestEvidenceAttestationSigner();
#endif
#if KSI_EDGE_HAVE_CURL_TRANSPORT
    TestCurlExecutorGuards();
#endif
    TestCandidateTimingArtifacts();
    TestWorldStateTrackerEviction();
    TestPipeline();
    TestNativeArtifactWire();
    TestNativeEvidenceBuilder();
    TestJpegDimensionGolden();
    TestMediaIdConvention();
    TestArtifactVaultRemoval();
    TestSourceMediaRightsMarker();
    TestCoreRestSourceMediaWire();
    TestSourceMediaJournalGuards();
    TestMediaOffloadConveyor();
    TestMediaOffloadUploadDurableBeforePurge();
    TestMediaOffloadRightsReleasedDuringOffload();
    TestMediaOffloadReconcilesRightsAtStartup();
    TestSpoolArtifactIdUnambiguous();
    TestFlightExecutionKmzEnvelopeRederivation();
    TestFlightExecutionCeilingGuardDirect();
    TestFlightExecutionArmingTokenDirect();
    TestFlightExecutionAbortRequestDirect();
    TestFlightExecutionPipeline();
    if (g_skipped_groups > 0) {
        std::fprintf(stderr,
                     "[WARN] SQLite 백엔드 없이 %d개 계약 묶음을 건너뛰었다 — "
                     "이 실행은 저장후전달 순서·WAL 복구를 검증하지 않았다.\n",
                     g_skipped_groups);
        const char* require = std::getenv("KSI_EDGE_TESTS_REQUIRE_SQLITE");
        if (require != nullptr && std::string_view(require) == "1") {
            std::fprintf(stderr,
                         "[FAIL] KSI_EDGE_TESTS_REQUIRE_SQLITE=1 인데 건너뛴 묶음이 있다.\n");
            return 1;
        }
    }
    if (g_failures == 0) {
        std::printf("edge runtime tests: %d checks passed, %d groups skipped\n",
                    g_checks, g_skipped_groups);
        return 0;
    }
    std::fprintf(stderr, "edge runtime tests: %d/%d checks failed, %d groups skipped\n",
                 g_failures, g_checks, g_skipped_groups);
    return 1;
}

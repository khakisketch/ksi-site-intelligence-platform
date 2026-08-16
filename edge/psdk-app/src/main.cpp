// Manifold 3 PSDK application entry point for the KSI Edge shadow slice.
//
// This binary owns PSDK startup plus bounded sensor ingress.  KSI source
// intentionally contains no DJI Flight Control header or call.  The vendor
// static PSDK archive may retain unused FlightController *definitions* in the
// final ELF, so strict whole-binary symbol absence is a separately reported
// vendor-linkage gate rather than a claim made here.  A separately verified
// native activation handoff can be loaded, but until a registered TensorRT
// model and calibrated projector are available its worker remains capture-only
// and emits no risk/event/action.

#include <dji_core.h>
#include <dji_fc_subscription.h>
#include <dji_liveview.h>
#include <dji_typedef.h>

#include "dji_sdk_app_info.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <utility>

#include <sys/stat.h>
#include <unistd.h>

extern "C" {
#include "platform/logger_console_glue.h"
#include "platform/osal_glue.h"
#include "platform/socket_glue.h"
#include "platform/usb_bulk_glue.h"
}

#include "ksi/edge/activation.hpp"
#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/calibrated_projector.hpp"
#include "ksi/edge/core_sync_http.hpp"
#include "ksi/edge/crypto.hpp"
#include "ksi/edge/dfine.hpp"
#include "ksi/edge/event_timing.hpp"
#include "ksi/edge/evidence_builder.hpp"
#include "ksi/edge/frame_queue.hpp"
#include "ksi/edge/media_offload.hpp"
#include "ksi/edge/mission_kmz.hpp"
#include "ksi/edge/pipeline.hpp"
#include "ksi/edge/runtime_profile.hpp"
#include "ksi/edge/shadow.hpp"
#include "ksi/edge/store_forward.hpp"
#include "ksi/edge/sync.hpp"
#include "ksi/edge/telemetry.hpp"
#include "ksi/edge/tensorrt.hpp"

#ifndef KSI_EDGE_HAVE_CURL_TRANSPORT
#define KSI_EDGE_HAVE_CURL_TRANSPORT 0
#endif

#if KSI_EDGE_HAVE_CURL_TRANSPORT
#include "ksi/edge/curl_https_executor.hpp"
#endif

namespace {

constexpr std::size_t kFrameSlots = 4U;
constexpr std::size_t kMaxRgbFrameBytes = 3840U * 2160U * 3U;
constexpr std::size_t kTelemetrySamples = 1024U;
constexpr std::int64_t kNanosecondsPerSecond = 1'000'000'000LL;
constexpr std::int64_t kNanosecondsPerMicrosecond = 1'000LL;
constexpr std::int64_t kNanosecondsPerMillisecond = 1'000'000LL;
constexpr std::int64_t kMicrosecondsPerMillisecond = 1'000LL;
constexpr std::int64_t kMillisecondsPerSecond = 1'000LL;
constexpr std::int64_t kActivationRefreshPeriodNs = 1'000'000'000LL;
constexpr std::int64_t kCoreSyncPeriodMs = 1'000LL;
constexpr std::int64_t kMediaOffloadPeriodMs = 1'000LL;
constexpr std::int64_t kShadowIntentTtlMs = 1'000LL;
constexpr std::size_t kMaximumArtifactBytes = 32U * 1024U * 1024U;
constexpr double kRadiansPerDegree = 0.017453292519943295769;

#ifndef KSI_PSDK_APP_EDGE_ACTIVATION_CONFIGURED
#define KSI_PSDK_APP_EDGE_ACTIVATION_CONFIGURED 0
#endif

#ifndef KSI_PSDK_APP_CORE_SYNC_CONFIGURED
#define KSI_PSDK_APP_CORE_SYNC_CONFIGURED 0
#endif

#ifndef KSI_PSDK_APP_PERCEPTION_CONFIGURED
#define KSI_PSDK_APP_PERCEPTION_CONFIGURED 0
#endif

#ifndef KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED
#define KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED 0
#endif

volatile sig_atomic_t g_termination_requested = 0;

class AppRuntime;
std::atomic<AppRuntime*> g_runtime{nullptr};

std::int64_t MonotonicNowNs() noexcept {
    timespec value {};
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0 || value.tv_sec < 0 || value.tv_nsec < 0) {
        return 0;
    }
    if (static_cast<std::int64_t>(value.tv_sec) >
        std::numeric_limits<std::int64_t>::max() / kNanosecondsPerSecond) {
        return 0;
    }
    return static_cast<std::int64_t>(value.tv_sec) * kNanosecondsPerSecond +
           static_cast<std::int64_t>(value.tv_nsec);
}

std::int64_t RealtimeNowUtcMs() noexcept {
    timespec value {};
    if (clock_gettime(CLOCK_REALTIME, &value) != 0 || value.tv_sec < 0 || value.tv_nsec < 0) {
        return 0;
    }
    if (static_cast<std::int64_t>(value.tv_sec) >
        std::numeric_limits<std::int64_t>::max() / kMillisecondsPerSecond) {
        return 0;
    }
    return static_cast<std::int64_t>(value.tv_sec) * kMillisecondsPerSecond +
           static_cast<std::int64_t>(value.tv_nsec) / kNanosecondsPerMillisecond;
}

std::int64_t PSDKTimestampNs(const T_DjiDataTimestamp* timestamp) noexcept {
    if (timestamp == nullptr) {
        return 0;
    }
    const std::int64_t milliseconds = static_cast<std::int64_t>(timestamp->millisecond);
    const std::int64_t microseconds = static_cast<std::int64_t>(timestamp->microsecond);
    if (milliseconds >
            (std::numeric_limits<std::int64_t>::max() - microseconds) / kMicrosecondsPerMillisecond ||
        milliseconds * kMicrosecondsPerMillisecond + microseconds >
            std::numeric_limits<std::int64_t>::max() / kNanosecondsPerMicrosecond) {
        return 0;
    }
    return (milliseconds * kMicrosecondsPerMillisecond + microseconds) *
           kNanosecondsPerMicrosecond;
}

bool IsPlaceholderCredential() {
    return std::strcmp(USER_APP_NAME, "your_app_name") == 0 ||
           std::strcmp(USER_APP_ID, "your_app_id") == 0 ||
           std::strcmp(USER_APP_KEY, "your_app_key") == 0 ||
           std::strcmp(USER_APP_LICENSE, "your_app_license") == 0 ||
           std::strcmp(USER_DEVELOPER_ACCOUNT, "your_developer_account") == 0;
}

bool CopyCredentialField(char* destination, std::size_t capacity, const char* value) {
    if (destination == nullptr || value == nullptr) {
        return false;
    }
    const std::size_t length = std::strlen(value);
    if (length >= capacity) {
        return false;
    }
    std::memcpy(destination, value, length);
    return true;
}

bool FillUserInfo(T_DjiUserInfo* output) {
    if (output == nullptr) {
        return false;
    }
    std::memset(output, 0, sizeof(*output));
    return CopyCredentialField(output->appName, sizeof(output->appName), USER_APP_NAME) &&
           CopyCredentialField(output->appId, sizeof(output->appId), USER_APP_ID) &&
           CopyCredentialField(output->appKey, sizeof(output->appKey), USER_APP_KEY) &&
           CopyCredentialField(output->appLicense, sizeof(output->appLicense), USER_APP_LICENSE) &&
           CopyCredentialField(output->developerAccount, sizeof(output->developerAccount),
                               USER_DEVELOPER_ACCOUNT) &&
           CopyCredentialField(output->baudRate, sizeof(output->baudRate), USER_BAUD_RATE);
}

void OnTerminationSignal(int signal_number) {
    (void)signal_number;
    g_termination_requested = 1;
}

void LogPsdError(const char* operation, T_DjiReturnCode code) {
    std::fprintf(stderr, "[ksi-edge-shadow] %s failed: 0x%08llX\n", operation,
                 static_cast<unsigned long long>(code));
}

bool EnsurePrivateStateDirectory(const std::string& directory) {
    if (directory.empty() || directory.front() != '/') {
        return false;
    }
    struct stat state {};
    // Deployment creates the parent before DPK startup.  Creating a path below
    // a potentially shared parent here would leave a check-then-use window for
    // the evidence journal, so absence is a fail-closed configuration error.
    if (lstat(directory.c_str(), &state) != 0 || !S_ISDIR(state.st_mode) ||
        S_ISLNK(state.st_mode) || state.st_uid != geteuid()) {
        return false;
    }
    if ((state.st_mode & 0077) != 0 && chmod(directory.c_str(), 0700) != 0) {
        return false;
    }
    return lstat(directory.c_str(), &state) == 0 && S_ISDIR(state.st_mode) &&
           !S_ISLNK(state.st_mode) && state.st_uid == geteuid() && (state.st_mode & 0077) == 0;
}

bool IsPrivateOwnedDirectory(const std::string& directory) {
    if (directory.empty() || directory.front() != '/') {
        return false;
    }
    struct stat state {};
    return lstat(directory.c_str(), &state) == 0 && S_ISDIR(state.st_mode) &&
           !S_ISLNK(state.st_mode) && state.st_uid == geteuid() && (state.st_mode & 0077) == 0;
}
// PositionVO is a best-effort, origin-less N/E/D coordinate system.  It is
// retained only to pair callback times while a calibrated site-frame projector
// is unavailable; it is never promoted to a WorldEntity or RiskField here.
class AppRuntime {
public:
    AppRuntime()
        : frames_(kFrameSlots, kMaxRgbFrameBytes),
          telemetry_(kTelemetrySamples),
          shadow_supervisor_(1'000, 2'000) {}

    AppRuntime(const AppRuntime&) = delete;
    AppRuntime& operator=(const AppRuntime&) = delete;

    // This runs before PSDK callbacks are opened and then once per second from
    // the worker.  It deliberately consumes only the private artifact emitted
    // by the verified Python activation bridge; no signature parser or Python
    // process is placed in the callback or per-frame path.
    void ConfigureNativeActivation(std::string state_directory, std::string edge_device_id,
                                   std::string runtime_version) {
        activation_state_directory_ = std::move(state_directory);
        activation_edge_device_id_ = std::move(edge_device_id);
        activation_runtime_version_ = std::move(runtime_version);
        RefreshNativeActivation();
    }

    // Track B's mission_kmz.cpp had zero production caller before this method
    // (grep-verified) — only edge_runtime_tests.cpp exercised it.  This closes
    // that gap without adding any new PSDK symbol, secret, or state directory:
    // the KMZ sidecar is written by the same verified Python bridge, next to
    // ``active-dispatch.native.v1``, so it shares activation's directory and
    // device identity.  Call once at startup; every subsequent refresh below
    // keeps the cached NativeMissionKmz bound to whichever mission is active.
    void ConfigureMissionKmz() {
        mission_kmz_configured_ = true;
        RefreshMissionKmz();
    }

    // Perception is configured only at DPK startup, outside PSDK callbacks.
    // It owns one durable journal/vault pair; Core sync may borrow those same
    // instances but never creates a second journal over the same state path.
    void ConfigurePerception(std::string state_directory, std::string model_artifact_directory) {
        ResetPerceptionProvisioning();
        perception_state_directory_ = std::move(state_directory);
        perception_model_artifact_directory_ = std::move(model_artifact_directory);
        perception_setup_verdict_ = "UNCONFIGURED";
        perception_pipeline_verdict_ = "UNCONFIGURED";
        if (!EnsurePrivateStateDirectory(perception_state_directory_)) {
            perception_setup_verdict_ = "UNSAFE_STATE_DIRECTORY";
            return;
        }
        if (!IsPrivateOwnedDirectory(perception_model_artifact_directory_)) {
            perception_setup_verdict_ = "UNSAFE_MODEL_DIRECTORY";
            return;
        }
        if (!ksi::edge::TensorRtBackendCompiled()) {
            perception_setup_verdict_ = "TENSORRT_BACKEND_UNAVAILABLE";
            return;
        }
        try {
            const std::filesystem::path state_path(perception_state_directory_);
            auto evidence_vault = std::make_unique<ksi::edge::ArtifactVault>(
                (state_path / "artifacts").string(), kMaximumArtifactBytes);
            auto store = std::make_unique<ksi::edge::SqliteStoreForward>(
                (state_path / "store-forward.sqlite").string());
            if (store->Open() != ksi::edge::StoreForwardVerdict::kAccepted) {
                perception_setup_verdict_ = "STORE_FORWARD_UNAVAILABLE";
                return;
            }
            // This journal writes an immutable local record only after every
            // contract/policy/TTL/heartbeat gate has passed.  It shares the
            // evidence vault so it inherits the same private owner/no-symlink
            // and fsync guarantees, but it is not a DJI flight-command path.
            auto shadow_journal =
                std::make_unique<ksi::edge::ArtifactVaultShadowActionJournal>(evidence_vault.get());
            // Candidate latency is recorded only after the SQLite transaction
            // succeeds. This private writer is HIL/replay evidence, not an
            // extra EventBundle artifact that could break its atomic plan.
            auto timing_writer =
                std::make_unique<ksi::edge::EventTimingArtifactWriter>(evidence_vault.get());
            perception_vault_ = std::move(evidence_vault);
            perception_store_ = std::move(store);
            perception_shadow_journal_ = std::move(shadow_journal);
            perception_timing_writer_ = std::move(timing_writer);
            perception_provisioned_ = true;
            perception_setup_verdict_ = "READY";
            perception_pipeline_verdict_ = "AWAITING_ACTIVE_DISPATCH";
            // ConfigureNativeActivation may have run just before this method;
            // retry now that a valid dispatch can construct its pipeline.
            RefreshNativeActivation();
        } catch (const std::exception&) {
            ResetPerceptionProvisioning();
            perception_setup_verdict_ = "PERCEPTION_CONFIGURATION_REJECTED";
        }
    }

#if KSI_EDGE_HAVE_CURL_TRANSPORT
    // This is intentionally a startup/deployment path, not a PSDK callback or
    // frame worker.  A failure leaves capture active but Core sync disabled;
    // it never substitutes an unpinned or unauthenticated transport.
    void ConfigureCoreSync(std::string state_directory, std::string edge_device_id,
                           std::string core_base_url, std::string bearer_token_file,
                           std::string ca_bundle_path, std::string core_tls_pin,
                           std::string evidence_tls_pin) {
        core_sync_setup_verdict_ = "UNCONFIGURED";
        core_sync_configured_.store(false, std::memory_order_release);
        core_sync_driver_.reset();
        core_sync_transport_.reset();
        core_sync_executor_.reset();
        core_sync_store_.reset();
        core_sync_vault_.reset();
        core_sync_base_url_.clear();
        core_sync_bearer_token_.clear();
        if (!EnsurePrivateStateDirectory(state_directory) || edge_device_id.empty()) {
            core_sync_setup_verdict_ = "UNSAFE_STATE_DIRECTORY";
            return;
        }
        const ksi::edge::PrivateBearerTokenLoadResult token =
            ksi::edge::LoadPrivateBearerTokenFile(bearer_token_file);
        if (token.verdict != ksi::edge::PrivateBearerTokenVerdict::kLoaded) {
            core_sync_setup_verdict_ = ksi::edge::ToString(token.verdict);
            return;
        }
        try {
            const std::filesystem::path state_path(state_directory);
            const bool uses_perception_state =
                !perception_state_directory_.empty() &&
                state_directory == perception_state_directory_;
            if (uses_perception_state && !perception_provisioned_) {
                // CMake requires equality when both tiers are enabled. Do not
                // silently create a second database if perception setup failed;
                // that would turn one intended durable sequence into two.
                core_sync_setup_verdict_ = "PERCEPTION_JOURNAL_UNAVAILABLE";
                return;
            }
            const bool share_perception_journal =
                perception_provisioned_ && state_directory == perception_state_directory_ &&
                perception_vault_ != nullptr && perception_store_ != nullptr &&
                perception_store_->is_open();
            std::unique_ptr<ksi::edge::ArtifactVault> owned_vault;
            std::unique_ptr<ksi::edge::SqliteStoreForward> owned_store;
            ksi::edge::ArtifactVault* vault = nullptr;
            ksi::edge::SqliteStoreForward* store = nullptr;
            if (share_perception_journal) {
                vault = perception_vault_.get();
                store = perception_store_.get();
            } else {
                owned_vault = std::make_unique<ksi::edge::ArtifactVault>(
                    (state_path / "artifacts").string(), kMaximumArtifactBytes);
                owned_store = std::make_unique<ksi::edge::SqliteStoreForward>(
                    (state_path / "store-forward.sqlite").string());
                const ksi::edge::StoreForwardVerdict opened = owned_store->Open();
                if (opened != ksi::edge::StoreForwardVerdict::kAccepted) {
                    core_sync_setup_verdict_ = ksi::edge::ToString(opened);
                    return;
                }
                vault = owned_vault.get();
                store = owned_store.get();
            }
            const std::string configured_core_base_url = core_base_url;
            auto executor = std::make_unique<ksi::edge::CurlHttpsRequestExecutor>(
                ksi::edge::CurlHttpsExecutorConfig{std::move(core_base_url), std::move(core_tls_pin),
                                                    std::move(evidence_tls_pin), std::move(ca_bundle_path)});
            auto transport = std::make_unique<ksi::edge::CoreRestSyncTransport>(
                ksi::edge::CoreRestSyncConfig{configured_core_base_url, token.bearer_token,
                                               256U * 1024U, 2U * 1024U * 1024U},
                executor.get(), vault);
            auto driver = std::make_unique<ksi::edge::StoreForwardSyncDriver>(store);
            core_sync_vault_ = std::move(owned_vault);
            core_sync_store_ = std::move(owned_store);
            core_sync_executor_ = std::move(executor);
            core_sync_transport_ = std::move(transport);
            core_sync_driver_ = std::move(driver);
            // Media offload (below) reuses this exact origin/bearer pair for
            // its own Core-facing transport rather than re-deriving them from
            // the CMake strings a second time.  Neither value is logged.
            core_sync_base_url_ = configured_core_base_url;
            core_sync_bearer_token_ = token.bearer_token;
            core_sync_setup_verdict_ = "READY";
            last_core_sync_verdict_.store(
                static_cast<int>(ksi::edge::CoreSyncVerdict::kAcknowledged), std::memory_order_release);
            core_sync_configured_.store(true, std::memory_order_release);
        } catch (const std::exception&) {
            // Do not echo a path, URL, TLS pin, or exception payload: deployment
            // strings may contain sensitive topology.  The typed state is enough
            // for an operator to diagnose the configuration gate.
            core_sync_setup_verdict_ = "TRANSPORT_CONFIGURATION_REJECTED";
        }
    }

    // Media offload proves ``MediaOffloadWorker::RunOnce`` is actually driven
    // by a production main loop — an independent reviewer confirmed zero
    // caller before this method (only edge_runtime_tests.cpp exercised it).
    // No PSDK ``DjiCameraManager_*`` adapter exists anywhere in this
    // repository yet (media_offload.hpp's own header comment: "실기 미확인을
    // IMediaSourcePort 하나로 격리한다"), so ``source_`` is pinned to
    // FakeMediaSourcePort with zero seeded entries.  That means this wiring
    // proves the worker's periodic drive loop, its Core-facing transport, and
    // its recoverable-failure handling run inside the packaged binary — it
    // recovers zero real photos.  Requires ConfigureCoreSync to have already
    // succeeded: it reuses that HTTPS executor and bearer token rather than
    // opening a second one, and it assumes CORE_BEARER_TOKEN_FILE also carries
    // EDGE_SOURCE_MEDIA_WRITE (a separate scope needs its own CMake input,
    // which this slice does not add).
    void ConfigureMediaOffload() {
        media_offload_setup_verdict_ = "UNCONFIGURED";
        media_offload_worker_.reset();
        media_offload_transport_.reset();
        media_offload_source_.reset();
        {
            std::lock_guard<std::mutex> lock(media_offload_mission_mutex_);
            media_offload_mission_id_.clear();
        }
        if (!core_sync_configured_.load(std::memory_order_acquire) || core_sync_executor_ == nullptr ||
            core_sync_base_url_.empty() || core_sync_bearer_token_.empty()) {
            media_offload_setup_verdict_ = "CORE_SYNC_REQUIRED";
            return;
        }
        // The journal (SqliteStoreForward) and spool (ArtifactVault) are the
        // same multi-domain durable store already open for perception/core
        // sync — SourceMedia* methods live on SqliteStoreForward itself, and
        // ArtifactVault is a generic artifact_id-keyed blob store (mediaId
        // prefixed "srcmedia-", so it cannot collide with an evidence
        // artifact id).  A third SQLite connection to the same purpose is not
        // opened.  The rights marker lives beside the activation snapshot,
        // per MediaOffloadPolicy::state_directory's own doc comment.
        ksi::edge::ArtifactVault* const vault = OperationalVault();
        ksi::edge::SqliteStoreForward* const store = OperationalStore();
        if (vault == nullptr || store == nullptr || activation_state_directory_.empty()) {
            media_offload_setup_verdict_ = "JOURNAL_UNAVAILABLE";
            return;
        }
        try {
            ksi::edge::MediaOffloadPolicy policy;
            policy.state_directory = activation_state_directory_;
            auto source = std::make_unique<ksi::edge::FakeMediaSourcePort>();
            auto transport = std::make_unique<ksi::edge::CoreRestSourceMediaTransport>(
                ksi::edge::CoreRestSourceMediaConfig{core_sync_base_url_, core_sync_bearer_token_},
                core_sync_executor_.get(), vault);
            auto worker = std::make_unique<ksi::edge::MediaOffloadWorker>(
                std::move(policy), store, vault, source.get(), transport.get());
            media_offload_source_ = std::move(source);
            media_offload_transport_ = std::move(transport);
            media_offload_worker_ = std::move(worker);
            media_offload_setup_verdict_ = "READY";
            // ConfigureNativeActivation may have already run once (Run() calls
            // it first); seed the current mission now instead of waiting up to
            // kActivationRefreshPeriodNs for the next periodic refresh.
            if (active_native_snapshot_.has_value()) {
                std::lock_guard<std::mutex> lock(media_offload_mission_mutex_);
                media_offload_mission_id_ = active_native_snapshot_->mission_id;
            }
        } catch (const std::exception&) {
            media_offload_worker_.reset();
            media_offload_transport_.reset();
            media_offload_source_.reset();
            media_offload_setup_verdict_ = "MEDIA_OFFLOAD_CONFIGURATION_REJECTED";
        }
    }
#endif

    void StartWorker() {
        worker_running_.store(true, std::memory_order_release);
        worker_ = std::thread([this] { DrainWorker(); });
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        if (core_sync_configured_.load(std::memory_order_acquire) && core_sync_driver_ != nullptr &&
            core_sync_transport_ != nullptr) {
            core_sync_worker_running_.store(true, std::memory_order_release);
            core_sync_worker_ = std::thread([this] { DrainCoreSync(); });
        }
        if (media_offload_worker_ != nullptr) {
            media_offload_worker_running_.store(true, std::memory_order_release);
            media_offload_thread_ = std::thread([this] { DrainMediaOffload(); });
        }
#endif
    }

    void StopWorker() {
        worker_running_.store(false, std::memory_order_release);
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        core_sync_worker_running_.store(false, std::memory_order_release);
        media_offload_worker_running_.store(false, std::memory_order_release);
#endif
        if (worker_.joinable()) {
            worker_.join();
        }
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        if (core_sync_worker_.joinable()) {
            core_sync_worker_.join();
        }
        if (media_offload_thread_.joinable()) {
            media_offload_thread_.join();
        }
#endif
    }

    void OpenIngress() { accepting_.store(true, std::memory_order_release); }
    void CloseIngress() { accepting_.store(false, std::memory_order_release); }

    void OnRgbFrame(const uint8_t* bytes, std::uint32_t byte_count,
                    T_DjiLiveviewImageInfo image_info) noexcept {
        if (!accepting_.load(std::memory_order_acquire)) {
            return;
        }
        if (image_info.pixFmt != PIXFMT_RGB_PACKED) {
            ++non_rgb_frames_;
            return;
        }
        const ksi::edge::FrameMetadata metadata = {
            static_cast<std::uint32_t>(image_info.width),
            static_cast<std::uint32_t>(image_info.height),
            image_info.frameId,
            MonotonicNowNs(),
            0,  // DJI RGB callback exposes no camera sensor timestamp.
            RealtimeNowUtcMs(),
        };
        const ksi::edge::FrameDropReason result =
            frames_.PushFromCallback(bytes, static_cast<std::size_t>(byte_count), metadata);
        if (result != ksi::edge::FrameDropReason::kAccepted) {
            ++frame_drops_;
        }
    }

    void OnPosition(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionPositionVO)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionPositionVO position {};
        std::memcpy(&position, bytes, sizeof(position));
        const bool valid = position.xHealth != 0U && position.yHealth != 0U &&
                           position.zHealth != 0U && std::isfinite(position.x) &&
                           std::isfinite(position.y) && std::isfinite(position.z);
        if (position_writer_.test_and_set(std::memory_order_acquire)) {
            ++telemetry_drops_;
            return;
        }
        position_generation_.fetch_add(1U, std::memory_order_acq_rel);
        position_x_.store(position.x, std::memory_order_relaxed);
        position_y_.store(position.y, std::memory_order_relaxed);
        position_z_.store(position.z, std::memory_order_relaxed);
        position_valid_.store(valid, std::memory_order_release);
        position_generation_.fetch_add(1U, std::memory_order_release);
        position_writer_.clear(std::memory_order_release);
        if (!valid) {
            ++telemetry_drops_;
        }
    }

    void OnVelocity(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionVelocity)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionVelocity velocity {};
        std::memcpy(&velocity, bytes, sizeof(velocity));
        // PSDK velocity is NEU while PositionVO is N/E/D.  Flip Z only for the
        // timestamp-pairing sample; no site-frame projection is claimed.
        const bool valid = velocity.health != 0U && std::isfinite(velocity.data.x) &&
                           std::isfinite(velocity.data.y) && std::isfinite(velocity.data.z);
        const std::int64_t received = MonotonicNowNs();
        if (velocity_writer_.test_and_set(std::memory_order_acquire)) {
            ++telemetry_drops_;
            return;
        }
        velocity_generation_.fetch_add(1U, std::memory_order_acq_rel);
        velocity_x_.store(velocity.data.x, std::memory_order_relaxed);
        velocity_y_.store(velocity.data.y, std::memory_order_relaxed);
        velocity_z_.store(-velocity.data.z, std::memory_order_relaxed);
        velocity_received_ns_.store(received, std::memory_order_relaxed);
        velocity_valid_.store(valid, std::memory_order_release);
        velocity_generation_.fetch_add(1U, std::memory_order_release);
        velocity_writer_.clear(std::memory_order_release);
        if (!valid || received <= 0) {
            ++telemetry_drops_;
        }
    }

    void OnPositionFused(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionPositionFused)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionPositionFused position {};
        std::memcpy(&position, bytes, sizeof(position));
        const double latitude = static_cast<double>(position.latitude);
        const double longitude = static_cast<double>(position.longitude);
        const double altitude = static_cast<double>(position.altitude);
        const std::int64_t received = MonotonicNowNs();
        const bool valid = received > 0 && std::isfinite(latitude) && std::isfinite(longitude) &&
                           std::isfinite(altitude) && latitude >= -1.5707963267948966 &&
                           latitude <= 1.5707963267948966 && longitude >= -3.141592653589793 &&
                           longitude <= 3.141592653589793;
        if (global_position_writer_.test_and_set(std::memory_order_acquire)) {
            ++telemetry_drops_;
            return;
        }
        global_position_generation_.fetch_add(1U, std::memory_order_acq_rel);
        global_latitude_rad_.store(latitude, std::memory_order_relaxed);
        global_longitude_rad_.store(longitude, std::memory_order_relaxed);
        global_altitude_m_.store(altitude, std::memory_order_relaxed);
        global_position_received_ns_.store(received, std::memory_order_relaxed);
        global_position_valid_.store(valid, std::memory_order_release);
        global_position_generation_.fetch_add(1U, std::memory_order_release);
        global_position_writer_.clear(std::memory_order_release);
        if (!valid) {
            ++telemetry_drops_;
        }
    }

    void OnGpsDetails(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionGpsDetails)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionGpsDetails details {};
        std::memcpy(&details, bytes, sizeof(details));
        // PSDK declares hacc/vacc in millimetres. Convert exactly once at
        // ingress and retain it as an uncertainty source, never as a pose.
        const double horizontal_sigma_m = static_cast<double>(details.hacc) / 1000.0;
        const double vertical_sigma_m = static_cast<double>(details.vacc) / 1000.0;
        const std::int64_t received = MonotonicNowNs();
        const bool valid = received > 0 && std::isfinite(horizontal_sigma_m) &&
                           std::isfinite(vertical_sigma_m) && horizontal_sigma_m >= 0.0 &&
                           vertical_sigma_m >= 0.0;
        if (position_accuracy_writer_.test_and_set(std::memory_order_acquire)) {
            ++telemetry_drops_;
            return;
        }
        position_accuracy_generation_.fetch_add(1U, std::memory_order_acq_rel);
        horizontal_sigma_m_.store(horizontal_sigma_m, std::memory_order_relaxed);
        vertical_sigma_m_.store(vertical_sigma_m, std::memory_order_relaxed);
        position_accuracy_received_ns_.store(received, std::memory_order_relaxed);
        position_accuracy_valid_.store(valid, std::memory_order_release);
        position_accuracy_generation_.fetch_add(1U, std::memory_order_release);
        position_accuracy_writer_.clear(std::memory_order_release);
        if (!valid) {
            ++telemetry_drops_;
        }
    }

    void OnGimbalAngles(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionGimbalAngles)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionGimbalAngles angles {};
        std::memcpy(&angles, bytes, sizeof(angles));
        // PSDK declares x=pitch, y=roll, z=yaw in degrees for NO_1.
        const double pitch = static_cast<double>(angles.x) * kRadiansPerDegree;
        const double roll = static_cast<double>(angles.y) * kRadiansPerDegree;
        const double yaw = static_cast<double>(angles.z) * kRadiansPerDegree;
        const std::int64_t received = MonotonicNowNs();
        const bool valid = received > 0 && std::isfinite(pitch) && std::isfinite(roll) &&
                           std::isfinite(yaw);
        if (gimbal_writer_.test_and_set(std::memory_order_acquire)) {
            ++telemetry_drops_;
            return;
        }
        gimbal_generation_.fetch_add(1U, std::memory_order_acq_rel);
        gimbal_pitch_rad_.store(pitch, std::memory_order_relaxed);
        gimbal_roll_rad_.store(roll, std::memory_order_relaxed);
        gimbal_yaw_rad_.store(yaw, std::memory_order_relaxed);
        gimbal_received_ns_.store(received, std::memory_order_relaxed);
        gimbal_valid_.store(valid, std::memory_order_release);
        gimbal_generation_.fetch_add(1U, std::memory_order_release);
        gimbal_writer_.clear(std::memory_order_release);
        if (!valid) {
            ++telemetry_drops_;
        }
    }

    void OnHardSync(const uint8_t* bytes, std::uint16_t size,
                    const T_DjiDataTimestamp* timestamp) noexcept {
        if (!accepting_.load(std::memory_order_acquire) || bytes == nullptr ||
            size != sizeof(T_DjiFcSubscriptionHardSync)) {
            ++telemetry_drops_;
            return;
        }
        ksi::edge::Vec3 position;
        ksi::edge::TimedVelocityMps velocity;
        if (!SnapshotPosition(&position) || !SnapshotVelocity(&velocity)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionHardSync hard_sync {};
        std::memcpy(&hard_sync, bytes, sizeof(hard_sync));
        ksi::edge::TelemetrySample sample = {
            MonotonicNowNs(),
            PSDKTimestampNs(timestamp),
            position,
            velocity.value,
            hard_sync.ts.flag != 0U,
            std::nullopt,
            std::nullopt,
            std::nullopt,
            std::nullopt,
            velocity,
        };
        // PSDK 3.16.0 declares this as a Hamilton quaternion rotating aircraft
        // body FRD into ground NED.  Store it with the same FC sample, but do
        // not treat it as a camera/site calibration or as RGB sensor timing.
        sample.body_frd_to_ground_ned = ksi::edge::BodyFrdToGroundNedQuaternion{
            static_cast<double>(hard_sync.q.q0), static_cast<double>(hard_sync.q.q1),
            static_cast<double>(hard_sync.q.q2), static_cast<double>(hard_sync.q.q3)};
        ksi::edge::TimedWgs84Position global_position;
        if (SnapshotGlobalPosition(&global_position)) {
            sample.wgs84_position = global_position;
        }
        ksi::edge::TimedPositionAccuracy accuracy;
        if (SnapshotPositionAccuracy(&accuracy)) {
            sample.position_accuracy = accuracy;
        }
        ksi::edge::TimedGimbalNedEuler gimbal;
        if (SnapshotGimbal(&gimbal)) {
            sample.gimbal_ned_euler = gimbal;
        }
        const ksi::edge::TelemetryVerdict result = telemetry_.RecordFromCallback(sample);
        if (result != ksi::edge::TelemetryVerdict::kRecorded) {
            ++telemetry_drops_;
        }
    }

    // The following six topics are precondition-sensing only (ADR-KSI-021 §5
    // [8]): none of them feed the perception/telemetry alignment path above,
    // and none of them arm or call any DJI flight-control symbol.  Each is a
    // single scalar (or small POD), so a plain atomic triple (value + valid +
    // observed_at) is enough — unlike Position/Velocity/GlobalPosition above,
    // there is no multi-field point that needs seqlock-style read consistency.
    // Timestamps are UTC epoch ms (RealtimeNowUtcMs), not the monotonic clock
    // the frame-alignment fields use above: these values are read later by a
    // TTL-style freshness bound, not paired against a frame's sensor time.
    void OnFlightStatus(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionFlightStatus)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionFlightStatus status = 0U;
        std::memcpy(&status, bytes, sizeof(status));
        flight_status_.store(status, std::memory_order_relaxed);
        flight_status_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        flight_status_valid_.store(true, std::memory_order_release);
    }

    void OnBatteryInfo(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionWholeBatteryInfo)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionWholeBatteryInfo info {};
        std::memcpy(&info, bytes, sizeof(info));
        battery_capacity_mah_.store(info.capacity, std::memory_order_relaxed);
        battery_voltage_mv_.store(info.voltage, std::memory_order_relaxed);
        battery_current_ma_.store(info.current, std::memory_order_relaxed);
        battery_percent_1pct_.store(info.percentage, std::memory_order_relaxed);
        battery_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        battery_valid_.store(true, std::memory_order_release);
    }

    void OnHomePointSetStatus(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionHomePointSetStatus)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionHomePointSetStatus status = 0U;
        std::memcpy(&status, bytes, sizeof(status));
        home_point_set_status_.store(status, std::memory_order_relaxed);
        home_point_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        home_point_valid_.store(true, std::memory_order_release);
    }

    void OnRtkPositionInfo(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionRtkPositionInfo)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionRtkPositionInfo property = 0U;
        std::memcpy(&property, bytes, sizeof(property));
        position_solution_property_.store(property, std::memory_order_relaxed);
        position_solution_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        position_solution_valid_.store(true, std::memory_order_release);
    }

    void OnFlightAnomaly(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionFlightAnomaly)) {
            ++telemetry_drops_;
            return;
        }
        // T_DjiFcSubscriptionFlightAnomaly is a 32-bit bitfield struct, not an
        // integer type — copy it into a plain uint32_t so flight_execution.hpp
        // (which does not know this PSDK layout) receives an opaque raw value
        // rather than a struct it would have to reinterpret blindly.
        static_assert(sizeof(T_DjiFcSubscriptionFlightAnomaly) == sizeof(std::uint32_t),
                     "flight anomaly bitfield is expected to be exactly 32 bits");
        std::uint32_t bits = 0U;
        std::memcpy(&bits, bytes, sizeof(bits));
        flight_anomaly_bits_.store(bits, std::memory_order_relaxed);
        flight_anomaly_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        flight_anomaly_valid_.store(true, std::memory_order_release);
    }

    void OnDisplayMode(const uint8_t* bytes, std::uint16_t size) noexcept {
        if (bytes == nullptr || size != sizeof(T_DjiFcSubscriptionDisplaymode)) {
            ++telemetry_drops_;
            return;
        }
        T_DjiFcSubscriptionDisplaymode mode = 0U;
        std::memcpy(&mode, bytes, sizeof(mode));
        display_mode_.store(mode, std::memory_order_relaxed);
        display_mode_observed_utc_ms_.store(RealtimeNowUtcMs(), std::memory_order_relaxed);
        display_mode_valid_.store(true, std::memory_order_release);
    }

    void PrintStatistics() const {
        const ksi::edge::FrameQueueStats frame_stats = frames_.stats();
        std::fprintf(stderr,
                     "[ksi-edge-shadow] ingress stats: accepted=%llu queueBusy=%llu "
                     "queueFull=%llu malformed=%llu workerDrained=%llu telemetrySamples=%zu "
                     "telemetryDrops=%llu nonRgb=%llu\n",
                     static_cast<unsigned long long>(frame_stats.accepted),
                     static_cast<unsigned long long>(frame_stats.queue_busy),
                     static_cast<unsigned long long>(frame_stats.queue_full),
                     static_cast<unsigned long long>(frame_stats.malformed),
                     static_cast<unsigned long long>(worker_drained_.load()), telemetry_.size(),
                     static_cast<unsigned long long>(telemetry_drops_.load()),
                     static_cast<unsigned long long>(non_rgb_frames_.load()));
        std::fprintf(stderr, "[ksi-edge-shadow] native activation=%s shadowActive=%s\n",
                     native_activation_verdict_.c_str(),
                     active_native_snapshot_.has_value() ? "yes" : "no");
        std::fprintf(stderr, "[ksi-edge-shadow] missionKmz=%s bytes=%zu\n",
                     mission_kmz_verdict_.c_str(),
                     active_mission_kmz_.has_value() ? active_mission_kmz_->bytes.size() : 0U);
        const auto last_pipeline = static_cast<ksi::edge::PipelineVerdict>(
            last_pipeline_verdict_.load(std::memory_order_acquire));
        std::fprintf(stderr,
                     "[ksi-edge-shadow] perceptionSetup=%s perceptionPipeline=%s steps=%llu "
                     "durableCandidates=%llu lastPipeline=%s shadowAccepted=%llu "
                     "shadowRejected=%llu shadowSuppressed=%llu lastShadow=%s "
                     "lastShadowHeartbeat=%s\n",
                     perception_setup_verdict_.c_str(), perception_pipeline_verdict_.c_str(),
                     static_cast<unsigned long long>(perception_steps_.load()),
                     static_cast<unsigned long long>(durable_candidates_.load()),
                     ksi::edge::ToString(last_pipeline),
                     static_cast<unsigned long long>(shadow_actions_accepted_.load()),
                     static_cast<unsigned long long>(shadow_actions_rejected_.load()),
                     static_cast<unsigned long long>(shadow_actions_suppressed_.load()),
                     ksi::edge::ToString(static_cast<ksi::edge::ShadowVerdict>(
                         last_shadow_verdict_.load(std::memory_order_acquire))),
                     ksi::control_plane::ToString(
                         static_cast<ksi::control_plane::HeartbeatVerdict>(
                             last_shadow_heartbeat_verdict_.load(std::memory_order_acquire))));
        const auto last_timing_artifact = static_cast<ksi::edge::EventTimingArtifactVerdict>(
            last_event_timing_artifact_verdict_.load(std::memory_order_acquire));
        std::fprintf(stderr,
                     "[ksi-edge-shadow] candidateTimingArtifacts durable=%llu failures=%llu "
                     "duplicateRetries=%llu last=%s\n",
                     static_cast<unsigned long long>(event_timing_artifacts_durable_.load()),
                     static_cast<unsigned long long>(event_timing_artifact_failures_.load()),
                     static_cast<unsigned long long>(event_timing_duplicate_retries_.load()),
                     ksi::edge::ToString(last_timing_artifact));
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        const auto last_sync = static_cast<ksi::edge::CoreSyncVerdict>(
            last_core_sync_verdict_.load(std::memory_order_acquire));
        std::fprintf(stderr, "[ksi-edge-shadow] coreSync=%s lastCoreSync=%s\n",
                     core_sync_setup_verdict_.c_str(), ksi::edge::ToString(last_sync));
        const auto last_media_offload = static_cast<ksi::edge::MediaOffloadVerdict>(
            last_media_offload_verdict_.load(std::memory_order_acquire));
        std::fprintf(stderr, "[ksi-edge-shadow] mediaOffload=%s lastMediaOffload=%s\n",
                     media_offload_setup_verdict_.c_str(), ksi::edge::ToString(last_media_offload));
#endif
    }

private:
    // Each auxiliary pose cache has a short single-writer critical section.
    // PSDK normally serializes callbacks for a topic, but that is not a
    // contract we depend on: if a second callback races, it drops its sample
    // rather than letting a reader combine fields from two pose updates.  The
    // worker uses the generation number as a bounded seqlock reader.
    bool SnapshotPosition(ksi::edge::Vec3* output) const noexcept {
        if (output == nullptr) {
            return false;
        }
        for (std::size_t attempt = 0; attempt < 3U; ++attempt) {
            const std::uint64_t before = position_generation_.load(std::memory_order_acquire);
            if ((before & 1U) != 0U) {
                continue;
            }
            const bool valid = position_valid_.load(std::memory_order_relaxed);
            const ksi::edge::Vec3 value = {
                position_x_.load(std::memory_order_relaxed),
                position_y_.load(std::memory_order_relaxed),
                position_z_.load(std::memory_order_relaxed)};
            const std::uint64_t after = position_generation_.load(std::memory_order_acquire);
            if (before == after && (after & 1U) == 0U && valid && std::isfinite(value.x) &&
                std::isfinite(value.y) && std::isfinite(value.z)) {
                *output = value;
                return true;
            }
        }
        return false;
    }

    bool SnapshotVelocity(ksi::edge::TimedVelocityMps* output) const noexcept {
        if (output == nullptr) {
            return false;
        }
        for (std::size_t attempt = 0; attempt < 3U; ++attempt) {
            const std::uint64_t before = velocity_generation_.load(std::memory_order_acquire);
            if ((before & 1U) != 0U) {
                continue;
            }
            const bool valid = velocity_valid_.load(std::memory_order_relaxed);
            const ksi::edge::Vec3 value = {
                velocity_x_.load(std::memory_order_relaxed),
                velocity_y_.load(std::memory_order_relaxed),
                velocity_z_.load(std::memory_order_relaxed)};
            const std::int64_t received = velocity_received_ns_.load(std::memory_order_relaxed);
            const std::uint64_t after = velocity_generation_.load(std::memory_order_acquire);
            if (before == after && (after & 1U) == 0U && valid && received > 0 &&
                std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z)) {
                *output = ksi::edge::TimedVelocityMps{value, received};
                return true;
            }
        }
        return false;
    }

    bool SnapshotGlobalPosition(ksi::edge::TimedWgs84Position* output) const noexcept {
        if (output == nullptr) {
            return false;
        }
        for (std::size_t attempt = 0; attempt < 3U; ++attempt) {
            const std::uint64_t before =
                global_position_generation_.load(std::memory_order_acquire);
            if ((before & 1U) != 0U) {
                continue;
            }
            const bool valid = global_position_valid_.load(std::memory_order_relaxed);
            const double latitude = global_latitude_rad_.load(std::memory_order_relaxed);
            const double longitude = global_longitude_rad_.load(std::memory_order_relaxed);
            const double altitude = global_altitude_m_.load(std::memory_order_relaxed);
            const std::int64_t received =
                global_position_received_ns_.load(std::memory_order_relaxed);
            const std::uint64_t after =
                global_position_generation_.load(std::memory_order_acquire);
            if (before != after || (after & 1U) != 0U || !valid || received <= 0 ||
                !std::isfinite(latitude) || !std::isfinite(longitude) || !std::isfinite(altitude) ||
                latitude < -1.5707963267948966 || latitude > 1.5707963267948966 ||
                longitude < -3.141592653589793 || longitude > 3.141592653589793) {
                continue;
            }
            *output = ksi::edge::TimedWgs84Position{
                ksi::edge::Wgs84Position{latitude, longitude, altitude}, received};
            return true;
        }
        return false;
    }

    bool SnapshotPositionAccuracy(ksi::edge::TimedPositionAccuracy* output) const noexcept {
        if (output == nullptr) {
            return false;
        }
        for (std::size_t attempt = 0; attempt < 3U; ++attempt) {
            const std::uint64_t before =
                position_accuracy_generation_.load(std::memory_order_acquire);
            if ((before & 1U) != 0U) {
                continue;
            }
            const bool valid = position_accuracy_valid_.load(std::memory_order_relaxed);
            const double horizontal = horizontal_sigma_m_.load(std::memory_order_relaxed);
            const double vertical = vertical_sigma_m_.load(std::memory_order_relaxed);
            const std::int64_t received =
                position_accuracy_received_ns_.load(std::memory_order_relaxed);
            const std::uint64_t after =
                position_accuracy_generation_.load(std::memory_order_acquire);
            if (before != after || (after & 1U) != 0U || !valid || received <= 0 ||
                !std::isfinite(horizontal) || !std::isfinite(vertical) || horizontal < 0.0 ||
                vertical < 0.0) {
                continue;
            }
            *output = ksi::edge::TimedPositionAccuracy{
                ksi::edge::PositionAccuracy{horizontal, vertical}, received};
            return true;
        }
        return false;
    }

    bool SnapshotGimbal(ksi::edge::TimedGimbalNedEuler* output) const noexcept {
        if (output == nullptr) {
            return false;
        }
        for (std::size_t attempt = 0; attempt < 3U; ++attempt) {
            const std::uint64_t before = gimbal_generation_.load(std::memory_order_acquire);
            if ((before & 1U) != 0U) {
                continue;
            }
            const bool valid = gimbal_valid_.load(std::memory_order_relaxed);
            const double pitch = gimbal_pitch_rad_.load(std::memory_order_relaxed);
            const double roll = gimbal_roll_rad_.load(std::memory_order_relaxed);
            const double yaw = gimbal_yaw_rad_.load(std::memory_order_relaxed);
            const std::int64_t received = gimbal_received_ns_.load(std::memory_order_relaxed);
            const std::uint64_t after = gimbal_generation_.load(std::memory_order_acquire);
            if (before != after || (after & 1U) != 0U || !valid || received <= 0 ||
                !std::isfinite(pitch) || !std::isfinite(roll) || !std::isfinite(yaw)) {
                continue;
            }
            *output = ksi::edge::TimedGimbalNedEuler{
                ksi::edge::GimbalNedEuler{pitch, roll, yaw}, received};
            return true;
        }
        return false;
    }

    void ClearPerceptionPipeline() noexcept {
        // Destroy non-owning orchestration first, then its worker-only
        // components.  The SQLite/evidence journal intentionally remains open
        // across an expired/replaced activation so an ACKed candidate is never
        // discarded merely because a later profile becomes invalid.
        perception_pipeline_.reset();
        perception_evidence_builder_.reset();
        perception_projector_.reset();
        perception_risk_engine_.reset();
        perception_tracker_.reset();
        perception_inference_.reset();
        active_runtime_profile_.reset();
    }

    void ResetPerceptionProvisioning() noexcept {
        ClearPerceptionPipeline();
        perception_engine_vault_.reset();
        perception_shadow_journal_.reset();
        perception_timing_writer_.reset();
        perception_store_.reset();
        perception_vault_.reset();
        perception_provisioned_ = false;
    }

    void RecordCandidateTimingArtifacts(const ksi::edge::PipelineReport& report) noexcept {
        if (report.durable_candidates.empty()) {
            return;
        }
        if (perception_timing_writer_ == nullptr) {
            event_timing_artifact_failures_.fetch_add(report.durable_candidates.size(),
                                                      std::memory_order_relaxed);
            last_event_timing_artifact_verdict_.store(
                static_cast<int>(ksi::edge::EventTimingArtifactVerdict::kStorageError),
                std::memory_order_release);
            return;
        }
        for (const ksi::edge::PipelineReport::DurableCandidate& candidate :
             report.durable_candidates) {
            try {
                const ksi::edge::EventTimingArtifactResult result =
                    perception_timing_writer_->PersistCandidateTiming(candidate.candidate_timing);
                last_event_timing_artifact_verdict_.store(static_cast<int>(result.verdict),
                                                          std::memory_order_release);
                if (result.verdict == ksi::edge::EventTimingArtifactVerdict::kPersisted ||
                    result.verdict == ksi::edge::EventTimingArtifactVerdict::kDuplicate) {
                    event_timing_artifacts_durable_.fetch_add(1U, std::memory_order_relaxed);
                } else if (result.verdict == ksi::edge::EventTimingArtifactVerdict::kSkippedDuplicate) {
                    event_timing_duplicate_retries_.fetch_add(1U, std::memory_order_relaxed);
                } else {
                    event_timing_artifact_failures_.fetch_add(1U, std::memory_order_relaxed);
                }
            } catch (...) {
                // Timing evidence must never fabricate success or take down
                // the worker after the candidate itself is already durable.
                event_timing_artifact_failures_.fetch_add(1U, std::memory_order_relaxed);
                last_event_timing_artifact_verdict_.store(
                    static_cast<int>(ksi::edge::EventTimingArtifactVerdict::kStorageError),
                    std::memory_order_release);
            }
        }
    }

    void RecordShadowCandidates(const ksi::edge::PipelineReport& report) noexcept {
        if (report.durable_candidates.empty()) {
            return;
        }
        if (!active_native_snapshot_.has_value() || perception_shadow_journal_ == nullptr) {
            shadow_actions_suppressed_.fetch_add(report.durable_candidates.size(),
                                                 std::memory_order_relaxed);
            last_shadow_verdict_.store(static_cast<int>(ksi::edge::ShadowVerdict::kJournalUnavailable),
                                       std::memory_order_release);
            return;
        }
        const std::int64_t now_utc_ms = RealtimeNowUtcMs();
        if (now_utc_ms <= 0) {
            shadow_actions_suppressed_.fetch_add(report.durable_candidates.size(),
                                                 std::memory_order_relaxed);
            last_shadow_verdict_.store(static_cast<int>(ksi::edge::ShadowVerdict::kClockRollback),
                                       std::memory_order_release);
            return;
        }

        // A durable Candidate proves the calibrated perception/evidence path
        // completed for this frame.  It is the heartbeat source for the
        // immediately following shadow-only decision, never a callback-time
        // synthetic heartbeat and never a network liveness signal.
        const ksi::control_plane::HeartbeatVerdict heartbeat =
            shadow_supervisor_.RecordHeartbeat(now_utc_ms, now_utc_ms);
        last_shadow_heartbeat_verdict_.store(static_cast<int>(heartbeat), std::memory_order_release);
        const std::string& active_digest =
            active_native_snapshot_->context.mission_contract_digest;
        for (const ksi::edge::PipelineReport::DurableCandidate& candidate :
             report.durable_candidates) {
            const std::string seed = active_digest + "\n" + candidate.idempotency_key;
            const std::string identity = ksi::edge::Sha256Hex(
                reinterpret_cast<const std::uint8_t*>(seed.data()), seed.size());
            if (identity.empty()) {
                shadow_actions_suppressed_.fetch_add(1U, std::memory_order_relaxed);
                last_shadow_verdict_.store(
                    static_cast<int>(ksi::edge::ShadowVerdict::kControlPlaneRejected),
                    std::memory_order_release);
                continue;
            }
            // This slice intentionally emits only a high-level HOLD proposal
            // after a durable equipment-risk candidate.  It contains no
            // coordinate, velocity, or DJI call; ShadowFlightSupervisor only
            // records the judgment and never sends it to a controller.
            ksi::control_plane::ActionIntent intent;
            intent.schema_version = "1.0";
            intent.command_id = "shadow-hold-" + identity;
            intent.kind = ksi::control_plane::ActionIntentKind::kHold;
            intent.authorization_digest = active_digest;
            intent.issued_at_utc_ms = now_utc_ms;
            intent.ttl_ms = kShadowIntentTtlMs;
            const ksi::edge::ShadowDecision decision = shadow_supervisor_.Evaluate(
                intent, candidate.risk_policy_pack_digest, now_utc_ms,
                perception_shadow_journal_.get());
            last_shadow_verdict_.store(static_cast<int>(decision.verdict), std::memory_order_release);
            if (decision.verdict == ksi::edge::ShadowVerdict::kShadowAccepted) {
                shadow_actions_accepted_.fetch_add(1U, std::memory_order_relaxed);
            } else {
                shadow_actions_rejected_.fetch_add(1U, std::memory_order_relaxed);
            }
        }
    }

    bool ProfileBindsActivePolicy(const ksi::edge::NativeActivationSnapshot& activation,
                                  const ksi::edge::NativeRuntimeProfile& profile) const noexcept {
        if (activation.risk_policy_pack.digest != profile.risk_policy_pack_digest ||
            activation.risk_policy_pack.risk_policy_pack_id.empty() ||
            profile.calibration.calibration_profile_id.empty()) {
            return false;
        }
        for (const auto& item : profile.model.class_bindings) {
            const ksi::edge::NativeRegisteredEquipmentBinding& binding = item.second;
            const auto policy = activation.risk_policy_pack.by_equipment_class.find(
                binding.equipment_class);
            if (policy == activation.risk_policy_pack.by_equipment_class.end() ||
                policy->second.calibration_profile_id != profile.calibration.calibration_profile_id) {
                return false;
            }
        }
        return true;
    }

    bool ProfileHasAcceptedTensorRtDifferential(
        const ksi::edge::NativeRuntimeProfile& profile) const noexcept {
        // The native parser already rejects a missing or altered attestation.
        // Keep this check at the actuator boundary as well: future callers
        // must not be able to assemble a NativeRuntimeProfile in memory and
        // start TensorRT merely from matching tensor dimensions.
        return ksi::edge::HasAcceptedTensorRtDifferential(profile.model);
    }

    void ConfigurePerceptionPipeline(const ksi::edge::NativeActivationSnapshot& activation,
                                     const ksi::edge::NativeRuntimeProfile& profile) noexcept {
        ClearPerceptionPipeline();
        perception_engine_vault_.reset();
        if (!perception_provisioned_ || perception_vault_ == nullptr ||
            perception_shadow_journal_ == nullptr || perception_timing_writer_ == nullptr ||
            perception_store_ == nullptr ||
            !perception_store_->is_open()) {
            perception_pipeline_verdict_ = "STORE_FORWARD_UNAVAILABLE";
            return;
        }
        if (!ksi::edge::TensorRtBackendCompiled()) {
            perception_pipeline_verdict_ = "TENSORRT_BACKEND_UNAVAILABLE";
            return;
        }
        if (!ProfileHasAcceptedTensorRtDifferential(profile)) {
            perception_pipeline_verdict_ = "TENSORRT_DIFFERENTIAL_REQUIRED";
            return;
        }
        if (!ProfileBindsActivePolicy(activation, profile) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(profile.model.onnx_artifact_id) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(profile.model.engine_artifact_id) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(profile.site_id) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(activation.edge_device_id) ||
            !ksi::edge::ArtifactVault::IsSafeArtifactId(activation.mission_id) ||
            profile.max_alignment_ms <= 0 ||
            profile.max_alignment_ms >
                std::numeric_limits<std::int64_t>::max() / kNanosecondsPerMillisecond) {
            perception_pipeline_verdict_ = "PROFILE_POLICY_BINDING_REJECTED";
            return;
        }
        try {
            const std::filesystem::path state_path(perception_state_directory_);
            auto engine_vault = std::make_unique<ksi::edge::ArtifactVault>(
                (state_path / "tensorrt-engines").string(), profile.model.max_engine_bytes);
            const std::filesystem::path onnx_path =
                std::filesystem::path(perception_model_artifact_directory_) /
                profile.model.onnx_artifact_id;
            const ksi::edge::TensorRtEngineBuildResult built = ksi::edge::BuildTensorRtDfineEngine(
                ksi::edge::TensorRtEngineBuildRequest{
                    onnx_path.string(), profile.model.registered_onnx_digest,
                    profile.model.engine_artifact_id, engine_vault.get(), profile.model.tensor_contract,
                    profile.model.max_onnx_bytes, profile.model.workspace_bytes});
            if (built.verdict != ksi::edge::TensorRtBuildVerdict::kBuilt) {
                perception_pipeline_verdict_ =
                    std::string("TENSORRT_BUILD_") + ksi::edge::ToString(built.verdict);
                return;
            }
            ksi::edge::TensorRtDfineInference::LoadResult loaded =
                ksi::edge::TensorRtDfineInference::Load(ksi::edge::TensorRtDfineLoadRequest{
                    built.binding, profile.model.tensor_contract, profile.model.max_engine_bytes});
            if (loaded.verdict != ksi::edge::TensorRtLoadVerdict::kLoaded ||
                loaded.inference == nullptr) {
                perception_pipeline_verdict_ =
                    std::string("TENSORRT_LOAD_") + ksi::edge::ToString(loaded.verdict);
                return;
            }
            std::map<std::uint32_t, std::string> taxonomy;
            for (const auto& item : profile.model.class_bindings) {
                if (!taxonomy.emplace(item.first, item.second.source_class_name).second) {
                    perception_pipeline_verdict_ = "PROFILE_CLASS_MAPPING_REJECTED";
                    return;
                }
            }
            constexpr float kAssociationIouThreshold = 0.5F;
            constexpr std::size_t kMaximumTracks = 256U;
            auto tracker = std::make_unique<ksi::edge::WorldStateTracker>(
                kAssociationIouThreshold, kMaximumTracks);
            auto risk_engine = std::make_unique<ksi::edge::ConservativeRiskEngine>(
                activation.risk_policy_pack);
            auto projector = std::make_unique<ksi::edge::ProfiledGroundPlaneProjector>(profile);
            auto evidence_builder = std::make_unique<ksi::edge::NativeCandidateEvidenceBuilder>(
                ksi::edge::NativeEvidenceConfig{activation.edge_device_id, activation.mission_id,
                                                profile.site_id, activation.runtime_version},
                perception_vault_.get(), perception_store_.get());
            auto pipeline = std::make_unique<ksi::edge::EdgePipeline>(
                &frames_, &telemetry_,
                ksi::edge::DfinePostprocessor(std::move(taxonomy), profile.model.score_threshold,
                                               profile.model.top_k),
                tracker.get(), risk_engine.get(), perception_store_.get(),
                profile.max_alignment_ms * kNanosecondsPerMillisecond,
                true /* signed profile requires sensor alignment */, &MonotonicNowNs);
            perception_engine_vault_ = std::move(engine_vault);
            perception_inference_ = std::move(loaded.inference);
            perception_tracker_ = std::move(tracker);
            perception_risk_engine_ = std::move(risk_engine);
            perception_projector_ = std::move(projector);
            perception_evidence_builder_ = std::move(evidence_builder);
            perception_pipeline_ = std::move(pipeline);
            active_runtime_profile_ = profile;
            perception_pipeline_verdict_ = "READY";
        } catch (...) {
            ClearPerceptionPipeline();
            perception_engine_vault_.reset();
            perception_pipeline_verdict_ = "PERCEPTION_PIPELINE_REJECTED";
        }
    }

    void ClearNativeActivation(const char* verdict) {
        shadow_supervisor_.Deactivate();
        active_native_snapshot_.reset();
        ClearPerceptionPipeline();
        native_activation_verdict_ = verdict;
        if (perception_provisioned_) {
            perception_pipeline_verdict_ = verdict;
        }
        if (mission_kmz_configured_) {
            active_mission_kmz_.reset();
            mission_kmz_verdict_ = verdict;
        }
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        if (media_offload_worker_ != nullptr) {
            std::lock_guard<std::mutex> lock(media_offload_mission_mutex_);
            media_offload_mission_id_.clear();
        }
#endif
    }

    // Called only from RefreshNativeActivation, right after a valid snapshot
    // is (re)published, and from ConfigureMissionKmz for the first load.  The
    // KMZ sidecar is written by the same verified Python bridge that writes
    // ``active-dispatch.native.v1``, so it is read from the same directory
    // with the same device/mission/contract binding — never a path or
    // identity this method invents on its own.
    void RefreshMissionKmz() {
        if (!mission_kmz_configured_) {
            return;
        }
        if (!active_native_snapshot_.has_value()) {
            active_mission_kmz_.reset();
            mission_kmz_verdict_ = "NO_ACTIVATION";
            return;
        }
        const ksi::edge::NativeMissionKmzLoadResult loaded = ksi::edge::LoadNativeMissionKmz(
            activation_state_directory_, activation_edge_device_id_,
            active_native_snapshot_->mission_id,
            active_native_snapshot_->context.mission_contract_digest);
        mission_kmz_verdict_ = ksi::edge::ToString(loaded.verdict);
        if (loaded.verdict == ksi::edge::NativeMissionKmzVerdict::kLoaded) {
            active_mission_kmz_ = loaded.kmz;
        } else {
            active_mission_kmz_.reset();
        }
    }

    void RefreshNativeActivation() {
        if (activation_state_directory_.empty() || activation_edge_device_id_.empty() ||
            activation_runtime_version_.empty()) {
            ClearNativeActivation("UNCONFIGURED");
            return;
        }
        const std::int64_t now_utc_ms = RealtimeNowUtcMs();
        if (now_utc_ms <= 0) {
            ClearNativeActivation("CLOCK_UNAVAILABLE");
            return;
        }
        const ksi::edge::NativeActivationLoadResult loaded =
            ksi::edge::LoadNativeActivationSnapshot(activation_state_directory_,
                                                     activation_edge_device_id_,
                                                     activation_runtime_version_, now_utc_ms);
        if (loaded.verdict != ksi::edge::NativeActivationVerdict::kLoaded) {
            ClearNativeActivation(ksi::edge::ToString(loaded.verdict));
            return;
        }
        const bool changed =
            !active_native_snapshot_.has_value() ||
            active_native_snapshot_->dispatch_id != loaded.snapshot.dispatch_id ||
            active_native_snapshot_->context.mission_contract_digest !=
                loaded.snapshot.context.mission_contract_digest ||
            active_native_snapshot_->context.risk_policy_pack_digest !=
                loaded.snapshot.context.risk_policy_pack_digest ||
            active_native_snapshot_->context.valid_until_utc_ms !=
                loaded.snapshot.context.valid_until_utc_ms;
        if (changed && !shadow_supervisor_.Activate(loaded.snapshot.context, now_utc_ms)) {
            ClearNativeActivation("SUPERVISOR_REJECTED_ACTIVATION");
            return;
        }
        active_native_snapshot_ = loaded.snapshot;
        native_activation_verdict_ = "LOADED";
        RefreshMissionKmz();
#if KSI_EDGE_HAVE_CURL_TRANSPORT
        if (media_offload_worker_ != nullptr) {
            std::lock_guard<std::mutex> lock(media_offload_mission_mutex_);
            media_offload_mission_id_ = loaded.snapshot.mission_id;
        }
#endif
        if (!perception_provisioned_) {
            return;
        }
        const ksi::edge::NativeRuntimeProfileLoadResult profile =
            ksi::edge::LoadNativeRuntimeProfile(
                activation_state_directory_, loaded.snapshot.edge_device_id, loaded.snapshot.dispatch_id,
                loaded.snapshot.mission_id, loaded.snapshot.context.mission_contract_digest,
                loaded.snapshot.context.risk_policy_pack_digest);
        if (profile.verdict != ksi::edge::NativeRuntimeProfileVerdict::kLoaded) {
            ClearPerceptionPipeline();
            perception_pipeline_verdict_ =
                std::string("RUNTIME_PROFILE_") + ksi::edge::ToString(profile.verdict);
            return;
        }
        const bool profile_changed =
            !active_runtime_profile_.has_value() ||
            active_runtime_profile_->edge_runtime_profile_digest !=
                profile.profile.edge_runtime_profile_digest ||
            active_runtime_profile_->dispatch_id != profile.profile.dispatch_id ||
            active_runtime_profile_->mission_contract_digest !=
                profile.profile.mission_contract_digest ||
            active_runtime_profile_->risk_policy_pack_digest !=
                profile.profile.risk_policy_pack_digest;
        if (profile_changed || perception_pipeline_ == nullptr || perception_inference_ == nullptr ||
            perception_projector_ == nullptr || perception_evidence_builder_ == nullptr) {
            ConfigurePerceptionPipeline(loaded.snapshot, profile.profile);
        }
    }

    void DrainWorker() noexcept {
        // This is a worker-thread operation; PSDK callbacks only copy into
        // bounded rings.  A missing/incomplete signed runtime profile remains
        // capture-only; no model, calibration, or timing default is invented.
        try {
            ksi::edge::FramePacket frame;
            std::int64_t next_activation_refresh_ns = 0;
            while (worker_running_.load(std::memory_order_acquire)) {
                const std::int64_t monotonic_now_ns = MonotonicNowNs();
                if (monotonic_now_ns > 0 && monotonic_now_ns >= next_activation_refresh_ns) {
                    RefreshNativeActivation();
                    next_activation_refresh_ns =
                        monotonic_now_ns > std::numeric_limits<std::int64_t>::max() -
                                               kActivationRefreshPeriodNs
                            ? std::numeric_limits<std::int64_t>::max()
                            : monotonic_now_ns + kActivationRefreshPeriodNs;
                }
                if (perception_pipeline_ != nullptr && perception_inference_ != nullptr &&
                    perception_projector_ != nullptr && perception_evidence_builder_ != nullptr) {
                    const ksi::edge::PipelineReport report = perception_pipeline_->ProcessOne(
                        perception_inference_.get(), perception_projector_.get(),
                        perception_evidence_builder_.get());
                    last_pipeline_verdict_.store(static_cast<int>(report.verdict),
                                                 std::memory_order_release);
                    ++perception_steps_;
                    if (report.durable_candidate_count > 0U) {
                        durable_candidates_.fetch_add(report.durable_candidate_count,
                                                       std::memory_order_relaxed);
                    }
                    RecordCandidateTimingArtifacts(report);
                    RecordShadowCandidates(report);
                    if (report.verdict != ksi::edge::PipelineVerdict::kNoFrame) {
                        ++worker_drained_;
                        continue;
                    }
                } else if (frames_.TryPop(&frame)) {
                    ++worker_drained_;
                    continue;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
        } catch (const std::exception& exception) {
            std::fprintf(stderr, "[ksi-edge-shadow] activation worker failed closed: %s\n",
                         exception.what());
            worker_running_.store(false, std::memory_order_release);
        } catch (...) {
            std::fputs("[ksi-edge-shadow] activation worker failed closed: unknown exception\n", stderr);
            worker_running_.store(false, std::memory_order_release);
        }
    }

#if KSI_EDGE_HAVE_CURL_TRANSPORT
    void DrainCoreSync() noexcept {
        try {
            while (core_sync_worker_running_.load(std::memory_order_acquire)) {
                if (core_sync_driver_ == nullptr || core_sync_transport_ == nullptr) {
                    last_core_sync_verdict_.store(
                        static_cast<int>(ksi::edge::CoreSyncVerdict::kRetryableFailure),
                        std::memory_order_release);
                    return;
                }
                const ksi::edge::StoreForwardSyncReport report =
                    core_sync_driver_->SynchronizeOnce(core_sync_transport_.get());
                last_core_sync_verdict_.store(static_cast<int>(report.verdict), std::memory_order_release);
                for (std::int64_t elapsed_ms = 0;
                     elapsed_ms < kCoreSyncPeriodMs &&
                     core_sync_worker_running_.load(std::memory_order_acquire);
                     elapsed_ms += 100LL) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
            }
        } catch (...) {
            last_core_sync_verdict_.store(
                static_cast<int>(ksi::edge::CoreSyncVerdict::kPermanentFailure),
                std::memory_order_release);
        }
    }

    // Exactly one of these is non-null whenever core_sync_configured_ is true:
    // perception owns it when perception is provisioned (CMake forces
    // PERCEPTION_STATE_DIR == SYNC_STATE_DIR in that case, and ConfigureCoreSync
    // then borrows perception's pointers instead of opening a second SQLite
    // connection — see share_perception_journal above); otherwise core_sync
    // owns its own.  Either way this is the one durable vault/store this DPK
    // already trusts, never a new one media offload invents.
    ksi::edge::ArtifactVault* OperationalVault() const noexcept {
        if (perception_vault_ != nullptr) {
            return perception_vault_.get();
        }
        return core_sync_vault_.get();
    }

    ksi::edge::SqliteStoreForward* OperationalStore() const noexcept {
        if (perception_store_ != nullptr) {
            return perception_store_.get();
        }
        return core_sync_store_.get();
    }

    void DrainMediaOffload() noexcept {
        try {
            while (media_offload_worker_running_.load(std::memory_order_acquire)) {
                std::string mission_id;
                {
                    std::lock_guard<std::mutex> lock(media_offload_mission_mutex_);
                    mission_id = media_offload_mission_id_;
                }
                // No active mission is a routine, recoverable state (before
                // the first dispatch, or between missions) — not a setup
                // failure — so this cycle is skipped rather than the thread
                // exiting or a verdict being fabricated.
                if (media_offload_worker_ != nullptr && !mission_id.empty() &&
                    !activation_edge_device_id_.empty()) {
                    const ksi::edge::MediaOffloadReport report =
                        media_offload_worker_->RunOnce(mission_id, activation_edge_device_id_);
                    last_media_offload_verdict_.store(static_cast<int>(report.verdict),
                                                       std::memory_order_release);
                }
                for (std::int64_t elapsed_ms = 0;
                     elapsed_ms < kMediaOffloadPeriodMs &&
                     media_offload_worker_running_.load(std::memory_order_acquire);
                     elapsed_ms += 100LL) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
            }
        } catch (...) {
            last_media_offload_verdict_.store(
                static_cast<int>(ksi::edge::MediaOffloadVerdict::kSourceFailure),
                std::memory_order_release);
        }
    }
#endif

    ksi::edge::BoundedFrameQueue frames_;
    ksi::edge::TelemetryTimeline telemetry_;
    ksi::edge::ShadowFlightSupervisor shadow_supervisor_;
    std::optional<ksi::edge::NativeActivationSnapshot> active_native_snapshot_;
    std::optional<ksi::edge::NativeRuntimeProfile> active_runtime_profile_;
    std::string activation_state_directory_;
    std::string activation_edge_device_id_;
    std::string activation_runtime_version_;
    std::string native_activation_verdict_ = "UNCONFIGURED";
    bool mission_kmz_configured_ = false;
    std::optional<ksi::edge::NativeMissionKmz> active_mission_kmz_;
    std::string mission_kmz_verdict_ = "UNCONFIGURED";
    std::string perception_state_directory_;
    std::string perception_model_artifact_directory_;
    std::string perception_setup_verdict_ = "UNCONFIGURED";
    std::string perception_pipeline_verdict_ = "UNCONFIGURED";
    bool perception_provisioned_ = false;
    // Declare in reverse dependency order so default destruction remains safe
    // even if startup exits before StopWorker reached a normal steady state.
    std::unique_ptr<ksi::edge::ArtifactVault> perception_vault_;
    std::unique_ptr<ksi::edge::SqliteStoreForward> perception_store_;
    std::unique_ptr<ksi::edge::ArtifactVaultShadowActionJournal> perception_shadow_journal_;
    std::unique_ptr<ksi::edge::EventTimingArtifactWriter> perception_timing_writer_;
    std::unique_ptr<ksi::edge::ArtifactVault> perception_engine_vault_;
    std::unique_ptr<ksi::edge::TensorRtDfineInference> perception_inference_;
    std::unique_ptr<ksi::edge::WorldStateTracker> perception_tracker_;
    std::unique_ptr<ksi::edge::ConservativeRiskEngine> perception_risk_engine_;
    std::unique_ptr<ksi::edge::ProfiledGroundPlaneProjector> perception_projector_;
    std::unique_ptr<ksi::edge::NativeCandidateEvidenceBuilder> perception_evidence_builder_;
    std::unique_ptr<ksi::edge::EdgePipeline> perception_pipeline_;
    std::atomic<float> position_x_{0.0F};
    std::atomic<float> position_y_{0.0F};
    std::atomic<float> position_z_{0.0F};
    std::atomic<float> velocity_x_{0.0F};
    std::atomic<float> velocity_y_{0.0F};
    std::atomic<float> velocity_z_{0.0F};
    std::atomic<bool> position_valid_{false};
    std::atomic<bool> velocity_valid_{false};
    std::atomic_flag position_writer_ = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> position_generation_{0U};
    std::atomic_flag velocity_writer_ = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> velocity_generation_{0U};
    std::atomic<std::int64_t> velocity_received_ns_{0};
    std::atomic_flag global_position_writer_ = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> global_position_generation_{0U};
    std::atomic<double> global_latitude_rad_{0.0};
    std::atomic<double> global_longitude_rad_{0.0};
    std::atomic<double> global_altitude_m_{0.0};
    std::atomic<std::int64_t> global_position_received_ns_{0};
    std::atomic<bool> global_position_valid_{false};
    std::atomic_flag position_accuracy_writer_ = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> position_accuracy_generation_{0U};
    std::atomic<double> horizontal_sigma_m_{0.0};
    std::atomic<double> vertical_sigma_m_{0.0};
    std::atomic<std::int64_t> position_accuracy_received_ns_{0};
    std::atomic<bool> position_accuracy_valid_{false};
    std::atomic_flag gimbal_writer_ = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> gimbal_generation_{0U};
    std::atomic<double> gimbal_pitch_rad_{0.0};
    std::atomic<double> gimbal_roll_rad_{0.0};
    std::atomic<double> gimbal_yaw_rad_{0.0};
    std::atomic<std::int64_t> gimbal_received_ns_{0};
    std::atomic<bool> gimbal_valid_{false};
    // ADR-KSI-021 §5 [8] precondition-sensing caches — see the six OnXxx
    // methods above for why these are plain atomics instead of the seqlock
    // pattern used by the multi-field points above.
    std::atomic<std::uint8_t> flight_status_{0U};
    std::atomic<std::int64_t> flight_status_observed_utc_ms_{0};
    std::atomic<bool> flight_status_valid_{false};
    std::atomic<std::uint32_t> battery_capacity_mah_{0U};
    std::atomic<std::int32_t> battery_voltage_mv_{0};
    std::atomic<std::int32_t> battery_current_ma_{0};
    std::atomic<std::uint8_t> battery_percent_1pct_{0U};
    std::atomic<std::int64_t> battery_observed_utc_ms_{0};
    std::atomic<bool> battery_valid_{false};
    std::atomic<std::uint8_t> home_point_set_status_{0U};
    std::atomic<std::int64_t> home_point_observed_utc_ms_{0};
    std::atomic<bool> home_point_valid_{false};
    std::atomic<std::uint8_t> position_solution_property_{0U};
    std::atomic<std::int64_t> position_solution_observed_utc_ms_{0};
    std::atomic<bool> position_solution_valid_{false};
    std::atomic<std::uint32_t> flight_anomaly_bits_{0U};
    std::atomic<std::int64_t> flight_anomaly_observed_utc_ms_{0};
    std::atomic<bool> flight_anomaly_valid_{false};
    std::atomic<std::uint8_t> display_mode_{0U};
    std::atomic<std::int64_t> display_mode_observed_utc_ms_{0};
    std::atomic<bool> display_mode_valid_{false};
    std::atomic<bool> accepting_{false};
    std::atomic<bool> worker_running_{false};
    std::atomic<std::uint64_t> frame_drops_{0U};
    std::atomic<std::uint64_t> telemetry_drops_{0U};
    std::atomic<std::uint64_t> non_rgb_frames_{0U};
    std::atomic<std::uint64_t> worker_drained_{0U};
    std::atomic<std::uint64_t> perception_steps_{0U};
    std::atomic<std::uint64_t> durable_candidates_{0U};
    std::atomic<std::uint64_t> event_timing_artifacts_durable_{0U};
    std::atomic<std::uint64_t> event_timing_artifact_failures_{0U};
    std::atomic<std::uint64_t> event_timing_duplicate_retries_{0U};
    std::atomic<std::uint64_t> shadow_actions_accepted_{0U};
    std::atomic<std::uint64_t> shadow_actions_rejected_{0U};
    std::atomic<std::uint64_t> shadow_actions_suppressed_{0U};
    std::atomic<int> last_pipeline_verdict_{static_cast<int>(ksi::edge::PipelineVerdict::kNoFrame)};
    std::atomic<int> last_shadow_verdict_{static_cast<int>(ksi::edge::ShadowVerdict::kNoActivation)};
    std::atomic<int> last_shadow_heartbeat_verdict_{
        static_cast<int>(ksi::control_plane::HeartbeatVerdict::kOutOfDomain)};
    std::atomic<int> last_event_timing_artifact_verdict_{
        static_cast<int>(ksi::edge::EventTimingArtifactVerdict::kStorageError)};
    std::thread worker_;
#if KSI_EDGE_HAVE_CURL_TRANSPORT
    std::unique_ptr<ksi::edge::ArtifactVault> core_sync_vault_;
    std::unique_ptr<ksi::edge::SqliteStoreForward> core_sync_store_;
    std::unique_ptr<ksi::edge::CurlHttpsRequestExecutor> core_sync_executor_;
    std::unique_ptr<ksi::edge::CoreRestSyncTransport> core_sync_transport_;
    std::unique_ptr<ksi::edge::StoreForwardSyncDriver> core_sync_driver_;
    std::string core_sync_setup_verdict_ = "UNCONFIGURED";
    std::atomic<bool> core_sync_configured_{false};
    std::atomic<bool> core_sync_worker_running_{false};
    std::atomic<int> last_core_sync_verdict_{
        static_cast<int>(ksi::edge::CoreSyncVerdict::kRetryableFailure)};
    std::thread core_sync_worker_;
    // Persisted only so ConfigureMediaOffload can reuse the same origin/bearer
    // pair without re-deriving it from the CMake strings a second time.
    std::string core_sync_base_url_;
    std::string core_sync_bearer_token_;
    // Declare in reverse dependency order, same discipline as the perception
    // block above: the worker references source_/transport_ by raw pointer.
    std::unique_ptr<ksi::edge::FakeMediaSourcePort> media_offload_source_;
    std::unique_ptr<ksi::edge::CoreRestSourceMediaTransport> media_offload_transport_;
    std::unique_ptr<ksi::edge::MediaOffloadWorker> media_offload_worker_;
    std::string media_offload_setup_verdict_ = "UNCONFIGURED";
    // The active mission_id changes with every RefreshNativeActivation call on
    // the DrainWorker thread, but DrainMediaOffload runs on its own thread —
    // unlike the other AppRuntime snapshot fields (which only one thread ever
    // touches), this one genuinely needs a lock rather than reusing the
    // seqlock pattern above, which is sized for trivially-copyable telemetry.
    std::mutex media_offload_mission_mutex_;
    std::string media_offload_mission_id_;
    std::atomic<bool> media_offload_worker_running_{false};
    std::atomic<int> last_media_offload_verdict_{
        static_cast<int>(ksi::edge::MediaOffloadVerdict::kProgressed)};
    std::thread media_offload_thread_;
#endif
};

void OnRgbImage(E_DjiLiveViewCameraPosition position, const uint8_t* bytes, std::uint32_t byte_count,
                T_DjiLiveviewImageInfo image_info) {
    (void)position;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnRgbFrame(bytes, byte_count, image_info);
    }
}

T_DjiReturnCode OnPositionTopic(const uint8_t* bytes, std::uint16_t size,
                                const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnPosition(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnVelocityTopic(const uint8_t* bytes, std::uint16_t size,
                                const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnVelocity(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnPositionFusedTopic(const uint8_t* bytes, std::uint16_t size,
                                     const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnPositionFused(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnGpsDetailsTopic(const uint8_t* bytes, std::uint16_t size,
                                  const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnGpsDetails(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnGimbalAnglesTopic(const uint8_t* bytes, std::uint16_t size,
                                    const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnGimbalAngles(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnHardSyncTopic(const uint8_t* bytes, std::uint16_t size,
                                const T_DjiDataTimestamp* timestamp) {
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnHardSync(bytes, size, timestamp);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnFlightStatusTopic(const uint8_t* bytes, std::uint16_t size,
                                    const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnFlightStatus(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnBatteryInfoTopic(const uint8_t* bytes, std::uint16_t size,
                                   const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnBatteryInfo(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnHomePointSetStatusTopic(const uint8_t* bytes, std::uint16_t size,
                                          const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnHomePointSetStatus(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnRtkPositionInfoTopic(const uint8_t* bytes, std::uint16_t size,
                                       const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnRtkPositionInfo(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnFlightAnomalyTopic(const uint8_t* bytes, std::uint16_t size,
                                     const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnFlightAnomaly(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode OnDisplayModeTopic(const uint8_t* bytes, std::uint16_t size,
                                   const T_DjiDataTimestamp* timestamp) {
    (void)timestamp;
    if (AppRuntime* const runtime = g_runtime.load(std::memory_order_acquire); runtime != nullptr) {
        runtime->OnDisplayMode(bytes, size);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

int Run() {
    if (IsPlaceholderCredential()) {
        std::fputs("[ksi-edge-shadow] DJI credential header still contains placeholders\n", stderr);
        return 2;
    }

    AppRuntime runtime;
#if KSI_PSDK_APP_EDGE_ACTIVATION_CONFIGURED
    try {
        runtime.ConfigureNativeActivation(KSI_PSDK_APP_ACTIVATION_STATE_DIR,
                                          KSI_PSDK_APP_EDGE_DEVICE_ID,
                                          KSI_PSDK_APP_RUNTIME_VERSION);
        // No separate opt-in: the KMZ sidecar shares activation's directory
        // and identity, so it is exercised whenever activation itself is.
        runtime.ConfigureMissionKmz();
    } catch (const std::exception& exception) {
        std::fprintf(stderr, "[ksi-edge-shadow] native activation setup failed closed: %s\n",
                     exception.what());
    }
#else
    std::fputs("[ksi-edge-shadow] native activation is not provisioned in this DPK; "
               "capture-only mode\n",
               stderr);
#endif
#if KSI_PSDK_APP_PERCEPTION_CONFIGURED
    runtime.ConfigurePerception(KSI_PSDK_APP_PERCEPTION_STATE_DIR,
                                KSI_PSDK_APP_MODEL_ARTIFACT_DIR);
#else
    std::fputs("[ksi-edge-shadow] perception is not provisioned in this DPK; "
               "capture-only mode\n",
               stderr);
#endif
#if KSI_PSDK_APP_CORE_SYNC_CONFIGURED && KSI_EDGE_HAVE_CURL_TRANSPORT
    runtime.ConfigureCoreSync(KSI_PSDK_APP_SYNC_STATE_DIR, KSI_PSDK_APP_EDGE_DEVICE_ID,
                              KSI_PSDK_APP_CORE_BASE_URL, KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE,
                              KSI_PSDK_APP_TLS_CA_BUNDLE, KSI_PSDK_APP_CORE_TLS_PIN,
                              KSI_PSDK_APP_STORAGE_TLS_PIN);
#elif KSI_PSDK_APP_CORE_SYNC_CONFIGURED
    std::fputs("[ksi-edge-shadow] Core sync provisioning was requested without the static TLS backend; "
               "capture-only mode\n",
               stderr);
#endif
#if KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED && KSI_EDGE_HAVE_CURL_TRANSPORT
    runtime.ConfigureMediaOffload();
#elif KSI_PSDK_APP_MEDIA_OFFLOAD_CONFIGURED
    std::fputs("[ksi-edge-shadow] media offload provisioning was requested without the static TLS "
               "backend; source-media stays on the aircraft SD card\n",
               stderr);
#else
    std::fputs("[ksi-edge-shadow] media offload is not provisioned in this DPK; source-media stays "
               "on the aircraft SD card\n",
               stderr);
#endif
    g_runtime.store(&runtime, std::memory_order_release);
    bool core_initialized = false;
    bool liveview_initialized = false;
    bool subscription_initialized = false;
    bool position_subscribed = false;
    bool velocity_subscribed = false;
    bool position_fused_subscribed = false;
    bool gps_details_subscribed = false;
    bool gimbal_angles_subscribed = false;
    bool hard_sync_subscribed = false;
    bool flight_status_subscribed = false;
    bool battery_info_subscribed = false;
    bool home_point_set_status_subscribed = false;
    bool rtk_position_info_subscribed = false;
    bool flight_anomaly_subscribed = false;
    bool display_mode_subscribed = false;
    bool image_started = false;

    const auto cleanup = [&] {
        runtime.CloseIngress();
        if (image_started) {
            (void)DjiLiveview_StopImageStream(DJI_LIVEVIEW_CAMERA_POSITION_NO_1,
                                               DJI_LIVEVIEW_CAMERA_SOURCE_M4D_VIS);
        }
        runtime.StopWorker();
        // PSDK requires FIFO unsubscribe order.
        if (position_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_POSITION_VO);
        }
        if (velocity_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_VELOCITY);
        }
        if (position_fused_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_POSITION_FUSED);
        }
        if (gps_details_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_GPS_DETAILS);
        }
        if (gimbal_angles_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(
                DJI_FC_SUBSCRIPTION_TOPIC_GIMBAL_ANGLES_ON_POS_NO1);
        }
        if (hard_sync_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HARD_SYNC);
        }
        if (flight_status_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_STATUS_FLIGHT);
        }
        if (battery_info_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_BATTERY_INFO);
        }
        if (home_point_set_status_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HOME_POINT_SET_STATUS);
        }
        if (rtk_position_info_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_RTK_POSITION_INFO);
        }
        if (flight_anomaly_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_FLIGHT_ANOMALY);
        }
        if (display_mode_subscribed) {
            (void)DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_STATUS_DISPLAYMODE);
        }
        if (subscription_initialized) {
            (void)DjiFcSubscription_DeInit();
        }
        if (liveview_initialized) {
            (void)DjiLiveview_Deinit();
        }
        if (core_initialized) {
            (void)DjiCore_DeInit();
        }
        g_runtime.store(nullptr, std::memory_order_release);
    };

    T_DjiReturnCode result = KsiOsalGlue_Register();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("register OSAL", result);
        cleanup();
        return 1;
    }
    (void)KsiLoggerConsoleGlue_Register();
    result = KsiSocketGlue_Register();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("register socket", result);
        cleanup();
        return 1;
    }
    result = KsiUsbBulkGlue_Register();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("register USB bulk", result);
        cleanup();
        return 1;
    }

    T_DjiUserInfo user_info {};
    if (!FillUserInfo(&user_info)) {
        std::fputs("[ksi-edge-shadow] invalid DJI credential field length\n", stderr);
        cleanup();
        return 2;
    }
    result = DjiCore_Init(&user_info);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("DjiCore_Init", result);
        cleanup();
        return 1;
    }
    core_initialized = true;

    // A DPK must acknowledge dji_app_mgr promptly; this call never authorizes
    // a flight action and is made before sensor subscriptions just as the
    // working PSDK tap does.
    result = DjiCore_ApplicationStart();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("DjiCore_ApplicationStart", result);
        cleanup();
        return 1;
    }

    result = DjiFcSubscription_Init();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("DjiFcSubscription_Init", result);
        cleanup();
        return 1;
    }
    subscription_initialized = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_POSITION_VO,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_50_HZ,
                                               OnPositionTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe PositionVO", result);
        cleanup();
        return 1;
    }
    position_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_VELOCITY,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_50_HZ,
                                               OnVelocityTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe velocity", result);
        cleanup();
        return 1;
    }
    velocity_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_POSITION_FUSED,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_50_HZ,
                                               OnPositionFusedTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe fused position", result);
        cleanup();
        return 1;
    }
    position_fused_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_GPS_DETAILS,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_5_HZ,
                                               OnGpsDetailsTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe GPS details", result);
        cleanup();
        return 1;
    }
    gps_details_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(
        DJI_FC_SUBSCRIPTION_TOPIC_GIMBAL_ANGLES_ON_POS_NO1,
        DJI_DATA_SUBSCRIPTION_TOPIC_50_HZ, OnGimbalAnglesTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe gimbal angles", result);
        cleanup();
        return 1;
    }
    gimbal_angles_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HARD_SYNC,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_400_HZ,
                                               OnHardSyncTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe hard-sync", result);
        cleanup();
        return 1;
    }
    hard_sync_subscribed = true;
    // ADR-KSI-021 §5 [8] precondition-sensing topics. 1Hz is a policy choice,
    // not a measured requirement — these feed a pre-arming precondition check,
    // not continuous control, and this is the same topic-addition pattern as
    // the six subscriptions above (DjiFcSubscription_* is not gated by
    // tools/edge/check_shadow_flight_boundary.py's allowlist).
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_STATUS_FLIGHT,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ, OnFlightStatusTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe flight status", result);
        cleanup();
        return 1;
    }
    flight_status_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_BATTERY_INFO,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ, OnBatteryInfoTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe battery info", result);
        cleanup();
        return 1;
    }
    battery_info_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HOME_POINT_SET_STATUS,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ,
                                               OnHomePointSetStatusTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe home point set status", result);
        cleanup();
        return 1;
    }
    home_point_set_status_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_RTK_POSITION_INFO,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ,
                                               OnRtkPositionInfoTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe RTK position info", result);
        cleanup();
        return 1;
    }
    rtk_position_info_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_FLIGHT_ANOMALY,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ, OnFlightAnomalyTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe flight anomaly", result);
        cleanup();
        return 1;
    }
    flight_anomaly_subscribed = true;
    result = DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_STATUS_DISPLAYMODE,
                                               DJI_DATA_SUBSCRIPTION_TOPIC_1_HZ, OnDisplayModeTopic);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("subscribe display mode", result);
        cleanup();
        return 1;
    }
    display_mode_subscribed = true;

    result = DjiLiveview_Init();
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("DjiLiveview_Init", result);
        cleanup();
        return 1;
    }
    liveview_initialized = true;
    runtime.OpenIngress();
    runtime.StartWorker();
    result = DjiLiveview_StartImageStream(DJI_LIVEVIEW_CAMERA_POSITION_NO_1,
                                           DJI_LIVEVIEW_CAMERA_SOURCE_M4D_VIS,
                                           PIXFMT_RGB_PACKED, OnRgbImage);
    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        LogPsdError("start RGB packed image stream", result);
        cleanup();
        return 1;
    }
    image_started = true;

    std::fputs("[ksi-edge-shadow] PSDK ingress active; shadow actions disabled; "
               "activation/TensorRT/calibration gates remain fail-closed\n",
               stderr);
    while (g_termination_requested == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    // cleanup() (via StopWorker()) joins DrainWorker before we read its
    // std::string/std::optional members below -- PrintStatistics() used to run
    // first, racing the still-live worker thread's per-second/per-frame writes
    // to those same members (a data race, UB, observed to be able to tear or
    // dereference freed memory on shutdown). Order matters here.
    cleanup();
    runtime.PrintStatistics();
    return 0;
}

}  // namespace

int main() {
    struct sigaction action {};
    action.sa_handler = OnTerminationSignal;
    (void)sigemptyset(&action.sa_mask);
    action.sa_flags = 0;
    (void)sigaction(SIGINT, &action, nullptr);
    (void)sigaction(SIGTERM, &action, nullptr);
    return Run();
}

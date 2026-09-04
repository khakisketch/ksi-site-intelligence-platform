// Non-actuating HIL-1P PSDK/MOP peer receiver.
//
// This client is deliberately independent of PsdkRouteCompanion's server
// listener. It connects only to an explicitly configured remote PSDK address
// and channel, validates EDGE_BUNDLE_UPLOAD metadata, and exposes no action
// callback or DJI flight/media control surface.

#ifndef KSI_PSDK_APP_PSDK_MOP_PEER_RECEIVER_HPP
#define KSI_PSDK_APP_PSDK_MOP_PEER_RECEIVER_HPP

#include <cstddef>
#include <cstdint>
#include <condition_variable>
#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <thread>

namespace ksi::psdk {

using MopPeerHandle = void*;
using MopPeerResult = std::uint64_t;

// Numeric values are the pinned PSDK E_DjiChannelAddress values. Keeping this
// public boundary free of vendor headers makes the closest vendor boundary
// injectable in native tests.
enum class MopPeerAddress : std::uint32_t {
    kUnknown = 0U,
    kPayloadPortNo1 = 1U,
    kPayloadPortNo2 = 2U,
    kPayloadPortNo3 = 3U,
    kExtensionPortV2No4 = 4U,
    kExtensionPortV2No5 = 5U,
    kExtensionPortV2No6 = 6U,
    kExtensionPortV2No7 = 7U,
    kExtensionPort = 8U,
};

struct MopPeerApi {
    MopPeerResult success = 0U;
    MopPeerResult connection_closed = 0U;
    std::function<MopPeerResult()> initialize;
    std::function<MopPeerResult(MopPeerHandle*)> create_reliable;
    std::function<MopPeerResult(MopPeerHandle, MopPeerAddress, std::uint16_t)> connect;
    std::function<MopPeerResult(MopPeerHandle, std::uint8_t*, std::uint32_t,
                                std::uint32_t*)>
        receive;
    std::function<MopPeerResult(MopPeerHandle)> close;
    std::function<MopPeerResult(MopPeerHandle)> destroy;
};

// Returns wrappers over the actual vendored DjiMopChannel_Init/Create/Connect/
// RecvData/Close/Destroy API. EDGE_BUNDLE_UPLOAD defines no acknowledgement,
// so this receiver intentionally has no SendData callback or send behaviour.
MopPeerApi DjiMopPeerApi();

struct EdgeBundleMetadata;

struct PsdkMopPeerReceiverConfig {
    std::string organization_id;
    std::string site_id;
    std::string edge_device_id;
    std::string subject_port_id;
    MopPeerAddress peer_address = MopPeerAddress::kUnknown;
    std::uint16_t mop_channel_id = 0U;
    std::size_t maximum_frame_bytes = 64U * 1024U;
    std::size_t idempotency_capacity = 128U;
    std::uint32_t reconnect_delay_ms = 100U;
    // Optional metadata observation only. It is invoked for a newly accepted
    // validated frame and cannot select a local DJI/device action.
    std::function<void(const EdgeBundleMetadata&)> accepted_metadata_sink;
};

struct EdgeBundleMetadata {
    std::string organization_id;
    std::string site_id;
    std::string mission_id;
    std::string edge_device_id;
    std::string bundle_object_ref;
    std::string bundle_sha256;
    std::string idempotency_key;

    bool operator==(const EdgeBundleMetadata& other) const noexcept;
};

struct MopPeerSnapshot {
    bool psdk_initialized = false;
    bool mop_connected = false;
    std::uint64_t connect_attempts = 0U;
    std::uint64_t accepted_frames = 0U;
    std::uint64_t duplicate_frames = 0U;
    std::uint64_t rejected_frames = 0U;
    std::uint64_t transport_disconnects = 0U;
};

enum class MopPeerReceiveVerdict {
    kAccepted,
    kDuplicate,
    kIdempotencyConflict,
    kMalformedFrame,
    kOversizeFrame,
    kIdentityMismatch,
    kDisconnected,
    kTransportFailure,
};

struct MopPeerReceiveResult {
    MopPeerReceiveVerdict verdict = MopPeerReceiveVerdict::kTransportFailure;
    EdgeBundleMetadata metadata;
};

class PsdkMopPeerReceiver final {
public:
    explicit PsdkMopPeerReceiver(PsdkMopPeerReceiverConfig config,
                                 MopPeerApi api = DjiMopPeerApi());
    ~PsdkMopPeerReceiver();

    PsdkMopPeerReceiver(const PsdkMopPeerReceiver&) = delete;
    PsdkMopPeerReceiver& operator=(const PsdkMopPeerReceiver&) = delete;

    // The caller must invoke this only after DjiCore_ApplicationStart succeeds.
    // Start owns a bounded reconnect worker. A receiver object alone never
    // implies a MOP connection, and a successful Connect is the only state
    // transition that sets mop_connected.
    bool Start(bool psdk_initialized, std::string* error);
    void Stop();
    bool mop_connected() const noexcept;
    MopPeerSnapshot Snapshot() const;

private:
    void ReceiveLoop();
    bool ConnectOnce();
    MopPeerReceiveResult ReceiveNext(MopPeerHandle handle);
    MopPeerReceiveResult ValidateFrame(const std::string& frame);
    void ReleaseChannel(MopPeerHandle handle);
    bool WaitForRetry();
    void Record(MopPeerReceiveVerdict verdict);

    PsdkMopPeerReceiverConfig config_;
    MopPeerApi api_;
    mutable std::mutex state_mutex_;
    std::condition_variable retry_cv_;
    MopPeerSnapshot snapshot_;
    MopPeerHandle channel_handle_ = nullptr;
    bool close_requested_ = false;
    bool started_ = false;
    bool stopping_ = false;
    std::string pending_bytes_;
    std::map<std::string, EdgeBundleMetadata> idempotency_records_;
    std::thread receive_thread_;
};

}  // namespace ksi::psdk

#endif  // KSI_PSDK_APP_PSDK_MOP_PEER_RECEIVER_HPP

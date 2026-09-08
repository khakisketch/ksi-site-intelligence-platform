// Non-actuating PSDK/MOP EDGE_UPLINK companion.
//
// This module owns only a reliable MOP data channel and a local Unix JSON
// control/status socket.  It deliberately has no DJI flight, waypoint, gimbal,
// camera, or payload-control dependency.

#ifndef KSI_PSDK_APP_PSDK_ROUTE_COMPANION_HPP
#define KSI_PSDK_APP_PSDK_ROUTE_COMPANION_HPP

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace ksi::psdk {

using MopHandle = void*;
using MopResult = std::uint64_t;

struct MopApi {
    MopResult success = 0U;
    MopResult connection_closed = 0U;
    std::function<MopResult()> initialize;
    std::function<MopResult(MopHandle*)> create_reliable;
    std::function<MopResult(MopHandle, std::uint16_t)> bind;
    std::function<MopResult(MopHandle, MopHandle*)> accept;
    std::function<MopResult(MopHandle)> close;
    std::function<MopResult(MopHandle)> destroy;
    std::function<MopResult(MopHandle, std::uint8_t*, std::uint32_t,
                            std::uint32_t*)>
        send;
    std::function<MopResult(MopHandle, std::uint8_t*, std::uint32_t,
                            std::uint32_t*)>
        receive;
};

// Returns wrappers over the actual vendored dji_mop_channel.h API.
MopApi DjiMopApi();

struct RouteStateSnapshot {
    bool psdk_initialized = false;
    bool mop_connected = false;
    bool handler_registered = false;
    std::uint64_t generation = 0U;

    bool available() const noexcept {
        return psdk_initialized && mop_connected && handler_registered;
    }
};

class RouteState final {
public:
    void SetPsdkInitialized(bool value);
    void SetMopConnected(bool value);
    void SetHandlerRegistered(bool value);
    RouteStateSnapshot Snapshot() const;

private:
    void Set(bool* field, bool value);

    mutable std::mutex mutex_;
    RouteStateSnapshot state_;
};

struct PsdkRouteCompanionConfig {
    std::string socket_path;
    std::string organization_id;
    std::string site_id;
    std::string edge_device_id;
    std::string subject_port_id;
    std::uint16_t mop_channel_id = 0U;
    std::size_t maximum_request_bytes = 64U * 1024U;
    std::uint32_t client_timeout_ms = 2000U;
};

class PsdkRouteCompanion final {
public:
    explicit PsdkRouteCompanion(PsdkRouteCompanionConfig config,
                                MopApi api = DjiMopApi());
    ~PsdkRouteCompanion();

    PsdkRouteCompanion(const PsdkRouteCompanion&) = delete;
    PsdkRouteCompanion& operator=(const PsdkRouteCompanion&) = delete;

    // PSDK initialization is supplied by the owner after
    // DjiCore_ApplicationStart succeeds.  Start creates the Unix endpoint and
    // launches the MOP lifecycle; it never manufactures a connected state.
    bool Start(bool psdk_initialized, std::string* error);
    void Stop();

    RouteStateSnapshot Snapshot() const;

private:
    bool OpenUnixListener(std::string* error);
    void UnixLoop();
    void MopLoop();
    void HandleUnixClient(int client_fd);
    bool SendMopFrame(const std::string& frame);
    void CloseForShutdown();
    void RemoveOwnedSocket();
    bool IsCurrentOpenConnectionLocked(MopHandle handle,
                                       std::uint64_t connection_epoch) const;
    MopHandle RequestConnectedCloseLocked(MopHandle handle,
                                          std::uint64_t connection_epoch);
    MopHandle RequestListenerCloseLocked(MopHandle handle);
    void InvokeConnectedClose(MopHandle handle, std::uint64_t connection_epoch);
    void InvokeListenerClose(MopHandle handle);
    void RetireConnectedHandle(MopHandle handle, std::uint64_t connection_epoch);
    void RetireListenerHandle(MopHandle handle);

    PsdkRouteCompanionConfig config_;
    MopApi api_;
    RouteState state_;
    std::atomic<bool> stopping_{false};
    std::atomic<bool> started_{false};
    std::atomic<std::uint64_t> status_sequence_{0U};
    // Per-instance collision-resistant identity used only to make status signal
    // retries unambiguous across companion/process incarnations. It is never
    // an authority or route-subject input.
    const std::string incarnation_id_;

    // Every transition which publishes/revokes a MOP handle holds this mutex.
    // A sender takes a per-accepted-handle lease before releasing the mutex for
    // vendor SendData. Close may run while that lease is active to unblock the
    // vendor call; only MopLoop destroys after every lease has returned.
    mutable std::mutex handles_mutex_;
    std::condition_variable handles_changed_;
    MopHandle listener_handle_ = nullptr;
    MopHandle connected_handle_ = nullptr;
    std::uint64_t connected_epoch_ = 0U;
    std::size_t connected_send_leases_ = 0U;
    bool listener_close_requested_ = false;
    bool listener_close_in_flight_ = false;
    bool listener_close_completed_ = false;
    bool connected_close_requested_ = false;
    bool connected_close_in_flight_ = false;
    bool connected_close_completed_ = false;
    int unix_listener_fd_ = -1;
    std::uint64_t socket_device_ = 0U;
    std::uint64_t socket_inode_ = 0U;

    std::thread mop_thread_;
    std::thread unix_thread_;
};

}  // namespace ksi::psdk

#endif  // KSI_PSDK_APP_PSDK_ROUTE_COMPANION_HPP

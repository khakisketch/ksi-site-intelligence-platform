#include "runtime/psdk_route_companion.hpp"
#include "runtime/psdk_mop_peer_receiver.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace {

using ksi::psdk::MopApi;
using ksi::psdk::MopHandle;
using ksi::psdk::MopPeerAddress;
using ksi::psdk::MopPeerApi;
using ksi::psdk::MopPeerHandle;
using ksi::psdk::MopResult;
using ksi::psdk::PsdkMopPeerReceiver;
using ksi::psdk::PsdkMopPeerReceiverConfig;
using ksi::psdk::PsdkRouteCompanion;
using ksi::psdk::PsdkRouteCompanionConfig;
using ksi::psdk::RouteState;

constexpr MopResult kSuccess = 0U;
constexpr MopResult kClosed = 11U;
constexpr MopResult kFailure = 99U;

void Check(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Predicate>
void WaitFor(Predicate predicate, const char* message) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!predicate()) {
        if (std::chrono::steady_clock::now() >= deadline) {
            throw std::runtime_error(message);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
}

template <typename Predicate>
bool WaitForWithin(Predicate predicate, std::chrono::milliseconds timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!predicate()) {
        if (std::chrono::steady_clock::now() >= deadline) {
            return false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return true;
}

std::string Exchange(const std::filesystem::path& path, const std::string& request);
PsdkRouteCompanionConfig Config(const std::filesystem::path& socket_path);
std::string UploadRequest();

struct FakeMop {
    struct Connection {
        bool closed = false;
    };

    std::mutex mutex;
    std::condition_variable changed;
    bool listener_closed = false;
    int listener_token = 1;
    std::deque<std::unique_ptr<Connection>> pending;
    std::vector<std::unique_ptr<Connection>> owned;
    std::vector<std::string> sent_frames;
    std::uint16_t bound_channel = 0U;
    int initialize_calls = 0;
    int accept_calls = 0;
    int close_calls = 0;
    int destroy_calls = 0;
    int connected_close_calls = 0;
    int listener_close_calls = 0;
    int active_sends = 0;
    bool block_send = false;
    bool send_entered = false;
    bool release_blocked_send = false;
    bool destroy_before_send_return = false;
    int active_connected_closes = 0;
    int active_listener_closes = 0;
    bool block_close_return = false;
    bool release_blocked_close = false;
    bool connected_close_entered = false;
    bool listener_close_entered = false;
    bool connected_destroyed = false;
    bool listener_destroyed = false;
    bool destroy_during_connected_close = false;
    bool destroy_during_listener_close = false;
    bool close_after_destroy = false;

    MopHandle Connect() {
        auto connection = std::make_unique<Connection>();
        MopHandle handle = connection.get();
        {
            std::lock_guard<std::mutex> lock(mutex);
            pending.push_back(std::move(connection));
        }
        changed.notify_all();
        return handle;
    }

    void Disconnect(MopHandle handle) {
        {
            std::lock_guard<std::mutex> lock(mutex);
            static_cast<Connection*>(handle)->closed = true;
        }
        changed.notify_all();
    }

    MopApi Api() {
        MopApi api;
        api.success = kSuccess;
        api.connection_closed = kClosed;
        api.initialize = [this] {
            std::lock_guard<std::mutex> lock(mutex);
            ++initialize_calls;
            return kSuccess;
        };
        api.create_reliable = [this](MopHandle* output) {
            *output = &listener_token;
            return kSuccess;
        };
        api.bind = [this](MopHandle handle, std::uint16_t channel) {
            if (handle != &listener_token) {
                return kFailure;
            }
            std::lock_guard<std::mutex> lock(mutex);
            bound_channel = channel;
            return kSuccess;
        };
        api.accept = [this](MopHandle handle, MopHandle* output) {
            if (handle != &listener_token) {
                return kFailure;
            }
            std::unique_lock<std::mutex> lock(mutex);
            ++accept_calls;
            changed.wait(lock, [this] { return listener_closed || !pending.empty(); });
            if (listener_closed) {
                return kClosed;
            }
            std::unique_ptr<Connection> connection = std::move(pending.front());
            pending.pop_front();
            *output = connection.get();
            owned.push_back(std::move(connection));
            return kSuccess;
        };
        api.close = [this](MopHandle handle) {
            std::unique_lock<std::mutex> lock(mutex);
            ++close_calls;
            if (handle == &listener_token) {
                close_after_destroy = close_after_destroy || listener_destroyed;
                listener_closed = true;
                ++listener_close_calls;
                ++active_listener_closes;
                listener_close_entered = true;
                changed.notify_all();
                if (block_close_return) {
                    changed.wait(lock, [this] { return release_blocked_close; });
                }
                --active_listener_closes;
            } else if (handle != nullptr) {
                close_after_destroy = close_after_destroy || connected_destroyed;
                static_cast<Connection*>(handle)->closed = true;
                ++connected_close_calls;
                ++active_connected_closes;
                connected_close_entered = true;
                changed.notify_all();
                if (block_close_return) {
                    changed.wait(lock, [this] { return release_blocked_close; });
                }
                --active_connected_closes;
            }
            lock.unlock();
            changed.notify_all();
            return kSuccess;
        };
        api.destroy = [this](MopHandle handle) {
            std::lock_guard<std::mutex> lock(mutex);
            ++destroy_calls;
            destroy_before_send_return = destroy_before_send_return || active_sends != 0;
            if (handle == &listener_token) {
                listener_destroyed = true;
                destroy_during_listener_close =
                    destroy_during_listener_close || active_listener_closes != 0;
            } else {
                connected_destroyed = true;
                destroy_during_connected_close =
                    destroy_during_connected_close || active_connected_closes != 0;
            }
            return kSuccess;
        };
        api.send = [this](MopHandle handle, std::uint8_t* data, std::uint32_t size,
                          std::uint32_t* sent) {
            std::unique_lock<std::mutex> lock(mutex);
            if (handle == nullptr || static_cast<Connection*>(handle)->closed) {
                *sent = 0U;
                return kClosed;
            }
            if (block_send) {
                send_entered = true;
                ++active_sends;
                changed.notify_all();
                changed.wait(lock, [this, handle] {
                    return release_blocked_send || static_cast<Connection*>(handle)->closed;
                });
                --active_sends;
                changed.notify_all();
                if (static_cast<Connection*>(handle)->closed) {
                    *sent = 0U;
                    return kClosed;
                }
            }
            sent_frames.emplace_back(reinterpret_cast<char*>(data), size);
            *sent = size;
            return kSuccess;
        };
        api.receive = [this](MopHandle handle, std::uint8_t*, std::uint32_t,
                             std::uint32_t* received) {
            std::unique_lock<std::mutex> lock(mutex);
            auto* connection = static_cast<Connection*>(handle);
            changed.wait(lock, [this, connection] {
                return listener_closed || connection->closed;
            });
            *received = 0U;
            return kClosed;
        };
        return api;
    }
};

// Closest hardware-free seam: both production lifecycle classes share this
// in-memory implementation of only the vendored MOP function tables. Framing,
// state transitions, Unix ingress and receiver validation remain production
// code; no TCP/Unix substitute is used by a production target.
struct InteropMop {
    struct Connection {
        bool closed = false;
        std::string server_to_peer;
    };
    struct Endpoint {
        Connection* connection;
        bool server_side;
    };

    std::mutex mutex;
    std::condition_variable changed;
    int listener_token = 1;
    bool listener_closed = false;
    bool listener_bound = false;
    bool connect_pending = false;
    std::uint16_t bound_channel = 0U;
    Connection connection;
    Endpoint server_endpoint{&connection, true};
    Endpoint peer_endpoint{&connection, false};

    MopApi ServerApi() {
        MopApi api;
        api.success = kSuccess;
        api.connection_closed = kClosed;
        api.initialize = [] { return kSuccess; };
        api.create_reliable = [this](MopHandle* output) {
            *output = &listener_token;
            return kSuccess;
        };
        api.bind = [this](MopHandle handle, std::uint16_t channel) {
            if (handle != &listener_token) {
                return kFailure;
            }
            {
                std::lock_guard<std::mutex> lock(mutex);
                listener_bound = true;
                bound_channel = channel;
            }
            changed.notify_all();
            return kSuccess;
        };
        api.accept = [this](MopHandle handle, MopHandle* output) {
            if (handle != &listener_token) {
                return kFailure;
            }
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock, [this] { return listener_closed || connect_pending; });
            if (listener_closed) {
                return kClosed;
            }
            connect_pending = false;
            *output = &server_endpoint;
            return kSuccess;
        };
        api.close = [this](MopHandle handle) { return Close(handle); };
        api.destroy = [](MopHandle) { return kSuccess; };
        api.send = [this](MopHandle handle, std::uint8_t* data, std::uint32_t size,
                          std::uint32_t* sent) {
            std::lock_guard<std::mutex> lock(mutex);
            auto* endpoint = static_cast<Endpoint*>(handle);
            if (endpoint != &server_endpoint || connection.closed) {
                *sent = 0U;
                return kClosed;
            }
            connection.server_to_peer.append(reinterpret_cast<const char*>(data), size);
            *sent = size;
            changed.notify_all();
            return kSuccess;
        };
        api.receive = [this](MopHandle handle, std::uint8_t*, std::uint32_t,
                             std::uint32_t* received) {
            std::unique_lock<std::mutex> lock(mutex);
            if (handle != &server_endpoint) {
                *received = 0U;
                return kFailure;
            }
            changed.wait(lock, [this] { return connection.closed; });
            *received = 0U;
            return kClosed;
        };
        return api;
    }

    MopPeerApi PeerApi() {
        MopPeerApi api;
        api.success = kSuccess;
        api.connection_closed = kClosed;
        api.initialize = [] { return kSuccess; };
        api.create_reliable = [this](MopPeerHandle* output) {
            *output = &peer_endpoint;
            return kSuccess;
        };
        api.connect = [this](MopPeerHandle handle, MopPeerAddress address,
                             std::uint16_t channel) {
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock, [this] { return listener_bound || connection.closed; });
            if (handle != &peer_endpoint || connection.closed ||
                address != MopPeerAddress::kPayloadPortNo1 || channel != bound_channel) {
                return kFailure;
            }
            connect_pending = true;
            changed.notify_all();
            return kSuccess;
        };
        api.receive = [this](MopPeerHandle handle, std::uint8_t* data, std::uint32_t size,
                             std::uint32_t* received) {
            std::unique_lock<std::mutex> lock(mutex);
            if (handle != &peer_endpoint) {
                *received = 0U;
                return kFailure;
            }
            changed.wait(lock, [this] {
                return connection.closed || !connection.server_to_peer.empty();
            });
            if (connection.closed) {
                *received = 0U;
                return kClosed;
            }
            const std::size_t count =
                std::min<std::size_t>(size, connection.server_to_peer.size());
            std::memcpy(data, connection.server_to_peer.data(), count);
            connection.server_to_peer.erase(0U, count);
            *received = static_cast<std::uint32_t>(count);
            return kSuccess;
        };
        api.close = [this](MopPeerHandle handle) { return Close(handle); };
        api.destroy = [](MopPeerHandle) { return kSuccess; };
        return api;
    }

    MopResult Close(void* handle) {
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (handle == &listener_token) {
                listener_closed = true;
            } else if (handle == &server_endpoint || handle == &peer_endpoint) {
                connection.closed = true;
            } else {
                return kFailure;
            }
        }
        changed.notify_all();
        return kSuccess;
    }
};

std::string Exchange(const std::filesystem::path& path, const std::string& request) {
    const int client = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    Check(client >= 0, "must create Gateway-side Unix socket");
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    const std::string text = path.string();
    std::memcpy(address.sun_path, text.c_str(), text.size() + 1U);
    Check(connect(client, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) == 0,
          "must connect to PSDK companion");
    std::size_t offset = 0U;
    while (offset < request.size()) {
        const ssize_t sent =
            send(client, request.data() + offset, request.size() - offset, MSG_NOSIGNAL);
        Check(sent > 0, "must send complete Unix request");
        offset += static_cast<std::size_t>(sent);
    }
    Check(shutdown(client, SHUT_WR) == 0, "must delimit Unix request with EOF");
    std::string response;
    std::array<char, 4096U> buffer{};
    while (true) {
        const ssize_t count = recv(client, buffer.data(), buffer.size(), 0);
        Check(count >= 0, "must receive companion response");
        if (count == 0) {
            break;
        }
        response.append(buffer.data(), static_cast<std::size_t>(count));
    }
    close(client);
    return response;
}

void TestStopClosesBlockedSendWithoutExternalRelease() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-stop-blocked-send-" + std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";
    FakeMop fake;
    fake.block_send = true;
    PsdkRouteCompanion companion(Config(socket_path), fake.Api());
    std::string error;
    Check(companion.Start(true, &error), "companion must start before blocked-send shutdown");
    const MopHandle connection = fake.Connect();
    WaitFor([&] { return companion.Snapshot().available(); },
            "MOP route must be available before blocked send");

    std::string response;
    std::thread sender([&] { response = Exchange(socket_path, UploadRequest()); });
    WaitFor(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.send_entered;
        },
        "test MOP send must enter its controllable blocked state");

    std::atomic<bool> stop_completed{false};
    std::thread stopper([&] {
        companion.Stop();
        stop_completed.store(true);
    });

    const bool close_observed = WaitForWithin(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.connected_close_calls == 1;
        },
        std::chrono::milliseconds(300));
    if (!close_observed) {
        // Keep the RED test failure recoverable on the old implementation: it
        // holds the companion handles lock across send, so release only after
        // recording that Stop could not request Close.
        {
            std::lock_guard<std::mutex> lock(fake.mutex);
            fake.release_blocked_send = true;
        }
        fake.changed.notify_all();
        stopper.join();
        sender.join();
        Check(false, "Stop must request Close while SendData is blocked");
    }

    WaitFor([&] { return stop_completed.load(); },
            "Stop must complete when Close releases the blocked send");
    stopper.join();
    sender.join();
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(fake.connected_close_calls == 1,
              "blocked-send shutdown must request exactly one connected-handle Close");
        Check(!fake.destroy_before_send_return,
              "MOP worker must not Destroy a handle before its send lease returns");
    }
    Check(response == "{\"error\":\"ROUTE_UNAVAILABLE\"}\n",
          "a send invalidated by shutdown must not receive a stale success receipt");
    Check(connection != nullptr, "test must retain the accepted connection identity");
    std::filesystem::remove(directory);
}

void TestConnectedCloseCompletesBeforeDestroy() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-connected-close-completion-" +
         std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";
    FakeMop fake;
    fake.block_close_return = true;
    PsdkRouteCompanion companion(Config(socket_path), fake.Api());
    std::string error;
    Check(companion.Start(true, &error), "companion must start before close completion test");
    fake.Connect();
    WaitFor([&] { return companion.Snapshot().available(); },
            "MOP route must be available before connected close");

    std::thread stopper([&] { companion.Stop(); });
    WaitFor(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.connected_close_entered;
        },
        "Stop must enter the controllable connected Close call");
    const bool destroyed_before_close_return = WaitForWithin(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.connected_destroyed;
        },
        std::chrono::milliseconds(300));
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        fake.release_blocked_close = true;
    }
    fake.changed.notify_all();
    stopper.join();
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(!destroyed_before_close_return,
              "accepted handle must not Destroy while its Close call is in flight");
        Check(!fake.destroy_during_connected_close,
              "accepted-handle Destroy must follow completed Close");
        Check(!fake.close_after_destroy, "Close must never begin after Destroy");
    }
    std::filesystem::remove(directory);
}

void TestListenerCloseCompletesBeforeDestroy() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-listener-close-completion-" +
         std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";
    FakeMop fake;
    fake.block_close_return = true;
    PsdkRouteCompanion companion(Config(socket_path), fake.Api());
    std::string error;
    Check(companion.Start(true, &error), "companion must start before listener close test");
    WaitFor([&] { return companion.Snapshot().handler_registered; },
            "MOP handler must register before listener close");

    std::thread stopper([&] { companion.Stop(); });
    WaitFor(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.listener_close_entered;
        },
        "Stop must enter the controllable listener Close call");
    const bool destroyed_before_close_return = WaitForWithin(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.listener_destroyed;
        },
        std::chrono::milliseconds(300));
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        fake.release_blocked_close = true;
    }
    fake.changed.notify_all();
    stopper.join();
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(!destroyed_before_close_return,
              "listener must not Destroy while its Close call is in flight");
        Check(!fake.destroy_during_listener_close,
              "listener Destroy must follow completed Close");
        Check(!fake.close_after_destroy, "listener Close must never begin after Destroy");
    }
    std::filesystem::remove(directory);
}

void TestPeerDisconnectDefersDestroyUntilBlockedSendReturns() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-disconnect-blocked-send-" +
         std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";
    FakeMop fake;
    fake.block_send = true;
    PsdkRouteCompanion companion(Config(socket_path), fake.Api());
    std::string error;
    Check(companion.Start(true, &error), "companion must start before disconnect test");
    const MopHandle connection = fake.Connect();
    WaitFor([&] { return companion.Snapshot().available(); },
            "MOP route must be available before peer disconnect");

    std::string response;
    std::thread sender([&] { response = Exchange(socket_path, UploadRequest()); });
    WaitFor(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.send_entered;
        },
        "test MOP send must enter its controllable blocked state");

    fake.Disconnect(connection);
    sender.join();
    WaitFor(
        [&] {
            std::lock_guard<std::mutex> lock(fake.mutex);
            return fake.destroy_calls == 1;
        },
        "MOP worker must destroy the disconnected handle after the send returns");
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(fake.connected_close_calls == 1,
              "peer disconnect and send failure must not double-Close one handle");
        Check(!fake.destroy_before_send_return,
              "peer disconnect must not Destroy before an in-flight send returns");
    }
    Check(response == "{\"error\":\"ROUTE_UNAVAILABLE\"}\n",
          "peer disconnect must not leave a stale success receipt");
    companion.Stop();
    std::filesystem::remove(directory);
}

PsdkRouteCompanionConfig Config(const std::filesystem::path& socket_path) {
    return PsdkRouteCompanionConfig{socket_path.string(), "org-1", "site-1", "edge-1",
                                    "psdk.edge_uplink", 49154U};
}

std::string StatusRequest(std::string port = "psdk.edge_uplink") {
    return "{\"canonicalCapabilityId\":\"EDGE_UPLINK\",\"edgeDeviceId\":\"edge-1\","
           "\"integrationPath\":\"PSDK_MANIFOLD\",\"operation\":\"ROUTE_STATUS_V1\","
           "\"requiredHandler\":\"EDGE_BUNDLE_UPLOAD\",\"subjectPortId\":\"" +
           port + "\"}\n";
}

std::string UploadRequest() {
    return "{\"idempotency_key\":\"bundle-1\",\"operation\":\"EDGE_BUNDLE_UPLOAD\","
           "\"payload\":{\"bundle_object_ref\":\"objects/bundle-1.json\","
           "\"bundle_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
           "\"edge_device_id\":\"edge-1\",\"idempotency_key\":\"bundle-1\","
           "\"mission_id\":\"mission-1\",\"organization_id\":\"org-1\","
           "\"site_id\":\"site-1\"}}\n";
}

std::string SignalId(const std::string& response) {
    constexpr const char* prefix = "\"signalId\":\"";
    const std::size_t start = response.find(prefix);
    Check(start != std::string::npos, "status response must contain signalId");
    const std::size_t value_start = start + std::strlen(prefix);
    const std::size_t end = response.find('"', value_start);
    Check(end != std::string::npos, "status signalId must be terminated");
    return response.substr(value_start, end - value_start);
}

void CheckSignalIdFormat(const std::string& signal_id) {
    constexpr const char* prefix = "psdk-route-";
    Check(signal_id.rfind(prefix, 0U) == 0U,
          "signal ID must retain the stable PSDK route tracing prefix");
    const std::size_t nonce_start = std::strlen(prefix);
    const std::size_t nonce_end = signal_id.find('-', nonce_start);
    Check(nonce_end == nonce_start + 32U,
          "signal ID must contain one 128-bit hexadecimal incarnation ID");
    for (std::size_t index = nonce_start; index < nonce_end; ++index) {
        const char value = signal_id[index];
        Check((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f'),
              "incarnation ID must be lowercase hexadecimal");
    }
    Check(signal_id.find('-', nonce_end + 1U) != std::string::npos,
          "signal ID must retain route generation and request sequence");
}

void TestThreeFactTruthTable() {
    for (unsigned mask = 0U; mask < 8U; ++mask) {
        RouteState state;
        state.SetPsdkInitialized((mask & 1U) != 0U);
        state.SetMopConnected((mask & 2U) != 0U);
        state.SetHandlerRegistered((mask & 4U) != 0U);
        Check(state.Snapshot().available() == (mask == 7U),
              "availability must be the exact three-fact conjunction");
    }
}

void TestUnixStatusUploadAndReconnect() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-companion-" + std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";
    FakeMop fake;
    PsdkRouteCompanion companion(Config(socket_path), fake.Api());
    std::string error;
    Check(companion.Start(true, &error), "companion must start after PSDK application start");
    WaitFor([&] { return companion.Snapshot().handler_registered; },
            "MOP handler must register after bind");
    Check(fake.bound_channel == 49154U, "must bind the exact configured MOP channel");

    std::string status = Exchange(socket_path, StatusRequest());
    Check(status.find("\"psdkInitialized\":true") != std::string::npos &&
              status.find("\"mopConnected\":false") != std::string::npos &&
              status.find("\"handlerRegistered\":true") != std::string::npos,
          "liveness and registration alone must not report MOP connected");
    Check(Exchange(socket_path, StatusRequest("wrong-port")) ==
              "{\"error\":\"ROUTE_IDENTITY_MISMATCH\"}\n",
          "wrong subject port must fail closed");
    Check(Exchange(socket_path, "{}\n{}\n") == "{\"error\":\"INVALID_FRAME\"}\n",
          "multiple JSON lines must fail framing");
    Check(Exchange(socket_path, std::string(64U * 1024U + 1U, 'x') + "\n") ==
              "{\"error\":\"INVALID_FRAME\"}\n",
          "request above the configured byte bound must fail");
    Check(Exchange(socket_path, "{not-json}\n") == "{\"error\":\"INVALID_JSON\"}\n",
          "malformed JSON must fail closed");

    MopHandle first = fake.Connect();
    WaitFor([&] { return companion.Snapshot().available(); },
            "first MOP connection must make exact route available");
    status = Exchange(socket_path, StatusRequest());
    Check(status.find("\"mopConnected\":true") != std::string::npos,
          "status must expose a real accepted MOP connection");
    const std::string first_signal_id = SignalId(status);
    const std::string second_signal_id = SignalId(Exchange(socket_path, StatusRequest()));
    Check(first_signal_id != second_signal_id,
          "status requests in one incarnation must have unique signal IDs");
    CheckSignalIdFormat(first_signal_id);
    CheckSignalIdFormat(second_signal_id);
    const std::string receipt = Exchange(socket_path, UploadRequest());
    Check(receipt.find("\"provider_operation_id\":\"psdk-mop-bundle-1\"") !=
              std::string::npos,
          "non-actuating EdgeBundle metadata must receive a typed receipt");
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(fake.sent_frames.size() == 1U &&
                  fake.sent_frames[0].find("\"integrationPath\":\"PSDK_MANIFOLD\"") !=
                      std::string::npos &&
                  fake.sent_frames[0].find("\"subjectPortId\":\"psdk.edge_uplink\"") !=
                      std::string::npos &&
                  fake.sent_frames[0].find("\"canonicalCapabilityId\":\"EDGE_UPLINK\"") !=
                      std::string::npos &&
                  fake.sent_frames[0].find("\"bundleObjectRef\":\"objects/bundle-1.json\"") !=
                      std::string::npos,
              "handler must add exact route identity to the bounded EdgeBundle MOP frame");
    }
    std::string wrong_scope = UploadRequest();
    const std::string exact_scope = "\"organization_id\":\"org-1\"";
    const std::size_t scope_offset = wrong_scope.find(exact_scope);
    Check(scope_offset != std::string::npos, "test request must contain exact organization");
    wrong_scope.replace(scope_offset, exact_scope.size(), "\"organization_id\":\"org-2\"");
    Check(Exchange(socket_path, wrong_scope) ==
              "{\"error\":\"EDGE_BUNDLE_SCOPE_MISMATCH\"}\n",
          "wrong tenant must not reach the MOP channel");

    fake.Disconnect(first);
    WaitFor([&] { return !companion.Snapshot().mop_connected; },
            "MOP close must clear availability");
    Check(Exchange(socket_path, UploadRequest()) == "{\"error\":\"ROUTE_UNAVAILABLE\"}\n",
          "disconnected route must not acknowledge an upload");

    MopHandle second = fake.Connect();
    WaitFor([&] { return companion.Snapshot().available(); },
            "reaccepted MOP channel must restore route availability");
    fake.Disconnect(second);
    WaitFor([&] { return !companion.Snapshot().mop_connected; },
            "second disconnect must clear availability again");

    companion.Stop();
    Check(!std::filesystem::exists(socket_path),
          "deterministic shutdown must remove only its owned stale socket");
    Check(!companion.Snapshot().available(), "shutdown must clear all route facts");
    std::filesystem::remove(directory);
}

void TestSequentialCompanionIncarnationsHaveDifferentSignalIds() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-incarnation-" + std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path socket_path = directory / "psdk.sock";

    std::string first_signal;
    {
        FakeMop fake;
        PsdkRouteCompanion companion(Config(socket_path), fake.Api());
        std::string error;
        Check(companion.Start(true, &error), "first companion incarnation must start");
        WaitFor([&] { return companion.Snapshot().handler_registered; },
                "first companion handler must register");
        first_signal = SignalId(Exchange(socket_path, StatusRequest()));
        companion.Stop();
    }
    std::string second_signal;
    {
        FakeMop fake;
        PsdkRouteCompanion companion(Config(socket_path), fake.Api());
        std::string error;
        Check(companion.Start(true, &error), "second companion incarnation must start");
        WaitFor([&] { return companion.Snapshot().handler_registered; },
                "second companion handler must register");
        second_signal = SignalId(Exchange(socket_path, StatusRequest()));
        companion.Stop();
    }
    Check(first_signal != second_signal,
          "sequential companion incarnations must not repeat signal IDs");
    CheckSignalIdFormat(first_signal);
    CheckSignalIdFormat(second_signal);
    std::filesystem::remove(directory);
}

void TestStartFailsWithoutPsdkInitialization() {
    const std::filesystem::path path =
        std::filesystem::temp_directory_path() / "ksi-psdk-never-created.sock";
    FakeMop fake;
    PsdkRouteCompanion companion(Config(path), fake.Api());
    std::string error;
    Check(!companion.Start(false, &error) && !std::filesystem::exists(path),
          "process configuration alone must not create an available companion");
}

void TestStaleSocketCleanupAndActiveSocketRefusal() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("ksi-psdk-stale-" + std::to_string(static_cast<long long>(getpid())));
    std::filesystem::create_directory(directory);
    const std::filesystem::path path = directory / "psdk.sock";
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    const std::string text = path.string();
    std::memcpy(address.sun_path, text.c_str(), text.size() + 1U);

    int stale = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    Check(stale >= 0 && bind(stale, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) == 0,
          "must create stale Unix socket inode");
    close(stale);
    FakeMop first_fake;
    PsdkRouteCompanion first(Config(path), first_fake.Api());
    std::string error;
    Check(first.Start(true, &error), "owned refused socket must be cleaned as stale");

    FakeMop second_fake;
    PsdkRouteCompanion second(Config(path), second_fake.Api());
    Check(!second.Start(true, &error), "active companion socket must never be unlinked");
    first.Stop();
    Check(!std::filesystem::exists(path), "first owner must clean its socket on shutdown");
    std::filesystem::remove(directory);
}

int RunGatewayInteropFixture(const std::filesystem::path& socket_path, bool available) {
    InteropMop transport;
    PsdkRouteCompanion companion(Config(socket_path), transport.ServerApi());
    std::string error;
    if (!companion.Start(true, &error)) {
        std::fprintf(stderr, "fixture companion start failed: %s\n", error.c_str());
        return 2;
    }
    std::unique_ptr<PsdkMopPeerReceiver> peer;
    if (available) {
        try {
            peer = std::make_unique<PsdkMopPeerReceiver>(
                PsdkMopPeerReceiverConfig{
                    "org-1", "site-1", "edge-1", "psdk.edge_uplink",
                    MopPeerAddress::kPayloadPortNo1, 49154U, 64U * 1024U, 128U,
                    10U, nullptr},
                transport.PeerApi());
            if (!peer->Start(true, &error)) {
                std::fprintf(stderr, "fixture peer start failed: %s\n", error.c_str());
                companion.Stop();
                return 2;
            }
        } catch (const std::exception& exception) {
            std::fprintf(stderr, "fixture peer setup failed: %s\n", exception.what());
            companion.Stop();
            return 2;
        }
    }
    try {
        WaitFor(
            [&] {
                const auto snapshot = companion.Snapshot();
                return available ? snapshot.available()
                                 : snapshot.psdk_initialized &&
                                       snapshot.handler_registered &&
                                       !snapshot.mop_connected;
            },
            "fixture MOP route did not reach requested state");
    } catch (const std::exception& exception) {
        std::fprintf(stderr, "fixture setup failed: %s\n", exception.what());
        companion.Stop();
        return 2;
    }
    std::puts("READY");
    std::fflush(stdout);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (std::chrono::steady_clock::now() < deadline) {
        if (available && peer != nullptr && peer->Snapshot().accepted_frames == 1U) {
            peer->Stop();
            companion.Stop();
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    std::fputs("fixture timed out waiting for Gateway EDGE_BUNDLE_UPLOAD\n", stderr);
    if (peer != nullptr) {
        peer->Stop();
    }
    companion.Stop();
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 4 && std::string(argv[1]) == "--gateway-interop-fixture") {
        const std::string state = argv[3];
        if (state != "available" && state != "unavailable") {
            std::fputs("fixture state must be available or unavailable\n", stderr);
            return 2;
        }
        return RunGatewayInteropFixture(argv[2], state == "available");
    }
    try {
        TestThreeFactTruthTable();
        TestUnixStatusUploadAndReconnect();
        TestStopClosesBlockedSendWithoutExternalRelease();
        TestConnectedCloseCompletesBeforeDestroy();
        TestListenerCloseCompletesBeforeDestroy();
        TestPeerDisconnectDefersDestroyUntilBlockedSendReturns();
        TestSequentialCompanionIncarnationsHaveDifferentSignalIds();
        TestStartFailsWithoutPsdkInitialization();
        TestStaleSocketCleanupAndActiveSocketRefusal();
    } catch (const std::exception& exception) {
        std::fprintf(stderr, "psdk route companion test failed: %s\n", exception.what());
        return 1;
    }
    std::puts("psdk route companion tests passed");
    return 0;
}

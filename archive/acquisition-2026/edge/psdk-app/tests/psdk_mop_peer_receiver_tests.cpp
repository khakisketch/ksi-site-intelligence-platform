#include "runtime/psdk_mop_peer_receiver.hpp"

#include <array>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

using ksi::psdk::EdgeBundleMetadata;
using ksi::psdk::MopPeerAddress;
using ksi::psdk::MopPeerApi;
using ksi::psdk::MopPeerHandle;
using ksi::psdk::MopPeerResult;
using ksi::psdk::PsdkMopPeerReceiver;
using ksi::psdk::PsdkMopPeerReceiverConfig;

constexpr MopPeerResult kSuccess = 0U;
constexpr MopPeerResult kClosed = 11U;
constexpr MopPeerResult kFailure = 99U;

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

struct FakePeerMop {
    struct Connection {
        bool closed = false;
    };

    mutable std::mutex mutex;
    std::condition_variable changed;
    std::vector<std::unique_ptr<Connection>> connections;
    std::deque<std::string> chunks;
    int initialize_calls = 0;
    int create_calls = 0;
    int connect_calls = 0;
    int receive_calls = 0;
    int close_calls = 0;
    int destroy_calls = 0;
    int create_failures_remaining = 0;
    int connect_failures_remaining = 0;
    int receive_failures_remaining = 0;
    bool initialize_succeeds = true;
    bool block_connect = false;
    bool connect_entered = false;
    MopPeerAddress address = MopPeerAddress::kUnknown;
    std::uint16_t channel_id = 0U;
    MopPeerHandle active = nullptr;

    void AddChunks(const std::string& frame, std::initializer_list<std::size_t> sizes) {
        std::lock_guard<std::mutex> lock(mutex);
        std::size_t offset = 0U;
        for (const std::size_t size : sizes) {
            Check(size > 0U && offset + size <= frame.size(), "invalid fake partial receive size");
            chunks.push_back(frame.substr(offset, size));
            offset += size;
        }
        if (offset < frame.size()) {
            chunks.push_back(frame.substr(offset));
        }
        changed.notify_all();
    }

    void AddOversizeFrame() {
        const std::string frame(64U * 1024U + 1U, 'x');
        std::lock_guard<std::mutex> lock(mutex);
        for (std::size_t offset = 0U; offset < frame.size(); offset += 4096U) {
            chunks.push_back(frame.substr(offset, 4096U));
        }
        chunks.push_back("\n");
        changed.notify_all();
    }

    void DisconnectActive() {
        std::lock_guard<std::mutex> lock(mutex);
        Check(active != nullptr, "fake must have a connected peer to disconnect");
        static_cast<Connection*>(active)->closed = true;
        changed.notify_all();
    }

    int ConnectCalls() const {
        std::lock_guard<std::mutex> lock(mutex);
        return connect_calls;
    }

    bool ConnectEntered() const {
        std::lock_guard<std::mutex> lock(mutex);
        return connect_entered;
    }

    MopPeerApi Api() {
        MopPeerApi api;
        api.success = kSuccess;
        api.connection_closed = kClosed;
        api.initialize = [this] {
            std::lock_guard<std::mutex> lock(mutex);
            ++initialize_calls;
            return initialize_succeeds ? kSuccess : kFailure;
        };
        api.create_reliable = [this](MopPeerHandle* output) {
            std::lock_guard<std::mutex> lock(mutex);
            ++create_calls;
            if (create_failures_remaining > 0) {
                --create_failures_remaining;
                *output = nullptr;
                return kFailure;
            }
            connections.push_back(std::make_unique<Connection>());
            *output = connections.back().get();
            return kSuccess;
        };
        api.connect = [this](MopPeerHandle handle, MopPeerAddress configured_address,
                             std::uint16_t configured_channel) {
            std::unique_lock<std::mutex> lock(mutex);
            ++connect_calls;
            if (connect_failures_remaining > 0) {
                --connect_failures_remaining;
                return kFailure;
            }
            address = configured_address;
            channel_id = configured_channel;
            active = handle;
            if (block_connect) {
                connect_entered = true;
                changed.notify_all();
                auto* connection = static_cast<Connection*>(handle);
                changed.wait(lock, [connection] { return connection->closed; });
                return kClosed;
            }
            changed.notify_all();
            return kSuccess;
        };
        api.receive = [this](MopPeerHandle handle, std::uint8_t* data, std::uint32_t size,
                             std::uint32_t* received) {
            std::unique_lock<std::mutex> lock(mutex);
            ++receive_calls;
            auto* connection = static_cast<Connection*>(handle);
            changed.wait(lock, [this, connection] {
                return connection->closed || receive_failures_remaining > 0 || !chunks.empty();
            });
            if (connection->closed) {
                *received = 0U;
                return kClosed;
            }
            if (receive_failures_remaining > 0) {
                --receive_failures_remaining;
                *received = 0U;
                return kFailure;
            }
            const std::string chunk = std::move(chunks.front());
            chunks.pop_front();
            if (chunk.size() > size) {
                *received = 0U;
                return kFailure;
            }
            std::memcpy(data, chunk.data(), chunk.size());
            *received = static_cast<std::uint32_t>(chunk.size());
            return kSuccess;
        };
        api.close = [this](MopPeerHandle handle) {
            std::lock_guard<std::mutex> lock(mutex);
            ++close_calls;
            static_cast<Connection*>(handle)->closed = true;
            changed.notify_all();
            return kSuccess;
        };
        api.destroy = [this](MopPeerHandle) {
            std::lock_guard<std::mutex> lock(mutex);
            ++destroy_calls;
            return kSuccess;
        };
        return api;
    }

    void FailNextReceive() {
        std::lock_guard<std::mutex> lock(mutex);
        ++receive_failures_remaining;
        changed.notify_all();
    }
};

PsdkMopPeerReceiverConfig Config(std::vector<EdgeBundleMetadata>* accepted = nullptr,
                                 std::mutex* accepted_mutex = nullptr) {
    PsdkMopPeerReceiverConfig config{"org-1", "site-1", "edge-1", "psdk.edge_uplink",
                                      MopPeerAddress::kPayloadPortNo1, 49154U,
                                      64U * 1024U, 128U, 100U, nullptr};
    config.reconnect_delay_ms = 10U;
    if (accepted != nullptr && accepted_mutex != nullptr) {
        config.accepted_metadata_sink = [accepted, accepted_mutex](const EdgeBundleMetadata& metadata) {
            std::lock_guard<std::mutex> lock(*accepted_mutex);
            accepted->push_back(metadata);
        };
    }
    return config;
}

std::string ExistingRouteFrame(std::string idempotency_key = "bundle-1",
                               std::string object_ref = "objects/bundle-1.json") {
    return "{\"canonicalCapabilityId\":\"EDGE_UPLINK\",\"edgeDeviceId\":\"edge-1\","
           "\"idempotencyKey\":\"" +
           idempotency_key + "\",\"integrationPath\":\"PSDK_MANIFOLD\","
                             "\"operation\":\"EDGE_BUNDLE_UPLOAD\",\"payload\":{"
                             "\"bundleObjectRef\":\"" +
           object_ref + "\",\"bundleSha256\":\""
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
                        "\"missionId\":\"mission-1\",\"organizationId\":\"org-1\","
                        "\"siteId\":\"site-1\"},\"schemaVersion\":\"1.0\","
                        "\"subjectPortId\":\"psdk.edge_uplink\"}\n";
}

void TestApprovedPsdkAddressAndReconnect() {
    FakePeerMop fake;
    fake.connect_failures_remaining = 1;
    std::vector<EdgeBundleMetadata> accepted;
    std::mutex accepted_mutex;
    PsdkMopPeerReceiver receiver(Config(&accepted, &accepted_mutex), fake.Api());
    Check(!receiver.mop_connected() && fake.ConnectCalls() == 0,
          "receiver construction must not synthesize a MOP connection");
    std::string error;
    Check(!receiver.Start(false, &error) && fake.ConnectCalls() == 0,
          "receiver must not initialize before DjiCore_ApplicationStart");
    Check(receiver.Start(true, &error), "receiver worker must start after application start");
    WaitFor([&] { return fake.ConnectCalls() >= 2 && receiver.mop_connected(); },
            "failed initial Connect must retry before becoming connected");
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(fake.address == MopPeerAddress::kPayloadPortNo1 && fake.channel_id == 49154U,
              "client must target the configured PSDK companion address and channel");
    }

    fake.AddChunks(ExistingRouteFrame(), {1U, 17U, 31U});
    WaitFor([&] {
                if (receiver.Snapshot().accepted_frames != 1U) {
                    return false;
                }
                std::lock_guard<std::mutex> lock(accepted_mutex);
                return accepted.size() == 1U;
            },
            "partial receives must deliver exactly one validated metadata record");
    {
        std::lock_guard<std::mutex> lock(accepted_mutex);
        Check(accepted.size() == 1U && accepted.front().bundle_object_ref == "objects/bundle-1.json",
              "safe sink must observe metadata only after exact validation");
    }

    fake.DisconnectActive();
    WaitFor([&] { return fake.ConnectCalls() >= 3 && receiver.mop_connected(); },
            "peer disconnect must release, reconnect, and restore connected state");
    fake.AddChunks(ExistingRouteFrame(), {9U});
    WaitFor([&] { return receiver.Snapshot().duplicate_frames == 1U; },
            "idempotency state must remain deterministic across reconnect");

    fake.AddChunks(ExistingRouteFrame("bundle-1", "objects/changed-bundle.json"), {13U});
    WaitFor([&] { return receiver.Snapshot().rejected_frames == 1U; },
            "same provider operation ID with changed payload must be an idempotency conflict");
    {
        std::lock_guard<std::mutex> lock(accepted_mutex);
        Check(accepted.size() == 1U,
              "duplicate or conflicting metadata must not re-enter the safe sink");
    }

    receiver.Stop();
    const auto snapshot = receiver.Snapshot();
    Check(!snapshot.psdk_initialized && !snapshot.mop_connected,
          "shutdown must clear PSDK and MOP state before owner teardown");

    Check(receiver.Start(true, &error), "Stop followed by Start is an explicitly supported lifecycle");
    WaitFor([&] { return receiver.mop_connected(); },
            "restarted receiver must establish a new connection");
    fake.AddChunks(ExistingRouteFrame(), {7U});
    WaitFor([&] { return receiver.Snapshot().duplicate_frames == 2U; },
            "restart must preserve the bounded idempotency record");
    receiver.Stop();
}

void TestCreateAndNonCloseReceiveFailuresReconnect() {
    FakePeerMop fake;
    fake.create_failures_remaining = 1;
    PsdkMopPeerReceiver receiver(Config(), fake.Api());
    std::string error;
    Check(receiver.Start(true, &error), "receiver must start before controlled Create failure");
    WaitFor([&] { return fake.ConnectCalls() >= 1 && receiver.mop_connected(); },
            "Create failure must be retried without manufacturing a connection");
    {
        std::lock_guard<std::mutex> lock(fake.mutex);
        Check(fake.create_calls >= 2,
              "a failed DjiMopChannel_Create must lead to a fresh Create attempt");
    }

    const int connected_before = fake.ConnectCalls();
    fake.FailNextReceive();
    WaitFor([&] {
                return receiver.Snapshot().transport_disconnects >= 1U &&
                       fake.ConnectCalls() > connected_before && receiver.mop_connected();
            },
            "non-close RecvData transport failure must release and reconnect");
    receiver.Stop();
}

void TestHostileFramesAndBlockingShutdown() {
    FakePeerMop fake;
    PsdkMopPeerReceiver receiver(Config(), fake.Api());
    std::string error;
    Check(receiver.Start(true, &error), "receiver must start for hostile frame checks");
    WaitFor([&] { return receiver.mop_connected(); }, "receiver must connect for hostile frame checks");

    fake.AddChunks("{\"schemaVersion\":\"1.0\",\"schemaVersion\":\"1.0\"}\n", {5U});
    struct Rejection {
        const char* expected;
        const char* replacement;
    };
    const std::array<Rejection, 7U> rejections{{
        {"\"schemaVersion\":\"1.0\"", "\"schemaVersion\":\"2.0\""},
        {"\"operation\":\"EDGE_BUNDLE_UPLOAD\"", "\"operation\":\"OTHER\""},
        {"\"integrationPath\":\"PSDK_MANIFOLD\"", "\"integrationPath\":\"OTHER\""},
        {"\"canonicalCapabilityId\":\"EDGE_UPLINK\"", "\"canonicalCapabilityId\":\"OTHER\""},
        {"\"subjectPortId\":\"psdk.edge_uplink\"", "\"subjectPortId\":\"wrong-port\""},
        {"\"organizationId\":\"org-1\"", "\"organizationId\":\"org-2\""},
        {"\"siteId\":\"site-1\"", "\"siteId\":\"site-2\""},
    }};
    for (const Rejection& rejection : rejections) {
        std::string frame = ExistingRouteFrame();
        const std::size_t offset = frame.find(rejection.expected);
        Check(offset != std::string::npos, "fixture must contain each exact field");
        frame.replace(offset, std::strlen(rejection.expected), rejection.replacement);
        fake.AddChunks(frame, {21U});
    }
    fake.AddOversizeFrame();
    WaitFor([&] { return receiver.Snapshot().rejected_frames >= 9U; },
            "malformed, wrong-schema, wrong-identity, and oversize frames must all reject");

    const auto started = std::chrono::steady_clock::now();
    receiver.Stop();
    Check(std::chrono::steady_clock::now() - started < std::chrono::seconds(1),
          "Stop must close and unblock a blocking RecvData before returning");
    std::lock_guard<std::mutex> lock(fake.mutex);
    Check(fake.close_calls >= 1 && fake.destroy_calls >= 1,
          "shutdown must close and destroy the connected client handle");
}

void TestInitFailureAndBlockingConnectShutdown() {
    {
        FakePeerMop fake;
        fake.initialize_succeeds = false;
        PsdkMopPeerReceiver receiver(Config(), fake.Api());
        std::string error;
        Check(!receiver.Start(true, &error) && !receiver.Snapshot().psdk_initialized &&
                  fake.ConnectCalls() == 0,
              "DjiMopChannel_Init failure must fail Start before creating a worker or client");
    }

    FakePeerMop fake;
    fake.block_connect = true;
    PsdkMopPeerReceiver receiver(Config(), fake.Api());
    std::string error;
    Check(receiver.Start(true, &error), "receiver must start before the controlled blocking Connect");
    WaitFor([&] { return fake.ConnectEntered(); },
            "test must observe DjiMopChannel_Connect after its handle is published");
    Check(!receiver.mop_connected(),
          "a published but still-blocking Connect must not synthesize mopConnected");
    const auto started = std::chrono::steady_clock::now();
    receiver.Stop();
    Check(std::chrono::steady_clock::now() - started < std::chrono::seconds(1),
          "Stop must close a published connecting handle and unblock Connect");
    std::lock_guard<std::mutex> lock(fake.mutex);
    Check(fake.close_calls == 1 && fake.destroy_calls == 1,
          "blocked Connect shutdown must close once and leave Destroy ownership to the worker");
}

}  // namespace

int main() {
    try {
        TestApprovedPsdkAddressAndReconnect();
        TestCreateAndNonCloseReceiveFailuresReconnect();
        TestHostileFramesAndBlockingShutdown();
        TestInitFailureAndBlockingConnectShutdown();
    } catch (const std::exception& exception) {
        std::fprintf(stderr, "psdk MOP peer receiver test failed: %s\n", exception.what());
        return 1;
    }
    std::puts("psdk MOP peer receiver tests passed");
    return 0;
}

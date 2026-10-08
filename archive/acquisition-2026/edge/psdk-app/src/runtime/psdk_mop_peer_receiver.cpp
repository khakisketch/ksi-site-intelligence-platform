#include "runtime/psdk_mop_peer_receiver.hpp"

#include <dji_error.h>
#include <dji_mop_channel.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cstring>
#include <limits>
#include <map>
#include <stdexcept>
#include <utility>

namespace ksi::psdk {
namespace {

constexpr std::size_t kMaximumJsonDepth = 3U;
constexpr std::size_t kMaximumIdentifierBytes = 200U;
constexpr std::size_t kMaximumObjectReferenceBytes = 4096U;
constexpr std::size_t kMaximumFrameBytes = 64U * 1024U;
constexpr std::size_t kMaximumIdempotencyRecords = 1024U;

MopPeerResult DjiInitialize() { return DjiMopChannel_Init(); }

MopPeerResult DjiCreateReliable(MopPeerHandle* output) {
    return DjiMopChannel_Create(output, DJI_MOP_CHANNEL_TRANS_RELIABLE);
}

MopPeerResult DjiConnect(MopPeerHandle handle, MopPeerAddress address,
                         std::uint16_t channel_id) {
    return DjiMopChannel_Connect(handle, static_cast<E_DjiChannelAddress>(address), channel_id);
}

MopPeerResult DjiReceive(MopPeerHandle handle, std::uint8_t* data, std::uint32_t size,
                         std::uint32_t* received) {
    return DjiMopChannel_RecvData(handle, data, size, received);
}

MopPeerResult DjiClose(MopPeerHandle handle) { return DjiMopChannel_Close(handle); }
MopPeerResult DjiDestroy(MopPeerHandle handle) { return DjiMopChannel_Destroy(handle); }

bool IsIdentifier(const std::string& value) {
    if (value.empty() || value.size() > kMaximumIdentifierBytes ||
        !std::isalnum(static_cast<unsigned char>(value.front()))) {
        return false;
    }
    return std::all_of(value.begin() + 1, value.end(), [](char character) {
        const auto value = static_cast<unsigned char>(character);
        return std::isalnum(value) || character == '_' || character == '.' || character == '-';
    });
}

bool IsSha256(const std::string& value) {
    return value.size() == 64U &&
           std::all_of(value.begin(), value.end(), [](char character) {
               return (character >= '0' && character <= '9') ||
                      (character >= 'a' && character <= 'f');
           });
}

bool IsObjectReference(const std::string& value) {
    return !value.empty() && value.size() <= kMaximumObjectReferenceBytes &&
           value.find_first_not_of(" \t\r\n") != std::string::npos &&
           value.find('?') == std::string::npos && value.find('#') == std::string::npos &&
           std::none_of(value.begin(), value.end(), [](char character) {
               return static_cast<unsigned char>(character) < 0x20U;
           });
}

bool IsApprovedPsdkServerAddress(MopPeerAddress address) {
    const auto numeric = static_cast<std::uint32_t>(address);
    return numeric >= static_cast<std::uint32_t>(MopPeerAddress::kPayloadPortNo1) &&
           numeric <= static_cast<std::uint32_t>(MopPeerAddress::kExtensionPort);
}

enum class JsonType { kNull, kBoolean, kNumber, kString, kObject };

struct JsonValue {
    JsonType type = JsonType::kNull;
    std::string scalar;
    std::map<std::string, JsonValue> object;
};

class JsonParser final {
public:
    explicit JsonParser(const std::string& input) : input_(input) {}

    bool Parse(JsonValue* output) {
        SkipWhitespace();
        if (!ParseValue(output, 0U)) {
            return false;
        }
        SkipWhitespace();
        return position_ == input_.size();
    }

private:
    bool ParseValue(JsonValue* output, std::size_t depth) {
        if (output == nullptr || depth > kMaximumJsonDepth || position_ >= input_.size()) {
            return false;
        }
        if (input_[position_] == '{') {
            return ParseObject(output, depth);
        }
        if (input_[position_] == '"') {
            output->type = JsonType::kString;
            return ParseString(&output->scalar);
        }
        if (Consume("true") || Consume("false") || Consume("null")) {
            return false;
        }
        return false;
    }

    bool ParseObject(JsonValue* output, std::size_t depth) {
        if (input_[position_++] != '{') {
            return false;
        }
        output->type = JsonType::kObject;
        output->object.clear();
        SkipWhitespace();
        if (position_ < input_.size() && input_[position_] == '}') {
            ++position_;
            return true;
        }
        while (position_ < input_.size()) {
            std::string key;
            if (!ParseString(&key)) {
                return false;
            }
            SkipWhitespace();
            if (position_ >= input_.size() || input_[position_++] != ':') {
                return false;
            }
            SkipWhitespace();
            JsonValue child;
            if (!ParseValue(&child, depth + 1U) ||
                !output->object.emplace(std::move(key), std::move(child)).second) {
                return false;
            }
            SkipWhitespace();
            if (position_ >= input_.size()) {
                return false;
            }
            const char separator = input_[position_++];
            if (separator == '}') {
                return true;
            }
            if (separator != ',') {
                return false;
            }
            SkipWhitespace();
        }
        return false;
    }

    bool ParseString(std::string* output) {
        if (output == nullptr || position_ >= input_.size() || input_[position_++] != '"') {
            return false;
        }
        output->clear();
        while (position_ < input_.size()) {
            const unsigned char character = static_cast<unsigned char>(input_[position_++]);
            if (character == '"') {
                return true;
            }
            if (character < 0x20U) {
                return false;
            }
            if (character != '\\') {
                output->push_back(static_cast<char>(character));
                continue;
            }
            if (position_ >= input_.size()) {
                return false;
            }
            const char escaped = input_[position_++];
            switch (escaped) {
                case '"': output->push_back('"'); break;
                case '\\': output->push_back('\\'); break;
                case '/': output->push_back('/'); break;
                case 'b': output->push_back('\b'); break;
                case 'f': output->push_back('\f'); break;
                case 'n': output->push_back('\n'); break;
                case 'r': output->push_back('\r'); break;
                case 't': output->push_back('\t'); break;
                default:
                    // Identity-bearing fields intentionally reject Unicode
                    // normalization ambiguities rather than decoding them.
                    return false;
            }
        }
        return false;
    }

    bool Consume(const char* token) {
        const std::size_t size = std::strlen(token);
        if (input_.compare(position_, size, token) != 0) {
            return false;
        }
        position_ += size;
        return true;
    }

    void SkipWhitespace() {
        while (position_ < input_.size() &&
               (input_[position_] == ' ' || input_[position_] == '\t' ||
                input_[position_] == '\r' || input_[position_] == '\n')) {
            ++position_;
        }
    }

    const std::string& input_;
    std::size_t position_ = 0U;
};

bool ExactFields(const JsonValue& value, std::initializer_list<const char*> fields) {
    if (value.type != JsonType::kObject || value.object.size() != fields.size()) {
        return false;
    }
    return std::all_of(fields.begin(), fields.end(), [&](const char* field) {
        return value.object.find(field) != value.object.end();
    });
}

const std::string* StringField(const JsonValue& value, const char* field) {
    if (value.type != JsonType::kObject) {
        return nullptr;
    }
    const auto found = value.object.find(field);
    return found != value.object.end() && found->second.type == JsonType::kString
               ? &found->second.scalar
               : nullptr;
}

}  // namespace

MopPeerApi DjiMopPeerApi() {
    return MopPeerApi{DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS,
                      DJI_ERROR_MOP_CHANNEL_MODULE_CODE_CONNECTION_CLOSE,
                      DjiInitialize,
                      DjiCreateReliable,
                      DjiConnect,
                      DjiReceive,
                      DjiClose,
                      DjiDestroy};
}

bool EdgeBundleMetadata::operator==(const EdgeBundleMetadata& other) const noexcept {
    return organization_id == other.organization_id && site_id == other.site_id &&
           mission_id == other.mission_id && edge_device_id == other.edge_device_id &&
           bundle_object_ref == other.bundle_object_ref && bundle_sha256 == other.bundle_sha256 &&
           idempotency_key == other.idempotency_key;
}

PsdkMopPeerReceiver::PsdkMopPeerReceiver(PsdkMopPeerReceiverConfig config, MopPeerApi api)
    : config_(std::move(config)), api_(std::move(api)) {
    if (!IsIdentifier(config_.organization_id) || !IsIdentifier(config_.site_id) ||
        !IsIdentifier(config_.edge_device_id) || !IsIdentifier(config_.subject_port_id) ||
        config_.organization_id == "legacy" || !IsApprovedPsdkServerAddress(config_.peer_address) ||
        config_.mop_channel_id == 0U || config_.maximum_frame_bytes == 0U ||
        config_.maximum_frame_bytes > kMaximumFrameBytes || config_.idempotency_capacity == 0U ||
        config_.idempotency_capacity > kMaximumIdempotencyRecords ||
        config_.reconnect_delay_ms < 10U || config_.reconnect_delay_ms > 10'000U) {
        throw std::invalid_argument("PSDK MOP peer receiver configuration is not exact and bounded");
    }
    if (!api_.initialize || !api_.create_reliable || !api_.connect || !api_.receive || !api_.close ||
        !api_.destroy) {
        throw std::invalid_argument("PSDK MOP peer client API table is incomplete");
    }
}

PsdkMopPeerReceiver::~PsdkMopPeerReceiver() { Stop(); }

bool PsdkMopPeerReceiver::Start(bool psdk_initialized, std::string* error) {
    if (!psdk_initialized) {
        if (error != nullptr) {
            *error = "DjiCore_ApplicationStart has not succeeded";
        }
        return false;
    }
    std::lock_guard<std::mutex> lock(state_mutex_);
    if (started_) {
        if (error != nullptr) {
            *error = "PSDK MOP peer receiver was already started";
        }
        return false;
    }
    if (api_.initialize() != api_.success) {
        snapshot_.psdk_initialized = false;
        if (error != nullptr) {
            *error = "DjiMopChannel_Init failed";
        }
        return false;
    }
    pending_bytes_.clear();
    started_ = true;
    stopping_ = false;
    snapshot_.psdk_initialized = true;
    try {
        receive_thread_ = std::thread(&PsdkMopPeerReceiver::ReceiveLoop, this);
    } catch (...) {
        started_ = false;
        snapshot_.psdk_initialized = false;
        if (error != nullptr) {
            *error = "unable to start PSDK MOP peer receive worker";
        }
        return false;
    }
    return true;
}

void PsdkMopPeerReceiver::Stop() {
    MopPeerHandle channel = nullptr;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (!started_) {
            return;
        }
        stopping_ = true;
        snapshot_.mop_connected = false;
        channel = channel_handle_;
        if (channel != nullptr && !close_requested_) {
            close_requested_ = true;
            // Close is the vendored mechanism that unblocks a concurrent
            // RecvData. Keep the handle ownership lock while issuing it so the
            // worker cannot destroy this handle concurrently.
            (void)api_.close(channel);
        }
    }
    retry_cv_.notify_all();
    if (receive_thread_.joinable()) {
        receive_thread_.join();
    }
    std::lock_guard<std::mutex> lock(state_mutex_);
    started_ = false;
    stopping_ = false;
    snapshot_.psdk_initialized = false;
    snapshot_.mop_connected = false;
    pending_bytes_.clear();
}

bool PsdkMopPeerReceiver::mop_connected() const noexcept {
    std::lock_guard<std::mutex> lock(state_mutex_);
    return snapshot_.mop_connected;
}

MopPeerSnapshot PsdkMopPeerReceiver::Snapshot() const {
    std::lock_guard<std::mutex> lock(state_mutex_);
    return snapshot_;
}

void PsdkMopPeerReceiver::ReceiveLoop() {
    while (true) {
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            if (stopping_) {
                break;
            }
        }
        if (!ConnectOnce()) {
            if (!WaitForRetry()) {
                break;
            }
            continue;
        }
        while (true) {
            MopPeerHandle channel = nullptr;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                if (stopping_ || channel_handle_ == nullptr) {
                    break;
                }
                channel = channel_handle_;
            }
            const MopPeerReceiveResult result = ReceiveNext(channel);
            Record(result.verdict);
            if (result.verdict == MopPeerReceiveVerdict::kAccepted &&
                config_.accepted_metadata_sink) {
                try {
                    config_.accepted_metadata_sink(result.metadata);
                } catch (...) {
                    // The receiver never turns a metadata observer failure into
                    // a device action or a retry of an accepted frame.
                }
            }
            if (result.verdict == MopPeerReceiveVerdict::kDisconnected ||
                result.verdict == MopPeerReceiveVerdict::kTransportFailure) {
                break;
            }
        }
        if (!WaitForRetry()) {
            break;
        }
    }
}

bool PsdkMopPeerReceiver::ConnectOnce() {
    MopPeerHandle created = nullptr;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (stopping_) {
            return false;
        }
        ++snapshot_.connect_attempts;
    }
    if (api_.create_reliable(&created) != api_.success || created == nullptr) {
        return false;
    }
    bool release = false;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (stopping_) {
            release = true;
        } else {
            // Publish ownership before the potentially blocking vendor Connect
            // call. This deliberately does not set mop_connected: only a
            // successful Connect below does that. Stop can now Close this
            // handle to release Connect, while this worker remains its sole
            // Destroy owner.
            channel_handle_ = created;
            close_requested_ = false;
            pending_bytes_.clear();
        }
    }
    if (release) {
        (void)api_.close(created);
        (void)api_.destroy(created);
        return false;
    }
    const MopPeerResult connected =
        api_.connect(created, config_.peer_address, config_.mop_channel_id);
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (channel_handle_ == created && connected == api_.success && !stopping_ &&
            !close_requested_) {
            snapshot_.mop_connected = true;
            return true;
        }
    }
    ReleaseChannel(created);
    return false;
}

MopPeerReceiveResult PsdkMopPeerReceiver::ReceiveNext(MopPeerHandle handle) {
    if (handle == nullptr) {
        return MopPeerReceiveResult{MopPeerReceiveVerdict::kDisconnected, {}};
    }
    while (true) {
        const std::size_t newline = pending_bytes_.find('\n');
        if (newline != std::string::npos) {
            std::string frame = pending_bytes_.substr(0U, newline);
            pending_bytes_.erase(0U, newline + 1U);
            if (frame.size() > config_.maximum_frame_bytes) {
                return MopPeerReceiveResult{MopPeerReceiveVerdict::kOversizeFrame, {}};
            }
            return ValidateFrame(frame);
        }
        if (pending_bytes_.size() > config_.maximum_frame_bytes) {
            pending_bytes_.clear();
            return MopPeerReceiveResult{MopPeerReceiveVerdict::kOversizeFrame, {}};
        }
        std::array<std::uint8_t, 4096U> received_bytes{};
        std::uint32_t received = 0U;
        const MopPeerResult result = api_.receive(
            handle, received_bytes.data(), static_cast<std::uint32_t>(received_bytes.size()),
            &received);
        if (result != api_.success || received == 0U || received > received_bytes.size()) {
            const MopPeerReceiveVerdict verdict =
                result == api_.connection_closed ? MopPeerReceiveVerdict::kDisconnected
                                                 : MopPeerReceiveVerdict::kTransportFailure;
            ReleaseChannel(handle);
            return MopPeerReceiveResult{verdict, {}};
        }
        pending_bytes_.append(reinterpret_cast<const char*>(received_bytes.data()), received);
    }
}

MopPeerReceiveResult PsdkMopPeerReceiver::ValidateFrame(const std::string& frame) {
    JsonValue root;
    if (frame.empty() || !JsonParser(frame).Parse(&root) ||
        !ExactFields(root, {"schemaVersion", "operation", "integrationPath",
                            "canonicalCapabilityId", "subjectPortId", "edgeDeviceId",
                            "idempotencyKey", "payload"})) {
        return MopPeerReceiveResult{MopPeerReceiveVerdict::kMalformedFrame, {}};
    }
    const auto payload_it = root.object.find("payload");
    if (payload_it == root.object.end() ||
        !ExactFields(payload_it->second,
                     {"bundleObjectRef", "bundleSha256", "missionId", "organizationId",
                      "siteId"})) {
        return MopPeerReceiveResult{MopPeerReceiveVerdict::kMalformedFrame, {}};
    }
    const std::string* schema_version = StringField(root, "schemaVersion");
    const std::string* operation = StringField(root, "operation");
    const std::string* integration_path = StringField(root, "integrationPath");
    const std::string* capability = StringField(root, "canonicalCapabilityId");
    const std::string* subject_port = StringField(root, "subjectPortId");
    const std::string* edge_device = StringField(root, "edgeDeviceId");
    const std::string* idempotency_key = StringField(root, "idempotencyKey");
    const std::string* organization = StringField(payload_it->second, "organizationId");
    const std::string* site = StringField(payload_it->second, "siteId");
    const std::string* mission = StringField(payload_it->second, "missionId");
    const std::string* object_ref = StringField(payload_it->second, "bundleObjectRef");
    const std::string* digest = StringField(payload_it->second, "bundleSha256");
    if (schema_version == nullptr || *schema_version != "1.0" || operation == nullptr ||
        *operation != "EDGE_BUNDLE_UPLOAD" || integration_path == nullptr ||
        *integration_path != "PSDK_MANIFOLD" || capability == nullptr || *capability != "EDGE_UPLINK" ||
        subject_port == nullptr || edge_device == nullptr || idempotency_key == nullptr ||
        organization == nullptr || site == nullptr || mission == nullptr || object_ref == nullptr ||
        digest == nullptr || !IsIdentifier(*idempotency_key) || !IsIdentifier(*mission) ||
        !IsObjectReference(*object_ref) || !IsSha256(*digest)) {
        return MopPeerReceiveResult{MopPeerReceiveVerdict::kMalformedFrame, {}};
    }
    if (*subject_port != config_.subject_port_id || *edge_device != config_.edge_device_id ||
        *organization != config_.organization_id || *site != config_.site_id) {
        return MopPeerReceiveResult{MopPeerReceiveVerdict::kIdentityMismatch, {}};
    }
    EdgeBundleMetadata metadata{*organization, *site, *mission, *edge_device, *object_ref, *digest,
                                *idempotency_key};
    const auto existing = idempotency_records_.find(metadata.idempotency_key);
    if (existing != idempotency_records_.end()) {
        return MopPeerReceiveResult{existing->second == metadata
                                        ? MopPeerReceiveVerdict::kDuplicate
                                        : MopPeerReceiveVerdict::kIdempotencyConflict,
                                    existing->second};
    }
    if (idempotency_records_.size() >= config_.idempotency_capacity) {
        // Ordered eviction is deterministic. This is a bounded hardware slice,
        // not a durable execution journal or authority record.
        idempotency_records_.erase(idempotency_records_.begin());
    }
    idempotency_records_.emplace(metadata.idempotency_key, metadata);
    return MopPeerReceiveResult{MopPeerReceiveVerdict::kAccepted, metadata};
}

void PsdkMopPeerReceiver::ReleaseChannel(MopPeerHandle handle) {
    if (handle == nullptr) {
        return;
    }
    bool close = false;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (channel_handle_ != handle) {
            return;
        }
        close = !close_requested_;
        channel_handle_ = nullptr;
        close_requested_ = false;
        snapshot_.mop_connected = false;
    }
    if (close) {
        (void)api_.close(handle);
    }
    (void)api_.destroy(handle);
}

bool PsdkMopPeerReceiver::WaitForRetry() {
    std::unique_lock<std::mutex> lock(state_mutex_);
    if (stopping_) {
        return false;
    }
    return !retry_cv_.wait_for(lock, std::chrono::milliseconds(config_.reconnect_delay_ms),
                               [this] { return stopping_; });
}

void PsdkMopPeerReceiver::Record(MopPeerReceiveVerdict verdict) {
    std::lock_guard<std::mutex> lock(state_mutex_);
    switch (verdict) {
        case MopPeerReceiveVerdict::kAccepted: ++snapshot_.accepted_frames; break;
        case MopPeerReceiveVerdict::kDuplicate: ++snapshot_.duplicate_frames; break;
        case MopPeerReceiveVerdict::kDisconnected:
        case MopPeerReceiveVerdict::kTransportFailure: ++snapshot_.transport_disconnects; break;
        case MopPeerReceiveVerdict::kIdempotencyConflict:
        case MopPeerReceiveVerdict::kMalformedFrame:
        case MopPeerReceiveVerdict::kOversizeFrame:
        case MopPeerReceiveVerdict::kIdentityMismatch: ++snapshot_.rejected_frames; break;
    }
}

}  // namespace ksi::psdk

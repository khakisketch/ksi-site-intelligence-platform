#include "runtime/psdk_route_companion.hpp"

#include <dji_error.h>
#include <dji_mop_channel.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <ctime>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <utility>

#include <poll.h>
#include <sys/socket.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

namespace ksi::psdk {
namespace {

constexpr std::size_t kMaximumJsonDepth = 4U;
constexpr std::size_t kMaximumIdentifierBytes = 200U;
constexpr std::size_t kMaximumObjectReferenceBytes = 4096U;
constexpr std::chrono::milliseconds kAcceptRetry{200};

MopResult DjiInitialize() { return DjiMopChannel_Init(); }

MopResult DjiCreateReliable(MopHandle* output) {
    return DjiMopChannel_Create(output, DJI_MOP_CHANNEL_TRANS_RELIABLE);
}

MopResult DjiBind(MopHandle handle, std::uint16_t channel_id) {
    return DjiMopChannel_Bind(handle, channel_id);
}

MopResult DjiAccept(MopHandle handle, MopHandle* output) {
    return DjiMopChannel_Accept(handle, output);
}

MopResult DjiClose(MopHandle handle) { return DjiMopChannel_Close(handle); }
MopResult DjiDestroy(MopHandle handle) { return DjiMopChannel_Destroy(handle); }

MopResult DjiSend(MopHandle handle, std::uint8_t* data, std::uint32_t size,
                  std::uint32_t* sent) {
    return DjiMopChannel_SendData(handle, data, size, sent);
}

MopResult DjiReceive(MopHandle handle, std::uint8_t* data, std::uint32_t size,
                     std::uint32_t* received) {
    return DjiMopChannel_RecvData(handle, data, size, received);
}

bool IsIdentifier(const std::string& value) {
    if (value.empty() || value.size() > kMaximumIdentifierBytes ||
        !std::isalnum(static_cast<unsigned char>(value.front()))) {
        return false;
    }
    return std::all_of(value.begin() + 1, value.end(), [](char character) {
        const auto value = static_cast<unsigned char>(character);
        return std::isalnum(value) || character == '_' || character == '.' ||
               character == '-';
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

std::string EscapeJson(const std::string& value) {
    std::string output;
    output.reserve(value.size() + 8U);
    for (const unsigned char character : value) {
        switch (character) {
            case '"': output += "\\\""; break;
            case '\\': output += "\\\\"; break;
            case '\b': output += "\\b"; break;
            case '\f': output += "\\f"; break;
            case '\n': output += "\\n"; break;
            case '\r': output += "\\r"; break;
            case '\t': output += "\\t"; break;
            default:
                if (character < 0x20U) {
                    char escaped[7]{};
                    std::snprintf(escaped, sizeof(escaped), "\\u%04x", character);
                    output += escaped;
                } else {
                    output.push_back(static_cast<char>(character));
                }
        }
    }
    return output;
}

enum class JsonType { kNull, kBoolean, kNumber, kString, kObject };

struct JsonValue {
    JsonType type = JsonType::kNull;
    bool boolean = false;
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
        if (Consume("true")) {
            output->type = JsonType::kBoolean;
            output->boolean = true;
            return true;
        }
        if (Consume("false")) {
            output->type = JsonType::kBoolean;
            output->boolean = false;
            return true;
        }
        if (Consume("null")) {
            output->type = JsonType::kNull;
            return true;
        }
        return ParseNumber(output);
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
                    // Identity fields must be ASCII. Reject \u escapes rather
                    // than normalizing ambiguous Unicode spellings.
                    return false;
            }
        }
        return false;
    }

    bool ParseNumber(JsonValue* output) {
        const std::size_t start = position_;
        if (position_ < input_.size() && input_[position_] == '-') {
            ++position_;
        }
        if (position_ >= input_.size() || !std::isdigit(static_cast<unsigned char>(input_[position_]))) {
            return false;
        }
        if (input_[position_] == '0') {
            ++position_;
        } else {
            while (position_ < input_.size() &&
                   std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                ++position_;
            }
        }
        if (position_ < input_.size() &&
            (input_[position_] == '.' || input_[position_] == 'e' || input_[position_] == 'E')) {
            return false;
        }
        output->type = JsonType::kNumber;
        output->scalar = input_.substr(start, position_ - start);
        return true;
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

std::string UtcNow() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t timestamp = std::chrono::system_clock::to_time_t(now);
    const auto microseconds = std::chrono::duration_cast<std::chrono::microseconds>(
                                  now.time_since_epoch())
                                  .count() %
                              1'000'000LL;
    std::tm utc{};
    if (gmtime_r(&timestamp, &utc) == nullptr) {
        return {};
    }
    std::ostringstream output;
    output << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.' << std::setw(6)
           << std::setfill('0') << microseconds << 'Z';
    return output.str();
}

std::string ErrorResponse(const char* code) {
    return std::string{"{\"error\":\""} + code + "\"}\n";
}

bool WriteAll(int fd, const std::string& payload) {
    std::size_t offset = 0U;
    while (offset < payload.size()) {
        const ssize_t written = send(fd, payload.data() + offset, payload.size() - offset,
                                     MSG_NOSIGNAL);
        if (written <= 0) {
            return false;
        }
        offset += static_cast<std::size_t>(written);
    }
    return true;
}

std::string NewIncarnationId() {
    // A process-local counter or wall clock repeats after restart. Obtain a
    // fresh 128-bit kernel-random identity for every companion instance instead.
    // There is intentionally no timestamp/zero fallback: entropy failure must
    // keep the companion unavailable.
    std::array<unsigned char, 16U> bytes{};
    std::size_t offset = 0U;
    while (offset < bytes.size()) {
        const ssize_t count =
            getrandom(bytes.data() + offset, bytes.size() - offset, GRND_NONBLOCK);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0) {
            return {};
        }
        offset += static_cast<std::size_t>(count);
    }
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (const unsigned char byte : bytes) {
        output << std::setw(2) << static_cast<unsigned>(byte);
    }
    return output.str();
}

}  // namespace

MopApi DjiMopApi() {
    return MopApi{DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS,
                  DJI_ERROR_MOP_CHANNEL_MODULE_CODE_CONNECTION_CLOSE,
                  DjiInitialize,
                  DjiCreateReliable,
                  DjiBind,
                  DjiAccept,
                  DjiClose,
                  DjiDestroy,
                  DjiSend,
                  DjiReceive};
}

void RouteState::Set(bool* field, bool value) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (*field != value) {
        *field = value;
        ++state_.generation;
    }
}

void RouteState::SetPsdkInitialized(bool value) { Set(&state_.psdk_initialized, value); }
void RouteState::SetMopConnected(bool value) { Set(&state_.mop_connected, value); }
void RouteState::SetHandlerRegistered(bool value) { Set(&state_.handler_registered, value); }

RouteStateSnapshot RouteState::Snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_;
}

PsdkRouteCompanion::PsdkRouteCompanion(PsdkRouteCompanionConfig config, MopApi api)
    : config_(std::move(config)),
      api_(std::move(api)),
      incarnation_id_(NewIncarnationId()) {
    if (incarnation_id_.empty()) {
        throw std::runtime_error(
            "unable to obtain collision-resistant companion incarnation identity");
    }
    const std::filesystem::path socket_path(config_.socket_path);
    if (!socket_path.is_absolute() || socket_path.filename().empty() ||
        config_.socket_path.size() >= sizeof(sockaddr_un{}.sun_path)) {
        throw std::invalid_argument("PSDK companion socket path must be a bounded absolute path");
    }
    if (!IsIdentifier(config_.organization_id) || !IsIdentifier(config_.site_id) ||
        !IsIdentifier(config_.edge_device_id) || !IsIdentifier(config_.subject_port_id) ||
        config_.organization_id == "legacy" || config_.mop_channel_id == 0U ||
        config_.maximum_request_bytes == 0U || config_.maximum_request_bytes > 1024U * 1024U ||
        config_.client_timeout_ms == 0U || config_.client_timeout_ms > 10'000U) {
        throw std::invalid_argument("PSDK companion configuration is not exact and bounded");
    }
    if (!api_.initialize || !api_.create_reliable || !api_.bind || !api_.accept ||
        !api_.close || !api_.destroy || !api_.send || !api_.receive) {
        throw std::invalid_argument("PSDK MOP API table is incomplete");
    }
}

PsdkRouteCompanion::~PsdkRouteCompanion() { Stop(); }

bool PsdkRouteCompanion::Start(bool psdk_initialized, std::string* error) {
    if (!psdk_initialized) {
        if (error != nullptr) {
            *error = "DjiCore_ApplicationStart has not succeeded";
        }
        return false;
    }
    bool expected = false;
    if (!started_.compare_exchange_strong(expected, true)) {
        if (error != nullptr) {
            *error = "PSDK route companion was already started";
        }
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        stopping_.store(false);
        state_.SetPsdkInitialized(true);
    }
    if (!OpenUnixListener(error)) {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        state_.SetPsdkInitialized(false);
        started_.store(false);
        return false;
    }
    unix_thread_ = std::thread(&PsdkRouteCompanion::UnixLoop, this);
    mop_thread_ = std::thread(&PsdkRouteCompanion::MopLoop, this);
    return true;
}

void PsdkRouteCompanion::Stop() {
    if (!started_.exchange(false)) {
        return;
    }
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        // Lifecycle publication and every route-state promotion share this
        // lock, so a worker cannot publish an accepted handle or AVAILABLE
        // fact after shutdown has begun.
        stopping_.store(true);
        state_.SetMopConnected(false);
        state_.SetHandlerRegistered(false);
        state_.SetPsdkInitialized(false);
    }
    CloseForShutdown();
    if (unix_thread_.joinable()) {
        unix_thread_.join();
    }
    if (mop_thread_.joinable()) {
        mop_thread_.join();
    }
    RemoveOwnedSocket();
}

RouteStateSnapshot PsdkRouteCompanion::Snapshot() const { return state_.Snapshot(); }

bool PsdkRouteCompanion::IsCurrentOpenConnectionLocked(
    MopHandle handle, std::uint64_t connection_epoch) const {
    return !stopping_.load() && connected_handle_ == handle &&
           connected_epoch_ == connection_epoch && !connected_close_requested_;
}

MopHandle PsdkRouteCompanion::RequestConnectedCloseLocked(
    MopHandle handle, std::uint64_t connection_epoch) {
    if (connected_handle_ != handle || connected_epoch_ != connection_epoch) {
        return nullptr;
    }
    state_.SetMopConnected(false);
    if (connected_close_requested_) {
        return nullptr;
    }
    connected_close_requested_ = true;
    connected_close_in_flight_ = true;
    connected_close_completed_ = false;
    return handle;
}

MopHandle PsdkRouteCompanion::RequestListenerCloseLocked(MopHandle handle) {
    if (listener_handle_ != handle || listener_close_requested_) {
        return nullptr;
    }
    listener_close_requested_ = true;
    listener_close_in_flight_ = true;
    listener_close_completed_ = false;
    return handle;
}

void PsdkRouteCompanion::InvokeConnectedClose(MopHandle handle,
                                              std::uint64_t connection_epoch) {
    (void)api_.close(handle);
    std::lock_guard<std::mutex> lock(handles_mutex_);
    if (connected_handle_ == handle && connected_epoch_ == connection_epoch &&
        connected_close_in_flight_) {
        connected_close_in_flight_ = false;
        connected_close_completed_ = true;
        handles_changed_.notify_all();
    }
}

void PsdkRouteCompanion::InvokeListenerClose(MopHandle handle) {
    (void)api_.close(handle);
    std::lock_guard<std::mutex> lock(handles_mutex_);
    if (listener_handle_ == handle && listener_close_in_flight_) {
        listener_close_in_flight_ = false;
        listener_close_completed_ = true;
        handles_changed_.notify_all();
    }
}

void PsdkRouteCompanion::RetireConnectedHandle(MopHandle handle,
                                                std::uint64_t connection_epoch) {
    MopHandle close_handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        close_handle = RequestConnectedCloseLocked(handle, connection_epoch);
    }
    if (close_handle != nullptr) {
        InvokeConnectedClose(close_handle, connection_epoch);
    }

    bool destroy = false;
    {
        std::unique_lock<std::mutex> lock(handles_mutex_);
        handles_changed_.wait(lock, [this, handle, connection_epoch] {
            return connected_handle_ != handle || connected_epoch_ != connection_epoch ||
                   (connected_send_leases_ == 0U && connected_close_completed_);
        });
        if (connected_handle_ == handle && connected_epoch_ == connection_epoch) {
            connected_handle_ = nullptr;
            connected_close_requested_ = false;
            connected_close_in_flight_ = false;
            connected_close_completed_ = false;
            destroy = true;
            handles_changed_.notify_all();
        }
    }
    if (destroy) {
        // MopLoop is the sole accepted-handle destroy owner. In particular,
        // Stop and Unix request threads can request Close but cannot race a
        // still-active SendData lease with Destroy.
        (void)api_.destroy(handle);
    }
}

void PsdkRouteCompanion::RetireListenerHandle(MopHandle handle) {
    MopHandle close_handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        close_handle = RequestListenerCloseLocked(handle);
    }
    if (close_handle != nullptr) {
        InvokeListenerClose(close_handle);
    }

    bool destroy = false;
    {
        std::unique_lock<std::mutex> lock(handles_mutex_);
        handles_changed_.wait(lock, [this, handle] {
            return listener_handle_ != handle || listener_close_completed_;
        });
        if (listener_handle_ == handle) {
            listener_handle_ = nullptr;
            listener_close_requested_ = false;
            listener_close_in_flight_ = false;
            listener_close_completed_ = false;
            destroy = true;
            handles_changed_.notify_all();
        }
    }
    if (destroy) {
        (void)api_.destroy(handle);
    }
}

bool PsdkRouteCompanion::OpenUnixListener(std::string* error) {
    const std::filesystem::path path(config_.socket_path);
    struct stat parent_state {};
    if (lstat(path.parent_path().c_str(), &parent_state) != 0 ||
        !S_ISDIR(parent_state.st_mode) || S_ISLNK(parent_state.st_mode) ||
        parent_state.st_uid != geteuid()) {
        if (error != nullptr) {
            *error = "Unix socket parent must be a real directory owned by the process user";
        }
        return false;
    }
    struct stat old_state {};
    if (lstat(path.c_str(), &old_state) == 0) {
        if (!S_ISSOCK(old_state.st_mode) || old_state.st_uid != geteuid()) {
            if (error != nullptr) {
                *error = "refusing to replace a non-owned or non-socket Unix endpoint";
            }
            return false;
        }
        const int probe = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (probe < 0) {
            if (error != nullptr) {
                *error = "unable to probe existing Unix endpoint";
            }
            return false;
        }
        sockaddr_un existing{};
        existing.sun_family = AF_UNIX;
        std::memcpy(existing.sun_path, config_.socket_path.c_str(),
                    config_.socket_path.size() + 1U);
        const int connected =
            connect(probe, reinterpret_cast<const sockaddr*>(&existing), sizeof(existing));
        const int connect_error = errno;
        close(probe);
        if (connected == 0 || connect_error != ECONNREFUSED) {
            if (error != nullptr) {
                *error = "refusing to replace an active or ambiguous Unix endpoint";
            }
            return false;
        }
        struct stat confirmed_state {};
        if (lstat(path.c_str(), &confirmed_state) != 0 ||
            confirmed_state.st_dev != old_state.st_dev ||
            confirmed_state.st_ino != old_state.st_ino || unlink(path.c_str()) != 0) {
            if (error != nullptr) {
                *error = "stale Unix endpoint changed during cleanup";
            }
            return false;
        }
    } else if (errno != ENOENT) {
        if (error != nullptr) {
            *error = "unable to inspect Unix socket path";
        }
        return false;
    }

    const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        if (error != nullptr) {
            *error = "unable to create Unix socket";
        }
        return false;
    }
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::memcpy(address.sun_path, config_.socket_path.c_str(), config_.socket_path.size() + 1U);
    const mode_t previous_umask = umask(0077);
    const int bind_result = bind(fd, reinterpret_cast<const sockaddr*>(&address), sizeof(address));
    umask(previous_umask);
    if (bind_result != 0 || chmod(path.c_str(), 0600) != 0 || listen(fd, 8) != 0) {
        close(fd);
        (void)unlink(path.c_str());
        if (error != nullptr) {
            *error = "unable to bind protected Unix companion socket";
        }
        return false;
    }
    struct stat created_state {};
    if (lstat(path.c_str(), &created_state) != 0 || !S_ISSOCK(created_state.st_mode) ||
        created_state.st_uid != geteuid() || (created_state.st_mode & 0077) != 0) {
        close(fd);
        (void)unlink(path.c_str());
        if (error != nullptr) {
            *error = "created Unix companion endpoint failed ownership/mode validation";
        }
        return false;
    }
    std::lock_guard<std::mutex> lock(handles_mutex_);
    unix_listener_fd_ = fd;
    socket_device_ = static_cast<std::uint64_t>(created_state.st_dev);
    socket_inode_ = static_cast<std::uint64_t>(created_state.st_ino);
    return true;
}

void PsdkRouteCompanion::UnixLoop() {
    while (!stopping_.load()) {
        int listener = -1;
        {
            std::lock_guard<std::mutex> lock(handles_mutex_);
            listener = unix_listener_fd_;
        }
        if (listener < 0) {
            break;
        }
        pollfd ready{listener, POLLIN, 0};
        const int polled = poll(&ready, 1, 200);
        if (polled < 0 && errno != EINTR) {
            break;
        }
        if (polled <= 0 || (ready.revents & POLLIN) == 0) {
            continue;
        }
        const int client = accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
        if (client < 0) {
            if (!stopping_.load() && errno != EINTR) {
                std::this_thread::sleep_for(kAcceptRetry);
            }
            continue;
        }
        HandleUnixClient(client);
        close(client);
    }
}

void PsdkRouteCompanion::HandleUnixClient(int client_fd) {
    timeval timeout{};
    timeout.tv_sec = static_cast<time_t>(config_.client_timeout_ms / 1000U);
    timeout.tv_usec = static_cast<suseconds_t>((config_.client_timeout_ms % 1000U) * 1000U);
    (void)setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));

    std::string request;
    request.reserve(std::min<std::size_t>(config_.maximum_request_bytes, 4096U));
    std::array<char, 4096U> buffer{};
    bool too_large = false;
    while (request.size() <= config_.maximum_request_bytes) {
        const ssize_t count = recv(client_fd, buffer.data(), buffer.size(), 0);
        if (count == 0) {
            break;
        }
        if (count < 0) {
            (void)WriteAll(client_fd, ErrorResponse("REQUEST_READ_FAILED"));
            return;
        }
        request.append(buffer.data(), static_cast<std::size_t>(count));
        if (request.size() > config_.maximum_request_bytes) {
            too_large = true;
            break;
        }
    }
    if (too_large || request.empty() || request.back() != '\n' ||
        request.find('\n') != request.size() - 1U) {
        (void)WriteAll(client_fd, ErrorResponse("INVALID_FRAME"));
        return;
    }
    request.pop_back();
    JsonValue root;
    if (!JsonParser(request).Parse(&root)) {
        (void)WriteAll(client_fd, ErrorResponse("INVALID_JSON"));
        return;
    }
    const std::string* operation = StringField(root, "operation");
    if (operation != nullptr && *operation == "ROUTE_STATUS_V1") {
        if (!ExactFields(root, {"operation", "integrationPath", "canonicalCapabilityId",
                                "subjectPortId", "edgeDeviceId", "requiredHandler"}) ||
            StringField(root, "integrationPath") == nullptr ||
            *StringField(root, "integrationPath") != "PSDK_MANIFOLD" ||
            StringField(root, "canonicalCapabilityId") == nullptr ||
            *StringField(root, "canonicalCapabilityId") != "EDGE_UPLINK" ||
            StringField(root, "subjectPortId") == nullptr ||
            *StringField(root, "subjectPortId") != config_.subject_port_id ||
            StringField(root, "edgeDeviceId") == nullptr ||
            *StringField(root, "edgeDeviceId") != config_.edge_device_id ||
            StringField(root, "requiredHandler") == nullptr ||
            *StringField(root, "requiredHandler") != "EDGE_BUNDLE_UPLOAD") {
            (void)WriteAll(client_fd, ErrorResponse("ROUTE_IDENTITY_MISMATCH"));
            return;
        }
        const RouteStateSnapshot snapshot = state_.Snapshot();
        const std::string observed_at = UtcNow();
        const std::uint64_t status_sequence = status_sequence_.fetch_add(1U) + 1U;
        std::ostringstream response;
        response << "{\"schemaVersion\":\"1.0\",\"signalId\":\"psdk-route-"
                 << incarnation_id_ << '-' << snapshot.generation << '-'
                 << status_sequence
                 << "\",\"observedAt\":\"" << observed_at
                 << "\",\"integrationPath\":\"PSDK_MANIFOLD\","
                    "\"canonicalCapabilityId\":\"EDGE_UPLINK\",\"subjectPortId\":\""
                 << EscapeJson(config_.subject_port_id) << "\",\"edgeDeviceId\":\""
                 << EscapeJson(config_.edge_device_id) << "\",\"psdkInitialized\":"
                 << (snapshot.psdk_initialized ? "true" : "false")
                 << ",\"mopConnected\":" << (snapshot.mop_connected ? "true" : "false")
                 << ",\"handlerRegistered\":"
                 << (snapshot.handler_registered ? "true" : "false") << "}\n";
        (void)WriteAll(client_fd, response.str());
        return;
    }
    if (operation == nullptr || *operation != "EDGE_BUNDLE_UPLOAD" ||
        !ExactFields(root, {"operation", "idempotency_key", "payload"})) {
        (void)WriteAll(client_fd, ErrorResponse("UNSUPPORTED_OPERATION"));
        return;
    }
    const std::string* idempotency_key = StringField(root, "idempotency_key");
    const auto payload_it = root.object.find("payload");
    if (idempotency_key == nullptr || !IsIdentifier(*idempotency_key) ||
        payload_it == root.object.end() ||
        !ExactFields(payload_it->second,
                     {"organization_id", "site_id", "mission_id", "edge_device_id",
                      "bundle_object_ref", "bundle_sha256", "idempotency_key"})) {
        (void)WriteAll(client_fd, ErrorResponse("INVALID_EDGE_BUNDLE_REQUEST"));
        return;
    }
    const JsonValue& payload = payload_it->second;
    const std::string* organization = StringField(payload, "organization_id");
    const std::string* site = StringField(payload, "site_id");
    const std::string* mission = StringField(payload, "mission_id");
    const std::string* edge = StringField(payload, "edge_device_id");
    const std::string* object_ref = StringField(payload, "bundle_object_ref");
    const std::string* digest = StringField(payload, "bundle_sha256");
    const std::string* nested_key = StringField(payload, "idempotency_key");
    if (organization == nullptr || *organization != config_.organization_id ||
        site == nullptr || *site != config_.site_id || mission == nullptr ||
        !IsIdentifier(*mission) || edge == nullptr || *edge != config_.edge_device_id ||
        object_ref == nullptr || !IsObjectReference(*object_ref) || digest == nullptr ||
        !IsSha256(*digest) || nested_key == nullptr || *nested_key != *idempotency_key) {
        (void)WriteAll(client_fd, ErrorResponse("EDGE_BUNDLE_SCOPE_MISMATCH"));
        return;
    }
    const RouteStateSnapshot before_send = state_.Snapshot();
    std::ostringstream mop_frame;
    mop_frame << "{\"canonicalCapabilityId\":\"EDGE_UPLINK\",\"edgeDeviceId\":\""
              << EscapeJson(config_.edge_device_id) << "\",\"idempotencyKey\":\""
              << EscapeJson(*idempotency_key)
              << "\",\"integrationPath\":\"PSDK_MANIFOLD\","
                 "\"operation\":\"EDGE_BUNDLE_UPLOAD\",\"payload\":{"
                 "\"bundleObjectRef\":\""
              << EscapeJson(*object_ref) << "\",\"bundleSha256\":\"" << *digest
              << "\",\"missionId\":\"" << EscapeJson(*mission)
              << "\",\"organizationId\":\"" << EscapeJson(*organization)
              << "\",\"siteId\":\"" << EscapeJson(*site)
              << "\"},\"schemaVersion\":\"1.0\",\"subjectPortId\":\""
              << EscapeJson(config_.subject_port_id) << "\"}\n";
    if (!before_send.available() || !SendMopFrame(mop_frame.str())) {
        (void)WriteAll(client_fd, ErrorResponse("ROUTE_UNAVAILABLE"));
        return;
    }
    const std::string accepted_at = UtcNow();
    const std::string receipt =
        "{\"provider_operation_id\":\"psdk-mop-" + EscapeJson(*idempotency_key) +
        "\",\"accepted_at\":\"" + accepted_at +
        "\",\"item_count\":1,\"manifest_ref\":null}\n";
    (void)WriteAll(client_fd, receipt);
}

void PsdkRouteCompanion::MopLoop() {
    if (api_.initialize() != api_.success || stopping_.load()) {
        return;
    }
    MopHandle listener = nullptr;
    if (api_.create_reliable(&listener) != api_.success || listener == nullptr) {
        return;
    }
    bool listener_published = false;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        if (!stopping_.load()) {
            listener_handle_ = listener;
            listener_close_requested_ = false;
            listener_close_in_flight_ = false;
            listener_close_completed_ = false;
            listener_published = true;
        }
    }
    if (!listener_published) {
        (void)api_.close(listener);
        (void)api_.destroy(listener);
        return;
    }
    if (api_.bind(listener, config_.mop_channel_id) != api_.success) {
        RetireListenerHandle(listener);
        return;
    }
    bool handler_registered = false;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        if (!stopping_.load() && listener_handle_ == listener &&
            !listener_close_requested_) {
            state_.SetHandlerRegistered(true);
            handler_registered = true;
        }
    }
    while (handler_registered && !stopping_.load()) {
        MopHandle connected = nullptr;
        const MopResult accepted = api_.accept(listener, &connected);
        std::uint64_t connection_epoch = 0U;
        bool connected_published = false;
        {
            std::lock_guard<std::mutex> lock(handles_mutex_);
            if (accepted == api_.success && connected != nullptr && !stopping_.load() &&
                listener_handle_ == listener && !listener_close_requested_) {
                connected_handle_ = connected;
                connected_close_requested_ = false;
                connected_close_in_flight_ = false;
                connected_close_completed_ = false;
                connected_send_leases_ = 0U;
                ++connected_epoch_;
                if (connected_epoch_ == 0U) {
                    ++connected_epoch_;
                }
                connection_epoch = connected_epoch_;
                state_.SetMopConnected(true);
                connected_published = true;
            }
        }
        if (!connected_published) {
            if (connected != nullptr) {
                (void)api_.close(connected);
                (void)api_.destroy(connected);
            }
            if (stopping_.load()) {
                break;
            }
            std::this_thread::sleep_for(kAcceptRetry);
            continue;
        }
        std::array<std::uint8_t, 1024U> discard{};
        while (!stopping_.load()) {
            std::uint32_t received = 0U;
            const MopResult result =
                api_.receive(connected, discard.data(), static_cast<std::uint32_t>(discard.size()),
                             &received);
            if (result != api_.success || received == 0U) {
                break;
            }
            // Peer-originated bytes cannot select any local action. The HIL-1S
            // route is Edge uplink only, so inbound MOP data is deliberately
            // discarded and never dispatched to flight/media APIs.
        }
        RetireConnectedHandle(connected, connection_epoch);
    }
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        state_.SetMopConnected(false);
        state_.SetHandlerRegistered(false);
    }
    RetireListenerHandle(listener);
}

bool PsdkRouteCompanion::SendMopFrame(const std::string& frame) {
    if (frame.empty() || frame.size() > std::numeric_limits<std::uint32_t>::max()) {
        return false;
    }
    MopHandle handle = nullptr;
    std::uint64_t connection_epoch = 0U;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        if (connected_handle_ == nullptr || connected_close_requested_ || stopping_.load()) {
            return false;
        }
        handle = connected_handle_;
        connection_epoch = connected_epoch_;
        ++connected_send_leases_;
    }

    // The lease above pins this exact accepted handle until the final release
    // below. Do not hold handles_mutex_ across vendor SendData: Stop must be
    // able to publish unavailability and Close a blocked send.
    std::size_t offset = 0U;
    while (offset < frame.size()) {
        {
            std::lock_guard<std::mutex> lock(handles_mutex_);
            if (!IsCurrentOpenConnectionLocked(handle, connection_epoch)) {
                break;
            }
        }
        std::uint32_t sent = 0U;
        auto* bytes = reinterpret_cast<std::uint8_t*>(
            const_cast<char*>(frame.data() + offset));
        const std::uint32_t remaining = static_cast<std::uint32_t>(frame.size() - offset);
        const MopResult result = api_.send(handle, bytes, remaining, &sent);
        if (result != api_.success || sent == 0U || sent > remaining) {
            MopHandle close_handle = nullptr;
            {
                std::lock_guard<std::mutex> lock(handles_mutex_);
                close_handle = RequestConnectedCloseLocked(handle, connection_epoch);
            }
            // Keep this sender's lease until its Close request has returned so
            // RetireConnectedHandle cannot Destroy before the request itself
            // reaches the vendor API.
            if (close_handle != nullptr) {
                InvokeConnectedClose(close_handle, connection_epoch);
            }
            break;
        }
        offset += sent;
    }
    bool sent_current_connection = false;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        sent_current_connection = offset == frame.size() &&
                                  IsCurrentOpenConnectionLocked(handle, connection_epoch);
        if (connected_handle_ == handle && connected_epoch_ == connection_epoch &&
            connected_send_leases_ != 0U) {
            --connected_send_leases_;
            handles_changed_.notify_all();
        }
    }
    // A success linearizes at the final exact-handle/epoch revalidation. A
    // Close or Stop that wins before this point yields ROUTE_UNAVAILABLE, so a
    // stale accepted receipt cannot be manufactured after revocation.
    return sent_current_connection;
}

void PsdkRouteCompanion::CloseForShutdown() {
    int unix_listener = -1;
    MopHandle connected_to_close = nullptr;
    std::uint64_t connected_close_epoch = 0U;
    MopHandle listener_to_close = nullptr;
    {
        std::lock_guard<std::mutex> lock(handles_mutex_);
        unix_listener = std::exchange(unix_listener_fd_, -1);
        if (connected_handle_ != nullptr) {
            connected_to_close = RequestConnectedCloseLocked(connected_handle_, connected_epoch_);
            connected_close_epoch = connected_epoch_;
        }
        if (listener_handle_ != nullptr) {
            listener_to_close = RequestListenerCloseLocked(listener_handle_);
        }
    }
    if (unix_listener >= 0) {
        (void)shutdown(unix_listener, SHUT_RDWR);
        close(unix_listener);
    }
    if (connected_to_close != nullptr) {
        InvokeConnectedClose(connected_to_close, connected_close_epoch);
    }
    if (listener_to_close != nullptr) {
        InvokeListenerClose(listener_to_close);
    }
}

void PsdkRouteCompanion::RemoveOwnedSocket() {
    struct stat state {};
    if (lstat(config_.socket_path.c_str(), &state) == 0 && S_ISSOCK(state.st_mode) &&
        state.st_uid == geteuid() && static_cast<std::uint64_t>(state.st_dev) == socket_device_ &&
        static_cast<std::uint64_t>(state.st_ino) == socket_inode_) {
        (void)unlink(config_.socket_path.c_str());
    }
    socket_device_ = 0U;
    socket_inode_ = 0U;
}

}  // namespace ksi::psdk

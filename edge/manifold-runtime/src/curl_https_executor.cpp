#include "ksi/edge/curl_https_executor.hpp"

#if KSI_EDGE_HAVE_CURL_TRANSPORT

#include <curl/curl.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>

namespace ksi::edge {

namespace {

std::once_flag g_curl_initialize_once;
CURLcode g_curl_initialize_result = CURLE_FAILED_INIT;

void InitializeCurl() {
    g_curl_initialize_result = curl_global_init(CURL_GLOBAL_DEFAULT);
}

bool IsPrintableNoControl(const std::string& value) {
    return !value.empty() && std::all_of(value.begin(), value.end(), [](char character) {
        const unsigned char byte = static_cast<unsigned char>(character);
        return byte >= 0x20U && byte != 0x7FU;
    });
}

bool IsStaticPublicKeyPin(const std::string& pin) {
    if (pin.size() != 52U || pin.compare(0U, 8U, "sha256//") != 0) {
        return false;
    }
    for (std::size_t index = 8U; index < pin.size(); ++index) {
        const unsigned char byte = static_cast<unsigned char>(pin[index]);
        if (!((byte >= static_cast<unsigned char>('A') && byte <= static_cast<unsigned char>('Z')) ||
              (byte >= static_cast<unsigned char>('a') && byte <= static_cast<unsigned char>('z')) ||
              (byte >= static_cast<unsigned char>('0') && byte <= static_cast<unsigned char>('9')) ||
              byte == static_cast<unsigned char>('+') || byte == static_cast<unsigned char>('/') ||
              (byte == static_cast<unsigned char>('=') && index + 1U == pin.size()))) {
            return false;
        }
    }
    return true;
}

bool IsOriginOnlyUrl(const std::string& url) {
    if (!IsStrictHttpsUrl(url)) {
        return false;
    }
    const std::size_t suffix = url.find_first_of("/?", 8U);
    return suffix == std::string::npos ||
           (suffix + 1U == url.size() && url[suffix] == '/');
}

bool IsCoreRequestUrl(const std::string& core_base_url, const std::string& request_url) {
    if (request_url.size() <= core_base_url.size() ||
        request_url.compare(0U, core_base_url.size(), core_base_url) != 0) {
        return false;
    }
    return request_url[core_base_url.size()] == '/';
}

bool IsSafeHeader(const std::string& name, const std::string& value) {
    if (name.empty() || name.size() > 128U || value.size() > 4096U || !IsPrintableNoControl(value)) {
        return false;
    }
    return std::all_of(name.begin(), name.end(), [](char character) {
        const unsigned char byte = static_cast<unsigned char>(character);
        return (byte >= static_cast<unsigned char>('a') && byte <= static_cast<unsigned char>('z')) ||
               (byte >= static_cast<unsigned char>('A') && byte <= static_cast<unsigned char>('Z')) ||
               (byte >= static_cast<unsigned char>('0') && byte <= static_cast<unsigned char>('9')) ||
               byte == static_cast<unsigned char>('!') || byte == static_cast<unsigned char>('#') ||
               byte == static_cast<unsigned char>('$') || byte == static_cast<unsigned char>('%') ||
               byte == static_cast<unsigned char>('&') || byte == static_cast<unsigned char>('\'') ||
               byte == static_cast<unsigned char>('*') || byte == static_cast<unsigned char>('+') ||
               byte == static_cast<unsigned char>('-') || byte == static_cast<unsigned char>('.') ||
               byte == static_cast<unsigned char>('^') || byte == static_cast<unsigned char>('_') ||
               byte == static_cast<unsigned char>('`') || byte == static_cast<unsigned char>('|') ||
               byte == static_cast<unsigned char>('~');
    });
}

// CoreRestSyncTransport already gives a presigned PUT only the Core-issued
// `Content-Type` and `x-amz-*` headers.  Enforce the same narrow capability at
// the concrete transport boundary as defense in depth: a future caller of the
// generic executor must not be able to leak a Core bearer (or replace the
// signed Host/content length) to object storage.
bool IsAllowedEvidenceUploadHeader(const std::string& name) {
    std::string normalized;
    normalized.reserve(name.size());
    for (const char character : name) {
        const unsigned char byte = static_cast<unsigned char>(character);
        if (byte >= static_cast<unsigned char>('A') && byte <= static_cast<unsigned char>('Z')) {
            normalized.push_back(static_cast<char>(byte - static_cast<unsigned char>('A') +
                                                   static_cast<unsigned char>('a')));
        } else {
            normalized.push_back(character);
        }
    }
    return normalized == "content-type" || normalized.rfind("x-amz-", 0U) == 0U;
}

struct ResponseBuffer {
    std::string bytes;
    std::size_t maximum_bytes = 0U;
    bool overflowed = false;
};

size_t WriteResponse(char* data, size_t element_size, size_t element_count, void* user_data) {
    auto* buffer = static_cast<ResponseBuffer*>(user_data);
    if (buffer == nullptr || data == nullptr || element_size == 0U ||
        element_count > std::numeric_limits<std::size_t>::max() / element_size) {
        return 0U;
    }
    const std::size_t bytes = element_size * element_count;
    if (bytes > buffer->maximum_bytes - buffer->bytes.size()) {
        buffer->overflowed = true;
        return 0U;
    }
    buffer->bytes.append(data, bytes);
    return bytes;
}

HttpsRequestVerdict MapCurlError(CURLcode result, bool overflowed) {
    if (overflowed) {
        return HttpsRequestVerdict::kPermanentFailure;
    }
    switch (result) {
        case CURLE_OK:
            return HttpsRequestVerdict::kCompleted;
        case CURLE_OPERATION_TIMEDOUT:
        case CURLE_COULDNT_RESOLVE_HOST:
        case CURLE_COULDNT_CONNECT:
        case CURLE_SEND_ERROR:
        case CURLE_RECV_ERROR:
        case CURLE_GOT_NOTHING:
            return HttpsRequestVerdict::kRetryableFailure;
        default:
            // TLS verification/pin failures and request-shape failures must
            // never be retried as if they were a successful transport.
            return HttpsRequestVerdict::kPermanentFailure;
    }
}

class CurlEasyHandle final {
public:
    CurlEasyHandle() : handle_(curl_easy_init()) {}
    ~CurlEasyHandle() {
        if (handle_ != nullptr) {
            curl_easy_cleanup(handle_);
        }
    }
    CurlEasyHandle(const CurlEasyHandle&) = delete;
    CurlEasyHandle& operator=(const CurlEasyHandle&) = delete;
    CURL* get() const { return handle_; }

private:
    CURL* handle_ = nullptr;
};

class CurlHeaderList final {
public:
    ~CurlHeaderList() {
        if (headers_ != nullptr) {
            curl_slist_free_all(headers_);
        }
    }
    bool Append(const std::string& header) {
        curl_slist* next = curl_slist_append(headers_, header.c_str());
        if (next == nullptr) {
            return false;
        }
        headers_ = next;
        return true;
    }
    curl_slist* get() const { return headers_; }

private:
    curl_slist* headers_ = nullptr;
};

bool SetOption(CURL* handle, CURLoption option, long value) {
    return curl_easy_setopt(handle, option, value) == CURLE_OK;
}

bool SetOption(CURL* handle, CURLoption option, const char* value) {
    return curl_easy_setopt(handle, option, value) == CURLE_OK;
}

bool RestrictToHttps(CURL* handle) {
#if LIBCURL_VERSION_NUM >= 0x075500
    return SetOption(handle, CURLOPT_PROTOCOLS_STR, "https") &&
           SetOption(handle, CURLOPT_REDIR_PROTOCOLS_STR, "https");
#else
    return SetOption(handle, CURLOPT_PROTOCOLS, static_cast<long>(CURLPROTO_HTTPS)) &&
           SetOption(handle, CURLOPT_REDIR_PROTOCOLS, static_cast<long>(CURLPROTO_HTTPS));
#endif
}

}  // namespace

CurlHttpsRequestExecutor::CurlHttpsRequestExecutor(CurlHttpsExecutorConfig config)
    : config_(std::move(config)) {
    if (!IsOriginOnlyUrl(config_.core_base_url) || !IsStaticPublicKeyPin(config_.core_pinned_public_key) ||
        !IsStaticPublicKeyPin(config_.evidence_upload_pinned_public_key) ||
        config_.ca_bundle_path.empty() || config_.ca_bundle_path.front() != '/' ||
        !IsPrintableNoControl(config_.ca_bundle_path) || config_.connect_timeout_ms <= 0L ||
        config_.request_timeout_ms <= 0L || config_.connect_timeout_ms > config_.request_timeout_ms) {
        throw std::invalid_argument("invalid curl HTTPS executor configuration");
    }
    if (config_.core_base_url.back() == '/') {
        config_.core_base_url.pop_back();
    }
    std::call_once(g_curl_initialize_once, InitializeCurl);
    if (g_curl_initialize_result != CURLE_OK) {
        throw std::runtime_error("curl global initialization failed");
    }
}

HttpsRequestVerdict CurlHttpsRequestExecutor::Execute(const HttpsRequest& request,
                                                       HttpsResponse* response) {
    if (response == nullptr || request.method.empty() || request.maximum_response_bytes == 0U ||
        request.maximum_response_bytes > 1024U * 1024U || !IsStrictHttpsUrl(request.url) ||
        request.headers.size() > 32U) {
        return HttpsRequestVerdict::kPermanentFailure;
    }
    const std::string* pin = nullptr;
    if (request.endpoint == HttpsEndpoint::kCore) {
        if (!IsCoreRequestUrl(config_.core_base_url, request.url)) {
            return HttpsRequestVerdict::kPermanentFailure;
        }
        pin = &config_.core_pinned_public_key;
    } else if (request.endpoint == HttpsEndpoint::kEvidenceUpload) {
        pin = &config_.evidence_upload_pinned_public_key;
    } else {
        return HttpsRequestVerdict::kPermanentFailure;
    }
    CurlHeaderList headers;
    for (const auto& header : request.headers) {
        if (!IsSafeHeader(header.first, header.second) ||
            (request.endpoint == HttpsEndpoint::kEvidenceUpload &&
             !IsAllowedEvidenceUploadHeader(header.first)) ||
            !headers.Append(header.first + ": " + header.second)) {
            return HttpsRequestVerdict::kPermanentFailure;
        }
    }
    CurlEasyHandle handle;
    if (handle.get() == nullptr) {
        return HttpsRequestVerdict::kRetryableFailure;
    }
    ResponseBuffer body;
    body.maximum_bytes = request.maximum_response_bytes;
    const char* body_data = request.body.empty()
                                ? ""
                                : reinterpret_cast<const char*>(request.body.data());
    const bool configured =
        SetOption(handle.get(), CURLOPT_URL, request.url.c_str()) &&
        SetOption(handle.get(), CURLOPT_CUSTOMREQUEST, request.method.c_str()) &&
        SetOption(handle.get(), CURLOPT_POSTFIELDS, body_data) &&
        curl_easy_setopt(handle.get(), CURLOPT_POSTFIELDSIZE_LARGE,
                         static_cast<curl_off_t>(request.body.size())) == CURLE_OK &&
        curl_easy_setopt(handle.get(), CURLOPT_HTTPHEADER, headers.get()) == CURLE_OK &&
        curl_easy_setopt(handle.get(), CURLOPT_WRITEFUNCTION, WriteResponse) == CURLE_OK &&
        curl_easy_setopt(handle.get(), CURLOPT_WRITEDATA, &body) == CURLE_OK &&
        SetOption(handle.get(), CURLOPT_NOSIGNAL, 1L) &&
        SetOption(handle.get(), CURLOPT_FOLLOWLOCATION, 0L) &&
        SetOption(handle.get(), CURLOPT_SSL_VERIFYPEER, 1L) &&
        SetOption(handle.get(), CURLOPT_SSL_VERIFYHOST, 2L) &&
        RestrictToHttps(handle.get()) &&
        SetOption(handle.get(), CURLOPT_CONNECTTIMEOUT_MS, config_.connect_timeout_ms) &&
        SetOption(handle.get(), CURLOPT_TIMEOUT_MS, config_.request_timeout_ms) &&
        SetOption(handle.get(), CURLOPT_CAINFO, config_.ca_bundle_path.c_str()) &&
        SetOption(handle.get(), CURLOPT_PINNEDPUBLICKEY, pin->c_str()) &&
        SetOption(handle.get(), CURLOPT_USERAGENT, "ksi-edge-shadow/0.2") &&
        SetOption(handle.get(), CURLOPT_HTTP_VERSION, static_cast<long>(CURL_HTTP_VERSION_1_1));
    if (!configured) {
        return HttpsRequestVerdict::kPermanentFailure;
    }
    const CURLcode result = curl_easy_perform(handle.get());
    const HttpsRequestVerdict verdict = MapCurlError(result, body.overflowed);
    if (verdict != HttpsRequestVerdict::kCompleted) {
        return verdict;
    }
    long status = 0L;
    if (curl_easy_getinfo(handle.get(), CURLINFO_RESPONSE_CODE, &status) != CURLE_OK || status <= 0L ||
        status > static_cast<long>(std::numeric_limits<int>::max())) {
        return HttpsRequestVerdict::kPermanentFailure;
    }
    response->status_code = static_cast<int>(status);
    response->body = std::move(body.bytes);
    return HttpsRequestVerdict::kCompleted;
}

}  // namespace ksi::edge

#endif  // KSI_EDGE_HAVE_CURL_TRANSPORT

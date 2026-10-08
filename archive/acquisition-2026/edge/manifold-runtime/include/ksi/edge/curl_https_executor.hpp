// Optional libcurl HTTPS executor for a deployable Manifold Edge transport.
//
// This header is intentionally unavailable unless the target was built with a
// statically linked libcurl backend.  The default runtime remains dependency
// free so host/replay tests do not claim a target TLS capability.

#ifndef KSI_EDGE_CURL_HTTPS_EXECUTOR_HPP
#define KSI_EDGE_CURL_HTTPS_EXECUTOR_HPP

#include <cstddef>
#include <string>

#include "ksi/edge/core_sync_http.hpp"

#ifndef KSI_EDGE_HAVE_CURL_TRANSPORT
#define KSI_EDGE_HAVE_CURL_TRANSPORT 0
#endif

#if KSI_EDGE_HAVE_CURL_TRANSPORT
namespace ksi::edge {

struct CurlHttpsExecutorConfig {
    // Must be the same HTTPS origin passed to CoreRestSyncTransport.  Core
    // requests are restricted to it; a redirect can never switch authority.
    std::string core_base_url;
    // libcurl's `sha256//<base64>` CURLOPT_PINNEDPUBLICKEY form.  Separate
    // pins stop a Core URL compromise from redirecting evidence bytes to an
    // arbitrary TLS endpoint.  Certificate rotation is therefore a deliberate
    // deployment action, not an unreviewed runtime fallback.
    std::string core_pinned_public_key;
    std::string evidence_upload_pinned_public_key;
    // Absolute CA bundle path supplied by the DPK deployment; this is public
    // trust material, not a bearer token, but absence is fail-closed.
    std::string ca_bundle_path;
    long connect_timeout_ms = 5'000L;
    long request_timeout_ms = 30'000L;
};

class CurlHttpsRequestExecutor final : public IHttpsRequestExecutor {
public:
    explicit CurlHttpsRequestExecutor(CurlHttpsExecutorConfig config);

    HttpsRequestVerdict Execute(const HttpsRequest& request, HttpsResponse* response) override;

private:
    CurlHttpsExecutorConfig config_;
};

}  // namespace ksi::edge
#endif  // KSI_EDGE_HAVE_CURL_TRANSPORT

#endif  // KSI_EDGE_CURL_HTTPS_EXECUTOR_HPP

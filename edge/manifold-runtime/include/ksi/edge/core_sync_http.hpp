// Strict Core REST wire adapter for the Edge store-and-forward journal.
//
// The journal owns ordering and durability.  This adapter owns only the
// authenticated HTTP representation of that journal and deliberately keeps
// the TLS implementation injectable: a target deployment can use a verified
// HTTPS executor without teaching the callback/perception loop about tokens,
// sockets, or presigned URLs.

#ifndef KSI_EDGE_CORE_SYNC_HTTP_HPP
#define KSI_EDGE_CORE_SYNC_HTTP_HPP

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/sync.hpp"

namespace ksi::edge {

// A Core bearer must never be sent to a presigned object-storage URL.  The
// endpoint class is explicit so concrete executors can apply distinct TLS pin
// policy and tests can prove that separation.
enum class HttpsEndpoint {
    kCore,
    kEvidenceUpload,
};

enum class HttpsRequestVerdict {
    kCompleted,
    kRetryableFailure,
    kPermanentFailure,
};

const char* ToString(HttpsRequestVerdict verdict);

struct HttpsRequest {
    HttpsEndpoint endpoint = HttpsEndpoint::kCore;
    std::string method;
    std::string url;
    std::map<std::string, std::string> headers;
    std::vector<std::uint8_t> body;
    std::size_t maximum_response_bytes = 0;
};

struct HttpsResponse {
    int status_code = 0;
    std::string body;
};

// The concrete implementation must use HTTPS, verify the peer, refuse
// redirects, and honour maximum_response_bytes.  The adapter repeats the
// response-size check so a faulty executor cannot turn that contract into a
// fail-open condition.
class IHttpsRequestExecutor {
public:
    virtual ~IHttpsRequestExecutor() = default;
    virtual HttpsRequestVerdict Execute(const HttpsRequest& request,
                                        HttpsResponse* response) = 0;
};

enum class PrivateBearerTokenVerdict {
    kLoaded,
    kNotFound,
    kUnsafeFile,
    kTooLarge,
    kInvalidToken,
    kReadFailed,
};

const char* ToString(PrivateBearerTokenVerdict verdict);

struct PrivateBearerTokenLoadResult {
    PrivateBearerTokenVerdict verdict = PrivateBearerTokenVerdict::kReadFailed;
    // Present only on kLoaded.  Callers must not log this value.
    std::string bearer_token;
};

// Reads one deployment-provisioned bearer without following symlinks or
// accepting group/world-readable files.  It accepts a single terminal LF (or
// CRLF) for secret managers but rejects all embedded whitespace/control bytes.
PrivateBearerTokenLoadResult LoadPrivateBearerTokenFile(const std::string& path,
                                                        std::size_t maximum_bytes = 4096U);

// Validates an absolute HTTPS URL without dereferencing it.  It rejects
// userinfo, fragments, control characters, malformed ports, and non-HTTPS
// schemes.  It intentionally permits a query string for a presigned upload.
bool IsStrictHttpsUrl(const std::string& url);

struct CoreRestSyncConfig {
    // Origin only, e.g. https://core.example.test or https://core.example.test:8443.
    // Route prefixes, query strings, userinfo, and fragments are rejected so
    // the adapter cannot be pointed at an ambiguous authorization target.
    std::string core_base_url;
    // Loaded from a private file at startup; never put this in a CMake value,
    // command line, log, journal, or evidence upload request.
    std::string bearer_token;
    std::size_t maximum_core_response_bytes = 256U * 1024U;
    std::size_t maximum_candidate_payload_bytes = 2U * 1024U * 1024U;
};

// Implements the existing durable sync port against the exact Core routes:
// - POST /v1/edge-sync/event-bundles (JournalEntry)
// - POST /v1/edge-sync/events/{edgeDeviceId}::{eventId}/evidence
// - direct checksum-bound presigned PUT
//
// It is intentionally not a flight-control surface.  It cannot manufacture a
// remote object key, change event status, or send Core credentials to storage.
class CoreRestSyncTransport final : public IEdgeCoreSyncTransport {
public:
    CoreRestSyncTransport(CoreRestSyncConfig config, IHttpsRequestExecutor* executor,
                          ArtifactVault* artifact_vault);

    CoreSyncVerdict UploadCandidate(const CandidateEventRecord& candidate) override;
    EvidenceRegistrationResult RegisterEvidence(const CandidateEventRecord& candidate,
                                                const EvidenceRecord& evidence) override;
    CoreSyncVerdict PutEvidence(const EvidenceRecord& evidence,
                                const EvidenceRegistrationResult& registration) override;

private:
    CoreRestSyncConfig config_;
    IHttpsRequestExecutor* executor_;
    ArtifactVault* artifact_vault_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_CORE_SYNC_HTTP_HPP

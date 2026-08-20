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
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/evidence_attestation.hpp"
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
    CoreRestSyncConfig(std::string core_url, std::string token,
                       std::size_t maximum_core_bytes = 256U * 1024U,
                       std::size_t maximum_candidate_bytes = 2U * 1024U * 1024U,
                       std::string attestation_key_id = {},
                       std::string attestation_private_key_path = {})
        : core_base_url(std::move(core_url)),
          bearer_token(std::move(token)),
          maximum_core_response_bytes(maximum_core_bytes),
          maximum_candidate_payload_bytes(maximum_candidate_bytes),
          evidence_attestation_key_id(std::move(attestation_key_id)),
          evidence_attestation_private_key_path(std::move(attestation_private_key_path)) {}

    // Origin only, e.g. https://core.example.test or https://core.example.test:8443.
    // Route prefixes, query strings, userinfo, and fragments are rejected so
    // the adapter cannot be pointed at an ambiguous authorization target.
    std::string core_base_url;
    // Loaded from a private file at startup; never put this in a CMake value,
    // command line, log, journal, or evidence upload request.
    std::string bearer_token;
    std::size_t maximum_core_response_bytes = 256U * 1024U;
    std::size_t maximum_candidate_payload_bytes = 2U * 1024U * 1024U;
    // Both empty keeps the transport compatible with non-critical legacy evidence.
    // Production perception wiring requires both and loads only from an external 0600 file.
    std::string evidence_attestation_key_id;
    std::string evidence_attestation_private_key_path;
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
    std::unique_ptr<EvidenceAttestationSigner> evidence_attestation_signer_;
};

// ── 원본 사진 번들(source media) ────────────────────────────────────────────
//
// evidence 와 같은 HTTPS 실행기·같은 엔드포인트 분리를 쓰지만 **계약이 다르다**:
//  - 경로가 Event 가 아니라 Mission 종속이다
//    (``POST /v1/missions/{missionId}/source-media``)
//  - Core 가 업로드 헤더를 돌려주지 않는다. source-media 는 digest-bound 가
//    아니라 ``presigned_put(object_key, content_type, ttl)`` 로 서명하므로
//    (services/core/src/ksi_core/source_media.py), PUT 이 실어야 하는 헤더는
//    Content-Type 하나이고 그 값은 **방금 우리가 신고한 값**으로 이미 정해진다.
//    evidence 처럼 서버 응답에서 헤더를 받아 실으면 오히려 응답이 헤더 주입
//    표면이 된다 — 여기서는 받을 것이 없으므로 받지 않는다.
//  - digest 표기가 ``sha256:`` 접두 없는 64 hex 다(Core 의 pattern).
//
// 그래서 StoreForwardSyncDriver 를 재사용하지 않는다. 같은 드라이버에 두 계약을
// 넣으면 어느 쪽 실패도 상대 쪽 상태기계로 번역해야 한다.
struct SourceMediaUploadClaim {
    std::string media_id;
    std::string content_type;
    // 내부 표기("sha256:" + 64 hex). 전송 직전에 Core 표기로 바꾼다.
    std::string content_digest;
    std::uint64_t byte_count = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
};

struct SourceMediaRegistrationResult {
    CoreSyncVerdict verdict = CoreSyncVerdict::kRetryableFailure;
    std::string upload_url;
    // presigned PUT 이 서명한 헤더. 저널에 저장하지 않는다 — URL 과 마찬가지로
    // 만료되고, 재기동은 재등록해서 새 것을 받는다.
    std::map<std::string, std::string> required_upload_headers;
};

class IEdgeSourceMediaTransport {
public:
    virtual ~IEdgeSourceMediaTransport() = default;
    virtual SourceMediaRegistrationResult RegisterSourceMedia(
        const std::string& mission_id, const SourceMediaUploadClaim& claim) = 0;
    virtual CoreSyncVerdict PutSourceMedia(const SourceMediaItemRecord& item,
                                           const SourceMediaRegistrationResult& registration) = 0;
    // 전량 회수가 끝났다는 선언. Core 가 이 시점의 매니페스트로
    // sourceBundleDigest 를 계산한다 — 부분 집합으로 부르면 그 값이 거짓이 된다.
    virtual CoreSyncVerdict SealSourceMedia(const std::string& mission_id) = 0;
};

struct CoreRestSourceMediaConfig {
    // origin 만. CoreRestSyncConfig 와 같은 규칙으로 검증한다.
    std::string core_base_url;
    // ``EDGE_SOURCE_MEDIA_WRITE`` 를 가진 장비 토큰. presigned URL 요청에는
    // 절대 실리지 않는다.
    std::string bearer_token;
    std::size_t maximum_core_response_bytes = 256U * 1024U;
};

class CoreRestSourceMediaTransport final : public IEdgeSourceMediaTransport {
public:
    CoreRestSourceMediaTransport(CoreRestSourceMediaConfig config, IHttpsRequestExecutor* executor,
                                 ArtifactVault* spool);

    SourceMediaRegistrationResult RegisterSourceMedia(const std::string& mission_id,
                                                      const SourceMediaUploadClaim& claim) override;
    CoreSyncVerdict PutSourceMedia(const SourceMediaItemRecord& item,
                                   const SourceMediaRegistrationResult& registration) override;
    CoreSyncVerdict SealSourceMedia(const std::string& mission_id) override;

private:
    CoreRestSourceMediaConfig config_;
    IHttpsRequestExecutor* executor_;
    ArtifactVault* spool_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_CORE_SYNC_HTTP_HPP

// Ed25519 device evidence attestation for the Core evidence registration boundary.

#ifndef KSI_EDGE_EVIDENCE_ATTESTATION_HPP
#define KSI_EDGE_EVIDENCE_ATTESTATION_HPP

#include <memory>
#include <string>

namespace ksi::edge {

enum class EvidenceAttestationVerdict {
    kSigned,
    kInvalidInput,
    kKeyUnavailable,
    kSigningFailed,
};

const char* ToString(EvidenceAttestationVerdict verdict);

struct EvidenceAttestationResult {
    EvidenceAttestationVerdict verdict = EvidenceAttestationVerdict::kSigningFailed;
    std::string key_id;
    // Unpadded base64url Ed25519 signature. Never write it to the local journal.
    std::string signature_base64url;
};

// Loads one deployment-provisioned PEM Ed25519 key through a no-symlink,
// owner-only (0600) file boundary. The key bytes never enter config, logs,
// journals, fixtures, or the request outside the Ed25519 signature.
class EvidenceAttestationSigner final {
public:
    EvidenceAttestationSigner(std::string key_id, std::string private_key_path);
    ~EvidenceAttestationSigner();

    EvidenceAttestationSigner(const EvidenceAttestationSigner&) = delete;
    EvidenceAttestationSigner& operator=(const EvidenceAttestationSigner&) = delete;
    EvidenceAttestationSigner(EvidenceAttestationSigner&&) noexcept;
    EvidenceAttestationSigner& operator=(EvidenceAttestationSigner&&) noexcept;

    EvidenceAttestationResult Sign(const std::string& device_id, const std::string& site_id,
                                   const std::string& mission_id, const std::string& event_key,
                                   const std::string& artifact_id,
                                   const std::string& content_type,
                                   const std::string& content_digest) const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_EVIDENCE_ATTESTATION_HPP

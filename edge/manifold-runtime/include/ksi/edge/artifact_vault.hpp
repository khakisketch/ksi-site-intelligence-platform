// Crash-safe local artifact storage for Edge store-and-forward.

#ifndef KSI_EDGE_ARTIFACT_VAULT_HPP
#define KSI_EDGE_ARTIFACT_VAULT_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace ksi::edge {

enum class ArtifactVaultVerdict {
    kPersisted,
    kDuplicate,
    kConflict,
    kInvalidArtifactId,
    kTooLarge,
    kNotFound,
    kDigestMismatch,
    kStorageError,
};

const char* ToString(ArtifactVaultVerdict verdict);

struct StoredArtifact {
    std::string artifact_id;
    std::string local_path;
    std::string content_digest;
    std::uint64_t byte_count = 0;
};

struct ArtifactVaultResult {
    ArtifactVaultVerdict verdict = ArtifactVaultVerdict::kStorageError;
    StoredArtifact artifact;
};

class ArtifactVault {
public:
    // base_directory must be a dedicated application-owned directory, never a
    // general workspace.  max_artifact_bytes bounds RAM used to verify duplicate
    // data and gives oversized capture a typed failure rather than an OOM path.
    ArtifactVault(std::string base_directory, std::size_t max_artifact_bytes);

    ArtifactVaultResult Persist(const std::string& artifact_id, const std::uint8_t* data,
                                std::size_t size);
    ArtifactVaultResult ReadAndVerify(const StoredArtifact& expected,
                                      std::vector<std::uint8_t>* output) const;
    // Verifies a journaled artifact identity when the transport needs only the
    // durable artifact ID/path/digest.  Byte count is intentionally obtained
    // from the private file after verification; it is not part of the Core
    // evidence registration wire contract.
    ArtifactVaultResult ReadAndVerifyDigest(const std::string& artifact_id,
                                            const std::string& local_path,
                                            const std::string& content_digest,
                                            std::vector<std::uint8_t>* output) const;

    static bool IsSafeArtifactId(const std::string& artifact_id);

private:
    ArtifactVaultResult InspectExisting(const std::string& artifact_id,
                                        const std::string& destination,
                                        const std::string& desired_digest,
                                        std::size_t desired_size) const;

    const std::string base_directory_;
    const std::size_t max_artifact_bytes_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_ARTIFACT_VAULT_HPP

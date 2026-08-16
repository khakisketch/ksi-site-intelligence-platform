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

// 삭제는 보관과 다른 질문이라 판정 집합도 다르다. ArtifactVaultVerdict 에
// 값을 하나 더 넣으면 "보관됐다"와 "지워졌다"가 같은 타입으로 섞여, 두 뜻을
// 한 switch 로 다루는 기존 호출부(shadow.cpp)가 조용히 의미를 잃는다.
enum class ArtifactRemovalVerdict {
    kRemoved,
    // 이미 없다. 삭제의 사후조건("이 산출물은 디스크를 점유하지 않는다")은
    // 성립하므로, 재기동 복구가 이 값을 성공으로 취급해도 된다.
    kAlreadyAbsent,
    kInvalidArtifactId,
    // vault 안의 평범한 소유 파일이 아니다(심링크·하드링크·타 소유자 등).
    // 이런 경로는 지우지 않는다 — 우리가 만든 것이 아니면 우리 것이 아니다.
    kUnsafeArtifact,
    kStorageError,
};

const char* ToString(ArtifactRemovalVerdict verdict);

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

    // 보관된 산출물을 지우고 디렉터리 엔트리까지 fsync 한다.
    //
    // vault 는 원래 "쓰고 나면 불변"이었다. 원본 사진 회수는 그 전제로는 성립
    // 하지 않는다 — 매니폴드 여유는 8.6GB 인데 20MP 3,000장은 30GB 다. 스풀은
    // 창고가 아니라 컨베이어이고, 컨베이어에는 배출구가 있어야 한다.
    //
    // 이 API 를 증거(evidence) 경로에 쓰지 말 것. 증거는 Core 가 보존 정책으로
    // 폐기를 결정하는 대상이고(ADR-KSI-010 §3), 여기서 지우는 것은 **원본이
    // 기체 SD 카드에 그대로 남아 있는** 경유지 사본뿐이다.
    ArtifactRemovalVerdict Remove(const std::string& artifact_id);

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

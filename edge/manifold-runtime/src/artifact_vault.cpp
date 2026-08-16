#include "ksi/edge/artifact_vault.hpp"

#include "ksi/edge/crypto.hpp"

#include <atomic>
#include <cerrno>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

std::atomic<std::uint64_t> g_temporary_sequence {0};

bool WriteAll(int descriptor, const std::uint8_t* data, std::size_t size) {
    std::size_t written = 0;
    while (written < size) {
        const ssize_t result = write(descriptor, data + written, size - written);
        if (result > 0) {
            written += static_cast<std::size_t>(result);
            continue;
        }
        if (result < 0 && errno == EINTR) {
            continue;
        }
        if (result <= 0) {
            return false;
        }
    }
    return true;
}

bool FsyncDirectory(const std::filesystem::path& directory) {
    const int descriptor = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return false;
    }
    struct stat value {};
    const bool success = fstat(descriptor, &value) == 0 && S_ISDIR(value.st_mode) &&
                         value.st_uid == geteuid() && (value.st_mode & 0077) == 0 &&
                         fsync(descriptor) == 0;
    (void)close(descriptor);
    return success;
}

ArtifactVaultResult StorageFailure() {
    return {ArtifactVaultVerdict::kStorageError, {}};
}

bool EnsurePrivateArtifactDirectory(const std::filesystem::path& directory) {
    std::error_code error;
    if (!std::filesystem::create_directories(directory, error) && error) {
        return false;
    }
    struct stat value {};
    if (lstat(directory.c_str(), &value) != 0 || !S_ISDIR(value.st_mode) || S_ISLNK(value.st_mode) ||
        value.st_uid != geteuid()) {
        return false;
    }
    // A vault is an evidence boundary, not a shared scratch directory.  New
    // directories inherit the process umask, so make the private requirement
    // explicit rather than treating a permissive umask as an authorization.
    if ((value.st_mode & 0077) != 0 && chmod(directory.c_str(), 0700) != 0) {
        return false;
    }
    return lstat(directory.c_str(), &value) == 0 && S_ISDIR(value.st_mode) &&
           !S_ISLNK(value.st_mode) && value.st_uid == geteuid() && (value.st_mode & 0077) == 0;
}

enum class ReadArtifactResult {
    kRead,
    kNotFound,
    kTooLarge,
    kUnsafe,
    kStorageError,
};

ReadArtifactResult ReadPrivateArtifact(const std::string& path, std::size_t maximum_size,
                                       std::vector<std::uint8_t>* output) {
    if (output == nullptr || maximum_size == 0U) {
        return ReadArtifactResult::kStorageError;
    }
    struct stat before {};
    if (lstat(path.c_str(), &before) != 0) {
        return errno == ENOENT ? ReadArtifactResult::kNotFound : ReadArtifactResult::kStorageError;
    }
    if (!S_ISREG(before.st_mode) || S_ISLNK(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_nlink != 1) {
        return ReadArtifactResult::kUnsafe;
    }
    if (before.st_size < 0 || static_cast<std::uintmax_t>(before.st_size) > maximum_size) {
        return ReadArtifactResult::kTooLarge;
    }
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return errno == ENOENT ? ReadArtifactResult::kNotFound : ReadArtifactResult::kStorageError;
    }
    struct stat opened {};
    const bool same_file = fstat(descriptor, &opened) == 0 && opened.st_dev == before.st_dev &&
                           opened.st_ino == before.st_ino && S_ISREG(opened.st_mode) &&
                           !S_ISLNK(opened.st_mode) && opened.st_uid == geteuid() &&
                           (opened.st_mode & 0077) == 0 && opened.st_nlink == 1 &&
                           opened.st_size == before.st_size;
    if (!same_file) {
        (void)close(descriptor);
        return ReadArtifactResult::kUnsafe;
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(opened.st_size));
    std::size_t offset = 0U;
    bool read_ok = true;
    while (offset < bytes.size()) {
        const ssize_t received = read(descriptor, bytes.data() + offset, bytes.size() - offset);
        if (received > 0) {
            offset += static_cast<std::size_t>(received);
            continue;
        }
        if (received < 0 && errno == EINTR) {
            continue;
        }
        read_ok = false;
        break;
    }
    const bool closed = close(descriptor) == 0;
    if (!read_ok || !closed || offset != bytes.size()) {
        return ReadArtifactResult::kStorageError;
    }
    *output = std::move(bytes);
    return ReadArtifactResult::kRead;
}

ArtifactVaultResult ReadFailure(ReadArtifactResult result) {
    switch (result) {
        case ReadArtifactResult::kNotFound:
            return {ArtifactVaultVerdict::kNotFound, {}};
        case ReadArtifactResult::kTooLarge:
            return {ArtifactVaultVerdict::kTooLarge, {}};
        case ReadArtifactResult::kUnsafe:
            return {ArtifactVaultVerdict::kDigestMismatch, {}};
        case ReadArtifactResult::kStorageError:
            return StorageFailure();
        case ReadArtifactResult::kRead:
            break;
    }
    return StorageFailure();
}

}  // namespace

const char* ToString(ArtifactVaultVerdict verdict) {
    switch (verdict) {
        case ArtifactVaultVerdict::kPersisted:
            return "PERSISTED";
        case ArtifactVaultVerdict::kDuplicate:
            return "DUPLICATE";
        case ArtifactVaultVerdict::kConflict:
            return "CONFLICT";
        case ArtifactVaultVerdict::kInvalidArtifactId:
            return "INVALID_ARTIFACT_ID";
        case ArtifactVaultVerdict::kTooLarge:
            return "TOO_LARGE";
        case ArtifactVaultVerdict::kNotFound:
            return "NOT_FOUND";
        case ArtifactVaultVerdict::kDigestMismatch:
            return "DIGEST_MISMATCH";
        case ArtifactVaultVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

const char* ToString(ArtifactRemovalVerdict verdict) {
    switch (verdict) {
        case ArtifactRemovalVerdict::kRemoved:
            return "REMOVED";
        case ArtifactRemovalVerdict::kAlreadyAbsent:
            return "ALREADY_ABSENT";
        case ArtifactRemovalVerdict::kInvalidArtifactId:
            return "INVALID_ARTIFACT_ID";
        case ArtifactRemovalVerdict::kUnsafeArtifact:
            return "UNSAFE_ARTIFACT";
        case ArtifactRemovalVerdict::kStorageError:
            return "STORAGE_ERROR";
    }
    return "UNKNOWN";
}

ArtifactVault::ArtifactVault(std::string base_directory, std::size_t max_artifact_bytes)
    : base_directory_(std::move(base_directory)), max_artifact_bytes_(max_artifact_bytes) {
    if (base_directory_.empty() || max_artifact_bytes_ == 0U) {
        throw std::invalid_argument("artifact vault requires a directory and non-zero size limit");
    }
}

bool ArtifactVault::IsSafeArtifactId(const std::string& artifact_id) {
    if (artifact_id.empty() || artifact_id == "." || artifact_id == "..") {
        return false;
    }
    const unsigned char first = static_cast<unsigned char>(artifact_id.front());
    if (!std::isalnum(first)) {
        return false;
    }
    for (const char character : artifact_id) {
        const unsigned char value = static_cast<unsigned char>(character);
        if (!(std::isalnum(value) || character == '.' || character == '_' || character == '-')) {
            return false;
        }
    }
    return true;
}

ArtifactVaultResult ArtifactVault::InspectExisting(const std::string& artifact_id,
                                                   const std::string& destination,
                                                   const std::string& desired_digest,
                                                   std::size_t desired_size) const {
    std::vector<std::uint8_t> bytes;
    const ReadArtifactResult read_result =
        ReadPrivateArtifact(destination, max_artifact_bytes_, &bytes);
    if (read_result != ReadArtifactResult::kRead) {
        return ReadFailure(read_result);
    }
    const std::string digest = Sha256Digest(bytes.data(), bytes.size());
    if (digest.empty()) {
        return StorageFailure();
    }
    const StoredArtifact artifact = {
        artifact_id, destination, digest, static_cast<std::uint64_t>(bytes.size())};
    if (bytes.size() == desired_size && digest == desired_digest) {
        return {ArtifactVaultVerdict::kDuplicate, artifact};
    }
    return {ArtifactVaultVerdict::kConflict, artifact};
}

ArtifactVaultResult ArtifactVault::Persist(const std::string& artifact_id, const std::uint8_t* data,
                                           std::size_t size) {
    if (!IsSafeArtifactId(artifact_id)) {
        return {ArtifactVaultVerdict::kInvalidArtifactId, {}};
    }
    if ((data == nullptr && size != 0U) || size > max_artifact_bytes_) {
        return {ArtifactVaultVerdict::kTooLarge, {}};
    }
    const std::string digest = Sha256Digest(data, size);
    if (digest.empty()) {
        return StorageFailure();
    }
    const std::filesystem::path directory(base_directory_);
    if (!EnsurePrivateArtifactDirectory(directory)) {
        return StorageFailure();
    }
    const std::filesystem::path destination_path = directory / artifact_id;
    const std::string destination = destination_path.string();
    struct stat existing {};
    if (lstat(destination.c_str(), &existing) == 0) {
        return InspectExisting(artifact_id, destination, digest, size);
    }
    if (errno != ENOENT) {
        return StorageFailure();
    }
    const std::string temporary = destination + ".tmp." + std::to_string(static_cast<long long>(getpid())) +
                                  "." + std::to_string(g_temporary_sequence.fetch_add(1U));
    const int descriptor = open(temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (descriptor < 0) {
        const int open_error = errno;
        // A racing writer may have committed the same artifact after our exists
        // check.  Re-read the final path before classifying it as I/O failure.
        struct stat raced_destination {};
        if (open_error == EEXIST && lstat(destination.c_str(), &raced_destination) == 0) {
            return InspectExisting(artifact_id, destination, digest, size);
        }
        return StorageFailure();
    }
    const bool written = WriteAll(descriptor, data, size);
    const bool synced = written && fsync(descriptor) == 0;
    const bool closed = close(descriptor) == 0;
    if (!synced || !closed) {
        (void)std::remove(temporary.c_str());
        return StorageFailure();
    }
    // POSIX rename() replaces an existing destination, which would allow two
    // racing callbacks to overwrite an already-journalled artifact.  Link the
    // fsynced temporary file into place instead: same-directory hard-link is
    // atomic and fails with EEXIST, so the first durable artifact wins.
    if (link(temporary.c_str(), destination.c_str()) != 0) {
        const int link_error = errno;
        (void)std::remove(temporary.c_str());
        if (link_error == EEXIST) {
            return InspectExisting(artifact_id, destination, digest, size);
        }
        return StorageFailure();
    }
    if (!FsyncDirectory(directory)) {
        (void)std::remove(temporary.c_str());
        return StorageFailure();
    }
    if (unlink(temporary.c_str()) != 0) {
        return StorageFailure();
    }
    if (!FsyncDirectory(directory)) {
        return StorageFailure();
    }
    return {ArtifactVaultVerdict::kPersisted,
            {artifact_id, destination, digest, static_cast<std::uint64_t>(size)}};
}

ArtifactRemovalVerdict ArtifactVault::Remove(const std::string& artifact_id) {
    if (!IsSafeArtifactId(artifact_id)) {
        return ArtifactRemovalVerdict::kInvalidArtifactId;
    }
    const std::filesystem::path directory(base_directory_);
    const std::filesystem::path target = directory / artifact_id;
    struct stat existing {};
    if (lstat(target.c_str(), &existing) != 0) {
        return errno == ENOENT ? ArtifactRemovalVerdict::kAlreadyAbsent
                               : ArtifactRemovalVerdict::kStorageError;
    }
    // Persist() 가 만든 산출물의 성질과 정확히 같은 것만 지운다. 링크 수까지
    // 보는 이유: 다른 이름이 같은 inode 를 가리키고 있다면 여기서 unlink 해도
    // 바이트가 사라지지 않는다 — "지웠다"는 보고가 거짓이 된다.
    if (!S_ISREG(existing.st_mode) || S_ISLNK(existing.st_mode) || existing.st_uid != geteuid() ||
        (existing.st_mode & 0077) != 0 || existing.st_nlink != 1) {
        return ArtifactRemovalVerdict::kUnsafeArtifact;
    }
    if (unlink(target.c_str()) != 0) {
        return errno == ENOENT ? ArtifactRemovalVerdict::kAlreadyAbsent
                               : ArtifactRemovalVerdict::kStorageError;
    }
    // 디렉터리 엔트리를 fsync 하지 않으면 "지웠다"가 재기동을 넘지 못한다.
    // 전원이 끊긴 뒤 파일이 되살아나면 스풀 예산 계산이 실제 점유와 어긋난다.
    if (!FsyncDirectory(directory)) {
        return ArtifactRemovalVerdict::kStorageError;
    }
    return ArtifactRemovalVerdict::kRemoved;
}

ArtifactVaultResult ArtifactVault::ReadAndVerify(const StoredArtifact& expected,
                                                 std::vector<std::uint8_t>* output) const {
    if (output == nullptr || !IsSafeArtifactId(expected.artifact_id) || expected.local_path.empty() ||
        !IsSha256Digest(expected.content_digest) || expected.byte_count > max_artifact_bytes_) {
        return {ArtifactVaultVerdict::kDigestMismatch, {}};
    }
    const ArtifactVaultResult result =
        ReadAndVerifyDigest(expected.artifact_id, expected.local_path, expected.content_digest, output);
    if (result.verdict != ArtifactVaultVerdict::kPersisted) {
        return result;
    }
    if (output->size() != expected.byte_count) {
        output->clear();
        return {ArtifactVaultVerdict::kNotFound, {}};
    }
    return {ArtifactVaultVerdict::kPersisted, expected};
}

ArtifactVaultResult ArtifactVault::ReadAndVerifyDigest(const std::string& artifact_id,
                                                       const std::string& local_path,
                                                       const std::string& content_digest,
                                                       std::vector<std::uint8_t>* output) const {
    if (output == nullptr || !IsSafeArtifactId(artifact_id) || local_path.empty() ||
        !IsSha256Digest(content_digest)) {
        return {ArtifactVaultVerdict::kDigestMismatch, {}};
    }
    const std::filesystem::path expected_path = std::filesystem::path(base_directory_) / artifact_id;
    if (expected_path.string() != local_path) {
        return {ArtifactVaultVerdict::kDigestMismatch, {}};
    }
    const ReadArtifactResult read_result =
        ReadPrivateArtifact(expected_path.string(), max_artifact_bytes_, output);
    if (read_result != ReadArtifactResult::kRead) {
        return ReadFailure(read_result);
    }
    if (Sha256Digest(output->data(), output->size()) != content_digest) {
        output->clear();
        return {ArtifactVaultVerdict::kDigestMismatch, {}};
    }
    return {ArtifactVaultVerdict::kPersisted,
            {artifact_id, expected_path.string(), content_digest,
             static_cast<std::uint64_t>(output->size())}};
}

}  // namespace ksi::edge

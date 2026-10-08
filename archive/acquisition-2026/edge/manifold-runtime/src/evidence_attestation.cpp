#include "ksi/edge/evidence_attestation.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef KSI_EDGE_HAVE_OPENSSL_ATTESTATION
#define KSI_EDGE_HAVE_OPENSSL_ATTESTATION 0
#endif

#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#endif

namespace ksi::edge {

namespace {

#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
constexpr std::size_t kMaximumPrivateKeyBytes = 16U * 1024U;
#endif

std::string EscapeJson(const std::string& value) {
    std::string output;
    output.reserve(value.size() + 8U);
    constexpr char kHex[] = "0123456789abcdef";
    for (const char character : value) {
        const auto byte = static_cast<unsigned char>(character);
        switch (character) {
            case '"':
                output += "\\\"";
                break;
            case '\\':
                output += "\\\\";
                break;
            case '\b':
                output += "\\b";
                break;
            case '\f':
                output += "\\f";
                break;
            case '\n':
                output += "\\n";
                break;
            case '\r':
                output += "\\r";
                break;
            case '\t':
                output += "\\t";
                break;
            default:
                if (byte < 0x20U) {
                    output += "\\u00";
                    output.push_back(kHex[(byte >> 4U) & 0x0FU]);
                    output.push_back(kHex[byte & 0x0FU]);
                } else {
                    output.push_back(character);
                }
        }
    }
    return output;
}

bool IsNonEmptyJsonString(const std::string& value) {
    return !value.empty() && value.size() <= 8192U;
}

std::string CanonicalPayload(const std::string& device_id, const std::string& site_id,
                             const std::string& mission_id, const std::string& event_key,
                             const std::string& artifact_id, const std::string& content_type,
                             const std::string& content_digest) {
    // Alphabetical key order exactly matches ksi_domain.canonical_json_bytes.
    return "{\"artifactId\":\"" + EscapeJson(artifact_id) + "\",\"contentDigest\":\"" +
           EscapeJson(content_digest) + "\",\"contentType\":\"" + EscapeJson(content_type) +
           "\",\"deviceId\":\"" + EscapeJson(device_id) + "\",\"eventKey\":\"" +
           EscapeJson(event_key) + "\",\"missionId\":\"" + EscapeJson(mission_id) +
           "\",\"siteId\":\"" + EscapeJson(site_id) + "\"}";
}

#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
std::vector<std::uint8_t> ReadPrivateFile(const std::string& path) {
    const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        throw std::runtime_error("device attestation private key is unavailable");
    }
    struct stat before {};
    if (fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode) || before.st_uid != geteuid() ||
        (before.st_mode & 0077) != 0 || before.st_nlink != 1 || before.st_size <= 0 ||
        static_cast<std::uint64_t>(before.st_size) > kMaximumPrivateKeyBytes) {
        close(descriptor);
        throw std::runtime_error("device attestation private key file is unsafe");
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(before.st_size));
    std::size_t offset = 0U;
    while (offset < bytes.size()) {
        const ssize_t count = read(descriptor, bytes.data() + offset, bytes.size() - offset);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0) {
            close(descriptor);
            throw std::runtime_error("device attestation private key read failed");
        }
        offset += static_cast<std::size_t>(count);
    }
    struct stat after {};
    const bool unchanged = fstat(descriptor, &after) == 0 && before.st_dev == after.st_dev &&
                           before.st_ino == after.st_ino && before.st_size == after.st_size &&
                           before.st_uid == after.st_uid && (after.st_mode & 0077) == 0 &&
                           after.st_nlink == 1;
    const bool close_ok = close(descriptor) == 0;
    if (!unchanged || !close_ok) {
        throw std::runtime_error("device attestation private key changed while reading");
    }
    return bytes;
}

std::string Base64UrlNoPadding(const std::vector<std::uint8_t>& bytes) {
    if (bytes.empty()) {
        return {};
    }
    std::vector<unsigned char> encoded(4U * ((bytes.size() + 2U) / 3U) + 1U);
    const int length = EVP_EncodeBlock(encoded.data(), bytes.data(), static_cast<int>(bytes.size()));
    if (length <= 0) {
        return {};
    }
    std::string output(reinterpret_cast<const char*>(encoded.data()), static_cast<std::size_t>(length));
    std::replace(output.begin(), output.end(), '+', '-');
    std::replace(output.begin(), output.end(), '/', '_');
    while (!output.empty() && output.back() == '=') {
        output.pop_back();
    }
    return output;
}
#endif

}  // namespace

class EvidenceAttestationSigner::Impl final {
public:
    Impl(std::string key_id, const std::string& path) : key_id_(std::move(key_id)) {
        if (key_id_.empty() || path.empty()) {
            throw std::invalid_argument("device attestation key id/path must be non-empty");
        }
#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
        const std::vector<std::uint8_t> bytes = ReadPrivateFile(path);
        BIO* bio = BIO_new_mem_buf(bytes.data(), static_cast<int>(bytes.size()));
        if (bio == nullptr) {
            throw std::runtime_error("device attestation key parser unavailable");
        }
        key_ = PEM_read_bio_PrivateKey(bio, nullptr, nullptr, nullptr);
        BIO_free(bio);
        if (key_ == nullptr || EVP_PKEY_base_id(key_) != EVP_PKEY_ED25519) {
            if (key_ != nullptr) {
                EVP_PKEY_free(key_);
                key_ = nullptr;
            }
            throw std::runtime_error("device attestation key is not an Ed25519 PEM private key");
        }
#else
        (void)path;
        throw std::runtime_error("OpenSSL evidence attestation support was not compiled");
#endif
    }

    ~Impl() {
#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
        if (key_ != nullptr) {
            EVP_PKEY_free(key_);
        }
#endif
    }

    EvidenceAttestationResult Sign(const std::string& payload) const {
#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
        EVP_MD_CTX* context = EVP_MD_CTX_new();
        if (context == nullptr) {
            return {EvidenceAttestationVerdict::kSigningFailed, {}, {}};
        }
        std::vector<std::uint8_t> signature(64U);
        std::size_t signature_size = signature.size();
        const bool ok = EVP_DigestSignInit(context, nullptr, nullptr, nullptr, key_) == 1 &&
                        EVP_DigestSign(context, signature.data(), &signature_size,
                                       reinterpret_cast<const unsigned char*>(payload.data()),
                                       payload.size()) == 1 &&
                        signature_size == 64U;
        EVP_MD_CTX_free(context);
        if (!ok) {
            return {EvidenceAttestationVerdict::kSigningFailed, {}, {}};
        }
        signature.resize(signature_size);
        std::string encoded = Base64UrlNoPadding(signature);
        if (encoded.empty()) {
            return {EvidenceAttestationVerdict::kSigningFailed, {}, {}};
        }
        return {EvidenceAttestationVerdict::kSigned, key_id_, std::move(encoded)};
#else
        (void)payload;
        return {EvidenceAttestationVerdict::kKeyUnavailable, {}, {}};
#endif
    }

private:
    std::string key_id_;
#if KSI_EDGE_HAVE_OPENSSL_ATTESTATION
    EVP_PKEY* key_ = nullptr;
#endif
};

const char* ToString(EvidenceAttestationVerdict verdict) {
    switch (verdict) {
        case EvidenceAttestationVerdict::kSigned:
            return "SIGNED";
        case EvidenceAttestationVerdict::kInvalidInput:
            return "INVALID_INPUT";
        case EvidenceAttestationVerdict::kKeyUnavailable:
            return "KEY_UNAVAILABLE";
        case EvidenceAttestationVerdict::kSigningFailed:
            return "SIGNING_FAILED";
    }
    return "SIGNING_FAILED";
}

EvidenceAttestationSigner::EvidenceAttestationSigner(std::string key_id,
                                                     std::string private_key_path)
    : impl_(std::make_unique<Impl>(std::move(key_id), private_key_path)) {}

EvidenceAttestationSigner::~EvidenceAttestationSigner() = default;
EvidenceAttestationSigner::EvidenceAttestationSigner(EvidenceAttestationSigner&&) noexcept = default;
EvidenceAttestationSigner& EvidenceAttestationSigner::operator=(
    EvidenceAttestationSigner&&) noexcept = default;

EvidenceAttestationResult EvidenceAttestationSigner::Sign(
    const std::string& device_id, const std::string& site_id, const std::string& mission_id,
    const std::string& event_key, const std::string& artifact_id, const std::string& content_type,
    const std::string& content_digest) const {
    if (!IsNonEmptyJsonString(device_id) || !IsNonEmptyJsonString(site_id) ||
        !IsNonEmptyJsonString(mission_id) || !IsNonEmptyJsonString(event_key) ||
        !IsNonEmptyJsonString(artifact_id) || !IsNonEmptyJsonString(content_type) ||
        !IsNonEmptyJsonString(content_digest)) {
        return {EvidenceAttestationVerdict::kInvalidInput, {}, {}};
    }
    return impl_->Sign(CanonicalPayload(device_id, site_id, mission_id, event_key, artifact_id,
                                        content_type, content_digest));
}

}  // namespace ksi::edge

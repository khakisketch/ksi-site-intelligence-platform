// Minimal dependency-free SHA-256 used for local artifact and EventBundle
// digests.  The protocol prefix is always "sha256:"; callers never select an
// algorithm at runtime.

#ifndef KSI_EDGE_CRYPTO_HPP
#define KSI_EDGE_CRYPTO_HPP

#include <cstddef>
#include <cstdint>
#include <string>

namespace ksi::edge {

// Empty result means an invalid pointer/length combination or a message beyond
// SHA-256's representable bit length.  It is intentionally fail-closed rather
// than silently truncating length modulo 2^64.
std::string Sha256Hex(const std::uint8_t* data, std::size_t size);
std::string Sha256Digest(const std::uint8_t* data, std::size_t size);
std::string Sha256Digest(const std::string& value);
bool IsSha256Digest(const std::string& value);

}  // namespace ksi::edge

#endif  // KSI_EDGE_CRYPTO_HPP

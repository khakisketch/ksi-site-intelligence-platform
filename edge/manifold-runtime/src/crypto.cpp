#include "ksi/edge/crypto.hpp"

#include <array>
#include <limits>

namespace ksi::edge {

namespace {

constexpr std::array<std::uint32_t, 8> kInitialHash = {
    0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
    0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
};

constexpr std::array<std::uint32_t, 64> kRoundConstants = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U,
    0x923f82a4U, 0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U,
    0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U,
    0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
    0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU,
    0x5b9cca4fU, 0x682e6ff3U, 0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

constexpr std::uint32_t RotateRight(std::uint32_t value, unsigned amount) {
    return (value >> amount) | (value << (32U - amount));
}

void Transform(std::array<std::uint32_t, 8>* hash, const std::uint8_t* block) {
    std::array<std::uint32_t, 64> words {};
    for (std::size_t index = 0; index < 16U; ++index) {
        const std::size_t offset = index * 4U;
        words[index] = (static_cast<std::uint32_t>(block[offset]) << 24U) |
                       (static_cast<std::uint32_t>(block[offset + 1U]) << 16U) |
                       (static_cast<std::uint32_t>(block[offset + 2U]) << 8U) |
                       static_cast<std::uint32_t>(block[offset + 3U]);
    }
    for (std::size_t index = 16U; index < words.size(); ++index) {
        const std::uint32_t lower_sigma0 = RotateRight(words[index - 15U], 7U) ^
                                            RotateRight(words[index - 15U], 18U) ^
                                            (words[index - 15U] >> 3U);
        const std::uint32_t lower_sigma1 = RotateRight(words[index - 2U], 17U) ^
                                            RotateRight(words[index - 2U], 19U) ^
                                            (words[index - 2U] >> 10U);
        words[index] = words[index - 16U] + lower_sigma0 + words[index - 7U] + lower_sigma1;
    }
    std::uint32_t a = (*hash)[0];
    std::uint32_t b = (*hash)[1];
    std::uint32_t c = (*hash)[2];
    std::uint32_t d = (*hash)[3];
    std::uint32_t e = (*hash)[4];
    std::uint32_t f = (*hash)[5];
    std::uint32_t g = (*hash)[6];
    std::uint32_t h = (*hash)[7];
    for (std::size_t index = 0; index < words.size(); ++index) {
        const std::uint32_t upper_sigma1 = RotateRight(e, 6U) ^ RotateRight(e, 11U) ^ RotateRight(e, 25U);
        const std::uint32_t choose = (e & f) ^ ((~e) & g);
        const std::uint32_t temporary1 = h + upper_sigma1 + choose + kRoundConstants[index] + words[index];
        const std::uint32_t upper_sigma0 = RotateRight(a, 2U) ^ RotateRight(a, 13U) ^ RotateRight(a, 22U);
        const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        const std::uint32_t temporary2 = upper_sigma0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary1;
        d = c;
        c = b;
        b = a;
        a = temporary1 + temporary2;
    }
    (*hash)[0] += a;
    (*hash)[1] += b;
    (*hash)[2] += c;
    (*hash)[3] += d;
    (*hash)[4] += e;
    (*hash)[5] += f;
    (*hash)[6] += g;
    (*hash)[7] += h;
}

std::string Hex(const std::array<std::uint32_t, 8>& hash) {
    constexpr char kDigits[] = "0123456789abcdef";
    std::string output;
    output.reserve(64U);
    for (const std::uint32_t word : hash) {
        for (int shift = 28; shift >= 0; shift -= 4) {
            output.push_back(kDigits[(word >> static_cast<unsigned>(shift)) & 0x0FU]);
        }
    }
    return output;
}

}  // namespace

std::string Sha256Hex(const std::uint8_t* data, std::size_t size) {
    if ((data == nullptr && size != 0U) ||
        size > static_cast<std::size_t>(std::numeric_limits<std::uint64_t>::max() / 8U)) {
        return {};
    }
    std::array<std::uint32_t, 8> hash = kInitialHash;
    std::size_t offset = 0;
    while (size - offset >= 64U) {
        Transform(&hash, data + offset);
        offset += 64U;
    }
    std::array<std::uint8_t, 128> final_blocks {};
    const std::size_t remainder = size - offset;
    for (std::size_t index = 0; index < remainder; ++index) {
        final_blocks[index] = data[offset + index];
    }
    final_blocks[remainder] = 0x80U;
    const std::size_t final_size = remainder + 1U + 8U <= 64U ? 64U : 128U;
    const std::uint64_t bit_length = static_cast<std::uint64_t>(size) * 8U;
    for (std::size_t index = 0; index < 8U; ++index) {
        final_blocks[final_size - 1U - index] =
            static_cast<std::uint8_t>((bit_length >> (index * 8U)) & 0xFFU);
    }
    Transform(&hash, final_blocks.data());
    if (final_size == 128U) {
        Transform(&hash, final_blocks.data() + 64U);
    }
    return Hex(hash);
}

std::string Sha256Digest(const std::uint8_t* data, std::size_t size) {
    const std::string hex = Sha256Hex(data, size);
    return hex.empty() ? std::string{} : "sha256:" + hex;
}

std::string Sha256Digest(const std::string& value) {
    return Sha256Digest(reinterpret_cast<const std::uint8_t*>(value.data()), value.size());
}

bool IsSha256Digest(const std::string& value) {
    if (value.size() != 71U || value.compare(0, 7U, "sha256:") != 0) {
        return false;
    }
    for (std::size_t index = 7U; index < value.size(); ++index) {
        const char character = value[index];
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) {
            return false;
        }
    }
    return true;
}

}  // namespace ksi::edge

#include "ksi/edge/jpeg_dimensions.hpp"

namespace ksi::edge {

namespace {

constexpr std::uint8_t kMarkerPrefix = 0xFFU;
constexpr std::uint8_t kMarkerStartOfImage = 0xD8U;
constexpr std::uint8_t kMarkerEndOfImage = 0xD9U;
constexpr std::uint8_t kMarkerStartOfScan = 0xDAU;
constexpr std::uint8_t kMarkerTemporary = 0x01U;
constexpr std::uint8_t kMarkerRestartFirst = 0xD0U;
constexpr std::uint8_t kMarkerRestartLast = 0xD7U;

// 우리가 화소수를 읽겠다고 선언하는 프레임은 이 셋뿐이다. SOF3/5~7/9~11/13~15 는
// 프레임 헤더 배치가 같지만 실물을 본 적이 없어 kUnsupportedFrame 으로 거른다.
bool IsSupportedStartOfFrame(std::uint8_t marker) {
    return marker == 0xC0U || marker == 0xC1U || marker == 0xC2U;
}

// SOF 자리에 있으면서 프레임이 아닌 마커들(DHT=C4, JPG=C8, DAC=CC).
bool IsFrameShapedButNotFrame(std::uint8_t marker) {
    return marker == 0xC4U || marker == 0xC8U || marker == 0xCCU;
}

bool IsStartOfFrameRange(std::uint8_t marker) {
    return marker >= 0xC0U && marker <= 0xCFU && !IsFrameShapedButNotFrame(marker);
}

JpegDimensionsResult Failure(JpegDimensionsVerdict verdict) {
    return {verdict, {}};
}

}  // namespace

const char* ToString(JpegDimensionsVerdict verdict) {
    switch (verdict) {
        case JpegDimensionsVerdict::kParsed:
            return "PARSED";
        case JpegDimensionsVerdict::kNotJpeg:
            return "NOT_JPEG";
        case JpegDimensionsVerdict::kTruncated:
            return "TRUNCATED";
        case JpegDimensionsVerdict::kUnsupportedFrame:
            return "UNSUPPORTED_FRAME";
        case JpegDimensionsVerdict::kMalformed:
            return "MALFORMED";
    }
    return "UNKNOWN";
}

JpegDimensionsResult ReadJpegDimensions(const std::uint8_t* data, std::size_t size) {
    if (data == nullptr || size < 4U || data[0] != kMarkerPrefix || data[1] != kMarkerStartOfImage) {
        return Failure(JpegDimensionsVerdict::kNotJpeg);
    }
    std::size_t offset = 2U;
    while (offset + 1U < size) {
        if (data[offset] != kMarkerPrefix) {
            // 마커 사이에 채움 바이트가 아닌 값이 나왔다 — 구조가 깨졌다.
            return Failure(JpegDimensionsVerdict::kMalformed);
        }
        // 0xFF 는 여러 개 이어질 수 있다(채움 바이트). 마지막 것이 마커다.
        std::size_t marker_offset = offset;
        while (marker_offset + 1U < size && data[marker_offset + 1U] == kMarkerPrefix) {
            ++marker_offset;
        }
        if (marker_offset + 1U >= size) {
            return Failure(JpegDimensionsVerdict::kTruncated);
        }
        const std::uint8_t marker = data[marker_offset + 1U];
        offset = marker_offset + 2U;
        if (marker == 0x00U) {
            // FF00 은 엔트로피 데이터의 이스케이프다 — 마커 스캔 중에는 나올 수 없다.
            return Failure(JpegDimensionsVerdict::kMalformed);
        }
        if (marker == kMarkerStartOfImage || marker == kMarkerEndOfImage ||
            marker == kMarkerTemporary ||
            (marker >= kMarkerRestartFirst && marker <= kMarkerRestartLast)) {
            // 길이 필드가 없는 독립 마커. EOI 까지 왔는데 SOF 를 못 봤으면 실패다.
            if (marker == kMarkerEndOfImage) {
                return Failure(JpegDimensionsVerdict::kMalformed);
            }
            continue;
        }
        if (offset + 2U > size) {
            return Failure(JpegDimensionsVerdict::kTruncated);
        }
        const std::size_t segment_length =
            (static_cast<std::size_t>(data[offset]) << 8U) | static_cast<std::size_t>(data[offset + 1U]);
        if (segment_length < 2U) {
            return Failure(JpegDimensionsVerdict::kMalformed);
        }
        if (offset + segment_length > size) {
            return Failure(JpegDimensionsVerdict::kTruncated);
        }
        if (marker == kMarkerStartOfScan) {
            // 스캔이 시작됐는데 프레임 헤더를 못 봤다. 그 뒤는 엔트로피 데이터라
            // 마커 스캔이 성립하지 않는다 — 여기서 멈추고 실패로 낸다.
            return Failure(JpegDimensionsVerdict::kMalformed);
        }
        if (IsStartOfFrameRange(marker)) {
            if (!IsSupportedStartOfFrame(marker)) {
                return Failure(JpegDimensionsVerdict::kUnsupportedFrame);
            }
            // 프레임 헤더: length(2) precision(1) height(2) width(2) components(1).
            if (segment_length < 8U) {
                return Failure(JpegDimensionsVerdict::kMalformed);
            }
            const std::uint32_t height =
                (static_cast<std::uint32_t>(data[offset + 3U]) << 8U) |
                static_cast<std::uint32_t>(data[offset + 4U]);
            const std::uint32_t width =
                (static_cast<std::uint32_t>(data[offset + 5U]) << 8U) |
                static_cast<std::uint32_t>(data[offset + 6U]);
            if (width == 0U || height == 0U) {
                // DNL 로 나중에 채우는 height==0 은 규격상 가능하지만, 그 값을
                // 알려면 스캔을 끝까지 읽어야 한다. 추정하지 않고 실패로 낸다.
                return Failure(JpegDimensionsVerdict::kMalformed);
            }
            return {JpegDimensionsVerdict::kParsed, {width, height}};
        }
        offset += segment_length;
    }
    return Failure(JpegDimensionsVerdict::kTruncated);
}

}  // namespace ksi::edge

// 카메라 원본 JPEG 의 화소수를 바이트에서 직접 읽는다.
//
// Core 의 source-media 등록은 ``width``/``height`` 를 **필수**로 요구하는데
// (``services/core/src/ksi_core/source_media.py`` 의 ``SourceMediaFileClaim``,
// 둘 다 ``ge=1``), PSDK 파일 목록은 화소수를 주지 않는다. 매니폴드에는 이미지
// 디코더가 없고, DPK 는 glibc 외 동적 의존을 허용하지 않아 libjpeg 를 끌어올
// 수도 없다. 그래서 프레임 헤더만 읽는다 — 픽셀은 디코드하지 않는다.
//
// **값을 지어내지 않는다.** 화소수를 못 읽으면 0 이나 추정치를 채우는 대신
// 타입 있는 실패를 돌려주고, 호출부(MediaOffloadWorker)가 그 장을 격리한다.
// 이 필드는 결함 후보의 폴리곤 배율 계산 근거이므로(``source_media.py`` 의
// ``SourceMediaViewResponse`` docstring), 틀린 값은 없는 값보다 나쁘다.

#ifndef KSI_EDGE_JPEG_DIMENSIONS_HPP
#define KSI_EDGE_JPEG_DIMENSIONS_HPP

#include <cstddef>
#include <cstdint>

namespace ksi::edge {

enum class JpegDimensionsVerdict {
    kParsed,
    // SOI(FFD8) 로 시작하지 않는다 — JPEG 가 아니다.
    kNotJpeg,
    // 세그먼트가 선언한 길이가 버퍼 밖을 가리킨다(전송 중 잘렸을 때).
    kTruncated,
    // SOF0/1/2(baseline·extended sequential·progressive) 이외의 프레임이다.
    // 산술부호화·로스리스·계층 프레임은 헤더 배치가 같아 보여도 우리가 실측한
    // 적이 없다 — 같은 자리에서 읽어 "맞겠지"라고 쓰지 않는다.
    kUnsupportedFrame,
    // 마커 구조가 깨졌거나, SOS 까지 갔는데 SOF 가 없거나, 화소수가 0 이다.
    kMalformed,
};

const char* ToString(JpegDimensionsVerdict verdict);

struct JpegDimensions {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
};

struct JpegDimensionsResult {
    JpegDimensionsVerdict verdict = JpegDimensionsVerdict::kMalformed;
    // kParsed 일 때만 의미가 있다. 그 외에는 항상 0/0 이다.
    JpegDimensions dimensions;
};

// 마커만 훑어 첫 SOF0/1/2 의 화소수를 읽는다. 엔트로피 부호화 데이터는 읽지
// 않으므로 20MP 파일이라도 상수 시간에 가깝다.
JpegDimensionsResult ReadJpegDimensions(const std::uint8_t* data, std::size_t size);

}  // namespace ksi::edge

#endif  // KSI_EDGE_JPEG_DIMENSIONS_HPP

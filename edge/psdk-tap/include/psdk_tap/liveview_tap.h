/* edge/psdk-tap — liveview 프레임 콜백 wiring.
 *
 * 조사 확정 사실(작업 지시 인용): liveview 콜백(H264/Image 어느 쪽이든)에는 카메라
 * 자체 타임스탬프가 없다(dji_liveview.h:194-207,268-277 — 콜백 인자는 position/buf/len
 * 뿐이거나 +ImageInfo{pixFmt,width,height,frameId} 뿐이며 frameId 는 단조 카운터이지
 * 타임스탬프가 아니다). 그래서 이 tap 은 항상 H264 콜백(더 가벼운 경로 — 픽셀 디코딩이
 * 필요 없다, 어차피 콘텐츠는 안 본다)을 쓰고 recv_mono_ns 만 기록한다.
 * capabilities.frame_sensor_ts 는 항상 false 로 보고한다 — "recv 를 sensor 라고 부르는"
 * 것이 이 작업에서 가장 피해야 할 결과라고 명시됐기 때문이다.
 */
#ifndef KSI_PSDK_TAP_LIVEVIEW_TAP_H
#define KSI_PSDK_TAP_LIVEVIEW_TAP_H

#include <dji_typedef.h>

#include "psdk_tap/shared_state.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int camera_position_index; /* 1..3 → DJI_LIVEVIEW_CAMERA_POSITION_NO_{1,2,3} (payload port) */
    bool camera_source_4k;     /* false=M4D_VIS(기본), true=M4D_4K */
} ksi_liveview_config_t;

/* DjiCore_Init 이후에만 호출 가능(DjiLiveview_Init 의 계약). 프레임이 도착할 때마다
 * ksi_shared_state_on_frame() 을 호출해 짝짓기+NDJSON 기록을 트리거한다. */
T_DjiReturnCode KsiLiveviewTap_Start(const ksi_liveview_config_t *config, ksi_shared_state_t *state);
T_DjiReturnCode KsiLiveviewTap_Stop(const ksi_liveview_config_t *config);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_LIVEVIEW_TAP_H */

#include "psdk_tap/liveview_tap.h"

#include <dji_liveview.h>

#include <string.h>

#include "psdk_tap/clock_util.h"

/* DjiLiveview_H264Callback 시그니처(dji_liveview.h:196)에는 사용자 컨텍스트 인자가
 * 없다 — PSDK 자체 제약이라 우회할 수 없다. 이 프로세스는 tap 인스턴스를 하나만
 * 다루므로(CLI 도구, 서버 아님) module-level 정적 포인터가 정당한 선택이다. */
static ksi_shared_state_t *g_liveview_state = NULL;

static E_DjiLiveViewCameraPosition PositionFromIndex(int index)
{
    switch (index) {
        case 2:
            return DJI_LIVEVIEW_CAMERA_POSITION_NO_2;
        case 3:
            return DJI_LIVEVIEW_CAMERA_POSITION_NO_3;
        default:
            return DJI_LIVEVIEW_CAMERA_POSITION_NO_1;
    }
}

static E_DjiLiveViewCameraSource SourceFromConfig(const ksi_liveview_config_t *config)
{
    return config->camera_source_4k ? DJI_LIVEVIEW_CAMERA_SOURCE_M4D_4K : DJI_LIVEVIEW_CAMERA_SOURCE_M4D_VIS;
}

static void OnH264Frame(E_DjiLiveViewCameraPosition position, const uint8_t *buf, uint32_t len)
{
    /* 다른 무엇보다 먼저 시각을 찍는다 — 이후의 모든 작업(짝짓기 탐색, 파일 쓰기)이
     * 측정 지연에 섞여 들어가면 "언제 도착했나"라는 이 tap 의 유일한 책무가 흐려진다. */
    int64_t recv_mono_ns = ksi_mono_now_ns();
    (void) position;
    (void) buf;
    (void) len; /* 픽셀 내용은 이 tap 의 관심사가 아니다 — 도착 시각만 정직하게 적는다. */

    if (g_liveview_state != NULL) {
        ksi_frame_event_t event;
        memset(&event, 0, sizeof(event));
        event.recv_mono_ns = recv_mono_ns;
        event.source = KSI_FRAME_SOURCE_LIVEVIEW_H264;
        ksi_shared_state_on_frame(g_liveview_state, event);
    }
}

T_DjiReturnCode KsiLiveviewTap_Start(const ksi_liveview_config_t *config, ksi_shared_state_t *state)
{
    g_liveview_state = state;

    T_DjiReturnCode rc = DjiLiveview_Init();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        return rc;
    }

    return DjiLiveview_StartH264Stream(PositionFromIndex(config->camera_position_index),
                                        SourceFromConfig(config), OnH264Frame);
}

T_DjiReturnCode KsiLiveviewTap_Stop(const ksi_liveview_config_t *config)
{
    T_DjiReturnCode stop_rc = DjiLiveview_StopH264Stream(PositionFromIndex(config->camera_position_index),
                                                           SourceFromConfig(config));
    T_DjiReturnCode deinit_rc = DjiLiveview_Deinit();
    g_liveview_state = NULL;
    return stop_rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS ? stop_rc : deinit_rc;
}

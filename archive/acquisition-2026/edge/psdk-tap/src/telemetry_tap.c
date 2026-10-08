#include "psdk_tap/telemetry_tap.h"

#include <dji_fc_subscription.h>

#include <string.h>

#include "psdk_tap/clock_util.h"

/* DjiReceiveDataOfTopicCallback(dji_typedef.h:477) 에도 사용자 컨텍스트 인자가 없다 —
 * liveview_tap.c 와 같은 이유로 module-level 정적 포인터를 쓴다. */
static ksi_shared_state_t *g_telemetry_state = NULL;

static T_DjiReturnCode OnHardSyncTopic(const uint8_t *data, uint16_t dataSize, const T_DjiDataTimestamp *timestamp)
{
    /* 경고(dji_typedef.h:472): "User can not execute blocking style operations ... in
     * the callback function" — 여기서는 mono 시각을 찍고 뮤텍스 보호된 링에 push 만
     * 한다(ksi_shared_state_on_telemetry). 파일 I/O 는 절대 여기서 하지 않는다. */
    int64_t recv_mono_ns = ksi_mono_now_ns();

    ksi_telemetry_event_t event;
    memset(&event, 0, sizeof(event));
    event.recv_mono_ns = recv_mono_ns;

    if (timestamp != NULL) {
        /* 기종별로 기준이 다르다고 PSDK 문서가 명시한 바로 그 타임스탬프(header 참조) —
         * "센서/장치 로컬 시각"이라는 의미에서 sensor_us 로 싣지만, 절대 wall-clock 이
         * 아니다. Python 쪽 delta 계산은 이 값이 아니라 recv_mono_ns 쌍으로 하게 된다
         * (frame 쪽엔 sensor_us 가 아예 없으므로) — 이 필드는 향후 분석용 부가 정보다. */
        event.has_sensor_us = true;
        event.sensor_us = (int64_t) timestamp->millisecond * 1000 + (int64_t) timestamp->microsecond;
    }

    if (data != NULL && dataSize == sizeof(T_DjiFcSubscriptionHardSync)) {
        const T_DjiFcSubscriptionHardSync *hard_sync = (const T_DjiFcSubscriptionHardSync *) data;
        event.has_hw_flag = true;
        /* flag: true=실제 하드웨어 펄스에 대응하는 패킷 (dji_fc_subscription.h:1244-1247) */
        event.hw_flag = hard_sync->ts.flag != 0;
    }

    if (g_telemetry_state != NULL) {
        ksi_shared_state_on_telemetry(g_telemetry_state, event);
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode KsiTelemetryTap_Start(ksi_shared_state_t *state)
{
    g_telemetry_state = state;

    T_DjiReturnCode rc = DjiFcSubscription_Init();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        return rc;
    }

    return DjiFcSubscription_SubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HARD_SYNC,
                                             DJI_DATA_SUBSCRIPTION_TOPIC_400_HZ, OnHardSyncTopic);
}

T_DjiReturnCode KsiTelemetryTap_Stop(void)
{
    /* 구독 해제는 구독 순서와 같은 순서로(FIFO) 해야 한다는 제약이 있다
     * (dji_fc_subscription.h) — 이 tap 은 토픽을 하나만 구독하므로 자동으로 만족된다. */
    T_DjiReturnCode unsub_rc = DjiFcSubscription_UnSubscribeTopic(DJI_FC_SUBSCRIPTION_TOPIC_HARD_SYNC);
    T_DjiReturnCode deinit_rc = DjiFcSubscription_DeInit();
    g_telemetry_state = NULL;
    return unsub_rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS ? unsub_rc : deinit_rc;
}

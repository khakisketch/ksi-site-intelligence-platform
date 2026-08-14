#include "psdk_tap/perception_tap.h"

#include <dji_perception.h>

#include <string.h>

#include "psdk_tap/clock_util.h"

/* DjiPerceptionImageCallback에는 user context가 없다. The HIL tap is a one-instance
 * CLI process, so this mirrors the bounded lifetime approach used by liveview_tap.c.
 */
static ksi_shared_state_t *g_perception_state = NULL;

static E_DjiPerceptionDirection DirectionFromConfig(ksi_perception_direction_t direction)
{
    switch (direction) {
        case KSI_PERCEPTION_DIRECTION_DOWN:
            return DJI_PERCEPTION_RECTIFY_DOWN;
        case KSI_PERCEPTION_DIRECTION_REAR:
            return DJI_PERCEPTION_RECTIFY_REAR;
        case KSI_PERCEPTION_DIRECTION_UP:
            return DJI_PERCEPTION_RECTIFY_UP;
        case KSI_PERCEPTION_DIRECTION_LEFT:
            return DJI_PERCEPTION_RECTIFY_LEFT;
        case KSI_PERCEPTION_DIRECTION_RIGHT:
            return DJI_PERCEPTION_RECTIFY_RIGHT;
        case KSI_PERCEPTION_DIRECTION_FRONT:
        default:
            return DJI_PERCEPTION_RECTIFY_FRONT;
    }
}

static void OnPerceptionFrame(T_DjiPerceptionImageInfo image_info, uint8_t *image_raw_buffer,
                              uint32_t buffer_len)
{
    /* Take the receive timestamp before inspecting metadata. The PSDK header warns against
     * blocking work in this callback. We never touch image_raw_buffer or copy pixels here;
     * only fixed-size metadata is copied into the tap event. */
    int64_t recv_mono_ns = ksi_mono_now_ns();
    (void) image_raw_buffer;

    if (g_perception_state != NULL) {
        ksi_frame_event_t event;
        memset(&event, 0, sizeof(event));
        event.recv_mono_ns = recv_mono_ns;
        event.source = KSI_FRAME_SOURCE_PERCEPTION_GRAYSCALE;

        /* Intentionally a raw uint64, not sensor_us. DJI documents the field's presence,
         * but this pinned header does not establish unit, epoch, wrap, or a common domain
         * with HARD_SYNC. */
        event.has_raw_sensor_timestamp_u64 = true;
        event.raw_sensor_timestamp_u64 = image_info.timeStamp;
        event.has_perception_metadata = true;
        event.perception_data_id = image_info.dataId;
        event.perception_sequence = image_info.sequence;
        event.perception_data_type = image_info.dataType;
        event.perception_raw_index = image_info.rawInfo.index;
        event.perception_raw_direction = image_info.rawInfo.direction;
        event.perception_bpp = image_info.rawInfo.bpp;
        event.perception_width = image_info.rawInfo.width;
        event.perception_height = image_info.rawInfo.height;
        event.perception_buffer_len = buffer_len;
        ksi_shared_state_on_frame(g_perception_state, event);
    }
}

T_DjiReturnCode KsiPerceptionTap_Start(const ksi_perception_config_t *config,
                                       ksi_shared_state_t *state)
{
    T_DjiReturnCode rc = DjiPerception_Init();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        return rc;
    }

    /* Set before subscribe in case a PSDK implementation dispatches the first callback as
     * part of subscription. On failure the module is returned to its pre-start state. */
    g_perception_state = state;
    rc = DjiPerception_SubscribePerceptionImage(DirectionFromConfig(config->direction), OnPerceptionFrame);
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        g_perception_state = NULL;
        (void) DjiPerception_Deinit();
    }
    return rc;
}

T_DjiReturnCode KsiPerceptionTap_Stop(const ksi_perception_config_t *config)
{
    /* Avoid accepting a late in-flight callback while unsubscribe/deinit completes. */
    g_perception_state = NULL;
    T_DjiReturnCode unsubscribe_rc =
        DjiPerception_UnsubscribePerceptionImage(DirectionFromConfig(config->direction));
    T_DjiReturnCode deinit_rc = DjiPerception_Deinit();
    return unsubscribe_rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS ? unsubscribe_rc : deinit_rc;
}

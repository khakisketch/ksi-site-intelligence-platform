/* edge/psdk-tap — PSDK Perception raw-timestamp diagnostic source.
 *
 * This is deliberately separate from Liveview. Perception delivers grayscale
 * stereo-camera frames; it is not a timestamp side channel for payload RGB.
 */
#ifndef KSI_PSDK_TAP_PERCEPTION_TAP_H
#define KSI_PSDK_TAP_PERCEPTION_TAP_H

#include <dji_typedef.h>

#include "psdk_tap/shared_state.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    KSI_PERCEPTION_DIRECTION_DOWN = 0,
    KSI_PERCEPTION_DIRECTION_FRONT = 1,
    KSI_PERCEPTION_DIRECTION_REAR = 2,
    KSI_PERCEPTION_DIRECTION_UP = 3,
    KSI_PERCEPTION_DIRECTION_LEFT = 4,
    KSI_PERCEPTION_DIRECTION_RIGHT = 5,
} ksi_perception_direction_t;

typedef struct {
    ksi_perception_direction_t direction;
} ksi_perception_config_t;

/* DjiCore_Init 이후에만 호출한다. callback은 imageInfo metadata만 보존하고 image pixel
 * buffer는 읽거나 복사하지 않는다. imageInfo.timeStamp의 unit/epoch/clock domain은
 * unverified raw evidence로만 기록하며 sensor_us에 넣지 않는다. */
T_DjiReturnCode KsiPerceptionTap_Start(const ksi_perception_config_t *config,
                                       ksi_shared_state_t *state);
T_DjiReturnCode KsiPerceptionTap_Stop(const ksi_perception_config_t *config);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_PERCEPTION_TAP_H */

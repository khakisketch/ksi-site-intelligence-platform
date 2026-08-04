/* edge/psdk-tap — FC subscription telemetry 콜백 wiring.
 *
 * 조사 확정 사실(작업 지시 인용): DJI_FC_SUBSCRIPTION_TOPIC_HARD_SYNC 가 "the only data
 * which can be synchronized with external software or hardware systems"라고 PSDK
 * 헤더가 명시한다(dji_fc_subscription.h:1226-1256) — HIL 7단계 시간 정합 실측 후보를
 * 사실상 이 토픽 하나로 좁힌 근거다. 최대 400Hz.
 *
 * DjiReceiveDataOfTopicCallback 이 받는 T_DjiDataTimestamp(밀리초+마이크로초)는 모든
 * 토픽 공통 콜백 인자이고, PSDK 문서는 그 기준 시각이 기종마다 다르다고 명시한다
 * ("Use flight controller power-on timestamp on M300 RTK. Use payload local timestamp
 * on M30/M30T." — dji_typedef.h:467-472). Manifold3/M4D 조합이 어느 쪽을 쓰는지는
 * 헤더에 없다 — capabilities.telemetry_sensor_ts=true 로 정직하게 보고하되, 그 기준이
 * 무엇인지는 실기 확인 전까지 미확정임을 README 에 남긴다.
 */
#ifndef KSI_PSDK_TAP_TELEMETRY_TAP_H
#define KSI_PSDK_TAP_TELEMETRY_TAP_H

#include <dji_typedef.h>

#include "psdk_tap/shared_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/* DjiCore_Init 이후, 그리고 PSDK 문서상 "유저 태스크 안에서, 스케줄러 시작 이후"에만
 * 호출 가능(DjiFcSubscription_Init 의 계약, dji_fc_subscription.h:1414-1421). */
T_DjiReturnCode KsiTelemetryTap_Start(ksi_shared_state_t *state);
T_DjiReturnCode KsiTelemetryTap_Stop(void);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_TELEMETRY_TAP_H */

/* edge/psdk-tap/platform — PSDK 로그를 stderr 로 흘려보낸다.
 * stdout 은 NDJSON 산출물 전용으로 비워둔다(--out 이 아니라 stdout 리다이렉트로 쓸 수도
 * 있는 운영 방식을 막지 않기 위함) — PSDK 자체 로그는 항상 stderr.
 */
#ifndef KSI_PSDK_TAP_PLATFORM_LOGGER_CONSOLE_GLUE_H
#define KSI_PSDK_TAP_PLATFORM_LOGGER_CONSOLE_GLUE_H

#include <dji_typedef.h>

#ifdef __cplusplus
extern "C" {
#endif

T_DjiReturnCode KsiLoggerConsoleGlue_Register(void);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_PLATFORM_LOGGER_CONSOLE_GLUE_H */

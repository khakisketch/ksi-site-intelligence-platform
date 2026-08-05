/* edge/psdk-tap/platform — PSDK 소켓 핸들러 구현(POSIX socket 기반).
 *
 * DJI 자체 manifold3 샘플(edge/third_party/psdk/samples/.../main.c 의
 * DjiUser_PrepareSystemEnvironment)이 "카메라 스트림 뷰 기능을 쓰려면 반드시 등록하라"고
 * 주석으로 못박은 핸들러다 — liveview 를 쓰는 이 tap 에게는 선택이 아니라 필수다.
 * 함수 시그니처는 dji_platform.h 의 T_DjiSocketHandler 필드 타입 그대로.
 */
#ifndef KSI_PSDK_TAP_PLATFORM_SOCKET_GLUE_H
#define KSI_PSDK_TAP_PLATFORM_SOCKET_GLUE_H

#include <dji_typedef.h>

#ifdef __cplusplus
extern "C" {
#endif

T_DjiReturnCode KsiSocketGlue_Register(void);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_PLATFORM_SOCKET_GLUE_H */

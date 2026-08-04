/* edge/psdk-tap — 단조시계/벽시계 유틸.
 *
 * 설계 요점(작업 지시 인용): "수집기는 판정하지 않는다... C 는 '언제 무엇이 도착했나'만
 * 정직하게 적는다." 이 파일은 그 '언제'를 재는 단 하나의 자리다 — 콜백은 반드시
 * ksi_mono_now_ns() 만 부르고, UTC 환산은 meta 줄의 anchor 를 근거로 Python 쪽이 한다.
 */
#ifndef KSI_PSDK_TAP_CLOCK_UTIL_H
#define KSI_PSDK_TAP_CLOCK_UTIL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* CLOCK_MONOTONIC 나노초. 콜백에서 "언제 도착했나"를 잴 때 이것만 쓴다 — wall clock 은
 * NTP 보정으로 뒤로 튈 수 있어 delta 계산에 부적합하다. */
int64_t ksi_mono_now_ns(void);

/* CLOCK_REALTIME 을 ISO8601 UTC 문자열로 포맷한다("YYYY-MM-DDTHH:MM:SS.ffffffZ").
 * buf 는 최소 KSI_WALL_UTC_BUF_SIZE 바이트. */
#define KSI_WALL_UTC_BUF_SIZE 40
void ksi_format_wall_utc_now(char *buf, size_t buf_size);

/* 단조시계→벽시계 앵커 한 쌍을 최대한 가깝게(둘 사이 다른 syscall 없이) 뽑는다.
 * meta 줄의 clock.mono_ns/clock.wall_utc 에 그대로 쓴다 — 이후 샘플의 recv_mono_ns 는
 * (mono_ns_anchor, wall_utc_anchor) 쌍으로부터 Python 이 UTC 로 환산한다. */
void ksi_capture_clock_anchor(int64_t *out_mono_ns, char *wall_utc_buf, size_t wall_utc_buf_size);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_CLOCK_UTIL_H */

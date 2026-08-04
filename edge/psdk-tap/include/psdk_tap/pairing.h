/* edge/psdk-tap — 프레임/telemetry 짝짓기 순수 로직.
 *
 * 이 헤더/구현은 PSDK·pthread 어느 쪽에도 의존하지 않는다(순수 C11) — 호스트에서
 * PSDK 없이도 이 파일만 단위테스트할 수 있게 하기 위한 의도적 분리다. 스레드 안전성은
 * 이 파일의 책임이 아니다 — 호출자(shared_state.c)가 뮤텍스로 감싼다.
 */
#ifndef KSI_PSDK_TAP_PAIRING_H
#define KSI_PSDK_TAP_PAIRING_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* telemetry 표본 1건 — 링 버퍼에 쌓인다. */
typedef struct {
    int64_t recv_mono_ns;     /* 콜백이 이 표본을 받은 단조시계 시각 */
    bool has_sensor_us;       /* PSDK 가 이 표본에 장치-로컬 타임스탬프를 실었는가 */
    int64_t sensor_us;        /* has_sensor_us==false 면 의미 없음(0) */
    bool has_hw_flag;         /* HARD_SYNC 토픽의 하드웨어 펄스 플래그를 실었는가 */
    bool hw_flag;             /* true=실제 하드웨어 펄스 대응 패킷, false=소프트웨어 패킷 */
} ksi_telemetry_event_t;

/* 짝짓기 결과 — 프레임 하나에 대해 고른 telemetry 표본 + 얼마나 벌어졌나. */
typedef struct {
    ksi_telemetry_event_t telemetry;
    int64_t gap_ns; /* frame_mono_ns - telemetry.recv_mono_ns (부호 있음, telemetry 가 늦게 왔으면 음수) */
} ksi_pairing_result_t;

/* 고정 용량 원형 버퍼 — 최근 telemetry 표본 N 개를 보관한다.
 * storage 는 호출자가 소유한 배열(capacity 개)이며 ring 은 그 위에 view 를 얹는다. */
typedef struct {
    ksi_telemetry_event_t *items;
    int capacity;
    int count;     /* 현재 채워진 유효 표본 수 (0..capacity) */
    int next_slot;  /* 다음에 덮어쓸 인덱스 */
} ksi_telemetry_ring_t;

void ksi_ring_init(ksi_telemetry_ring_t *ring, ksi_telemetry_event_t *storage, int capacity);

/* 새 telemetry 표본을 링에 넣는다. 가득 차 있으면 가장 오래된 표본을 덮어쓴다. */
void ksi_ring_push(ksi_telemetry_ring_t *ring, ksi_telemetry_event_t event);

/* frame_mono_ns 에 시간적으로 가장 가까운(|gap| 최소) telemetry 표본을 링에서 고른다.
 * 링이 비어 있으면 false 를 반환하고 *out 은 건드리지 않는다.
 * 동률(gap 절대값이 같음)이면 더 나중에 push 된(=최신) 표본을 우선한다. */
bool ksi_ring_find_nearest(const ksi_telemetry_ring_t *ring, int64_t frame_mono_ns,
                            ksi_pairing_result_t *out);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_PAIRING_H */

/* edge/psdk-tap — liveview 콜백 스레드와 telemetry 콜백 스레드가 공유하는 상태.
 *
 * PSDK 헤더 조사 확정 사실(맥락 프롬프트 인용): "콜백은 서로 다른 스레드에서 불릴 수
 * 있다" — 이 파일이 그 공유 상태(telemetry 링 버퍼 + 카운터)를 뮤텍스로 감싸는 유일한
 * 자리다. pairing.c 자체는 스레드 비인지(pure) 로 남겨 단위테스트 가능하게 유지한다.
 */
#ifndef KSI_PSDK_TAP_SHARED_STATE_H
#define KSI_PSDK_TAP_SHARED_STATE_H

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>

#include "psdk_tap/ndjson_writer.h"
#include "psdk_tap/pairing.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t done_cond; /* CLOCK_MONOTONIC 기준으로 초기화된다 */

    ksi_telemetry_ring_t ring;
    ksi_telemetry_event_t *ring_storage; /* 이 구조체가 소유, capacity 개 */

    ksi_ndjson_writer_t *writer; /* 소유하지 않음 — 호출자(main)가 열고 닫는다 */

    int64_t target_num_samples; /* <=0 이면 "표본 수 목표 없음"(duration 만으로 종료) */
    int64_t samples_written;

    uint64_t frames_received;
    uint64_t telemetry_received;
    uint64_t frames_dropped_no_telemetry; /* 프레임 도착 시점에 telemetry 표본이 하나도 없었음 */

    bool done;
    const char *stop_reason; /* 정적 문자열 리터럴만 담는다(소유권 없음) */
} ksi_shared_state_t;

typedef enum {
    /* DJI Liveview H264 callback: sensor timestamp가 전혀 없다. */
    KSI_FRAME_SOURCE_LIVEVIEW_H264 = 0,
    /* DJI Perception grayscale callback: raw timeStamp는 있지만 단위/domain 미검증. */
    KSI_FRAME_SOURCE_PERCEPTION_GRAYSCALE = 1,
} ksi_frame_source_t;

/* 프레임 callback이 shared state에 넘기는 metadata-only event.
 *
 * ``raw_sensor_timestamp_u64``는 PSDK perception imageInfo.timeStamp를 손실 없이
 * 보존하기 위한 진단 값이다. 이는 ``sensor_us``가 아니며, downstream 공식 sensor
 * alignment 판정에 쓰일 수 없다. */
typedef struct {
    int64_t recv_mono_ns;
    ksi_frame_source_t source;
    bool has_raw_sensor_timestamp_u64;
    uint64_t raw_sensor_timestamp_u64;

    bool has_perception_metadata;
    uint16_t perception_data_id;
    uint16_t perception_sequence;
    uint32_t perception_data_type;
    uint32_t perception_raw_index;
    uint8_t perception_raw_direction;
    uint8_t perception_bpp;
    uint32_t perception_width;
    uint32_t perception_height;
    uint32_t perception_buffer_len;
} ksi_frame_event_t;

bool ksi_shared_state_init(ksi_shared_state_t *state, int ring_capacity,
                            int64_t target_num_samples, ksi_ndjson_writer_t *writer);
void ksi_shared_state_destroy(ksi_shared_state_t *state);

/* telemetry_tap 콜백에서 호출 — 링 push 만 한다(디스크 I/O 없음, 빠르게 반환). */
void ksi_shared_state_on_telemetry(ksi_shared_state_t *state, ksi_telemetry_event_t event);

/* liveview/perception callback에서 호출 — 가장 가까운 telemetry를 찾아 sample 줄을
 * 쓰고 카운터를 갱신한다. raw timestamp는 dedicated raw field로만 기록한다.
 * 목표 표본 수에 도달하면 done을 세팅하고 대기 중인 메인 스레드를 깨운다. */
void ksi_shared_state_on_frame(ksi_shared_state_t *state, ksi_frame_event_t event);

/* signal 핸들러/watchdog 등 외부 사유로 즉시 멈추게 한다(멱등). */
void ksi_shared_state_request_stop(ksi_shared_state_t *state, const char *reason);

/* deadline_mono_ns(CLOCK_MONOTONIC 절대시각) 까지 done 을 기다린다.
 * 반환값: true면 done(목표 달성/stop 요청), false면 데드라인 초과. */
bool ksi_shared_state_wait_done(ksi_shared_state_t *state, int64_t deadline_mono_ns);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_SHARED_STATE_H */

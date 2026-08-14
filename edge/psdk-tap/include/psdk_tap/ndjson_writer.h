/* edge/psdk-tap — NDJSON 출력 계약 구현.
 *
 * 이 파일이 쓰는 세 종류의 줄(meta/sample/stat)의 필드 이름·의미는 작업 지시의
 * "출력 계약(NDJSON)" 절이 정본이다 — 필드를 늘리는 건 괜찮지만(하위호환), 이미 정의된
 * 필드의 이름·타입·의미를 바꾸면 tools/hil/capture_frame_telemetry_timing.py 쪽 파서가
 * 깨진다.
 */
#ifndef KSI_PSDK_TAP_NDJSON_WRITER_H
#define KSI_PSDK_TAP_NDJSON_WRITER_H

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    FILE *file;
    pthread_mutex_t mutex; /* 프레임 콜백과 stat 마무리가 서로 다른 스레드에서 동시에 쓸 수 있다 */
} ksi_ndjson_writer_t;

/* out_path 를 쓰기 모드로 연다("w") — 이미 있으면 덮어쓴다(HIL 세션은 매번 새 파일). */
bool ksi_ndjson_open(ksi_ndjson_writer_t *writer, const char *out_path);
void ksi_ndjson_close(ksi_ndjson_writer_t *writer);

/* 하나의 짝짓기 엔드포인트(frame 또는 telemetry) 공통 표현. */
typedef struct {
    int64_t recv_mono_ns;
    bool has_sensor_us; /* false 면 sample 줄에 sensor_us:null 로 쓴다 */
    int64_t sensor_us;

    /* ``sensor_us``와 절대 섞지 않는 원시 device timestamp 진단 필드.
     *
     * PSDK perception imageInfo.timeStamp의 단위·epoch·clock domain은 현 시점에
     * 검증되지 않았다. 따라서 이 값은 decimal string으로만 보존한다. ``sensor_us``로
     * 변환하거나 host CLOCK_MONOTONIC 앵커에 붙이는 호출자는 없다. */
    bool has_sensor_timestamp_raw_u64;
    uint64_t sensor_timestamp_raw_u64;

    /* perception source일 때만 채우는 callback metadata. 픽셀 buffer는 절대 저장하지
     * 않는다 — 이 HIL tap은 시각/전달 경로 진단기이지 이미지 수집기가 아니다. */
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
} ksi_ndjson_endpoint_t;

void ksi_ndjson_write_meta(ksi_ndjson_writer_t *writer,
                            int tap_version,
                            const char *psdk_version,
                            const char *started_at_utc,
                            const char *aircraft_sn, /* NULL 이면 JSON null */
                            int64_t anchor_mono_ns,
                            const char *anchor_wall_utc,
                            bool capability_frame_sensor_ts,
                            bool capability_telemetry_sensor_ts,
                            const char *frame_source,
                            const char *frame_timestamp_provenance,
                            const char *sensor_us_domain);

void ksi_ndjson_write_sample(ksi_ndjson_writer_t *writer,
                              int64_t sample_index,
                              ksi_ndjson_endpoint_t frame,
                              ksi_ndjson_endpoint_t telemetry,
                              bool telemetry_has_hw_flag,
                              bool telemetry_hw_flag,
                              const char *pairing_strategy,
                              int64_t gap_ns);

/* stop_reason: "num_samples_reached" | "duration_exceeded" | "signal" | "error" */
void ksi_ndjson_write_stat(ksi_ndjson_writer_t *writer,
                            uint64_t frames_received,
                            uint64_t telemetry_received,
                            uint64_t samples_written,
                            uint64_t frames_dropped_no_telemetry,
                            int64_t target_num_samples,
                            const char *stop_reason,
                            bool insufficient_samples);

#ifdef __cplusplus
}
#endif

#endif /* KSI_PSDK_TAP_NDJSON_WRITER_H */

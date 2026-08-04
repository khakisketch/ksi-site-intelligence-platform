#include "psdk_tap/shared_state.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

bool ksi_shared_state_init(ksi_shared_state_t *state, int ring_capacity,
                            int64_t target_num_samples, ksi_ndjson_writer_t *writer)
{
    memset(state, 0, sizeof(*state));

    if (pthread_mutex_init(&state->mutex, NULL) != 0) {
        return false;
    }

    pthread_condattr_t cond_attr;
    if (pthread_condattr_init(&cond_attr) != 0) {
        pthread_mutex_destroy(&state->mutex);
        return false;
    }
    /* CLOCK_MONOTONIC 로 고정 — 대기 데드라인이 CLOCK_REALTIME(NTP 보정 등으로 튈 수 있음)의
     * 영향을 받지 않게 한다. */
    if (pthread_condattr_setclock(&cond_attr, CLOCK_MONOTONIC) != 0 ||
        pthread_cond_init(&state->done_cond, &cond_attr) != 0) {
        pthread_condattr_destroy(&cond_attr);
        pthread_mutex_destroy(&state->mutex);
        return false;
    }
    pthread_condattr_destroy(&cond_attr);

    state->ring_storage = calloc((size_t) ring_capacity, sizeof(ksi_telemetry_event_t));
    if (state->ring_storage == NULL) {
        pthread_cond_destroy(&state->done_cond);
        pthread_mutex_destroy(&state->mutex);
        return false;
    }
    ksi_ring_init(&state->ring, state->ring_storage, ring_capacity);

    state->writer = writer;
    state->target_num_samples = target_num_samples;
    state->samples_written = 0;
    state->frames_received = 0;
    state->telemetry_received = 0;
    state->frames_dropped_no_telemetry = 0;
    state->done = false;
    state->stop_reason = NULL;
    return true;
}

void ksi_shared_state_destroy(ksi_shared_state_t *state)
{
    free(state->ring_storage);
    state->ring_storage = NULL;
    pthread_cond_destroy(&state->done_cond);
    pthread_mutex_destroy(&state->mutex);
}

void ksi_shared_state_on_telemetry(ksi_shared_state_t *state, ksi_telemetry_event_t event)
{
    pthread_mutex_lock(&state->mutex);
    ksi_ring_push(&state->ring, event);
    state->telemetry_received += 1;
    pthread_mutex_unlock(&state->mutex);
}

void ksi_shared_state_on_frame(ksi_shared_state_t *state, int64_t frame_mono_ns)
{
    pthread_mutex_lock(&state->mutex);
    state->frames_received += 1;
    if (state->done) {
        /* 이미 목표 달성/정지 요청된 뒤 — 더 이상 샘플을 쓰지 않는다(카운터만 반영). */
        pthread_mutex_unlock(&state->mutex);
        return;
    }

    ksi_pairing_result_t result;
    bool found = ksi_ring_find_nearest(&state->ring, frame_mono_ns, &result);
    if (!found) {
        /* telemetry 표본이 아직 하나도 없다 — telemetry.recv_mono_ns 를 정직하게 채울 수
         * 없으므로 지어내지 않고 이 프레임을 버린다(카운터로만 남긴다). */
        state->frames_dropped_no_telemetry += 1;
        pthread_mutex_unlock(&state->mutex);
        return;
    }

    int64_t sample_index = state->samples_written;
    state->samples_written += 1;
    bool reached_target = state->target_num_samples > 0 &&
                           state->samples_written >= state->target_num_samples;
    if (reached_target) {
        state->done = true;
        state->stop_reason = "num_samples_reached";
    }
    pthread_mutex_unlock(&state->mutex);

    /* 파일 I/O 는 락 밖에서 한다 — 안 그러면 telemetry 콜백(빠른 push 만 해야 함)이 프레임
     * 콜백의 디스크 쓰기 지연에 걸려 대기하게 된다. */
    ksi_ndjson_endpoint_t frame_ep = {
        .recv_mono_ns = frame_mono_ns,
        .has_sensor_us = false, /* liveview 콜백엔 센서 타임스탬프가 없다(조사 확정) */
        .sensor_us = 0,
    };
    ksi_ndjson_endpoint_t telemetry_ep = {
        .recv_mono_ns = result.telemetry.recv_mono_ns,
        .has_sensor_us = result.telemetry.has_sensor_us,
        .sensor_us = result.telemetry.sensor_us,
    };
    ksi_ndjson_write_sample(state->writer, sample_index, frame_ep, telemetry_ep,
                             result.telemetry.has_hw_flag, result.telemetry.hw_flag,
                             "nearest_recv_mono_ns", result.gap_ns);

    if (reached_target) {
        pthread_cond_broadcast(&state->done_cond);
    }
}

void ksi_shared_state_request_stop(ksi_shared_state_t *state, const char *reason)
{
    pthread_mutex_lock(&state->mutex);
    if (!state->done) {
        state->done = true;
        state->stop_reason = reason;
    }
    pthread_mutex_unlock(&state->mutex);
    pthread_cond_broadcast(&state->done_cond);
}

bool ksi_shared_state_wait_done(ksi_shared_state_t *state, int64_t deadline_mono_ns)
{
    struct timespec deadline;
    deadline.tv_sec = (time_t) (deadline_mono_ns / 1000000000LL);
    deadline.tv_nsec = (long) (deadline_mono_ns % 1000000000LL);

    pthread_mutex_lock(&state->mutex);
    while (!state->done) {
        int rc = pthread_cond_timedwait(&state->done_cond, &state->mutex, &deadline);
        if (rc == ETIMEDOUT) {
            break;
        }
    }
    bool done = state->done;
    pthread_mutex_unlock(&state->mutex);
    return done;
}

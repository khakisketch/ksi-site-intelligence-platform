#include "psdk_tap/pairing.h"

#include <stddef.h>

void ksi_ring_init(ksi_telemetry_ring_t *ring, ksi_telemetry_event_t *storage, int capacity)
{
    ring->items = storage;
    ring->capacity = capacity;
    ring->count = 0;
    ring->next_slot = 0;
}

void ksi_ring_push(ksi_telemetry_ring_t *ring, ksi_telemetry_event_t event)
{
    if (ring->capacity <= 0) {
        return;
    }
    ring->items[ring->next_slot] = event;
    ring->next_slot = (ring->next_slot + 1) % ring->capacity;
    if (ring->count < ring->capacity) {
        ring->count += 1;
    }
}

static int64_t ksi_abs_i64(int64_t v)
{
    return v < 0 ? -v : v;
}

bool ksi_ring_find_nearest(const ksi_telemetry_ring_t *ring, int64_t frame_mono_ns,
                            ksi_pairing_result_t *out)
{
    if (ring->count == 0) {
        return false;
    }

    /* 최신 표본부터 과거로 훑는다 — 동률(같은 |gap|)이면 먼저 만나는 최신 쪽이
     * 이기도록 strict less-than 비교만 쓴다(명세: "동률이면 최신 우선"). */
    int newest_index = (ring->next_slot - 1 + ring->capacity) % ring->capacity;
    bool found = false;
    int64_t best_abs_gap = 0;
    ksi_telemetry_event_t best_event = {0};
    int64_t best_gap = 0;

    int index = newest_index;
    for (int i = 0; i < ring->count; ++i) {
        const ksi_telemetry_event_t *candidate = &ring->items[index];
        int64_t gap = frame_mono_ns - candidate->recv_mono_ns;
        int64_t abs_gap = ksi_abs_i64(gap);
        if (!found || abs_gap < best_abs_gap) {
            found = true;
            best_abs_gap = abs_gap;
            best_event = *candidate;
            best_gap = gap;
        }
        index = (index - 1 + ring->capacity) % ring->capacity;
    }

    if (!found) {
        return false;
    }
    out->telemetry = best_event;
    out->gap_ns = best_gap;
    return true;
}

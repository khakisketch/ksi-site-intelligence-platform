/* pairing.c 계약 테스트 — PSDK/pthread 의존 없이 순수 로직만 검증한다.
 * 외부 프레임워크 없이 단언 + 종료코드로만 동작한다(edge/manifold-runtime 관례를 따름).
 */
#include "psdk_tap/pairing.h"

#include <stdio.h>

static int g_checks = 0;
static int g_failures = 0;

static void Check(bool condition, const char *what)
{
    g_checks += 1;
    if (!condition) {
        g_failures += 1;
        fprintf(stderr, "FAIL: %s\n", what);
    }
}

static ksi_telemetry_event_t MakeEvent(int64_t recv_mono_ns)
{
    ksi_telemetry_event_t event;
    event.recv_mono_ns = recv_mono_ns;
    event.has_sensor_us = false;
    event.sensor_us = 0;
    event.has_hw_flag = false;
    event.hw_flag = false;
    return event;
}

static void TestEmptyRingHasNoMatch(void)
{
    ksi_telemetry_event_t storage[4];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 4);

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 1000, &result) == false, "빈 링은 짝을 못 찾는다");
}

static void TestSingleSampleMatches(void)
{
    ksi_telemetry_event_t storage[4];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 4);
    ksi_ring_push(&ring, MakeEvent(1000));

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 1500, &result) == true, "표본 1개면 짝을 찾는다");
    Check(result.telemetry.recv_mono_ns == 1000, "짝지어진 telemetry 시각이 맞다");
    Check(result.gap_ns == 500, "gap_ns = frame - telemetry (부호 있음)");
}

static void TestPicksNearestNotLatest(void)
{
    ksi_telemetry_event_t storage[8];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 8);
    ksi_ring_push(&ring, MakeEvent(1000));
    ksi_ring_push(&ring, MakeEvent(2000));
    ksi_ring_push(&ring, MakeEvent(5000)); /* 가장 최근이지만 가장 가깝지는 않다 */

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 2100, &result) == true, "짝을 찾는다");
    Check(result.telemetry.recv_mono_ns == 2000,
          "최신(5000)이 아니라 시간적으로 가장 가까운(2000) 표본을 고른다");
    Check(result.gap_ns == 100, "gap_ns 는 고른 표본 기준으로 계산된다");
}

static void TestTieBreaksTowardNewest(void)
{
    ksi_telemetry_event_t storage[8];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 8);
    ksi_ring_push(&ring, MakeEvent(1000)); /* frame(1500) 에서 |gap|=500 */
    ksi_ring_push(&ring, MakeEvent(2000)); /* frame(1500) 에서 |gap|=500, 이쪽이 더 최신 */

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 1500, &result) == true, "짝을 찾는다");
    Check(result.telemetry.recv_mono_ns == 2000, "동률이면 최신 표본을 우선한다");
    Check(result.gap_ns == -500, "gap_ns 부호는 고른 쪽 기준(telemetry 가 frame 보다 늦음)");
}

static void TestRingOverwritesOldest(void)
{
    ksi_telemetry_event_t storage[2];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 2);
    ksi_ring_push(&ring, MakeEvent(1000));
    ksi_ring_push(&ring, MakeEvent(2000));
    ksi_ring_push(&ring, MakeEvent(3000)); /* capacity=2 — 1000 이 밀려난다 */

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 1000, &result) == true, "짝을 찾는다(링이 안 비었으므로)");
    Check(result.telemetry.recv_mono_ns == 2000,
          "가장 오래된 표본(1000)은 밀려났으므로 남은 것 중 가장 가까운(2000)을 고른다");
}

static void TestSensorUsAndHwFlagPassThrough(void)
{
    ksi_telemetry_event_t storage[4];
    ksi_telemetry_ring_t ring;
    ksi_ring_init(&ring, storage, 4);

    ksi_telemetry_event_t event = MakeEvent(500);
    event.has_sensor_us = true;
    event.sensor_us = 123456;
    event.has_hw_flag = true;
    event.hw_flag = true;
    ksi_ring_push(&ring, event);

    ksi_pairing_result_t result;
    Check(ksi_ring_find_nearest(&ring, 500, &result) == true, "짝을 찾는다");
    Check(result.telemetry.has_sensor_us == true, "sensor_us 유무가 그대로 전달된다");
    Check(result.telemetry.sensor_us == 123456, "sensor_us 값이 그대로 전달된다");
    Check(result.telemetry.has_hw_flag == true, "hw_flag 유무가 그대로 전달된다");
    Check(result.telemetry.hw_flag == true, "hw_flag 값이 그대로 전달된다");
}

int main(void)
{
    TestEmptyRingHasNoMatch();
    TestSingleSampleMatches();
    TestPicksNearestNotLatest();
    TestTieBreaksTowardNewest();
    TestRingOverwritesOldest();
    TestSensorUsAndHwFlagPassThrough();

    printf("pairing_tests: %d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

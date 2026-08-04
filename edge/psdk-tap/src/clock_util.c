#include "psdk_tap/clock_util.h"

#include <stdio.h>
#include <time.h>

int64_t ksi_mono_now_ns(void)
{
    struct timespec ts;
    /* CLOCK_MONOTONIC 실패는 커널이 근본적으로 고장난 경우뿐이다 — 그 경우 0을 반환해
     * 호출자가 명백히 이상한 값을 보게 하는 편이 조용히 잘못된 시각을 주는 것보다 낫다. */
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return (int64_t) ts.tv_sec * 1000000000LL + (int64_t) ts.tv_nsec;
}

static void format_wall_utc(struct timespec ts, char *buf, size_t buf_size)
{
    struct tm tm_utc;
    gmtime_r(&ts.tv_sec, &tm_utc);
    char date_part[24];
    strftime(date_part, sizeof(date_part), "%Y-%m-%dT%H:%M:%S", &tm_utc);
    long microsecond = ts.tv_nsec / 1000;
    snprintf(buf, buf_size, "%s.%06ldZ", date_part, microsecond);
}

void ksi_format_wall_utc_now(char *buf, size_t buf_size)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) != 0) {
        snprintf(buf, buf_size, "1970-01-01T00:00:00.000000Z");
        return;
    }
    format_wall_utc(ts, buf, buf_size);
}

void ksi_capture_clock_anchor(int64_t *out_mono_ns, char *wall_utc_buf, size_t wall_utc_buf_size)
{
    /* 두 clock_gettime 호출 사이의 스케줄링 지연이 앵커 오차의 유일한 원인이다.
     * 여기서 더 줄일 수는 없다(같은 스레드에서 뗄 수 없는 두 syscall) — Python 쪽이
     * 이 앵커의 오차를 신뢰 구간으로 보정하고 싶다면 meta 줄에 두 값이 나란히 있으니
     * capture 전후로 자체적으로 한 번 더 재는 방식으로 상한을 잴 수 있다. */
    *out_mono_ns = ksi_mono_now_ns();
    ksi_format_wall_utc_now(wall_utc_buf, wall_utc_buf_size);
}

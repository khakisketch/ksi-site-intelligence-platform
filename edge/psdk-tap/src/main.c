/* edge/psdk-tap — PSDK liveview + FC subscription 콜백을 raw NDJSON 으로 적는 CLI.
 *
 * 이 파일은 오케스트레이션만 한다 — 판정 로직은 없다(설계 요점: "수집기는 판정하지
 * 않는다"). 짝짓기 순수 로직은 pairing.c, 스레드 공유 상태는 shared_state.c, PSDK
 * OS 추상화 계층은 src/platform/ 아래 각 소스 파일에 있다.
 */
#include <dji_core.h>
#include <dji_typedef.h>
#include <dji_version.h>

/* 빌드 입력 — 소스가 아니다. config/dji_sdk_app_info.h.example 을 복사해서 만든다.
 * 없으면 CMake configure 단계에서 이미 실패했을 것이다(레포에 없으면 이 #include 는
 * 개발자 로컬 빌드에서만 성립한다 — README 참조). */
#include "dji_sdk_app_info.h"

#include <getopt.h>
#include <inttypes.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "psdk_tap/clock_util.h"
#include "psdk_tap/liveview_tap.h"
#include "psdk_tap/ndjson_writer.h"
#include "psdk_tap/perception_tap.h"
#include "psdk_tap/shared_state.h"
#include "psdk_tap/telemetry_tap.h"
#include "platform/logger_console_glue.h"
#include "platform/osal_glue.h"
#include "platform/socket_glue.h"
#include "platform/usb_bulk_glue.h"

#define KSI_TAP_VERSION 2
#define KSI_TELEMETRY_RING_CAPACITY 512  /* 400Hz 로 약 1.28초치 버퍼 */
#define KSI_POLL_INTERVAL_NS 200000000LL /* 시그널을 200ms 내 반응성으로 관측한다 */

/* DPK service는 argv 없이 실행한다. HIL에서 perception raw-timestamp probe를 설치할
 * 때만 CMake cache 입력으로 기본 source를 바꾼다. 일반 DPK의 안전한 기본값은 계속
 * Liveview H264다. */
#ifndef KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE
#define KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE "liveview"
#endif
#ifndef KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION
#define KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION "front"
#endif

typedef enum {
    KSI_TAP_INPUT_LIVEVIEW = 0,
    KSI_TAP_INPUT_PERCEPTION = 1,
} ksi_tap_input_source_t;

typedef struct {
    int64_t num_samples;
    const char *out_path;
    int camera_index;      /* 1..3 */
    bool camera_source_4k; /* false=vis(기본) */
    ksi_tap_input_source_t frame_source;
    ksi_perception_direction_t perception_direction;
    int64_t duration_sec;
    const char *aircraft_sn; /* NULL 허용 — PSDK 는 기체 SN 을 payload 에 노출하지 않는다 */
} ksi_cli_args_t;

static volatile sig_atomic_t g_signal_requested = 0;

static void OnTerminationSignal(int signum)
{
    (void) signum;
    g_signal_requested = 1;
}

static void PrintUsage(const char *argv0)
{
    fprintf(stderr,
            "사용법: %s --num-samples N --out PATH [--camera-index 1|2|3]\n"
            "         [--camera-source vis|4k] [--frame-source liveview|perception]\n"
            "         [--perception-direction down|front|rear|up|left|right]\n"
            "         [--duration-sec N] [--aircraft-sn SN]\n",
            argv0);
}

static bool ParseFrameSource(const char *value, ksi_tap_input_source_t *out)
{
    if (strcmp(value, "liveview") == 0) {
        *out = KSI_TAP_INPUT_LIVEVIEW;
        return true;
    }
    if (strcmp(value, "perception") == 0) {
        *out = KSI_TAP_INPUT_PERCEPTION;
        return true;
    }
    return false;
}

static bool ParsePerceptionDirection(const char *value, ksi_perception_direction_t *out)
{
    if (strcmp(value, "down") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_DOWN;
    } else if (strcmp(value, "front") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_FRONT;
    } else if (strcmp(value, "rear") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_REAR;
    } else if (strcmp(value, "up") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_UP;
    } else if (strcmp(value, "left") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_LEFT;
    } else if (strcmp(value, "right") == 0) {
        *out = KSI_PERCEPTION_DIRECTION_RIGHT;
    } else {
        return false;
    }
    return true;
}

static const char *FrameSourceName(ksi_tap_input_source_t source)
{
    return source == KSI_TAP_INPUT_PERCEPTION ? "perception_grayscale" : "liveview_h264";
}

static const char *FrameTimestampProvenance(ksi_tap_input_source_t source)
{
    return source == KSI_TAP_INPUT_PERCEPTION
               ? "perception_image_info_timestamp_raw_unverified"
               : "liveview_callback_receive_monotonic_only";
}

static bool ParseArgs(int argc, char **argv, ksi_cli_args_t *args)
{
    args->num_samples = -1;
    args->out_path = NULL;
    args->camera_index = 1;
    args->camera_source_4k = false;
    if (!ParseFrameSource(KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE, &args->frame_source)) {
        fprintf(stderr, "빌드 기본 KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE가 잘못됐다: %s\n",
                KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE);
        return false;
    }
    if (!ParsePerceptionDirection(KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION,
                                  &args->perception_direction)) {
        fprintf(stderr, "빌드 기본 KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION가 잘못됐다: %s\n",
                KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION);
        return false;
    }
    args->duration_sec = 60;
    args->aircraft_sn = NULL;

    enum {
        OPT_NUM_SAMPLES = 1000,
        OPT_OUT,
        OPT_CAMERA_INDEX,
        OPT_CAMERA_SOURCE,
        OPT_FRAME_SOURCE,
        OPT_PERCEPTION_DIRECTION,
        OPT_DURATION_SEC,
        OPT_AIRCRAFT_SN,
        OPT_HELP,
    };
    static const struct option kLongOptions[] = {
        {"num-samples", required_argument, NULL, OPT_NUM_SAMPLES},
        {"out", required_argument, NULL, OPT_OUT},
        {"camera-index", required_argument, NULL, OPT_CAMERA_INDEX},
        {"camera-source", required_argument, NULL, OPT_CAMERA_SOURCE},
        {"frame-source", required_argument, NULL, OPT_FRAME_SOURCE},
        {"perception-direction", required_argument, NULL, OPT_PERCEPTION_DIRECTION},
        {"duration-sec", required_argument, NULL, OPT_DURATION_SEC},
        {"aircraft-sn", required_argument, NULL, OPT_AIRCRAFT_SN},
        {"help", no_argument, NULL, OPT_HELP},
        {NULL, 0, NULL, 0},
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "", kLongOptions, NULL)) != -1) {
        switch (opt) {
            case OPT_NUM_SAMPLES:
                args->num_samples = strtoll(optarg, NULL, 10);
                break;
            case OPT_OUT:
                args->out_path = optarg;
                break;
            case OPT_CAMERA_INDEX:
                args->camera_index = (int) strtol(optarg, NULL, 10);
                break;
            case OPT_CAMERA_SOURCE:
                if (strcmp(optarg, "vis") == 0) {
                    args->camera_source_4k = false;
                } else if (strcmp(optarg, "4k") == 0) {
                    args->camera_source_4k = true;
                } else {
                    fprintf(stderr, "--camera-source 는 vis 또는 4k 여야 한다: %s\n", optarg);
                    return false;
                }
                break;
            case OPT_FRAME_SOURCE:
                if (!ParseFrameSource(optarg, &args->frame_source)) {
                    fprintf(stderr, "--frame-source 는 liveview 또는 perception 이어야 한다: %s\n", optarg);
                    return false;
                }
                break;
            case OPT_PERCEPTION_DIRECTION:
                if (!ParsePerceptionDirection(optarg, &args->perception_direction)) {
                    fprintf(stderr,
                            "--perception-direction 은 down|front|rear|up|left|right 중 하나여야 한다: %s\n",
                            optarg);
                    return false;
                }
                break;
            case OPT_DURATION_SEC:
                args->duration_sec = strtoll(optarg, NULL, 10);
                break;
            case OPT_AIRCRAFT_SN:
                args->aircraft_sn = optarg;
                break;
            case OPT_HELP:
                PrintUsage(argv[0]);
                exit(0);
            default:
                PrintUsage(argv[0]);
                return false;
        }
    }

    /* --num-samples 생략 시 unbounded(<=0, shared_state.h 의 기존 규약 그대로) —
     * DJI 앱 프레임워크(dji_app_mgr)가 dpk 로 설치한 앱을 systemd 서비스로 기동할 때
     * 인자 없이 실행한다(2026-08-12 실기 실측: ExecStart 가 무인자로 우리 바이너리를
     * 불렀고, 그때 이 필드가 필수였던 탓에 exit(2)/INVALIDARGUMENT 로 설치가 통째로
     * 롤백됐다 — dji_app_mgr 로그 'upgrade_start_third_psdk_app failed' 3회 재시도 후
     * 'app install fail'). --duration-sec 는 여전히 기본 60초로 유한하다(무인자 실행이
     * 무한정 도는 것은 원치 않는다 — 필요하면 --duration-sec 로 늘린다). */
    if (args->out_path == NULL || args->out_path[0] == '\0') {
        args->out_path = "/tmp/ksi-psdk-tap.ndjson";
    }
    if (args->camera_index < 1 || args->camera_index > 3) {
        fprintf(stderr, "--camera-index 는 1, 2, 3 중 하나여야 한다\n");
        return false;
    }
    if (args->duration_sec <= 0) {
        fprintf(stderr, "--duration-sec 는 0보다 커야 한다\n");
        return false;
    }
    return true;
}

static bool IsPlaceholderCredential(void)
{
    return strcmp(USER_APP_NAME, "your_app_name") == 0 || strcmp(USER_APP_ID, "your_app_id") == 0 ||
           strcmp(USER_APP_KEY, "your_app_key") == 0 || strcmp(USER_APP_LICENSE, "your_app_license") == 0 ||
           strcmp(USER_DEVELOPER_ACCOUNT, "your_developer_account") == 0;
}

static bool FillUserInfo(T_DjiUserInfo *user_info)
{
    memset(user_info, 0, sizeof(*user_info));

    if (strlen(USER_APP_NAME) >= sizeof(user_info->appName) ||
        strlen(USER_APP_ID) > sizeof(user_info->appId) ||
        strlen(USER_APP_KEY) > sizeof(user_info->appKey) ||
        strlen(USER_APP_LICENSE) > sizeof(user_info->appLicense) ||
        strlen(USER_DEVELOPER_ACCOUNT) >= sizeof(user_info->developerAccount) ||
        strlen(USER_BAUD_RATE) > sizeof(user_info->baudRate)) {
        fprintf(stderr, "dji_sdk_app_info.h 의 필드 길이가 한도를 넘는다\n");
        return false;
    }

    strncpy(user_info->appName, USER_APP_NAME, sizeof(user_info->appName) - 1);
    memcpy(user_info->appId, USER_APP_ID, strlen(USER_APP_ID));
    memcpy(user_info->appKey, USER_APP_KEY, strlen(USER_APP_KEY));
    memcpy(user_info->appLicense, USER_APP_LICENSE, strlen(USER_APP_LICENSE));
    memcpy(user_info->baudRate, USER_BAUD_RATE, strlen(USER_BAUD_RATE));
    strncpy(user_info->developerAccount, USER_DEVELOPER_ACCOUNT, sizeof(user_info->developerAccount) - 1);
    return true;
}

int main(int argc, char **argv)
{
    ksi_cli_args_t args;
    if (!ParseArgs(argc, argv, &args)) {
        return 2;
    }

    if (IsPlaceholderCredential()) {
        fprintf(stderr,
                "config/dji_sdk_app_info.h 가 플레이스홀더 값 그대로다 — developer.dji.com "
                "앱 정보로 채운 실제 파일을 만들어라(edge/psdk-tap/README.md 참조).\n");
        return 2;
    }

    ksi_ndjson_writer_t writer;
    if (!ksi_ndjson_open(&writer, args.out_path)) {
        fprintf(stderr, "출력 파일을 열 수 없다: %s\n", args.out_path);
        return 2;
    }

    ksi_shared_state_t state;
    if (!ksi_shared_state_init(&state, KSI_TELEMETRY_RING_CAPACITY, args.num_samples, &writer)) {
        fprintf(stderr, "shared_state 초기화 실패(메모리 부족?)\n");
        ksi_ndjson_close(&writer);
        return 2;
    }

    /* --- meta 줄: 아직 아무 콜백도 등록하기 전에, 앵커부터 최대한 이르게 찍는다. --- */
    char started_at_utc[KSI_WALL_UTC_BUF_SIZE];
    ksi_format_wall_utc_now(started_at_utc, sizeof(started_at_utc));
    int64_t anchor_mono_ns = 0;
    char anchor_wall_utc[KSI_WALL_UTC_BUF_SIZE];
    ksi_capture_clock_anchor(&anchor_mono_ns, anchor_wall_utc, sizeof(anchor_wall_utc));

    char psdk_version[32];
    snprintf(psdk_version, sizeof(psdk_version), "%d.%d.%d", DJI_VERSION_MAJOR, DJI_VERSION_MINOR,
             DJI_VERSION_MODIFY);

    /* capabilities: Liveview에는 sensor timestamp가 없고, Perception raw timestamp도
     * unit/domain이 아직 검증되지 않았으므로 frame_sensor_ts는 어느 mode에서도 false다.
     * FC subscription은 T_DjiDataTimestamp를 싣지만 host CLOCK_MONOTONIC과 같은 domain
     * 이라는 근거가 없다. 따라서 sensor_us_domain=unverified를 raw log 계약에 명시해
     * Python converter가 --timestamp-basis sensor를 fail-closed하게 한다. */
    ksi_ndjson_write_meta(&writer, KSI_TAP_VERSION, psdk_version, started_at_utc, args.aircraft_sn,
                           anchor_mono_ns, anchor_wall_utc, /*frame_sensor_ts=*/false,
                           /*telemetry_sensor_ts=*/true, FrameSourceName(args.frame_source),
                           FrameTimestampProvenance(args.frame_source), "unverified");

    /* --- 시스템 환경 준비: Osal 은 모든 PSDK 앱에 필수, Socket 은 liveview 에 필수,
     * UsbBulk 는 Manifold3 의 CONFIG_HARDWARE_CONNECTION=USB_BULK 에 필수. --- */
    T_DjiReturnCode rc;
    rc = KsiOsalGlue_Register();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "Osal 핸들러 등록 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        goto fail_before_core;
    }
    (void) KsiLoggerConsoleGlue_Register(); /* 실패해도 치명적이지 않다 — 진단용 */
    rc = KsiSocketGlue_Register();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "Socket 핸들러 등록 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        goto fail_before_core;
    }
    rc = KsiUsbBulkGlue_Register();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "UsbBulk 핸들러 등록 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        goto fail_before_core;
    }

    T_DjiUserInfo user_info;
    if (!FillUserInfo(&user_info)) {
        goto fail_before_core;
    }

    /* 이 호출은 실기 연결을 기다린다(문서상 통상 2~4초, PSDK 가 올바른 기체 타입을 얻을
     * 때까지 반환하지 않는다) — 실기가 물려 있지 않으면 여기서 블로킹되거나 타임아웃
     * 오류를 반환한다. 이 워크스테이션에는 실기가 없으므로 여기까지가 이 작업의 검증
     * 범위다(README 참조). */
    rc = DjiCore_Init(&user_info);
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "DjiCore_Init 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        goto fail_before_core;
    }

    /* DjiCore_Init 만으로는 부족하다 — dji_app_mgr(dpk 로 설치된 앱을 systemd 로 기동한
     * 뒤 "app_upgrade_verify_real_app_id_info_after_start_app" 로 앱에게 신원 확인
     * 메시지를 보낸다)가 이 호출 전에는 응답을 받지 못한다. 2026-08-12 실기 실측:
     * 이 호출 없이 설치하면 dji_app_mgr 로그에 "send message to psdk app fail,
     * result = -1002"가 5회 재시도 끝에 실패로 끝나고 설치가 롤백됐다(result=53).
     * 레퍼런스 샘플(edge/third_party/psdk/samples/sample_c/platform/linux/manifold3/
     * application/main.c)도 DjiCore_Init 직후 모듈 등록을 마치고 이 호출로 마무리한다
     * — 이 호출이 SDK를 "앱이 살아있고 요청에 응답 가능한 상태"로 전환하는 지점이다. */
    rc = DjiCore_ApplicationStart();
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "DjiCore_ApplicationStart 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        goto fail_before_core;
    }

    struct sigaction signal_action;
    memset(&signal_action, 0, sizeof(signal_action));
    signal_action.sa_handler = OnTerminationSignal;
    sigaction(SIGINT, &signal_action, NULL);
    sigaction(SIGTERM, &signal_action, NULL);

    /* telemetry 를 먼저 켜서 첫 프레임이 도착하기 전에 링에 telemetry 표본이 쌓이게
     * 한다 — frames_dropped_no_telemetry 를 줄이려는 순서일 뿐, 정확성 요구사항은
     * 아니다. */
    rc = KsiTelemetryTap_Start(&state);
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "telemetry 구독 시작 실패: 0x%08" PRIX64 "\n", (uint64_t) rc);
        ksi_ndjson_write_stat(&writer, 0, 0, 0, 0, args.num_samples, "error", true);
        ksi_shared_state_destroy(&state);
        ksi_ndjson_close(&writer);
        return 1;
    }

    ksi_liveview_config_t liveview_config = {
        .camera_position_index = args.camera_index,
        .camera_source_4k = args.camera_source_4k,
    };
    ksi_perception_config_t perception_config = {
        .direction = args.perception_direction,
    };
    if (args.frame_source == KSI_TAP_INPUT_LIVEVIEW) {
        rc = KsiLiveviewTap_Start(&liveview_config, &state);
    } else {
        rc = KsiPerceptionTap_Start(&perception_config, &state);
    }
    if (rc != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        fprintf(stderr, "%s source 시작 실패: 0x%08" PRIX64 "\n", FrameSourceName(args.frame_source),
                (uint64_t) rc);
        KsiTelemetryTap_Stop();
        ksi_ndjson_write_stat(&writer, 0, 0, 0, 0, args.num_samples, "error", true);
        ksi_shared_state_destroy(&state);
        ksi_ndjson_close(&writer);
        return 1;
    }

    /* --- 메인 대기 루프: 목표 표본 수 도달, --duration-sec 초과, 시그널 중 먼저 오는
     * 것으로 끝난다. 200ms 간격으로 깨어나 시그널 플래그를 확인한다 — 시그널 핸들러
     * 안에서 뮤텍스/조건변수를 직접 건드리지 않는다(async-signal-safety). --- */
    int64_t overall_deadline_ns = ksi_mono_now_ns() + args.duration_sec * 1000000000LL;
    while (true) {
        int64_t now_ns = ksi_mono_now_ns();
        if (now_ns >= overall_deadline_ns) {
            ksi_shared_state_request_stop(&state, "duration_exceeded");
            break;
        }
        int64_t poll_deadline_ns = now_ns + KSI_POLL_INTERVAL_NS;
        if (poll_deadline_ns > overall_deadline_ns) {
            poll_deadline_ns = overall_deadline_ns;
        }
        if (ksi_shared_state_wait_done(&state, poll_deadline_ns)) {
            break; /* 목표 표본 수 도달 — state.stop_reason 은 이미 "num_samples_reached" */
        }
        if (g_signal_requested) {
            ksi_shared_state_request_stop(&state, "signal");
            break;
        }
    }

    if (args.frame_source == KSI_TAP_INPUT_LIVEVIEW) {
        KsiLiveviewTap_Stop(&liveview_config);
    } else {
        KsiPerceptionTap_Stop(&perception_config);
    }
    KsiTelemetryTap_Stop();
    /* DjiCore_DeInit 은 최선 노력으로만 부른다 — 실기 미연결 상태에서의 동작은
     * 이 작업 범위 밖(실기 미검증)이라 반환값을 치명적 오류로 취급하지 않는다. */
    (void) DjiCore_DeInit();

    pthread_mutex_lock(&state.mutex);
    uint64_t frames_received = state.frames_received;
    uint64_t telemetry_received = state.telemetry_received;
    int64_t samples_written = state.samples_written;
    uint64_t frames_dropped = state.frames_dropped_no_telemetry;
    const char *stop_reason = state.stop_reason != NULL ? state.stop_reason : "unknown";
    pthread_mutex_unlock(&state.mutex);

    bool insufficient = samples_written < args.num_samples;
    ksi_ndjson_write_stat(&writer, frames_received, telemetry_received, (uint64_t) samples_written,
                           frames_dropped, args.num_samples, stop_reason, insufficient);

    ksi_shared_state_destroy(&state);
    ksi_ndjson_close(&writer);

    /* 명세: "표본을 다 못 채우고 끝나면 ... 0이 아닌 종료코드로 끝나라 — 부족한
     * 표본으로 조용히 성공하면 안 된다." */
    return insufficient ? 1 : 0;

fail_before_core:
    ksi_ndjson_write_stat(&writer, 0, 0, 0, 0, args.num_samples, "error", true);
    ksi_shared_state_destroy(&state);
    ksi_ndjson_close(&writer);
    return 1;
}

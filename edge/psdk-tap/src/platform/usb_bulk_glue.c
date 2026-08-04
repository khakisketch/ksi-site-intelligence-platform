#include "usb_bulk_glue.h"

#include <dji_platform.h>

#ifdef LIBUSB_INSTALLED
#include <libusb-1.0/libusb.h>
#endif

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Manifold3/M4-계열 USB gadget 이 노출하는 것으로 관측된 고정 VID/PID·채널 표.
 * 출처: edge/third_party/psdk/samples/sample_c/platform/linux/manifold3/hal/hal_usb_bulk.h
 * (LINUX_USB_VID/PID, LINUX_USB_BULK{1,2,3}_* 매크로) — 벤더 샘플의 하드코딩된 상수를
 * 그대로 옮긴 값이며 실기로 재검증되지 않았다(README 참조). */
#define KSI_USB_VID 0x2CA3u
#define KSI_USB_PID 0x3181u

static const T_DjiHalUsbBulkChannelInfo kKnownManifold3Channels[DJI_HAL_USB_BULK_NUM_MAX] = {
    {.interfaceNum = 2, .endPointIn = 0x83, .endPointOut = 0x02},
    {.interfaceNum = 6, .endPointIn = 0x87, .endPointOut = 0x06},
    {.interfaceNum = 3, .endPointIn = 0x84, .endPointOut = 0x03},
};

typedef struct {
    bool is_usb_host;
    int ep_in_fd;  /* device 모드(FunctionFS)에서만 유효 */
    int ep_out_fd; /* device 모드(FunctionFS)에서만 유효 */
#ifdef LIBUSB_INSTALLED
    libusb_context *usb_context;         /* host 모드에서만 유효 */
    libusb_device_handle *usb_handle;    /* host 모드에서만 유효 */
    int interface_num;
    uint8_t endpoint_in;
    uint8_t endpoint_out;
#endif
} KsiUsbBulkChannel;

/* 호스트 실측(2026-08-04, 하드웨어 없는 aarch64 워크스테이션)에서 실제로 관측한 문제:
 * UsbBulkInit 이 실패(SYSTEM_ERROR)를 반환했는데도 PSDK 코어(DjiAccessAdapter_Init →
 * DjiAccessAdapter_IdentifyAircraftSeries)가 곧이어 UsbBulkWriteData 를 호출했고, 그때
 * 넘어온 usbBulkHandle 이 우리가 절대 반환한 적 없는 값이었다(Init 실패 경로에서는
 * *usbBulkHandle 을 건드리지 않고 그냥 return 하므로, PSDK 내부의 미초기화 메모리가
 * 그대로 넘어온 것으로 보인다) — 그 값을 그대로 역참조해 SIGSEGV 로 죽었다(gdb 백트레이스
 * 확보, README 참조). PSDK 자체(.a 블롭)의 실패 경로 처리를 우리가 고칠 수는 없으니,
 * 우리 경계에서 "우리가 실제로 내준 핸들인가"를 확인하는 방어선을 둔다 — 모르는 핸들이면
 * 역참조하지 않고 INVALID_PARAMETER 로 정직하게 실패한다(세그폴트 대신). */
#define KSI_USB_BULK_MAX_ACTIVE_CHANNELS 8
static KsiUsbBulkChannel *g_active_channels[KSI_USB_BULK_MAX_ACTIVE_CHANNELS];
static pthread_mutex_t g_active_channels_mutex = PTHREAD_MUTEX_INITIALIZER;

static bool RegisterActiveChannel(KsiUsbBulkChannel *channel)
{
    bool registered = false;
    pthread_mutex_lock(&g_active_channels_mutex);
    for (int i = 0; i < KSI_USB_BULK_MAX_ACTIVE_CHANNELS; ++i) {
        if (g_active_channels[i] == NULL) {
            g_active_channels[i] = channel;
            registered = true;
            break;
        }
    }
    pthread_mutex_unlock(&g_active_channels_mutex);
    return registered;
}

static void UnregisterActiveChannel(const KsiUsbBulkChannel *channel)
{
    pthread_mutex_lock(&g_active_channels_mutex);
    for (int i = 0; i < KSI_USB_BULK_MAX_ACTIVE_CHANNELS; ++i) {
        if (g_active_channels[i] == channel) {
            g_active_channels[i] = NULL;
            break;
        }
    }
    pthread_mutex_unlock(&g_active_channels_mutex);
}

static bool IsActiveChannel(const void *handle)
{
    bool found = false;
    pthread_mutex_lock(&g_active_channels_mutex);
    for (int i = 0; i < KSI_USB_BULK_MAX_ACTIVE_CHANNELS; ++i) {
        if (g_active_channels[i] == handle) {
            found = true;
            break;
        }
    }
    pthread_mutex_unlock(&g_active_channels_mutex);
    return found;
}

static T_DjiReturnCode InitDeviceModeChannel(KsiUsbBulkChannel *channel, uint16_t interfaceNum)
{
    char in_path[64];
    char out_path[64];
    /* 폴더명 == interfaceNum, ep2=IN, ep1=OUT — 벤더 샘플의 세 하드코딩 예시에서
     * 관측된 규칙을 일반화한 것(usb_bulk_glue.h 상단 주석 참조). */
    snprintf(in_path, sizeof(in_path), "/dev/usb-ffs/bulk%u/ep2", (unsigned) interfaceNum);
    snprintf(out_path, sizeof(out_path), "/dev/usb-ffs/bulk%u/ep1", (unsigned) interfaceNum);

    channel->ep_in_fd = open(in_path, O_RDWR);
    if (channel->ep_in_fd < 0) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    channel->ep_out_fd = open(out_path, O_RDWR);
    if (channel->ep_out_fd < 0) {
        close(channel->ep_in_fd);
        channel->ep_in_fd = -1;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

#ifdef LIBUSB_INSTALLED
static T_DjiReturnCode InitHostModeChannel(KsiUsbBulkChannel *channel, T_DjiHalUsbBulkInfo info)
{
    if (libusb_init(&channel->usb_context) != 0) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    channel->usb_handle = libusb_open_device_with_vid_pid(channel->usb_context, info.vid, info.pid);
    if (channel->usb_handle == NULL) {
        libusb_exit(channel->usb_context);
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    channel->interface_num = info.channelInfo.interfaceNum;
    channel->endpoint_in = (uint8_t) info.channelInfo.endPointIn;
    channel->endpoint_out = (uint8_t) info.channelInfo.endPointOut;
    if (libusb_claim_interface(channel->usb_handle, channel->interface_num) != 0) {
        libusb_close(channel->usb_handle);
        libusb_exit(channel->usb_context);
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}
#endif

static T_DjiReturnCode KsiUsbBulk_Init(T_DjiHalUsbBulkInfo usbBulkInfo, T_DjiUsbBulkHandle *usbBulkHandle)
{
    KsiUsbBulkChannel *channel = calloc(1, sizeof(KsiUsbBulkChannel));
    if (channel == NULL) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_MEMORY_ALLOC_FAILED;
    }
    channel->ep_in_fd = -1;
    channel->ep_out_fd = -1;
    channel->is_usb_host = usbBulkInfo.isUsbHost;

    T_DjiReturnCode result;
    if (!usbBulkInfo.isUsbHost) {
        result = InitDeviceModeChannel(channel, usbBulkInfo.channelInfo.interfaceNum);
    } else {
#ifdef LIBUSB_INSTALLED
        result = InitHostModeChannel(channel, usbBulkInfo);
#else
        /* libusb-1.0 dev 헤더가 빌드 환경에 없다 — 지어낸 성공을 반환하지 않는다.
         * README 의 "libusb 없이 호스트 검증" 절 참조. */
        result = DJI_ERROR_SYSTEM_MODULE_CODE_NONSUPPORT;
#endif
    }

    if (result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        free(channel);
        return result;
    }
    if (!RegisterActiveChannel(channel)) {
        /* 동시 채널이 KSI_USB_BULK_MAX_ACTIVE_CHANNELS 를 넘는 비정상 상황 — 실제로는
         * Manifold3 이 채널 3개(DJI_HAL_USB_BULK_NUM_MAX)만 쓰므로 발생하지 않아야
         * 한다. 조용히 반쪽짜리 핸들을 내주지 않고 자원을 정리한 뒤 실패시킨다. */
        if (!channel->is_usb_host) {
            close(channel->ep_in_fd);
            close(channel->ep_out_fd);
        }
#ifdef LIBUSB_INSTALLED
        else if (channel->usb_handle != NULL) {
            libusb_release_interface(channel->usb_handle, channel->interface_num);
            libusb_close(channel->usb_handle);
            libusb_exit(channel->usb_context);
        }
#endif
        free(channel);
        return DJI_ERROR_SYSTEM_MODULE_CODE_MEMORY_ALLOC_FAILED;
    }
    *usbBulkHandle = channel;
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

static T_DjiReturnCode KsiUsbBulk_DeInit(T_DjiUsbBulkHandle usbBulkHandle)
{
    if (usbBulkHandle == NULL || !IsActiveChannel(usbBulkHandle)) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_INVALID_PARAMETER;
    }
    KsiUsbBulkChannel *channel = (KsiUsbBulkChannel *) usbBulkHandle;
    UnregisterActiveChannel(channel);
    if (!channel->is_usb_host) {
        if (channel->ep_in_fd >= 0) {
            close(channel->ep_in_fd);
        }
        if (channel->ep_out_fd >= 0) {
            close(channel->ep_out_fd);
        }
    }
#ifdef LIBUSB_INSTALLED
    else {
        if (channel->usb_handle != NULL) {
            libusb_release_interface(channel->usb_handle, channel->interface_num);
            libusb_close(channel->usb_handle);
        }
        if (channel->usb_context != NULL) {
            libusb_exit(channel->usb_context);
        }
    }
#endif
    free(channel);
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

static T_DjiReturnCode KsiUsbBulk_WriteData(T_DjiUsbBulkHandle usbBulkHandle, const uint8_t *buf, uint32_t len,
                                             uint32_t *realLen)
{
    if (!IsActiveChannel(usbBulkHandle)) {
        /* 우리가 내준 적 없는 핸들 — 위 주석 참조(호스트 실측에서 실제로 관측된 경로).
         * 역참조하지 않고 정직하게 실패한다. */
        *realLen = 0;
        return DJI_ERROR_SYSTEM_MODULE_CODE_INVALID_PARAMETER;
    }
    KsiUsbBulkChannel *channel = (KsiUsbBulkChannel *) usbBulkHandle;
    if (!channel->is_usb_host) {
        ssize_t written = write(channel->ep_out_fd, buf, len);
        if (written < 0) {
            *realLen = 0;
            return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
        }
        *realLen = (uint32_t) written;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    }
#ifdef LIBUSB_INSTALLED
    int transferred = 0;
    int rc = libusb_bulk_transfer(channel->usb_handle, channel->endpoint_out, (unsigned char *) buf,
                                   (int) len, &transferred, 0);
    if (rc != 0) {
        *realLen = 0;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    *realLen = (uint32_t) transferred;
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
#else
    *realLen = 0;
    return DJI_ERROR_SYSTEM_MODULE_CODE_NONSUPPORT;
#endif
}

static T_DjiReturnCode KsiUsbBulk_ReadData(T_DjiUsbBulkHandle usbBulkHandle, uint8_t *buf, uint32_t len,
                                            uint32_t *realLen)
{
    if (!IsActiveChannel(usbBulkHandle)) {
        *realLen = 0;
        return DJI_ERROR_SYSTEM_MODULE_CODE_INVALID_PARAMETER;
    }
    KsiUsbBulkChannel *channel = (KsiUsbBulkChannel *) usbBulkHandle;
    if (!channel->is_usb_host) {
        ssize_t bytes_read = read(channel->ep_in_fd, buf, len);
        if (bytes_read < 0) {
            *realLen = 0;
            return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
        }
        *realLen = (uint32_t) bytes_read;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    }
#ifdef LIBUSB_INSTALLED
    int transferred = 0;
    int rc = libusb_bulk_transfer(channel->usb_handle, channel->endpoint_in, buf, (int) len, &transferred, 0);
    if (rc != 0) {
        *realLen = 0;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    *realLen = (uint32_t) transferred;
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
#else
    *realLen = 0;
    return DJI_ERROR_SYSTEM_MODULE_CODE_NONSUPPORT;
#endif
}

static T_DjiReturnCode KsiUsbBulk_GetDeviceInfo(T_DjiHalUsbBulkDeviceInfo *deviceInfo)
{
    if (deviceInfo == NULL) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_INVALID_PARAMETER;
    }
    deviceInfo->vid = KSI_USB_VID;
    deviceInfo->pid = KSI_USB_PID;
    memcpy(deviceInfo->channelInfo, kKnownManifold3Channels, sizeof(kKnownManifold3Channels));
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode KsiUsbBulkGlue_Register(void)
{
    T_DjiHalUsbBulkHandler handler = {
        .UsbBulkInit = KsiUsbBulk_Init,
        .UsbBulkDeInit = KsiUsbBulk_DeInit,
        .UsbBulkWriteData = KsiUsbBulk_WriteData,
        .UsbBulkReadData = KsiUsbBulk_ReadData,
        .UsbBulkGetDeviceInfo = KsiUsbBulk_GetDeviceInfo,
    };
    return DjiPlatform_RegHalUsbBulkHandler(&handler);
}

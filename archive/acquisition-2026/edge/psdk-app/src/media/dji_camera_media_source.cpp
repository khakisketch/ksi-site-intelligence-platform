#include "media/dji_camera_media_source.hpp"

#include <algorithm>
#include <atomic>
#include <cstring>
#include <limits>

#include <dji_error.h>

namespace ksi::psdk {

namespace {

constexpr std::uint16_t kMaximumCameraFileCount = 10'000U;
std::mutex g_callback_slot_mutex;
std::atomic<DjiCameraManagerMediaSourcePort*> g_callback_owner{nullptr};

bool IsSafeCameraFileName(const std::string& name) {
    if (name.empty() || name.size() > 255U) {
        return false;
    }
    return std::all_of(name.begin(), name.end(), [](char character) {
        const unsigned char byte = static_cast<unsigned char>(character);
        return byte >= 0x20U && byte != 0x7FU && character != '/' && character != '\\';
    });
}

bool CopyCameraFileName(const char source[DJI_FILE_NAME_SIZE_MAX], std::string* output) {
    if (output == nullptr) {
        return false;
    }
    const void* terminator = std::memchr(source, '\0', DJI_FILE_NAME_SIZE_MAX);
    if (terminator == nullptr) {
        return false;
    }
    const std::size_t size = static_cast<const char*>(terminator) - source;
    std::string name(source, size);
    if (!IsSafeCameraFileName(name)) {
        return false;
    }
    *output = std::move(name);
    return true;
}

bool IsValidHandle(const edge::SourceMediaFileHandle& file, std::uint64_t maximum_bytes) {
    return file.source_file_index >= 0 &&
           static_cast<std::uint64_t>(file.source_file_index) <=
               static_cast<std::uint64_t>(std::numeric_limits<uint32_t>::max()) &&
           file.announced_bytes > 0U && file.announced_bytes <= maximum_bytes &&
           IsSafeCameraFileName(file.camera_file_name);
}

}  // namespace

DjiCameraManagerApi DjiCameraManagerApi::FromSdk() {
    return DjiCameraManagerApi{
        &DjiCameraManager_ObtainDownloaderRights,
        &DjiCameraManager_ReleaseDownloaderRights,
        &DjiCameraManager_DownloadFileList,
        &DjiCameraManager_RegDownloadFileDataCallback,
        &DjiCameraManager_DownloadFileByIndex,
    };
}

bool DjiCameraManagerApi::complete() const {
    return obtain_downloader_rights != nullptr && release_downloader_rights != nullptr &&
           download_file_list != nullptr && register_download_callback != nullptr &&
           download_file_by_index != nullptr;
}

DjiCameraManagerMediaSourcePort::DjiCameraManagerMediaSourcePort(
    E_DjiMountPosition position, DjiCameraManagerApi api, std::uint64_t maximum_download_bytes)
    : position_(position), api_(api), maximum_download_bytes_(maximum_download_bytes) {
    if (!api_.complete() || maximum_download_bytes_ == 0U) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_callback_slot_mutex);
    DjiCameraManagerMediaSourcePort* expected = nullptr;
    owns_callback_slot_ = g_callback_owner.compare_exchange_strong(expected, this,
                                                                      std::memory_order_acq_rel);
}

DjiCameraManagerMediaSourcePort::~DjiCameraManagerMediaSourcePort() {
    if (!owns_callback_slot_) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_callback_slot_mutex);
    DjiCameraManagerMediaSourcePort* expected = this;
    (void)g_callback_owner.compare_exchange_strong(expected, nullptr, std::memory_order_acq_rel);
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::MapResult(T_DjiReturnCode result,
                                                                      bool rights_operation) {
    if (result == DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
        return edge::MediaSourceVerdict::kCompleted;
    }
    if (result == DJI_ERROR_SYSTEM_MODULE_CODE_BUSY ||
        result == DJI_ERROR_CAMERA_MANAGER_MODULE_CODE_UNSUPPORTED_COMMAND_IN_CUR_STATE) {
        return rights_operation ? edge::MediaSourceVerdict::kRightsUnavailable
                                : edge::MediaSourceVerdict::kTransientFailure;
    }
    if (result == DJI_ERROR_CAMERA_MANAGER_MODULE_CODE_UNSUPPORTED_COMMAND ||
        result == DJI_ERROR_CAMERA_MANAGER_MODULE_CODE_INVALID_COMMAND_PARAMETER ||
        result == DJI_ERROR_CAMERA_MANAGER_MODULE_CODE_SD_CARD_MISSING) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    return edge::MediaSourceVerdict::kTransientFailure;
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::ObtainRights() {
    if (!owns_callback_slot_ || !api_.complete()) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    std::lock_guard<std::mutex> operation_lock(operation_mutex_);
    return MapResult(api_.obtain_downloader_rights(position_), true);
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::ReleaseRights() {
    if (!owns_callback_slot_ || !api_.complete()) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    std::lock_guard<std::mutex> operation_lock(operation_mutex_);
    return MapResult(api_.release_downloader_rights(position_), true);
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::ListFiles(
    std::vector<edge::SourceMediaFileHandle>* files) {
    if (files == nullptr || !owns_callback_slot_ || !api_.complete()) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    std::lock_guard<std::mutex> operation_lock(operation_mutex_);
    T_DjiCameraManagerFileList list{};
    const edge::MediaSourceVerdict result = MapResult(api_.download_file_list(position_, &list));
    if (result != edge::MediaSourceVerdict::kCompleted) {
        return result;
    }
    if (list.totalCount > kMaximumCameraFileCount ||
        (list.totalCount > 0U && list.fileListInfo == nullptr)) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    std::vector<edge::SourceMediaFileHandle> copied;
    copied.reserve(list.totalCount);
    for (uint16_t index = 0U; index < list.totalCount; ++index) {
        const T_DjiCameraManagerFileListInfo& source = list.fileListInfo[index];
        // v1 deliberately transfers only original JPEG.  Video/LDRT/subfiles
        // are not a partial substitute for the photogrammetry source bundle.
        if (source.type != DJI_CAMERA_FILE_TYPE_JPEG) {
            continue;
        }
        edge::SourceMediaFileHandle file;
        file.source_file_index = static_cast<std::int64_t>(source.fileIndex);
        file.announced_bytes = static_cast<std::uint64_t>(source.fileSize);
        if (!CopyCameraFileName(source.fileName, &file.camera_file_name) ||
            !IsValidHandle(file, maximum_download_bytes_)) {
            return edge::MediaSourceVerdict::kPermanentFailure;
        }
        copied.push_back(std::move(file));
    }
    *files = std::move(copied);
    return edge::MediaSourceVerdict::kCompleted;
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::EnsureCallbackRegistered() {
    if (!owns_callback_slot_ || !api_.complete()) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    if (callback_registered_) {
        return edge::MediaSourceVerdict::kCompleted;
    }
    const edge::MediaSourceVerdict result =
        MapResult(api_.register_download_callback(position_, &DjiCameraManagerMediaSourcePort::OnDownloadData));
    if (result == edge::MediaSourceVerdict::kCompleted) {
        callback_registered_ = true;
    }
    return result;
}

bool DjiCameraManagerMediaSourcePort::IsExpectedPacket(
    const T_DjiDownloadFilePacketInfo& packet_info) const {
    return download_.active && packet_info.fileType == DJI_DOWNLOAD_FILE_ORG &&
           packet_info.fileIndex == static_cast<uint32_t>(download_.expected.source_file_index) &&
           packet_info.fileSize == download_.expected.announced_bytes;
}

bool DjiCameraManagerMediaSourcePort::AppendPacketBytes(const uint8_t* data, uint16_t data_length) {
    if (data_length > 0U && data == nullptr) {
        return false;
    }
    const std::uint64_t next_size = static_cast<std::uint64_t>(download_.bytes.size()) +
                                    static_cast<std::uint64_t>(data_length);
    if (next_size > download_.expected.announced_bytes || next_size > maximum_download_bytes_) {
        return false;
    }
    if (data_length > 0U) {
        download_.bytes.insert(download_.bytes.end(), data, data + data_length);
    }
    return true;
}

T_DjiReturnCode DjiCameraManagerMediaSourcePort::OnDownloadData(
    T_DjiDownloadFilePacketInfo packet_info, const uint8_t* data, uint16_t data_length) {
    DjiCameraManagerMediaSourcePort* const port =
        g_callback_owner.load(std::memory_order_acquire);
    if (port == nullptr) {
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    return port->HandleDownloadData(packet_info, data, data_length);
}

T_DjiReturnCode DjiCameraManagerMediaSourcePort::HandleDownloadData(
    T_DjiDownloadFilePacketInfo packet_info, const uint8_t* data, uint16_t data_length) {
    std::lock_guard<std::mutex> state_lock(state_mutex_);
    if (!IsExpectedPacket(packet_info) || download_.finished) {
        download_.malformed = true;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    switch (packet_info.downloadFileEvent) {
        case DJI_DOWNLOAD_FILE_EVENT_START:
            if (download_.started) {
                download_.malformed = true;
                return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
            }
            download_.started = true;
            break;
        case DJI_DOWNLOAD_FILE_EVENT_TRANSFER:
            if (!download_.started) {
                download_.malformed = true;
                return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
            }
            break;
        case DJI_DOWNLOAD_FILE_EVENT_END:
            if (!download_.started) {
                download_.malformed = true;
                return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
            }
            break;
        case DJI_DOWNLOAD_FILE_EVENT_START_TRANSFER_END:
            if (download_.started) {
                download_.malformed = true;
                return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
            }
            download_.started = true;
            break;
        default:
            download_.malformed = true;
            return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    if (!AppendPacketBytes(data, data_length)) {
        download_.malformed = true;
        return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
    }
    if (packet_info.downloadFileEvent == DJI_DOWNLOAD_FILE_EVENT_END ||
        packet_info.downloadFileEvent == DJI_DOWNLOAD_FILE_EVENT_START_TRANSFER_END) {
        download_.finished = true;
    }
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

edge::MediaSourceVerdict DjiCameraManagerMediaSourcePort::DownloadFile(
    const edge::SourceMediaFileHandle& file, std::vector<std::uint8_t>* bytes) {
    if (bytes == nullptr || !owns_callback_slot_ || !api_.complete() ||
        !IsValidHandle(file, maximum_download_bytes_)) {
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    std::lock_guard<std::mutex> operation_lock(operation_mutex_);
    const edge::MediaSourceVerdict callback = EnsureCallbackRegistered();
    if (callback != edge::MediaSourceVerdict::kCompleted) {
        return callback;
    }
    {
        std::lock_guard<std::mutex> state_lock(state_mutex_);
        download_ = DownloadState{};
        download_.active = true;
        download_.expected = file;
        download_.bytes.reserve(static_cast<std::size_t>(file.announced_bytes));
    }
    const edge::MediaSourceVerdict invocation =
        MapResult(api_.download_file_by_index(position_, static_cast<uint32_t>(file.source_file_index)));
    std::lock_guard<std::mutex> state_lock(state_mutex_);
    if (invocation != edge::MediaSourceVerdict::kCompleted) {
        download_ = DownloadState{};
        return invocation;
    }
    if (download_.malformed || !download_.started || !download_.finished ||
        download_.bytes.size() != file.announced_bytes) {
        download_ = DownloadState{};
        return edge::MediaSourceVerdict::kPermanentFailure;
    }
    *bytes = std::move(download_.bytes);
    download_ = DownloadState{};
    return edge::MediaSourceVerdict::kCompleted;
}

}  // namespace ksi::psdk

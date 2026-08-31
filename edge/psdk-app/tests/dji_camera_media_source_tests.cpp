#include "media/dji_camera_media_source.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using ksi::edge::MediaSourceVerdict;
using ksi::edge::SourceMediaFileHandle;
using ksi::psdk::DjiCameraManagerApi;
using ksi::psdk::DjiCameraManagerMediaSourcePort;

struct FakeCameraManager {
    static inline T_DjiReturnCode obtain_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    static inline T_DjiReturnCode release_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    static inline T_DjiReturnCode list_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    static inline T_DjiReturnCode register_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    static inline T_DjiReturnCode download_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    static inline DjiCameraManagerDownloadFileDataCallback callback = nullptr;
    static inline std::vector<T_DjiCameraManagerFileListInfo> files;
    static inline std::vector<std::uint8_t> payload;
    static inline bool emit_bad_size = false;
    static inline bool emit_without_end = false;
    static inline int obtain_calls = 0;
    static inline int release_calls = 0;
    static inline int list_calls = 0;
    static inline int register_calls = 0;
    static inline int download_calls = 0;

    static void Reset() {
        obtain_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
        release_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
        list_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
        register_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
        download_result = DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
        callback = nullptr;
        files.clear();
        payload.clear();
        emit_bad_size = false;
        emit_without_end = false;
        obtain_calls = 0;
        release_calls = 0;
        list_calls = 0;
        register_calls = 0;
        download_calls = 0;
    }

    static T_DjiReturnCode Obtain(E_DjiMountPosition) {
        ++obtain_calls;
        return obtain_result;
    }
    static T_DjiReturnCode Release(E_DjiMountPosition) {
        ++release_calls;
        return release_result;
    }
    static T_DjiReturnCode List(E_DjiMountPosition, T_DjiCameraManagerFileList* output) {
        ++list_calls;
        if (output != nullptr) {
            output->totalCount = static_cast<uint16_t>(files.size());
            output->fileListInfo = files.empty() ? nullptr : files.data();
        }
        return list_result;
    }
    static T_DjiReturnCode Register(E_DjiMountPosition, DjiCameraManagerDownloadFileDataCallback value) {
        ++register_calls;
        callback = value;
        return register_result;
    }
    static T_DjiReturnCode Download(E_DjiMountPosition, uint32_t index) {
        ++download_calls;
        if (download_result != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS || callback == nullptr) {
            return download_result;
        }
        const auto found = std::find_if(files.begin(), files.end(), [index](const auto& file) {
            return file.fileIndex == index;
        });
        if (found == files.end()) {
            return DJI_ERROR_CAMERA_MANAGER_MODULE_CODE_INVALID_COMMAND_PARAMETER;
        }
        T_DjiDownloadFilePacketInfo packet{};
        packet.fileType = DJI_DOWNLOAD_FILE_ORG;
        packet.fileIndex = index;
        packet.fileSize = emit_bad_size ? found->fileSize + 1U : found->fileSize;
        packet.downloadFileEvent = DJI_DOWNLOAD_FILE_EVENT_START;
        if (callback(packet, payload.data(), static_cast<uint16_t>(payload.size())) !=
            DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
            return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
        }
        if (!emit_without_end) {
            packet.downloadFileEvent = DJI_DOWNLOAD_FILE_EVENT_END;
            if (callback(packet, nullptr, 0U) != DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS) {
                return DJI_ERROR_SYSTEM_MODULE_CODE_SYSTEM_ERROR;
            }
        }
        return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
    }

    static DjiCameraManagerApi Api() {
        return DjiCameraManagerApi{&Obtain, &Release, &List, &Register, &Download};
    }
};

void Check(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

T_DjiCameraManagerFileListInfo MakeFile(uint32_t index, uint32_t bytes, E_DjiCameraMediaFileType type,
                                         const char* name) {
    T_DjiCameraManagerFileListInfo result{};
    result.fileIndex = index;
    result.fileSize = bytes;
    result.type = type;
    std::snprintf(result.fileName, sizeof(result.fileName), "%s", name);
    return result;
}

SourceMediaFileHandle Handle(uint32_t index, uint32_t bytes, const char* name) {
    return SourceMediaFileHandle{static_cast<std::int64_t>(index), name, bytes};
}

bool SameHandle(const SourceMediaFileHandle& left, const SourceMediaFileHandle& right) {
    return left.source_file_index == right.source_file_index &&
           left.camera_file_name == right.camera_file_name &&
           left.announced_bytes == right.announced_bytes;
}

void TestListFiltersAndCopies() {
    FakeCameraManager::Reset();
    FakeCameraManager::files.push_back(MakeFile(7U, 4U, DJI_CAMERA_FILE_TYPE_JPEG, "DJI_0007.JPG"));
    FakeCameraManager::files.push_back(MakeFile(8U, 9U, DJI_CAMERA_FILE_TYPE_MP4, "DJI_0008.MP4"));
    DjiCameraManagerMediaSourcePort port(DJI_MOUNT_POSITION_PAYLOAD_PORT_NO1,
                                         FakeCameraManager::Api(), 1024U);
    std::vector<SourceMediaFileHandle> files;
    Check(port.ListFiles(&files) == MediaSourceVerdict::kCompleted, "JPEG list must succeed");
    Check(files.size() == 1U && SameHandle(files[0], Handle(7U, 4U, "DJI_0007.JPG")),
          "only exact JPEG file identity may leave adapter");
}

void TestDownloadValidatesCallbackStream() {
    FakeCameraManager::Reset();
    FakeCameraManager::files.push_back(MakeFile(7U, 4U, DJI_CAMERA_FILE_TYPE_JPEG, "DJI_0007.JPG"));
    FakeCameraManager::payload = {'J', 'P', 'E', 'G'};
    DjiCameraManagerMediaSourcePort port(DJI_MOUNT_POSITION_PAYLOAD_PORT_NO1,
                                         FakeCameraManager::Api(), 1024U);
    std::vector<std::uint8_t> bytes;
    Check(port.DownloadFile(Handle(7U, 4U, "DJI_0007.JPG"), &bytes) ==
              MediaSourceVerdict::kCompleted,
          "valid callback sequence must download");
    Check(bytes == FakeCameraManager::payload && FakeCameraManager::register_calls == 1,
          "adapter must retain exact callback bytes and register once");
}

void TestDownloadRejectsCallbackDrift() {
    FakeCameraManager::Reset();
    FakeCameraManager::files.push_back(MakeFile(7U, 4U, DJI_CAMERA_FILE_TYPE_JPEG, "DJI_0007.JPG"));
    FakeCameraManager::payload = {'J', 'P', 'E', 'G'};
    FakeCameraManager::emit_bad_size = true;
    DjiCameraManagerMediaSourcePort port(DJI_MOUNT_POSITION_PAYLOAD_PORT_NO1,
                                         FakeCameraManager::Api(), 1024U);
    std::vector<std::uint8_t> bytes;
    Check(port.DownloadFile(Handle(7U, 4U, "DJI_0007.JPG"), &bytes) ==
              MediaSourceVerdict::kTransientFailure,
          "vendor callback refusal must not produce bytes");
    FakeCameraManager::emit_bad_size = false;
    FakeCameraManager::emit_without_end = true;
    Check(port.DownloadFile(Handle(7U, 4U, "DJI_0007.JPG"), &bytes) ==
              MediaSourceVerdict::kPermanentFailure,
          "incomplete callback stream must fail closed");
}

void TestRightsAndSingleCallbackOwner() {
    FakeCameraManager::Reset();
    FakeCameraManager::obtain_result = DJI_ERROR_SYSTEM_MODULE_CODE_BUSY;
    DjiCameraManagerMediaSourcePort first(DJI_MOUNT_POSITION_PAYLOAD_PORT_NO1,
                                          FakeCameraManager::Api(), 1024U);
    Check(first.ObtainRights() == MediaSourceVerdict::kRightsUnavailable,
          "busy downloader rights must be retryable rights-unavailable");
    DjiCameraManagerMediaSourcePort second(DJI_MOUNT_POSITION_PAYLOAD_PORT_NO1,
                                           FakeCameraManager::Api(), 1024U);
    Check(second.ObtainRights() == MediaSourceVerdict::kPermanentFailure,
          "second callback owner must fail closed");
}

}  // namespace

int main() {
    try {
        TestListFiltersAndCopies();
        TestDownloadValidatesCallbackStream();
        TestDownloadRejectsCallbackDrift();
        TestRightsAndSingleCallbackOwner();
    } catch (const std::exception& exception) {
        std::fprintf(stderr, "psdk media source test failed: %s\n", exception.what());
        return 1;
    }
    std::puts("psdk media source tests passed");
    return 0;
}

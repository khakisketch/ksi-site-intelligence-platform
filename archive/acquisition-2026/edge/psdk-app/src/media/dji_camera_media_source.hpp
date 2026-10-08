// Thin, fail-closed PSDK Camera Manager adapter for the generic source-media
// conveyor.  The conveyor and journal deliberately stay PSDK-free; this file
// is the only place that translates DJI Camera Manager list/download/rights
// calls into IMediaSourcePort.

#ifndef KSI_PSDK_APP_DJI_CAMERA_MEDIA_SOURCE_HPP
#define KSI_PSDK_APP_DJI_CAMERA_MEDIA_SOURCE_HPP

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include <dji_camera_manager.h>

#include "ksi/edge/media_offload.hpp"

namespace ksi::psdk {

// Kept injectable so the adapter is contract-tested without an aircraft or a
// vendor static archive performing I/O.  It is intentionally the small
// read/download surface only: no delete, format, capture, gimbal, flight, or
// camera-setting function can enter through this table.
struct DjiCameraManagerApi {
    T_DjiReturnCode (*obtain_downloader_rights)(E_DjiMountPosition position) = nullptr;
    T_DjiReturnCode (*release_downloader_rights)(E_DjiMountPosition position) = nullptr;
    T_DjiReturnCode (*download_file_list)(E_DjiMountPosition position,
                                          T_DjiCameraManagerFileList* output) = nullptr;
    T_DjiReturnCode (*register_download_callback)(
        E_DjiMountPosition position, DjiCameraManagerDownloadFileDataCallback callback) = nullptr;
    T_DjiReturnCode (*download_file_by_index)(E_DjiMountPosition position, uint32_t file_index) =
        nullptr;

    static DjiCameraManagerApi FromSdk();
    bool complete() const;
};

// Camera Manager only exposes one C callback per mount.  KSI serializes
// downloads and permits exactly one live adapter process; constructing a
// second adapter fails closed rather than letting callbacks cross-wire bytes.
class DjiCameraManagerMediaSourcePort final : public edge::IMediaSourcePort {
public:
    DjiCameraManagerMediaSourcePort(E_DjiMountPosition position, DjiCameraManagerApi api,
                                    std::uint64_t maximum_download_bytes);
    ~DjiCameraManagerMediaSourcePort() override;

    DjiCameraManagerMediaSourcePort(const DjiCameraManagerMediaSourcePort&) = delete;
    DjiCameraManagerMediaSourcePort& operator=(const DjiCameraManagerMediaSourcePort&) = delete;

    edge::MediaSourceVerdict ObtainRights() override;
    edge::MediaSourceVerdict ReleaseRights() override;
    edge::MediaSourceVerdict ListFiles(std::vector<edge::SourceMediaFileHandle>* files) override;
    edge::MediaSourceVerdict DownloadFile(const edge::SourceMediaFileHandle& file,
                                          std::vector<std::uint8_t>* bytes) override;

private:
    struct DownloadState {
        bool active = false;
        bool started = false;
        bool finished = false;
        bool malformed = false;
        edge::SourceMediaFileHandle expected;
        std::vector<std::uint8_t> bytes;
    };

    static T_DjiReturnCode OnDownloadData(T_DjiDownloadFilePacketInfo packet_info,
                                          const uint8_t* data, uint16_t data_length);
    T_DjiReturnCode HandleDownloadData(T_DjiDownloadFilePacketInfo packet_info,
                                       const uint8_t* data, uint16_t data_length);
    edge::MediaSourceVerdict EnsureCallbackRegistered();
    static edge::MediaSourceVerdict MapResult(T_DjiReturnCode result,
                                               bool rights_operation = false);
    bool IsExpectedPacket(const T_DjiDownloadFilePacketInfo& packet_info) const;
    bool AppendPacketBytes(const uint8_t* data, uint16_t data_length);

    E_DjiMountPosition position_;
    DjiCameraManagerApi api_;
    std::uint64_t maximum_download_bytes_;
    bool owns_callback_slot_ = false;
    bool callback_registered_ = false;
    std::mutex operation_mutex_;
    std::mutex state_mutex_;
    DownloadState download_;
};

}  // namespace ksi::psdk

#endif  // KSI_PSDK_APP_DJI_CAMERA_MEDIA_SOURCE_HPP

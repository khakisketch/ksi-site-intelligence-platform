#include "ksi/edge/media_offload.hpp"

#include "ksi/edge/crypto.hpp"
#include "ksi/edge/jpeg_dimensions.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <filesystem>
#include <map>
#include <set>
#include <stdexcept>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ksi::edge {

namespace {

constexpr std::size_t kMaximumMediaIdBytes = 120U;
constexpr std::size_t kMediaIdSuffixHexDigits = 8U;
constexpr std::size_t kMaximumSpoolArtifactIdBytes = 200U;
constexpr char kRightsMarkerContents[] = "KSI_EDGE_SOURCE_MEDIA_RIGHTS_HELD_V1\n";

bool IsAsciiAlphaNumeric(unsigned char value) {
    return (value >= static_cast<unsigned char>('a') && value <= static_cast<unsigned char>('z')) ||
           (value >= static_cast<unsigned char>('A') && value <= static_cast<unsigned char>('Z')) ||
           (value >= static_cast<unsigned char>('0') && value <= static_cast<unsigned char>('9'));
}

bool IsMediaIdCharacter(char character) {
    const unsigned char value = static_cast<unsigned char>(character);
    return IsAsciiAlphaNumeric(value) || character == '.' || character == '_' || character == '-';
}

// 활성화 스냅샷 디렉터리와 같은 성질을 요구한다: 우리 소유, group/other 권한 없음,
// 심링크 아님. rights marker 는 "앨범이 잠겼을 수 있다"는 사실의 유일한 증거라,
// 남이 쓸 수 있는 자리에 두면 그 증거가 증거가 아니다.
bool EnsurePrivateStateDirectory(const std::filesystem::path& directory) {
    std::error_code error;
    if (!std::filesystem::create_directories(directory, error) && error) {
        return false;
    }
    struct stat value {};
    if (lstat(directory.c_str(), &value) != 0 || !S_ISDIR(value.st_mode) || S_ISLNK(value.st_mode) ||
        value.st_uid != geteuid()) {
        return false;
    }
    if ((value.st_mode & 0077) != 0 && chmod(directory.c_str(), 0700) != 0) {
        return false;
    }
    return lstat(directory.c_str(), &value) == 0 && (value.st_mode & 0077) == 0;
}

bool FsyncDirectory(const std::filesystem::path& directory) {
    const int descriptor = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        return false;
    }
    const bool success = fsync(descriptor) == 0;
    (void)close(descriptor);
    return success;
}

bool WritePrivateMarker(const std::filesystem::path& path) {
    const int descriptor = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0) {
        return false;
    }
    const std::size_t length = sizeof(kRightsMarkerContents) - 1U;
    std::size_t written = 0U;
    bool ok = true;
    while (written < length) {
        const ssize_t result = write(descriptor, kRightsMarkerContents + written, length - written);
        if (result > 0) {
            written += static_cast<std::size_t>(result);
            continue;
        }
        if (result < 0 && errno == EINTR) {
            continue;
        }
        ok = false;
        break;
    }
    ok = ok && fsync(descriptor) == 0;
    const bool closed = close(descriptor) == 0;
    return ok && closed && FsyncDirectory(path.parent_path());
}

bool MarkerExists(const std::filesystem::path& path) {
    struct stat value {};
    return lstat(path.c_str(), &value) == 0 && S_ISREG(value.st_mode);
}

bool RemoveMarker(const std::filesystem::path& path) {
    if (unlink(path.c_str()) != 0 && errno != ENOENT) {
        return false;
    }
    return FsyncDirectory(path.parent_path());
}

std::string MediaIdSuffix(const std::string& camera_file_name) {
    const std::string digest = Sha256Digest(
        reinterpret_cast<const std::uint8_t*>(camera_file_name.data()), camera_file_name.size());
    // "sha256:" 뒤 8 자리. 빈 digest 는 Sha256Digest 의 fail-closed 결과라 그대로 흘린다.
    return IsSha256Digest(digest) ? digest.substr(7U, kMediaIdSuffixHexDigits) : std::string{};
}

}  // namespace

const char* ToString(MediaSourceVerdict verdict) {
    switch (verdict) {
        case MediaSourceVerdict::kCompleted:
            return "COMPLETED";
        case MediaSourceVerdict::kRightsUnavailable:
            return "RIGHTS_UNAVAILABLE";
        case MediaSourceVerdict::kTransientFailure:
            return "TRANSIENT_FAILURE";
        case MediaSourceVerdict::kPermanentFailure:
            return "PERMANENT_FAILURE";
    }
    return "UNKNOWN";
}

const char* ToString(MediaRightsVerdict verdict) {
    switch (verdict) {
        case MediaRightsVerdict::kHeld:
            return "HELD";
        case MediaRightsVerdict::kReleased:
            return "RELEASED";
        case MediaRightsVerdict::kNotHeld:
            return "NOT_HELD";
        case MediaRightsVerdict::kUnsafeStateDirectory:
            return "UNSAFE_STATE_DIRECTORY";
        case MediaRightsVerdict::kMarkerWriteFailed:
            return "MARKER_WRITE_FAILED";
        case MediaRightsVerdict::kSourceRefused:
            return "SOURCE_REFUSED";
    }
    return "UNKNOWN";
}

const char* ToString(MediaOffloadVerdict verdict) {
    switch (verdict) {
        case MediaOffloadVerdict::kCompleted:
            return "COMPLETED";
        case MediaOffloadVerdict::kProgressed:
            return "PROGRESSED";
        case MediaOffloadVerdict::kSpoolHighWater:
            return "SPOOL_HIGH_WATER";
        case MediaOffloadVerdict::kRightsUnavailable:
            return "RIGHTS_UNAVAILABLE";
        case MediaOffloadVerdict::kSourceFailure:
            return "SOURCE_FAILURE";
        case MediaOffloadVerdict::kTransportFailure:
            return "TRANSPORT_FAILURE";
        case MediaOffloadVerdict::kJournalFailure:
            return "JOURNAL_FAILURE";
        case MediaOffloadVerdict::kSpoolFailure:
            return "SPOOL_FAILURE";
        case MediaOffloadVerdict::kMediaIdCollision:
            return "MEDIA_ID_COLLISION";
        case MediaOffloadVerdict::kQuarantineBlocked:
            return "QUARANTINE_BLOCKED";
    }
    return "UNKNOWN";
}

std::string DeriveMediaId(const std::string& camera_file_name) {
    // 1. 마지막 확장자를 뗀다. 맨 앞의 '.' 은 확장자 구분자가 아니다.
    const std::size_t dot = camera_file_name.find_last_of('.');
    const std::string stem =
        (dot == std::string::npos || dot == 0U) ? camera_file_name : camera_file_name.substr(0U, dot);
    // 2. 허용 문자 밖의 연속 구간 하나를 '-' 하나로.
    std::string collapsed;
    collapsed.reserve(stem.size());
    bool in_replacement = false;
    for (const char character : stem) {
        if (IsMediaIdCharacter(character)) {
            collapsed.push_back(character);
            in_replacement = false;
            continue;
        }
        if (!in_replacement) {
            collapsed.push_back('-');
            in_replacement = true;
        }
    }
    // 3. 맨 앞의 영숫자 아닌 문자를 버린다.
    std::size_t start = 0U;
    while (start < collapsed.size() &&
           !IsAsciiAlphaNumeric(static_cast<unsigned char>(collapsed[start]))) {
        ++start;
    }
    std::string result = collapsed.substr(start);
    // 4~5. 비면 "media", 그리고 120 자로 자른다.
    if (result.empty()) {
        result = "media";
    }
    if (result.size() > kMaximumMediaIdBytes) {
        result.resize(kMaximumMediaIdBytes);
    }
    return result;
}

bool AssignMediaIds(const std::vector<std::string>& camera_file_names,
                    std::vector<std::string>* media_ids) {
    if (media_ids == nullptr) {
        return false;
    }
    media_ids->clear();
    std::set<std::string> distinct_names;
    std::map<std::string, std::size_t> base_usage;
    for (const std::string& name : camera_file_names) {
        if (name.empty() || !distinct_names.insert(name).second) {
            // 같은 파일명이 두 번 나오면 어떤 접미사를 붙여도 갈라지지 않는다.
            return false;
        }
        base_usage[DeriveMediaId(name)] += 1U;
    }
    std::set<std::string> assigned;
    for (const std::string& name : camera_file_names) {
        const std::string base = DeriveMediaId(name);
        std::string media_id = base;
        if (base_usage[base] > 1U) {
            const std::string suffix = MediaIdSuffix(name);
            if (suffix.size() != kMediaIdSuffixHexDigits) {
                return false;
            }
            const std::size_t room = kMaximumMediaIdBytes - (kMediaIdSuffixHexDigits + 1U);
            media_id = base.substr(0U, std::min(base.size(), room)) + "-" + suffix;
        }
        if (!ArtifactVault::IsSafeArtifactId(media_id) || !assigned.insert(media_id).second) {
            return false;
        }
        media_ids->push_back(media_id);
    }
    return true;
}

// ── rights marker ───────────────────────────────────────────────────────────

MediaRightsVerdict ReconcileSourceMediaRightsMarker(const std::string& state_directory,
                                                    IMediaSourcePort* source) {
    if (state_directory.empty() || source == nullptr) {
        return MediaRightsVerdict::kUnsafeStateDirectory;
    }
    const std::filesystem::path directory(state_directory);
    if (!EnsurePrivateStateDirectory(directory)) {
        return MediaRightsVerdict::kUnsafeStateDirectory;
    }
    const std::filesystem::path marker = directory / kSourceMediaRightsMarkerFilename;
    if (!MarkerExists(marker)) {
        return MediaRightsVerdict::kNotHeld;
    }
    const MediaSourceVerdict released = source->ReleaseRights();
    if (released == MediaSourceVerdict::kCompleted || released == MediaSourceVerdict::kPermanentFailure) {
        // kPermanentFailure 는 "지금 잡고 있지 않다"로 읽는다. 여기서 marker 를
        // 남기면 자동 경로가 영영 뜨지 못한다.
        return RemoveMarker(marker) ? MediaRightsVerdict::kReleased
                                    : MediaRightsVerdict::kMarkerWriteFailed;
    }
    return MediaRightsVerdict::kSourceRefused;
}

MediaSourceRightsGuard::MediaSourceRightsGuard(std::string state_directory, IMediaSourcePort* source)
    : state_directory_(std::move(state_directory)), source_(source) {}

MediaSourceRightsGuard::~MediaSourceRightsGuard() {
    if (held_) {
        (void)Release();
    }
}

MediaRightsVerdict MediaSourceRightsGuard::Acquire() {
    if (source_ == nullptr || state_directory_.empty()) {
        return MediaRightsVerdict::kUnsafeStateDirectory;
    }
    if (held_) {
        return MediaRightsVerdict::kHeld;
    }
    const std::filesystem::path directory(state_directory_);
    if (!EnsurePrivateStateDirectory(directory)) {
        return MediaRightsVerdict::kUnsafeStateDirectory;
    }
    const std::filesystem::path marker = directory / kSourceMediaRightsMarkerFilename;
    // marker 를 **먼저** 쓴다. 반대 순서면 Obtain 직후 SIGKILL 이 났을 때 앨범이
    // 잠긴 채 아무 증거도 남지 않는다. 반대로 marker 만 남고 Obtain 이 실패한
    // 경우는 다음 기동이 불필요한 Release 를 한 번 내는 것으로 끝난다.
    if (!WritePrivateMarker(marker)) {
        return MediaRightsVerdict::kMarkerWriteFailed;
    }
    const MediaSourceVerdict obtained = source_->ObtainRights();
    if (obtained != MediaSourceVerdict::kCompleted) {
        (void)RemoveMarker(marker);
        return MediaRightsVerdict::kSourceRefused;
    }
    held_ = true;
    return MediaRightsVerdict::kHeld;
}

MediaRightsVerdict MediaSourceRightsGuard::Release() {
    if (source_ == nullptr || state_directory_.empty()) {
        return MediaRightsVerdict::kUnsafeStateDirectory;
    }
    if (!held_) {
        return MediaRightsVerdict::kNotHeld;
    }
    const MediaSourceVerdict released = source_->ReleaseRights();
    if (released != MediaSourceVerdict::kCompleted) {
        // marker 를 남긴다 — 다음 기동이 다시 시도한다.
        return MediaRightsVerdict::kSourceRefused;
    }
    held_ = false;
    const std::filesystem::path marker =
        std::filesystem::path(state_directory_) / kSourceMediaRightsMarkerFilename;
    return RemoveMarker(marker) ? MediaRightsVerdict::kReleased
                                : MediaRightsVerdict::kMarkerWriteFailed;
}

// ── 워커 ────────────────────────────────────────────────────────────────────

MediaOffloadWorker::MediaOffloadWorker(MediaOffloadPolicy policy, SqliteStoreForward* journal,
                                       ArtifactVault* spool, IMediaSourcePort* source,
                                       IEdgeSourceMediaTransport* transport)
    : policy_(std::move(policy)),
      journal_(journal),
      spool_(spool),
      source_(source),
      transport_(transport) {
    if (journal_ == nullptr || spool_ == nullptr || source_ == nullptr || transport_ == nullptr ||
        policy_.state_directory.empty() || policy_.spool_high_water_bytes == 0U ||
        policy_.spool_high_water_items == 0U) {
        throw std::invalid_argument("media offload worker requires ports, a state directory, and a "
                                    "non-zero spool high-water mark");
    }
}

std::string MediaOffloadWorker::SpoolArtifactId(const std::string& mission_id,
                                                const std::string& media_id) {
    if (!ArtifactVault::IsSafeArtifactId(mission_id) || !ArtifactVault::IsSafeArtifactId(media_id)) {
        return {};
    }
    // mission_id·media_id 둘 다 '-' 를 포함할 수 있어(IsSafeArtifactId 가
    // 허용) 단순 연결은 서로 다른 (mission_id, media_id) 쌍을 같은 문자열로
    // 뭉갤 수 있다 — 예: ("m", "1-x") 와 ("m-1", "x") 는 구분자 하나만으로는
    // 갈라지지 않는다. mission_id 의 **길이**를 숫자로 먼저 적고 숫자가 아닌
    // '.' 로 끝을 표시한다 — mission_id 안에 무슨 문자가 오든(숫자 포함) 이
    // 프리픽스는 항상 자기 서술적이라 두 쌍이 같은 문자열을 낼 수 없다.
    const std::string artifact_id =
        "srcmedia-" + std::to_string(mission_id.size()) + "." + mission_id + "-" + media_id;
    if (artifact_id.size() > kMaximumSpoolArtifactIdBytes) {
        return {};
    }
    return artifact_id;
}

void MediaOffloadWorker::Quarantine(const SourceMediaItemRecord& item, const std::string& reason,
                                    MediaOffloadReport* report) {
    // 격리는 자동 경로에서 빼는 것이지 사진을 잃는 것이 아니다 — 원본은 기체 SD
    // 카드에 있고 수동 경로로 올릴 수 있다. 그래서 경유지 사본은 지운다. 안
    // 지우면 격리된 장이 컨베이어를 막아 회수 전체가 멈춘다.
    if (!item.artifact_id.empty()) {
        (void)spool_->Remove(item.artifact_id);
    }
    const SourceMediaJournalVerdict verdict =
        journal_->QuarantineSourceMedia(item.mission_id, item.media_id, reason);
    if (verdict == SourceMediaJournalVerdict::kAccepted) {
        report->quarantined += 1U;
    }
}

bool MediaOffloadWorker::Discover(const std::string& mission_id, MediaOffloadReport* report) {
    std::vector<SourceMediaFileHandle> files;
    {
        MediaSourceRightsGuard guard(policy_.state_directory, source_);
        const MediaRightsVerdict rights = guard.Acquire();
        if (rights != MediaRightsVerdict::kHeld) {
            report->verdict = rights == MediaRightsVerdict::kSourceRefused
                                  ? MediaOffloadVerdict::kRightsUnavailable
                                  : MediaOffloadVerdict::kSourceFailure;
            return false;
        }
        if (source_->ListFiles(&files) != MediaSourceVerdict::kCompleted) {
            report->verdict = MediaOffloadVerdict::kSourceFailure;
            return false;
        }
    }
    std::vector<std::string> names;
    names.reserve(files.size());
    for (const SourceMediaFileHandle& file : files) {
        names.push_back(file.camera_file_name);
    }
    std::vector<std::string> media_ids;
    if (!AssignMediaIds(names, &media_ids)) {
        report->verdict = MediaOffloadVerdict::kMediaIdCollision;
        return false;
    }
    for (std::size_t index = 0U; index < files.size(); ++index) {
        const SourceMediaJournalVerdict recorded = journal_->RecordSourceMediaDiscovered(
            mission_id, media_ids[index], files[index].camera_file_name, files[index].announced_bytes);
        if (recorded == SourceMediaJournalVerdict::kAccepted) {
            report->discovered += 1U;
            continue;
        }
        if (recorded != SourceMediaJournalVerdict::kDuplicate) {
            report->verdict = MediaOffloadVerdict::kJournalFailure;
            return false;
        }
    }
    const SourceMediaJournalVerdict complete = journal_->MarkSourceMediaDiscoveryComplete(
        mission_id, static_cast<std::uint32_t>(files.size()));
    if (complete != SourceMediaJournalVerdict::kAccepted &&
        complete != SourceMediaJournalVerdict::kDuplicate) {
        report->verdict = MediaOffloadVerdict::kJournalFailure;
        return false;
    }
    return true;
}

std::size_t MediaOffloadWorker::Fill(const std::string& mission_id, MediaOffloadReport* report,
                                     bool* paused, bool* fatal) {
    const std::vector<SourceMediaItemRecord> pending =
        journal_->SourceMediaItemsInState(mission_id, SourceMediaState::kDiscovered);
    if (pending.empty()) {
        return 0U;
    }
    std::uint64_t spool_bytes = 0U;
    std::uint32_t spool_items = 0U;
    if (journal_->SourceMediaSpoolUsage(mission_id, &spool_bytes, &spool_items) !=
        SourceMediaJournalVerdict::kAccepted) {
        *fatal = true;
        report->verdict = MediaOffloadVerdict::kJournalFailure;
        return 0U;
    }
    // 권한은 카메라를 만지는 이 구간에서만 잡는다. 배출(네트워크)은 권한 없이
    // 진행되므로, 통신이 느린 동안 운영자의 앨범이 잠기지 않는다.
    MediaSourceRightsGuard guard(policy_.state_directory, source_);
    std::size_t progressed = 0U;
    for (const SourceMediaItemRecord& item : pending) {
        if (item.announced_bytes > policy_.spool_high_water_bytes) {
            // 한 장이 예산 전체보다 크면 배출로도 자리가 생기지 않는다 —
            // 컨베이어를 세우는 대신 그 장을 자동 경로에서 뺀다.
            Quarantine(item, "announced size exceeds the spool high-water mark", report);
            continue;
        }
        if (spool_items >= policy_.spool_high_water_items ||
            spool_bytes + item.announced_bytes > policy_.spool_high_water_bytes) {
            *paused = true;
            break;
        }
        if (!guard.held()) {
            const MediaRightsVerdict rights = guard.Acquire();
            if (rights != MediaRightsVerdict::kHeld) {
                *fatal = true;
                report->verdict = rights == MediaRightsVerdict::kSourceRefused
                                      ? MediaOffloadVerdict::kRightsUnavailable
                                      : MediaOffloadVerdict::kSourceFailure;
                break;
            }
        }
        SourceMediaFileHandle handle;
        handle.camera_file_name = item.camera_file_name;
        handle.announced_bytes = item.announced_bytes;
        std::vector<std::uint8_t> bytes;
        const MediaSourceVerdict downloaded = source_->DownloadFile(handle, &bytes);
        if (downloaded == MediaSourceVerdict::kPermanentFailure) {
            Quarantine(item, "camera refused this file permanently", report);
            continue;
        }
        if (downloaded != MediaSourceVerdict::kCompleted) {
            *fatal = true;
            report->verdict = downloaded == MediaSourceVerdict::kRightsUnavailable
                                  ? MediaOffloadVerdict::kRightsUnavailable
                                  : MediaOffloadVerdict::kSourceFailure;
            break;
        }
        // 화소수를 못 읽으면 값을 지어내지 않고 그 장을 격리한다.
        const JpegDimensionsResult dimensions = ReadJpegDimensions(bytes.data(), bytes.size());
        if (dimensions.verdict != JpegDimensionsVerdict::kParsed) {
            Quarantine(item, std::string("jpeg dimensions: ") + ToString(dimensions.verdict), report);
            continue;
        }
        const std::string artifact_id = SpoolArtifactId(mission_id, item.media_id);
        if (artifact_id.empty()) {
            *fatal = true;
            report->verdict = MediaOffloadVerdict::kSpoolFailure;
            break;
        }
        const ArtifactVaultResult persisted = spool_->Persist(artifact_id, bytes.data(), bytes.size());
        if (persisted.verdict == ArtifactVaultVerdict::kTooLarge ||
            persisted.verdict == ArtifactVaultVerdict::kConflict) {
            Quarantine(item, std::string("spool refused the bytes: ") + ToString(persisted.verdict),
                       report);
            continue;
        }
        if (persisted.verdict != ArtifactVaultVerdict::kPersisted &&
            persisted.verdict != ArtifactVaultVerdict::kDuplicate) {
            *fatal = true;
            report->verdict = MediaOffloadVerdict::kSpoolFailure;
            break;
        }
        SourceMediaItemRecord measured = item;
        measured.artifact_id = persisted.artifact.artifact_id;
        measured.local_path = persisted.artifact.local_path;
        measured.content_digest = persisted.artifact.content_digest;
        measured.byte_count = persisted.artifact.byte_count;
        measured.width = dimensions.dimensions.width;
        measured.height = dimensions.dimensions.height;
        // 화소수를 읽어낸 이상 이 바이트는 JPEG 다 — 신고 content type 을
        // 파일명이나 카메라 주장이 아니라 실측에서 얻는다.
        measured.content_type = "image/jpeg";
        const SourceMediaJournalVerdict spooled = journal_->MarkSourceMediaSpooled(measured);
        if (spooled != SourceMediaJournalVerdict::kAccepted &&
            spooled != SourceMediaJournalVerdict::kDuplicate) {
            *fatal = true;
            report->verdict = MediaOffloadVerdict::kJournalFailure;
            break;
        }
        spool_bytes += measured.byte_count;
        spool_items += 1U;
        report->spooled += 1U;
        progressed += 1U;
    }
    return progressed;
}

bool MediaOffloadWorker::PurgeItem(const SourceMediaItemRecord& item, MediaOffloadReport* report,
                                   bool* fatal) {
    const ArtifactRemovalVerdict removed = spool_->Remove(item.artifact_id);
    if (removed != ArtifactRemovalVerdict::kRemoved &&
        removed != ArtifactRemovalVerdict::kAlreadyAbsent) {
        *fatal = true;
        report->verdict = MediaOffloadVerdict::kSpoolFailure;
        return false;
    }
    const SourceMediaJournalVerdict purged =
        journal_->MarkSourceMediaPurged(item.mission_id, item.media_id);
    if (purged != SourceMediaJournalVerdict::kAccepted &&
        purged != SourceMediaJournalVerdict::kDuplicate) {
        *fatal = true;
        report->verdict = MediaOffloadVerdict::kJournalFailure;
        return false;
    }
    if (purged == SourceMediaJournalVerdict::kAccepted) {
        report->purged += 1U;
    }
    return true;
}

bool MediaOffloadWorker::PushItem(const SourceMediaItemRecord& item, MediaOffloadReport* report,
                                  bool* fatal) {
    SourceMediaUploadClaim claim;
    claim.media_id = item.media_id;
    claim.content_type = item.content_type;
    claim.content_digest = item.content_digest;
    claim.byte_count = item.byte_count;
    claim.width = item.width;
    claim.height = item.height;
    // URL 은 저장하지 않는다 — REGISTERED 로 재기동한 장도 여기서 새로 받는다.
    const SourceMediaRegistrationResult registration =
        transport_->RegisterSourceMedia(item.mission_id, claim);
    if (registration.verdict == CoreSyncVerdict::kPermanentFailure) {
        Quarantine(item, "Core rejected this registration permanently", report);
        return false;
    }
    if (registration.verdict != CoreSyncVerdict::kAcknowledged) {
        report->verdict = MediaOffloadVerdict::kTransportFailure;
        return false;
    }
    const SourceMediaJournalVerdict registered =
        journal_->MarkSourceMediaRegistered(item.mission_id, item.media_id);
    if (registered != SourceMediaJournalVerdict::kAccepted &&
        registered != SourceMediaJournalVerdict::kDuplicate) {
        *fatal = true;
        report->verdict = MediaOffloadVerdict::kJournalFailure;
        return false;
    }
    const CoreSyncVerdict put = transport_->PutSourceMedia(item, registration);
    if (put == CoreSyncVerdict::kPermanentFailure) {
        Quarantine(item, "storage rejected this upload permanently", report);
        return false;
    }
    if (put != CoreSyncVerdict::kAcknowledged) {
        report->verdict = MediaOffloadVerdict::kTransportFailure;
        return false;
    }
    // 업로드 사실을 durable 하게 굳힌 **뒤에** 바이트를 지운다. 반대 순서면
    // 그 사이의 전원 손실이 "올린 적 없는데 로컬에도 없는" 장을 만든다.
    const SourceMediaJournalVerdict uploaded =
        journal_->MarkSourceMediaUploaded(item.mission_id, item.media_id);
    if (uploaded != SourceMediaJournalVerdict::kAccepted &&
        uploaded != SourceMediaJournalVerdict::kDuplicate) {
        *fatal = true;
        report->verdict = MediaOffloadVerdict::kJournalFailure;
        return false;
    }
    if (uploaded == SourceMediaJournalVerdict::kAccepted) {
        report->uploaded += 1U;
    }
    if (test_only_after_uploaded_before_purge_hook) {
        test_only_after_uploaded_before_purge_hook(item);
    }
    return PurgeItem(item, report, fatal);
}

std::size_t MediaOffloadWorker::Drain(const std::string& mission_id, MediaOffloadReport* report,
                                      bool* fatal) {
    std::size_t progressed = 0U;
    // UPLOADED 를 먼저 본다 — 디스크를 가장 빨리 비우고, 재기동 복구(업로드는
    // 끝났는데 삭제 전에 죽은 경우)가 바로 여기로 들어온다.
    for (const SourceMediaItemRecord& item :
         journal_->SourceMediaItemsInState(mission_id, SourceMediaState::kUploaded)) {
        if (!PurgeItem(item, report, fatal)) {
            return progressed;
        }
        progressed += 1U;
    }
    for (const SourceMediaState state : {SourceMediaState::kRegistered, SourceMediaState::kSpooled}) {
        for (const SourceMediaItemRecord& item : journal_->SourceMediaItemsInState(mission_id, state)) {
            if (!PushItem(item, report, fatal)) {
                if (*fatal || report->verdict == MediaOffloadVerdict::kTransportFailure) {
                    return progressed;
                }
                // 격리된 장은 진행으로 세지 않지만 컨베이어는 계속 돈다.
                continue;
            }
            progressed += 1U;
        }
    }
    return progressed;
}

MediaOffloadReport MediaOffloadWorker::RunOnce(const std::string& mission_id,
                                               const std::string& edge_device_id) {
    MediaOffloadReport report;
    // 워커 수명당 정확히 한 번, 카메라를 건드리기(Discover/Fill 의 Obtain) 전에
    // 먼저 낸다. 이전 프로세스가 권한을 쥔 채 죽었으면 marker 가 남아 있고,
    // 그걸 정리하지 못하면 여기서 멈춘다 — 정리 안 된 채로 Obtain 을 또 내면
    // 운영자 쪽 앨범 잠금이 이중으로 꼬인다.
    if (!startup_rights_reconciled_) {
        const MediaRightsVerdict reconciled = ReconcileSourceMediaRightsMarker(
            policy_.state_directory, source_);
        if (reconciled != MediaRightsVerdict::kNotHeld && reconciled != MediaRightsVerdict::kReleased) {
            report.verdict = reconciled == MediaRightsVerdict::kSourceRefused
                                  ? MediaOffloadVerdict::kRightsUnavailable
                                  : MediaOffloadVerdict::kSourceFailure;
            return report;
        }
        startup_rights_reconciled_ = true;
    }
    const SourceMediaJournalVerdict begun =
        journal_->BeginSourceMediaMission(mission_id, edge_device_id);
    if (begun != SourceMediaJournalVerdict::kAccepted &&
        begun != SourceMediaJournalVerdict::kDuplicate) {
        report.verdict = MediaOffloadVerdict::kJournalFailure;
        return report;
    }
    SourceMediaMissionState mission;
    if (journal_->FindSourceMediaMission(mission_id, &mission) !=
        SourceMediaJournalVerdict::kAccepted) {
        report.verdict = MediaOffloadVerdict::kJournalFailure;
        return report;
    }
    if (mission.sealed) {
        report.verdict = MediaOffloadVerdict::kCompleted;
        report.sealed = true;
        return report;
    }
    if (!mission.discovery_complete && !Discover(mission_id, &report)) {
        return report;
    }

    bool fatal = false;
    bool paused = false;
    // 순환 상한: 목록 크기 + 2. 배출이 자리를 만들어 다시 받는 정상 교대를
    // 충분히 허용하면서, 어떤 버그도 무한 루프가 되지 않게 한다.
    SourceMediaMissionState after_discovery;
    (void)journal_->FindSourceMediaMission(mission_id, &after_discovery);
    const std::size_t maximum_cycles = static_cast<std::size_t>(after_discovery.discovered_count) + 2U;
    for (std::size_t cycle = 0U; cycle < maximum_cycles; ++cycle) {
        const std::size_t drained = Drain(mission_id, &report, &fatal);
        if (fatal || report.verdict == MediaOffloadVerdict::kTransportFailure) {
            break;
        }
        paused = false;
        const std::size_t filled = Fill(mission_id, &report, &paused, &fatal);
        if (fatal) {
            break;
        }
        if (paused) {
            // 고수위다. 이번 순환의 배출이 아무것도 못 비웠다면 더 돌아도
            // 자리가 생기지 않는다 — 다운로드를 멈춘 채로 돌려준다.
            if (drained == 0U) {
                report.download_paused_for_spool = true;
                break;
            }
            continue;
        }
        if (drained == 0U && filled == 0U) {
            break;
        }
    }

    (void)journal_->SourceMediaSpoolUsage(mission_id, &report.spool_bytes_in_use,
                                          &report.spool_items_in_use);
    report.pending_download =
        journal_->SourceMediaItemsInState(mission_id, SourceMediaState::kDiscovered).size();
    if (fatal || report.verdict == MediaOffloadVerdict::kTransportFailure) {
        return report;
    }
    if (report.download_paused_for_spool) {
        report.verdict = MediaOffloadVerdict::kSpoolHighWater;
        return report;
    }

    SourceMediaMissionState final_state;
    if (journal_->FindSourceMediaMission(mission_id, &final_state) !=
        SourceMediaJournalVerdict::kAccepted) {
        report.verdict = MediaOffloadVerdict::kJournalFailure;
        return report;
    }
    const std::size_t quarantined =
        journal_->SourceMediaItemsInState(mission_id, SourceMediaState::kQuarantined).size();
    const std::size_t purged =
        journal_->SourceMediaItemsInState(mission_id, SourceMediaState::kPurged).size();
    if (!final_state.discovery_complete || final_state.discovered_count == 0U ||
        purged != static_cast<std::size_t>(final_state.discovered_count)) {
        // 부분 집합 봉인은 하지 않는다. 격리된 장이 남았다면 그 사실을 판정으로
        // 낸다 — "아직 진행 중"과 "사람이 손봐야 한다"는 다른 상태다.
        report.verdict = quarantined > 0U ? MediaOffloadVerdict::kQuarantineBlocked
                                          : MediaOffloadVerdict::kProgressed;
        return report;
    }
    // Core 를 먼저 봉인하고 그 다음에 원장을 굳힌다. 반대 순서면 재기동이
    // "우리는 봉인했다고 아는데 Core 는 모른다"로 갈라진다.
    const CoreSyncVerdict sealed = transport_->SealSourceMedia(mission_id);
    if (sealed != CoreSyncVerdict::kAcknowledged) {
        report.verdict = MediaOffloadVerdict::kTransportFailure;
        return report;
    }
    const SourceMediaJournalVerdict marked = journal_->MarkSourceBundleSealed(mission_id);
    if (marked != SourceMediaJournalVerdict::kAccepted &&
        marked != SourceMediaJournalVerdict::kDuplicate) {
        report.verdict = MediaOffloadVerdict::kJournalFailure;
        return report;
    }
    report.sealed = true;
    report.verdict = MediaOffloadVerdict::kCompleted;
    return report;
}

// ── 가짜 소스 ───────────────────────────────────────────────────────────────

MediaSourceVerdict FakeMediaSourcePort::ObtainRights() {
    ++obtain_calls;
    if (obtain_verdict != MediaSourceVerdict::kCompleted) {
        return obtain_verdict;
    }
    rights_held = true;
    return MediaSourceVerdict::kCompleted;
}

MediaSourceVerdict FakeMediaSourcePort::ReleaseRights() {
    ++release_calls;
    if (release_verdict != MediaSourceVerdict::kCompleted) {
        return release_verdict;
    }
    rights_held = false;
    return MediaSourceVerdict::kCompleted;
}

MediaSourceVerdict FakeMediaSourcePort::ListFiles(std::vector<SourceMediaFileHandle>* files) {
    ++list_calls;
    if (!rights_held) {
        touched_without_rights = true;
    }
    if (list_verdict != MediaSourceVerdict::kCompleted) {
        return list_verdict;
    }
    if (files == nullptr) {
        return MediaSourceVerdict::kPermanentFailure;
    }
    files->clear();
    for (const Entry& entry : entries) {
        files->push_back(entry.handle);
    }
    return MediaSourceVerdict::kCompleted;
}

MediaSourceVerdict FakeMediaSourcePort::DownloadFile(const SourceMediaFileHandle& file,
                                                     std::vector<std::uint8_t>* bytes) {
    ++download_calls;
    if (!rights_held) {
        touched_without_rights = true;
    }
    if (!download_script.empty()) {
        const MediaSourceVerdict scripted = download_script.front();
        download_script.pop_front();
        if (scripted != MediaSourceVerdict::kCompleted) {
            return scripted;
        }
    }
    if (bytes == nullptr) {
        return MediaSourceVerdict::kPermanentFailure;
    }
    for (const Entry& entry : entries) {
        if (entry.handle.camera_file_name == file.camera_file_name) {
            *bytes = entry.bytes;
            return MediaSourceVerdict::kCompleted;
        }
    }
    return MediaSourceVerdict::kPermanentFailure;
}

}  // namespace ksi::edge

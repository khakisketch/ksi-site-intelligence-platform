// 기체 SD 카드 → 매니폴드 → Core 로 원본 사진을 흘려보내는 골격.
//
// ## 스풀은 창고가 아니라 컨베이어다
//
// 매니폴드 여유는 실측 8.6GB(27GB 중 66% 사용)이고 20MP 3,000장은 약 30GB 다.
// 전량을 받아두고 나중에 올리는 설계는 **성립하지 않는다.** 그래서 이 파일의
// 모든 판단이 하나의 규칙에서 나온다:
//
//   고수위를 넘으면 다운로드를 멈추고 배출부터. UPLOADED 가 durable 해진
//   직후 스풀 사본을 즉시 지운다.
//
// 원본은 기체 SD 카드에 그대로 있다(ADR-KSI-013). 매니폴드 사본은 경유지일 뿐이라
// 지워도 잃는 것이 없고, 지우지 않으면 회수 자체가 중간에 멈춘다.
//
// ## PSDK 심볼이 하나도 없다
//
// 실기 미확인(M4D 가 DjiCameraManager_Download* 를 지원하는지, 장당 몇 초인지 —
// FIELD-0b U5/U7)을 IMediaSourcePort 하나로 격리한다. 이 파일과 구현부는 호스트
// CI 에서 100% 돌고, 실기 확인 뒤에 얇은 어댑터 하나만 붙는다.
//
// ## 상태기계
//
//   DISCOVERED → SPOOLED → REGISTERED → UPLOADED → PURGED   (장당)
//   전량 PURGED 일 때만 → SEALED                            (임무당)
//
// URL 은 저장하지 않는다. 재기동은 재등록해 새 presigned URL 을 받는다(Core 가
// 같은 신고값에 멱등이다). 만료된 URL 을 원장에 남겨 두면 복구 경로가 "언젠가
// 죽는 권한"을 되살리는 일이 된다.

#ifndef KSI_EDGE_MEDIA_OFFLOAD_HPP
#define KSI_EDGE_MEDIA_OFFLOAD_HPP

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <string>
#include <vector>

#include "ksi/edge/artifact_vault.hpp"
#include "ksi/edge/core_sync_http.hpp"
#include "ksi/edge/store_forward.hpp"

namespace ksi::edge {

// ── mediaId 규약 (자동 경로와 수동 경로가 같은 사진을 같은 이름으로 부른다) ──
//
//   mediaId = 카메라 원본 파일명에서 **마지막 확장자를 뺀** 뒤 정규화한 것
//
// 정규화(순서대로):
//   1. 마지막 '.' 이후를 버린다. 단 '.' 이 맨 앞이면 확장자로 보지 않는다
//      (".JPG" → "JPG"). '.' 이 없으면 이름 전체를 쓴다.
//   2. `[A-Za-z0-9_.-]` 밖의 **연속 구간 하나**를 '-' 하나로 바꾼다.
//   3. 맨 앞의 `[A-Za-z0-9]` 아닌 문자를 전부 버린다.
//   4. 비면 "media".
//   5. 앞에서 120자로 자른다.
//
// 결과는 Core 의 ``PATH_SAFE_IDENTIFIER_PATTERN``
// (``^[A-Za-z0-9][A-Za-z0-9_.-]*$``, services/core/src/ksi_core/identifiers.py)을
// 항상 만족한다.
//
// 짝 구현은 ``apps/dashboard/src/lib/source-upload.ts`` 의 ``deriveMediaId`` 다.
// 두 시험(edge_runtime_tests.cpp 의 media_id_golden, source-upload.test.ts 의
// MEDIA_ID_GOLDEN)이 **같은 11행 표**를 함께 주장한다 — 한쪽만 고치면 둘 중
// 하나가 반드시 깨진다.
//
// **동치는 ASCII 파일명 한정이다.** NFC 정규화는 여기서 하지 않는다 — 이 함수는
// 2 단계에서 문자가 아니라 **바이트** 단위로 허용문자 밖 구간을 뭉친다. 완성형
// 한 글자(예: U+00E9 é, UTF-8 2바이트)는 그 2바이트 전체가 하나의 '-' 로
// 뭉치지만, 자모분리형(예: U+0065 e + U+0301 결합 억음부호)은 선행 ASCII 글자
// e 가 허용 문자라서 살아남는다 — 그래서 같은 화면 표기의 두 정규화 형태가
// **여기서는 다른 mediaId** 를 받는다("café.jpg" 완성형 → "caf-", 자모분리형 →
// "cafe-", 손으로 실행 확인). TypeScript 쪽은 ``normalize("NFC")`` 를 먼저 걸어
// 두 형태를 항상 하나로 모으므로, 이 경계에서는 TS 결과와도 갈릴 수 있다 —
// media_id_nfc_boundary 시험(아래)이 그 경계를 명시 케이스로 남긴다.
// 카메라가 주는 파일명은 ASCII 라 실무 영향은 없고, 이 격차를 메우려 ICU 를
// 끌어오는 것은 지금은 과잉엔지니어링으로 보류한다(대표자/메인 판단 필요 시
// 재검토).
std::string DeriveMediaId(const std::string& camera_file_name);

// 한 발견 목록 전체에 mediaId 를 부여한다.
//
// 확장자를 떼면 충돌이 **실제로** 생긴다 — RAW+JPEG 동시 저장이면 ``DJI_0001.JPG``
// 와 ``DJI_0001.DNG`` 가 같은 base 가 된다. 그래서 **카메라 원본 파일명(확장자
// 포함)의 sha256 앞 8 hex** 를 접미사로 쓴다 — 목록 순서와 무관하고 재기동을
// 넘어 같다(선택 순서로 순번(-2, -3...)을 매기는 방식은 재기동 후 목록이 한
// 장이라도 달라지면 같은 사진이 다른 이름을 받아 쓰지 않는다).
//
// false 면 목록 자체가 성립하지 않는다(빈 이름·같은 파일명 중복 — 완전히 같은
// 파일명 두 개는 접미사도 똑같이 나와 어떻게 해도 갈라지지 않는다). 값을
// 지어내 진행하지 않는다.
//
// 짝 구현은 ``apps/dashboard/src/lib/source-upload.ts`` 의
// ``assignUniqueMediaIds`` 다 — **같은 규칙**(sha256 앞 8 hex, 선택 순서 무관)을
// 쓴다. 자동/수동 두 경로가 RAW+JPEG 동시 저장 임무에서도 같은 두 장에 같은
// mediaId 쌍을 부여한다 — 두 시험(edge_runtime_tests.cpp 의
// media_id_assign_golden, source-upload.test.ts 의 MEDIA_ID_ASSIGN_GOLDEN)이
// 같은 파일명 목록·같은 sha256 접미사를 함께 주장한다.
bool AssignMediaIds(const std::vector<std::string>& camera_file_names,
                    std::vector<std::string>* media_ids);

// ── 미디어 소스 포트 (실기 미확인 격리 경계) ────────────────────────────────

struct SourceMediaFileHandle {
    // DJI Camera Manager fileIndex. 다운로드 API도 이 값을 받으므로 파일명만으로
    // 동일성을 추정하지 않는다. -1은 legacy/unbound이며 자동 경로에서 거부한다.
    std::int64_t source_file_index = -1;
    // 카메라가 준 원본 파일명(확장자 포함).
    std::string camera_file_name;
    // 목록이 주장하는 크기. 다운로드 전 예산 계산에만 쓴다 — 실측은 받은 뒤에 한다.
    std::uint64_t announced_bytes = 0;
};

// 자동 반출을 시작할 수 있는 두 가지 증거. 단순히 "목록을 볼 수 있다"는 사실은
// 시작 신호가 아니다 — 이전 임무 사진까지 현재 Mission으로 귀속시키게 된다.
enum class MediaOffloadTriggerKind {
    kMissionCompleted,
    kOperatorApprovedOneShot,
};

const char* ToString(MediaOffloadTriggerKind kind);

struct MissionMediaSelectionContext {
    std::string mission_id;
    std::string dispatch_id;
    std::string mission_contract_digest;
    MediaOffloadTriggerKind trigger_kind = MediaOffloadTriggerKind::kMissionCompleted;
    // 완료 event 또는 one-shot 승인 record의 canonical SHA-256.
    std::string trigger_evidence_digest;
    // baseline <= activation <= trigger를 강제한다. 임무가 시작된 뒤 찍은 baseline은
    // 이미 현재 임무 사진을 과거 파일로 오분류할 수 있으므로 받지 않는다.
    std::int64_t baseline_observed_at_utc_ms = 0;
    std::int64_t activated_at_utc_ms = 0;
    std::int64_t triggered_at_utc_ms = 0;
    // 임무 활성화 전에 동일 카메라에서 읽어 durable하게 보관한 정확한 목록.
    // 비어 있어도 된다(SD 카드가 실제로 비어 있던 snapshot).
    std::vector<SourceMediaFileHandle> baseline_files;
};

enum class MissionMediaSelectionVerdict {
    kSelected,
    kInvalidContext,
    kInvalidBaseline,
    kInvalidCurrentList,
    // baseline의 index/name/size가 사라지거나 변했다. index 재사용을 포함한다.
    kBaselineDrift,
    // 완료/승인 뒤 생긴 파일이 한 장도 없다. 과거 사진을 대신 가져오지 않는다.
    kNoNewMedia,
};

const char* ToString(MissionMediaSelectionVerdict verdict);

struct MissionMediaSelectionResult {
    MissionMediaSelectionVerdict verdict = MissionMediaSelectionVerdict::kInvalidContext;
    // trigger/baseline/Mission binding의 canonical digest.
    std::string selection_context_digest;
    // context digest와 선택된 exact identity 전체의 canonical digest.
    std::string selected_files_digest;
    std::vector<SourceMediaFileHandle> selected_files;
};

// 목록 순서와 무관한 결정적 selector. baseline에 없던 exact identity만 반환한다.
// 어느 목록이든 duplicate index/name, 0 byte, 제어문자 filename, unbound index를
// 포함하면 전체를 거부한다. "가능한 것만" 골라 부분 bundle을 만들지 않는다.
MissionMediaSelectionResult SelectMissionSourceMedia(
    const MissionMediaSelectionContext& context,
    const std::vector<SourceMediaFileHandle>& current_files);

// 카메라 현재 목록을 읽지 않고도 journal replay key를 계산한다. context 또는
// baseline이 유효하지 않으면 빈 문자열을 반환한다.
std::string ComputeMissionMediaSelectionContextDigest(
    const MissionMediaSelectionContext& context);

enum class MediaSourceVerdict {
    kCompleted,
    // 권한을 못 잡았다(Pilot 앱이 잡고 있는 등). 재시도 여지가 있다.
    kRightsUnavailable,
    kTransientFailure,
    // 이 파일은 다시 시도해도 안 된다.
    kPermanentFailure,
};

const char* ToString(MediaSourceVerdict verdict);

// PSDK 어댑터가 구현할 인터페이스. **이 헤더에는 Dji* 심볼이 없다.**
class IMediaSourcePort {
public:
    virtual ~IMediaSourcePort() = default;
    // 다운로드 권한 획득. 보유 중에는 Pilot 앱 앨범 접근이 막힐 수 있다
    // (FIELD-0b U6) — 그래서 이 골격은 카메라를 만지는 구간에서만 잡는다.
    virtual MediaSourceVerdict ObtainRights() = 0;
    virtual MediaSourceVerdict ReleaseRights() = 0;
    virtual MediaSourceVerdict ListFiles(std::vector<SourceMediaFileHandle>* files) = 0;
    // PSDK 는 한 번에 한 장이다. 바이트를 통째로 준다.
    virtual MediaSourceVerdict DownloadFile(const SourceMediaFileHandle& file,
                                            std::vector<std::uint8_t>* bytes) = 0;
};

// ── 권한 반납: RAII + 프로세스 사망을 넘는 marker ────────────────────────────
//
// 소멸자만으로는 부족하다 — SIGKILL·전원 손실은 소멸자를 부르지 않는다. 그런데
// 권한이 걸린 채로 남으면 운영자가 조종기 앞에서 앨범을 열 수 없다. 그 자체가
// 사고다. 그래서 Obtain **전에** marker 파일을 durable 하게 쓰고, 기동 시 marker
// 가 있으면 무엇을 하기 전에 Release 를 먼저 낸다.
inline constexpr char kSourceMediaRightsMarkerFilename[] = "source-media-rights-held.marker";

enum class MediaRightsVerdict {
    kHeld,
    kReleased,
    // marker 가 없었다 — 기동 시 정리할 것이 없다는 뜻.
    kNotHeld,
    kUnsafeStateDirectory,
    kMarkerWriteFailed,
    kSourceRefused,
};

const char* ToString(MediaRightsVerdict verdict);

// 기동 시 정확히 한 번 부른다. **Obtain 보다 먼저**여야 한다.
//
// Release 가 재시도 여지 있는 실패(kTransientFailure·kRightsUnavailable)를 내면
// marker 를 남긴다 — 다음 기동이 다시 시도한다. kPermanentFailure 는 "지금 잡고
// 있지 않다"는 뜻으로 보고 marker 를 지운다. 실패를 영원히 붙들면 자동 경로가
// 영영 못 뜬다.
MediaRightsVerdict ReconcileSourceMediaRightsMarker(const std::string& state_directory,
                                                    IMediaSourcePort* source);

class MediaSourceRightsGuard {
public:
    MediaSourceRightsGuard(std::string state_directory, IMediaSourcePort* source);
    ~MediaSourceRightsGuard();
    MediaSourceRightsGuard(const MediaSourceRightsGuard&) = delete;
    MediaSourceRightsGuard& operator=(const MediaSourceRightsGuard&) = delete;

    MediaRightsVerdict Acquire();
    MediaRightsVerdict Release();
    bool held() const { return held_; }

private:
    const std::string state_directory_;
    IMediaSourcePort* source_;
    bool held_ = false;
};

// ── 정책 ────────────────────────────────────────────────────────────────────

// **의도적으로 비어 있다.**
//
// FIELD-0b U7(``DownloadFileByIndex`` 실측 MB/s·초/장) 전에는 어떤 선별 기준도
// 근거가 없다. 장당 3초면 3,000장에 2.5시간이고 그건 "자동"이 아니다 — 그 경우
// 자동 경로를 선별 반출로 좁히고 전량은 수동으로 유지한다. 지금 기본값을 하나라도
// 넣으면 그 값이 측정된 것처럼 읽힌다. 실측 뒤에 채운다.
struct MediaSelectionPolicy {};

struct MediaOffloadPolicy {
    // 스풀 고수위. 8.6GB 중 512MB 는 보수적이지만, 이 값을 키우는 근거는
    // FIELD-0b U7 의 처리량뿐이다. 넘으면 다운로드를 멈추고 배출한다.
    //
    // **한계**: 이 예산은 SourceMediaSpoolUsage 를 통해 **임무 하나 기준**으로
    // 잰다(SPOOLED/REGISTERED/UPLOADED 합계). 매니폴드 디스크 여유 전체를 보는
    // 게 아니다 — 같은 매니폴드에서 다른 임무의 스풀 잔량이나 이 저장소 밖의
    // 다른 용도가 디스크를 같이 쓰면, 임무별로는 고수위 밑이어도 디스크 전체는
    // 8.6GB 여유를 넘어설 수 있다. "8.6GB 여유" 근거(파일 상단 주석)는 이
    // 격차를 아직 메우지 않은 상태다.
    std::uint64_t spool_high_water_bytes = 512U * 1024U * 1024U;
    std::uint32_t spool_high_water_items = 32U;
    // rights marker 를 두는 사설 상태 디렉터리(활성화 스냅샷과 같은 곳).
    std::string state_directory;
    MediaSelectionPolicy selection;
};

// ── 워커 ────────────────────────────────────────────────────────────────────

enum class MediaOffloadVerdict {
    // 발견 목록 전량이 PURGED 이고 봉인까지 끝났다.
    kCompleted,
    // 진행은 됐고 남은 일이 있다. 다음 호출에서 이어간다.
    kProgressed,
    // 고수위에 닿아 다운로드를 멈췄다. 배출이 진행되면 다시 받는다.
    kSpoolHighWater,
    kRightsUnavailable,
    kSourceFailure,
    kTransportFailure,
    kJournalFailure,
    kSpoolFailure,
    // 완료/승인·baseline·현재 목록의 결속이 성립하지 않는다.
    kSelectionRejected,
    // 저널에 고정한 fileIndex+name+size가 다운로드 직전 목록과 달라졌다.
    kSourceIdentityDrift,
    // 목록 안에서 mediaId 가 갈라지지 않는다 — 회수를 시작하지 않는다.
    kMediaIdCollision,
    // 격리된 장이 남아 봉인할 수 없다. **부분 집합 봉인은 하지 않는다.**
    kQuarantineBlocked,
};

const char* ToString(MediaOffloadVerdict verdict);

struct MediaOffloadReport {
    MediaOffloadVerdict verdict = MediaOffloadVerdict::kProgressed;
    // 이번 실행에서 새로 일어난 전이 수.
    std::size_t discovered = 0;
    std::size_t spooled = 0;
    std::size_t uploaded = 0;
    std::size_t purged = 0;
    std::size_t quarantined = 0;
    bool download_paused_for_spool = false;
    bool sealed = false;
    MissionMediaSelectionVerdict selection_verdict =
        MissionMediaSelectionVerdict::kInvalidContext;
    // 실행이 끝난 시점에 매니폴드 디스크를 실제로 점유하고 있는 양.
    std::uint64_t spool_bytes_in_use = 0;
    std::uint32_t spool_items_in_use = 0;
    std::size_t pending_download = 0;
};

class MediaOffloadWorker {
public:
    MediaOffloadWorker(MediaOffloadPolicy policy, SqliteStoreForward* journal, ArtifactVault* spool,
                       IMediaSourcePort* source, IEdgeSourceMediaTransport* transport);

    // 한 배치를 진행한다. 끝날 때까지 반복 호출하는 것이 정상 사용이다 —
    // 한 번에 다 하지 않는 이유가 곧 이 설계의 요점이다(고수위에서 멈춘다).
    MediaOffloadReport RunOnce(const MissionMediaSelectionContext& selection_context,
                               const std::string& edge_device_id);

    // 스풀 산출물 이름. 임무와 사진을 모두 담아 임무 간 충돌을 막는다.
    static std::string SpoolArtifactId(const std::string& mission_id, const std::string& media_id);

    // ── 시험 전용 훅 ──────────────────────────────────────────────────────────
    //
    // 기본은 no-op(빈 std::function). PushItem 이 MarkSourceMediaUploaded 를
    // durable 하게 기록한 **직후**, PurgeItem(스풀 삭제)을 부르기 **전**에 정확히
    // 한 번 불린다. 저널(SqliteStoreForward)과 스풀(ArtifactVault)이 모두
    // 인터페이스가 아니라 구체 클래스라 목으로 가로챌 수 없다 — "먼저 durable
    // 기록, 그 다음에만 삭제" 순서(RunOnce 주석 참조)를 화이트박스로 확인할
    // 다른 방법이 없어서 둔다. 운영 경로에서는 절대 설정하지 않는다.
    std::function<void(const SourceMediaItemRecord&)> test_only_after_uploaded_before_purge_hook;

private:
    bool Discover(const MissionMediaSelectionContext& selection_context,
                  MediaOffloadReport* report);
    std::size_t Fill(const std::string& mission_id, MediaOffloadReport* report, bool* paused,
                     bool* fatal);
    std::size_t Drain(const std::string& mission_id, MediaOffloadReport* report, bool* fatal);
    bool PushItem(const SourceMediaItemRecord& item, MediaOffloadReport* report, bool* fatal);
    bool PurgeItem(const SourceMediaItemRecord& item, MediaOffloadReport* report, bool* fatal);
    void Quarantine(const SourceMediaItemRecord& item, const std::string& reason,
                    MediaOffloadReport* report);

    MediaOffloadPolicy policy_;
    SqliteStoreForward* journal_;
    ArtifactVault* spool_;
    IMediaSourcePort* source_;
    IEdgeSourceMediaTransport* transport_;
    // 워커 수명당 한 번만: 기동 시 살아남은 rights marker 를 Obtain 보다 먼저
    // 정리한다(ReconcileSourceMediaRightsMarker 문서 참조).
    bool startup_rights_reconciled_ = false;
};

// ── 시험용 가짜 소스 ────────────────────────────────────────────────────────
//
// 실기 어댑터가 생기기 전에 이 골격 전체를 호스트에서 검증하기 위한 것이다.
// 권한을 잡지 않은 채 다운로드하면 실패한다 — PSDK 가 그렇게 동작하므로,
// 가짜가 더 관대하면 시험이 실기보다 약해진다.
// final 이 아니다 — 시험이 한 메서드만 덧씌워(예: Obtain 시점에 marker 가 이미
// 있는지 관찰) 호출 순서를 직접 단언할 수 있어야 한다.
class FakeMediaSourcePort : public IMediaSourcePort {
public:
    struct Entry {
        SourceMediaFileHandle handle;
        std::vector<std::uint8_t> bytes;
    };

    std::vector<Entry> entries;
    // 다음 호출들의 대본. 비면 kCompleted.
    std::deque<MediaSourceVerdict> download_script;
    MediaSourceVerdict list_verdict = MediaSourceVerdict::kCompleted;
    MediaSourceVerdict obtain_verdict = MediaSourceVerdict::kCompleted;
    MediaSourceVerdict release_verdict = MediaSourceVerdict::kCompleted;

    int obtain_calls = 0;
    int release_calls = 0;
    int list_calls = 0;
    int download_calls = 0;
    bool rights_held = false;
    // 권한을 안 잡은 채 카메라를 만진 적이 있는가 — 시험이 이걸 단언한다.
    bool touched_without_rights = false;
    // 비어 있지 않으면 ListFiles 호출마다 맨 앞 snapshot을 반환하고 제거한다.
    // discovery와 download 직전 사이의 identity drift를 재현하는 시험용 대본이다.
    std::deque<std::vector<SourceMediaFileHandle>> list_snapshots;

    MediaSourceVerdict ObtainRights() override;
    MediaSourceVerdict ReleaseRights() override;
    MediaSourceVerdict ListFiles(std::vector<SourceMediaFileHandle>* files) override;
    MediaSourceVerdict DownloadFile(const SourceMediaFileHandle& file,
                                    std::vector<std::uint8_t>* bytes) override;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_MEDIA_OFFLOAD_HPP

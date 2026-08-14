# HIL Raw Log 디렉터리·파일명 규약

- 상태: 절차 확정, 실행 대기 (Track A Hardware Session Pack)
- 대상: `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`가 만들어내는 모든 raw 증거 산출물
- 목적: `SpikeEvidence.raw_log_ref`(`packages/domain/src/ksi_domain/spike_evidence.py`)가
  가리킬 수 있는 안정적이고 재현 가능한 경로 규약을 정한다. 규약 없이 각자 임의 경로에
  로그를 흩어두면 `raw_log_ref`가 "어딘가에 있음"이라는 문자열로 퇴화한다 — 그건
  `latency_result`/`failure_result`와 마찬가지로 형식적 증거다.

## 0. 원칙

- **repo에 raw 로그를 커밋하지 않는다.** 영상·프레임·대용량 JSONL은 코드가 아니고,
  git 히스토리를 무한히 불리며, 라이선스/현장 데이터 취급 방침(INV-043의 정신 — 출처
  불명확한 데이터를 무분별하게 자산화하지 않는다)과도 맞지 않는다. 로컬 스테이징
  디렉터리는 `.gitignore` 처리한다(§4).
- **경로 자체가 재현정보를 담는다.** 세션ID·기체SN·UTC 타임스탬프만 보고도 "언제,
  어느 기체로, 어떤 세션에서 나온 로그인가"를 알 수 있어야 한다 — 파일을 열어보기
  전에 메타데이터가 이미 파일명에 있다.
- **부분 실패해도 이미 쓴 로그는 그대로 둔다.** 세션 중 3단계에서 막혀도 1~2단계
  로그는 유효한 증거로 남아야 한다(디렉터리를 세션 통짜로 지우고 재시작하지 않는다).

## 1. 로컬 스테이징 루트

```
hil_raw_logs/                      # repo 루트, .gitignore 처리(§4)
```

세션 종료 후 이 루트 아래 내용을 대표자가 지정한 durable 저장소(사내 object storage,
network share 등)로 옮긴다. `SpikeEvidence.raw_log_ref`에는 **최종적으로는 durable
저장소 URI**를 적는다 — 세션 도중 임시로는 로컬 경로를 적어도 되지만, VERIFIED 승격
시점에는 로컬 전용 경로(재부팅하면 사라질 수 있는 Manifold 로컬 디스크 등)만 남기지
않는다.

## 2. 세션 ID

형식:

```
SESS-<UTC 세션 시작 compact 타임스탬프>-<기체 시리얼넘버>
```

- `<UTC 세션 시작 compact 타임스탬프>`: `YYYYMMDDThhmmssZ` (예: `20260728T060000Z`).
  세션의 1단계(환경 인벤토리)를 시작한 시각을 사용한다.
- `<기체 시리얼넘버>`: M4D 기체 SN을 파일시스템 안전 문자(영숫자·하이픈)로 그대로
  사용한다. SN을 아직 모르는 상태(세션 0단계 이전)라면 `PENDING-SN`으로 두고, SN을
  확인한 즉시(3단계 기체 정보 읽기 완료 시점) 디렉터리를 리네임한다 — 리네임 이력은
  `session_manifest.json`(§3)에 남긴다.

예: `SESS-20260728T060000Z-1581F5EFC1234A`

여러 기체를 한 세션에서 번갈아 시험하는 경우, 세션 ID는 세션(사람이 앉아서 진행하는
한 회차)당 하나이며 기체 전환은 `session_manifest.json`의 하위 항목으로 기록한다
(디렉터리를 기체마다 새로 쪼개지 않는다 — 세션 연속성이 우선).

## 3. 디렉터리 구조

`HARDWARE_SESSION_PLAYBOOK.md`의 단계 번호와 그대로 대응시킨다 — 어느 로그가 몇 단계
산출물인지 디렉터리명만 보고 알 수 있게 한다.

```
hil_raw_logs/
  <session_id>/
    session_manifest.json                # 세션 메타 — §3.1
    01_env_inventory/
      <UTC_ts>__env_inventory.json        # collect_env_inventory.sh 산출물
    02_sample_build/
      <UTC_ts>__sample_build.log
    03_aircraft_telemetry/
      <UTC_ts>__telemetry_snapshot.json
    04_camera_live_view/
      <UTC_ts>__live_view_capture.{mp4,log}
    05_lens_switch/
      <UTC_ts>__lens_switch.log
    06_gimbal_control/
      <UTC_ts>__gimbal_control.jsonl
    07_frame_telemetry_timing/
      <UTC_ts>__frame_telemetry.jsonl     # capture_frame_telemetry_timing.py collect 산출물
      <UTC_ts>__frame_telemetry_summary.json  # 같은 스크립트 summarize 산출물
      <UTC_ts>__candidate_durable_timing/ # private DPK event-timing-*.json 사본
      <UTC_ts>__candidate_durable_timing_summary.json
                                           # summarize_event_candidate_timing.py 산출물
    08_dpk_deploy/
      <UTC_ts>__dpk_deploy.log
```

### 3.1 `session_manifest.json`

세션 시작 시 1건 생성, 세션 진행에 따라 갱신한다. 최소 필드:

```json
{
  "session_id": "SESS-20260728T060000Z-1581F5EFC1234A",
  "operator": "<실기 세션 수행자 이름>",
  "aircraft_sn": "<기체 SN 또는 PENDING-SN>",
  "build_commit": "<git rev-parse HEAD>",
  "started_at_utc": "2026-07-28T06:00:00Z",
  "ended_at_utc": null,
  "purpose": "Track A Hardware Capability Spike — PRD §20.3 읽기 중심 항목",
  "steps_completed": [],
  "notes": ""
}
```

## 4. 파일명 규칙

```
<UTC_ts>__<artifact-slug>.<ext>
```

- `<UTC_ts>`: 그 파일을 생성한 시각, `YYYYMMDDThhmmssZ` (세션 시작 시각과 다를 수
  있음 — 세션 내 각 산출물은 자기 생성 시각을 쓴다).
- `<artifact-slug>`: 소문자·언더스코어, 무엇을 담은 파일인지 사람이 읽고 아는 이름
  (`env_inventory`, `frame_telemetry`, `gimbal_control` 등).
- 구분자는 `__`(더블 언더스코어)로 통일해 `<UTC_ts>`와 `<artifact-slug>`를 스크립트로도
  쉽게 split할 수 있게 한다.

## 5. `.gitignore`

`hil_raw_logs/`는 로컬 스테이징이므로 git 추적 대상이 아니다 — 이 규약 작성과 함께
루트 `.gitignore`에 `/hil_raw_logs/`를 추가한다(별도 커밋 항목).

## 6. `SpikeEvidence.raw_log_ref`와의 연결

`SpikeEvidence`(`packages/domain/src/ksi_domain/spike_evidence.py`)를 채울 때
`raw_log_ref`에는 이 규약을 따른 **구체 파일 또는 디렉터리 경로/URI**를 적는다.
예: `hil_raw_logs/SESS-20260728T060000Z-1581F5EFC1234A/07_frame_telemetry_timing/` 또는
세션 종료 후 옮긴 durable 저장소 URI. "로그 어딘가에 있음" 같은 비특정 문자열은
`docs/hil/SPIKE_EVIDENCE_TEMPLATE.md`의 규칙상 유효한 값이 아니다.

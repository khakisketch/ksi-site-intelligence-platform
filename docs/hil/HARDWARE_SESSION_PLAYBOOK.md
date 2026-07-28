# Hardware Session Playbook (Track A — DJI Matrice 4D + RC Plus 2 + Manifold 3)

- 상태: 절차 확정, **실행 대기** (실기 세션 없이 준비 가능한 것까지만 완료)
- 근거: `docs/product/MASTER_PRD_v3.0.md` §20.3(SPIKE_REQUIRED 9항목), §21.1(Edge 실시간
  목표), `docs/dji/SPIKE_PROCEDURE.md`(8단계 실행 순서, 이 문서가 그 절차의 운영 세부판),
  `.ksi/goals.json` `track-a` 목표
- 이 문서와 `docs/dji/SPIKE_PROCEDURE.md`의 관계: `SPIKE_PROCEDURE.md`가 절차 SSOT(단계
  순서·evidence 게이트 원칙)이고, 이 문서는 **세션 당일 실제로 손으로 진행할 체크리스트**
  — 단계별 목적/실행 항목/수집 증거/PASS·BLOCKED 판정 기준을 구체화한다. 두 문서가
  어긋나면 `SPIKE_PROCEDURE.md`를 따른다.

## 0. 이 세션에서 절대 하지 않는 것

**FlyTo·Hold·Rejoin·Route Update 등 기체를 이동시키는 명령(`SPIKE-DJI-04`)과, DJI
장애물 회피와의 동시동작(`SPIKE-DJI-05`)은 이 세션에서 열지 않는다.** 이유는
`docs/dji/SPIKE_PROCEDURE.md` §0과 동일하다 — 읽기 경로(Telemetry·Camera·Heartbeat)가
먼저 안정적으로 검증돼야, 나중에 쓰기 명령이 실패했을 때 그게 명령 자체의 문제인지
읽기 경로의 문제인지 분리할 수 있다. `INV-001`/`INV-002`(서버·LLM은 실행 가능한
비행좌표·프레임별 명령을 내지 않는다)는 이 세션 내내 유효하며, 이 세션은 그 상태를
바꾸지 않는다.

같은 이유로 아래도 이번 세션 범위 밖이다(다른 게이트에서 별도로 다룬다):
- `SPIKE-DJI-06`(Pilot 2/Cloud API/PSDK 동시 제어권) — 다중 제어 소스 경쟁 시나리오는
  단일 제어 경로가 먼저 안정화된 뒤 별도 세션.
- `SPIKE-DJI-08`(Dock 3) — 이번 세션 장비 구성(M4D + RC Plus 2 + Manifold 3)에 Dock이
  포함돼 있지 않다.
- `SPIKE-DJI-09`(비행시간/발열/전력) — 실제 비행 시간 누적이 필요해 별도 비행 세션.

## 1. 사전 준비 (세션 착수 전)

- [ ] 기체·RC·Manifold 완충 및 물리 점검(프로펠러·짐벌 잠금 해제 등 — 표준 DJI 사전
      점검 절차, 이 문서 범위 밖)
- [ ] `hil_raw_logs/` 로컬 스테이징 디렉터리 쓰기 가능 확인 (`docs/hil/RAW_LOG_CONVENTIONS.md`)
- [ ] `SESSION_ID` 확정 — 세션 시작 UTC 시각 + 기체 SN(모르면 `PENDING-SN`)
- [ ] `docs/hil/SPIKE_EVIDENCE_TEMPLATE.md` 사본을 세션 노트로 준비(항목별로 채워나감)
- [ ] `git rev-parse HEAD` 기록 — 이 세션에서 시험할 KSI 빌드 commit

## 2. 실행 순서

순서에 의미가 있다 — 앞 단계가 실패(BLOCKED)하면 뒤 단계의 결과를 신뢰할 수 없으므로
`docs/dji/SPIKE_PROCEDURE.md` §1 표를 그대로 따른다. 각 단계는 대응 raw 로그 디렉터리
번호(`docs/hil/RAW_LOG_CONVENTIONS.md` §3)와 맞춘다.

---

### 1단계 — 환경 인벤토리 (`01_env_inventory/`)

**목적**: 이후 모든 단계의 기준선을 만든다. 이게 없으면 "어느 환경에서 검증했는가"를
아무도 재현할 수 없다.

**실행 항목**:
```bash
export SESSION_ID=SESS-<UTC 세션 시작>-<기체SN 또는 PENDING-SN>
bash tools/hil/collect_env_inventory.sh
```
스크립트가 실패하는 개별 항목(예: PSDK 버전 조회)은 `MISSING: <이유>`로 남고 스크립트
전체는 계속 진행한다 — 이는 정상 동작이다.

**수집 증거**: `hil_raw_logs/<session_id>/01_env_inventory/<UTC_ts>__env_inventory.json`
(JetPack/L4T, CUDA/cuDNN/TensorRT, RAM/디스크, 네트워크 인터페이스, git commit, PSDK
버전 조회 결과 포함)

**판정 기준**:
- **PASS**: JSON이 생성됐고, 최소한 `hostname`/`uname`/`git_commit`/`disk_root`가
  `MISSING`이 아니다(장비 자체 식별과 빌드 식별은 협상 불가 최소치).
- **BLOCKED**: 스크립트 자체가 실행되지 않음(python3·bash 부재 등 환경 문제) → 이후
  단계 전부 중단, 원인을 이 문서에 기록 후 재시도.

---

### 2단계 — DJI 공식 샘플 빌드·실행

**목적**: 툴체인이 실제로 동작하는지 확인한다. 여기서 실패하면 이후 KSI 코드가 실패해도
그게 KSI 문제인지 툴체인 문제인지 구분할 수 없다.

**실행 항목**:
- DJI 공식 Payload SDK(PSDK) 샘플 저장소를 받아 공식 안내대로 빌드한다. **구체적인
  빌드 명령·디렉터리 구조는 여기서 단정하지 않는다** — 이 세션 시점에 공식 문서/샘플
  저장소에서 확인한 절차를 그대로 따르고, 실제로 사용한 명령을 로그에 남긴다.
- 빌드 성공 후 최소 1개 공식 예제(예: 로그 출력 전용 샘플)를 Manifold 3에서 실행해
  프로세스가 정상 기동·종료하는지 확인한다.

**수집 증거**: `hil_raw_logs/<session_id>/02_sample_build/<UTC_ts>__sample_build.log`
(빌드 전체 출력 + 실행 시 표준출력/표준에러 + 사용한 정확한 명령어 기록)

**판정 기준**:
- **PASS**: 빌드가 에러 없이 끝났고, 최소 1개 샘플 실행이 크래시 없이 완료(또는 의도된
  종료 신호로 정상 종료)했다.
- **BLOCKED**: 빌드 실패 또는 실행 시 크래시 → 3~8단계 전부 중단. 원인(툴체인 버전
  불일치, 헤더 누락 등)을 `02_sample_build` 로그에서 확인 가능한 만큼 기록.

---

### 3단계 — 기체 정보·Telemetry 읽기 (`03_aircraft_telemetry/`)

**목적**: PSDK를 통해 기체와의 연결·식별·상태 수신이 되는지 확인한다. 이 단계가 이후
카메라·짐벌·시간동기 단계 전부의 전제다.

**실행 항목**:
- PSDK(또는 공식 샘플)로 기체에 연결
- 기체 모델·시리얼넘버·펌웨어 버전 조회 → `docs/hil/RAW_LOG_CONVENTIONS.md`의
  `PENDING-SN`을 실제 SN으로 갱신
- RC(조종기) 연결 상태·펌웨어 버전 조회
- Telemetry 스트림(자세·위치·배터리 등 가용한 필드) 최소 30초간 수신, 수신 주기 관찰

**수집 증거**:
`hil_raw_logs/<session_id>/03_aircraft_telemetry/<UTC_ts>__telemetry_snapshot.json`
(기체·RC 식별 정보 + 수신한 Telemetry 필드 샘플 + 관측된 수신 주기)

**판정 기준**:
- **PASS**: 기체 SN·펌웨어 버전을 실제로 읽었고, Telemetry가 최소 30초간 끊기지 않고
  수신됐다(수신 주기는 기록만 하고 이 단계에서 목표치 판정은 하지 않는다 — 그건 7단계).
- **BLOCKED**: 연결 자체가 안 되거나 Telemetry가 수신되지 않음 → 4~7단계 중단(카메라
  자체는 별개 경로일 수 있으나, 시간동기 실측(7단계)은 Telemetry 없이 의미가 없다).

---

### 4단계 — Camera Live View 접근 (`04_camera_live_view/`)

**목적**: `SPIKE-DJI-01`(M4D 카메라별 실시간 프레임 접근)의 핵심 증거를 만든다.

**실행 항목**:
- PSDK를 통해 카메라 스트림에 접근(공식 샘플이 제공하는 카메라 페이로드 인터페이스
  사용 — 정확한 API 이름은 2단계에서 확인한 것을 쓴다)
- 최소 1개 렌즈에서 프레임을 수신해 해상도·프레임률을 관측
- 가능하면 짧은 구간(예: 10~30초) 영상 또는 프레임 시퀀스를 저장

**수집 증거**:
`hil_raw_logs/<session_id>/04_camera_live_view/<UTC_ts>__live_view_capture.{mp4,log}`
+ 관측된 해상도·프레임률(fps)·연속 수신 지속시간을 텍스트로 함께 기록

**판정 기준** (`docs/hil/CAPABILITY_ACCEPTANCE.md` "Frame 접근" 행과 동일 기준):
- **PASS**: 실제 프레임을 수신했고, 해상도·프레임률·연속 수신 지속시간 3가지를 모두
  구체적 수치로 기록했다.
- **BLOCKED**: 프레임이 아예 수신되지 않거나, 수신되더라도 해상도/fps 중 하나라도 확인
  불가 → `SPIKE-DJI-01`은 `BLOCKED`로 남기고 사유 기록. 5~6단계(렌즈·짐벌)는 카메라
  스트림에 의존하므로 함께 중단.

---

### 5단계 — Lens 식별·전환 (`05_lens_switch/`)

**목적**: `SPIKE-DJI-02`(광각/중망원/망원 전환과 촬영·초점 제어)의 증거를 만든다.

**실행 항목**:
- 사용 가능한 렌즈(광각/중망원/망원) 목록을 PSDK/샘플로 식별
- 각 렌즈로 순서대로 전환하며 4단계와 동일하게 프레임 수신 확인
- 촬영(스냅샷) 명령과 초점 제어(가능한 범위)를 시험 — **이동 명령이 아니므로 이
  세션에서 열어도 된다**(§0의 제외 목록은 기체 이동·회피 동시동작에 한정)

**수집 증거**: `hil_raw_logs/<session_id>/05_lens_switch/<UTC_ts>__lens_switch.log`
(전환 명령·응답 타임스탬프, 전환 후 프레임 수신 여부, 촬영/초점 명령 결과)

**판정 기준**:
- **PASS**: 최소 2개 렌즈 간 전환이 성공하고, 전환 후 각각 프레임이 수신됐다. 촬영·초점
  제어는 결과(성공/실패)를 구체적으로 기록하면 되고, 실패해도 렌즈 전환 자체가
  성공했다면 이 항목은 부분 PASS로 기록하고 촬영·초점 부분만 별도 BLOCKED 메모.
- **BLOCKED**: 렌즈 전환 자체가 안 됨 → `SPIKE-DJI-02` `BLOCKED`.

---

### 6단계 — Gimbal 상태·제한 제어 (`06_gimbal_control/`)

**목적**: `SPIKE-DJI-03`(기체 Yaw/짐벌 Pitch API와 지연) 중 **짐벌 부분**의 증거를
만든다. 기체 Yaw(회전)는 이 세션에서 다루지 않는다 — Yaw는 기체 자체의 자세를
바꾸는 동작이라 §0의 "이동/조작 명령 최소화" 원칙에 따라 짐벌만 우선 검증하고,
기체 Yaw는 짐벌 결과를 본 뒤 별도 게이트에서 판단한다(대표자 확인 필요 시 상신).

**실행 항목**:
- 짐벌 현재 자세(pitch/roll/yaw) 읽기
- 소각도(예: ±5~10도) pitch 이동 명령을 보내고, 명령값·관측값·오차·응답 지연을 기록
- 짐벌 제한 조건(기계적 리밋, 안전 모드 등) 관찰

**수집 증거**: `hil_raw_logs/<session_id>/06_gimbal_control/<UTC_ts>__gimbal_control.jsonl`
— 각 줄: `{"command_pitch_deg": ..., "observed_pitch_deg": ..., "error_deg": ...,
"latency_ms": ..., "timestamp_utc": ...}` 형태 (정확한 필드는 실기에서 관측 가능한
것에 맞춰 조정하되, 명령값/관측값/오차/지연 4가지는 반드시 포함)

**판정 기준** (`docs/hil/CAPABILITY_ACCEPTANCE.md` "짐벌" 행과 동일 기준):
- **PASS**: 최소 5회 이상의 pitch 명령-관측 쌍에서 명령값·관측값·오차·지연을 모두
  기록했고, 짐벌이 명령에 반응했다(오차 크기 자체는 PASS 조건이 아니다 — 실측하고
  기록하는 것이 조건).
- **BLOCKED**: 짐벌이 명령에 전혀 반응하지 않거나 안전 모드에서 벗어나지 않음.

---

### 7단계 — Frame–Telemetry 시간차 실측 (`07_frame_telemetry_timing/`)

**목적**: PRD §21.1 "Sensor Timestamp alignment: p95 50ms 이하" 목표를 실측하고,
`docs/product/DOMAIN_INVARIANTS.md` INV-025(CONFIRMED 승격의 시점 증거 전제조건)가
기대는 시간 정합성이 실제로 확보되는지 확인한다.

**실행 항목**:
```bash
uv run python tools/hil/capture_frame_telemetry_timing.py collect \
    --session-id "$SESSION_ID" \
    --aircraft-sn <실측 기체SN> \
    --out hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \
    --num-samples 200
```
**주의**: 이 스크립트의 `collect` 서브커맨드는 현재 PSDK 콜백이 미연동 상태라
`NotImplementedError`로 즉시 중단된다(의도된 동작 — `tools/hil/capture_frame_telemetry_timing.py`
docstring 참고). 실기 세션에서 `read_next_frame_telemetry_timestamps()` 함수를 실제
PSDK 카메라·Telemetry 콜백으로 채운 뒤에야 수집이 가능하다. 이 구현은 **이번 세션의
사전 준비 범위를 벗어난다** — 실기 세션 당일, 2단계에서 확인한 실제 PSDK API로
채워 넣는 작업이 필요하다(대표자/구현 담당에 그대로 인계).

수집 후 요약:
```bash
uv run python tools/hil/capture_frame_telemetry_timing.py summarize \
    --in hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \
    --out hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__frame_telemetry_summary.json
```

**수집 증거**: raw JSONL(표본별 timestamp 쌍) + 요약 JSON(p50/p95/max/표본 수 +
`measurement_status`/`acceptance_status`)

**판정 기준** (`docs/hil/CAPABILITY_ACCEPTANCE.md` "시간동기" 행과 동일 기준 — 2축):
- **`measurement_status=MEASURED` + `acceptance_status=PASS`**: 표본 수 ≥ 100(권장,
  통계적 신뢰를 위한 최소치) **그리고** p95 ≤ 50ms. VERIFIED 승격 근거는 이 조합뿐이다.
- **`measurement_status=MEASURED` + `acceptance_status=FAIL`**: p95 > 50ms. 표본 수가
  충분해도 **VERIFIED 승격 금지** — 목표 미달은 별도로 리스크 기록(`.ksi/goals.json`
  risk 항목 등)으로 남기고, 이 단계는 `BLOCKED`(사유: "p95 목표 미달 —
  requirement_not_met")로 정직하게 남긴다.
- **`measurement_status=MEASURED` + `acceptance_status=INSUFFICIENT_SAMPLES`**: 표본을
  모았으나 100건 미만 — PASS도 FAIL도 주장하지 않는다. 표본 수와 이유를 명시하고
  다음 세션에서 보강한다("잠정 PASS" 같은 중간 상태로 표기하지 않는다).
- **`measurement_status=NOT_MEASURED`**: 표본을 아예 수집하지 못했거나, collect
  스크립트가 `NotImplementedError`인 채로 세션이 끝났다면 이 단계는 `BLOCKED`(사유:
  "PSDK 콜백 미연동")로 정직하게 남긴다 — "미측정 + 이유 없음"은 허용되지 않는다
  (`docs/hil/CAPABILITY_ACCEPTANCE.md` 참고).

---

### 8단계 — DPK 설치·재시작 검증 (`08_dpk_deploy/`)

**목적**: 배포 경로(빌드된 페이로드 애플리케이션을 Manifold/기체에 설치하고 재시작 후
정상 기동하는 경로)가 실제로 동작하는지 확인한다. **"DPK"라는 명칭·정확한 패키지
포맷은 이 문서 작성 시점에 확신 없이 단정하지 않는다** — DJI PSDK가 페이로드
애플리케이션을 배포하는 표준 절차/패키지 형식을 2단계에서 확인한 공식 문서/샘플
기준으로 그대로 따른다.

**실행 항목**:
- KSI 빌드(또는 최소한 공식 샘플 빌드)를 배포 절차대로 설치
- 대상 장치(Manifold 또는 페이로드) 재시작
- 재시작 후 애플리케이션이 자동/수동으로 정상 기동하는지 확인

**수집 증거**: `hil_raw_logs/<session_id>/08_dpk_deploy/<UTC_ts>__dpk_deploy.log`
(설치 명령·출력, 재시작 전후 상태, 기동 로그)

**판정 기준**:
- **PASS**: 설치가 에러 없이 끝났고, 재시작 후 애플리케이션이 확인 가능한 상태로
  기동했다.
- **BLOCKED**: 설치 실패 또는 재시작 후 기동 실패 → "운영 배포가 동작한다"는 주장을
  하지 않는다.

## 3. 세션 종료 후

1. `session_manifest.json`의 `ended_at_utc`·`steps_completed`를 채운다.
2. 각 단계 PASS/BLOCKED 결과를 `docs/hil/SPIKE_EVIDENCE_TEMPLATE.md` 형식으로 옮겨
   `SpikeEvidence` 레코드(11필드)를 실제로 구성한다.
3. PASS한 capability는 `CapabilityRegistry.transition(..., VERIFIED, spike_evidence=...)`로
   승격한다(`docs/dji/SPIKE_PROCEDURE.md` §3 코드 예시).
4. BLOCKED로 남은 항목은 사유와 함께 `.ksi/goals.json`의 관련 목표/리스크에 반영한다.
5. `hil_raw_logs/<session_id>/` 전체를 durable 저장소로 옮기고, 옮긴 URI로
   `raw_log_ref`를 갱신한다(로컬 전용 경로만 남기지 않는다 — §RAW_LOG_CONVENTIONS §1).

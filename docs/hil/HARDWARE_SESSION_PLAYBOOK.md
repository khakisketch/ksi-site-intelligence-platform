# Hardware Session Playbook (Track A — DJI Matrice 4D + RC Plus 2 + Manifold 3)

- 상태: **1~2단계 실기 검증 완료**(2026-08-03, `SESS-20260803T125616Z-PENDING-SN`),
  3단계 이후는 기체 데이터 링크 재확립 대기 — 세션 중 실기가 네트워크에서 이탈해
  중단됨(원인 미확인, 다음 세션에서 §3.0으로 우선 확인)
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
- [ ] `session_manifest.json`을 `docs/hil/RAW_LOG_CONVENTIONS.md` §3.1의 최소 필드
      **9개 전부**(`session_id`/`operator`/`aircraft_sn`/`build_commit`/
      `started_at_utc`/`ended_at_utc`/`purpose`/`steps_completed`/`notes`)를 채워
      생성한다 — `ended_at_utc`(초기값 `null`)와 `purpose`·`steps_completed`(초기값
      `[]`)도 처음부터 키 자체는 넣어둔다(2026-08-03 세션은 이 세 필드를 누락한 채
      진행돼 종료 시 되짚어 채우지 못했다 — 재발 방지)
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
# HIL_RAW_LOG_ROOT를 레포 밖에 둔다 — rsync --delete 왕복에 로그가 지워지는 사고를
# 구조적으로 차단한다(2026-08-03 세션에서 실증한 방식).
ssh <manifold-host> "cd /open_app/ksi && SESSION_ID=$SESSION_ID \
  HIL_RAW_LOG_ROOT=/open_app/ksi_hil_raw_logs bash tools/hil/collect_env_inventory.sh"
rsync -az <manifold-host>:/open_app/ksi_hil_raw_logs/$SESSION_ID/ hil_raw_logs/$SESSION_ID/
```
스크립트가 실패하는 개별 항목(예: PSDK 버전 조회)은 `MISSING: <이유>`로 남고 스크립트
전체는 계속 진행한다 — 이는 정상 동작이다.

**실기에 KSI 레포를 두는 방법 — `git rev-parse HEAD`가 성립하려면 `.git`이 필요하다.**
`git worktree`의 `.git`은 메인 저장소를 가리키는 포인터 파일이라 그대로 rsync하면
깨진다(2026-08-03 세션에서 실제로 겪음). 자기완결적 clone을 만들어 보낸다:
```bash
git clone --quiet <main-repo> <scratch>/ksi-spike-clone
git -C <scratch>/ksi-spike-clone checkout --quiet <시험할 commit>
rsync -az <scratch>/ksi-spike-clone/ <manifold-host>:/open_app/ksi/   # .git 포함, 11M 내외
```
이렇게 하면 실기에서 `git rev-parse HEAD`가 그대로 성공하고, `GIT_COMMIT`이
MISSING으로 남는 편차 없이 완전한 PASS를 얻는다.

**수집 증거**: `hil_raw_logs/<session_id>/01_env_inventory/<UTC_ts>__env_inventory.json`
(JetPack/L4T, CUDA/cuDNN/TensorRT, RAM/디스크, 네트워크 인터페이스, git commit, PSDK
버전 조회 결과 포함) + `<UTC_ts>__psdk_discovery.log`(툴체인·`dji_app_ctl --help`·
네트워크 인터페이스·USB·인터넷 가용성 — 스크립트가 안 잡는 항목 보강)

**판정 기준**:
- **PASS**: JSON이 생성됐고, 최소한 `hostname`/`uname`/`git_commit`/`disk_root`가
  `MISSING`이 아니다(장비 자체 식별과 빌드 식별은 협상 불가 최소치).
- **BLOCKED**: 스크립트 자체가 실행되지 않음(python3·bash 부재 등 환경 문제) → 이후
  단계 전부 중단, 원인을 이 문서에 기록 후 재시도.
- **실측 결과(2026-08-03)**: PASS. `L4T_RELEASE=R35.5.0`(JetPack 5.1.3),
  `OS_RELEASE=20.04.6`, CUDA 11.4.19, cuDNN 8.6.0.166, TensorRT 8.5.2.2 확인.
  상세는 `docs/edge/MANIFOLD3_TOOLCHAIN.md` §2·§4 참조.

---

### 2단계 — 툴체인 검증(KSI 온보드 빌드) + DJI 공식 샘플 빌드·실행

**목적**: 툴체인이 실제로 동작하는지 확인한다. 여기서 실패하면 이후 KSI 코드가 실패해도
그게 KSI 문제인지 툴체인 문제인지 구분할 수 없다.

**2a. KSI `edge/manifold-runtime` 온보드 네이티브 빌드 — 오늘의 최소 성공선**

```bash
ssh <manifold-host> 'cd /open_app/ksi && cmake -S edge/manifold-runtime -B /open_app/ksi-build \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo && cmake --build /open_app/ksi-build -j4'
ssh <manifold-host> 'cd /open_app/ksi-build && ctest --output-on-failure'   # ctest --test-dir 는 cmake 3.20+ 전용, 실기 3.16.3엔 없음
```

**cmake 하한 충돌**: 실기 cmake 3.16.3인데 `CMakeLists.txt`가 3.22를 요구해 첫 시도는
`CMake Error: CMake 3.22 or higher is required.`로 실패한다(원문을 로그에 남길 것 —
충돌의 1차 증거). 이건 **정정됐다**(D1, 2026-08-03) — `3.16...3.28` 범위 표기로
저장소에 반영 완료이므로 최신 코드를 받았다면 이 에러는 재현되지 않아야 한다.
재현되면 회귀이니 `edge/manifold-runtime/CMakeLists.txt:8`을 확인할 것.

**gcc 9.4 경고 주의**: CI는 gcc 13, 실기는 gcc 9.4 — `-Wall -Wextra -Wpedantic -Werror`에서
신규 경고가 날 수 있다. **`-Werror`를 끄지 않고 소스를 고친다.**

**2b. DJI 공식 PSDK 샘플 빌드·실행**
- DJI 공식 Payload SDK(PSDK) 샘플 저장소를 받아 공식 안내대로 빌드한다. 2026-08-03
  실측: `git clone https://github.com/dji-sdk/Payload-SDK.git`(V3.16.0)의 최상위
  `CMakeLists.txt`는 **이미 manifold3를 기본 빌드 대상으로 설정**돼 있다
  (manifold2→manifold3 교체 작업 불필요, README의 "기본 빌드 대상이 Manifold 2에서
  Manifold 3으로 변경" 변경 로그와 일치). `aarch64-linux-gnu-gcc`도 실기에 이미
  gcc 9.4.0으로 존재해 별도 크로스 툴체인 설치가 불필요했다.
- `samples/sample_c/platform/linux/manifold3/application/dji_sdk_app_info.h`에
  APP_ID/KEY/LICENSE/ACCOUNT 기입 필요 — **이 파일은 절대 커밋하지 않는다**
  (`.gitignore`의 `**/dji_sdk_app_info.h`, `scripts/check_repo_hygiene.sh` 규칙 4·5로 이중 차단).
- **PSDK 라이선스**: `LICENSE.txt`/`EULA.txt` 실측 확인 결과 MIT(STM32 RTOS 서브트리
  제외) — `edge/third_party/PSDK_LOCK.yaml` §license 참조. vendoring 가능 판단 근거 포함.
- 빌드 성공 후 최소 1개 공식 예제(예: 로그 출력 전용 샘플)를 Manifold 3에서 실행해
  프로세스가 정상 기동·종료하는지 확인한다. **컴파일 성공과 실행 성공(인증)은
  구분한다** — 기체 미연결·자격증명 미검증 상태에서는 컴파일까지만 PASS로 인정하고,
  실행 판정은 3단계(기체 연결) 확보 후로 미룬다.

**수집 증거**: `hil_raw_logs/<session_id>/02_sample_build/<UTC_ts>__ksi_onboard_native_build.log`
(2a: cmake 실패 원문 + 정정 근거 + 빌드/ctest 전체 출력) 및
`<UTC_ts>__sample_build.log`(2b: 빌드 전체 출력 + 실행 시 표준출력/표준에러 + 사용한
정확한 명령어 기록)

**판정 기준**:
- **PASS(2a)**: 실기에서 `ctest`가 `100% tests passed, 0 tests failed out of N`을 출력.
- **PASS(2b)**: 빌드가 에러 없이 끝났고, 최소 1개 샘플 실행이 크래시 없이 완료(또는 의도된
  종료 신호로 정상 종료)했다.
- **BLOCKED**: 빌드 실패 또는 실행 시 크래시 → 3~8단계 전부 중단. 원인(툴체인 버전
  불일치, 헤더 누락 등)을 `02_sample_build` 로그에서 확인 가능한 만큼 기록.
- **실측 결과(2026-08-03)**: **2a PASS**(gcc 9.4.0, cmake 3.16.3, `2/2 passed`,
  경고 0건 — `docs/edge/MANIFOLD3_TOOLCHAIN.md` §1). 2b는 PSDK clone·컴파일까지
  진행 중이며 완료 여부는 다음 세션에서 확정.

---

### 3.0단계(신설) — 기체 데이터 링크 확인 (`03_aircraft_telemetry/` 선행 항목)

**목적**: 3단계(Telemetry) 이후 전부가 기체와의 데이터 링크에 의존한다. 이 확인을
3단계 본체와 분리한 이유는, 2026-08-03 세션에서 **링크 확립 여부 자체가 예측 불가한
축**임이 드러났기 때문이다 — 실기 USB 이더넷(`eth0`, DHCP)은 정상 작동해도
기체 경유 가상 네트워크(`rndis0`)의 상대(`192.168.42.1`)는 응답이 없을 수 있고,
심지어 실기 자체가 세션 도중 서브넷에서 완전히 사라질 수 있다(원인 미확인 — 도킹
분리·전원 문제·재부팅 등 가능성 다수, 다음 세션에서 최우선 재현·원인 규명할 것).

**실행 항목**: 기체 E-Port 장착·전원 인가 **전/후**로 diff를 뜬다.
```bash
ssh <manifold-host> 'ip -brief addr; ip route; cat /sys/class/net/rndis0/carrier; \
  ping -c3 -W2 192.168.42.1; ls /dev/ttyACM* /dev/ttyUSB* 2>&1; lsusb'
```

**수집 증거**: `03_aircraft_telemetry/<UTC_ts>__link_probe.log`

**판정 기준**:
- **PASS**: `192.168.42.1`(또는 PSDK가 실제로 쓰는 링크)에 도달 — 3단계로 진행.
- **BLOCKED(`AIRCRAFT_LINK_DOWN`)**: 미도달 → 3~8단계 전부 중단.
- 주의: `rndis0` carrier=1(USB 링크 레벨 연결)이어도 상대(기체)가 응답 안 할 수
  있다 — carrier는 "케이블이 꽂혀 있다"만 보장하지 "기체가 응답한다"를 보장하지 않는다.
- **실측 결과(2026-08-03)**: 세션 초반 `rndis0 carrier=1`이었으나 `192.168.42.1`
  무응답으로 BLOCKED. 이후 세션 중 실기 자체가 서브넷(`172.30.1.0/24`)에서 완전히
  사라져(USB 이더넷 `eth0` 포함) 원인 규명 전 세션이 중단됐다. **다음 세션 최우선
  항목**: 이 단계를 재현해 원인(전원/도킹/재부팅 중 하나로 좁힐 것)을 확정한다.

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

**이 단계의 명령은 현재 미구현이다(PENDING).** 아래 블록은 ADR-KSI-009 D3(수집은
C, 판정은 Python)이 확정한 **설계**를 그대로 적은 것이지, 지금 실행 가능한 명령이
아니다 — `edge/psdk-tap`은 코드가 아직 없고(디렉터리 자체가 저장소에 없다),
`tools/hil/capture_frame_telemetry_timing.py`의 `collect` 서브커맨드도 현재는
`--session-id/--aircraft-sn/--out/--num-samples` 4개 인자만 받아 아래의
`--source`/`--tap-log`/`--timestamp-basis`는 아직 존재하지 않는다. **이 명령은
`edge/psdk-tap` 구현과 `collect` 인자 확장을 완료한 뒤에야 유효하다** — 다음 세션
선행 작업.

**실행 항목(설계, 구현 후 유효)** — ADR-KSI-009 D3(수집은 C, 판정은 Python) 적용:
```bash
# 1) 실기에서 C tap이 PSDK liveview + FC subscription 콜백으로 NDJSON을 쓴다
ssh <manifold-host> 'edge/psdk-tap/build/frame_telemetry_tap --num-samples 400 \
    --out /open_app/ksi_hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__psdk_tap.ndjson'
rsync -az <manifold-host>:/open_app/ksi_hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/ \
    hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/

# 2) 개발 PC(Python 3.12)에서 tap의 raw NDJSON을 공식 판정 도구가 읽는 JSONL로 변환
uv run python tools/hil/capture_frame_telemetry_timing.py collect \
    --source tap-log --tap-log hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__psdk_tap.ndjson \
    --session-id "$SESSION_ID" --aircraft-sn <실측 기체SN> \
    --timestamp-basis sensor \
    --out hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl
```

**왜 두 언어로 나뉘는가**: 실기 Python은 3.8.10인데
`tools/hil/capture_frame_telemetry_timing.py`는 `StrEnum`·`datetime.UTC`(3.11+)를
쓴다 — 2026-08-03 실기 세션에서 이 모듈이 **실기에서 import조차 안 됨**을 실측
확인했다. 백포트해서 3.8 호환으로 낮추면 공식 Acceptance Profile·증거 무결성
게이트의 엄격성이 내려간다. 그래서 PSDK 콜백 수신은 `edge/psdk-tap`(C, 실기에서
네이티브 컴파일)이 맡고, 공식 판정(`summarize --mode official`)은 개발 PC Python
3.12에서 그대로 수행한다.

**`--timestamp-basis`는 필수 인자다**(기본값 없음 — 무의식적 선택을 차단). PRD
§21.1 "Sensor Timestamp alignment"의 정본은 `sensor`(카메라/Telemetry 자체
타임스탬프)이지만, PSDK가 그 값을 노출하지 않으면 `recv`(파이프라인 도착 시각)로
대체하되 그 사실을 `test_procedure`·`latency_result`에 명시한다 — 대체 정의로 낸
PASS를 "센서 시각 정합 PASS"라고 부르면 안 된다(정의 변경은 profile v2 문제이므로
대표자 결정 레인).

**표본 수는 넉넉히 요청한다** — 공식 최소 100인데 드롭률이 미지수이므로 400~600
요청을 권장(30fps면 20~30초). 200 요청 후 드롭으로 99개가 되면 세션이 헛돈다.

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

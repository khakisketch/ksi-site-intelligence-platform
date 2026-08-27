# Hardware Session Playbook (Track A — DJI Matrice 4D + RC Plus 2 + Manifold 3)

- 상태: **1~2단계 실기 검증 완료**(2026-08-03, `SESS-20260803T125616Z-PENDING-SN`).
  **3.0단계 PASS**(2026-08-12, `SESS-20260812T170000Z-MANIFOLD-LINK`) — 기체 링크는
  살아 있다. 다음 관문은 **8단계(dpk 설치·기동)이며 3~7단계보다 선행한다**(§3.0 본문 참조).
  2026-08-13/14에는 **매니폴드가 네트워크에 없다**(172.30.1.33 ARP FAILED)가
  차단 요인이었다. 2026-08-26 유선 read-only 재검증에서는 SSH/noVNC와 기체발
  6-source DUSS/Liveview 메시지가 다시 확인됐다. 다만 KSI DPK는 설치돼 있지 않고,
  RC Plus 2 세션·device-bound approval·propeller-off write 조건이 없으며, USB bulk
  두 번째 논리 채널도 bulk4/bulk5 중 어느 것인지 목록 관찰만으로 확정되지 않았다.
  그러므로 다음 관문은 여전히 승인된 8단계(DPK 설치·기동)이고 현재 세션에서는 실행하지 않는다.

  > **이 머리말은 2026-08-13에 정정됐다.** 이전 판은 "3단계 이후는 기체 데이터 링크
  > 재확립 대기 — 세션 중 실기가 네트워크에서 이탈해 중단됨(원인 미확인)"이었다.
  > 그 판정 둘 다 2026-08-12 온보드 실측으로 무효가 됐다: ① 링크 판정에 쓴 `ping`이
  > 애초에 무효한 지표였고 ② "실기가 사라진다"는 호스트 측 ARP 해석 실패였다(기기는
  > uptime 단절 없이 계속 돌고 있었다). §3.0 본문은 그때 정정됐는데 이 머리말이
  > 따라가지 않아 두 세션이 "장비 대기"로 오독될 뻔했다.
  >
  > **2026-08-14 추가 정정.** 위 "psdk_tap이 SDK 시작 단계에서 크래시" 서술도 저장소
  > 근거로 뒷받침되지 않아 제거했다(`.ksi/goals.json` `track-a` 2026-08-14 정정,
  > 12-agent 코드감사 재확인). 그 표현은 2026-08-04 하드웨어 없는 워크스테이션에서 난
  > SIGSEGV(이미 `usb_bulk_glue.c` 핸들 등록 방어선으로 처리됨)와 2026-08-12 실기의
  > `0x000000EC`(정상 오류 반환 — SSH 단독 실행이 USB bulk 채널을 DJI 상주 데몬과
  > 경합한 것이지 크래시가 아니다)를 뒤섞은 것이었다. 다음 세션이 이 문구만 보고
  > "코드 디버깅이 남았다"고 오독하지 않도록 굳힌다.
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

> **[2026-08-15 추가 — ADR-KSI-020]** 위 금지에 **온보드 임무 실행(`DjiWaypointV3_Action`,
> `DjiWaypointV2_*`, `DjiInterestPoint_*`, `DjiFts_*`)** 도 명시적으로 포함된다.
> 특히 `DjiWaypointV3_Action(START)` 는 "임무를 건다"처럼 들리지만 **시동·이륙을
> 실제로 수행한다.** 10단계는 그 계열 중 `Init`(과 조건부 `UploadKmzFile`)의 **반환값만**
> 보는 확인이며, 프로펠러 제거가 전제다.

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
  사라져(USB 이더넷 `eth0` 포함) 원인 규명 전 세션이 중단됐다.

- **실측 결과(2026-08-04, 호스트 측 관측만)**: **같은 이탈이 재현됐다.** 다만 이번에는
  이탈 전후를 호스트에서 연속 관측해 원인 후보를 좁혔다.

  | 시각(KST) | 관측 |
  |---|---|
  | 16:3x | `172.30.1.33` 도달. `22`(SSH, 계정 `dji` 존재) · `6080`(noVNC, HTTP 200 · `<title>noVNC`) 동시 응답. MAC `c0:ea:c3:6a:22:b0` |
  | 18:1x | 무응답. ARP `FAILED`. `/24` 전수 스윕에서 **해당 MAC 부재** |

  **이번에 새로 배제된 것들** — 지난 세션이 열어 둔 후보 중:
  - **DHCP 임대 갱신으로 IP만 바뀐 것이 아니다.** `/24` 전수 스윕 결과 MAC
    `c0:ea:c3:6a:22:b0`이 **어떤 IP에도 없다**. 장치가 링크 레벨에서 사라졌다.
  - **공유기·AP·우리 쪽 네트워크 문제가 아니다.** 같은 시각 게이트웨이(`172.30.1.254`)와
    다른 호스트 7대는 전부 정상 응답했다.
  - **우리가 보낸 명령이 유발한 것이 아니다.** 이탈 구간 내내 실기로 나간 트래픽은
    최초 포트 스캔뿐이고(SSH 인증은 `publickey` 거부로 끝났다), 그 뒤 약 1시간 40분 동안
    **완전히 유휴 상태**에서 사라졌다. 2026-08-03 세션에서 의심했던 "도킹 분리·조작 충격"
    가설은 이 관측과 맞지 않는다.

  **남은 후보(호스트에서는 더 좁힐 수 없다 — 물리 관측 필요)**: 전원 공급 중단(도킹 PD
  불안정·배터리 소진) · 절전/서스펜드 진입 · 과열 보호 정지 · 자발적 재부팅 후 네트워크
  미복구.

  **다음 세션 최우선 항목(갱신)**: 이탈 순간을 물리로 확인한다.
  1. **LED 상태를 먼저 본다** — 꺼짐=전원 없음 · 초록느림=정상(네트워크만 문제) ·
     초록상시=부팅 중(재부팅했다는 뜻) · 노랑느림=과열 감속 · 빨강느림=업데이트 실패.
     LED 하나로 위 후보 대부분이 갈린다([[manifold3-physical-constraints]] 매뉴얼 §1.1).
  2. 도달 가능한 동안 **`ssh-copy-id`를 최우선으로 끝낸다**. 2026-08-03·08-04 두 세션
     모두 키 설치 전에 장치가 사라져 온보드 관측을 한 번도 못 했다 — 셸이 없으면
     `uptime`(재부팅 여부)·`dmesg`(전원/과열)·`journalctl` 어느 것도 볼 수 없어
     원인 규명이 구조적으로 불가능하다. **이것이 이 항목의 실제 병목이다.**
  3. 셸 확보 후 즉시 `uptime -s`(부팅 시각)·`last -x reboot`·`dmesg -T | grep -iE
     'thermal|power|usb|eth'`를 떠서 이탈이 재부팅인지 링크 다운인지 확정한다.

- **실측 결과(2026-08-12) — "장치가 사라진다"는 판정이 반증됐다. 장치는 살아 있었다.**

  이 세션에서 셸을 확보한 직후 온보드에 5분 주기 상태 기록을 심었다(cron, 사용자 권한
  — `dji` 계정은 sudo 가 없어 systemd 저널 영속화는 못 한다). 그 뒤 **같은 이탈이
  재현됐고**, 이번에는 이탈 구간이 통째로 온보드에 남았다.

  | 시각(KST) | 호스트에서 본 것 | 온보드 기록 |
  |---|---|---|
  | 17:24 | SSH 두절. `ping` → `From 172.30.1.43 Destination Host Unreachable` | — |
  | 17:20~18:55 | 계속 무응답 | **5분 간격 기록이 단절 없이 이어짐.** uptime 카운터 연속 증가(2579s→8279s, 재부팅 흔적 0), `eth0 UP 172.30.1.33/24` **동일 IP 유지** |
  | 18:56:30 | — | 재부팅 1회(uptime 8279s→212s) — 이탈보다 **1시간 30분 뒤**라 이탈의 원인이 아니다 |
  | 19:0x | 다시 도달 가능 | 정상 |

  **결론: 기기가 사라진 것이 아니라 관측자–기기 사이 경로가 끊긴 것이다.**
  호스트가 받은 `Destination Host Unreachable` 의 발신자는 **호스트 자신**(`172.30.1.43`)
  이다 — 내 쪽에서 상대를 ARP 해석하지 못했다는 뜻이지 상대가 없다는 뜻이 아니다.

  **따라서 2026-08-03·08-04 의 "장치가 링크 레벨에서 사라졌다" 판정도 근거를 잃는다.**
  그 판정들은 전부 호스트 측 스윕만으로 내려진 것이고, 이 문서 자신이 그 한계를
  적어뒀다("호스트에서는 더 좁힐 수 없다 — 물리 관측 필요"). 온보드 증거가 생기자
  반대 결론이 나왔다. 전원 상실·과열 정지·서스펜드 가설은 **이번 재현에 한해** 전부
  배제된다(uptime 이 연속이므로 무엇도 프로세스를 멈추지 않았다).

  남은 후보는 우리 쪽 네트워크 경로다: 스위치/AP 의 MAC 테이블 만료·포트 플랩,
  유선-무선 세그먼트 전환, 케이블. 이건 호스트에서 좁힐 수 있는 종류다.

  **절차 변경**: 3.0단계 이탈을 판정할 때 **호스트 관측만으로 BLOCKED 를 찍지 않는다.**
  셸을 확보하는 즉시 아래를 심고, 이탈이 나면 재접속 후 그 기록부터 본다.

  ```bash
  # 온보드(dji 계정, sudo 불필요) — 5분마다 uptime·IP·경고레벨 로그 요약을 남긴다.
  # 하루 최대 수 MB 로 억제한다(초기 판에서 5분당 5MB 를 먹어 디스크를 위협했다 —
  # 실기 여유 공간이 8.6GB 뿐이다).
  crontab -l 2>/dev/null | grep -v ksi_health_log.sh > /tmp/ct
  echo "*/5 * * * * /home/dji/ksi_health_log.sh" >> /tmp/ct && crontab /tmp/ct
  ```

  재접속 후 이탈 구간 판정:

  | 온보드 기록 | 해석 |
  |---|---|
  | 기록이 **끊겼다** | 기기가 실제로 멈췄다(전원·과열·재부팅) — uptime 리셋 여부로 갈린다 |
  | 기록이 **이어졌고 IP 도 같다** | 기기는 정상. **네트워크 경로 문제다** — 스위치·케이블·세그먼트를 본다 |
  | 기록은 이어졌는데 IP 가 바뀌었다 | DHCP 임대 갱신 — 새 IP 로 재접속 |

- **실측 결과(2026-08-12) — 3.0단계 판정 기준(ping) 자체도 틀렸다. 정정한다.**

  이 세션에서 셸을 확보하고 온보드에서 직접 관측한 결과, **`ping 192.168.42.1`은
  기체 링크의 유효한 지표가 아니다.** 2026-08-03·08-04 두 세션의
  `BLOCKED(AIRCRAFT_LINK_DOWN)` 판정은 이 잘못된 지표에 근거했다.

  | 관측 | 결과 |
  |---|---|
  | `ping 192.168.42.1` (rndis0·l4tbr0 양쪽) | 100% loss — 지금도 동일 |
  | `ip neigh` | `192.168.42.1` **REACHABLE**, MAC `b6:2f:db:c4:12:f9`(L2 정상) |
  | `.101`·`.102` ping | 응답함. `.102`가 `.1` 앞에서 ICMP Destination Host Unreachable 반환 |
  | 42.x 대역 TCP 포트 스캔(22·80·443·8080·9000·2001·3000) | **전부 닫힘** — 기체는 IP 서비스를 열지 않는다 |
  | `journalctl` (dji_sdk_agent) | `Liveview uuid info total_num: 6` — **기체가 카메라/센서 6종 목록을 실제로 보내고 있다** |
  | `journalctl` (dji_sec) | `ciu98d_comm_chip_get_cert success` → `device_auth online to uav 0x1401` — 보안칩 인증이 기체와 진행 중 |

  **결론**: 기체-매니폴드 통신은 ICMP/TCP가 아니라 DJI 사유 프로토콜(DUSS, USB
  bulk 채널)로 이뤄진다. `.1`이 핑에 응답하지 않는 것은 정상이며, 링크 상태를
  ping으로 판정하면 **살아 있는 링크를 죽었다고 오판한다**. 판정 지표를 아래로
  바꾼다.

  **정정된 판정 기준(3.0단계)**:
  - **PASS**: `journalctl`에 기체發 DUSS 메시지가 실제로 흐른다. 최소 신호 —
    `dji_sdk_agent`의 `Liveview uuid info total_num: N`(N>0) 또는 `dji_sec`의
    `device_auth ... to uav 0x####`.
  - **BLOCKED**: 위 신호가 전무하다(로그가 조용하거나 링크 초기화 단계에서 멈춤).
  - `ping 192.168.42.1`은 **참고 정보로도 쓰지 않는다** — 결과와 무관하게 무의미하다.

  ```bash
  ssh <manifold-host> "journalctl --no-pager -q --since '-60 seconds' \
    | grep -E 'Liveview uuid info|device_auth .* to uav'"
  ```

  **DUSS 에러 로그가 다량 나오는 것은 그 자체로 BLOCKED 근거가 아니다.** 실측상
  `LINK_DEBUG-EVENT_SEND-WAIT_LIST Timeout to wait ack`·`no req_cb for event`류가
  초당 수십 건 나오는 동시에 위 성공 신호도 함께 흐른다 — 여러 하위 데몬이 각자
  재시도하는 상태이지 링크 부재가 아니다.

- **실측 결과(2026-08-12) — PSDK 앱은 SSH 단독 실행으로는 링크를 잡을 수 없다.**

  `psdk_tap`을 실기 타깃으로 빌드해 배포하고 SSH에서 직접 실행한 결과:

  ```
  dji_channel_bulk.c:120  Read usb bulk data failed, ret:000000EC
  dji_access_adapter.c:1888 DjiLinker_SendMsg, stat:236
  dji_core.c:153  Access adapter identify aircraft series error on manifold3, stat:0
  telemetry 구독 시작 실패: 0x000000EC
  ```

  같은 시각 DJI 자체 데몬(`dji_sdk_agent`·`dji_sec`·`dji_app_mgr`, 전부 root 상주)은
  같은 링크로 정상 통신 중이었다. 즉 **USB bulk 채널은 DJI 앱 프레임워크가 점유하며,
  우리 앱이 그 채널을 직접 열 수 없다.** 0xEC는 자격증명·빌드 문제가 아니라 채널
  점유 문제로 읽어야 한다(2026-08-03 세션이 "샘플이 크래시 없이 대기"로 관측한 것도
  같은 상태로 보인다).

  **따라서 3단계 이후(텔레메트리·라이브뷰 실측)의 전제는 "기체 링크 복구"가 아니라
  "우리 앱을 `.dpk`로 패키징해 `dji_app_ctl`로 설치·기동"이다** — §8(`08_dpk_deploy/`)이
  선행 조건이지 후속 작업이 아니다. 이 순서 오해가 지금까지 3단계를 막고 있었다.

  참고(2026-08-12 실측, risk `manifoldctl-dpk-install-permission-unknown` 해소):
  `dji` 계정은 sudo 권한이 없고 `/vendor_app`·`/etc/systemd/system`에 쓰지 못하지만,
  `dji_app_ctl`은 비-setuid 클라이언트일 뿐이고 실제 특권 쓰기는 root로 상주하는
  `dji_app_mgr`(PID 568)가 수행한다 — **rootless SSH 세션이어도 설치가 권한으로
  막히지 않는다.** RC 경유로 설치된 `Smart3DExplore`가 `/vendor_app/Smart3DExplore`
  + `/etc/systemd/system/Smart3DExplore.service`(둘 다 root:root)로 안착한 것이
  그 실증이다.

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

**구현 상태(2026-08-14): 소프트웨어 경로는 있고, 실기 실행은 아직 없다.**
`edge/psdk-tap`(C 수집기), official `.dpk` build target, 그리고
`collect --source tap-log` 경로는 구현·target ABI 검증됐다. 다만 **이 경로 전체가
실기에서 한 번도 돌지 않았다**: `psdk_tap`은 PSDK 실물과 DJI-issued App credential이
필요하고, DPK 설치·기동 성공도 별도 HIL 증거가 필요하다. CI가 검증하는 것은
PSDK 비의존 pairing logic뿐이다 — callback, `/tmp` output, NDJSON, 프레임 수렴은
실기에서 처음 확인된다.

**순서 강제:** 2026-08-12 실측상 SSH에서 executable을 직접 실행하면 USB bulk channel을
얻지 못한다. 따라서 이 단계는 **8단계 DPK 설치·기동이 PASS 또는 해당 앱의 정상 기동
로그를 남긴 뒤에만** 수행한다. 아래 명령의 DPK는 DJI-issued `user_app_id`와 실제
credential을 써야 하며, CI의 test ID package는 설치하지 않는다.

**실행 항목** — ADR-KSI-009 D3(수집은 C, 판정은 Python) 적용:
```bash
# 1) 개발 PC/target container에서 official HIL DPK 생성 (실제 DJI-issued ID만 사용)
cmake -S edge/psdk-tap -B edge/psdk-tap/build-manifold3 \
    -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
    -DKSI_TARGET_MANIFOLD3=ON \
    -DKSI_PSDK_TAP_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
    -DKSI_PSDK_TAP_BUILD_DPK=ON \
    -DKSI_PSDK_TAP_DPK_USER_APP_ID=<DJI_issued_id>
cmake --build edge/psdk-tap/build-manifold3 --target ksi_psdk_tap_dpk -j

# 2) DPK manager가 app을 기동하게 한다. SSH 직접 ./psdk_tap 실행은 금지.
scripts/manifold/manifoldctl install \
    edge/psdk-tap/build-manifold3/dpk/out/ksi-psdk-tap_v00.01.00.02.dpk
scripts/manifold/manifoldctl restart ksi-psdk-tap
scripts/manifold/manifoldctl status ksi-psdk-tap

# 3) 무인자 DPK는 기본 60초 수집 후 /tmp에 raw NDJSON을 쓴다. 실제 권한/경로는 로그로 검증.
sleep 65
scp <manifold-host>:/tmp/ksi-psdk-tap.ndjson \
    hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__psdk_tap.ndjson

# 4) 개발 PC(Python 3.12)에서 raw NDJSON을 공식 JSONL로 변환한다.
# Liveview frame sensor timestamp가 없으므로 recv 진단만 가능하며 sensor PASS를 주장하지 않는다.
uv run python tools/hil/capture_frame_telemetry_timing.py collect \
    --source tap-log --tap-log hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__psdk_tap.ndjson \
    --session-id "$SESSION_ID" --aircraft-sn <실측 기체SN> \
    --timestamp-basis recv \
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
타임스탬프)이다. 현재 PSDK Liveview callback은 frame sensor timestamp를 주지 않으므로
위의 `recv`(파이프라인 도착 시각) 결과는 수신 경로 진단만 뜻한다. `recv`로 숫자가
좋아도 **sensor alignment PASS/VERIFIED/CONFIRMED 승격 근거가 아니며**, sensor source를
실제로 확보해 `frame_sensor_ts=true` raw record를 다시 수집하기 전에는 이 단계의 sensor
criterion은 `BLOCKED`로 남긴다.

**별도 PSDK perception stream을 RGB timestamp로 오인하지 않는다(2026-08-14 재확인).**
PSDK 3.16.0의 `dji_perception.h`에는 `DjiPerceptionImageCallback`과
`T_DjiPerceptionImageInfo.timeStamp`가 있고, DJI의
[Perception Data 문서](https://developer.dji.com/doc/payload-sdk-tutorial/en/function-overview/advanced-function/perception-data.html)는
M4D에서 Manifold 3를 통해 받는 **회색조 시각-perception 카메라** 스트림이라고 명시한다.
이는 `DjiLiveview_StartImageStream(..., PIXFMT_RGB_PACKED, ...)`의 payload RGB frame과
서로 다른 센서·형상·callback이다. 따라서 perception `timeStamp`를 수신시각에 가장 가까운
Liveview RGB frame에 복사하거나 `frame_sensor_ts=true`로 표시하는 것은 금지한다.

이를 sensor-timing 경로로 채택하려면 별도 `SPIKE-DJI-07`에서 다음을 실증해야 한다.

- 설치된 DPK 안에서 perception USB logical channel과 실제 callback 수신을 먼저 기록한다.
- `timeStamp`의 단위·epoch·wrap 규칙, 그리고 HARD_SYNC timestamp와의 동일 time domain을
  100개 이상의 raw 쌍으로 검증한다. PSDK header의 `uint64_t` 필드명만으로 단위나
  host monotonic 환산을 추정하지 않는다.
- perception grayscale camera의 intrinsics/extrinsics와 D-FINE 입력 계약을 별도로 검증한다.
  이 증거는 RGB payload camera calibration 또는 RGB timing의 대체물이 아니다.

`edge/psdk-tap`에는 이 첫 항목을 위한 raw probe가 구현돼 있다. DPK가 argv 없이
기동되므로 perception probe package는 아래와 같이 compile-time default를 명시해 만든다.

```bash
cmake -S edge/psdk-tap -B edge/psdk-tap/build-manifold3-perception \
    -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
    -DKSI_TARGET_MANIFOLD3=ON \
    -DKSI_PSDK_TAP_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
    -DKSI_PSDK_TAP_BUILD_DPK=ON \
    -DKSI_PSDK_TAP_DPK_USER_APP_ID=<DJI_issued_id_max_16_ascii_bytes> \
    -DKSI_PSDK_TAP_DEFAULT_FRAME_SOURCE=perception \
    -DKSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION=front
cmake --build edge/psdk-tap/build-manifold3-perception --target ksi_psdk_tap_dpk -j
```

이 probe의 NDJSON v2 `frame.sensor_timestamp_raw_u64`는 lossless decimal string이고
`meta.timestamp_contract.sensor_us_domain="unverified"`다. 즉 callback 수신/USB mapping
및 raw sequence 분석을 위한 증거일 뿐, `sensor_us`나 sensor-alignment 표본이 아니다.
Python 변환기의 `--timestamp-basis sensor`는 `host_monotonic_us`라는 명시적 정규화 계약이
없으면 fail-closed하므로, 위 100개 raw 쌍 clock-domain 실증을 마치기 전에는 sensor PASS가
나올 수 없다.

그 spike가 끝나기 전에는 현재 tap의 `frame_sensor_ts=false`와 RGB pipeline의
`SENSOR_ALIGNMENT_REQUIRED`가 정본이다.

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
- **`measurement_status=MEASURED` + `acceptance_status=PASS` + `timestamp_basis=sensor`**:
  표본 수 ≥ 100(권장, 통계적 신뢰를 위한 최소치) **그리고** p95 ≤ 50ms. VERIFIED 승격
  근거는 이 조합뿐이다. `timestamp_basis=recv`의 PASS는 이 행을 만족하지 않는다.
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

### 7.5단계 — TensorRT ↔ ONNX corpus differential (`07_frame_telemetry_timing/`의 별도 evidence)

이 단계는 live flight나 PSDK callback에서 실행하지 않는다. 동일 Manifold TensorRT/CUDA
ABI에서 registered ONNX로 engine을 만들고, raw RGB corpus 최소 10개를 C++ TensorRT runner와
Python ONNX oracle에 각각 통과시켜 input tensor digest·class/query·confidence·original-pixel
bbox·typed drops가 일치하는지 확인한다. raw corpus/ONNX/engine/evidence는 git 밖의 durable
URI에 보관한다.

1. `corpus.json`의 canonical digest, ONNX digest, `preprocessor_config.json` digest,
   corpus ID/count 및 허용오차(`confidenceAtol <= 0.001`, `bboxAtolPx <= 0.5`)를 **unsigned
   candidate** `EdgeRuntimeProfile.tensorRtDifferential`에 채운다. candidate는 Core 서명 전에는
   perception을 활성화하지 않는다.
2. Manifold target에서 `KSI_ENABLE_TENSORRT=ON`과 `tensorrt_differential_runner`를 빌드한다.
   C++ runner가 `BACKEND_UNAVAILABLE`, ONNX digest mismatch, engine build/load/inference 실패를
   내면 `BLOCKED`이며 CPU/Python fallback으로 바꾸지 않는다.
3. 개발 PC의 Python 3.12에서
   `tools/edge/verify_tensorrt_differential.py verify`를 실행한다. 정확한 command와 corpus
   wire 형식은 [`edge/manifold-runtime` README](../../edge/manifold-runtime/README.md#tensorrt--onnx-differential-evidence)를
   따른다.
4. canonical evidence digest를 candidate에 넣은 뒤에만 Core가 signed profile을 발행한다.
   같은 artifact를 재검사할 때는 `--require-profile-evidence-digest`를 추가한다.

**PASS 기록 조건**: 결과 evidence와 raw TensorRT/ONNX report의 durable URI, ONNX·preprocessor
·corpus·evidence digest, runner/target TensorRT version, sample count(≥10), two tolerances 및
`PASS` 결과가 모두 있어야 한다. TensorRT differential PASS는 모델 경계 software evidence일
뿐이다. DPK 설치/restart, RGB/telemetry timing, calibrated projection, 5 Hz, hardware verified,
production supported로 승격하지 않는다.

### 7.6단계 — Edge candidate durable latency (`07_frame_telemetry_timing/`의 별도 evidence)

**목적**: `REQ-EVT-101`의 후보 생성 부분을 실측한다. 범위는 의도적으로 좁다:
PSDK RGB callback의 동일 process `CLOCK_MONOTONIC` 수신시각부터 SQLite의
candidate+evidence transaction이 durable `ACCEPTED`를 반환할 때까지다. 이 DPK slice는
사용자 로컬경보와 Core→사용자 서버알림을 구현하지 않으므로, 이 단계는 Critical
1초/2초/5초 전체 SLO를 PASS시키는 경로가 아니다.

**전제조건**: signed perception profile, registered TensorRT/ONNX differential evidence,
calibration, sensor-time alignment이 모두 충족되어 실제 candidate가 만들어져야 한다. 현재
표준 DPK는 이 입력들이 없으면 capture-only이므로 artifact가 0개인 것이 정상이며, 그
경우 이 단계는 `NOT_MEASURED`다. 테스트 입력이 Critical 사건을 대표한다는 근거도 이
artifact 밖에서 별도로 남긴다.

**수집**:

1. DPK를 중지한 뒤, private `PERCEPTION_STATE_DIR/artifacts/`의
   `event-timing-*.json` **사본**만 raw log로 옮긴다. 원본 vault를 수정·rename·삭제하지
   않는다.
2. HIL machine에서 고정 validator를 실행한다. `build_commit`은 session manifest와 같은
   commit이어야 한다.

```bash
uv run python tools/hil/summarize_event_candidate_timing.py summarize \
  --in-dir hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__candidate_durable_timing \
  --out hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__candidate_durable_timing_summary.json \
  --session-id "$SESSION_ID" \
  --build-commit "$(git rev-parse HEAD)"
```

validator는 schema/stage/clock domain, integer latency 재계산, duplicate candidate ID,
손상 JSON을 검증한다. 기준값은 CLI로 바꿀 수 없는
`ksi-edge-candidate-durability-v1`의 **모든** measured sample `max <= 1000 ms`다.

**판정**:

- `evidenceStatus=VALID`, `measurementStatus=MEASURED`,
  `candidateDurabilityBudget.status=WITHIN_BUDGET`: 해당 좁은 candidate-durable stage의
  실측 evidence다. hardware/production 또는 전체 REQ-EVT-101 PASS로 승격하지 않는다.
- `NOT_MEASURED`, `PARTIAL`, `INVALID`, `NOT_EVALUABLE`: PASS가 아니다. clock rollback,
  callback timestamp/worker clock 부재, corrupt copy, duplicate input 등의 구체 사유를
  summary와 session note에 남긴다. 남은 좋은 표본만으로 PASS를 주장하지 않는다.
- `EXCEEDED`: 실측한 candidate-durable stage가 1초 목표를 넘었다. `BLOCKED`
  (`requirement_not_met`)로 남기며, 처리율/queue/engine 경로를 별도 분석한다.

전체 Critical SLO에는 위 raw artifact 외에 (a) 입력이 실제 Critical임을 묶는 replay/HIL
lineage, (b) 사용자 로컬경보 2초, (c) 서버 연결 시 사용자 알림 5초의 별도 timestamped
evidence가 필요하다. 현재 shadow slice에는 (b)/(c) 구현이 없으므로 이 세 항목을
`EventBundle.timing`에 추정치로 쓰거나 완료로 표기하지 않는다.

### 8단계 — DPK 설치·재시작 검증 (`08_dpk_deploy/`)

**목적**: 배포 경로(빌드된 페이로드 애플리케이션을 Manifold/기체에 설치하고 재시작 후
정상 기동하는 경로)가 실제로 동작하는지 확인한다. **"DPK"라는 명칭·정확한 패키지
포맷은 이 문서 작성 시점에 확신 없이 단정하지 않는다** — DJI PSDK가 페이로드
애플리케이션을 배포하는 표준 절차/패키지 형식을 2단계에서 확인한 공식 문서/샘플
기준으로 그대로 따른다.

**실행 항목**:
- DJI-issued `user_app_id`와 실제 credential로 만든 `.dpk`만
  `scripts/manifold/manifoldctl install <local.dpk>`로 설치
- `scripts/manifold/manifoldctl restart <app_name>` 뒤
  `scripts/manifold/manifoldctl status <app_name>` 및 `list <app_name>`를 기록
- 재시작 후 애플리케이션이 정상 기동하고, HIL probe라면 raw output 파일까지 실제로 생성되는지 확인

**수집 증거**: `hil_raw_logs/<session_id>/08_dpk_deploy/<UTC_ts>__dpk_deploy.log`
(설치 명령·출력, 재시작 전후 상태, 기동 로그)

**판정 기준**:
- **PASS**: 설치가 에러 없이 끝났고, 재시작 후 애플리케이션이 확인 가능한 상태로
  기동했다.
- **BLOCKED**: 설치 실패 또는 재시작 후 기동 실패 → "운영 배포가 동작한다"는 주장을
  하지 않는다.

### 8.1단계 — activation control-plane companion (activation-enabled DPK에만)

`KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION=ON`인 DPK는 `active-dispatch.native.v1` handoff를
읽을 뿐, Mission Dispatch를 자체 pull하거나 Python verifier를 callback에서 실행하지
않는다. 별도 Python 3.12 `ksi-edge-dispatch-sync` companion이 한 번에
`GET /v1/edge-sync/missions/next` → 기존 signed verifier → matching activation receipt POST를
수행한다. Core bearer는 private `0600` file에서만 읽고, supplied CA + exact Core SPKI pin을
검증한 뒤에만 header를 보내며 redirect를 따르지 않는다.

**실기 제약**: 현 Manifold 기본 Python은 3.8.10이고 이 package는 Python 3.12를 요구한다.
현재 `.dpk`도 native executable만 package한다. 따라서 operator는 stock Python을 백포트하거나
DPK callback에 Python을 넣지 말고, 실제 DPK 사용자와 같은 private `0700` activation state
directory에 접근 가능한 별도 검토된 non-root Python 3.12 runtime(또는 동등한 atomic handoff)을
먼저 제공해야 한다. directory ownership/mode, Core CA/SPKI pin, public key registry, token file의
소유권은 HIL에서 실측한다. 이 조건이 없으면 DPK는 capture-only로 남고 이 단계는 `BLOCKED`다.

비밀값은 command line·raw log·git에 넣지 않는다. 실제 값은 operator가 private file/secure
configuration에 넣고, log에는 아래와 같은 non-secret verdict만 남긴다.

```bash
# 3.12 companion이 실제 native handoff directory를 보는 환경에서 one-shot 실행.
ksi-edge-dispatch-sync \
  --core-base-url https://<core_origin> \
  --tls-ca-bundle <reviewed_ca_bundle> \
  --core-spki-pin sha256//<core_spki_pin> \
  --bearer-token-file <private_0600_edge_token> \
  --keys-dir <public_verification_key_directory> \
  --state-dir <same_private_0700_activation_state_dir> \
  --edge-device-id <device_id> \
  --runtime-version <runtime_version>
```

**추가 PASS 증거**: `NO_MISSION`(204), successful
`ACTIVATED_AND_RECORDED`, 그리고 receipt network/5xx failure 뒤
`ACTIVATED_RECEIPT_PENDING` 상태에서도 private native handoff가 유지되고 다음 one-shot이
같은 pending dispatch를 idempotently receipt 처리하는 redacted log가 필요하다. 이 결과는
PSDK ingress/telemetry/RGB/timing HIL을 대체하지 않으며, 실제 비행 command를 수행하지 않는다.

### 9단계 — Pilot 2 웹뷰 JSBridge 접속점 확인 (`09_pilot_cloud_jsbridge/`, 신설 2026-08-15)

**왜:** ADR-KSI-019 G3의 최소 접속 관문이다. 2026-08-27 현재 DJI 라이브 공식
문서에는 Pilot 2 Wayline Management와 JSBridge mission module이 명시돼 있다.
그러나 Product Supported 표에 exact `M4D + RC Plus 2 + Pilot 2` 조합은 없으므로
문서상 기능 존재를 실기 지원으로 승격하지 않는다(REQ-ACQ-103).

**이 단계에서 하는 것 — read-only, wayline 발급 없이 확인 가능한 것만:**

0. KSI workstation과 RC Plus 2를 같은 신뢰 LAN에 두고 probe를 실행한다.

   ```bash
   uv run --locked python -m ksi_dji_gateway.open_platform_probe \
     --bind 0.0.0.0 --port 8080
   ```

   Pilot 2 → Cloud Services → Open Platforms에
   `http://<workstation-ip>:8080/pilot-connect`를 입력한다. probe는 GET/HEAD만 제공하고
   access log를 남기지 않으며 CSP `connect-src 'none'`으로 결과 송신도 막는다.
1. 화면의 `window.djiBridge` 판정을 본다. `BRIDGE ABSENT`면 이 RC/Pilot 2 환경에서
   접속점이 노출되지 않은 것이고, 그 자체가 결론이다(지어내지 않는다).
2. `platformGetVersion`, `platformIsVerified`, `platformVerifyLicense`,
   `platformLoadComponent`, `platformIsComponentLoaded`, `apiGetToken`의 존재 여부를
   화면에서 확인한다. probe는 이름을 읽을 뿐 **어느 함수도 호출하지 않는다.**
3. 화면 사진을 owner-private HIL session에 원본으로 보관하고 digest를 기록한다.
   RC/기체 SN, token, App Key, license 값은 기록하지 않는다.

**PASS 증거**: `window.djiBridge`와 위 allowlist 함수 이름 존재 여부가 표시된 원본
화면 및 digest. 이것은 접속점 PASS일 뿐 license 인증·module load·wayline/file transfer
capability PASS가 아니다. 그 단계는 별도 승인 세션에서 독립적으로 검증한다.

**이 단계가 절대 하지 않는 것**: license 함수 호출, token/SN 조회, DJI component load.
라이선스 인증
성공만으로 "Wayline Management 가 된다"고 결론 내지 않는다(부트스트랩 인증과
실제 임무 배포 기능은 별개 사실이다. 이번 단계에서는 DJI 함수 자체를 호출하지 않는다.)

### 10단계 — 온보드 임무 실행 API 기종 지원 판별 (`10_waypoint_support_probe/`, 신설 2026-08-15)

> 근거: ADR-KSI-020 §3.1. **읽기 1회짜리 확인이지만, 절차를 틀리면 실제로 이륙한다.**

**먼저 물리적으로 막는다: 프로펠러를 제거한 상태에서만 수행한다.**

1. **DJI 공식 샘플 트리에서만 한다.** KSI 소스(`edge/psdk-app/src` 등)에는
   `DjiWaypointV3_*` 를 넣지 않는다 — 안전 게이트가 막고, 막는 것이 의도다.
2. **`DjiWaypointV3_Init()` 반환값만 본다.** SUCCESS 면 M4D 지원, 
   `DJI_ERROR_SYSTEM_MODULE_CODE_NONSUPPORT` 면 미지원이다. **이 값 하나가
   G3 설계 방향을 가른다.**
3. **`DjiTest_WaypointV3RunSample()` 을 그대로 호출하지 않는다.** 그 함수는 Init
   다음에 KMZ 업로드와 `DjiWaypointV3_Action(START)` 까지 이어지고, START 는
   시동·이륙을 실제로 건다(샘플이 비행상태를 `IN_AIR` 까지 기다리는 것이 그 증거).
4. U1이 SUCCESS 일 때만, 같은 조건(프로펠러 제거)에서 **우리가 발급한 KMZ**로
   `DjiWaypointV3_UploadKmzFile()` 반환값까지 확인한다. **`Action` 은 호출하지 않는다.**
5. 확대된 안전 게이트를 실제 빌드 산출물 대상으로 재실행한다
   (`tools/edge/verify_flight_boundary_on_built_target.sh`). strict 층 보고 심볼이
   늘어도 벤더 정의면 실패가 아니다(ADR-KSI-020 D3 체크포인트).

**PASS 증거**: Init 반환코드 raw, (해당 시) Upload 반환코드 raw, 게이트 재실행 출력.

**이 단계가 절대 하지 않는 것**: `DjiWaypointV3_Action` 호출, 프로펠러 장착 상태 실행.

## 3. 세션 종료 후

1. `session_manifest.json`의 `ended_at_utc`·`steps_completed`를 채운다.
2. 각 단계 PASS/BLOCKED 결과를 `docs/hil/SPIKE_EVIDENCE_TEMPLATE.md` 형식으로 옮겨
   `SpikeEvidence` 레코드(11필드)를 실제로 구성한다.
3. PASS한 capability는 `CapabilityRegistry.transition(..., VERIFIED, spike_evidence=...)`로
   승격한다(`docs/dji/SPIKE_PROCEDURE.md` §3 코드 예시).
4. BLOCKED로 남은 항목은 사유와 함께 `.ksi/goals.json`의 관련 목표/리스크에 반영한다.
5. `hil_raw_logs/<session_id>/` 전체를 durable 저장소로 옮기고, 옮긴 URI로
   `raw_log_ref`를 갱신한다(로컬 전용 경로만 남기지 않는다 — §RAW_LOG_CONVENTIONS §1).

# ADR-KSI-009 — Manifold 3 빌드·배포 정책: 온보드 네이티브 정본, PSDK 핀-비vendoring, 2속 배포

- 상태: ACCEPTED (2026-08-03, 실기 HIL 세션 중 확정)
- 관련: `docs/edge/MANIFOLD3_TOOLCHAIN.md`(실측값·정책 상세), `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`
  (실행 절차), `docs/dji/SPIKE_PROCEDURE.md`(Track A 절차 SSOT)

## 맥락

Manifold 3 실기(Ubuntu 20.04.6, gcc 9.4.0, cmake 3.16.3, glibc 2.31, Python 3.8.10)에
SSH 접속을 확보하면서, 저장소가 계획 단계에서 가정하지 못했던 구체적 충돌 5가지가
드러났다: cmake 하한(3.22 요구 vs 실기 3.16.3), glibc 버전(개발 PC 24.04=2.39 vs
실기 20.04=2.31), Python 버전(프로젝트 3.12 vs 실기 3.8), sudo 불가(rootless),
그리고 PSDK 재배포 라이선스 조건(미확인이었음). 이 문서는 그 각각에 대해 어떤
정책을 택했고 무엇을 기각했는지 기록한다 — 수개월 뒤 같은 논쟁이 반복되는 것을
막는 게 이 ADR의 존재 이유다.

## 결정

### D1 — cmake 하한 정정: `3.22` → `3.16...3.28`

`edge/manifold-runtime/CMakeLists.txt`가 실제로 쓰는 최신 기능은
`add_link_options`(cmake 3.13)이고, 3.17 이상 기능은 코드 안에 없었다. 3.22 요구는
근거 없는 상향이었다. 범위 표기(`3.16...3.28`, cmake 3.12+ 지원)로 정정해 실기
3.16.3과 호스트/CI 3.28을 동시에 만족시킨다 — 이건 "실기에 맞춘 타협"이 아니라
"잘못 적힌 하한의 정정"이다.

**기각한 대안**: 실기에 `pip install --user cmake>=3.22`로 새 cmake를 rootless
설치. 가능은 하지만 필수가 아니게 만든다 — "새 장비를 받으면 부트스트랩부터"라는
전제 자체가 세션 당일 리드타임을 깎아먹는다.

### D2 — 실기 산출물은 온보드 네이티브 빌드(또는 그 재현 컨테이너)만 인정

개발 PC(Ubuntu 24.04, glibc 2.39)에서 빌드한 바이너리는 실기(Ubuntu 20.04.6,
glibc 2.31)에서 **실행되지 않는다** — glibc는 하위 호환이 없다. 크로스컴파일
sysroot를 구축하는 대신, 개발 PC·CI 러너가 이미 aarch64라는 사실을 활용해
**네이티브 빌드를 정본으로 삼는다**:

| 환경 | 역할 |
|---|---|
| `edge/docker/manifold3-build.Dockerfile`(arm64 Ubuntu 20.04) | **정본** — 모든 배포 산출물은 여기서 나온다. 실기 userland를 apt로 그대로 재현(QEMU로 개발 PC에서, 또는 CI에서 `docker/setup-qemu-action`으로) |
| 호스트 직접(24.04, gcc 13) | 계약 테스트·ASan/UBSan — 빠른 문법·UB 피드백(기존 `edge-control-plane` CI job 유지) |
| 실기 온보드 | 탈출구 + 최종 진실 — 컨테이너에서만 되고 실기에서 안 될 때 그 자리에서 이등분 |

`cmake/toolchain-manifold3.cmake`는 크로스컴파일 툴체인 파일이 **아니라 정책
파일**이다 — `KSI_MANIFOLD_SYSROOT`가 비어 있으면 `CMAKE_SYSTEM_NAME`을 설정하지
않는다. 설정하면 `CMAKE_CROSSCOMPILING=TRUE`가 되어 컨테이너에서 ctest 실행이
막힌다(이 설계의 최대 이득을 잃는다). 담는 것은 컴파일러 신원 단언(gcc major
드리프트 게이트) · 정적 링크 강제(`BUILD_SHARED_LIBS=OFF`, `-static-libstdc++
-static-libgcc`) · RPATH 정책(`$ORIGIN` 기반, 절대경로 금지)뿐이다.

**아키텍처 튜닝(`-march=armv8.2-a` 등)은 기본값을 건드리지 않는다** — 측정 없는
최적화 플래그는 이 저장소의 증거 규율(실측 없이 "지원"이라 쓰지 않는다)에
어긋난다. 실측 벤치마크 확보 후에만 채운다.

### D3 — HIL 시간동기 수집은 C, 판정은 Python

`tools/hil/capture_frame_telemetry_timing.py`(공식 Acceptance Profile·증거
무결성 게이트가 전부 여기 있음)는 `StrEnum`·`datetime.UTC`·
`dataclass(slots=True)`를 쓴다(Python 3.10/3.11+ 전용). 실기는 Python 3.8.10 —
이 모듈은 **실기에서 import조차 되지 않는다**(2026-08-03 실측).

백포트해서 3.8 호환으로 낮추는 대신, PSDK 콜백 수신은 `edge/psdk-tap`(C, 실기
네이티브 컴파일)이 맡아 raw NDJSON을 쓰고, 공식 판정(`summarize --mode
official`)은 개발 PC의 Python 3.12에서 그대로 수행한다. NDJSON이 두 언어의
계약이 된다 — `contracts/conformance/`가 C++/Python 양쪽에 같은 벡터를 검증하게
하는 기존 패턴과 동형이다.

**남는 실기 Python은 두 티어로 분리**: `tools/hil/device/`(콜드스타트 — 세션
필수 최소치, python3.8 표준 라이브러리만, CI `edge-manifold-target` job이 진짜
python3.8로 컴파일 가능성을 검사) vs 실기 온보드에 선택적으로 두는 분석 도구
(부트스트랩 티어, uv standalone CPython 등 — 없어도 세션이 진행돼야 한다).

### D4 — 정적 링크(DPK 제약)는 실제 배포 대상에만 강제

`KSI_TARGET_MANIFOLD3=ON` 없이 빌드하면 `libstdc++.so.6`이 동적으로 남는다 —
이건 결함이 아니라 `control_plane_tests`/`conformance_tests`가 애초에 DPK 배포
대상이 아니기 때문이다(Stage C-3 계약 골격, PSDK 미연동). `tools/edge/
check_target_abi.py`가 이 정책을 코드로 강제한다: NEEDED 허용목록(glibc 계열
Tier 1 + 동적 링커 자체, NVIDIA 런타임은 Tier 2로 `--allow-nvidia-libs` 명시
없이는 거부) · glibc 심볼 상한(실측 2.31) · RPATH 절대경로 금지. CI
(`edge-manifold-target` job)는 `KSI_TARGET_MANIFOLD3=ON`으로 이 게이트 통과를
실증하지만, 진짜 소비자는 향후 `edge/psdk-app`이다.

### D5 — PSDK는 핀하되 vendoring(서브모듈)하지 않는다

`edge/third_party/PSDK_LOCK.yaml`(커밋)에 `pinned_commit`·라이선스 판단·대표
파일 sha256을 기록하고, 실물은 `tools/edge/fetch_psdk.py`로 명시적으로 받는다
(`edge/third_party/psdk/`, gitignored). `models/` + `tools/fetch_model.py`와
동형 패턴 — 계보는 git에, 실물은 명시적 fetch로.

**`references/` 서브모듈 아래 두지 않는다** — `REFERENCE_REPOS_LOCK.yaml:
build_references: false`와 `scripts/check_no_reference_imports.sh`가 "읽고
베끼되 링크하지 않는다"를 강제하는데, PSDK는 정반대로 "실제로 링크하는 빌드
입력"이다. 성격이 다른 것을 같은 메커니즘에 우겨넣지 않는다.

**라이선스 판단(2026-08-03 실기에서 원문 직접 확인)**: `LICENSE.txt`(934줄)가
파일 트리 형태로 MIT 대상을 나열 — `psdk_lib/**`(사전 컴파일 `libpayloadsdk.a`
포함), `samples/**`, `CMakeLists.txt` 등. 예외는 `STM32_USB_Host_Library`
(STMicroelectronics 별도 라이선스, RTOS/STM32 전용 — 우리 Linux/manifold3
경로와 무관). `EULA.txt` §3.5(Open-Source Components)가 "오픈소스 구성요소와
EULA가 충돌하면 오픈소스 라이선스가 우선한다"고 명시하므로, MIT로 나열된 부분에는
EULA §3.2(c)의 재배포 금지가 적용되지 않는다. 이 근거로 vendoring을 허용한다.
재검토가 필요해지면(DJI가 LICENSE.txt를 바꾸는 등) `pinned_commit` 갱신 시 이
판단을 다시 실측한다 — 자동 승계하지 않는다.

### D6 — 배포 루프는 2속: raw(빠른 반복) / dpk(릴리스 게이트)

`scripts/manifold/manifoldctl` 단일 진입점.

| 모드 | 경로 | 소요 | 답하는 질문 |
|---|---|---|---|
| `raw`(기본) | 컨테이너 빌드 → rsync → `current` 심볼릭 링크 원자적 교체 → 직접 실행 | 수 초~수십 초 | "내 코드가 맞나" |
| `dpk`(향후, `edge/psdk-app` 통합 후) | `build_dpk.sh` → `dji_app_ctl install/start` | 분 단위 | "DPK로서 동작하나" |

`manifoldctl deploy`는 워킹트리가 dirty하면 `--allow-dirty` 없이 거부한다 —
`SpikeEvidence.build_commit`이 실제 시험 코드와 다른 SHA를 가리키는 사고를
원천 차단한다(이 저장소가 가장 싫어하는 실패 클래스).

**비밀 관리**: `dji_sdk_app_info.h`(App ID/Key/License)는 커밋하지 않는다 —
`.gitignore`(`**/dji_sdk_app_info.h`, `/.secrets/`, `/dist/`)와
`scripts/check_repo_hygiene.sh`(생성 헤더·`.secrets/`·리터럴 키·`*.dpk` 추적
금지 4규칙)로 이중 방어한다. 이 4규칙은 **수동 변이 확인만 수행했다**(대화형으로
위반 케이스를 만들어 스크립트가 실제로 잡는지 손으로 확인 — 자동 회귀 테스트는
아직 저장소에 없다, 별도 과제). CI는 실키 없이 더미 자격증명으로 컴파일·링크·ABI
검증만 한다.

## 기각한 대안

- **완전 `-static` 링크**: glibc NSS·dlopen이 깨지고 PSDK 내부 동작을 모른다.
  정책은 "glibc 계열만 동적, 서드파티는 정적"이다.
- **self-hosted GitHub runner를 Manifold에 상주**: 4코어 비행 컴퓨터에 CI
  데몬을 얹는 것은 운영·안전상 나쁜 신호이고 외부 인바운드 의존을 만든다.
- **PSDK를 git 서브모듈로 핀**: MIT 확인 전에는 라이선스 노출 리스크가
  불명확했고, 확인 후에도 `fetch_psdk.py`가 같은 강제력(핀 이탈 감지)을 더
  가볍게 제공한다 — 저장소 크기·클론 UX 이점으로 fetch 방식을 유지한다.
- **cmake 3.22 유지 + 실기에 새 cmake 설치**: 장비 교체·리플래시마다 부트스트랩이
  선행조건이 되고, 그 실패가 세션 당일에 터진다.

## 결과

- `docs/edge/MANIFOLD3_TOOLCHAIN.md` §1·§2·§4가 계획값에서 실측값으로 갱신됨.
- `edge/manifold-runtime/CMakeLists.txt`의 cmake 하한이 코드로 정정됨(D1).
- `cmake/toolchain-manifold3.cmake`·`tools/edge/check_target_abi.py`·
  `edge/docker/manifold3-build.Dockerfile`·`scripts/manifold/manifoldctl`·
  `edge/third_party/PSDK_LOCK.yaml`·`tools/edge/fetch_psdk.py`가 신설됨.
- CI 설정에 `edge-manifold-target` job이 추가되어, 실기 없이도 gcc9.4/cmake3.16.3/
  glibc2.31 환경 드리프트를 매 커밋 기계적으로 잡도록 **작성**했다 — 다만 이 job은
  아직 한 번도 실행된 적이 없다(첫 CI 실행 미확인). 로컬에서는 동등한 컨테이너
  빌드를 1회 실행해 통과를 확인했다(§D2). 이 job은 "타깃 빌드·링크·ABI가
  유효하다"만 주장하며, 텔레메트리·카메라·짐벌·DPK 설치 실동작 검증은 여전히
  `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`의 HIL 세션 증거로만 주장한다.
- `edge/psdk-tap`(C, 시간동기 tap)과 `edge/psdk-app`(향후, DPK 배포 대상)의
  경계가 명확해짐 — `edge/manifold-runtime`은 "의존성 없는 순수 C++17 계약
  골격" 계약을 계속 유지한다.

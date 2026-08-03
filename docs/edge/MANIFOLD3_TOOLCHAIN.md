# Manifold 3 Toolchain Manifest

- 상태: Stage C-3 (골격 단계) — **호스트·타깃(온보드 네이티브) 빌드 검증됨, 컨테이너 빌드는 로컬 1회 확인(CI 미실행)**
- 대상: DJI Manifold 3 온보드 컴퓨터 (MASTER_PRD §9.1)
- 2026-08-03 HIL 세션(`SESS-20260803T125616Z-PENDING-SN`, device_id `A25WN8B0011082`)에서
  실기 SSH 접속 확보 후 §1·§2·§4를 실측값으로 갱신. 크로스빌드 대신 **온보드 네이티브
  빌드**(D2, ADR-KSI-009)를 정책으로 채택했다 — 이유는 §6 참조.

## 1. 현재 검증된 것 / 아닌 것

정직하게 구분한다 — 미검증 항목을 "지원"으로 표시하지 않는다(INV-041과 같은 원칙).

| 항목 | 상태 | 근거 |
|---|---|---|
| 호스트(x86-64/aarch64 Linux) C++17 빌드 | **검증됨** | `cmake 3.28 + g++ 13.3`, `-Wall -Wextra -Wpedantic -Werror` 통과, ctest green |
| control plane 계약 테스트 | **검증됨** | 33개 단언 통과 + 변이 테스트로 하네스 유효성 확인 |
| **Manifold 3 타깃 온보드 네이티브 빌드** | **검증됨** | 실기(gcc 9.4.0/cmake 3.16.3) `100% tests passed, 0 tests failed out of 2` — `hil_raw_logs/SESS-20260803T125616Z-PENDING-SN/02_sample_build/` |
| **arm64 컨테이너 빌드(CI 정본)** | **작성 완료 — 로컬 1회 실행 확인 / CI 미실행(PENDING_CI_RUN)** | `edge/docker/manifold3-build.Dockerfile`(Ubuntu 20.04) 자체는 존재하고, 2026-08-03 세션에서 `docker run --platform linux/arm64 ksi-manifold3-build:latest`로 로컬 1회 실행해 gcc 9.4.0/cmake 3.16.3/glibc 2.31 재현과 `100% tests passed, 0 tests failed out of 2`를 확인했다. 다만 CI job(`edge-manifold-target`)은 아직 한 번도 실행된 적 없다 — "CI 정본"은 설계 의도이지 실행 증거가 아니다 |
| **DPK 정적 링크 ABI 게이트** | **작성 완료 — 로컬 1회 실행 확인 / CI 미실행** | `cmake/toolchain-manifold3.cmake`(`KSI_TARGET_MANIFOLD3=ON`) 적용 시 `tools/edge/check_target_abi.py` 통과를 위 로컬 컨테이너 실행 1회에서 실증했다. CI에서 이 게이트가 매 커밋 도는지는 미확인 |
| Manifold 3 타깃 크로스빌드(x86→arm64) | **비채택(정책)** | 개발 PC·CI 컨테이너가 이미 aarch64라 불필요 — §6 D2 참조 |
| PSDK 링크·카메라/짐벌 API | **미검증(SPIKE_REQUIRED)** | Capability Registry `SPIKE-DJI-01`~`09` 참조. PSDK 저장소 clone·공식 샘플 빌드는 진행 중(2단계) |
| CUDA/TensorRT 추론 파이프라인 | **미착수** | Phase 1 이후 범위 |

## 2. 타깃 하드웨어 — 공식 사양 vs 실측

공식 사양(Master PRD §1.2 B, [R1][R2])과 2026-08-03 HIL 세션 실측을 나란히 둔다.

| 항목 | 공식 사양 | 실측(HIL 세션) |
|---|---|---|
| RAM | 16GB LPDDR5 | 14Gi 가용(`free -h`), 부팅 직후 buff/cache 포함 13Gi available |
| 스토리지 | 256GB SSD | `/` 27G(66% 사용) + `/open_app` 99G(94G 여유, 개발 스테이징 전용 파티션) |
| 컴퓨팅 | 최대 100 TOPS(특정 INT8 희소 연산 조건의 **이론값**) | 미측정 — 실제 처리량은 모델 벤치마크로 별도 확정 |
| CPU | (미명시) | 4코어 ARMv8, 전력모드 **MAXN** |
| 아키텍처 | aarch64 (NVIDIA Jetson 계열) | **NVIDIA Orin NX**, `aarch64`, device_id `A25WN8B0011082`, serial `1422525001127` |
| OS | (미명시) | **Ubuntu 20.04.6 LTS**(Focal), 커널 `5.10.192-tegra` |
| L4T/JetPack | (미명시) | **L4T R35.5.0 = JetPack 5.1.3** |

최대 TOPS 이론값 단서는 PRD 원문 그대로 유지한다 — 실측 전까지 "지원"으로 격상하지 않는다.

## 3. 빌드

### 3.1 호스트 빌드 (개발 PC, 빠른 반복용)

```bash
cd edge/manifold-runtime
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j
ctest --test-dir build --output-on-failure
```

의존성: **없음**(순수 C++17 표준 라이브러리). 외부 테스트 프레임워크를 쓰지 않는 이유는
네트워크 fetch 없이 CI에서 그대로 돌아야 하기 때문이다.

### 3.2 타깃 정책 적용 빌드 (DPK 배포 대상에만 — 정적 링크 강제)

```bash
cmake -S edge/manifold-runtime -B build-manifold3 \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON
cmake --build build-manifold3 -j
uv run python tools/edge/check_target_abi.py build-manifold3/<binary>   # 정적 링크·glibc 상한·RPATH 검증
```

`tools/edge/check_target_abi.py`에는 shebang이 없다 — 직접 실행 파일이 아니라
`uv run python`으로 호출하는 저장소 관례를 따른다.

`KSI_TARGET_MANIFOLD3=ON` 없이 빌드한 산출물은 `libstdc++.so.6`이 동적으로 남아
ABI 게이트가 항상 실패한다(2026-08-03 실측 — DPK "서드파티는 정적 링크만" 제약의
직접 결과). control_plane_tests/conformance_tests는 테스트 바이너리이지 DPK
배포 대상이 아니므로, 이 정책은 **실제 DPK 앱(`edge/psdk-app`, 향후)에만** 강제한다.

**주의**: 위 `build-manifold3`는 저장소 루트 산출물이다. 루트 `.gitignore`의
`edge/manifold-runtime/build*/` 패턴은 `edge/manifold-runtime/` 하위만 잡으므로 이
경로는 ignore 대상이 아니다 — `git status`로 추적되지 않는지 확인하고, 실수로
커밋하지 않도록 주의한다(CI는 `edge/manifold-runtime/build-manifold3-ci`처럼
ignore되는 경로를 쓴다 — `.github/workflows/ci.yml` 참조).

### 3.3 컨테이너 정본 빌드 (CI 및 로컬 반복 — 실기 없이 회귀 검출)

```bash
docker buildx build --platform linux/arm64 \
  -f edge/docker/manifold3-build.Dockerfile -t ksi-manifold3-build:latest --load edge/docker/
docker run --rm --platform linux/arm64 \
  -v "$(pwd)/edge/manifold-runtime:/workspace/src:ro" -v "$(pwd)/build-manifold3:/workspace/build" \
  -w /workspace ksi-manifold3-build:latest bash -c \
  'cmake -S src -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo && cmake --build build -j && cd build && ctest --output-on-failure'
```

개발 PC가 이미 aarch64이므로 로컬에서는 QEMU 불필요. CI(x86-64 러너)는
`docker/setup-qemu-action`으로 등록 후 `--platform=linux/arm64`를 명시한다.

### 3.4 배포 루프 (반복 개발)

`scripts/manifold/manifoldctl {doctor|build|deploy|run|status|cycle}` — §7 참조.

## 4. 타깃 툴체인 — 실측값(2026-08-03 HIL 세션)

이전 버전은 계획값이었다. 아래는 실기에서 직접 확인한 값이다.

| 구성 | 실측값 | 확정 근거 |
|---|---|---|
| 타깃 트리플 | `aarch64-linux-gnu` | 실기 `uname -m` → `aarch64` |
| C++ 표준 | C++17 (PRD §9.1 "C++17 이상") | 유지, 실기에서 `-std=c++17` 컴파일 확인 |
| 컴파일러 | **gcc/g++ 9.4.0**(Ubuntu 9.4.0-1ubuntu1~20.04.2) | 실기 `g++ --version` — `aarch64-linux-gnu-gcc`도 동일 버전으로 이미 존재(별도 크로스 설치 불필요) |
| cmake | **3.16.3** | 실기 `cmake --version`. 저장소 `cmake_minimum_required`가 3.22였던 것을 `3.16...3.28`로 정정(D1) |
| glibc | **2.31**(Ubuntu 20.04.6) | 실기 `ldd --version`. ABI 게이트 상한(`DEFAULT_MAX_GLIBC`)의 근거 |
| Python | **3.8.10** | 실기 `python3 --version` — `capture_frame_telemetry_timing.py`의 `StrEnum`/`datetime.UTC`(3.11+)가 실기에서 import 불가함을 실측 확인(D3) |
| CUDA | **11.4.19** | `/usr/local/cuda/version.json` |
| cuDNN | **8.6.0.166** | `dpkg -l \| grep libcudnn8` |
| TensorRT | **8.5.2.2** | `python3 -c "import tensorrt"` |
| PSDK | **3.16.0**(commit `9af08536df3671ed77aee02f1f2e4173b0e0f558`) | `edge/third_party/PSDK_LOCK.yaml` — MIT 라이선스 확인(§8) |
| CMake 툴체인 파일 | `cmake/toolchain-manifold3.cmake` | **작성 완료** — 정책 파일(크로스 아님), §3.2에서 실증 |
| sudo | **불가**(rootless) | DJI 제공 `install.py`로 root 없이 apt/deb 설치 (`/open_app/install`) |

## 5. 금지 사항 (Stage C 범위 제약)

승인된 Stage C 범위는 계약·빌드·상태전이 골격까지다. 다음은 실기/HIL 증거 전까지 금지:

- 실제 PSDK 비행명령 활성화
- Capability Registry에서 DJI 기능을 `VERIFIED`로 승격
- Python에서 DJI Flight Command 직접 호출
- 실기 증거 없이 M4D 카메라·짐벌·비행 API가 작동한다고 선언

현재 `ksi_control_plane` 라이브러리에는 기체를 움직이는 코드 경로가 **존재하지 않는다** —
명령 유효성 판정과 안전 상태 계산만 한다.

## 6. 빌드 정책 (ADR-KSI-009 요약)

**D1 — cmake 하한 정정.** `edge/manifold-runtime/CMakeLists.txt`가 실제로 쓰는 최신
기능은 `add_link_options`(3.13)이고 3.17+ 기능은 없었다. 3.22 요구는 근거 없는
상향이었다 — `3.16...3.28`(범위 표기)로 정정해 호스트/CI(3.28)와 실기(3.16.3)를
동시에 만족시킨다.

**D2 — 실기 산출물은 온보드 네이티브 빌드만 인정.** 개발 PC는 Ubuntu 24.04(glibc
2.39), 실기는 Ubuntu 20.04.6(glibc 2.31) — glibc는 하위 호환이 없으므로 **PC에서
빌드한 바이너리는 실기에서 실행되지 않는다.** 크로스컴파일(x86→arm64) sysroot를
구축하는 대신, 개발 PC·CI 컨테이너가 이미 aarch64라는 사실을 활용해 **네이티브
빌드를 정본으로 삼는다.** `cmake/toolchain-manifold3.cmake`는 `KSI_MANIFOLD_SYSROOT`가
비어 있으면 `CMAKE_SYSTEM_NAME`을 설정하지 않는다 — 이게 ctest가 컨테이너에서
그대로 도는 이유다(크로스컴파일 모드였다면 `CMAKE_CROSSCOMPILING=TRUE`가 되어
테스트 실행이 막혔을 것).

**D3 — 수집은 C, 판정은 Python.** `tools/hil/capture_frame_telemetry_timing.py`(공식
Acceptance Profile·증거 무결성 게이트가 전부 여기 있음)를 실기 Python 3.8로
백포트하면 엄격성이 내려간다(`StrEnum`·`datetime.UTC`·`dataclass(slots=True)`가
전부 3.10/3.11+ 전용). 대신 PSDK 콜백은 **C tap**(`edge/psdk-tap`)이 받아 NDJSON을
쓰고, 판정은 개발 PC 3.12에서 한다는 설계까지만 이 세션에서 확정했다 —
`edge/psdk-tap` 자체는 **아직 코드가 없다**(설계만 확정, 다음 세션 선행 작업).
`tools/hil/capture_frame_telemetry_timing.py`의 `collect` 서브커맨드도 현재는
`--session-id/--aircraft-sn/--out/--num-samples` 4개 인자만 받고 tap 로그를
읽는 경로(`--source`/`--tap-log`/`--timestamp-basis`)는 아직 구현돼 있지 않다.

**D4 — 정적 링크는 DPK 배포 대상에만 강제.** `KSI_TARGET_MANIFOLD3=ON`(정적 링크
정책)을 켜지 않은 빌드는 `libstdc++.so.6`이 동적으로 남는다 — 이건 결함이 아니라
control_plane_tests/conformance_tests가 애초에 DPK 배포 대상이 아니기 때문이다.
CI(`edge-manifold-target` job)는 검증 목적으로 이 옵션을 켜서 ABI 게이트 통과를
실증하지만, 실제 DPK 앱(`edge/psdk-app`, 향후)만 이 정책의 진짜 소비자다.

## 7. 배포 루프

`scripts/manifold/manifoldctl` — 2속 배포:

| 모드 | 명령 | 소요 | 용도 |
|---|---|---|---|
| raw(기본) | `manifoldctl cycle` | 수 초~수십 초 | 빠른 반복 — rsync + 심볼릭 링크 원자적 교체 + 직접 실행 |
| dpk | (`edge/psdk-app` 통합 후 구현) | 분 단위 | 릴리스 게이트 — `dji_app_ctl` 위임 |

`manifoldctl deploy`는 워킹트리가 dirty하면 `--allow-dirty` 없이 거부한다 —
`SpikeEvidence.build_commit`이 실제 시험 코드와 다른 SHA를 가리키는 것을 원천 차단한다.
설정은 `scripts/manifold/manifold.env`(gitignored — 비밀은 없지만 머신별 설정이라
커밋하지 않는다. 2026-08-04 감사에서 이 파일이 무시 대상이 아니어서
`mf_git_is_dirty`가 항상 true가 되던 결함을 발견·정정. IP는 여기도 아니라
`~/.ssh/config`의 Host 별칭에 둔다).

## 8. PSDK 라이선스 확인 (2026-08-03 실기 세션)

`edge/third_party/PSDK_LOCK.yaml`이 계보 SSOT다. 실기에서 `LICENSE.txt`/`EULA.txt`
원문을 직접 확인한 결과:

- `LICENSE.txt`(934줄)가 파일 트리 형태로 MIT 대상 파일을 나열 — `psdk_lib/**`
  (헤더 + 사전 컴파일 `libpayloadsdk.a` 포함), `samples/**`, `CMakeLists.txt` 등.
  예외는 `STM32_USB_Host_Library`(STMicroelectronics 별도 라이선스, RTOS/STM32
  플랫폼 전용 — 우리가 쓰는 Linux/manifold3 경로와 무관).
- `EULA.txt` §3.5(Open-Source Components)가 "이 SDK의 오픈소스 구성요소와 EULA가
  충돌하면 오픈소스 라이선스가 우선한다"고 명시 — 따라서 MIT로 나열된 부분에는
  EULA §3.2(c)의 재배포 금지가 적용되지 않는다.

이 근거로 `libpayloadsdk.a`(바이너리 블롭 포함)의 vendoring/재배포가 허용된다고
판단한다. `tools/edge/fetch_psdk.py`가 핀 커밋(`pinned_commit`)과 대표 파일
sha256을 대조해 핀 이탈을 감지한다 — 실물은 `edge/third_party/psdk/`(gitignored)에
받고, `references/` 서브모듈 정책(`build_references: false`)과는 무관하다(PSDK는
"실제로 링크하는 빌드 입력"이라 성격이 다르다).

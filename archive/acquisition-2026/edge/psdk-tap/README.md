# edge/psdk-tap — PSDK 콜백 수집기 (C)

Manifold 3 실기에서 PSDK 콜백(Liveview 프레임 / FC Telemetry)을 받아 **raw NDJSON**
한 줄씩 쓰는 수집기다. 판정은 여기서 하지 않는다.

**분업(ADR-KSI-009 D3, 재론 금지)**

```
수집(C, 실기 네이티브)            판정(Python 3.12, 개발 PC)
edge/psdk-tap  ──raw NDJSON──▶  tools/hil/capture_frame_telemetry_timing.py
                                  collect --source tap-log → summarize --mode official
```

왜 나뉘는가: 실기 Python은 3.8.10인데 판정 도구는 `StrEnum`·`datetime.UTC`(3.11+)를
쓴다 — 2026-08-03 세션에서 실기 import 실패를 실측했다. 3.8로 백포트하면 공식
Acceptance Profile과 증거 무결성 게이트의 엄격성이 내려간다. 그래서 실기에는 C만 둔다.

## 빌드

`psdk_tap` 실행파일은 **두 가지 빌드 입력이 모두 있어야** 만들어진다. 없으면 configure
단계에서 명확히 실패한다 — 조용히 스텁으로 넘어가지 않는다.

1. **PSDK 실물** — `edge/third_party/psdk`. 커밋하지 않는다(계보 SSOT는
   `edge/third_party/PSDK_LOCK.yaml`). 받기: `uv run python tools/edge/fetch_psdk.py`
2. **App 자격증명** — `dji_sdk_app_info.h`. developer.dji.com에서 발급받는다.

   ```bash
   cp edge/psdk-tap/config/dji_sdk_app_info.h.example /secure/dji_sdk_app_info.h
   # USER_APP_NAME / USER_APP_ID / USER_APP_KEY / USER_APP_LICENSE 를 실제 값으로 채운다
   ```

   파일명은 반드시 `dji_sdk_app_info.h`여야 한다. worktree 안에 둘 필요 없이
   `-DKSI_PSDK_TAP_APP_INFO_HEADER=/secure/dji_sdk_app_info.h`로 전달할 수 있다.
   그 파일명은 저장소 루트 `.gitignore`의 `**/dji_sdk_app_info.h` 규칙으로 경로와
   무관하게 항상 무시된다.

```bash
cmake -S edge/psdk-tap -B edge/psdk-tap/build-host \
  -DKSI_PSDK_TAP_APP_INFO_HEADER=/secure/dji_sdk_app_info.h
cmake --build edge/psdk-tap/build-host -j
```

Manifold 3 타깃 빌드는 `cmake/toolchain-manifold3.cmake`를 얹는다(`scripts/manifold/
manifoldctl` 참조) — 호스트 gcc major가 실기와 다르면 툴체인 드리프트 게이트가 막는다.

### HIL DPK 패키지

기체 링크가 필요한 callback 수집기는 SSH에서 직접 실행하지 않는다. 실기 관측은
공식 DPK를 `dji_app_ctl` 경로로 설치·기동한 뒤에만 수행한다. `user_app_id`는 반드시
DJI가 발급한 값이며, test ID로 만든 패키지는 형식 검증 외 용도로 사용할 수 없다.

```bash
cmake -S edge/psdk-tap -B edge/psdk-tap/build-manifold3 \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_TAP_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
  -DKSI_PSDK_TAP_BUILD_DPK=ON \
  -DKSI_PSDK_TAP_DPK_USER_APP_ID=<DJI_issued_id>
cmake --build edge/psdk-tap/build-manifold3 --target ksi_psdk_tap_dpk -j

scripts/manifold/manifoldctl install \
  edge/psdk-tap/build-manifold3/dpk/out/ksi-psdk-tap_v00.01.00.02.dpk
scripts/manifold/manifoldctl restart ksi-psdk-tap
scripts/manifold/manifoldctl status ksi-psdk-tap
```

DPK service는 인자를 받지 않으므로 기본 60초 수집을 수행하고
`/tmp/ksi-psdk-tap.ndjson`에 raw 관측을 쓴다. 이 경로가 DPK 실행 사용자에게 실제로
쓰이고 SSH 사용자에게 읽히는지는 HIL 증거로 확인해야 한다. 확인 전에는 임의 경로를
추정하거나 sensor timestamp가 있다고 선언하지 않는다.

### Perception raw-timestamp probe (`SPIKE-DJI-07`)

기본 source는 기존의 `liveview` H264다. 별도 PSDK Perception grayscale stream의
`T_DjiPerceptionImageInfo.timeStamp`를 **조사만** 하려면, DPK가 argv 없이 실행되는
제약 때문에 패키지 빌드 때 source를 명시한다.

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

이 mode는 `DjiPerception_SubscribePerceptionImage` callback의 **고정 크기 metadata만**
기록한다. pixel buffer는 읽거나 복사하지 않는다. raw NDJSON v2에는 다음이 추가된다.

- meta: `frame_source="perception_grayscale"`,
  `frame_timestamp_provenance="perception_image_info_timestamp_raw_unverified"`,
  `timestamp_contract.sensor_us_domain="unverified"`.
- sample frame: `sensor_timestamp_raw_u64` (lossless decimal **string**) 및 direction,
  sequence, resolution, bpp 같은 perception metadata.

이 값은 `sensor_us`가 아니다. PSDK header만으로 raw timestamp의 unit, epoch, wrap,
HARD_SYNC와의 공통 clock domain을 알 수 없고, grayscale perception camera는 payload RGB
camera와도 별개다. 따라서 probe가 callback을 받아도 `capabilities.frame_sensor_ts`는
계속 `false`이며 `collect --timestamp-basis sensor`는 fail-closed 된다. Python 변환기가
sensor basis를 허용하려면 두 endpoint가 실제로 host monotonic microsecond domain으로
정규화됐다는 `timestamp_contract.sensor_us_domain="host_monotonic_us"`와 HIL 근거가
별도로 필요하다. raw probe/`recv` 수치만으로 sensor alignment PASS 또는 RGB calibration을
주장하면 안 된다.

## 테스트

`tests/pairing_tests.c`는 frame↔telemetry 페어링의 **순수 로직만** 검증한다(PSDK 의존
없음). `KSI_PSDK_TAP_LOGIC_TESTS_ONLY=ON`은 이 테스트만 명시적으로 구성하는 CI 경로다.
이 모드에서는 `psdk_tap` 실행파일·PSDK callback·NDJSON 파일 I/O를 전혀 빌드하거나
검증하지 않는다. 기본값은 여전히 `OFF`이며, PSDK나 자격증명 없이 기본 configure가
통과하는 폴백은 허용하지 않는다.

```bash
# PSDK/자격증명 없이 가능한 순수 로직 gate
cmake -S edge/psdk-tap -B edge/psdk-tap/build-logic \
  -DKSI_PSDK_TAP_LOGIC_TESTS_ONLY=ON
cmake --build edge/psdk-tap/build-logic -j
(cd edge/psdk-tap/build-logic && ctest --output-on-failure)

# 실제 PSDK 수집기 빌드 뒤의 pairing test
(cd edge/psdk-tap/build-host && ctest --output-on-failure)
```

Manifold 3의 CTest 3.16.3은 `--test-dir`를 지원하지 않는다. 위처럼 build directory로
이동해 실행해야 `No tests were found`를 거짓 통과처럼 오독하지 않는다.

## 검증되지 않은 것 (2026-08-04 현재)

- **실기 실행 이력 없음.** 기체 M4D 물리 연결(blocker `AIRCRAFT_LINK_DOWN`) 이후에야
  가능하다. DPK 설치/재시작, `/tmp` output 경로, NDJSON 스키마, callback 수렴은 전부
  실기 초회 확인 대상이다.
- **CI 범위 제한.** `.github/workflows/ci.yml`의 `edge-psdk-tap` job은 위
  `LOGIC_TESTS_ONLY` pairing test와 기본 configure의 fail-closed 성질만 검증한다.
  PSDK callback·실기 NDJSON·프레임 페어링의 측정 유효성은 HIL 증거가 있어야 한다.
- **Sensor alignment 미해결.** 현재 Liveview callback은 camera sensor timestamp를
  제공하지 않는다. tap은 이를 `frame_sensor_ts=false`로 기록하므로 `--timestamp-basis
  sensor`는 fail-closed 된다. `recv` 결과는 수신시각 진단일 뿐 sensor-alignment PASS나
  `CONFIRMED` 승격 근거가 아니다. PSDK의 별도 `DjiPerceptionImageCallback`은 grayscale
  visual-perception frame의 `timeStamp`를 준다. 현재 `--frame-source perception`은 그
  값을 raw string으로만 보존하는 SPIKE 수집 mode이며 Liveview RGB와 같은 frame이라는
  계약은 없다. 그 raw clock unit/domain·HARD_SYNC와의 상관·camera calibration을 HIL로
  입증하기 전에는 이 tap의 capability를 true로 바꾸거나 RGB sensor evidence로 쓰지 않는다.
- USB bulk **host-mode**(`isUsbHost=true`) 경로는 libusb-1.0이 없으면 컴파일만 되는
  스텁(NONSUPPORT)으로 빌드된다. Manifold 3 실기 경로(FunctionFS gadget)는 무관하다.

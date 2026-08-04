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
2. **App 자격증명** — `config/dji_sdk_app_info.h`. developer.dji.com에서 발급받는다.

   ```bash
   cp config/dji_sdk_app_info.h.example config/dji_sdk_app_info.h
   # USER_APP_NAME / USER_APP_ID / USER_APP_KEY / USER_APP_LICENSE 를 실제 값으로 채운다
   ```

   이 파일명은 저장소 루트 `.gitignore`의 `**/dji_sdk_app_info.h` 규칙으로 경로와
   무관하게 항상 무시된다.

```bash
cmake -S edge/psdk-tap -B edge/psdk-tap/build-host
cmake --build edge/psdk-tap/build-host -j
```

Manifold 3 타깃 빌드는 `cmake/toolchain-manifold3.cmake`를 얹는다(`scripts/manifold/
manifoldctl` 참조) — 호스트 gcc major가 실기와 다르면 툴체인 드리프트 게이트가 막는다.

## 테스트

`tests/pairing_tests.c`는 frame↔telemetry 페어링의 **순수 로직만** 검증한다(PSDK 의존
없음). 다만 최상단 CMakeLists가 PSDK·자격증명을 먼저 요구하므로, 그 둘이 없는 환경
(=CI)에서는 이 테스트조차 configure되지 않는다.

```bash
ctest --test-dir edge/psdk-tap/build-host --output-on-failure
```

## 검증되지 않은 것 (2026-08-04 현재)

- **실기 실행 이력 없음.** 기체 M4D 물리 연결(blocker `AIRCRAFT_LINK_DOWN`) 이후에야
  가능하다. `--out` 경로 동작·NDJSON 스키마·`--num-samples` 수렴은 전부 실기 초회
  확인 대상이다.
- **CI 미배선.** 위 사유(PSDK·자격증명 부재로 configure 불가)로 이 트리는 현재
  자동 게이트 밖에 있다 — `pairing.c`의 순수 로직조차 회귀 검증되지 않는다.
- USB bulk **host-mode**(`isUsbHost=true`) 경로는 libusb-1.0이 없으면 컴파일만 되는
  스텁(NONSUPPORT)으로 빌드된다. Manifold 3 실기 경로(FunctionFS gadget)는 무관하다.

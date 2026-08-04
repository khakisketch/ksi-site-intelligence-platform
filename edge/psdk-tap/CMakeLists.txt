# edge/psdk-tap — Manifold3 실기 네이티브 수집기(HIL 7단계 선행 작업, ADR-KSI-009 D3).
#
# 분업(D3, 재론 금지): 수집(C, 이 트리) → raw NDJSON → 판정(Python 3.12,
# tools/hil/capture_frame_telemetry_timing.py). 이 CMakeLists 는 수집기(psdk_tap)와 그
# 순수 로직 단위테스트(psdk_tap_pairing_tests)만 정의한다.
#
# cmake 하한: edge/manifold-runtime/CMakeLists.txt 와 같은 범위 표기 관례
# (cmake_minimum_required(VERSION 3.16...3.28)) — 실기 cmake 3.16.3, CI 3.28.
cmake_minimum_required(VERSION 3.16...3.28)
project(ksi_psdk_tap LANGUAGES C VERSION 0.1.0)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
# GNU 확장이 필요하다 — pthread_setname_np/getrandom/sigaction 등은 순수 ISO C11 범위
# 밖이고, glibc 는 _GNU_SOURCE 없이 선언을 감춘다. DJI 자신의 manifold3 샘플도
# -std=gnu99 를 쓴다(edge/third_party/psdk/samples/.../manifold3/CMakeLists.txt:5).
set(CMAKE_C_EXTENSIONS ON)
add_compile_definitions(_GNU_SOURCE)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "빌드 타입" FORCE)
endif()

# 실기와 다른 gcc major 로 KSI_TARGET_MANIFOLD3=ON 빌드를 만드는 것을 차단한다
# (edge/manifold-runtime/CMakeLists.txt 와 동일한 관례 — cmake/toolchain-manifold3.cmake
# 가 -DCMAKE_TOOLCHAIN_FILE 로 로드됐을 때만 이 함수가 존재한다).
if(COMMAND ksi_check_manifold3_toolchain_drift)
  ksi_check_manifold3_toolchain_drift()
endif()

# --- 자격증명 게이트 ---------------------------------------------------------------
# "자격증명(dji_sdk_app_info.h)은 빌드 입력이지 소스가 아니다" — 없으면 조용히
# 스텁/더미로 넘어가지 않고 여기서 명확하게 실패한다.
set(KSI_PSDK_TAP_APP_INFO_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/config/dji_sdk_app_info.h")
if(NOT EXISTS "${KSI_PSDK_TAP_APP_INFO_HEADER}")
  message(FATAL_ERROR
    "edge/psdk-tap/config/dji_sdk_app_info.h 가 없다.\n"
    "developer.dji.com 에서 발급받은 앱 정보로 다음을 해라:\n"
    "  cp edge/psdk-tap/config/dji_sdk_app_info.h.example edge/psdk-tap/config/dji_sdk_app_info.h\n"
    "  (편집해서 USER_APP_NAME 등 실제 값 채우기)\n"
    "이 파일은 저장소 루트 .gitignore 의 `**/dji_sdk_app_info.h` 규칙으로 항상 무시된다 — "
    "실수로 커밋될 위험이 없다. 자세한 건 edge/psdk-tap/README.md 참조.")
endif()

# --- PSDK 위치 ----------------------------------------------------------------------
# vendored PSDK 트리(edge/third_party/psdk)는 fetch 산출물이다(ADR-KSI-009 D5 — 핀하되
# vendoring 하지 않는다). 이 CMakeLists 는 그 트리를 수정하지 않고 읽기만 한다.
set(KSI_PSDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/psdk" CACHE PATH
    "vendored PSDK 트리 경로")
if(NOT EXISTS "${KSI_PSDK_ROOT}/psdk_lib/include/dji_core.h")
  message(FATAL_ERROR
    "PSDK 를 ${KSI_PSDK_ROOT} 에서 찾지 못했다(psdk_lib/include/dji_core.h 없음). "
    "tools/edge/fetch_psdk.py 로 먼저 fetch 하거나 -DKSI_PSDK_ROOT=<경로> 로 위치를 "
    "알려줘라 — 조용히 스텁으로 빌드하지 않는다.")
endif()

set(KSI_PSDK_LIB_TRIPLET "" CACHE STRING
    "psdk_lib/lib/<triplet> 디렉터리 이름. 비우면 CMAKE_SYSTEM_PROCESSOR 로 자동판별한다.")
if(NOT KSI_PSDK_LIB_TRIPLET)
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64")
    set(KSI_PSDK_LIB_TRIPLET "aarch64-linux-gnu-gcc")
  elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
    set(KSI_PSDK_LIB_TRIPLET "x86_64-linux-gnu-gcc")
  else()
    message(FATAL_ERROR
      "CMAKE_SYSTEM_PROCESSOR=${CMAKE_SYSTEM_PROCESSOR} 에 대응하는 PSDK lib triplet 을 "
      "자동판별할 수 없다 — -DKSI_PSDK_LIB_TRIPLET=<psdk_lib/lib 아래 디렉터리명> 으로 "
      "직접 지정해라(예: aarch64-linux-gnu-gcc).")
  endif()
endif()

set(KSI_PSDK_LIB_PATH "${KSI_PSDK_ROOT}/psdk_lib/lib/${KSI_PSDK_LIB_TRIPLET}/libpayloadsdk.a")
if(NOT EXISTS "${KSI_PSDK_LIB_PATH}")
  message(FATAL_ERROR "PSDK 정적 라이브러리를 찾지 못했다: ${KSI_PSDK_LIB_PATH}")
endif()

add_library(psdk_static STATIC IMPORTED)
set_target_properties(psdk_static PROPERTIES IMPORTED_LOCATION "${KSI_PSDK_LIB_PATH}")

# --- 선택: libusb-1.0 (USB bulk host-mode, isUsbHost==true 전용) ---------------------
# Manifold3 실기 경로(isUsbHost==false, Linux FunctionFS gadget)는 libusb 가 전혀
# 필요없다 — src/platform/usb_bulk_glue.h 상단 주석 참조. 없어도 configure 는 통과하고
# host-mode 만 컴파일 타임 스텁(NONSUPPORT)이 된다.
find_package(PkgConfig QUIET)
set(KSI_PSDK_TAP_HAVE_LIBUSB FALSE)
if(PKG_CONFIG_FOUND)
  pkg_check_modules(LIBUSB QUIET libusb-1.0)
  if(LIBUSB_FOUND)
    set(KSI_PSDK_TAP_HAVE_LIBUSB TRUE)
  endif()
endif()
if(NOT KSI_PSDK_TAP_HAVE_LIBUSB)
  message(STATUS
    "psdk-tap: libusb-1.0 개발 헤더를 찾지 못했다 — USB bulk host-mode(isUsbHost=true) "
    "경로는 컴파일만 되는 스텁(NONSUPPORT)으로 빌드된다. Manifold3 실기 경로"
    "(isUsbHost=false, FunctionFS)는 영향 없다.")
endif()

find_package(Threads REQUIRED)

# --- 실행파일 -------------------------------------------------------------------------
add_executable(psdk_tap
  src/main.c
  src/pairing.c
  src/clock_util.c
  src/ndjson_writer.c
  src/shared_state.c
  src/liveview_tap.c
  src/telemetry_tap.c
  src/platform/osal_glue.c
  src/platform/socket_glue.c
  src/platform/usb_bulk_glue.c
  src/platform/logger_console_glue.c
)

target_include_directories(psdk_tap PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${CMAKE_CURRENT_SOURCE_DIR}/config
)
# SYSTEM — 벤더 헤더(anonymous union 등)가 우리 -Wpedantic -Werror 에 걸리지 않게 한다.
target_include_directories(psdk_tap SYSTEM PRIVATE
  ${KSI_PSDK_ROOT}/psdk_lib/include
)

target_compile_options(psdk_tap PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(psdk_tap PRIVATE psdk_static Threads::Threads m dl)

if(KSI_PSDK_TAP_HAVE_LIBUSB)
  target_compile_definitions(psdk_tap PRIVATE LIBUSB_INSTALLED)
  target_include_directories(psdk_tap SYSTEM PRIVATE ${LIBUSB_INCLUDE_DIRS})
  target_link_directories(psdk_tap PRIVATE ${LIBUSB_LIBRARY_DIRS})
  target_link_libraries(psdk_tap PRIVATE ${LIBUSB_LIBRARIES})
endif()

# --- 테스트: pairing.c 순수 로직만, PSDK 의존 없음 -------------------------------------
option(KSI_BUILD_TESTS "psdk-tap 순수 로직 테스트를 빌드한다" ON)
if(KSI_BUILD_TESTS)
  enable_testing()
  add_executable(psdk_tap_pairing_tests tests/pairing_tests.c src/pairing.c)
  target_include_directories(psdk_tap_pairing_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
  target_compile_options(psdk_tap_pairing_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME psdk_tap_pairing COMMAND psdk_tap_pairing_tests)
endif()

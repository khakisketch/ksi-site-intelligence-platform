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

# --- 검증 범위 스위치 -----------------------------------------------------------------
#
# 기본(OFF)은 fail-closed 다 — 자격증명과 PSDK 실물이 없으면 configure 단계에서
# 명확히 실패한다. 조용히 스텁으로 빌드하지 않는다.
#
# 문제는 그 게이트가 **PSDK 와 무관한** 순수 로직(pairing.c 등)의 테스트까지 함께
# 막는다는 것이었다 — 그래서 이 트리 2179줄이 CI 밖에 있었다(risk
# psdk-tap-outside-ci-gate). 이 옵션을 명시적으로 켠 빌드는 psdk_tap 실행파일을
# 아예 구성하지 않고 PSDK 비의존 테스트만 만든다. 기본 경로의 엄격성은 그대로다.
#
# **이 모드가 통과했다는 것은 "수집기가 동작한다"가 아니라 "PSDK 를 건드리지 않는
# 로직이 회귀하지 않았다"만 뜻한다.** 아래 message 가 그 사실을 빌드 로그에 남긴다.
option(KSI_PSDK_TAP_LOGIC_TESTS_ONLY
       "PSDK·자격증명 없이 순수 로직 테스트만 구성한다(CI 전용, 기본 OFF)" OFF)

# HIL probe의 official DPK package는 실제 PSDK executable을 전제로 한다. Logic-only
# test 모드에서 이 옵션을 켜면 package target이 없다는 사실을 뒤늦게 발견하므로,
# configure 단계에서 두 모드의 충돌을 fail-closed로 밝힌다.
option(KSI_PSDK_TAP_BUILD_DPK "enable official build_dpk.sh target for the HIL probe" OFF)
set(KSI_PSDK_TAP_DPK_USER_APP_ID "" CACHE STRING "DJI-issued user_app_id for this DPK")
set(KSI_PSDK_TAP_FIRMWARE_VERSION "00.01.00.02" CACHE STRING "HIL probe DPK firmware version")
# dji_app_ctl가 DPK executable을 argv 없이 기동하므로, HIL raw-perception probe를 만들
# 때만 이 compile-time defaults를 바꾼다. 기본은 기존 Liveview H264 진단 경로다.
set(KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE "liveview" CACHE STRING
    "argv-less DPK default frame source: liveview or perception")
set_property(CACHE KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE PROPERTY STRINGS liveview perception)
set(KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION "front" CACHE STRING
    "argv-less DPK perception direction: down/front/rear/up/left/right")
set_property(CACHE KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION PROPERTY STRINGS
             down front rear up left right)
if(NOT KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE MATCHES "^(liveview|perception)$")
  message(FATAL_ERROR
    "KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE must be liveview or perception")
endif()
if(NOT KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION MATCHES "^(down|front|rear|up|left|right)$")
  message(FATAL_ERROR
    "KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION must be down/front/rear/up/left/right")
endif()
if(KSI_PSDK_TAP_LOGIC_TESTS_ONLY AND KSI_PSDK_TAP_BUILD_DPK)
  message(FATAL_ERROR
    "KSI_PSDK_TAP_BUILD_DPK=ON conflicts with KSI_PSDK_TAP_LOGIC_TESTS_ONLY=ON; "
    "a DPK requires the real PSDK executable")
endif()

if(KSI_PSDK_TAP_LOGIC_TESTS_ONLY)
  message(STATUS
    "psdk-tap: LOGIC_TESTS_ONLY — psdk_tap 실행파일을 구성하지 않는다. "
    "검증 범위는 PSDK 비의존 순수 로직뿐이며, 실기 수집 동작은 이 빌드가 "
    "주장하지 않는다(HIL 세션 증거로만).")
endif()

if(NOT KSI_PSDK_TAP_LOGIC_TESTS_ONLY)

# --- 자격증명 게이트 ---------------------------------------------------------------
# "자격증명(dji_sdk_app_info.h)은 빌드 입력이지 소스가 아니다" — 없으면 조용히
# 스텁/더미로 넘어가지 않고 여기서 명확하게 실패한다. 외부 owner-only 경로도 받아
# DPK HIL 빌드가 worktree에 credential을 복사하도록 강요하지 않는다.
set(KSI_PSDK_TAP_APP_INFO_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/config/dji_sdk_app_info.h" CACHE FILEPATH
    "DJI PSDK credential header (untracked deployment input)")
if(NOT EXISTS "${KSI_PSDK_TAP_APP_INFO_HEADER}")
  message(FATAL_ERROR
    "DJI credential header를 찾지 못했다: ${KSI_PSDK_TAP_APP_INFO_HEADER}\n"
    "developer.dji.com에서 발급받은 dji_sdk_app_info.h를 만들고 "
    "-DKSI_PSDK_TAP_APP_INFO_HEADER=<외부 경로>로 지정해라.\n"
    "예시는 edge/psdk-tap/config/dji_sdk_app_info.h.example 이다.\n"
    "이 파일은 저장소 루트 .gitignore 의 `**/dji_sdk_app_info.h` 규칙으로 항상 무시된다 — "
    "실수로 커밋될 위험이 없다. 자세한 건 edge/psdk-tap/README.md 참조.")
endif()
get_filename_component(_tap_app_info_name "${KSI_PSDK_TAP_APP_INFO_HEADER}" NAME)
if(NOT _tap_app_info_name STREQUAL "dji_sdk_app_info.h")
  message(FATAL_ERROR "KSI_PSDK_TAP_APP_INFO_HEADER의 파일명은 dji_sdk_app_info.h 여야 한다")
endif()
get_filename_component(KSI_PSDK_TAP_APP_INFO_DIR "${KSI_PSDK_TAP_APP_INFO_HEADER}" DIRECTORY)

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
include("${CMAKE_CURRENT_SOURCE_DIR}/../psdk-platform/psdk_platform.cmake")

# --- 실행파일 -------------------------------------------------------------------------
add_executable(psdk_tap
  src/main.c
  src/pairing.c
  src/clock_util.c
  src/ndjson_writer.c
  src/shared_state.c
  src/liveview_tap.c
  src/perception_tap.c
  src/telemetry_tap.c
)
ksi_add_psdk_platform_glue(psdk_tap)

target_include_directories(psdk_tap PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${KSI_PSDK_TAP_APP_INFO_DIR}
)
# SYSTEM — 벤더 헤더(anonymous union 등)가 우리 -Wpedantic -Werror 에 걸리지 않게 한다.
target_include_directories(psdk_tap SYSTEM PRIVATE
  ${KSI_PSDK_ROOT}/psdk_lib/include
)

target_compile_options(psdk_tap PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_compile_definitions(psdk_tap PRIVATE
  KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE=\"${KSI_PSDK_TAP_DEFAULT_FRAME_SOURCE}\"
  KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION=\"${KSI_PSDK_TAP_DEFAULT_PERCEPTION_DIRECTION}\"
)
target_link_libraries(psdk_tap PRIVATE psdk_static Threads::Threads m dl)

if(KSI_PSDK_TAP_HAVE_LIBUSB)
  target_compile_definitions(psdk_tap PRIVATE LIBUSB_INSTALLED)
  target_include_directories(psdk_tap SYSTEM PRIVATE ${LIBUSB_INCLUDE_DIRS})
  target_link_directories(psdk_tap PRIVATE ${LIBUSB_LIBRARY_DIRS})
  target_link_libraries(psdk_tap PRIVATE ${LIBUSB_LIBRARIES})
endif()

# HIL probe도 SSH에서 직접 실행하면 PSDK USB bulk channel을 얻지 못한다. 실제
# telemetry/liveview 관측은 official DPK를 dji_app_ctl로 설치해 시작해야 한다.
# user_app_id는 DJI가 발급하므로 default package를 만들지 않는다.
if(KSI_PSDK_TAP_BUILD_DPK)
  if(NOT KSI_TARGET_MANIFOLD3)
    message(FATAL_ERROR
      "KSI_PSDK_TAP_BUILD_DPK=ON requires KSI_TARGET_MANIFOLD3=ON")
  endif()
  if(NOT KSI_PSDK_TAP_DPK_USER_APP_ID)
    message(FATAL_ERROR
      "KSI_PSDK_TAP_BUILD_DPK=ON requires DJI-issued -DKSI_PSDK_TAP_DPK_USER_APP_ID=<id>")
  endif()
  if(NOT KSI_PSDK_TAP_DPK_USER_APP_ID MATCHES "^[A-Za-z0-9._-]+$")
    message(FATAL_ERROR
      "KSI_PSDK_TAP_DPK_USER_APP_ID must contain only letters, digits, dot, underscore, or hyphen")
  endif()
  # DJI build_dpk.sh rejects user_app_id longer than 16 bytes. The character
  # allow-list above is ASCII, so CMake string length equals the package byte
  # count; fail here before an expensive target build reaches the vendor tool.
  string(LENGTH "${KSI_PSDK_TAP_DPK_USER_APP_ID}" _ksi_psdk_tap_user_app_id_length)
  if(_ksi_psdk_tap_user_app_id_length GREATER 16)
    message(FATAL_ERROR "KSI_PSDK_TAP_DPK_USER_APP_ID must be at most 16 ASCII bytes")
  endif()
  if(NOT KSI_PSDK_TAP_FIRMWARE_VERSION MATCHES
     "^[0-9][0-9]\\.[0-9][0-9]\\.[0-9][0-9]\\.[0-9][0-9]$")
    message(FATAL_ERROR
      "KSI_PSDK_TAP_FIRMWARE_VERSION must have the form 00.00.00.00")
  endif()
  set(KSI_PSDK_TAP_DPK_BINARY "../psdk_tap")
  configure_file(config/app.json.in "${CMAKE_CURRENT_BINARY_DIR}/dpk/app.json" @ONLY)
  add_custom_target(ksi_psdk_tap_dpk
    COMMAND "${KSI_PSDK_ROOT}/tools/build_dpk/build_dpk.sh"
            -i "${CMAKE_CURRENT_BINARY_DIR}/dpk/app.json"
            -o "${CMAKE_CURRENT_BINARY_DIR}/dpk/out"
    DEPENDS psdk_tap
    COMMENT "Generating official Manifold 3 HIL probe .dpk with DJI build_dpk.sh"
    VERBATIM
  )
endif()

endif()  # NOT KSI_PSDK_TAP_LOGIC_TESTS_ONLY

# --- 테스트: pairing.c 순수 로직만, PSDK 의존 없음 -------------------------------------
option(KSI_BUILD_TESTS "psdk-tap 순수 로직 테스트를 빌드한다" ON)
if(KSI_BUILD_TESTS)
  find_package(Threads REQUIRED)
  enable_testing()
  add_executable(psdk_tap_pairing_tests tests/pairing_tests.c src/pairing.c)
  target_include_directories(psdk_tap_pairing_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
  target_compile_options(psdk_tap_pairing_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME psdk_tap_pairing COMMAND psdk_tap_pairing_tests)

  # NDJSON v2 contract test: no PSDK/callback dependency, but proves that an
  # unverified perception timestamp remains a lossless raw string rather than
  # being silently re-labelled sensor_us.
  add_executable(psdk_tap_ndjson_writer_tests tests/ndjson_writer_tests.c src/ndjson_writer.c)
  target_include_directories(psdk_tap_ndjson_writer_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
  target_compile_options(psdk_tap_ndjson_writer_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  target_link_libraries(psdk_tap_ndjson_writer_tests PRIVATE Threads::Threads)
  add_test(NAME psdk_tap_ndjson_writer COMMAND psdk_tap_ndjson_writer_tests)
endif()

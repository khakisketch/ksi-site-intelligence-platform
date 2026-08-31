# Manifold 3 production PSDK entry point — RGB/telemetry ingress plus the
# native Edge runtime.  This target deliberately contains no DJI Flight Control
# header or library: it is a shadow-only data application.
cmake_minimum_required(VERSION 3.16...3.28)
project(ksi_psdk_app LANGUAGES C CXX VERSION 0.1.0)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_definitions(_GNU_SOURCE)

# Native activation is deliberately a deployment-time opt-in.  The values are
# not credentials, but embedding an unreviewed device ID or a shared/writable
# state directory would make a copied DPK accept the wrong private handoff.
# A package without these three explicit inputs remains capture-only.
option(KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION
       "load private verified native activation handoff at DPK startup" OFF)
set(KSI_PSDK_APP_EDGE_DEVICE_ID "" CACHE STRING
    "Edge device ID bound into the DPK native activation reader")
set(KSI_PSDK_APP_ACTIVATION_STATE_DIR "" CACHE PATH
    "Private on-device directory written by the verified activation consumer")
set(KSI_PSDK_APP_RUNTIME_VERSION "manifold3-edge-shadow-0.2.0" CACHE STRING
    "Runtime version that must match the activation receipt")

# Perception is a third, stricter deployment tier.  It needs a verified native
# dispatch/profile handoff, a dedicated journal/artifact directory, and a
# private model input directory.  The standard DPK deliberately leaves this
# disabled: no arbitrary model path or calibration can turn capture-only mode
# into an event producer.
option(KSI_PSDK_APP_ENABLE_PERCEPTION
       "enable signed-profile TensorRT/projector/evidence pipeline" OFF)
set(KSI_PSDK_APP_PERCEPTION_STATE_DIR "" CACHE PATH
    "Private on-device SQLite/artifact directory for perception")
set(KSI_PSDK_APP_MODEL_ARTIFACT_DIR "" CACHE PATH
    "Private on-device directory containing signed-profile ONNX artifacts")
if(KSI_PSDK_APP_ENABLE_PERCEPTION)
  # Set this before adding manifold-runtime.  That target then rejects a
  # missing TensorRT/CUDA installation instead of compiling a hidden CPU
  # fallback that might be mistaken for an approved deployment.
  set(KSI_ENABLE_TENSORRT ON CACHE BOOL
      "build the optional native TensorRT D-FINE adapter" FORCE)
endif()

# Store-and-forward network delivery is separately provisioned from native
# activation.  The bearer itself remains only in a private on-device file; the
# other values bind this particular DPK to reviewed Core/storage TLS endpoints.
# Without every value this target remains capture-only rather than falling back
# to an unauthenticated or unpinned HTTP client.
option(KSI_PSDK_APP_ENABLE_CORE_SYNC
       "enable the statically-linked HTTPS Core/store-and-forward adapter" OFF)
set(KSI_PSDK_APP_SYNC_STATE_DIR "" CACHE PATH
    "Private on-device SQLite/artifact directory for Core sync")
set(KSI_PSDK_APP_CORE_BASE_URL "" CACHE STRING
    "Pinned Core HTTPS origin for Edge sync")
set(KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE "" CACHE FILEPATH
    "Private bearer token file, never packaged or embedded")
set(KSI_PSDK_APP_TLS_CA_BUNDLE "" CACHE FILEPATH
    "Absolute CA bundle path trusted by the Core/storage TLS executor")
set(KSI_PSDK_APP_CORE_TLS_PIN "" CACHE STRING
    "Core SPKI pin in libcurl sha256//base64 form")
set(KSI_PSDK_APP_STORAGE_TLS_PIN "" CACHE STRING
    "Evidence-storage SPKI pin in libcurl sha256//base64 form")
set(KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID "" CACHE STRING
    "Operator-provisioned device attestation key ID")
set(KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE "" CACHE FILEPATH
    "External owner-only 0600 Ed25519 PEM private key; never package or log")
if(KSI_PSDK_APP_ENABLE_CORE_SYNC)
  # The runtime checks the resulting archive is static.  Set this before the
  # subdirectory so an enabled DPK cannot accidentally retain only its abstract
  # transport interface.
  set(KSI_ENABLE_CURL_EDGE_TRANSPORT ON CACHE BOOL
      "build the optional statically-linked libcurl HTTPS executor" FORCE)
  set(KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION ON CACHE BOOL
      "build the statically-linked Ed25519 evidence signer" FORCE)
endif()

# Automatic media offload is deliberately unavailable in the production host.
# The PSDK-independent conveyor remains fully tested in manifold-runtime, but
# the product still lacks two pieces that cannot be guessed from a file list:
# a real DjiCameraManager_* adapter and a device-wired completion/baseline
# provider.  The PSDK-independent exact-identity boundary now exists in
# manifold-runtime, but no packaged code supplies its trigger/baseline from a
# verified DJI source. Keep the historical cache
# option so old build invocations fail with an actionable message instead of
# silently ignoring a requested capability.
option(KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD
       "request mission-scoped PSDK media offload (currently blocked pending adapter + HIL)"
       OFF)

if(COMMAND ksi_check_manifold3_toolchain_drift)
  ksi_check_manifold3_toolchain_drift()
endif()

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "build type" FORCE)
endif()

# Credentials are a deployment input, never a repository asset.  An absolute
# path is accepted so a HIL operator can keep it outside the worktree, but its
# basename is fixed because the source include is intentionally unambiguous.
set(KSI_PSDK_APP_INFO_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/config/dji_sdk_app_info.h" CACHE FILEPATH
    "DJI PSDK credential header (untracked deployment input)")
if(NOT EXISTS "${KSI_PSDK_APP_INFO_HEADER}")
  message(FATAL_ERROR
    "edge/psdk-app/config/dji_sdk_app_info.h 가 없다. 실제 DJI 자격증명 헤더를 만들거나 "
    "-DKSI_PSDK_APP_INFO_HEADER=<외부 경로> 를 지정해라. 예시는 config/dji_sdk_app_info.h.example 이다.")
endif()
get_filename_component(_app_info_name "${KSI_PSDK_APP_INFO_HEADER}" NAME)
if(NOT _app_info_name STREQUAL "dji_sdk_app_info.h")
  message(FATAL_ERROR "KSI_PSDK_APP_INFO_HEADER 의 파일명은 dji_sdk_app_info.h 여야 한다")
endif()
get_filename_component(KSI_PSDK_APP_INFO_DIR "${KSI_PSDK_APP_INFO_HEADER}" DIRECTORY)

# PSDK is an explicitly fetched, pinned build input (ADR-KSI-009 D5), not a
# source subtree this application vendors or patches.
set(KSI_PSDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/psdk" CACHE PATH
    "official fetched DJI PSDK root")
if(NOT EXISTS "${KSI_PSDK_ROOT}/psdk_lib/include/dji_core.h")
  message(FATAL_ERROR
    "PSDK 를 ${KSI_PSDK_ROOT} 에서 찾지 못했다. tools/edge/fetch_psdk.py 로 fetch 하거나 "
    "-DKSI_PSDK_ROOT=<경로> 를 지정해라.")
endif()

set(KSI_PSDK_LIB_TRIPLET "" CACHE STRING
    "psdk_lib/lib 아래 PSDK ABI triplet (비우면 CPU 아키텍처에서 판별)")
if(NOT KSI_PSDK_LIB_TRIPLET)
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64")
    set(KSI_PSDK_LIB_TRIPLET "aarch64-linux-gnu-gcc")
  elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
    set(KSI_PSDK_LIB_TRIPLET "x86_64-linux-gnu-gcc")
  else()
    message(FATAL_ERROR
      "CMAKE_SYSTEM_PROCESSOR=${CMAKE_SYSTEM_PROCESSOR} 의 PSDK triplet을 판별할 수 없다. "
      "-DKSI_PSDK_LIB_TRIPLET=<디렉터리명> 으로 지정해라.")
  endif()
endif()
set(KSI_PSDK_LIB_PATH "${KSI_PSDK_ROOT}/psdk_lib/lib/${KSI_PSDK_LIB_TRIPLET}/libpayloadsdk.a")
if(NOT EXISTS "${KSI_PSDK_LIB_PATH}")
  message(FATAL_ERROR "PSDK 정적 라이브러리를 찾지 못했다: ${KSI_PSDK_LIB_PATH}")
endif()
add_library(ksi_psdk_static STATIC IMPORTED)
set_target_properties(ksi_psdk_static PROPERTIES IMPORTED_LOCATION "${KSI_PSDK_LIB_PATH}")

find_package(Threads REQUIRED)
find_package(PkgConfig QUIET)
set(KSI_PSDK_APP_HAVE_LIBUSB FALSE)
if(PKG_CONFIG_FOUND)
  pkg_check_modules(LIBUSB QUIET libusb-1.0)
  if(LIBUSB_FOUND)
    set(KSI_PSDK_APP_HAVE_LIBUSB TRUE)
  endif()
endif()

# The packaged application is an executable, not the runtime unit-test tree.
# The runtime still receives its independent host/Docker test build elsewhere.
set(KSI_BUILD_TESTS OFF CACHE BOOL "disable nested manifold-runtime tests in PSDK app" FORCE)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../manifold-runtime"
                 "${CMAKE_CURRENT_BINARY_DIR}/manifold-runtime")
include("${CMAKE_CURRENT_SOURCE_DIR}/../psdk-platform/psdk_platform.cmake")

add_executable(ksi_psdk_app src/main.cpp)
ksi_add_psdk_platform_glue(ksi_psdk_app)
target_include_directories(ksi_psdk_app PRIVATE
  "${KSI_PSDK_APP_INFO_DIR}"
)
target_include_directories(ksi_psdk_app SYSTEM PRIVATE
  "${KSI_PSDK_ROOT}/psdk_lib/include"
)
target_compile_options(ksi_psdk_app PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(ksi_psdk_app PRIVATE ksi_edge_runtime ksi_psdk_static Threads::Threads m dl)

# Candidate S1 is compiled only for an approval-bound HIL build. Merely placing
# the source in the repository does not add it to the default DPK. The committed
# allowlist cannot permit DjiWaypointV3_Action or any FlightController API.
option(KSI_PSDK_APP_ENABLE_WAYLINE_UPLOAD_ONLY
       "compile the HIL-only WaypointV3 Init/Upload/DeInit surface" OFF)
set(KSI_PSDK_APP_WAYLINE_UPLOAD_ALLOWLIST
    "${CMAKE_CURRENT_SOURCE_DIR}/../flight-execution-upload-only-allowlist.v1.json"
    CACHE FILEPATH "reviewed C2-S1 flight-boundary allowlist")
if(KSI_PSDK_APP_ENABLE_WAYLINE_UPLOAD_ONLY)
  if(NOT KSI_TARGET_MANIFOLD3)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_WAYLINE_UPLOAD_ONLY=ON requires KSI_TARGET_MANIFOLD3=ON")
  endif()
  if(NOT EXISTS "${KSI_PSDK_APP_WAYLINE_UPLOAD_ALLOWLIST}")
    message(FATAL_ERROR "reviewed Waypoint upload-only allowlist is missing")
  endif()
  # The canonical Manifold 3 builder is Ubuntu 20.04/Python 3.8. The checker
  # is import-tested on that interpreter, so requiring the developer host's
  # newer Python would make the deployment build impossible.
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  execute_process(
    COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/edge/check_psdk_waypoint_archive.py"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/PSDK_LOCK.yaml"
            --psdk-root "${KSI_PSDK_ROOT}"
            --format json
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../.."
    RESULT_VARIABLE _waypoint_archive_gate_result
    OUTPUT_VARIABLE _waypoint_archive_gate_output
    ERROR_VARIABLE _waypoint_archive_gate_error
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_STRIP_TRAILING_WHITESPACE
  )
  if(NOT _waypoint_archive_gate_result EQUAL 0)
    message(FATAL_ERROR
      "Waypoint upload-only archive preflight failed closed "
      "(exit=${_waypoint_archive_gate_result}).\n"
      "${_waypoint_archive_gate_output}\n${_waypoint_archive_gate_error}")
  endif()
  target_sources(ksi_psdk_app PRIVATE
    src/flight_execution/waypoint_v3_upload_only.cpp
  )
  add_custom_command(TARGET ksi_psdk_app POST_BUILD
    COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/edge/check_shadow_flight_boundary.py"
            "$<TARGET_FILE:ksi_psdk_app>"
            edge/psdk-app/src
            edge/manifold-runtime/src
            edge/manifold-runtime/include
            --allow-mission-execution "${KSI_PSDK_APP_WAYLINE_UPLOAD_ALLOWLIST}"
    COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/edge/check_shadow_flight_boundary.py"
            "$<TARGET_FILE:ksi_psdk_app>"
            edge/psdk-app/src
            edge/manifold-runtime/src
            edge/manifold-runtime/include
            --require-zero-defined-symbols
            --allow-mission-execution "${KSI_PSDK_APP_WAYLINE_UPLOAD_ALLOWLIST}"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../.."
    COMMENT "Verifying the C2-S1 upload-only source and ELF boundary"
    VERBATIM
  )
endif()
if(KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION)
  if(NOT KSI_PSDK_APP_EDGE_DEVICE_ID OR NOT KSI_PSDK_APP_ACTIVATION_STATE_DIR OR
     NOT KSI_PSDK_APP_RUNTIME_VERSION)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION=ON requires EDGE_DEVICE_ID, ACTIVATION_STATE_DIR, and RUNTIME_VERSION")
  endif()
  foreach(_native_value IN ITEMS KSI_PSDK_APP_EDGE_DEVICE_ID KSI_PSDK_APP_ACTIVATION_STATE_DIR
                                KSI_PSDK_APP_RUNTIME_VERSION)
    if("${${_native_value}}" MATCHES "[\"\n\r;]")
      message(FATAL_ERROR "${_native_value} contains an unsafe C++ string literal character")
    endif()
  endforeach()
  target_compile_definitions(ksi_psdk_app PRIVATE
    KSI_PSDK_APP_EDGE_ACTIVATION_CONFIGURED=1
    "KSI_PSDK_APP_EDGE_DEVICE_ID=\"${KSI_PSDK_APP_EDGE_DEVICE_ID}\""
    "KSI_PSDK_APP_ACTIVATION_STATE_DIR=\"${KSI_PSDK_APP_ACTIVATION_STATE_DIR}\""
    "KSI_PSDK_APP_RUNTIME_VERSION=\"${KSI_PSDK_APP_RUNTIME_VERSION}\""
  )
else()
  target_compile_definitions(ksi_psdk_app PRIVATE KSI_PSDK_APP_EDGE_ACTIVATION_CONFIGURED=0)
endif()
if(KSI_PSDK_APP_ENABLE_PERCEPTION)
  if(NOT KSI_TARGET_MANIFOLD3)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_PERCEPTION=ON requires KSI_TARGET_MANIFOLD3=ON")
  endif()
  if(NOT KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_PERCEPTION=ON requires KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION=ON")
  endif()
  if(NOT KSI_ENABLE_TENSORRT)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_PERCEPTION=ON requires KSI_ENABLE_TENSORRT=ON")
  endif()
  if(NOT KSI_PSDK_APP_EDGE_DEVICE_ID OR NOT KSI_PSDK_APP_ACTIVATION_STATE_DIR OR
     NOT KSI_PSDK_APP_PERCEPTION_STATE_DIR OR NOT KSI_PSDK_APP_MODEL_ARTIFACT_DIR)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_PERCEPTION=ON requires EDGE_DEVICE_ID, ACTIVATION_STATE_DIR, PERCEPTION_STATE_DIR, and MODEL_ARTIFACT_DIR")
  endif()
  if(NOT IS_ABSOLUTE "${KSI_PSDK_APP_PERCEPTION_STATE_DIR}" OR
     NOT IS_ABSOLUTE "${KSI_PSDK_APP_MODEL_ARTIFACT_DIR}")
    message(FATAL_ERROR
      "PERCEPTION_STATE_DIR and MODEL_ARTIFACT_DIR must be absolute on-device paths")
  endif()
  if("${KSI_PSDK_APP_PERCEPTION_STATE_DIR}" STREQUAL "${KSI_PSDK_APP_ACTIVATION_STATE_DIR}")
    message(FATAL_ERROR
      "PERCEPTION_STATE_DIR must differ from ACTIVATION_STATE_DIR; journal/artifacts must not share the activation handoff directory")
  endif()
  foreach(_perception_value IN ITEMS KSI_PSDK_APP_EDGE_DEVICE_ID
                                     KSI_PSDK_APP_PERCEPTION_STATE_DIR
                                     KSI_PSDK_APP_MODEL_ARTIFACT_DIR)
    if("${${_perception_value}}" MATCHES "[\"\n\r;]")
      message(FATAL_ERROR "${_perception_value} contains an unsafe C++ string literal character")
    endif()
  endforeach()
  target_compile_definitions(ksi_psdk_app PRIVATE
    KSI_PSDK_APP_PERCEPTION_CONFIGURED=1
    "KSI_PSDK_APP_PERCEPTION_STATE_DIR=\"${KSI_PSDK_APP_PERCEPTION_STATE_DIR}\""
    "KSI_PSDK_APP_MODEL_ARTIFACT_DIR=\"${KSI_PSDK_APP_MODEL_ARTIFACT_DIR}\""
  )
else()
  target_compile_definitions(ksi_psdk_app PRIVATE KSI_PSDK_APP_PERCEPTION_CONFIGURED=0)
endif()
if(KSI_PSDK_APP_ENABLE_CORE_SYNC)
  if(NOT KSI_TARGET_MANIFOLD3)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_CORE_SYNC=ON requires KSI_TARGET_MANIFOLD3=ON so TLS/SQLite dependencies are statically selected")
  endif()
  if(NOT KSI_PSDK_APP_EDGE_DEVICE_ID OR NOT KSI_PSDK_APP_SYNC_STATE_DIR OR
     NOT KSI_PSDK_APP_CORE_BASE_URL OR NOT KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE OR
     NOT KSI_PSDK_APP_TLS_CA_BUNDLE OR NOT KSI_PSDK_APP_CORE_TLS_PIN OR
     NOT KSI_PSDK_APP_STORAGE_TLS_PIN OR
     NOT KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID OR
     NOT KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE)
    message(FATAL_ERROR
      "KSI_PSDK_APP_ENABLE_CORE_SYNC=ON requires EDGE_DEVICE_ID, SYNC_STATE_DIR, CORE_BASE_URL, CORE_BEARER_TOKEN_FILE, TLS_CA_BUNDLE, CORE_TLS_PIN, STORAGE_TLS_PIN, EVIDENCE_ATTESTATION_KEY_ID, and external EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE")
  endif()
  if(NOT IS_ABSOLUTE "${KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE}")
    message(FATAL_ERROR "EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE must be an absolute external path")
  endif()
  if(KSI_PSDK_APP_ENABLE_PERCEPTION AND NOT
     "${KSI_PSDK_APP_SYNC_STATE_DIR}" STREQUAL "${KSI_PSDK_APP_PERCEPTION_STATE_DIR}")
    message(FATAL_ERROR
      "SYNC_STATE_DIR must equal PERCEPTION_STATE_DIR when perception is enabled so the pipeline and sync worker share one durable journal")
  endif()
  if(KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION AND
     "${KSI_PSDK_APP_SYNC_STATE_DIR}" STREQUAL "${KSI_PSDK_APP_ACTIVATION_STATE_DIR}")
    message(FATAL_ERROR
      "SYNC_STATE_DIR must differ from ACTIVATION_STATE_DIR; journal/artifacts must not share the activation handoff directory")
  endif()
  foreach(_sync_value IN ITEMS KSI_PSDK_APP_EDGE_DEVICE_ID KSI_PSDK_APP_SYNC_STATE_DIR
                               KSI_PSDK_APP_CORE_BASE_URL KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE
                               KSI_PSDK_APP_TLS_CA_BUNDLE KSI_PSDK_APP_CORE_TLS_PIN
                               KSI_PSDK_APP_STORAGE_TLS_PIN
                               KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID
                               KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE)
    if("${${_sync_value}}" MATCHES "[\"\n\r;]")
      message(FATAL_ERROR "${_sync_value} contains an unsafe C++ string literal character")
    endif()
  endforeach()
  target_compile_definitions(ksi_psdk_app PRIVATE
    KSI_PSDK_APP_CORE_SYNC_CONFIGURED=1
    "KSI_PSDK_APP_SYNC_STATE_DIR=\"${KSI_PSDK_APP_SYNC_STATE_DIR}\""
    "KSI_PSDK_APP_CORE_BASE_URL=\"${KSI_PSDK_APP_CORE_BASE_URL}\""
    "KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE=\"${KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE}\""
    "KSI_PSDK_APP_TLS_CA_BUNDLE=\"${KSI_PSDK_APP_TLS_CA_BUNDLE}\""
    "KSI_PSDK_APP_CORE_TLS_PIN=\"${KSI_PSDK_APP_CORE_TLS_PIN}\""
    "KSI_PSDK_APP_STORAGE_TLS_PIN=\"${KSI_PSDK_APP_STORAGE_TLS_PIN}\""
    "KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID=\"${KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID}\""
    "KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE=\"${KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE}\""
  )
  if(NOT KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION)
    target_compile_definitions(ksi_psdk_app PRIVATE
      "KSI_PSDK_APP_EDGE_DEVICE_ID=\"${KSI_PSDK_APP_EDGE_DEVICE_ID}\""
    )
  endif()
else()
  target_compile_definitions(ksi_psdk_app PRIVATE KSI_PSDK_APP_CORE_SYNC_CONFIGURED=0)
endif()
if(KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD)
  message(FATAL_ERROR
    "KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD is blocked: the production host has no real "
    "DjiCameraManager adapter or verified device-side trigger/baseline provider. Keep it OFF and use "
    "SD/PC/Web intake until the one-JPEG M4D HIL and cross-mission attribution gate pass.")
endif()
if(KSI_PSDK_APP_HAVE_LIBUSB)
  target_compile_definitions(ksi_psdk_app PRIVATE LIBUSB_INSTALLED)
  target_include_directories(ksi_psdk_app SYSTEM PRIVATE ${LIBUSB_INCLUDE_DIRS})
  target_link_directories(ksi_psdk_app PRIVATE ${LIBUSB_LIBRARY_DIRS})
  target_link_libraries(ksi_psdk_app PRIVATE ${LIBUSB_LIBRARIES})
else()
  message(STATUS "psdk-app: libusb development headers unavailable; Manifold FunctionFS path remains supported")
endif()

# Official DPK packaging is intentionally opt-in because user_app_id is issued
# by DJI.  The generated manifest lives in the build tree and points at the
# just-built binary via a relative path; no secret or generated package enters
# git.
option(KSI_PSDK_APP_BUILD_DPK "enable official build_dpk.sh target" OFF)
set(KSI_PSDK_APP_DPK_USER_APP_ID "" CACHE STRING "DJI user_app_id for this DPK")
set(KSI_PSDK_APP_FIRMWARE_VERSION "00.02.00.00" CACHE STRING "DPK firmware version")
if(KSI_PSDK_APP_BUILD_DPK)
  if(NOT KSI_PSDK_APP_DPK_USER_APP_ID)
    message(FATAL_ERROR
      "KSI_PSDK_APP_BUILD_DPK=ON requires DJI-issued -DKSI_PSDK_APP_DPK_USER_APP_ID=<id>")
  endif()
  set(KSI_PSDK_APP_DPK_BINARY "../ksi_psdk_app")
  configure_file(config/app.json.in "${CMAKE_CURRENT_BINARY_DIR}/dpk/app.json" @ONLY)
  add_custom_target(ksi_psdk_app_dpk
    COMMAND "${KSI_PSDK_ROOT}/tools/build_dpk/build_dpk.sh"
            -i "${CMAKE_CURRENT_BINARY_DIR}/dpk/app.json"
            -o "${CMAKE_CURRENT_BINARY_DIR}/dpk/out"
    DEPENDS ksi_psdk_app
    COMMENT "Generating official Manifold 3 .dpk with DJI build_dpk.sh"
    VERBATIM
  )
endif()

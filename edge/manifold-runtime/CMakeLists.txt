# KSI Edge — Manifold native control plane (Stage C-3 골격)
#
# 이 빌드는 **호스트에서 그대로 빌드·테스트되는** 순수 C++17 계약 골격이다.
# DJI PSDK 의존은 이 라이브러리에 없고, CUDA·TensorRT 어댑터는 명시적 opt-in으로만
# 빌드된다. 실기/HIL 증거 전까지 비행명령 경로를 활성화하지 않는다는 Stage C 범위
# 제약(승인된 금지 항목)은 그대로 유지한다.
# 실제 Manifold 3 타깃 툴체인은 docs/edge/MANIFOLD3_TOOLCHAIN.md 참조.
#
# cmake 하한: 이 파일이 실제로 쓰는 최신 기능은 add_link_options(3.13)이고 3.17+
# 기능은 없다 — 이전의 3.22 요구는 근거 없는 상향이었다(2026-08-03 실기 세션에서
# Manifold 3 온보드 cmake 3.16.3과 충돌해 발견·정정). 범위 표기(3.12+ 지원)를 써서
# 호스트/CI(3.28)의 정책 기본값은 그대로 유지한다.
cmake_minimum_required(VERSION 3.16...3.28)
project(ksi_manifold_runtime LANGUAGES CXX VERSION 0.0.1)

# 타깃 정책(KSI_TARGET_MANIFOLD3=ON)으로 빌드할 때만 컴파일러 신원을 단언한다.
# 이 호출이 없으면 cmake/toolchain-manifold3.cmake 의 드리프트 게이트가 정의만 되고
# 아무 데서도 실행되지 않는 죽은 코드가 된다 — 즉 "실기와 다른 gcc로 타깃 산출물을
# 만드는 것"을 막겠다는 그 파일의 존재 이유가 성립하지 않는다(2026-08-04 감사 지적).
# 함수는 툴체인 파일이 정의하므로, 툴체인 파일 없이 빌드하는 호스트 경로에서는
# 존재 여부를 먼저 확인해 무해하게 건너뛴다.
if(COMMAND ksi_check_manifold3_toolchain_drift)
  ksi_check_manifold3_toolchain_drift()
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "빌드 타입" FORCE)
endif()

# 정수 오버플로·UB·메모리 오류는 -Werror 로 잡히지 않는다(감사 #56·#72). 이 블록은
# 반드시 add_library **앞**이어야 한다 — 디렉토리 옵션은 타깃 생성 시점에 스냅샷
# 되므로 뒤에 두면 테스트 드라이버만 계측되고 정작 검증 대상 라이브러리(TTL 산술이
# 있는 TU)는 비계측이 된다(자율 재검토 P1-D1 — 실산출물 flags.make 로 확증).
option(KSI_ENABLE_SANITIZERS "ASan+UBSan 계측 빌드" OFF)
if(KSI_ENABLE_SANITIZERS)
  # -fno-sanitize-recover=all 이 없으면 **UBSan 이 UB 를 잡아도 종료코드가 0 이다.**
  # UBSan 은 기본이 recoverable 이라 런타임 에러를 stderr 에 찍고 그냥 계속 실행한다 —
  # ctest 는 green 을 보고, 그러면 이 job 이 주장하는 "UB 없음"이 사실은 아무것도
  # 주장하지 않는다(2026-08-07 실측: signed overflow 프로그램이 exit 0, 이 플래그를
  # 붙이면 exit 1). ASan 은 기본이 halt 라 원래 정상이었다.
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=all
                      -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined -fno-sanitize-recover=all)
endif()

# TensorRT is a device-provided dynamic runtime, not a host/CI dependency.
# Opting in is deliberately explicit: the target ABI gate separately requires
# --allow-nvidia-libs plus Manifold HIL proof before this profile can be used.
option(KSI_ENABLE_TENSORRT "build the optional native TensorRT D-FINE adapter" OFF)
set(KSI_TENSORRT_ROOT "" CACHE PATH "TensorRT/CUDA root on the Manifold image")

# The DPK ABI policy allows third-party code only when statically linked.  A
# concrete HTTPS executor therefore remains an explicit opt-in and rejects a
# shared libcurl at configure time; the final ELF ABI gate remains the last
# authority for curl's transitive dependencies.
option(KSI_ENABLE_CURL_EDGE_TRANSPORT
       "build the optional statically-linked libcurl HTTPS executor" OFF)
set(KSI_CURL_STATIC_EXTRA_LIBRARIES "" CACHE STRING
    "semicolon-separated absolute .a dependencies for the reviewed libcurl bundle")

option(KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION
       "sign Core evidence registration payloads with statically-linked OpenSSL Ed25519" OFF)
set(KSI_OPENSSL_ROOT "" CACHE PATH
    "OpenSSL development root containing include/openssl/evp.h and a static libcrypto.a")

add_library(ksi_control_plane
  src/command.cpp
  src/supervisor.cpp
)
target_include_directories(ksi_control_plane PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_compile_options(ksi_control_plane PRIVATE
  -Wall -Wextra -Wpedantic -Werror
)

# Edge data plane — PSDK callback은 이 라이브러리의 bounded ingress에 바이트만
# 복사하고, TensorRT/추적/위험/원장 작업은 별도 worker가 맡는다. DJI FC 제어
# 라이브러리는 어떤 target에도 링크하지 않는다(INV-001).
add_library(ksi_edge_runtime
  src/activation.cpp
  src/runtime_profile.cpp
  src/calibrated_projector.cpp
  src/artifact_vault.cpp
  src/crypto.cpp
  src/frame_queue.cpp
  src/telemetry.cpp
  src/world_entity.cpp
  src/dfine.cpp
  src/tensorrt.cpp
  src/event_timing.cpp
  src/evidence_builder.cpp
  src/risk.cpp
  src/shadow.cpp
  src/store_forward.cpp
  src/pipeline.cpp
  src/sync.cpp
  src/core_sync_http.cpp
  src/evidence_attestation.cpp
  src/capture_quality_policy.cpp
  # 활성화된 임무의 비행경로(KMZ) 판독. PSDK 심볼 0개 — 이 파일은 바이트가 서명된
  # 봉투의 digest 와 짝인지만 판정하고, 그 바이트를 기체에 올리는 어댑터는 실기
  # 확인 뒤에 별도로 붙는다.
  src/mission_kmz.cpp
  # 원본 사진 자동 회수. PSDK 심볼 0개 — 실기 미확인은 IMediaSourcePort 뒤로
  # 전량 격리돼 있어 호스트 CI 에서 그대로 검증된다.
  src/jpeg_dimensions.cpp
  src/media_offload.cpp
  # ADR-KSI-021 §5 — 임무 실행 START 전 안전 판단 + §2/§8 arming/abort 파일
  # 프로토콜. PSDK 심볼 0개(파일 상단 주석 참조) — 어댑터는 실기 확인 후
  # edge/psdk-app/src/flight_execution/ 에서 별도로 붙는다.
  src/flight_execution.cpp
)
target_include_directories(ksi_edge_runtime PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
# ksi_edge_runtime는 std::mutex와 SQLite POSIX VFS를 사용한다. 정적 runtime library의
# 소비자(독립 contract tests와 PSDK app 모두)가 이 의존성을 최종 링크에서 받도록
# PUBLIC으로 둔다. PSDK app에만 우연히 pthread/dl을 직접 넣으면 standalone target
# 검증이 통과하지 않고, 정적 DPK 산출물의 실제 링크 조건도 숨겨진다.
find_package(Threads REQUIRED)
target_link_libraries(ksi_edge_runtime PUBLIC ksi_control_plane)
target_compile_options(ksi_edge_runtime PRIVATE
  -Wall -Wextra -Wpedantic -Werror
)

if(KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION)
  find_path(KSI_OPENSSL_INCLUDE_DIR openssl/evp.h
    HINTS "${KSI_OPENSSL_ROOT}/include" /usr/include /usr/local/include)
  find_file(KSI_OPENSSL_CRYPTO_STATIC_LIBRARY
    NAMES libcrypto.a
    HINTS
      "${KSI_OPENSSL_ROOT}/lib/aarch64-linux-gnu"
      "${KSI_OPENSSL_ROOT}/lib"
      "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu"
      "${CMAKE_SYSROOT}/usr/lib"
      /usr/lib/aarch64-linux-gnu
      /usr/lib
      /usr/local/lib)
  if(NOT KSI_OPENSSL_INCLUDE_DIR OR NOT KSI_OPENSSL_CRYPTO_STATIC_LIBRARY OR
     NOT KSI_OPENSSL_CRYPTO_STATIC_LIBRARY MATCHES "\\.a$")
    message(FATAL_ERROR
      "KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION=ON requires OpenSSL headers and static libcrypto.a")
  endif()
  target_compile_definitions(ksi_edge_runtime PUBLIC KSI_EDGE_HAVE_OPENSSL_ATTESTATION=1)
  target_include_directories(ksi_edge_runtime SYSTEM PRIVATE "${KSI_OPENSSL_INCLUDE_DIR}")
  target_link_libraries(ksi_edge_runtime PRIVATE "${KSI_OPENSSL_CRYPTO_STATIC_LIBRARY}")
else()
  target_compile_definitions(ksi_edge_runtime PUBLIC KSI_EDGE_HAVE_OPENSSL_ATTESTATION=0)
endif()

# 게이트 환경이 "SQLite 없이 조용히 통과"를 금지할 수 있게 하는 옵트인 스위치.
# 기본값 OFF — 개발 호스트는 지금 그대로 빌드된다(아래 else 블록의 근거 참조).
# 이 블록 바깥에 두는 이유: if(KSI_TARGET_MANIFOLD3) 안에 넣으면 Manifold 타깃
# 빌드에서 옵션 자체가 정의되지 않는다.
option(KSI_REQUIRE_SQLITE "SQLite 개발 헤더가 없으면 configure 단계에서 실패한다" OFF)

# DPK는 glibc 이외의 동적 의존성을 허용하지 않는다. FindSQLite3는 일부 배포판에서
# CMAKE_FIND_LIBRARY_SUFFIXES=.a 보다 pkg-config/공유 라이브러리를 우선할 수 있어,
# Manifold target에서는 정확히 정적 archive를 찾고 없으면 fail-closed 한다. 그렇지
# 않으면 WAL store-and-forward가 켜진 것처럼 보여도 .dpk가 libsqlite3.so에 의존한다.
if(KSI_TARGET_MANIFOLD3)
  find_path(KSI_EDGE_SQLITE_INCLUDE_DIR sqlite3.h)
  find_file(KSI_EDGE_SQLITE_STATIC_LIBRARY
    NAMES libsqlite3.a
    HINTS
      "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu"
      "${CMAKE_SYSROOT}/usr/lib"
      "/usr/lib/aarch64-linux-gnu"
      "/usr/lib"
      "/usr/local/lib"
  )
  if(NOT KSI_EDGE_SQLITE_INCLUDE_DIR OR NOT KSI_EDGE_SQLITE_STATIC_LIBRARY)
    message(FATAL_ERROR
      "KSI_TARGET_MANIFOLD3 requires sqlite3.h and a static libsqlite3.a; "
      "a DPK must not dynamically depend on libsqlite3.so")
  endif()
  target_compile_definitions(ksi_edge_runtime PRIVATE KSI_EDGE_HAVE_SQLITE=1)
  target_include_directories(ksi_edge_runtime SYSTEM PRIVATE "${KSI_EDGE_SQLITE_INCLUDE_DIR}")
  # PUBLIC은 static runtime library의 최종 소비자에게 archive를 전파한다. 아래의
  # pthread/dl은 이 call 뒤에 넣어 GNU ld의 단일 패스 해석 순서도 보장한다.
  target_link_libraries(ksi_edge_runtime PUBLIC "${KSI_EDGE_SQLITE_STATIC_LIBRARY}")
else()
  find_package(SQLite3 QUIET)
  if(SQLite3_FOUND)
    target_compile_definitions(ksi_edge_runtime PRIVATE KSI_EDGE_HAVE_SQLITE=1)
    target_link_libraries(ksi_edge_runtime PRIVATE SQLite::SQLite3)
  else()
    if(KSI_REQUIRE_SQLITE)
      message(FATAL_ERROR
        "KSI_REQUIRE_SQLITE=ON 인데 SQLite3 개발 헤더를 찾지 못했다 — "
        "이 빌드는 저장후전달 순서·WAL 복구 계약을 검증하지 못한다.")
    endif()
    # 개발 호스트가 SQLite 개발 헤더를 갖지 않아도 순수 안전 루프 검증은 가능하다.
    # 이 경우 store-and-forward는 kBackendUnavailable로 fail-closed이며, Docker/HIL
    # gate에서 SQLite WAL backend를 반드시 다시 빌드·실행한다.
    target_compile_definitions(ksi_edge_runtime PRIVATE KSI_EDGE_HAVE_SQLITE=0)
    message(STATUS "ksi_edge_runtime: SQLite3 development package unavailable; WAL backend disabled")
  endif()
endif()
# sqlite3.a와 runtime의 std::mutex가 요구하는 시스템 라이브러리는 archive 뒤에
# 위치해야 한다. 이 순서를 runtime target에 귀속해 standalone CTest와 DPK가 같은
# 실제 최종 링크 조건을 검증한다.
target_link_libraries(ksi_edge_runtime PUBLIC Threads::Threads ${CMAKE_DL_LIBS})

if(KSI_ENABLE_TENSORRT)
  find_path(KSI_TENSORRT_INCLUDE_DIR NvInfer.h
    HINTS "${KSI_TENSORRT_ROOT}/include" /usr/include /usr/local/include)
  find_path(KSI_TENSORRT_PARSER_INCLUDE_DIR NvOnnxParser.h
    HINTS "${KSI_TENSORRT_ROOT}/include" /usr/include /usr/local/include)
  find_path(KSI_CUDA_INCLUDE_DIR cuda_runtime_api.h
    HINTS "${KSI_TENSORRT_ROOT}/include" /usr/local/cuda/include /usr/include)
  find_library(KSI_TENSORRT_LIBRARY nvinfer
    HINTS "${KSI_TENSORRT_ROOT}/lib" "${KSI_TENSORRT_ROOT}/lib64" /usr/lib /usr/lib/aarch64-linux-gnu)
  find_library(KSI_TENSORRT_PARSER_LIBRARY nvonnxparser
    HINTS "${KSI_TENSORRT_ROOT}/lib" "${KSI_TENSORRT_ROOT}/lib64" /usr/lib /usr/lib/aarch64-linux-gnu)
  find_library(KSI_CUDART_LIBRARY cudart
    HINTS "${KSI_TENSORRT_ROOT}/lib" "${KSI_TENSORRT_ROOT}/lib64" /usr/local/cuda/lib64 /usr/lib)
  if(NOT KSI_TENSORRT_INCLUDE_DIR OR NOT KSI_TENSORRT_PARSER_INCLUDE_DIR OR
     NOT KSI_CUDA_INCLUDE_DIR OR NOT KSI_TENSORRT_LIBRARY OR
     NOT KSI_TENSORRT_PARSER_LIBRARY OR NOT KSI_CUDART_LIBRARY)
    message(FATAL_ERROR
      "KSI_ENABLE_TENSORRT=ON requires NvInfer.h, NvOnnxParser.h, cuda_runtime_api.h, nvinfer, nvonnxparser, and cudart")
  endif()
  target_compile_definitions(ksi_edge_runtime PRIVATE KSI_EDGE_HAVE_TENSORRT=1)
  target_include_directories(ksi_edge_runtime SYSTEM PRIVATE
    "${KSI_TENSORRT_INCLUDE_DIR}" "${KSI_TENSORRT_PARSER_INCLUDE_DIR}" "${KSI_CUDA_INCLUDE_DIR}")
  target_link_libraries(ksi_edge_runtime PRIVATE
    "${KSI_TENSORRT_LIBRARY}" "${KSI_TENSORRT_PARSER_LIBRARY}" "${KSI_CUDART_LIBRARY}")
else()
  target_compile_definitions(ksi_edge_runtime PRIVATE KSI_EDGE_HAVE_TENSORRT=0)
endif()

if(KSI_ENABLE_CURL_EDGE_TRANSPORT)
  set(CURL_USE_STATIC_LIBS TRUE)
  find_package(CURL REQUIRED)
  if(NOT CURL_LIBRARY MATCHES "\\.a$")
    message(FATAL_ERROR
      "KSI_ENABLE_CURL_EDGE_TRANSPORT=ON requires a static libcurl (.a); DPK cannot depend on a shared libcurl")
  endif()
  if(NOT KSI_CURL_STATIC_EXTRA_LIBRARIES)
    message(FATAL_ERROR
      "KSI_ENABLE_CURL_EDGE_TRANSPORT=ON requires KSI_CURL_STATIC_EXTRA_LIBRARIES: reviewed absolute .a dependencies for libcurl (the distro libcurl.a alone is not a DPK-safe bundle)")
  endif()
  foreach(_curl_static_dependency IN LISTS KSI_CURL_STATIC_EXTRA_LIBRARIES)
    if(NOT IS_ABSOLUTE "${_curl_static_dependency}" OR
       NOT EXISTS "${_curl_static_dependency}" OR
       NOT "${_curl_static_dependency}" MATCHES "\\.a$")
      message(FATAL_ERROR
        "KSI_CURL_STATIC_EXTRA_LIBRARIES entry must be an existing absolute .a archive: ${_curl_static_dependency}")
    endif()
  endforeach()
  target_sources(ksi_edge_runtime PRIVATE src/curl_https_executor.cpp)
  target_compile_definitions(ksi_edge_runtime PUBLIC KSI_EDGE_HAVE_CURL_TRANSPORT=1)
  # Do not link CURL::libcurl here: FindCURL may attach shared transitive
  # dependencies even when CURL_LIBRARY itself ends in .a.  The reviewed
  # archive list above is the only non-glibc TLS dependency surface.
  target_include_directories(ksi_edge_runtime SYSTEM PRIVATE ${CURL_INCLUDE_DIRS})
  target_link_libraries(ksi_edge_runtime PRIVATE "${CURL_LIBRARY}" ${KSI_CURL_STATIC_EXTRA_LIBRARIES})
else()
  target_compile_definitions(ksi_edge_runtime PUBLIC KSI_EDGE_HAVE_CURL_TRANSPORT=0)
endif()

# ADR-KSI-021 §5[3]/§8 — 현장 arming/abort CLI. Python 컴패니언(3.8.10) 대신
# C++ 인 이유는 두 파일 상단 주석 참조. 실배치 도구라 KSI_BUILD_TESTS 와
# 무관하게 항상 빌드한다(테스트만 그 옵션 아래 게이팅한다).
add_executable(ksi_edge_flight_arm tools/ksi_edge_flight_arm.cpp)
target_link_libraries(ksi_edge_flight_arm PRIVATE ksi_edge_runtime)
target_compile_options(ksi_edge_flight_arm PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(ksi_edge_flight_abort tools/ksi_edge_flight_abort.cpp)
target_link_libraries(ksi_edge_flight_abort PRIVATE ksi_edge_runtime)
target_compile_options(ksi_edge_flight_abort PRIVATE -Wall -Wextra -Wpedantic -Werror)

option(KSI_BUILD_TESTS "control plane 계약 테스트를 빌드한다" ON)
if(KSI_BUILD_TESTS)
  enable_testing()
  # 외부 테스트 프레임워크(gtest 등)를 쓰지 않는다 — 네트워크 fetch 없이 CI에서
  # 그대로 돌아야 하고, 계약 검증에 필요한 것은 단언과 종료코드뿐이다.
  add_executable(control_plane_tests tests/control_plane_tests.cpp)
  target_link_libraries(control_plane_tests PRIVATE ksi_control_plane)
  target_compile_options(control_plane_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME control_plane_contract COMMAND control_plane_tests)

  # Python Intelligence Plane과 공유하는 conformance 벡터를 C++ 쪽에서도 실행한다.
  # 벡터 헤더는 contracts/conformance/*.json 에서 생성된다(tools/ 생성기).
  add_executable(conformance_tests tests/conformance_tests.cpp)
  target_link_libraries(conformance_tests PRIVATE ksi_control_plane)
  target_include_directories(conformance_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
  target_compile_options(conformance_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME action_intent_conformance COMMAND conformance_tests)

  add_executable(edge_runtime_tests tests/edge_runtime_tests.cpp)
  target_link_libraries(edge_runtime_tests PRIVATE ksi_edge_runtime)
  target_compile_options(edge_runtime_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME edge_runtime_contract COMMAND edge_runtime_tests)
  add_executable(capture_quality_policy_tests tests/capture_quality_policy_tests.cpp)
  target_link_libraries(capture_quality_policy_tests PRIVATE ksi_edge_runtime)
  target_compile_options(capture_quality_policy_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME capture_quality_policy_contract COMMAND capture_quality_policy_tests)

  # This offline companion executes the same optional TensorRT adapter as the
  # DPK and writes semantic results for the Python ONNX oracle.  It is built
  # with contract tests, never installed into the production DPK.
  add_executable(tensorrt_differential_runner tools/tensorrt_differential_runner.cpp)
  target_link_libraries(tensorrt_differential_runner PRIVATE ksi_edge_runtime)
  target_compile_options(tensorrt_differential_runner PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME tensorrt_differential_runner_contract
           COMMAND tensorrt_differential_runner --version)

  add_test(NAME ksi_edge_flight_arm_contract COMMAND ksi_edge_flight_arm --version)
  add_test(NAME ksi_edge_flight_abort_contract COMMAND ksi_edge_flight_abort --version)
endif()

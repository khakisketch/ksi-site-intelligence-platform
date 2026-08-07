# KSI Edge — Manifold native control plane (Stage C-3 골격)
#
# 이 빌드는 **호스트에서 그대로 빌드·테스트되는** 순수 C++17 계약 골격이다.
# DJI PSDK·CUDA·TensorRT 의존은 아직 없다 — 실기/HIL 증거 전까지 비행명령 경로를
# 활성화하지 않는다는 Stage C 범위 제약(승인된 금지 항목)에 따른 것이다.
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
endif()

# KSI Edge — Manifold native control plane (Stage C-3 골격)
#
# 이 빌드는 **호스트에서 그대로 빌드·테스트되는** 순수 C++17 계약 골격이다.
# DJI PSDK·CUDA·TensorRT 의존은 아직 없다 — 실기/HIL 증거 전까지 비행명령 경로를
# 활성화하지 않는다는 Stage C 범위 제약(승인된 금지 항목)에 따른 것이다.
# 실제 Manifold 3 타깃 툴체인은 docs/edge/MANIFOLD3_TOOLCHAIN.md 참조.

cmake_minimum_required(VERSION 3.22)
project(ksi_manifold_runtime LANGUAGES CXX VERSION 0.0.1)

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
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
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

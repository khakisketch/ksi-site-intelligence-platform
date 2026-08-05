# Manifold 3 타깃 정책 파일 (크로스컴파일 툴체인 파일이 아니다)
#
# 실기 실측(2026-08-03 HIL 세션): gcc 9.4.0 / cmake 3.16.3 / glibc 2.31 (Ubuntu 20.04.6)
# 개발 PC와 CI 컨테이너(edge/docker/manifold3-build.Dockerfile)가 이미 aarch64이므로,
# 기본 경로는 크로스컴파일이 아니라 **네이티브 빌드**다. 이 파일이 하는 일은 두 가지뿐이다:
#   1) 타깃 ABI 정책(정적 링크·RPATH·경화 플래그)을 단언한다.
#   2) 빌드 환경이 실기와 드리프트했으면 configure 단계에서 즉시 실패시킨다.
#
# 이 파일이 하지 않는 일: PSDK 탐색(edge/psdk-app이 자체 처리), 소스/테스트 목록 정의.
# 툴체인 파일은 여러 번 재실행되므로 부작용을 넣으면 디버깅이 어려워진다.
#
# 사용법:
#   cmake -S edge/manifold-runtime -B build-manifold3 \
#         -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
#         -DKSI_TARGET_MANIFOLD3=ON

# --- (A) 크로스 여부 — 기본은 "크로스가 아님" ---------------------------------
# KSI_MANIFOLD_SYSROOT가 비어 있으면 CMAKE_SYSTEM_NAME을 설정하지 않는다.
# 설정하면 CMAKE_CROSSCOMPILING=TRUE가 되어 try_run/ctest 실행이 막히고, 컨테이너에서
# ctest가 그대로 도는 이 설계의 핵심 이득을 잃는다. 실제 크로스 sysroot가 필요해지면
# (예: x86-64 CI 러너에서 arm64 sysroot로 링크만 검증) 이 캐시 변수를 채워서 켠다.
set(KSI_MANIFOLD_SYSROOT "" CACHE PATH "Manifold 3 크로스 sysroot 경로 (비우면 네이티브 빌드)")

if(KSI_MANIFOLD_SYSROOT)
  set(CMAKE_SYSTEM_NAME Linux)
  set(CMAKE_SYSTEM_PROCESSOR aarch64)
  set(CMAKE_SYSROOT "${KSI_MANIFOLD_SYSROOT}")
  set(CMAKE_FIND_ROOT_PATH "${KSI_MANIFOLD_SYSROOT}")
  set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
  set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
  set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
  set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
endif()

# --- (B) 컴파일러 신원 단언 (드리프트 게이트) -----------------------------------
option(KSI_ALLOW_TOOLCHAIN_DRIFT "실기와 다른 gcc major로 타깃 빌드를 허용한다(의도적 우회만)" OFF)
set(KSI_MANIFOLD_EXPECTED_GCC_MAJOR "9" CACHE STRING "실기 실측 gcc major 버전")
set(KSI_MANIFOLD_TOOLCHAIN_PREFIX "" CACHE STRING "크로스 툴체인 접두사(예: aarch64-linux-gnu-), 비우면 네이티브 gcc/g++")

if(KSI_MANIFOLD_TOOLCHAIN_PREFIX)
  set(CMAKE_C_COMPILER "${KSI_MANIFOLD_TOOLCHAIN_PREFIX}gcc")
  set(CMAKE_CXX_COMPILER "${KSI_MANIFOLD_TOOLCHAIN_PREFIX}g++")
endif()

# --- (C) 정적 링크 강제 (DPK "동적 라이브러리 금지" 제약의 코드화) ----------------
# 완전 -static은 쓰지 않는다 — glibc NSS/dlopen이 깨지고 PSDK 내부 동작이 무엇을
# dlopen하는지 알려진 바 없다. 정책은 "glibc 계열만 동적, 그 외 서드파티는 .a,
# libstdc++/libgcc는 정적"이다.
option(KSI_TARGET_MANIFOLD3 "Manifold 3 타깃 빌드 정책(정적 링크·RPATH 등)을 켠다" OFF)

if(KSI_TARGET_MANIFOLD3)
  set(BUILD_SHARED_LIBS OFF)
  set(CMAKE_FIND_LIBRARY_SUFFIXES ".a")
  set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -static-libstdc++ -static-libgcc")
  set(CMAKE_POSITION_INDEPENDENT_CODE ON)

  # --- (D) 아키텍처 튜닝 — 기본은 건드리지 않는다 ---
  # Orin은 armv8.2-A이지만 gcc 9.4가 -mcpu=cortex-a78ae를 아는지 실측 전이고,
  # 측정 없는 최적화 플래그는 이 저장소의 증거 규율에 어긋난다. 벤치마크 확보 후 채운다.
  set(KSI_MANIFOLD_ARCH_FLAGS "" CACHE STRING "실측 벤치마크 확보 후에만 채울 것(예: -march=armv8.2-a)")
  if(KSI_MANIFOLD_ARCH_FLAGS)
    add_compile_options(${KSI_MANIFOLD_ARCH_FLAGS})
  endif()

  # --- (E) 진단·경화 ---
  if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "빌드 타입" FORCE)
  endif()
  if(CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    add_compile_definitions(_FORTIFY_SOURCE=2 _GLIBCXX_ASSERTIONS)
  endif()
  set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

  # --- (F) 설치·스테이징 (DPK "상대경로만" 제약과 정렬) ---
  if(NOT CMAKE_INSTALL_PREFIX OR CMAKE_INSTALL_PREFIX STREQUAL "/usr/local")
    set(CMAKE_INSTALL_PREFIX "${CMAKE_BINARY_DIR}/stage" CACHE PATH "" FORCE)
  endif()
  set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib")
  set(CMAKE_BUILD_WITH_INSTALL_RPATH ON)
endif()

# --- 컴파일러 신원 검사는 project() 이후 project-level에서 수행해야 CMAKE_CXX_COMPILER_VERSION이
# 채워진다. 이 툴체인 파일은 project() 이전에 로드되므로, 실제 단언은
# edge/manifold-runtime/CMakeLists.txt 등 호출부가 project() 직후
# check_manifold3_toolchain_drift()를 호출해 수행한다(아래 함수 정의만 여기 둔다).
function(ksi_check_manifold3_toolchain_drift)
  if(NOT KSI_TARGET_MANIFOLD3)
    return()
  endif()
  if(KSI_ALLOW_TOOLCHAIN_DRIFT)
    return()
  endif()
  if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    message(FATAL_ERROR
      "Manifold 3 타깃 정책(KSI_TARGET_MANIFOLD3=ON)은 GNU gcc/g++를 전제한다 — "
      "감지된 컴파일러: ${CMAKE_CXX_COMPILER_ID}. 의도적 우회는 -DKSI_ALLOW_TOOLCHAIN_DRIFT=ON.")
  endif()
  string(REPLACE "." ";" _ver_list "${CMAKE_CXX_COMPILER_VERSION}")
  list(GET _ver_list 0 _major)
  if(NOT _major STREQUAL "${KSI_MANIFOLD_EXPECTED_GCC_MAJOR}")
    message(FATAL_ERROR
      "Manifold 3 실기는 gcc ${KSI_MANIFOLD_EXPECTED_GCC_MAJOR}.x인데 "
      "이 빌드는 gcc ${CMAKE_CXX_COMPILER_VERSION}로 구성됐다 — 실기와 다른 컴파일러로 "
      "타깃 산출물을 만드는 것을 차단한다(ABI/경고 드리프트 방지). "
      "의도적이면 -DKSI_ALLOW_TOOLCHAIN_DRIFT=ON.")
  endif()
endfunction()

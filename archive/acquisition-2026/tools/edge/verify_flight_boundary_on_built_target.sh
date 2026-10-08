#!/usr/bin/env bash
# 실제로 빌드된 ELF에 check_shadow_flight_boundary.py 를 돌린다 — "언젠가 손으로
# 한 번 돌려본다"가 아니라 재현 가능한 절차로 고정한다.
#
# 배경: goal manifold3-edge-shadow-vertical-slice 의 완료기준은 "PSDK 앱이 DJI
# Flight Control 을 직접 호출하지 않음(소스 스캔 + ELF 검증)"이다. 소스 스캔은
# tests/contract/test_shadow_flight_boundary_gate.py 가 매 CI 실행마다 고정하지만,
# ELF 검증(nm/objdump 로 실제 링크된 바이너리를 보는 것)은 실제 빌드 산출물이
# 있어야만 뜻이 있고, CI(edge-psdk-tap)는 지금 LOGIC_TESTS_ONLY=ON — 라이선스가
# 있는 PSDK vendor tree 를 fetch 하지 않는 모드라 검사할 실물 ELF 자체가 없다
# (2026-08-14 코드감사 확인). PSDK 를 CI 에 상시 fetch 하게 만드는 것은 이
# 스크립트의 권한 밖 결정(라이선스 승인 범위 변경)이라 여기서 하지 않는다.
#
# 이 스크립트는 그 공백을 메우는 최소한이다: PSDK 를 이미 fetch 해둔 로컬(또는
# self-hosted HIL) 환경에서, 실제로 빌드된 타깃 ELF를 찾아 strict/non-strict
# 두 게이트를 모두 돌리고 결과를 남긴다. HIL 세션 §8 전후로 매번 수동 실행하는
# 것을 이 한 줄로 대신한다.
#
# Usage:
#   tools/edge/verify_flight_boundary_on_built_target.sh [빌드 디렉터리...]
#   (인자 없으면 edge/psdk-tap/build-manifold3, edge/psdk-app/build-manifold3
#   를 이 순서로 찾는다 — 실기 툴체인(gcc 9.x)으로 만든 빌드만 대상이다.)
#
# ADR-KSI-021(2026-08-16) — flight-execution allowlist manifest 가 환경변수로
# 지정되면 기본 S0 결과는 진단용으로 먼저 인쇄하고, 같은 매니페스트를 적용한
# non-strict/strict 두 결과를 실제 판정으로 사용한다. 승인된 S1 심볼이 들어간
# 바이너리는 S0에서 실패하는 것이 정상이라 그 진단 결과를 전체 실패로 세면 안
# 된다. allowlist가 없으면 지금까지와 동일하게 S0 두 게이트가 판정한다.
#   KSI_FLIGHT_EXECUTION_ALLOWLIST=edge/flight-execution-allowlist.v1.json \
#     tools/edge/verify_flight_boundary_on_built_target.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CHECKER="tools/edge/check_shadow_flight_boundary.py"
SOURCE_ROOTS=(
  "edge/psdk-app/src"
  "edge/psdk-tap/src"
  "edge/manifold-runtime/src"
  "edge/manifold-runtime/include"
)

# 검사 대상: 인자로 빌드 디렉터리를 받거나, 알려진 실기-툴체인 빌드 자리를 찾는다.
declare -a BUILD_DIRS
if [ "$#" -gt 0 ]; then
  BUILD_DIRS=("$@")
else
  BUILD_DIRS=("edge/psdk-tap/build-manifold3" "edge/psdk-app/build-manifold3")
fi

found_any=0
failures=0

# strict 게이트(--require-zero-defined-symbols)의 결과는 실제로 검사해야 한다 —
# 예전 버전은 이 결과를 그냥 버렸다("차단 아님" 을 exit code 와 무관하게 항상
# 찍음). 그런데 strict 게이트는 PSDK 3.16.0 의 dji_error.c.o 가 항상 남기는
# DjiFlightController_GetDjiErrorCode 정의 하나 때문에 allowlist 없이 돌리면
# **항상** 비영(non-zero)으로 끝난다(check_shadow_flight_boundary.py 모듈
# docstring 49-55행 참조) — 그래서 "strict 비영이면 무조건 실패" 로 바꾸면 이
# 알려진 벤더 잡음 때문에 항상 실패하는 게이트가 된다. 대신 그 잡음 하나만
# knownVendorDefinitions 로 선언한 최소 매니페스트(stage=C2-S0, entries=[] —
# 링크·소스 스캔 결과에는 영향을 주지 않는다)를 strict 게이트에 넘긴다. 이러면
# 벤더 잡음만 있을 때는 정상적으로 통과하고, 그 잡음 밖의 **새로 정의된**
# Flight Control 심볼이 있을 때만 비영으로 끝난다 — 그 경우에만 실패로 잡는다.
KNOWN_VENDOR_NOISE_MANIFEST="$(mktemp)"
trap 'rm -f "$KNOWN_VENDOR_NOISE_MANIFEST"' EXIT
cat >"$KNOWN_VENDOR_NOISE_MANIFEST" <<'JSON'
{
  "stage": "C2-S0",
  "entries": [],
  "knownVendorDefinitions": ["DjiFlightController_GetDjiErrorCode"]
}
JSON

for build_dir in "${BUILD_DIRS[@]}"; do
  if [ ! -d "$build_dir" ]; then
    echo "건너뜀 — 없음: $build_dir" >&2
    continue
  fi
  # ELF 매직 바이트로 실행파일을 찾는다(확장자가 없다) — 테스트 바이너리도
  # 같은 링크 규칙을 타므로 함께 검사한다(부속 실행파일에 우회로가 없는지).
  while IFS= read -r -d '' candidate; do
    found_any=1
    echo "=== $candidate ==="
    if [ -n "${KSI_FLIGHT_EXECUTION_ALLOWLIST:-}" ]; then
      echo "  --- 기본 S0 진단(판정 제외) ---"
      python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}" || true
      python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}" \
        --require-zero-defined-symbols \
        --allow-mission-execution "$KNOWN_VENDOR_NOISE_MANIFEST" || true
      echo "  --- allowlist 적용 판정 (${KSI_FLIGHT_EXECUTION_ALLOWLIST}) ---"
      if python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}" \
        --allow-mission-execution "$KSI_FLIGHT_EXECUTION_ALLOWLIST"; then
        echo "  (allowlist 적용 게이트 통과)"
      else
        failures=1
      fi
      if python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}" \
        --require-zero-defined-symbols \
        --allow-mission-execution "$KSI_FLIGHT_EXECUTION_ALLOWLIST"; then
        echo "  (allowlist strict 게이트 통과 — 허가·벤더 잡음 외 motion 심볼 없음)"
      else
        echo "  ✗ allowlist strict 안전경계 게이트 실패" >&2
        failures=1
      fi
    else
      if python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}"; then
        echo "  (기본 게이트 통과 — 직접 호출/헤더 경계 확인됨, allowlist 미적용)"
      else
        failures=1
      fi
      # strict 게이트: 알려진 벤더 잡음만 걸러낸다. 그래도 비영이면 새
      # 정의/직접호출이 있다는 뜻이므로 진짜 실패로 잡는다.
      if python3 "$CHECKER" "$candidate" "${SOURCE_ROOTS[@]}" \
        --require-zero-defined-symbols \
        --allow-mission-execution "$KNOWN_VENDOR_NOISE_MANIFEST"; then
        echo "  (strict 게이트 통과 — 알려진 벤더 잡음 외 정의된/직접호출된 Flight Control 심볼 없음)"
      else
        echo "  ✗ strict 안전경계 게이트 실패 — 알려진 벤더 잡음 밖의 Flight Control 심볼이 ELF 에 있다(위 출력 참조)" >&2
        failures=1
      fi
    fi
    echo
  done < <(find "$build_dir" -maxdepth 1 -type f -executable -print0)
done

if [ "$found_any" -eq 0 ]; then
  echo "검사할 실행파일을 못 찾았다 — 실기 툴체인(gcc 9.x)으로 먼저 빌드하라:" >&2
  echo "  cmake -S edge/psdk-tap -B edge/psdk-tap/build-manifold3 \\" >&2
  echo "    -DCMAKE_TOOLCHAIN_FILE=\$(pwd)/cmake/toolchain-manifold3.cmake -DKSI_TARGET_MANIFOLD3=ON" >&2
  echo "  (psdk-app 는 이 호스트가 실기와 다른 gcc 를 쓰면 드리프트 게이트가 막는다 —" >&2
  echo "   edge/docker/manifold3-build.Dockerfile 컨테이너(CI edge-manifold-target 과 동일 경로)가 필요하다)" >&2
  exit 1
fi

if [ "$failures" -ne 0 ]; then
  echo "✗ 안전경계 게이트가 실패한 바이너리가 있다(기본 게이트 또는 strict 게이트) — 위 출력 참조" >&2
  exit 1
fi

if [ -n "${KSI_FLIGHT_EXECUTION_ALLOWLIST:-}" ]; then
  echo "✓ 검사한 모든 바이너리가 allowlist non-strict·strict 안전경계 게이트를 통과했다"
else
  echo "✓ 검사한 모든 바이너리가 기본·strict 안전경계 게이트를 통과했다"
fi

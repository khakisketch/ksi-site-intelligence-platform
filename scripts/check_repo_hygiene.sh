#!/usr/bin/env bash
# 저장소 위생 검사 (대표자 지정 P2 후속, 2026-07-27 CI 오염 재발 방지).
#
# 배경: gitignore 패턴 `models/` 가 docs/models/ 계보 SSOT 를 삼키고, git add -A 가
# 로컬 CMake 빌드 캐시·__pycache__ 를 커밋해 CI 가 깨졌던 실사례(1a6c013 에서 복구).
# 이 검사는 "로컬에서만 green" 클래스의 오염을 clean checkout 에서 기계적으로 잡는다.
set -euo pipefail

fail=0

# 1) 빌드 캐시·바이트코드가 추적되면 안 된다 (로컬 절대경로가 CI 를 오염시킨다)
banned=$(git ls-files | grep -E '(^|/)(CMakeCache\.txt|CMakeFiles/)|(^|/)build/|(^|/)__pycache__/|\.pyc$' || true)
if [ -n "$banned" ]; then
  echo "✗ 빌드 캐시/바이트코드가 git 에 추적되고 있다:"
  echo "$banned" | head -20
  fail=1
fi

# 2) 모델 계보 SSOT 는 반드시 추적돼야 한다 (gitignore 패턴 오염 감지)
for f in docs/models/MODEL_REGISTRY.yaml docs/models/MODEL_DECISIONS.yaml; do
  if ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "✗ 계보 SSOT 가 git 추적에서 빠졌다: $f (gitignore 패턴 확인)"
    fail=1
  fi
done

# 3) 모델 가중치·ONNX 산출물은 추적되면 안 된다 (계보만 추적, 실물은 fetch)
weights=$(git ls-files | grep -E '\.(safetensors|onnx|pth|engine)$' || true)
if [ -n "$weights" ]; then
  echo "✗ 모델 가중치/ONNX 산출물이 git 에 추적되고 있다:"
  echo "$weights"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "✓ repo hygiene OK (빌드캐시/pyc 미추적 · 계보 SSOT 추적 · 가중치 미추적)"

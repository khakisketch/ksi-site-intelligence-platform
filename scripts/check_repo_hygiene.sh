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

# 4) DJI PSDK 생성 헤더(비밀 포함 가능)·.secrets/ 하위는 추적되면 안 된다
#    (2026-08-03 Manifold3 HIL 세션, ADR-KSI-009 — App Key는 configure_file로만 생성한다)
#    -i: 대소문자 무관하게 잡는다. 현재 벤더 파일명은 소문자뿐이라 활성 사각지대는
#    없지만, 파일명 변형(DJI_SDK_APP_INFO.H)이 우회로가 되지 않도록 선제 차단한다.
secret_paths=$(git ls-files | grep -Ei '(^|/)dji_sdk_app_info\.h$|(^|/)\.secrets/' || true)
if [ -n "$secret_paths" ]; then
  echo "✗ DJI PSDK 생성 헤더 또는 .secrets/ 하위가 git 에 추적되고 있다:"
  echo "$secret_paths"
  fail=1
fi

# 5) 추적된 파일에 실제 DJI App Key/License 리터럴이 박혀 있으면 안 된다
#    (플레이스홀더 "your_app_key" 등과 빈 문자열 ""는 허용 — 실값만 차단)
#
#    이 규칙은 grep -P(PCRE)에 의존한다. 과거 이 저장소는 러너에 rg가 없어 가드가
#    조용한 no-op이 된 사고를 겪었으므로(감사 #29), 도구 부재를 통과로 위장하지
#    않고 명시적으로 실패시킨다.
if ! echo "x" | grep -qP 'x' 2>/dev/null; then
  echo "✗ grep 이 -P(PCRE)를 지원하지 않는다 — App Key 리터럴 스캔을 수행할 수 없다."
  echo "  검사 미수행을 통과로 처리하지 않는다(GNU grep 또는 pcregrep 설치 필요)."
  fail=1
else
  # 정규식 설계 근거(2026-08-04 감사 지적 반영):
  #  - `[^"]` 로 시작해 최소 1자 이상을 요구 → 빈 문자열 ""는 오탐하지 않는다.
  #  - `(?!your_[a-z_]*")` : 플레이스홀더는 your_로 시작해 곧바로 닫히는 형태
  #    (your_app_key")만 면제한다. 실값이 우연히 your_ 로 시작해도(your_company_key…)
  #    닫는 따옴표 전에 다른 문자가 있으면 잡힌다 — zero-width lookahead 우회 차단.
  #  - 멀티라인 #define(백슬래시 개행)은 grep이 라인 단위라 원리상 못 잡는다.
  #    별도 규칙 5b로 보완한다.
  leaked_creds=$(git ls-files -z \
    | xargs -0 grep -lP '#define[ \t]+USER_APP_(KEY|LICENSE)[ \t]+"(?!your_[a-z_]*")[^"]' 2>/dev/null || true)
  if [ -n "$leaked_creds" ]; then
    echo "✗ DJI App Key/License 실값이 추적 파일에 박혀 있다(플레이스홀더가 아님):"
    echo "$leaked_creds"
    fail=1
  fi

  # 5b) 백슬래시 개행으로 이어진 #define 은 라인 단위 grep 이 값을 못 본다.
  #     값 자체를 판정할 수 없으므로 "이 형태는 쓰지 않는다"를 규칙으로 강제한다.
  multiline_define=$(git ls-files -z \
    | xargs -0 grep -lP '#define[ \t]+USER_APP_(KEY|LICENSE)[ \t]+.*\\$' 2>/dev/null || true)
  if [ -n "$multiline_define" ]; then
    echo "✗ USER_APP_KEY/LICENSE 가 여러 줄에 걸친 #define 으로 작성됐다(값 검사 불가):"
    echo "$multiline_define"
    echo "  한 줄 #define 으로 바꿀 것 — 이 형태는 규칙5의 실값 스캔을 우회한다."
    fail=1
  fi
fi

# 6) DPK 패키지(.dpk)는 추적되면 안 된다 — App Key가 컴파일돼 들어간 배포 산출물이다
#    -i: .DPK 등 대문자 확장자도 잡는다(대소문자 구분은 우회로가 된다).
dpk_files=$(git ls-files | grep -Ei '\.dpk$' || true)
if [ -n "$dpk_files" ]; then
  echo "✗ DPK 패키지가 git 에 추적되고 있다(App Key 내장 산출물 — 커밋 금지):"
  echo "$dpk_files"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "✓ repo hygiene OK (빌드캐시/pyc 미추적 · 계보 SSOT 추적 · 가중치 미추적 · DJI 비밀/DPK 미추적)"

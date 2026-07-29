#!/usr/bin/env bash
# 참고 레포(references/repos)에 대한 runtime 의존을 4중으로 차단한다.
#  1) import/from/require/include 구문이 참고 레포 모듈·경로를 향하는 경우
#  2) pyproject/package.json/CMake 매니페스트의 path dependency가 references를 향하는 경우
#  3) 코드 트리 안의 symlink가 references/ 내부를 가리키는 경우
#  4) 서브모듈이 핀에서 이탈(+)했거나 worktree가 dirty한 경우
# provenance 주석("upstream Scout projection.py @42ccc0db" 등)은 import 구문이 아니므로 통과한다.
set -euo pipefail

# 게이트 자체의 전제 검증(감사 #29) — rg 미설치면 아래 if 조건이 조용히 실패해
# "검사 안 함"이 "위반 없음"으로 위장된다(가짜 green). 도구 부재는 즉시 실패다.
command -v rg >/dev/null 2>&1 || {
  echo "FAIL(0): ripgrep(rg) 미설치 — 게이트를 실행할 수 없다(검사 미수행 ≠ 통과)" >&2
  exit 1
}

CODE_DIRS=(apps services edge workers packages tests)
EXISTING_DIRS=()
for d in "${CODE_DIRS[@]}"; do [[ -d "$d" ]] && EXISTING_DIRS+=("$d"); done

fail=0

# 1) import 구문 검사 (Python/TS/JS/C++)
IMPORT_PATTERN='^[[:space:]]*(import[[:space:]]+ksi_(platform|terra|scout)|from[[:space:]]+ksi_(platform|terra|scout)[.[:space:]]|import[[:space:]].*["'\''][^"'\'']*references/repos|from[[:space:]]+["'\''][^"'\'']*references/repos|require\([^)]*references/repos|require\([^)]*ksi-(platform|terra|scout)|#include[[:space:]]+["<][^">]*references/repos)'
set +e
rg -n --hidden --glob '!.git/**' "$IMPORT_PATTERN" "${EXISTING_DIRS[@]}"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  echo "FAIL(1): 참고 레포를 향한 import/require/include 구문 발견" >&2
  fail=1
elif [[ $rc -ge 2 ]]; then
  echo "FAIL(1): rg 실행 오류(rc=$rc) — 검사 미수행을 통과로 위장하지 않는다" >&2
  fail=1
fi

# 2) 매니페스트 path dependency 검사 (의존 선언 문맥만 — workspace exclude 목록은 정당)
DEP_PATTERN='(path[[:space:]]*=[[:space:]]*["'\''][^"'\'']*references/|file:[^"'\'']*references/|["'\''][^"'\'']*references/repos[^"'\'']*["'\''][[:space:]]*:|add_subdirectory[[:space:]]*\([^)]*references|include[[:space:]]*\([^)]*references|-e[[:space:]]+[^[:space:]]*references/)'
set +e
rg -n --hidden --glob '!.git/**' \
  --glob '{pyproject.toml,package.json,CMakeLists.txt,*.cmake,requirements*.txt,setup.py,setup.cfg}' \
  "$DEP_PATTERN" "${EXISTING_DIRS[@]}" pyproject.toml
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  echo "FAIL(2): 매니페스트 의존 선언이 references/ 경로를 참조" >&2
  fail=1
elif [[ $rc -ge 2 ]]; then
  echo "FAIL(2): rg 실행 오류(rc=$rc) — 검사 미수행을 통과로 위장하지 않는다" >&2
  fail=1
fi

# 3) references 내부를 가리키는 symlink 검사
while IFS= read -r link; do
  target=$(readlink -f "$link" || true)
  if [[ "$target" == *"/references/repos/"* ]]; then
    echo "FAIL(3): symlink가 references를 가리킴: $link -> $target" >&2
    fail=1
  fi
done < <(find "${EXISTING_DIRS[@]}" -type l 2>/dev/null)

# 4) 서브모듈 핀 이탈(+)·충돌(U)·dirty worktree 검사 (초기화 안 된 '-'는 허용: CI는 클론 없이 검사)
if [[ -f .gitmodules ]]; then
  # process substitution 의 실패는 while 종료 상태로 전파되지 않는다(재검토 P2-D3
  # — `|| { }` 는 죽은 가드였다) — 종료코드를 스트림 마지막 줄에 실어 명시 검사한다.
  while IFS= read -r line; do
    if [[ "$line" == EXIT:* ]]; then
      if [[ "$line" != "EXIT:0" ]]; then
        echo "FAIL(4): git submodule status 실패(${line#EXIT:}) — 검사 미수행 ≠ 통과" >&2
        fail=1
      fi
      continue
    fi
    prefix="${line:0:1}"
    if [[ "$prefix" == "+" || "$prefix" == "U" ]]; then
      echo "FAIL(4): 서브모듈이 기록된 커밋에서 이탈: $line" >&2
      fail=1
    fi
  done < <(git submodule status; echo "EXIT:$?")
  if ! porcelain=$(git status --porcelain -- references/repos); then
    echo "FAIL(4): git status 실행 실패 — 검사 미수행을 통과로 위장하지 않는다" >&2
    fail=1
  elif [[ -n "$porcelain" ]]; then
    echo "FAIL(4): 서브모듈 worktree dirty:" >&2
    echo "$porcelain" >&2
    fail=1
  fi
fi

if [[ $fail -ne 0 ]]; then
  echo "Reference dependency guard FAILED." >&2
  exit 1
fi
echo "No direct reference imports detected."

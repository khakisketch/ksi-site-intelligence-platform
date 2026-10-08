#!/usr/bin/env bash
# edge/third_party/PSDK_LOCK.yaml 의 핀과 실제로 받아진 PSDK 트리(있다면)의 일치를
# 검증한다. scripts/verify_reference_pins.sh(서브모듈 gitlink 검증)의 형제이지만
# 다르게 동작한다 — PSDK는 서브모듈이 아니라 tools/edge/fetch_psdk.py로 받는
# 선택적 fetch 대상(gitignored)이라, "미설치"는 실패가 아니라 통과다(CI가 PSDK
# 접근권을 아직 갖추지 않은 상태에서도 이 게이트가 돌아야 하므로).
#
# 검증 대상:
#   1) PSDK_LOCK.yaml 자체가 존재하고 파싱 가능한가(계보 SSOT가 깨지지 않았는가)
#   2) edge/third_party/psdk/ 가 있으면: HEAD == pinned_commit
#   3) 있으면: verified_files 의 sha256 전부 일치(핀 이탈 감지)
set -euo pipefail

LOCK_FILE="edge/third_party/PSDK_LOCK.yaml"
PSDK_DIR="edge/third_party/psdk"

if [[ ! -f "$LOCK_FILE" ]]; then
  echo "FAIL: $LOCK_FILE 없음 — PSDK 핀 계보 SSOT가 사라졌다"
  exit 1
fi

python3 - "$LOCK_FILE" "$PSDK_DIR" <<'PY'
import subprocess
import sys
from pathlib import Path

# heredoc 으로 stdin 실행돼 __file__ 이 없다 — tools/_digest.py 를 가져오려면 CWD
# 기준 상대경로로 넣는다. 이 스크립트 자신이 이미 LOCK_FILE/PSDK_DIR 를 저장소
# 루트 기준 상대경로로 가정하므로(CI 는 `uv run --locked bash scripts/...`로 저장소
# 루트에서 호출) 새로운 제약이 아니다.
sys.path.insert(0, "tools")
from _digest import sha256_file

try:
    import yaml
except ImportError:
    # 도구 부재를 통과로 위장하지 않는다 — 이 저장소가 rg 부재로 겪은 조용한
    # no-op 사고(감사 #29)와 같은 클래스다. CI는 `uv run`으로 감싸 호출한다.
    print("FAIL: PyYAML 을 import 할 수 없다 — 핀 검증을 수행하지 못했다.")
    print("      `uv run bash scripts/check_third_party_pins.sh` 로 실행할 것.")
    sys.exit(1)

lock_path, psdk_dir = Path(sys.argv[1]), Path(sys.argv[2])
lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))

for required in ("source", "license", "target"):
    if required not in lock:
        print(f"FAIL: {lock_path}에 필수 키 '{required}' 없음 — 락 파일 스키마 손상")
        sys.exit(1)

pinned_commit = lock["source"]["pinned_commit"]

# 대조할 해시 목록을 먼저 모은다. 트리 미설치여도 락 파일 스키마는 항상 검증한다 —
# CI에는 PSDK를 fetch하는 job이 없어 트리 검증은 상시 SKIP이므로, 락 자체의 건전성만이
# CI에서 이 게이트가 실제로 수행하는 유일한 검사다.
checks: dict[str, str] = {}
checks.update(lock.get("verified_files") or {})
checks.update((lock.get("license") or {}).get("verified_files") or {})
target_lib = (lock.get("target") or {}).get("library_path")
target_sha = (lock.get("target") or {}).get("library_sha256_on_device")
if target_lib and target_sha:
    checks[target_lib] = target_sha

# 공집합을 "전부 일치"로 출력하면 검사 미수행이 통과로 위장된다(2026-08-04 감사 지적).
if not checks:
    print(f"FAIL: {lock_path}에 대조할 sha256 항목이 하나도 없다 "
          "(verified_files / license.verified_files / target.library_sha256_on_device 전부 비었음) — "
          "핀 게이트가 아무것도 검증하지 못한다.")
    sys.exit(1)

if not (psdk_dir / ".git").exists():
    print(f"OK(락 스키마): 대조 대상 {len(checks)}건 정의됨, license.spdx="
          f"{(lock.get('license') or {}).get('spdx', '?')}")
    print(f"SKIP(트리 검증): {psdk_dir} 미설치 — 로컬 HIL 세션에서만 fetch되는 선택적 대상")
    sys.exit(0)

actual = subprocess.check_output(
    ["git", "-C", str(psdk_dir), "rev-parse", "HEAD"], text=True
).strip()
if actual != pinned_commit:
    print(f"FAIL: {psdk_dir} HEAD={actual[:12]} != 핀 commit={pinned_commit[:12]}")
    sys.exit(1)

bad = False
for rel_path, expected_sha in checks.items():
    target = psdk_dir / rel_path
    if not target.is_file():
        print(f"FAIL: {rel_path} 없음(핀 커밋에 존재해야 함)")
        bad = True
        continue
    actual_sha = sha256_file(target)
    if actual_sha != expected_sha:
        print(f"FAIL: {rel_path} sha256 불일치(기대 {expected_sha}, 실제 {actual_sha})")
        bad = True

if bad:
    sys.exit(1)

print(f"OK: {psdk_dir} == 핀 commit {pinned_commit[:12]}, sha256 {len(checks)}건 전부 일치")
PY

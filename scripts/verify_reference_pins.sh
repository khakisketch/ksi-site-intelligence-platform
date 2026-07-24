#!/usr/bin/env bash
# REFERENCE_REPOS_LOCK.yaml의 핀과 실제 서브모듈 커밋 일치를 검증한다.
# 서브모듈이 초기화돼 있으면 rev-parse HEAD, 아니면 git ls-tree gitlink SHA로 검증
# (CI에서 private 서브모듈을 클론하지 않고도 핀 드리프트를 잡기 위함).
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import subprocess, sys, re

lock = Path("references/REFERENCE_REPOS_LOCK.yaml").read_text()
entries = re.findall(r'- name: ([^\n]+).*?path: "([^"]+)".*?pin: "([^"]+)"', lock, re.S)
bad = False
for name, path, pin in entries:
    p = Path(path)
    if (p / ".git").exists():
        actual = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "HEAD"], text=True
        ).strip()
        mode = "worktree"
    else:
        out = subprocess.check_output(["git", "ls-tree", "HEAD", path], text=True).strip()
        # 형식: <mode> commit <sha>\t<path>
        parts = out.split()
        if len(parts) < 3 or parts[1] != "commit":
            print(f"MISS {name}: {path} (gitlink 없음)")
            bad = True
            continue
        actual = parts[2]
        mode = "gitlink"
    print(f"{name}: {actual} ({mode})")
    if actual != pin:
        print(f"  expected {pin}")
        bad = True
sys.exit(1 if bad else 0)
PY

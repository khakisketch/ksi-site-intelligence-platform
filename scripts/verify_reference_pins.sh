#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import subprocess, sys, re
lock = Path("references/REFERENCE_REPOS_LOCK.yaml").read_text()
entries = re.findall(r'- name: ([^\n]+).*?path: "([^"]+)".*?pin: "([^"]+)"', lock, re.S)
bad = False
for name, path, pin in entries:
    p = Path(path)
    if not p.exists():
        print(f"MISS {name}: {path}")
        bad = True
        continue
    actual = subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()
    print(f"{name}: {actual}")
    if actual != pin:
        print(f"  expected {pin}")
        bad = True
sys.exit(1 if bad else 0)
PY

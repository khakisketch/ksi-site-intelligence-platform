"""Copy the external-use blocker catalog into the dashboard (byte-identical).

Run from the repo root: ``uv run --locked python tools/sync_external_use_blockers.py``.
``tests/contract/test_external_use_blockers.py`` fails when the copy drifts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "contracts" / "catalogs" / "external-use-blockers.v1.json"
TARGET = ROOT / "apps" / "dashboard" / "src" / "lib" / "external-use-blockers.generated.json"


def main() -> None:
    shutil.copyfile(SOURCE, TARGET)
    print(f"synced {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

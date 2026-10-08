#!/usr/bin/env python3
"""Phase-3 field-readiness audit entry point (P3 Task 5 boundary shim).

The real implementation retired blob-identical to
``archive/acquisition-2026/tools/hil/audit_phase3_readiness.py`` with the
managed set (it inspects pilot-export KMZ via archived
``ksi_core.flight_artifacts``). This shim exists only so operator invocations
fail loudly with a pointer instead of ``ModuleNotFoundError``. It is a NEW
record, not a rename — the archived copy is byte-identical to its pre-move
blob. T6 dispositions HIL tooling.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    raise RuntimeError(
        "phase-3 field-readiness audit retired to "
        "archive/acquisition-2026/tools/hil/audit_phase3_readiness.py in P3 "
        "Task 5 (managed flight-artifact inspection) — see the task report"
    )


if __name__ == "__main__":
    raise SystemExit(main())

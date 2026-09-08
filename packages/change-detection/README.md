# Change detection package

Runtime kind: **import-only Python package** (`ksi-change-detection` / `ksi_change_detection`).

## Responsibility

- deterministic point-cloud and DSM change calculation;
- volume and design-conformance computation;
- change-region extraction and comparison result submission helpers;
- fail-closed geometry, CRS, lineage, and compatibility checks owned by the calculation boundary.

It does not own durable comparison requests/results, Mission state, worker leasing, deployment, or
device behavior. Core owns durable authority; `services/processing-controller/` owns the independently
operated worker lifecycle and imports this package.

Primary consumers are `services/processing-controller/`, contract/E2E tests, and bounded offline
tools. Wire result models remain in `packages/event-contracts/` so Core does not inherit SciPy,
rasterio, or point-cloud dependencies.

## Authority and dependencies

- Relevant product gate: `REQ-INT-104` and `INV-053`.
- Direct KSI dependencies: `ksi-event-contracts`, `ksi-geo-spatial`.
- External calculation dependencies: NumPy, SciPy, rasterio, laspy, and lazrs.
- Open3D is not used on the recorded Python/aarch64 boundary; CloudCompare is excluded from this
  in-process package because of the recorded license/process policy.

## Verification

```bash
uv run --locked pytest -q packages/change-detection/tests \
  tests/contract/test_change_detection.py \
  tests/contract/test_volume_change_end_to_end.py \
  tests/contract/test_design_conformance_compute.py
uv run --locked ruff check packages/change-detection
```

Physical HIL or a deployed worker is not required to verify these deterministic algorithms. Passing
software tests does not promote any device or field capability.

## Rollback

Move `packages/change-detection/` back to `services/change-detection/`, then run `uv lock` to
regenerate workspace source paths. Do not keep both paths or add a compatibility symlink.

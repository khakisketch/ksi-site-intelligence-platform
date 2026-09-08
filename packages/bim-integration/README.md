# BIM integration package

Runtime kind: **import-only Python package** (`ksi-bim-integration` / `ksi_bim_integration`).

## Responsibility

- read supported IFC georeferencing metadata;
- sample IFC reference geometry for design/as-built comparison;
- reject unsupported or ambiguous coordinate behavior rather than infer it.

It does not own design-surface registration, durable comparison state, processing worker lifecycle,
or BIM authoring. `tools/convert_ifc_design_surface.py` and contract tests are its direct consumers;
Core remains the authority for registered design surfaces and comparison admission.

## Authority and dependencies

- Relevant product gate: `REQ-INT-104` and `INV-053`.
- External dependencies: IfcOpenShell (LGPL-3.0, unmodified package dependency) and NumPy.
- No code or runtime import comes from `references/`.

## Verification

```bash
uv run --locked pytest -q \
  tests/contract/test_ifc_reference_model.py \
  tests/contract/test_convert_ifc_design_surface.py
uv run --locked ruff check packages/bim-integration tools/convert_ifc_design_surface.py
```

These checks establish software conversion behavior only. Customer BIM rights, site CRS evidence,
and field accuracy acceptance remain separate gates.

## Rollback

Move `packages/bim-integration/` back to `services/bim-integration/`, then run `uv lock` to regenerate
workspace source paths. Do not keep both paths or add a compatibility symlink.

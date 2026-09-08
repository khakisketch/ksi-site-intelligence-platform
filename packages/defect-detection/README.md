# Defect detection package

Runtime kind: **import-only, optional-model Python package**
(`ksi-defect-detection` / `ksi_defect_detection`).

## Responsibility

- verify the local registered defect-model artifact before load;
- adapt the vendored MixerCSeg inference code behind an explicit optional extra;
- convert probability maps into deterministic, typed defect candidates.

It does not own a deployed detector service, Core persistence/API, automatic production activation,
model download policy, Mission state, or device behavior. `tools/fetch_defect_model.py`, optional model
CI, and contract tests consume the package. Core consumes the lightweight defect contract from
`packages/event-contracts/`, not this model stack.

## Authority, model, and licenses

- Relevant invariants: `INV-040` (no production mock fallback) and `INV-043` (model provenance).
- Base dependencies keep contract/post-processing checks available without the heavy model stack.
- The `mixercseg` extra is explicit and fail-closed; it does not imply production support.
- Vendored MixerCSeg and VMamba notices/licenses live under
  `src/ksi_defect_detection/_vendor/mixercseg/` and move with the source tree.
- Model bytes remain ignored under `models/`; provenance remains in
  `docs/models/MODEL_REGISTRY.yaml`.

## Verification

```bash
uv run --locked pytest -q \
  tests/contract/test_defect_model_registry.py \
  tests/contract/test_defect_postprocess.py \
  tests/contract/test_mixercseg_detector.py
uv run --locked ruff check packages/defect-detection
```

The heavy real-model test requires the recorded optional extra and model artifact. Base-suite skips
must remain explicit; a skip is not model, GPU, HIL, field, or production acceptance.

## Rollback

Move `packages/defect-detection/` back to `services/defect-detection/`, then run `uv lock` to
regenerate workspace source paths. Do not keep both paths or add a compatibility symlink.

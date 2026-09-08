# Vendored: spiderforest/MixerCSeg

- Source: https://github.com/spiderforest/MixerCSeg
- Commit: 7ad3fd6fd0e9bc60d1eb9c3b50292d876485dd1d (2026-03-09)
- License: MIT (`LICENSE.upstream`)
- Decision record: `docs/models/MODEL_DECISIONS.yaml` MODEL-P4-001

Also vendors a subset of `VMamba/models/` from https://github.com/MzeroMiko/VMamba
(MIT, `LICENSE.vmamba.upstream`), as included in the MixerCSeg repository itself
(acknowledged in its README).

## What was kept

Only the files reachable from `models.build_MixerCSeg` for pure inference —
traced empirically by importing the model and inspecting `sys.modules`
(2026-08-07). Excluded: `main.py`, `test.py`, `engine.py`, `datasets/`, `eval/`,
`util/`, `VMamba/models/kernels/` (the custom CUDA `selective_scan` kernel
source — not built; `VMamba/models/csms6s.py` falls back to a pure-PyTorch
`selective_scan_ref` path automatically when the compiled extension isn't
importable — slower, mathematically equivalent but not bit-exact against the
compiled kernel).

**GPU status, precisely** (corrected 2026-08-07 after review — the previous
wording here overclaimed): a GPU forward pass (random weights, unpatched
`csm_triton.py`, isolated scratch venv with `torch==2.13.0+cu130`) was
verified earlier in the same session that produced this vendoring, on this
machine's NVIDIA GB10. The `csm_triton.py` patch below was written and
verified afterward, against this repository's own CPU-only torch install
(root `pyproject.toml` pins the main workspace to a CPU-only index) — it was
**not** re-run against CUDA post-patch. Code inspection shows the patch is a
no-op on the CUDA branch (identical operations execute when `x.is_cuda` is
true, see patch 2 below), but that inspection is not a substitute for
re-running the GPU forward pass with the patch applied — do that before
relying on this vendoring for a GPU deployment.

## Local patches vs upstream

1. `models/encoder/vss_block.py`: `HoGEdgeGateConv(..., nbins=36)` →
   `nbins=180`.

   The checked-in upstream code only matches ONE of the four released
   checkpoints (`nbins=36`, per `test.py`'s hardcoded path
   `nbins_36_Crack500`) — `nbins` is not a stored/configurable training arg,
   it's hardcoded per-checkpoint by the authors. The checkpoint this project
   uses (`checkpoint_DeepCrack.pth`, the one MODEL-P4-001 cites for its
   DeepCrack mIoU 0.9151 figure) was trained with `nbins=180` (per
   `eval/evaluate.py`'s default result path `nbins_180_DeepCrack` and
   confirmed empirically: `strict=True` `load_state_dict` only succeeds with
   180, zero missing/unexpected keys).

2. `VMamba/models/csm_triton.py`: `cross_scan_fn`/`cross_merge_fn` each
   unconditionally wrap their body in `with torch.cuda.device(x.device):`,
   even though both functions already correctly select a CPU-safe fallback
   (`CrossScanF`/`CrossMergeF`, non-triton) when the input isn't on CUDA
   (`WITH_TRITON and x.is_cuda and (not force_torch)` gate). The unconditional
   `torch.cuda.device()` call raises `ValueError: Expected a cuda device, but
   got: cpu` before the fallback ever runs — the CPU path was reachable in
   the branch selection but not actually usable due to this guard being
   missing one level up. Patched to only enter the CUDA context when
   `x.is_cuda`/`y.is_cuda`. Confirmed 2026-08-07: forward pass now succeeds
   on `device="cpu"` (this workspace's default torch install — the root
   `pyproject.toml` pins the main workspace to a CPU-only torch index) with
   deterministic output across two runs.

## Import mechanics

Upstream code uses absolute top-level imports (`from models.decoder import
...`, `from VMamba.models.vmamba import ...`) that assume the repo root is on
`sys.path`. Rather than rewrite every import (harder to diff against upstream
on updates), `mixercseg_adapter.py` inserts this vendor directory onto
`sys.path` only for the duration of the import call, then removes it — see
that module's docstring for the collision rationale (`models`/`VMamba` are
generic top-level names).

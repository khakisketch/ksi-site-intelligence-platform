# Repository and operator workflow scripts

`scripts/` contains entrypoint-style orchestration for repository checks, local development, reference
pinning, and Manifold operator workflows. Scripts compose commands; they must not become a hidden home
for product business logic.

- Root `check_*` and `verify_*`: repository/CI guard orchestration.
- `run_core_dev.py`: local Core development entry.
- `q*`: authority/reference query helpers.
- `manifold/`: operator-facing Manifold build/status/probe workflow; device actions still require the
  separately approved playbook and authority.

Artifact validators, converters, import/export tools, and bounded generators live in `../tools/`.

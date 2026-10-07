# packages/domain

Stable domain value objects and enums.

- `ksi_domain.canonical_json` — canonical JSON bytes (sorted keys, minimal
  separators, `ensure_ascii=False`, `allow_nan=False`).
- `ksi_domain.signed_payload` — `canonical_payload_bytes` (drops only the
  top-level `signature` block) and `sha256_digest` (`sha256:<hex>`); the exact
  helpers re-exported by `ksi_mission_contracts.signing`.

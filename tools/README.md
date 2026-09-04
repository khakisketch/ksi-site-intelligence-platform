# Artifact and verification tools

`tools/` contains bounded validators, converters, evidence builders, import/export utilities, and
generators. A tool may validate or transform an artifact but does not own runtime product policy.

- `edge/`: native artifact, ABI, symbol, SDK-readiness, and boundary verification.
- `hil/`: HIL evidence preparation/import/verification software; never physical capability proof alone.
- `vector-extraction/`: isolated read-only reference-vector extraction.
- Root tools: media intake, model fetch, retention, release evidence, civil/IFC/geoid/ONNX conversion,
  local OIDC support, and repository normalization validation.

Repository/build/dev/operator orchestration belongs in `../scripts/`; reusable runtime logic belongs in
`../packages/`, `../services/`, or `../edge/` under its product owner.

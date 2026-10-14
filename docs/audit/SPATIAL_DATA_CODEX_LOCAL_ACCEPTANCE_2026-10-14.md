# Spatial-data Codex local acceptance — 2026-10-14 (synthetic)

- Status: LOCAL SOFTWARE EVIDENCE only. Synthetic copied data, local MinIO
  (`127.0.0.1:9100`), no customer data, no public sample, no bwrap sandbox,
  no deploy/CI. The parser-sandbox containment gate and customer acceptance
  remain OPEN.
- Related: [ADR-KSI-036 D6](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md),
  [rebaseline ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
  (2026-10-14 item-4 section), [provisioning runbook](../ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md).
- Rig (transient): `/tmp/opencode/ksi-sdata-codex-20261014/` — scripts, logs,
  evidence (`SUMMARY.md`); data copy `~/.cache/ksi-sdata-20261014/`.

## What was exercised and passed

- Protected lane boot: an owner-private generated config + rights file
  (Ed25519-signed activation, one operator grant) mounted
  `app.state.spatial_data` on the production factory (port 8061); the grant was
  imported idempotently into `spatial-data-grants.jsonl`.
- Operator read path: site 200 (`aiEgressAllowed=true`), spatial-asset catalog
  200 with 20 page-1 assets; the target DSM `ksa-v1-8430fcc…` shows `MEASURED`.
- Real inspection lane (documented in-process precedent, actual MinIO bytes):
  both current-policy requests executed `COMPLETED`, `MEASURED` 2×2 EPSG:5186.
- Codex CLI (0.160.1, ChatGPT auth) with the spatial-data MCP stdio adapter:
  initialize + `tools/list` (six tools), and a `tools/call` that reached Core
  and returned Core's typed finite-budget response (`RESOURCE_LIMIT_EXCEEDED`).
- Storage guarantees probe against local MinIO: **16/16 checks passed** —
  non-null version IDs, FULL_OBJECT SHA-256 echo and match on HEAD,
  exact-version read, version listing, presigned GET signed for
  `host;x-amz-checksum-mode` returning exact bytes and checksum header,
  exact-version delete, deleted version unreadable, other version survives,
  cleanup. A naive client sending extra unsigned headers is refused by MinIO
  (`400` "headers present which were not signed"), so consumers must send
  exactly the signed headers — the product transport already does.
  This closes only the local S3-compatible half of the storage gate; a cloud or
  customer-host S3 remains separate.

## Found and fixed (this session)

- The production token env could not register the documented
  `SPATIAL_DATA_MCP_CLIENT` kind with its required explicit scopes: the parser
  rejected `allowedSiteIds`/`allowedWorkAreaIds` for any kind other than
  `ANALYSIS_MCP_CLIENT`, making the AI client unreachable in production
  configuration. Fixed in `ksi_core.composition.runtime_config`
  (`_parse_principal_tokens` now accepts both MCP client kinds) with a locked
  adapter test; the runbook documents the registration shape.

## Blocked with reproduction (deferred to a reviewed chain-generation task)

- After renewing the copied 10-12 authority chain
  (`tools/regenerate_external_validation_chain.py`, seq 24→25), the AI
  discovery route (`GET /v1/sites/{site}/work-areas/{area}/spatial-data-assets`)
  fails `CURRENTNESS_UNAVAILABLE` (503): page projection materializes each
  catalog candidate; an older candidate whose retained report is bound to an
  expired policy fails the per-source currentness recheck, and since
  `CURRENTNESS_UNAVAILABLE` is not in `_LIST_SUPPRESSED`, the whole page fails.
  During the same run the renewed authority record resolved with a matching
  digest, but a reconcile-time `permits_selection(use="EVIDENCE")` returned
  False, so the registry's active selection did not cover every path the
  discovery flow rechecks. This is fail-closed behavior (no silent success);
  the exact selection-state cause needs a reviewed chain-generation review.
- Consequence: the Codex happy path (discover → create request → status via
  MCP) could not complete on this mixed-generation synthetic site; the client
  and authority boundary itself is proven (real tool call + typed Core error).

## Boundaries and next steps

- The sandboxed parser (`bwrap`) containment, the VM verification host chain,
  a cloud/customer S3, public-sample acceptance, customer/operational
  acceptance, and deploy/CI remain OPEN and are not implied by this evidence.
- Next bounded candidates: (a) review the chain-renewal + selection state
  (why the renewed record does not permit EVIDENCE selection / why mixed old
  candidates fail the page), then re-run the Codex happy path; (b) decide
  whether a per-candidate currentness failure should suppress one candidate
  (visible as unready) instead of failing the whole listing — an explicitly
  reviewed product/behavior decision, not a unilateral change.

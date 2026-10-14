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
- The AI discovery preflight could surface a non-current inspection report.
  Root cause: after the copied 10-12 chain renewal, candidates whose subject is
  no longer permitted by the active record get a non-ACTIVE selection; the
  preflight snapshot treated "no active selection" as "any retained record" and
  returned an old report bound to an expired policy. Delivery then failed that
  one candidate in `require_current`, and `CURRENTNESS_UNAVAILABLE` (not in
  `_LIST_SUPPRESSED`) escalated a single stale candidate into a whole-listing
  `503`; the operator catalog could also show a stale `MEASURED` as the current
  inspection. Fixed in
  `ExternalArtifactInspectionStore.public_snapshot_bounded`: without an active
  selection it returns the pending state and no report. The candidate is then
  classified per-candidate `SOURCE_NOT_MEASURED` (suppressed; `unready` when
  granted, invisible otherwise), the catalog projects the current pending
  state, and the historical report stays retrievable via
  `historical_report`/retained lookups. `require_current`'s pinned
  `CURRENTNESS_UNAVAILABLE` contract for the final check-and-commit is
  unchanged.
  Locked by two tests: store-level withdrawn-authority snapshot hiding
  (`test_bounded_inspection_without_active_selection_hides_stale_report`) and
  source-level preflight classification
  (`test_source_withdrawal_classifies_listing_preflight_as_unmeasured`), with
  the pinned final-recheck currentness test still green.
- Process lesson: two "fixed build" acceptance runs silently served a stale
  process that still held port 8061 (readiness was answered by the old build).
  The rig launcher now frees the acceptance port before spawning; the final
  evidence below was verified against the new process id.

## Completed Codex CLI chain (after both fixes)

Real client, real Core, synthetic copied data, local MinIO:

- Discovery (`ksi_list_spatial_data_assets`, limit 8): page `200` with the
  target `ksa-v1-8430fcc…` (`permittedOperations` `["READ","PREPARE"]`,
  `permittedBounds` `[200000, 549999.8, 200000.2, 550000]`); the other
  mixed-generation candidates are suppressed per-candidate as
  `SOURCE_NOT_MEASURED` instead of failing the page.
- Create (`ksi_create_spatial_data_request`, idempotency key
  `sdata-acc-codex-1`): `201` job `sdj-v1-a9bb54c9…`, `executionState`
  `QUEUED`, `availability` `NOT_READY` — an honest not-yet-prepared state, no
  fabricated receipt.
- Status (`ksi_get_spatial_data_request`): same job, `QUEUED`/`NOT_READY`.
- Cancel (`ksi_cancel_spatial_data_request`): `CANCELED`/`NOT_READY`; the Core
  journal shows `spatial-data-job.issued.v1` → `spatial-data-job.state.v1`
  (`CANCELED`) for that exact job.

## Boundaries and next steps

- The sandboxed parser (`bwrap`) containment, the VM verification host chain,
  a cloud/customer S3, public-sample acceptance, customer/operational
  acceptance, and deploy/CI remain OPEN and are not implied by this evidence.
  The prepared/`COMPLETED` half of the flow still requires the sandboxed
  preparation lane and its host containment proof.
- Next bounded candidates: run the same chain on the VM verification host
  (sandboxed parser plus a real preparation launcher), then re-check the
  storage guarantees against a cloud/customer S3 provider.

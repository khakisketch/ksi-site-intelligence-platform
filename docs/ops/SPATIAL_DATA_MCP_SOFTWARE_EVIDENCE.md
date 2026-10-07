# Spatial Data MCP — local software evidence (Task5, generated fixtures only)

Scope: **local generated-software evidence only**. Every byte below comes from
owned generated TIFFs on a known 10x10 grid through a real loopback Core,
the real data-worker control flow and isolated raster subprocess, the official
SDK stdio adapter path, and the guarded HTTP consumer. SDK/client/file traffic
uses loopback HTTP. The worker's Core calls use an in-process HTTPS-mounted
transport; this is not a separately deployed network-worker verification.
This document proves no host behavior, no customer
accuracy, no cost/rights/containment acceptance, and no production readiness.
Sample, rights, cost, containment, and product-state acceptances remain open;
`docs/superpowers/product-state.md` (EXTVAL slice) is unchanged by this task.

Base revision: `bcca3c3` (`feat(spatial-data): add bounded local stdio MCP adapter`).
Task5 runtime changes: one minimal RGBA mask-flag repair in
`packages/geo-spatial/src/ksi_geo_spatial/external_native_window.py`
(shared-alpha `per_dataset` accepted; true internal mask still refused),
plus 4 primitive tests in `tests/contract/test_external_native_window.py`.
Core single-job AI publication also captures an owner-selected, point-in-time
job response with private per-store integrity binding. Worker progress during
publication does not invalidate that response. Request credentials, consent,
the exact frozen grant, source and scope are still checked before headers and
body; the seal is not an access grant. Lists retain strict snapshot cursors,
and file access still checks current availability and rights. Metadata audit
hashes the selected bytes attempted for publication, not a client-receipt claim.

## Entrypoint / config / tool workflow

- Adapter entrypoint (source tree, never installed):
  `python -m ksi_spatial_data_mcp.server --config=/absolute/protected.json`
  with `PYTHONPATH=services/spatial-data-mcp/src`. Console script:
  `ksi-spatial-data-mcp --config=/absolute/protected.json`.
- Config: one owner-protected JSON (all limits required, strict, positive,
  finite; documented values are tests-only) plus one separate absolute
  `0600` token file holding only the opaque token. No bearer
  environment/CLI/config/tool input, no ambient proxy, no redirect.
- Tools (six, fixed): `ksi_list_spatial_data_assets`,
  `ksi_get_spatial_data_asset`, `ksi_create_spatial_data_request`,
  `ksi_list_spatial_data_requests`, `ksi_get_spatial_data_request`,
  `ksi_cancel_spatial_data_request`. Reads are read-only; create/cancel are
  idempotent. The get tool returns the exact Core job plus a deterministic
  file reference only for a `COMPLETED`+`AVAILABLE` receipt; all other shapes
  return the job with a null reference and never promise bytes.
- Example caller workflow (source tree, no install):
  `python examples/spatial-data/mcp_native_window_workflow.py --config
  /absolute/protected.json --site-id … --work-area-id … --asset-ref …
  --bounds W S E N --crs-digest … --idempotency-key … --poll-budget-seconds
  … --receipt-out /absolute/local/receipt.json [--download-dir
  /absolute/local/bytes] [--max-download-bytes …]`. Requests once, polls a finite caller budget,
  persists safe IDs/receipt/reference (`0600`, no-overwrite), downloads only
  through the guarded consumer, fails with closed codes. The optional
  `--max-download-bytes` is a finite caller raster quota; absent it falls back
  conservatively to `maxStructuredResponseBytes` (example fallback, not a
  Core/MCP file maximum). Receipt/download targets are caller-owned local
  paths; SDK child cleanup relies on the official SDK close (no host claim).

## Generated evidence (all local, all reproducible from this revision)

Run from the repository root with the project virtualenv:

```sh
.venv/bin/python -m pytest tests/contract/test_spatial_data_mcp_http_integration.py -q
.venv/bin/python -m pytest tests/replay/test_spatial_data_mcp_replay.py -q
.venv/bin/python -m pytest tests/contract/test_spatial_data_mcp_workflow_example.py -q
.venv/bin/python -m pytest tests/contract/test_external_native_window.py -q
.venv/bin/python -m pytest tests/contract/test_spatial_data_ai_job_snapshot.py tests/contract/test_spatial_data_ai_egress.py -q
```

Independent integrated verification of this source snapshot: **872 passed,
0 failed, 0 skipped** across 27 affected test files. One deliberate
`NodataShadowWarning` belongs to an unsupported RGBA negative control.
Ruff/format checked 12 Python files; mypy checked 11 targets (including their
imported test helpers); all passed. Durable revision/hash and verification
records are in `docs/superpowers/plans/2026-10-06-spatial-data-product-continuation.md`.
These counts are not a full-repository, package-build, or host acceptance claim.

What each proves:

- Parity (`test_sdk_discovery_prepare_receipt_http_consumer_parity[dsm|rgb|rgba]`):
  SDK stdio discovery → create → worker prepare → HTTP get returns the same
  V1 job; HTTP-only consumer verifies digest/size/native pixel array/affine/
  mask/CRS against a hand-derived oracle (known grid constants, never the
  production geometry helper). RGBA full byte parity included.
- Restart (`test_restart_preserves_job_and_rejects_changed_body`): same
  body+key returns the same ID after participant restart with identical
  receipt/bytes; changed body conflicts (409-class `IDEMPOTENCY_CONFLICT`).
- Next observation (`test_next_observation_gets_new_source_and_result`): new
  epoch binds a new asset/source/job/receipt; old receipt untouched; no
  latest substitution.
- Lost response (`test_lost_create_response_issues_exactly_once`): a raw-socket
  create whose response is never read retries to the same job ID; the job
  list holds exactly one job; altered body conflicts.
- Restart state machine (`test_restart_replays_queued_completed_canceled`,
  `test_revoked_completed_stays_frozen_in_journal_across_restart`): QUEUED
  stays runnable, COMPLETED keeps receipt+bytes, CANCELED stays canceled;
  revoked COMPLETED stays byte-identical in `jobs.jsonl` while live reads
  and bytes deny closed.
- Rights matrix (`test_rights_negative_matrix_closes_all_http_pairs_and_sdk_tools`,
  `test_revoked_bytes_abort_midstream_without_partial_file`): consent revoke
  closes all 8 HTTP pairs (`403 AI_EGRESS_DENIED`, no ack; HEAD 403);
  purpose downgrade `403 PERMISSION_DENIED`; foreign/wrong-site/wrong-area
  `404 NOT_FOUND`; revoked grant denies SDK details
  (`NOT_FOUND`/`GRANT_REQUIRED`/`ACCESS_REVOKED`) while lists filter to empty
  pages; expired replacement closes; READ-only reads but never creates;
  ambiguity denies (`AMBIGUOUS_GRANT`); replacement issues anew without
  resurrecting the frozen job; worker source mismatch fails closed
  (`SOURCE_BYTES_MISMATCH`, no receipt, no upload); consent revoked
  mid-download aborts the stream with no partial file.
- Example e2e: the caller subprocess and real worker/raster-launcher flow produce the safe
  receipt and byte-identical download; same-key rerun recovers the same job;
  revoked-grant run exits 2 with no receipt and no token/raster leakage.
- Additional matrix tests cover consent withdrawal before all six SDK tools,
  genuine pagination/cursor changes, WorkOrder source binding, header downgrade
  and missing acknowledgement from the real Core response.
- Job publication regressions use a controlled genuine worker-progress barrier;
  consistent forged snapshots, another store's seal, replaced/revoked grants,
  changed source and post-header revocation remain refused. The SDK teardown
  exception-group mapping preserves only unambiguous closed failure codes.

## Explicit non-claims

- No real-device, HIL, field, host, deployment, or customer verification.
- No quantitative or settlement accuracy claim; registration, RTK FIX, and
  software checks do not establish accuracy (see product authority).
- No universal Codex/Claude/ChatGPT compatibility claim; no tool
  configuration installation; no signed authority issuance.
- Fixture limits, budgets, ports, and tokens are generated-test values, not
  production SLAs, quotas, or credentials.

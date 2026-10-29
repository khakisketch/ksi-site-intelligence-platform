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

The 2026-10-28 local candidate adds a same-token machine-channel preflight before
MCP create/cancel. The earlier wheel/sdist and installed-SDK evidence below is
historical and does not verify that newer adapter source. The newer candidate's
separately scoped installed-package verification is recorded below; no external
AI-host installation or package publication is implied.

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

- Adapter entrypoint (default source-tree test workflow):
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

Final independent whole-change verification at base `fc14059` plus the five-entry
Core inventory correction: scoped **1,349 passed** (54 warnings), bare full
`.venv/bin/python -m pytest -q` **9,028 passed, 122 skipped, 102 warnings**,
no failures. The full command used child-process umask `022`; private verification
logs used `077`. Changed Python Ruff/format checked 39 files, scoped mypy checked
35 production/test targets, and offline lock verification preserved all 144
third-party entries. Manifest/console source closure and source import passed.
Skipped tests are unverified, not acceptance evidence. See the durable ledger
for exact frozen hashes, commands, receipts and the initially failing full run.

### Updated isolated package verification — 2026-10-28

- The source snapshot includes `core_client.py` SHA256
  `fed939572004418f20e1c8461333fdd8d58deae048cd2c8a7d098113a81a808c`.
  Offline wheel and sdist builds succeeded; rebuilding the wheel from that sdist
  produced the same wheel SHA256
  `4c5fe19e29a50b1e9e35ddf755e7a206b610ec91a3757e6a95196cc86d550a3a`.
  The five installed adapter modules match the source snapshot. These are local
  unsigned test artifacts, not a released package.
- A private Python 3.12 environment installed local wheels with `--no-deps` and
  a copied, already installed third-party closure; `uv pip check` passed. Cached
  index metadata was insufficient for a fresh offline dependency resolution, so
  this is **not** evidence of a clean resolver install. The SDK and console
  children used installed adapter bytes and no source `PYTHONPATH`; Core remained
  the project fixture, not an installed or deployed Core.
- With generated rights and a loopback Core, the installed stdio adapter listed,
  created and replayed one job, then canceled and re-canceled it. Wrong human
  credentials were refused and left the job count unchanged. Source-based MCP
  client, HTTP-integration and stdio suites passed **21 + 14 + 23 tests**.
  This is not a fresh full-suite, external-host, real-data or customer-acceptance
  claim. Logs and source/wheel hashes:
  `/tmp/opencode/spatial-mcp-offline-verify-93cewG/logs/`.
- Follow-through on the same installed candidate: generated DSM, RGB and RGBA
  fixtures each went through installed SDK stdio discovery/create, the real
  local worker control path, installed SDK result retrieval and the guarded HTTP
  consumer. A separately derived native-grid window compared downloaded pixel
  arrays, masks, affine, bounds, CRS, NoData, valid counts, byte sizes and
  hashes. The installed adapter refused a human credential before job creation;
  a separate direct Core HTTP check verified consent denial and restoration,
  and restart/same-key retrieval preserved the job and bytes. Build re-ran the
  task-owned harness independently with exit 0 and checked all five live source
  modules against the installed modules. Command:
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/opencode/spatial-mcp-lead-parity-9h7oyvy1/installed_full_parity.py`;
  author receipt and harness are in the same temporary directory. Core and
  worker remain the generated fixture described above, and its Core transport
  bridge is not a separately deployed network worker. This does not add a fresh
  resolver install, external host, real-data, field or customer acceptance.
- Build reran the installed parity harness and checked the five installed adapter
  module hashes against the live source: all matched. The current source's MCP
  client, config, stdio, HTTP, identity, example and replay suites also passed
  **120 tests**. The DSM/RGB/RGBA bytes are generated test inputs, and the
  results do not extend the package, host or customer-acceptance claims above.

### Earlier isolated package verification — 2026-10-07

After explicit permission for a task-owned isolated build/test environment,
Hatchling 1.32.4 and its build closure were prepared separately under
`/tmp/opencode/ksi-spatial-mcp-build-20261007-a1`. The shared `.venv`, root lock,
production configuration and external AI-host configuration were unchanged.

Independent runner `ses_eea7d86e8ffeHmJ00clvsU9KPH` verified the runtime source
at `d68b0fb5907df7ad0c5b3025d61e339e6a529ffe`:

- Offline, config-free wheel/sdist builds for `ksi-domain`,
  `ksi-event-contracts`, and `ksi-spatial-data-mcp`, plus an MCP wheel rebuilt
  from its exact sdist. All four commands exited 0; 68 source modules matched
  the archives and installed modules. The MCP wheel SHA256 was
  `c16a656d80f90cdb0978d763c3e02cc08532ed4ba2cdc221aa65b7577287e288`.
- Fresh isolated, non-editable installed package/SDK origins and exact locked
  dependency closure: `mcp==2.2.0`, `httpx==0.28.1`, `pydantic==2.13.4`;
  `uv pip check` passed for 34 installed distributions. No source `PYTHONPATH`
  or system-site-packages fallback in the installed client/server children.
- Installed SDK client and installed console, three genuine generated
  DSM/RGB/RGBA flows: six child exits 0, same-key restart preserves one issued
  job and one output upload per lane. SDK-returned hash/size equal the HTTP
  receipt and actual downloaded bytes; the independent native pixel, mask,
  affine, bounds and CRS oracle passes. Metadata publication audit may grow;
  it is not an extra job issuance.
- Unchanged `test_spatial_data_mcp_http_integration.py` through the installed
  console: **14 passed, 0 skipped, 0 warnings**, 13 observed console spawns.
  Parent fixtures still use the project Core and mounted worker control; this
  is not an installed/deployed Core or network-worker claim.

The original private smoke harness had a closed-session lifetime error and
read the wrong SDK response field. Copied harness repairs and negative
assertion controls were reviewed; no product runtime repair or retry policy
was needed. Incorrect manually copied RGB/RGBA hashes in an author receipt
were preserved and superseded by the raw results and independent receipt;
they do not establish nondeterministic runtime bytes.

Exact commands, fresh command witnesses, archive/installed origins and before/
after snapshots: `/tmp/opencode/task6-package-final-verify/receipt.json`, SHA256
`db1258a1577dd7246fb273768f56f81c3211d24bad17da5b04e7ae763565e7ef`;
durable summary and closeout evidence are in the continuation ledger linked
above. That temporary receipt is no longer available in the current environment;
the older package run was not independently revalidated. These local artifacts
are not a published release. Earlier
full-suite/static results are reused for unchanged runtime bytes, not rerun
or relabelled as fresh package-era full-suite execution.

This verifies local built-package execution only. Publication, deployment,
installation/configuration in an external AI host, permitted customer exports,
rights/accuracy/cost/containment and customer acceptance remain unverified.

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

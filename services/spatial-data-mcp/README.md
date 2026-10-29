# ksi-spatial-data-mcp

Bounded local stdio MCP adapter for the KSI spatial-data AI boundary. It
exposes six fixed tools over one configured Core origin and projects only
Core-evidenced, acknowledged responses. It owns no device authority, no
raster bytes, no grant/credential issuance, and no listener. Checkout contract
tests use the source tree by default. Wheel/sdist builds and the installed
console/SDK flow, including the local mutation preflight below, have also been
verified in a private local test environment with generated data. This
repository does not install the adapter into a shared
environment or AI-host configuration, or publish/deploy it. See
`docs/ops/SPATIAL_DATA_MCP_SOFTWARE_EVIDENCE.md` for the exact verification scope.

## Configuration

One owner-protected JSON file plus one separate absolute `0600` token file
(the token file holds only the opaque token: printable ASCII, no bearer
scheme label, no whitespace or control bytes):

```json
{
  "coreOrigin": "https://192.0.2.10:8443",
  "tokenFile": "/absolute/owner-private/token",
  "maxRequestBytes": 8192,
  "maxStructuredResponseBytes": 131072,
  "maxConcurrentCalls": 2,
  "maxIdentifierBytes": 255,
  "maxCursorBytes": 2048,
  "maxTokenBytes": 4096,
  "maxConfigBytes": 16384,
  "connectTimeoutSeconds": 2.0,
  "readTimeoutSeconds": 2.0,
  "poolTimeoutSeconds": 1.0,
  "callDeadlineSeconds": 5.0
}
```

Every limit is required, strict, positive, and finite; the values above are
tests-only, not production quotas. `maxRequestBytes` also bounds each
inbound stdio protocol line and each outbound Core request;
`maxStructuredResponseBytes` also bounds every serialized outbound stdio
frame, including tool schemas, control frames, and error envelopes;
`callDeadlineSeconds` starts at call entry and covers queuing, token
refresh, transport, validation, and output projection, and bounds each
outbound frame write.

HTTPS origins accept exact literal IPs or exact DNS names (no userinfo,
base path, query, fragment, or control bytes; no ambient proxy or
redirect; TLS stays verified). Plain HTTP is accepted only for literal
loopback addresses for local verification. Config and token files must be
exact-owner `0600`-or-stricter regular files under caller- or root-owned
ancestry with no group/other write permission, verified through a
no-follow descriptor walk with pre/at/post/path stat continuity; the token
is re-read before every call.

## Tools

`ksi_list_spatial_data_assets`, `ksi_get_spatial_data_asset`,
`ksi_create_spatial_data_request`, `ksi_list_spatial_data_requests`,
`ksi_get_spatial_data_request`, `ksi_cancel_spatial_data_request`.

Reads are read-only, create/cancel are idempotent mutations. The get tool
returns the exact Core job plus a deterministic file reference only for a
`COMPLETED`+`AVAILABLE` receipt; every other retained history shape returns
the job with a null reference and never promises bytes.

Before create, the adapter requires an acknowledged, scope-checked asset-list
read; before cancel, it requires an acknowledged read of that exact job. Both
the read and the POST use the same token snapshot from that invocation. A
failed preflight sends no POST; a successful one is not a grant and Core still
checks current consent and permissions for the mutation. Token rotation is
picked up on the next invocation. This binds token bytes, not any independent
server-side remapping of those bytes to a different principal.

Each mutation now needs two sequential Core exchanges and an additional
metadata audit. The configured total deadline and response-byte limit must
cover the preflight as well as the POST; an unavailable or oversized preflight
fails before mutation. If the POST response is lost, its outcome is unknown:
retry the same request body and idempotency key, or the same cancellation,
instead of silently starting a replacement request.

Start: `ksi-spatial-data-mcp --config=/absolute/protected.json`.
stdout carries MCP frames only; a frame that cannot fit the owner budget
closes the session with a safe stderr code instead of partial JSON.
Runtime imports are the pinned workspace closure (`httpx`,
`ksi-event-contracts`, `mcp==2.2.0`, `pydantic`; `anyio`/`threading` arrive
via the pinned MCP dependency, no new dependency is added).

## Generated end-to-end workflow (Task5 local software evidence)

`examples/spatial-data/mcp_native_window_workflow.py` drives this adapter over
stdio from its source tree (no install): it requests once with a
caller-supplied scope and idempotency key, polls a finite caller budget,
persists only safe IDs/receipt/reference (`0600`, no-overwrite), and
optionally downloads bytes through the existing guarded consumer.

```sh
python examples/spatial-data/mcp_native_window_workflow.py \
  --config /absolute/protected.json \
  --site-id site-1 --work-area-id area-1 --asset-ref <assetRef> \
  --bounds 102.1 183.9 108.1 193.9 --crs-digest <sha256:...> \
  --idempotency-key local-run-1 \
  --poll-budget-seconds 60 \
  --receipt-out /absolute/local/receipt.json \
  [--download-dir /absolute/local/bytes] [--max-download-bytes 1048576]
```

The script takes no token argument (the adapter reads its separate owner
token file), addresses no remote origin beyond the configured Core origin,
and never overwrites a partial file. `--max-download-bytes` is an optional
finite caller quota for raster bytes only; absent, it defaults conservatively
to the configured `maxStructuredResponseBytes` (an example fallback, not a
Core/MCP file maximum — a large authorized raster need not force an oversized
MCP JSON budget). Receipt/download targets must be caller-owned local paths;
SDK child cleanup relies on the official SDK close, with no host-compat claim. Full parity, restart, replay, and
rights-matrix evidence is recorded in
`docs/ops/SPATIAL_DATA_MCP_SOFTWARE_EVIDENCE.md`. Host, customer, accuracy,
cost, and containment acceptance remain open.

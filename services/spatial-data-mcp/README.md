# ksi-spatial-data-mcp

Bounded local stdio MCP adapter for the KSI spatial-data AI boundary. It
exposes six fixed tools over one configured Core origin and projects only
Core-evidenced, acknowledged responses. It owns no device authority, no
raster bytes, no grant/credential issuance, and no listener. This package is
source-only: it is exercised from its source tree in contract tests and is
not installed into any host or AI configuration by this repository.

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

Start: `ksi-spatial-data-mcp --config=/absolute/protected.json`.
stdout carries MCP frames only; a frame that cannot fit the owner budget
closes the session with a safe stderr code instead of partial JSON.
Runtime imports are the pinned workspace closure (`httpx`,
`ksi-event-contracts`, `mcp==2.2.0`, `pydantic`; `anyio`/`threading` arrive
via the pinned MCP dependency, no new dependency is added).

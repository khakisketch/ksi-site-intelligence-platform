# Product services and workers

This directory contains independently operated product processes only. Import-only domain,
algorithm, geometry, model-adapter, and processing code belongs in `../packages/`.

## Deployable units

| Path | Product name | Entry boundary |
|---|---|---|
| `core/` | KSI Site Intelligence Core | HTTP control plane and durable authority |
| `dji-gateway/` | DJI Capability Gateway | Exact provider/capability routing process |
| `processing-controller/` | Artifact Processing Worker | Polling/lease-based measurement orchestration |
| `analysis-mcp/` | KSI Analysis MCP adapter | Local stdio adapter over the bounded Analysis API |

## Placement gate

A new child belongs here only if operators start, monitor, configure, and deploy it independently. A
Python project that is only imported by another KSI process belongs in `../packages/`, regardless of
how computationally substantial it is.

The 2026-09-04 R3 migration moved change detection, BIM integration, and defect detection to
`../packages/`. The exact lineage and rollback are recorded in
`../docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`. Do not recreate compatibility directories or
symlinks under `services/`; stable Python distribution/import names provide compatibility.

## Local Analysis runtime (explicit development opt-in)

The Core development server can mount the existing Analysis graph only when an
operator supplies all five inputs: an S3 endpoint and bucket, a protected
`local-analysis-runtime.v1` file, and the separately protected external
workflow and authority-provider files. The Analysis config has exactly
`version`, `policy`, `runtime`, and `resourceEnvelope`. Its policy and
resource envelope must already carry their canonical sealed digests. Core does
not fill a digest, choose an engine, or create authority/configuration facts.

```text
uv run python scripts/run_core_dev.py \
  --host 127.0.0.1 --port 8000 --data-dir /absolute/private/core-data \
  --s3-endpoint http://127.0.0.1:9000 --s3-bucket ksi-dev-evidence \
  --local-analysis-config /absolute/private/local-analysis.json \
  --external-result-workflow-config /absolute/private/workflow.json \
  --external-authority-provider-config /absolute/private/provider.json
```

The three config paths must be absolute, owner-private regular files. The
Analysis opt-in accepts a literal loopback Core host only. It validates all
five inputs before `--reset` can delete durable state or dev signing bootstrap
can write a key. Without the opt-in, local Core startup keeps its existing
default graph. Production does not read these flags or this config.

The dashboard OIDC stack can forward the same explicit inputs:

```text
npm run dev -- \
  --s3-endpoint http://127.0.0.1:9000 --s3-bucket ksi-dev-evidence \
  --local-analysis-config /absolute/private/local-analysis.json \
  --external-result-workflow-config /absolute/private/workflow.json \
  --external-authority-provider-config /absolute/private/provider.json
```

The launcher creates no Analysis authority and has no default paths. It keeps
Core loopback-bound; Tailnet access, when separately enabled for the dashboard,
does not make this Analysis runtime a non-loopback Core listener.

`ksi-external-analysis-worker` remains an independently started worker. The
development launcher neither starts nor supervises it. Its owner-protected
worker token file, exact runtime provenance, trusted object endpoint mapping,
and transport limits are provisioned separately. This first local slice proves
the Core graph and its durable admission blocker (`NOT_STARTED` execution,
`BLOCKED` suitability, no numeric result); it does not claim a completed
numeric analysis from a fresh upload. That requires a supported actual
inspection host and remains blocked while inspection evidence is unavailable.

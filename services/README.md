# Product services and workers

This directory contains independently operated product processes only. Import-only domain,
algorithm, geometry, model-adapter, and processing code belongs in `../packages/`.

## Deployable units

| Path | Product name | Entry boundary |
|---|---|---|
| `core/` | KSI Site Intelligence Core | HTTP control plane and durable authority |
| `dji-gateway/` | DJI Capability Gateway | Exact provider/capability routing process |
| `processing-controller/` | Artifact Processing Worker | Polling/lease-based measurement orchestration |

## Placement gate

A new child belongs here only if operators start, monitor, configure, and deploy it independently. A
Python project that is only imported by another KSI process belongs in `../packages/`, regardless of
how computationally substantial it is.

The 2026-09-04 R3 migration moved change detection, BIM integration, and defect detection to
`../packages/`. The exact lineage and rollback are recorded in
`../docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`. Do not recreate compatibility directories or
symlinks under `services/`; stable Python distribution/import names provide compatibility.

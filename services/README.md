# Product services and workers

This directory currently contains both deployable processes and three historical import-only leaf
packages. That placement is explicitly `PARTIAL`, not a claim that every child is a service.

## Deployable units

| Path | Product name | Entry boundary |
|---|---|---|
| `core/` | KSI Site Intelligence Core | HTTP control plane and durable authority |
| `dji-gateway/` | DJI Capability Gateway | Exact provider/capability routing process |
| `processing-controller/` | Artifact Processing Worker | Polling/lease-based measurement orchestration |

## Import-only leaf packages

| Path | Responsibility | Current consumers |
|---|---|---|
| `change-detection/` | Raster/point-cloud change and volume algorithms | Processing Worker and tests |
| `bim-integration/` | IFC reference-model and geometry support | Tools/tests and processing flows |
| `defect-detection/` | Extra-gated defect model adapter/post-processing | Processing/model tools and tests |

The import-only leaves are R3 move candidates for `packages/`; they remain here until import, lock,
Docker, CI, test, documentation, and rollback evidence is approved.

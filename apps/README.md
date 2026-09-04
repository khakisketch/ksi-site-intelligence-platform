# Product applications

This directory contains human-facing KSI applications, not reusable libraries or device runtimes.

| Path | Product name | Responsibility |
|---|---|---|
| `dashboard/` | KSI Operations Console | Operator intent, workflow state, blockers, recovery, and evidence presentation |

The Console owns no device or flight authority. It calls Core through its server-side BFF/API layer and
must present Core-owned state without inventing readiness. The internal directory name `dashboard` is
retained for compatibility; use “KSI Operations Console” in product-facing documentation.

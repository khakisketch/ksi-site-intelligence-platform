# API-first legacy-boundary audit — 2026-09-20

Status: evidence-only documentation audit. This does not disable, remove, migrate, or authorize any
runtime, schema, invariant, product-state, customer-data, or deployment change.

ADR-KSI-037 D1–D7 defines the first MVP as evidence-bound observed terrain change. Product-state
continues to own the current slice; its Next slices are candidate inventory, not approved priority
until an authorized slice close.

| Class | Concrete paths | Boundary |
|---|---|---|
| Active Core | `services/core/`, `services/processing-controller/`, `contracts/api/openapi-core.yaml`, `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md` | Core records/admission/evidence and the first-MVP target remain authoritative; this audit makes no implementation claim. |
| Retained compatibility/provenance | `services/processing-controller/src/ksi_processing_controller/http_node_odm.py`, `services/core/src/ksi_core/processing_jobs.py`, `tools/ingest_watch.py`, `docs/architecture/ADR-KSI-030-civil-processing-consistency-v1.md` | Managed NodeODM, ProcessingJob, and source-upload paths remain preserved managed/test/demo or separately authorized scope; they are not external first-MVP prerequisites. |
| Conditional successor | `services/core/src/ksi_core/design_progress.py`, `services/core/src/ksi_core/domains/design/`, `contracts/api/openapi-core.yaml`, `packages/bim-integration/` | BIM/design-progress and design-conformance need customer design data and a separate provenance contract; they do not prove approved work, settlement, or first-MVP scope. |
| Not first-MVP / candidate | `services/core/src/ksi_core/copilot.py`, `services/core/src/ksi_core/copilot_openai.py`, `contracts/schemas/copilot-*.v1.json`, `edge/manifold-runtime/`, `edge/psdk-app/`, `edge/msdk-field-bridge/`, `design/ksi-operations-console-a-prototype/` | Copilot remains query/draft-only; Edge, autonomous acquisition, device paths, and prototype surfaces are retained candidates or profile-scoped work. This audit does not assert they are disabled because configuration/runtime evidence was not checked. |

A removal candidate requires an explicitly approved scope and dependency inventory, persisted-data and
contract review, replay/regression evidence, rollback plan, and any applicable deployment/HIL proof.
No class above is removal authorization.

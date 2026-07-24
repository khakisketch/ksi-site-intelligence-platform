# Architecture Decision Records

## ADR-001 Web-first dashboard
Accepted. Keep Next.js as common UI and do not rebuild the product as separate native apps.

## ADR-002 Edge-first autonomy
Accepted. Manifold owns realtime perception, local planning and event evidence decisions.

## ADR-003 DJI flight controller boundary
Accepted. KSI sends high-level intents; DJI owns low-level stability and reactive collision avoidance.

## ADR-004 Unified site mission
Accepted. User selects outcomes; orchestrator composes mapping, patrol, inspection and coverage recovery.

## ADR-005 Baseline mapping before verified patrol
Accepted. Provisional autonomy is conservative; verified autonomy requires validated world model.

## ADR-006 Automatic equipment risk
Accepted. Manual radii are fallback only.

## ADR-007 Event-first UX
Accepted. Live view and raw detections are secondary.

## ADR-008 Provider-agnostic processing
Accepted. DJI Terra, third-party photogrammetry and custom processing are adapters.

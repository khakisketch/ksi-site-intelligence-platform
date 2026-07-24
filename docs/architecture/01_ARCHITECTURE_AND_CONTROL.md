# Architecture and Control Authority

## Target topology

```text
KSI Dashboard (Next.js)
        | HTTPS/WebSocket
KSI Core + DJI Gateway + PostGIS
        | Mission Contract / Events
Matrice 4D + Manifold 3 (KSI Edge)
        | High-level ActionIntent
DJI Flight Controller
```

## Control principles

- Global mission planning and policy: Core
- Onboard perception, world model, local replanning: Edge
- Low-level motion stabilization, reactive avoidance, RTH: DJI
- Manual override: operator

## Server boundaries

Core MUST NOT send continuous attitude/velocity commands. It sends signed Mission Contracts, policy and world-model packages. Edge executes locally and returns state, events, coverage and data deltas.

## Deployment units

- `web-nextjs`
- `core-api`
- `dji-gateway`
- `realtime-gateway`
- `processing-worker`
- `object-storage`
- `manifold-runtime`

## Capability gating

Every device function is registered with product, firmware, SDK, verification evidence and enabled state. Unsupported features remain hidden in UX.

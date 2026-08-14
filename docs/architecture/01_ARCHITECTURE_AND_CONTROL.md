# Architecture and Control Authority

> 전체 구성 한 장 개요는 `00_SYSTEM_OVERVIEW.md` 참조.

## Target topology

```text
KSI Dashboard (Next.js)
        | HTTPS/WebSocket
KSI Core + DJI Gateway + PostGIS
        | Mission Contract / Events
        | (지상 게이트웨이: RC Plus 2 / DJI Pilot 2 —
        |  MQTT/HTTPS/WebSocket 경유, ADR-KSI-004 갱신·ADR-KSI-017.
        |  Edge-sync 자체 채널은 게이트웨이와 독립적으로 유지)
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

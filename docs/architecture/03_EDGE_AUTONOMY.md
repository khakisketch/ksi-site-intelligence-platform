# KSI Edge Autonomy — Manifold Runtime

## Responsibilities

- ingest camera and aircraft data
- synchronize timestamps
- run mission-specific AI
- track entities
- geo-localize entities
- update 4D world model
- estimate equipment states
- generate dynamic risk fields
- select next best view
- issue safe high-level actions
- build evidence bundles
- operate offline and resync

## Process layout

- `ksi-hardware-adapter`
- `ksi-sensor-sync`
- `ksi-perception`
- `ksi-world-model`
- `ksi-risk-engine`
- `ksi-viewpoint-planner`
- `ksi-flight-supervisor`
- `ksi-edge-sync`
- `ksi-health-agent`

Safety-critical state and command validation remain in compiled runtime. Models are replaceable plugins.

## State machine

BOOT -> SELF_TEST -> MISSION_LOAD -> PRE_FLIGHT -> TRANSIT -> CAPTURE/SEARCH -> TRACK -> ASSESS -> REPOSITION -> INSPECT -> EVENT -> REJOIN -> COVERAGE_RECOVERY -> RETURN -> SYNC

## Degradation

The system must reduce model load before dropping tracking, spatial safety or flight supervision. On critical failure it holds or returns according to policy.

# Scout → KSI Site Intelligence Porting Map

```text
Scout contracts/frame.py
Scout contracts/telemetry.py
Scout dal/sync.py
        ↓ PORT
edge/manifold-runtime/sensors

Scout ai/*
Scout rules/*
        ↓ PORT/EXTRACT
edge/manifold-runtime/perception
edge/manifold-runtime/policy

Scout geo/projection.py
Scout geo/zones.py
        ↓ PORT + EXTEND
packages/geo-core
edge/manifold-runtime/world-model

Scout events/*
        ↓ CONTRACT ADOPT
packages/event-contracts
edge/event-engine
services/core/events

Scout mission/*
        ↓ REFERENCE
services/core/mission-contract
edge/mission-executive
services/dji-gateway

Scout server/db/web
        ↓ EXTRACT
services/core
apps/dashboard
```

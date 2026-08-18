# Handoff

## Outcome

The software safety gates are implemented and locally verified. Field readiness is **not** claimed.
IFC mm georeference is fixed and its high-risk ledger item is resolved. Mission Contract activation
and CRITICAL RiskField consumption are fail-closed in software, while their hardware/generation risks
remain open under their original resolve conditions. The consumer also rejects untrusted state
directories (symlink, wrong owner, or any group/other permission) before writing or loading active
contracts.

The IFC meter contract now covers three distinct georeference cases: an explicit map unit, the IFC4.3
project-unit fallback when a present target CRS omits `MapUnit`, and scale-free `IfcRigidOperation`.
A coordinate operation whose `TargetCRS` itself is missing remains a compatibility-only half-set; its
unit cannot be proven from the CRS and must not be advertised as verified georeferencing.

## Remaining blockers

1. Restore network/device access to `ksi-manifold` and repeat HIL from step 8 first. The latest
   read-only retry at `2026-08-13T17:04:01Z` still returned `No route to host` with neighbor `FAILED`.
   Collect the actual `.dpk` install/start crash, `dji_app_ctl` state, firmware/SDK inventory and USB
   bulk channel.
2. Run `psdk_tap` through the installed DJI application framework, collect at least 100 valid
   frame/telemetry pairs and evaluate official p95 against 50 ms.
3. Import the generated KMZ on RC Plus 2 and record `wpmz/`, `droneEnumValue`, payload values and route
   display. Do not promote camera/flight/battery/RTH capability without that evidence.
4. Deploy `ksi-mission-contract-consumer` at the Manifold-facing execution boundary and HIL-test
   malformed/tampered/expired/revoked rejection before resolving `mission-contract-verification-unwired`.
5. Decide RISK-003 geometry synthesis ownership/shape and wire the producer before resolving
   `riskfield-production-generator-unwired`; the Core consumer now validates real bytes but
   intentionally does not invent tactical geometry.
6. Define a durable Edge device heartbeat/presence contract before implementing Fleet·Edge connection
   state. Event or equipment observations must not be relabeled as an online connection.

## Re-run commands

```bash
ulimit -n 8192 && uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
cd apps/dashboard && npm test && npm run lint && npm run build
```

The raised soft FD limit is currently required for the monolithic Python suite on this host; the
default 1024 limit exhausts descriptors across the large number of journal-backed tests.

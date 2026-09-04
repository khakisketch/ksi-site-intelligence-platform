# HIL-0 Capability Runtime Evidence and Route-Family Plan

## Scope and authority

This is the HIL-0 plan and machine-readable evidence boundary for runtime route
availability. It implements no DJI, Core, deployment, network, or device
operation. An artifact produced by `tools/hil/capability_runtime_hil.py` records
only explicitly supplied, non-success capture inputs; it is **not** a capability
qualification, product approval, operational activation, deployment approval, or
device acceptance.

Requirement IDs: REQ-ACQ-101, REQ-ACQ-102, REQ-ACQ-103, REQ-EDGE-101,
REQ-EDGE-102, REQ-INT-101, REQ-MSN-101, REQ-SEC-101.

Owner module: HIL evidence boundary (`contracts/hil/` and `tools/hil/`).

Invariants touched:

- INV-011: this plan never treats a route observation as a Mission Contract.
- INV-012: missing Core/route state blocks new route selection; it does not
  retroactively cancel a locally valid Mission Contract.
- INV-041: runtime evidence, equipment support, and commercial support remain
  separate; this artifact cannot set any of them to approved.
- INV-042: no unsigned, expired, wrong-device, or wrong-route runtime input is
  activated by this plan.

Contracts affected: the additive
`contracts/hil/capability-runtime-hil-evidence-v1.schema.json` only. Existing
capability, connectivity, approval, and activation contracts are unchanged.

Reference assets: ADR-KSI-023, `CAPABILITY_SEMANTIC_CONTRACT.md` §8.5,
`RC_FIRST_PHASE_3_READINESS_CHECKLIST.md`, and the connected-edge HIL manifest.
Adoption decision: **REFERENCE_ONLY**; no reference runtime code is imported.

License/data implications: use only owner-approved, private raw evidence in a
future HIL session. Do not put serials, credentials, topology, customer media,
or raw logs in the artifact or repository.

Rollback: do not consume this artifact for route selection. Deleting an
unconsumed local output is sufficient; no feature flag, deployment, or device
state has changed.

## Ranked route families

The ranking is an investigation order, not a fallback chain and not an approval.
Every family remains independently gated by its own exact capability/path
qualification, product approval, activation, configured deployment binding, and
fresh route observation.

| Rank | Route family | HIL-0 purpose | HIL-0 closure status |
| ---: | --- | --- | --- |
| 1 | PSDK/MOP `EDGE_UPLINK` | preferred M4D + Manifold runtime uplink investigation | `HIL_ROUTE_1 = BLOCKED_EXTERNAL` |
| 2 | Manifold Direct | connectivity add-on comparison path | `NOT_EXECUTED` |
| 3 | DJI Cloud | gateway/Pilot cloud adapter comparison path | `NOT_EXECUTED` |
| 4 | Dock | later Dock-specific route family | `NOT_EXECUTED` |
| 5 | MSDK | conditional preflight/postflight Bridge only | `NOT_EXECUTED` |

At HIL-0 closure, `HIL_ROUTE_1` was blocked because there was **no genuine typed route-state signal**
for the exact `PSDK_MANIFOLD / EDGE_UPLINK` subject. Generic RC internet,
gateway heartbeat, a configured socket, an SDK build, or telemetry is not a
substitute. The required safe effect is `NO_NEW_ROUTE_SELECTION`; it neither
approves a route nor invalidates an already locally valid Mission Contract.

### Route-family execution sequence

1. **PSDK/MOP `EDGE_UPLINK`** — setup: M4D-class aircraft, supported controller,
   Manifold/Edge and the PSDK application joined by an actual MOP channel. Missing
   producer at HIL-0 closure: the PSDK application did not emit `ROUTE_STATUS_V1`. HIL-1S
   adds the software companion, but physical MOP/firmware evidence remains separate. Expected
   subject is `EDGE_ROUTE_PORT(edgeDeviceId, PSDK_MANIFOLD, exact subjectPortId)`.
   AVAILABLE requires PSDK initialized + MOP connected + the exact
   `EDGE_BUNDLE_UPLOAD` handler registered. Disconnect that MOP channel; reconnect
   it and emit a new timestamped signal. Success means old observation expiry
   denies and a fresh exact signal restores only the synthetic bundle path.
   `FIELD_REQUIRED` remains true.
2. **Manifold Direct** — setup: Edge computer with operator-approved cellular/HTTPS
   uplink and an isolated endpoint. Missing producer: a route-scoped authenticated
   session reporter. Expected subject is `EDGE_ROUTE_PORT(edgeDeviceId,
   MANIFOLD_DIRECT, exact direct-uplink port)`. Availability is a successful exact
   endpoint session, not generic internet. Disconnect/reconnect the dedicated
   interface/session; expiry, denial and fresh-session recovery must be shown.
   `FIELD_REQUIRED`.
3. **DJI Cloud** — setup: approved Cloud project, RC/Pilot account, isolated tenant
   and callback/MQTT credentials. Missing producer: a Gateway reporter bound to the
   exact Cloud session and semantic route. Expected subject is
   `GATEWAY_ROUTE_PORT(gatewayDeviceId, DJI_CLOUD, exact port)`. Availability is an
   authenticated subscribed route session. Disconnect/reconnect that session;
   exact tenant/route denial and recovery are required. `FIELD_REQUIRED`.
4. **DJI Dock** — setup: isolated Dock, aircraft, configured network and approved
   maintenance window. Missing producer: Dock session/operation reporters per exact
   route. Expected subject is `DOCK_ROUTE_PORT(dock/gateway identity, DJI_DOCK,
   exact port)`. Availability comes from the Dock session capable of the selected
   non-actuating operation. Disconnect/reconnect the dedicated Dock link and prove
   no cross-port inference. HIL and FIELD validation are required.
5. **MSDK bridge** — setup: supported mobile controller application and Edge bridge
   in conditional preflight/postflight mode. Missing producer: typed MSDK session
   plus exact bridge-handler state. Expected subject is
   `GATEWAY_EDGE_ROUTE_PORT(gatewayDeviceId, edgeDeviceId, MSDK_FIELD, exact port)`.
   Both ends and the selected handler constitute availability. Disconnect/reconnect
   the bridge and require a fresh observation. `FIELD_REQUIRED`; this is not an
   in-flight control path.

## Planned scenarios

All scenarios are `FIELD_REQUIRED`. HIL-0 only emits their explicit
`NOT_CAPTURED` inputs, so it cannot fabricate their execution.

| Scenario | Required safe observation / response |
| --- | --- |
| `AVAILABILITY` | Observe an exact typed route-state signal, not generic reachability. |
| `UNAVAILABILITY` | Reject a new route selection fail-closed. |
| `RECONNECT` | Require a fresh exact signal; do not reuse the prior observation. |
| `EXPIRY` | Reject the expired observation. |
| `WRONG_ROUTE` | Reject a signal bound to another capability, path, device, or port. |
| `MISSION_DENY` | Preserve Core/Mission denial; do not route around it. |
| `FLAG_OFF` | Keep the route disabled even if an observation later exists. |
| `CORE_UNAVAILABLE` | Do not select a new Core-mediated route; retain only the separately valid local-Mission rule. |
| `EDGE_BUNDLE_UPLOAD` | Upload only an approved synthetic EdgeBundle through the selected data path; no flight, motor, waypoint, camera, or gimbal action. |

`EDGE_BUNDLE_UPLOAD` is deliberately a non-actuating transfer check. It is not
wayline delivery, flight execution, camera control, or evidence of Mission
acceptance.

## Mission-latency measurement

Mission latency is `FIELD_REQUIRED`. A future approved field procedure must
capture monotonic send/receive/rejection timestamps, exact route binding,
Mission/contract decision (without secrets), raw-log digest, and operator
attestation. It must report the measurement separately from any acceptance
decision. HIL-0 records only `NOT_CAPTURED`; it reports no latency and no PASS.

The field procedure starts immediately before route generation and records monotonic
checkpoints after route generation, KMZ serialization, contract/KMZ digesting,
Ed25519 signing, durable pre-commit validation, journal fsync, and final dispatch
availability. It records wall-clock UTC only for correlation; elapsed calculations
use the monotonic clock. Compare both total and per-stage latency with the exact
Mission snapshot `notBefore`/`notAfter` and dispatch-envelope validity. Run warm and
cold samples, report count/p50/p95/max plus failures, and preserve build/config/raw
log digests. No threshold or PASS exists until the field procedure is approved;
therefore this gate is `FIELD_REQUIRED`.

## Offline CLI

The CLI accepts a JSON file containing all nine scenario captures explicitly.
For this HIL-0 version each capture must be `NOT_CAPTURED`, evidence references
must be empty, the genuine route-state signal must be `ABSENT`, and mission
latency must be `NOT_CAPTURED`. This deliberately prevents a locally invented
success result.

```bash
uv run python tools/hil/capability_runtime_hil.py emit \
  --input /private/hil0-captured-input.json \
  --output /private/hil0-capability-runtime-evidence.json

uv run python tools/hil/capability_runtime_hil.py validate \
  --input /private/hil0-capability-runtime-evidence.json
```

The output is canonical JSON (sorted keys, compact separators, terminating
newline) and validates against the v1 schema. `emit` reads and writes files
only; it has no network, Core, DJI SDK, deployment, or device code path.

The blocked artifact still records route/capability, pinned deployment and
freshness-policy digests, software build digest, empty physical/firmware identity
lists, empty observation/preflight sequences, Mission/provider `NOT_CAPTURED`, null
disconnect/reconnect times, blocker errors, empty log digests, and overall
`INCONCLUSIVE`. Empty values are evidence of non-capture, not omitted claims. A
later field runner may populate a successor schema, but raw capture remains separate
from CAP-2 qualification.

## Software harness and physical handoff

The automated software harness is
`tests/contract/test_capability_runtime_transport_seam.py`, supplemented by
`services/dji-gateway/tests/test_runtime_transport.py`. It runs the real localhost
HTTP transport and Gateway coordinator while simulating only the external route
signal/provider. CAP-5 regressions cover expiry, wrong route/port, Mission DENY and
flag OFF; transport regressions cover disconnect/Core unavailable and malformed
responses. Every denial keeps the provider uncalled.

For physical HIL, replace only the simulated Unix `ROUTE_STATUS_V1` peer with the
PSDK application. Run the observation producer using a separate Edge-device
credential, Core with the isolated trusted deployment and explicit authority, and
the loopback Gateway runner with its Gateway credential. Capture raw Core, Gateway,
PSDK and monotonic timing logs and calculate digests offline. Do not edit this
blocked artifact into PASS; a field-capable successor evidence schema is required.

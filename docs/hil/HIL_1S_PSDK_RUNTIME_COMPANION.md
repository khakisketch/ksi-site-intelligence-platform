# HIL-1S PSDK_MANIFOLD / EDGE_UPLINK Runtime Companion

## Scope

HIL-1S closes the first-party software gap between the native `ksi_psdk_app`,
DJI PSDK MOP, the Gateway Unix adapter, and CAP-5 `RuntimeRouteObservationV1`.
It does not create qualification, approval, activation, Mission permission, or
physical HIL evidence.

Owner: `edge/psdk-app`.

Invariants:

- INV-011: route state is not a signed Mission Contract.
- INV-012: disconnect blocks a new route invocation but does not cancel an
  already valid local Mission Contract.
- INV-041/042: software linkage and runtime observation remain separate from
  verified device/equipment authority.

## Exact route and availability

```text
canonicalCapabilityId = EDGE_UPLINK
integrationPath       = PSDK_MANIFOLD
subjectKind           = EDGE_ROUTE_PORT
subjectPortId         = explicit deployment value
Unix endpoint         = /run/ksi/psdk.sock
```

The route is AVAILABLE iff all three synchronized facts are true:

```text
DjiCore_ApplicationStart succeeded
AND exact reliable MOP channel has an accepted peer
AND EDGE_BUNDLE_UPLOAD listener/handler is registered
```

The companion starts only after `DjiCore_ApplicationStart`. A MOP accept sets
`mopConnected`; receive close/error clears it; the next successful accept is a
new connection generation. Every `ROUTE_STATUS_V1` query receives a fresh signal
ID and timestamp. No static configuration or process heartbeat sets connected.

At each companion instance construction, Linux `getrandom(..., GRND_NONBLOCK)`
must provide a fresh 128-bit process-incarnation nonce. Construction fails closed before creating the
Unix listener or worker threads if safe entropy cannot be obtained; there is no
wall-clock, counter-zero, or default fallback. The status identity is:

```text
psdk-route-<32-lowercase-hex-incarnation>-<route-generation>-<request-sequence>
```

The nonce makes Gateway-derived observation IDs collision-resistant across
process restarts. It is observation/idempotency identity only: it is not part of
tenant, deployment, route subject, CAP-4, feature-flag, or Mission authority.

## Unix wire protocol

The server accepts one JSON document terminated by write EOF and a single final
newline, maximum 64 KiB. The socket is mode 0600 under a non-symlink directory
owned by the process user. Startup refuses a live/ambiguous endpoint, removes
only a same-owner refused stale socket, and shutdown removes only its recorded
device/inode.

`ROUTE_STATUS_V1` requires the exact six request fields used by the Gateway
producer and returns exactly the v1 signal fields, including both
`integrationPath` and `subjectPortId`.

`EDGE_BUNDLE_UPLOAD` requires exact tenant/site/mission/Edge identity,
idempotency key, object reference, and SHA-256. It sends only that bounded
metadata frame over the accepted reliable MOP handle. It has no inbound action
dispatcher and discards peer-originated bytes. The source includes no DJI
FlightController, Waypoint, motor, gimbal, camera, payload, or media API.

## Software evidence

- The C++ contract test covers all eight three-fact combinations, status
  identity, bounded upload, disconnect/reaccept, unavailable denial, active
  socket refusal, stale socket cleanup, and deterministic shutdown.
- The interoperability test runs the real C++ Unix server with the production
  Gateway `PsdkMopRuntimeObservationProducer` and `UnixJsonBridgeClient`, then
  publishes through the authenticated HTTP ingress into the real CAP-5
  journal/store and runtime projector. Current HIL-1P regression uses an
  isolated journaled CAP-2/3/4 fixture authority and the production KSI MOP
  peer receiver; only the hardware-dependent vendored MOP transport is replaced
  by an in-memory function-table seam. It covers AVAILABLE,
  UNAVAILABLE, same-process retries, process A/B restart identity, audit history,
  stale state, and post-restart runtime-ready recovery.
- The real `ksi_psdk_app` target is built in the pinned arm64 Ubuntu 20.04 / gcc
  9 builder and links all eight `DjiMopChannel_*` functions from the vendored
  PSDK 3.16 `libpayloadsdk.a`.
- The source/ELF flight-boundary checker remains a post-build gate for this
  companion tier.

The repository-supported memory/UB diagnostic is opt-in and never changes a
normal or device build:

```bash
cmake -S edge/psdk-app -B build-hil1s-asan \
  -DKSI_PSDK_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
  -DKSI_PSDK_APP_BUILD_TESTS=ON \
  -DKSI_PSDK_APP_ENABLE_SANITIZERS=ON
cmake --build build-hil1s-asan --target ksi_psdk_route_companion_tests -j
ctest --test-dir build-hil1s-asan --output-on-failure \
  -R 'ksi_psdk_route_companion_contract|ksi_gateway_psdk_companion_unix_interop'
```

`KSI_PSDK_APP_ENABLE_THREAD_SANITIZER=ON` provides a mutually exclusive,
non-PIE host TSan diagnostic for the same targets. Its CTest launcher uses
`setarch -R` because this host's randomized address layout collides with the
TSan shadow mapping before test code starts. A sanitized diagnostic PASS
increases confidence but is not the production binary and does not prove that
the exact unsanitized aarch64 device artifact is race-free.

These are software-only claims. They do not establish that M4D/Manifold 3
firmware exposes a working peer path.

## Physical HIL handoff

Before changing `HIL_ROUTE_1` to `VERIFIED_HIL`, an approved isolated session
must provide:

1. exact M4D, RC, Manifold, firmware, DPK, MOP channel and subject-port identity;
2. real peer connect and a fresh AVAILABLE observation through Core;
3. an approved synthetic EdgeBundle upload with no device action;
4. physical MOP disconnect, observation loss/expiry and provider denial;
5. reconnect, new signal/observation and restored new-invocation eligibility;
6. Mission DENY and feature-flag-OFF denials with no provider call;
7. raw PSDK/Gateway/Core logs, monotonic timestamps and artifact digests;
8. separate operator approval for any CAP-2/3/4 authority or feature flag.

Until those artifacts exist, the correct result is
`BLOCKED_HARDWARE_TOPOLOGY`, not `READY_FOR_PHYSICAL_HIL` or `VERIFIED_HIL`;
the pinned PSDK 3.16 material has not established a supported client endpoint
for the Manifold-hosted server. Production activation remains blocked. The
topology evidence and exact entry conditions are in
`docs/hil/HIL_1R_PHYSICAL_READINESS.md`.

The production observation lifecycle and separately provisioned peer receiver
added after this companion stage are documented in
`docs/hil/HIL_1P_PSDK_PRODUCTION_ROUTE.md`.

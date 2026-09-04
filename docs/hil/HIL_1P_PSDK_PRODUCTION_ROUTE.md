# HIL-1P — PSDK_MANIFOLD / EDGE_UPLINK production software seam

HIL-1P closes production software assembly for one non-actuating route. It does
not prove a physical DJI channel and it does not change CAP-1 through CAP-5
authority.

## Stage boundary

| Stage | Scope | Maximum software-only conclusion |
|---|---|---|
| HIL-0 | CAP-4/CAP-5 authority, Gateway preflight and fail-OFF runner | authority plumbing exists |
| HIL-1S | PSDK `Bind/Accept` companion, Unix protocol and route facts | companion/server software exists |
| HIL-1P | canonical Unix client, scheduled observation publication and separately provisioned PSDK `Connect` receiver | software seam assembled; physical entry remains topology-gated |
| Physical Route-1 HIL | exact aircraft, RC, Manifold, firmware, DPK and real peer | may produce HIL evidence after review |

`READY_FOR_PHYSICAL_HIL` is not `VERIFIED_HIL`. Feature flags, CAP-2 evidence,
CAP-3 approval and CAP-4 activation remain separate operator-owned decisions.
The current maximum verdict is stricter: pinned DJI PSDK 3.16 evidence does not
document PSDK payload-to-PSDK payload connectivity or a channel address for the
Manifold-hosted server, so `HIL_ROUTE_1=BLOCKED_HARDWARE_TOPOLOGY`. See
`HIL_1R_PHYSICAL_READINESS.md`.

## Production observation path

The only Gateway-side owner of `/run/ksi/psdk.sock` I/O is
`UnixJsonBridgeClient`. Both `EDGE_BUNDLE_UPLOAD` and `ROUTE_STATUS_V1` use its
same JSON-plus-EOF framing, 64 KiB request/response bound, timeout, duplicate-key
rejection and transport-error behavior. `PsdkMopRuntimeObservationProducer`
does not open a socket.

The owner-only runner configuration explicitly pins:

- trusted organization, site, Gateway and Edge identities;
- exact provider-derived `subjectPortId` (`<adapterId>.edge_uplink`);
- configured deployment, equipment, runtime build and freshness policy digests;
- exact Core-owned freshness TTL, explicit minimum refresh margin and a polling interval that
  preserves that margin;
- separate Edge observation and Gateway preflight token files with different credential values;
- pinned Core HTTPS certificate and fixed PSDK Unix endpoint.

At startup the runner creates one canonical client, one producer, one
`HttpCoreRuntimeObservationPublisher` and one bounded observation loop. A probe
failure produces `REPORTED_UNAVAILABLE`; a Core publication failure is recorded
and retried once at the next configured poll. It never retains or synthesizes
AVAILABLE. Core remains authoritative for expiry, ordering and projection. The
loop stops and joins before the runner closes its journal. `/ready` reports only
service readiness.

The production lifecycle regression also removes Core after one AVAILABLE
publication: the next poll records a transport failure, creates no cached Core
record or local ALLOW, and leaves the original explicit `expiresAt` unchanged.
The existing CAP-5 stale boundary and uncached preflight tests then keep new
route invocation fail-closed until a fresh publication and preflight succeed.

AVAILABLE remains derived only from:

```text
psdkInitialized
AND mopConnected
AND handlerRegistered
```

The response has no trusted final availability field.

## PSDK peer receiver

The peer is a separately provisioned `edge/psdk-app` build mode. It uses the
vendored PSDK `Init/Create/Connect/RecvData/Close/Destroy` calls against an
explicit PSDK server address and channel. CMake rejects enabling the peer and
the HIL-1S `Bind/Accept` server in the same binary, so software cannot connect
the server to itself or manufacture `mopConnected`.

The receiver accumulates partial reads up to 64 KiB and accepts only the exact
existing `EDGE_BUNDLE_UPLOAD` metadata frame: schema, operation, route,
capability, subject port, organization/site/Edge identity, mission, object
reference, lowercase SHA-256 and idempotency key. Duplicate JSON keys, malformed
or extra fields, wrong identity, oversize data and idempotency conflicts fail
closed. Accepted metadata is data only; no arbitrary dispatch, flight, waypoint,
motor, mission-start, camera or gimbal API is exposed. The current frame
protocol defines no acknowledgement, so the receiver does not invent one.

`DjiMopChannel_SendData` success is only a sender-to-vendor-channel handoff. It
does not establish peer receipt or validation. Physical evidence must correlate
an independent peer accepted-frame transition, operation ID, metadata/digest,
receipt timestamps and peer raw-log digest as defined by
`HIL_1R_PHYSICAL_READINESS.md`.

## Software evidence and remaining physical gate

Host tests exercise the companion, canonical Unix client, producer,
authenticated HTTP publisher, real Core observation journal/projector, real
journaled CAP-2/3/4 fixture authority, Core preflight, Gateway coordinator and
the KSI peer receiver. The end-to-end fixture substitutes only the vendored MOP
function tables with an in-memory duplex channel; both production MOP lifecycle
classes and the exact frame encoder/parser remain in the seam. Separate native
peer tests cover partial receive, malformed/oversize/wrong-identity input,
connect failure, disconnect and reconnect. Sanitizer success is software
evidence only.

Physical Route-1 HIL still requires all items in the HIL-1S handoff, including
exact device/firmware/DPK identity, a real peer connection, raw disconnect and
reconnect logs, a fresh Core observation, non-actuating synthetic bundle receipt
and independent feature/Mission/CAP denial checks. No physical evidence is
created by this document or by host tests.

The KSI PSDK `Connect` receiver is not currently an executable physical topology
for the Manifold-hosted `Accept` server. Vendor headers document MSDK/OSDK as
clients, while the only pinned PSDK `Connect` sample targets a DJI camera
payload. Do not schedule physical HIL until the exact peer endpoint is resolved.

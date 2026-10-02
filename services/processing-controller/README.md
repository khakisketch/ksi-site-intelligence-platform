# services/processing-controller

Processing job scheduling and worker registry.

## External validation worker

`ksi-external-validation-worker` runs only the fixed inspection,
checkpoint-validation, and relative-volume lanes.  Supply an absolute,
owner-protected `external-validation-worker-config.v1` file and a separate
absolute `0600` Core token file:

```text
ksi-external-validation-worker --config /absolute/worker.json --core-token-file /absolute/core.token
```

The configuration pins the HTTPS Core origin and worker UUID, object endpoint
addresses, one existing inspection UDS identity, one existing measurement UDS
identity, protocol limits, an inspection profile, and the signed measurement
manifest plus revocation and trusted-public-key pins.  The token is never read
from configuration, an environment variable, or a default path.

The entrypoint creates no listener, container, directory, socket, account, or
host provisioning state.  It exits closed when the configuration, token,
manifest/revocation proof, UDS identity, Core response, deadline, lease, or
currentness proof is unavailable.  `SIGINT` and `SIGTERM` request scheduler
stop; active lane cleanup and the shared Core session close before exit.

Local contract tests exercise the fixed configuration, loopback object reads,
private publication, Core-client transports, and synthetic UDS protocol seams.
They do not prove a deployed host's socket ownership, rootless containment,
systemd policy, credentials, Core reachability, or physical/HIL acceptance.

## External Analysis worker

`ksi-external-analysis-worker` uses an exact `analysis-worker-config.v1`
configuration and a separate absolute owner-protected `0600` token file:

```text
ksi-external-analysis-worker --config /absolute/analysis-worker.json --worker-token-file /absolute/analysis-worker.token
```

The JSON configuration must be a regular non-symlink file owned by the
effective user and group, mode `0600`, single-link, and no larger than 64 KiB.
It pins the literal-IP Core URL, worker instance, five runtime identity fields,
static object origins and addresses, and bounded HTTP, object, and polling
limits. Unknown or duplicate fields, invalid endpoints, and malformed values
fail before a Core client is created. The bearer token is never accepted in the
configuration, command arguments, environment, or a default path. The previous
explicit argument form remains available for local compatibility; it has no
production defaults.

Configuration checks and synthetic recovery tests are local evidence only;
they do not establish host ownership, service isolation, deployed identity,
Core connectivity, or pilot acceptance.

## Activated daemon listener ACL

The inspector and V2 measurement daemons accept only one systemd-activated
AF_UNIX listener.  The launcher owns the listener; the separately named worker
UID receives only the exact POSIX ACL rights needed to use it.  For distinct
identities, the socket is `0660` with owner `rw`, that worker's named `rw`, no
group or other rights, and an `rw` ACL mask.  Its private parent is `0710` with
owner `rwx`, that worker's named `x`, no group or other rights, and an `x` mask.
Neither node may have a default ACL.  The worker may traverse the trusted
directory chain but may not write any ancestor.  A sticky ancestor such as
`/tmp` is accepted only when its next path component is launcher-owned, so the
worker cannot rename or replace the private subtree.

The next host-preparation gate needs two new isolated identities: a launcher
owner and a worker.  Do not use the current `ksi` account as the production
worker because it belongs to the Docker group.  The launcher must also retain
its private systemd user bus and its Docker daemon socket at their existing
owner-only `0600` boundary; this listener rule does not relax either one.

The daemons only read and re-prove this state before each accepted connection.
They do not create accounts, directories, listeners, ACLs, or default trust.
Local ACL fixtures validate the parser and fail-closed path; cross-UID runtime
connection, systemd activation, and rootless host proof remain host acceptance
work.

## Spatial data preparation worker (explicit local lane)

The generated-only mounted test flow now connects actual TIFF inspection to this
distinct worker's real loopback source/PUT transport, a separate framed child/native
preparation, Core acceptance and an HTTP-only external consumer. Independent source
cell/mask/grid/hash comparison and participant journal replay are local software
evidence, not host containment or public/customer export acceptance. The generated
launcher is test-only; no production fallback is added. See
[local verification and remaining gates](../../docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md).

`ksi-spatial-data-worker` consumes only the dedicated Spatial Data V1 job API;
it is not an Analysis activation or a managed reconstruction worker. Supply an
absolute owner-protected `spatial-data-worker-config.v1` JSON file and a separate
absolute, owner-only `0600` bearer file:

```text
ksi-spatial-data-worker --config /absolute/data-worker.json --core-token-file /absolute/data-worker.token
```

`--once` attempts one bounded poll/job; it is **not** a dry run. No environment
token, default credential, dynamic factory, caller URL or shell command is accepted.
The config model is `spatial_data_worker_config.SpatialDataWorkerConfigV1`. It pins
the HTTPS Core origin, complete sealed policy/runtime/activation snapshots, a detached
Ed25519 activation signature, operator-trusted public key, activation revocations,
finite response/heartbeat/poll limits, exact object origins/static addresses and an
already-existing owner-only `0700` workspace. Config/token/workspace ancestor chains
must not be symlinked or writable by other users. Config and token reads are bounded;
activation/current config and the separate token are re-read for every Core operation.

Before polling, the worker verifies the separately provisioned launcher executable
(`0500` or `0700`, full SHA-256) and a `0600` containment-proof file (full SHA-256).
The proof binds the exact policy/runtime, resource envelope, output cap, namespace
inodes, mount-inventory digest, child identity and expiry. The launcher must exec the
fixed `spatial_data_entrypoint` with the supplied workspace and sealed proof descriptor;
it must not create a listener or expose the parent's credentials. The worker neither
installs this launcher nor creates namespaces, accounts, ACLs, images or proof files.

The child applies address-space/CPU/file-size/descriptor/process/core-dump rlimits
before readiness. Parent and child check actual namespace separation, pinned mount
inventory, absent capabilities, no-new-privileges, seccomp, network devices/routes and
finite kernel limits before decoding. Missing or unverifiable proof blocks execution.
Actual mount suitability, cross-identity workspace mapping, image/executable/build/lock
correspondence, namespace/host containment and operational memory limits require
independent host acceptance; a config digest or Python timeout does not establish them.

Source bytes are bounded, privately staged and fully rehashed before the child. Native
DSM/ORTHO preparation writes only `candidate.tif`; no resampling, reprojection, height
adjustment or accuracy assessment occurs. The parent accepts only finite framed JSON,
checks receipt/source/grid/provenance bindings, rehashes the candidate, obtains the exact
Core-owned upload grant, PUTs exact bytes without bearer/cookies, and renews before
completion. Lease/currentness loss never publishes a result. Process-group cleanup and
private workspace cleanup run on every exit; a pending launch or failed reap retains
ownership and blocks another launch. SIGINT/SIGTERM request bounded cooperative stop.
Core retains durable job history and uploaded-target cleanup obligations even when a
completion/failure reply cannot be obtained.

Local checks:

```text
.venv/bin/python -m pytest tests/contract/test_spatial_data_worker.py tests/contract/test_spatial_data_sandbox.py tests/contract/test_spatial_data_worker_config.py -q
```

These tests use generated TIFFs, real loopback object sockets, mounted Core authorities,
synthetic launcher seams and an actual rlimit child. They do not establish deployed
containment, immutable-provider/Terra compatibility, quantitative accuracy, customer
acceptance or release readiness. Core HTTP phase timeouts and bounded filesystem reads
do not prove a hard deadline for arbitrary blocked host I/O. Guarded public downloads
and operational retention cleanup are separate Core delivery responsibilities.

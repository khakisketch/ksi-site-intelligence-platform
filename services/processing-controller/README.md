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

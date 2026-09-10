# External reconstruction private-candidate runtime

This directory is the versioned assembly boundary for the separate
`ksi-external-rc` candidate. It never upgrades, stops, shares volumes with, or
reconfigures `ksi-phase2-staging`.

The host has two new identities:

| Identity | Responsibility | Prohibited access |
|---|---|---|
| `ksi-validator` | polls Core and calls the two fixed UDS lanes | sudo, rootful Docker, user D-Bus, ambient Docker socket |
| `ksi-inspector` | owns rootless Docker and the contained inspection/measurement launchers | Core worker credential, rootful Docker |

The validator configuration is a private `0600` regular file and points only
to absolute paths. Its Core token is a different private `0600` file. No
token, catalog, signing key, customer artifact, image digest, SBOM, scanner
report, or authority record belongs in this directory's examples.

The systemd services invoke an absolute executable path under
`/usr/local/lib/ksi-external-runtime/bin/`. Bootstrap does not install that
application bundle; a later release-evidence gate must install and bind it to
the reviewed source/image/SBOM record before any service is enabled.

## Host preparation

Before preflight, the root operator creates the separate private ledger
directory. It is deliberately outside the candidate runtime root so collecting
a new ledger never creates partial runtime state:

```bash
install -d -m 0700 -o root -g root /var/lib/ksi-external-runtime-preflight
deploy/bin/external-runtime-host-preflight.sh \
  --output /var/lib/ksi-external-runtime-preflight/preflight-YYYYMMDD.json
```

It records only host facts and the literal status `PREPARED, NOT APPLIED`. It
does not create accounts, edit subordinate maps, start a daemon, query Docker,
or inspect customer data.

The bootstrap command is intentionally separate because it changes accounts,
subordinate maps, user-systemd configuration, and the new launcher's rootless
Docker daemon. It requires a root operator, a fresh private ledger, and a
released copy of the templates:

```bash
deploy/bin/external-runtime-host-bootstrap.sh \
  --preflight-ledger /var/lib/ksi-external-runtime-preflight/preflight-YYYYMMDD.json \
  --template-root /usr/share/ksi-external-runtime/systemd \
  --template-manifest /usr/share/ksi-external-runtime/systemd/manifest.sha256 \
  --template-manifest-sha256 sha256:REPLACE-WITH-REVIEWED-MANIFEST-HASH
```

It requires a complete ledger no older than fifteen minutes and compares the
account records, complete subordinate-map hashes, inspector UID/runtime root/
D-Bus socket, candidate runtime root, and rootful Docker socket before it
changes anything. It can reconcile only the known staged account/map markers
after a new matching ledger; it never deletes unknown runtime state. It locks
both subordinate-map files while allocating a matching `65536` range.

The validator remains a system service. Inspection and measurement sockets,
services, and their slices are installed into the `ksi-inspector` user manager,
with `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` verified before rootless
Docker setup. Their service units retain `LISTEN_PID` and `LISTEN_FDS` and bind
only that user's Docker socket and D-Bus read-only into the sandbox. Bootstrap
installs units but does not enable the validator, inspection, or measurement
application services.

The root-owned template root, every required non-symlink template file, and a
root-owned `manifest.sha256` are checked before bootstrap. The operator passes
the reviewed manifest SHA256 explicitly; each manifest entry must match the
exact template bytes. A changed, group-writable, substituted, or extra template
fails before account or map changes.

The socket templates deliberately start as `0600` launcher-owned sockets. A
systemd socket directive cannot express the required named-user POSIX ACL
without granting group access. Before enabling either socket, a separately
reviewed root-owned ACL activation procedure must prove the exact private
parent and named `ksi-validator` ACL required by
`services/processing-controller/README.md`. Until then the units remain a
fail-closed deployment asset, not an activated worker lane.

## Candidate lifecycle

Make an owner-protected `0600` file outside the repository from
[`../.env.external-reconstruction.example`](../.env.external-reconstruction.example).
Then use only that file:

```bash
deploy/bin/external-runtime-stage.sh prepare --env-file /absolute/candidate.env
deploy/bin/external-runtime-stage.sh status --env-file /absolute/candidate.env
deploy/bin/external-runtime-stage.sh verify --env-file /absolute/candidate.env
```

`prepare` only creates the explicitly selected candidate directory and copies a
private template. `status` reads the `ksi-external-rc` project. `stop` uses
`docker compose stop`, preserving candidate volumes and never targeting the
existing Phase 2 stack.

`verify` and `start` require an exact clean source checkout and a current-
operator-owned private release-evidence record. The record must bind the
source commit; the two fixed local RC tags and their exact Docker image IDs;
each nonempty external runtime image reference and image ID; and the paths and
SHA256 values of the actual SBOM and scanner artifacts. The lifecycle parser
accepts only the reviewed `KEY=VALUE` environment keys and never sources the
file as shell code. Even with that evidence `verify` and `start` return
`BLOCKED_QUANTITATIVE_AUTHORITY` until a real,
independently controlled catalog, policy, evidence-currentness, and input
capability authority can be assembled in Core. The Compose profile contains no
placeholder authority and no ordinary processing worker or NodeODM service.

## Scope boundary

This candidate may use synthetic state only after the separate deployment
blockers are cleared. It is not customer acceptance, customer-export
compatibility, OCI/SBOM provenance, a functional contained runtime, DJI/Pilot
support, physical HIL, or field acceptance. The real DJI Pilot 2 handoff stays
manifest-first: request one exact source path only after this candidate has a
reviewed passing deployment activation.

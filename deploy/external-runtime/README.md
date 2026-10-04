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
without granting group access. Bootstrap installs but never starts the
root-owned `ksi-external-runtime-socket-acl.service`; it also installs its
reviewed helper at the exact path
`/usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl`.

After a root operator has separately started both reviewed user socket units,
the operator may manually start that ACL service. It refuses a missing,
symlinked, non-socket, wrong-owner, wrong-mode, linked, or replaced inode, and
it refuses any parent or socket ACL that differs from its unopened baseline.
For the brief mutation, it removes the launcher owner's write permission from
the parent, which is itself required to be beneath a root-owned,
launcher-nonwritable runtime root. It revalidates both socket inodes while the
parent is frozen, applies a transactional ACL change, restores any partial
write on failure, and restores the exact parent ACL. Re-running safely
normalizes pristine, active, or mixed socket states.

Only then does it add the named `ksi-validator:rw-` entries to both sockets;
it re-proves the exact root-owned `0770` parent (named `ksi-inspector:rwx`,
named `ksi-validator:--x`, group/other none, no default ACL) and `0660` sockets
(`ksi-inspector:rw-`, `ksi-validator:rw-`, group/other none, no default ACL).
The manual proof command is:

```bash
/usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl \
  verify --json --untrusted-user nobody
```

It performs real AF_UNIX `connect(2)` probes as `ksi-validator` to both
application sockets, obtains one fresh server-recorded `SO_PEERCRED` receipt
from each without sending a worker request, and verifies every required
untrusted socket access denial is `EACCES` or `EPERM`. Only when both receipts
and all denial checks succeed does its JSON record have status
`OBSERVED_SERVER_PEER_CREDENTIAL` and exit zero. This is not host acceptance,
release acceptance, or HIL acceptance; it does not start an application or
authorize a release.

## Candidate lifecycle

The lifecycle gate consumes the reviewed v2 peer-protocol JSON proof:
a fresh root-owned helper
must return `OBSERVED_SERVER_PEER_CREDENTIAL` for both lanes and denial for
`nobody`; a saved receipt is not accepted.

Make an owner-protected `0600` environment file outside the repository from
[`../.env.external-reconstruction.example`](../.env.external-reconstruction.example).
It must name the existing `KSI_EXTERNAL_RC_OPERATOR_DIR` at exactly one
dedicated candidate root (`/etc/ksi-external-runtime/operator` or
`/var/lib/ksi-external-runtime/operator`). The directory must already contain
`workflow.json`, `provider.json`, `secrets/`, and `signing/`; it cannot be a
repository, candidate state, customer-data, or shared project directory.
Its `authorityJournalPath` is fixed to
`/var/lib/ksi/data/external-quantitative-authority.jsonl`; an operator path or
`/tmp` path is refused.

All supplied private credential and signing files must be regular,
non-symlinked files owned by runtime UID `10001`, owner-readable, and
inaccessible to group and other. A public signing manifest/key may be owned by
root or UID `10001`, but must be non-writable by other identities and readable
by runtime UID `10001`. The root init-state validation and Core/Dashboard both
run against that runtime identity. The candidate never changes ownership,
generates a credential, signing key, catalog, or authority record.

Use the candidate environment file only for `prepare`, `verify`, and `start`:

```bash
deploy/bin/external-runtime-stage.sh prepare --env-file /absolute/candidate.env
deploy/bin/external-runtime-stage.sh verify --env-file /absolute/candidate.env
deploy/bin/external-runtime-stage.sh start --env-file /absolute/candidate.env
```

For fixed-project diagnostics and fail-safe shutdown, use no environment file:

```bash
deploy/bin/external-runtime-stage.sh status
deploy/bin/external-runtime-stage.sh stop
```

`prepare` only creates the explicitly selected candidate directory and copies a
private template.

`status` and fail-safe `stop` run without an environment file. `status` only
lists containers carrying the exact
`com.docker.compose.project=ksi-external-rc` label. `stop` re-lists that same
label scope, rechecks each immutable container ID's label, and stops only those
IDs. These diagnostics and fail-safe shutdown actions do not require a clean
checkout, current release evidence, image IDs, or any Compose interpolation;
they never target `ksi-phase2-staging`.

`verify` and `start` require an exact clean source checkout, a canonical
current-operator-owned private `release-evidence.v1` record, and a separate
current-operator-owned private
[`external-runtime-host-binding.v1`](../../contracts/schemas/external-runtime-host-binding.v1.json)
or additive [`v2`](../../contracts/schemas/external-runtime-host-binding.v2.json)
record. The canonical record retains only its source, immutable product/runtime
references, and product SBOM/scanner metadata. The host binding records the
exact canonical-record hash, source commit, observed Docker image IDs and
repository digests, and absolute artifact paths, hashes, byte counts, and
types. It must contain Core and Dashboard observations, separate product-owned
inspector and measurement runtime observations. The canonical
`externalRuntimeImages` field remains the complete exact source supply-chain
inventory; no canonical reference may be omitted, added, or substituted. The
host-binding `externalRuntimeImages` field instead contains exactly the three
external references used by this candidate Compose file: Caddy, MinIO, and
MinIO Client. That three-reference host set must be an exact subset of the
canonical inventory—this does not require the other build-only inventory images
to be installed on the candidate host. Runtime SBOMs must
be valid CycloneDX JSON. Strict runtime scanner validation accepts the existing
`scanner.name`/`scanner.schemaVersion` envelope or the reviewed native Grype
`0.120.0` profile, without rewriting the original report. Native reports require
DB status `valid: true`, DB schema `v6.1.10`, well-formed findings, and exact
`source.target.imageID` equality with the independently verified expected config
identity: v1 uses the host `dockerImageId` directly; v2 derives it from the
verified original OCI archive, without changing the actual host ID.
The verifier reads, hashes and parses the same bounded regular-file payload,
rejecting duplicate/non-finite JSON, symlinks and observed file replacement.
DB schema is not report schema, and format validation is not a vulnerability
waiver, tool-signature/DB-authenticity proof or activation approval.

**V1 target limitation:** the inspected Docker 29 containerd store returns
an OCI index as `.Id`, while Grype reports a config digest. `--platform` inspection
returns a platform manifest, still not the config digest. The native equality
path therefore **blocks on this target**. Do not substitute a config ID in a
host record observed as an index, relabel a manifest, or add fabricated scanner
fields. V2 supplies the separately reviewed cryptographic index/platform/config
link. Each runtime requires an `ociArchive` with exactly absolute path, SHA256,
positive byte length (at most1GiB) and `type: oci-archive`. The read-only stdlib
verifier checks the original archive against the independently host-verified
index, exactly one Linux/ARM64 manifest, all archived/referenced blob identities,
source revision and role-specific user/fixed command. Only its successfully
derived config ID becomes the scanner expectation; v2 native reports must also
declare Linux/ARM64. Unknown/mixed versions and incomplete/failed links block.

The archive reader checks raw regular/directory TAR headers (no extensions,
extraction or decompression), at most4096members,1MiB JSON metadata,64descriptors
per graph node and depth8. It hashes/reads/rechecks one protected descriptor;
PAX/GNU/sparse/link/special payloads never reach parser expansion. Attestation
blobs are hash-checked, **not signature-verified**. A successful historical image
link does not make it a clean-current-source release: both config revision and
canonical source must genuinely agree. Core/Dashboard/registry/security/signed
execution/current Core/live socket and application bundle gates are unchanged.
See [local evidence](../../docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md#python-repair-and-native-scanner-consumer--2026-10-04).

Each observed repository-digest list
must include the immutable release reference's canonical repository digest.
The observed immutable Core and Dashboard Docker image IDs—not
`ksi-external-rc-*:local` lookup tags—are exported only after this validation
and become those Compose image references. The three external Compose services
retain their literal digest pins, while their created containers are still
matched to the host-binding image IDs. The lifecycle parser accepts only the
reviewed `KEY=VALUE` environment keys and never sources the file as shell code.

Before `verify` or `start`, the lifecycle rechecks the exact image observations,
operator bundle shape, and fresh socket proof. The shared root-owned parent
may retain its bootstrap `0711` traversal mode; it must not be group/other
writable. The operator child and its credentials remain private. Likewise,
the root-owned public ACL helper may retain its installed `0755` mode, but
must be owner-executable and not group/other writable. These checks never
repair permissions or replace the required live peer proof.
It first runs the exact verified
Core image through an opt-in Compose service as UID/GID `10001:10001` in a disposable,
networkless, read-only container with only
`secrets/` and `signing/` mounted at the fixed `/state` paths read-only. Its
`--validate-only` command verifies the real UID `10001` ownership, permissions,
symlink resistance, UTF-8 secrets, and signing bytes without modifying state.
It then runs the same image through a separate opt-in Compose service as UID
`10001` with the complete operator bundle read-only and an UID `10001`-owned
tmpfs at `/var/lib/ksi/data`. The command
creates only an empty journal and lock in that disposable tmpfs so the workflow
loader can verify its fixed durable layout; it neither creates persistent
journal state nor invents authority. The ordinary Core preflight loads the two
fixed configuration paths, verifies the signed provider/catalog/workflow
configuration, and must return `CONFIG_VALIDATED`. This means configuration
only: the provider has not bound its receipt journal or attached to Core, and
no result is quantitatively eligible.

`start` runs release-evidence validation, the exact-image credential
`--validate-only` command, socket-ACL proof, and authority preflight once,
then renders Compose config and performs its single
`docker compose up -d --no-build --pull never --wait`. It does not rebuild,
pull, stop, remove, or delete a candidate. Before readiness can succeed it
inspects every created candidate container (init-state, identity, Core,
Dashboard, MinIO, bucket-init, and Caddy) and requires the Docker image ID to
equal its verified host-binding ID. It then queries the running Core's
loopback-only `/ready/external-authority` endpoint through the Compose service.
That endpoint must return only
`{"status":"PROVIDER_CONFIGURED"}`; a 503 or
`EXTERNAL_AUTHORITY_UNAVAILABLE` blocks the command while preserving the
running candidate for operator inspection. `verify` reports the detached
`CONFIG_VALIDATED` preflight state only when Core is not running; when it is
running, it reports `PROVIDER_CONFIGURED` as runtime attachment/currentness
without reporting any eligibility decision. Neither output is a customer export
compatibility, HIL, or field-acceptance claim.

The Compose profile contains no placeholder authority and no ordinary
processing worker or NodeODM service.

## Scope boundary

This candidate may use synthetic state only after the separate deployment
blockers are cleared. It is not customer acceptance, customer-export
compatibility, OCI/SBOM provenance, a functional contained runtime, DJI/Pilot
support, physical HIL, or field acceptance. The real DJI Pilot 2 handoff stays
manifest-first: request one exact source path only after this candidate has a
reviewed passing deployment activation.

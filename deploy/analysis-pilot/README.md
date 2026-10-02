# Analysis worker service candidate

**PREPARATION CANDIDATE; NOT DEPLOYED.** This directory is a reviewable local
service template. No account, credential, systemd unit, host, network rule,
Tailnet route, or customer OIDC application was changed or installed.

The service runs only the FPO-01 `ksi-external-analysis-worker` entrypoint as
the separate `ksi-analysis` user and group. Core remains the authority for
Analysis activation, worker admission, lease fencing, and durable results. The
worker has no listener. Its protected JSON config pins one literal-IP Core URL,
the five runtime identity values, static object endpoints, and finite transfer
limits. The bearer token is a separate file and is never passed in argv or the
environment.

## Host prerequisites

Before an operator installs this candidate, the host owner must review and
prepare all of the following outside this repository:

1. Create the dedicated `ksi-analysis` user and group with a recorded UID/GID.
   Verify `id -nG ksi-analysis` shows no `docker`, `sudo`, or administrative
   group membership. Do not reuse the general `ksi` account.
2. Install the reviewed worker application bundle at the absolute
   `/opt/ksi-analysis/` path. The tree, interpreter, entrypoint, dependencies,
   runtime image digest, image/runtime identity and SBOM must be immutable to
   `ksi-analysis` and
   match the separately reviewed release hashes. The unit deliberately fails
   when its installed executable is absent.
3. Prepare `/etc/ksi-analysis/` as an operator-controlled, non-writable parent.
   Provision `config.json` and `worker.token` as separate regular files owned
   by `ksi-analysis:ksi-analysis`, each mode `0600`, one link, with no symlink
   component. FPO-01 opens every parent path component without following
   symlinks, checks each ancestor's ownership and write permissions, and checks
   the target file's owner, group, mode, link count, size, and stable metadata
   while reading. A sticky shared temporary ancestor is accepted only when its
   next component is owned by the service user. Never store the token in the
   JSON, an environment file, shell history, or this repository.
4. Compare all five config runtime identity fields with the exact signed
   `AnalysisActivationV1` runtime identity, policy/resource digests, dedicated
   worker principal, organization, and current validity at Core. A matching
   local config alone does not activate Analysis. A missing, expired, or
   mismatched activation must leave new work denied while history remains
   readable.
5. The unit denies all IP egress except loopback by default. Before any use of
   non-loopback Core or object endpoints, the host owner must review the exact
   static addresses in the protected config and add only those addresses to a
   root-owned systemd drop-in; no wildcard or public range is accepted. The
   worker transport separately rejects DNS, redirects, and unpinned origins.
   Verify the host's cgroup/BPF support and the effective unit policy before
   starting it.
6. Check `systemd-analyze verify` and `systemd-analyze security` against the
   installed unit and systemd version. Confirm the account, executable,
   configuration, token, and network rules before enabling anything. This
   candidate does not enable or start itself.

`PrivateTmp=yes` is the only writable scratch area: the measurement code uses
anonymous temporary files for bounded input snapshots. The system filesystem,
application bundle, and config/token paths are read-only in the service. It
has no state directory, database, socket listener, Docker socket, user bus,
extra Linux capability, or writable host path. Output goes to the system
journal; no token or capability header should be logged.

## Operator checks

After an independently approved host installation, verify the effective unit
and current authority before start. Record the runtime tree hash, SBOM hash,
config hash, activation ID/digest/validity, Core and object address allowlist,
and service identity in the host evidence ledger. The activation signing key
and worker token remain outside the repository and are never printed.

For an approved restart rehearsal, check `systemctl status
ksi-analysis-worker.service` and inspect only sanitized worker status from
`journalctl -u ksi-analysis-worker.service`. Confirm Core still rejects a stale
lease attempt after interruption and that the same immutable historical result
remains readable. Exit status 2 is treated as a configuration/identity error
and is not restart-looped. A restart does not renew or recreate activation.

Back up the protected config and token only through the host's approved
encrypted secret-backup process. Record access controls, retention, restore
operator, and a restore test that verifies file hashes, owner/group, mode,
single-link status, and activation validity without exposing token bytes.
Rollback stops and disables the service, preserves logs and durable Core
history, and restores the last reviewed application/configuration under the
same identity and endpoint checks. Do not delete historical Analysis records
or treat rollback as revoking Core authority.

## Evidence not supplied by this candidate

The account and group do not exist because of this change. The executable,
activation, token, config, systemd drop-in, Tailnet HTTPS route, customer OIDC
issuer/audience/subject mapping, cgroup firewall behavior, host logs, backup,
restore, restart rehearsal, remote CI, and customer acceptance have not been
verified. This template proves none of those host or release conditions and
does not expose a public port, create a public listener, or install a
development OIDC issuer.

## Local Compose and customer OIDC candidate

`compose.yaml` is a separate Compose project containing only Core, Dashboard,
MinIO and one bucket initializer. It has no build steps, generic processing
worker, NodeODM, development identity issuer, Caddy, or device runtime. Core
and Dashboard image references must be reviewed immutable `@sha256:` IDs.
Dashboard, Core API and MinIO object traffic publish only to literal
`127.0.0.1` host bindings; the MinIO console is not published. Core and
Dashboard remain non-root, read-only containers with dropped capabilities and
`no-new-privileges`. Core data and MinIO object data persist in their own
storage locations. The one-shot `bucket-init` service uses MinIO root access
only to create the evidence bucket idempotently. Compose creates or changes no
MinIO user, secret, group, or policy. Core does not receive MinIO root
credentials. An existing same-name MinIO user or policy is not proof that its
credential and grants are safe, and the pinned `mc` container has no approved
machine-readable IAM reconciliation tool in this candidate.

### MinIO Core credential gate

Before starting or restarting Core, a MinIO administrator must independently
verify the supplied Core access key and secret against the pinned MinIO
release. The key must be enabled and authenticate with the exact secret in the
protected env file. Its only direct policy must be the bucket-scoped
`ksi-analysis-evidence-rw` policy, with `GetBucketLocation` on
`arn:aws:s3:::ksi-analysis-evidence` and `GetObject`, `PutObject`, and
`DeleteObject` on `arn:aws:s3:::ksi-analysis-evidence/*`. `MemberOf is empty`
must be confirmed so no group policy adds grants. The policy must contain no
other statements, resources, actions, or principals. Confirm the bucket exists
and exercise only the approved Core object operations with this identity.

Compose does not check these IAM facts and cannot detect later out-of-band
credential or policy drift. Record the verification and exact MinIO release
and client versions in the host evidence ledger. If the user, secret, policy,
group membership, or grants change, stop Core and repeat the verification
before restarting Core. Any unverified fact blocks Core startup by operator
procedure; no automatic repair is attempted.

The host operator must create a protected env file outside this repository and
provide every `KSI_ANALYSIS_PILOT_*` input consumed by the Compose file. The
read-only `preflight.py --env-file /absolute/path/to/pilot.env` command checks
the bounded env syntax, immutable image references, three Tailnet HTTPS
origins, customer OIDC URLs, protected authority/secret files, one active
Analysis worker principal digest, and the loopback-only Compose boundary. It
prints a fixed success or failure message and never prints env values. Run it
before `docker compose --env-file /absolute/path/to/pilot.env -f
deploy/analysis-pilot/compose.yaml config`. Compose config output contains
expanded environment values, including object-store credentials; do not share
or log that output. The example credentials in contract tests are synthetic.

Required operator inputs are:

| Input | Required content |
| --- | --- |
| Core and Dashboard image IDs | Exact reviewed release references ending in `@sha256:<64 lowercase hex>`; no mutable tag or local build. |
| Tailnet hostname and app/API/objects origins | Customer-approved HTTPS `*.ts.net` hostnames, pathless origins, with app origin matching the selected hostname. |
| Customer OIDC | HTTPS issuer, audience, HTTPS JWKS URL, and registered client ID. The Core subject registry at `AUTHORITY_DIR/oidc-subject-registry.json` must use the exact same issuer and contain only approved `iss+sub` mappings and explicit Site/WorkArea grants. |
| Dashboard secret files | `SECRET_DIR/oidc-client.secret` and `SECRET_DIR/dashboard-session.secret`, protected files owned/readable by Dashboard UID 10001 and each at least 32 bytes; never put contents in Compose variables or Git. |
| Core state and authority | `STATE_DIR` owned by UID/GID 10001 with mode 0700. `AUTHORITY_DIR` contains the Core signing-keys directory, device-attestation keys, OIDC registry, `analysis/runtime.json`, `analysis/activation.json`, `analysis/activation-keys.json`, `external/workflow.json`, and `external/provider.json`. Protected files must be valid, private, readable by Core UID/GID 10001 and mounted read-only. |
| Core token identities | `CORE_PRINCIPAL_TOKENS_JSON` contains exactly one active dedicated `ANALYSIS_WORKER` identity matching the signed activation, plus at most one explicitly Site/WorkArea-scoped `ANALYSIS_MCP_CLIENT` if Codex MCP is enabled. No general Processing/device token is provisioned in this profile. Values are token SHA-256 digests; raw bearer tokens do not appear here. |
| MinIO and ports | Long random MinIO root credentials plus a separately provisioned and verified bucket-scoped Core access key/secret, all held only in the protected env file; three distinct unused loopback host ports for Dashboard, Core API and MinIO objects. Core receives only the scoped credentials. Compose interpolation and container inspection expose environment values to host administrators; protect the host and never share rendered configuration or `docker inspect` output. |

Register the Dashboard redirect URI with the customer's OIDC provider as
`<APP_ORIGIN>/api/auth/callback/ksi-oidc`. The issuer, audience, JWKS URL,
client ID, callback registration, subject identities, organizations, Site and
WorkArea grant lists, allowed algorithms, token lifetime, and consent/AI-egress
policy require customer IT and KSI review. Core re-verifies OIDC subjects from
its protected registry; JWT `ksi_*` claims do not grant authority. A missing
registry, missing mapping, issuer mismatch, missing activation, invalid
signature, or stale activation must remain a closed startup or work-admission
condition.

### Tailnet and host gates

The Compose file only binds local TCP ports; it does not configure Tailscale
Serve, install certificates, create DNS names, open a firewall, or change a
host. After separate host authorization, the operator must configure HTTPS
Tailnet routing from each approved app/API/objects origin to its matching
loopback port, then verify the effective route from an authorized Tailnet
client and verify the same origins are unreachable from public and non-Tailnet
networks. The designated `*.ts.net` names and host Serve topology must be
confirmed with the Tailnet administrator; this repository does not assume that
arbitrary subdomains can be served by one Tailnet node.

The bridge network does not itself restrict outbound traffic. Before use, the
host owner must allow only the customer OIDC issuer/JWKS and the minimum
approved image/object-store operations required by the reviewed release,
while retaining Core-to-MinIO and Dashboard-to-Core internal traffic. Record
the effective host firewall and container egress behavior. Do not publish any
port on `0.0.0.0`, `::`, a LAN interface, or a public address. Do not add a
development issuer, public reverse proxy, general worker, or NodeODM to this
project. Tailscale Serve commands are an operator action and were not run for
this candidate.

Before a separately authorized start, compare runtime, policy, resource
envelope, worker identity and organization digests in the protected Core
material with the signed `AnalysisActivationV1`, check validity and verification
key role, review exact image/SBOM provenance, then rehearse Core readiness,
OIDC login/callback, Analysis admission, 64 KiB coverage range, object access,
worker restart/fencing, and backup/restore. The Compose template and preflight
do not establish those release or customer conditions.

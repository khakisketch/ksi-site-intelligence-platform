# External reconstruction private-staging procedure

Status: PREPARED — NOT DEPLOYED

Authority: ADR-KSI-036, `PRODUCT_CONSTITUTION`, `FINAL_DECISION_LEDGER_v1.0`,
`DOMAIN_INVARIANTS`, and
[`deploy/external-runtime/README.md`](../../deploy/external-runtime/README.md).

The private candidate is a new Compose project named `ksi-external-rc`. It is
not an in-place deployment of the existing synthetic Phase 2 stack. Its named
volumes, loopback ports, Tailnet routes, state directory, secrets, signing
keys, and worker identities are new. Do not use this procedure to alter
`ksi-phase2-staging`.

Host preparation writes its fresh ledger only under the separate root-owned
mode-`0700` directory `/var/lib/ksi-external-runtime-preflight/`. Bootstrap
accepts only a root-owned mode-`0600` ledger from that directory and a root-
owned template root whose exact `manifest.sha256` hash is supplied on the
command line. The manifest must cover every installed unit/drop-in and each
file is re-hashed before any account, map, D-Bus, or Docker action.

Before any activation, an owner must supply all of the following outside Git:

1. A current-operator-owned private canonical `release-evidence.v1` record
   from an exact clean source checkout, plus its separate owner-only
   `external-runtime-host-binding.v1` record. The binding must contain the
   canonical-record hash, Core/Dashboard observed image IDs, separate
   product-owned inspector/measurement immutable references and observed image
   IDs/repository digests, and the path, type, byte count, and SHA256 of their
   actual SBOM and scanner artifacts. Canonical `externalRuntimeImages` remain
   dependency pins and are verified separately; they do not declare product
   runtime roles. The lifecycle gate re-hashes and validates the runtime JSON,
   requires each recorded and locally observed repository-digest list to
   include the release reference's canonical repository digest, and re-inspects
   every named local image; a claimed digest alone is insufficient.
2. A private, real worker configuration, Core token, inspector configuration,
   measurement configuration, manifest, revocations, public keys, host proof,
   resource limits, and authority-currentness inputs. The repository examples
   intentionally contain unusable placeholders.
3. A reviewed root-owned activation procedure for the named POSIX ACL on both
   launcher sockets. The committed socket units stay `0600` until that proof
   exists; no shared Docker group or group-readable socket is an allowed
   substitute.
4. An approved Core production assembly that injects independent catalog,
   policy, evidence-currentness, and input-capability authorities. A mounted
   file cannot create that authority. Current `production.py` keeps the
   quantitative workflow absent.

The local identity issuer uses the candidate bridge network and publishes only
its `8080` service port to loopback. Core fetches JWKS through the private
`identity:8080` service address while retaining the externally visible issuer
origin. Tailnet routing is an owner-controlled external ingress decision; the
candidate `stop` action only stops its own Compose project.

The following evidence remains outside this procedure: customer upload and
vendor-export compatibility, actual operator usability, DJI Pilot 2 data,
DJI/PSDK device behavior, physical HIL, and field acceptance.

If the private candidate later passes its own deployment acceptance, request
one exact local source path for a customer-controlled externally reconstructed
orthomosaic and optional DSM. Do not scan `download/`, customer folders, or
raw field-media locations. Preserve the source files and collect their
checksums, capture interval, CRS, vertical reference, producer/version and
provenance in a manifest before issuing any upload grant.

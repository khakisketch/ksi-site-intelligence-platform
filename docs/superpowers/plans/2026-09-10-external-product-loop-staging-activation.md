# External Product Loop Private Staging Activation Implementation Plan

> **For Codex:** Execute each task in order. Keep the existing `ksi-phase2-staging` deployment and its volumes intact. Stop at any fail-closed evidence boundary rather than substituting placeholder authority.

**Goal:** Operate the merged external reconstruction product loop on a separate private staging candidate with a dedicated validation worker and contained inspection/measurement runtime, then prepare the exact real DJI Pilot 2 upload handoff.

**Architecture:** Core and Dashboard remain the durable product and operator boundaries. A `ksi-validator` system service polls Core and connects only to two pre-provisioned Unix sockets. A distinct `ksi-inspector` user owns both socket-activated daemons and one dedicated rootless Docker engine; every attempt is admitted against signed manifests, exact OCI identities, cgroup/systemd evidence and bounded protocols. The existing Phase 2 staging remains unchanged; candidate state, ports, tokens, keys and volumes use new names.

**Tech Stack:** Python 3.12/uv, systemd user units and socket activation, rootless Docker, Docker Compose v2, FastAPI Core, Next.js Dashboard, Tailscale Serve.

---

## Implementation contract

```text
Requirement IDs:
- REQ-INT-101..104, REQ-SEC-101, REQ-OPS-101/102, REQ-UX-101
- EXT-STAGE-01 additive private staging candidate without mutating Phase 2
- EXT-STAGE-02 dedicated validator and launcher identities
- EXT-STAGE-03 separate inspection and measurement UDS activation
- EXT-STAGE-04 dedicated rootless Docker with exact OCI evidence
- EXT-STAGE-05 fail-closed operator configuration and secret handling
- EXT-STAGE-06 synthetic end-to-end product-loop acceptance before customer data
- EXT-STAGE-07 exact real DJI Pilot 2 upload handoff

Owner module:
- deploy/ owns host and staging assembly
- services/processing-controller/ owns the independently operated validator and contained launchers
- services/core/ owns durable workflow authority
- apps/dashboard/ owns operator intent and presentation only

Acceptance criteria:
- Existing ksi-phase2-staging containers, volumes, ports and Tailscale routes remain unchanged.
- New identities have no sudo/rootful-docker access; launcher Docker socket and user bus are 0600.
- Validator cannot connect to Docker or D-Bus and can connect only to named inspection/measurement sockets.
- All configs are absolute owner-protected regular files and all image/manifest/trust inputs are exact.
- Candidate Core/Dashboard and worker/launchers pass focused contract, smoke and synthetic product-loop checks.
- No customer data is read until the user supplies an exact approved path.

Contracts affected:
- No wire/schema semantic change planned.
- Add deployment-asset contract tests for systemd units, bootstrap/preflight scripts and candidate isolation.
- Add production assembly tests proving quantitative routes stay fail-closed without real authority injection.

Reference assets:
- Existing runtime-activation proposal and reviewed unit drop-ins under CODEX_HOME/work-state.
- Existing compose.synthetic-staging.yaml and phase2-staging.sh patterns.
- No runtime import from references/repos.

Adoption decisions:
- Additive candidate deployment; do not upgrade in place.
- Host systemd services for validator/launchers; do not mount privileged host sockets into the product Compose network.
- One launcher identity and rootless engine, with distinct inspector and measurement sockets/services.
- Synthetic staging keys/manifests prove software execution only; production/customer authority remains separate.

Files to change:
- deploy/compose.external-reconstruction.yaml
- deploy/.env.external-reconstruction.example
- deploy/external-runtime/* (versioned unit templates and non-secret examples)
- deploy/bin/external-runtime-host-preflight.sh
- deploy/bin/external-runtime-host-bootstrap.sh
- deploy/bin/external-runtime-stage.sh
- deploy/README.md
- tests/contract/test_external_runtime_deployment_contract.py
- docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md
- docs/ops/EXTERNAL_RECONSTRUCTION_STAGING.md
- the narrow Core production composition/configuration files identified by the failing assembly test

Tests:
- New deployment contract test first (RED then GREEN)
- bash -n and systemd-analyze verify
- focused external worker/inspector/measurement contract tests
- docker compose config and candidate smoke
- synthetic full product-loop E2E

HIL or real-device assumptions:
- None for implementation and synthetic acceptance.
- DJI Pilot 2 data must already be reconstructed externally into supported orthomosaic/DSM artifacts.
- DJI/PSDK flight control and physical HIL remain separate.

License/data implications:
- No customer file is committed or copied into the repository.
- Contained runtime images must carry exact OCI/SBOM evidence; third-party license review stays explicit.
- Current cloud due-diligence restriction limits this activation to private development/synthetic data until cleared.

Rollback:
- Stop only new candidate and new user services; disable only new linger/units.
- Preserve diagnostic state and do not delete accounts, subordinate ranges, volumes or evidence without separate cleanup authority.
- Existing Phase 2 deployment remains the immediate fallback.
```

### Task 1: Freeze deployment contract in failing tests

**Files:**
- Create: `tests/contract/test_external_runtime_deployment_contract.py`

1. Assert required assets exist and contain no ambient Docker host, TCP listener, embedded token or mutable image tag.
2. Assert worker, inspector and measurement identities/units are distinct and all paths are absolute.
3. Assert bootstrap preserves rootful Docker/current staging and requires a clean preflight ledger.
4. Run the focused test and confirm RED because assets do not exist.

### Task 2: Add versioned host runtime assets

**Files:**
- Create: `deploy/external-runtime/systemd/*`
- Create: `deploy/external-runtime/examples/*`
- Create: `deploy/bin/external-runtime-host-preflight.sh`
- Create: `deploy/bin/external-runtime-host-bootstrap.sh`

1. Add exact system and user unit templates for validator, inspector socket/service and measurement socket/service.
2. Add private user-bus/rootless-Docker drop-ins and accounting slices.
3. Add a read-only preflight that records identities, subordinate maps, sockets, user namespace and cgroup facts without secrets.
4. Add an idempotent, stop-on-drift bootstrap that creates only the two new locked accounts and the launcher's empty rootless Docker runtime.
5. Run focused tests, `bash -n`, and `systemd-analyze verify` until GREEN.

### Task 2A: Wire Core production authority fail-closed

**Files:**
- Modify: narrow files under `services/core/src/ksi_core/` selected by the existing production composition boundary
- Modify: `tests/contract/test_production_assembly.py` or a focused new production-wiring contract test

1. Write a failing test proving production external quantitative routes cannot activate from config mounts alone.
2. Inject only a real `ExternalQuantitativeCatalogAuthorityPort`, policy/evidence-currentness source and input-capability issuer through the production assembly.
3. Keep missing authority typed and closed; do not generate fixture policy/digests or silently use in-memory authority in production.
4. Prove the existing managed processing, tenant and journal boundaries remain unchanged.

### Task 3: Add candidate preparation and lifecycle tooling

**Files:**
- Create: `deploy/bin/external-runtime-stage.sh`
- Create: `deploy/external-runtime/README.md`
- Modify: `deploy/README.md`
- Create: `deploy/compose.external-reconstruction.yaml`
- Create: `deploy/.env.external-reconstruction.example`

1. Prepare an owner-only candidate directory outside the repository.
2. Render a distinct `ksi-external-rc` Core/Dashboard/MinIO/Caddy project. External reconstruction does not require NodeODM or the ordinary processing worker in this profile.
3. Generate separate Core worker credentials, exact non-secret configs, signed synthetic manifests and OCI proof records without printing secrets.
4. Build/pin candidate images, install reviewed units and expose only new Tailnet HTTPS routes/loopback ports.
5. Support `prepare`, `start`, `status`, `verify`, and `stop`; omit destructive reset.
6. Assert it never calls `docker compose down` for `ksi-phase2-staging` and never changes existing Tailscale routes.

### Task 4: Verify software and host isolation

1. Run deployment contract tests and the focused inspector/measurement/worker suite.
2. Execute read-only host preflight and compare protected resources before/after bootstrap.
3. Apply bootstrap only when all stop conditions are green.
4. Verify UID/GID separation, subordinate maps, 0600 bus/socket modes, rootless daemon ownership, and denied cross-identity access.
5. Record actual facts in the external work-state checkpoint; do not promote them to customer acceptance.

### Task 5: Start an isolated private staging candidate

1. Prepare candidate state and build exact source images from this reviewed commit.
2. Start candidate Core/Dashboard/storage under a distinct Compose project and volumes.
3. Start rootless launchers and validator through systemd.
4. Verify readiness, authentication, object transport, UDS identity and contained no-op/synthetic attempts.
5. Compare existing Phase 2 container IDs, volumes and routes with the frozen baseline.

### Task 6: Exercise the full synthetic product loop

1. Register and seal supported synthetic orthomosaic/DSM artifacts.
2. Run inspection and sanitized display publication.
3. Produce checkpoint/use decision and relative-volume request/result.
4. Exercise review, reobservation proposal/approval, planning-only successor WorkOrder, assignment/due/close/reopen and authenticated report link.
5. Record exact receipts and browser-visible outcomes; do not label them real customer proof.

### Task 7: Real DJI Pilot 2 handoff and UX observation

1. Produce a manifest-only upload checklist for the user's externally reconstructed orthomosaic and DSM, including CRS, vertical reference, capture interval, producer/tool versions and checksums.
2. Ask for one exact local source path only after the private candidate passes and do not scan unrelated folders.
3. Upload and execute the same flow without moving or modifying the source files.
4. Record real-user friction separately and implement bounded UX corrections through a new reviewed diff.
5. Keep DJI/PSDK physical HIL and field acceptance explicitly open until actual devices and field authority are available.

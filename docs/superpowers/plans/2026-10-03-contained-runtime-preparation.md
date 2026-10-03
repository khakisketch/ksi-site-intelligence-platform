# Contained runtime preparation implementation plan

> For agentic workers: use `executing-plans` for this bounded operator task.

**Goal:** Prepare the existing dedicated rootless inspector route without bypassing
release, signed execution, policy, or containment gates.

**Architecture:** Reuse `deploy/external-runtime/` and the processing-controller
daemon/configuration loaders. Static preparation is distinct from application activation.
Core remains the policy and tenant authority; no alternative public TIFF parser is introduced.

**Tech stack:** existing Bash/Python, systemd user units, rootless Docker, cgroup v2.

**Spec:** `deploy/external-runtime/README.md`, existing inspector sandbox amendment selected
by the current EXT-VAL ledger, and ADR-KSI-036. The Human on 2026-10-03 selected dedicated
runtime installation/configuration/start preparation. That supersedes the older no-host-work
restriction only for this bounded task; it does not supply missing release/signing authority.

## Global constraints and task record

- Requirements: EXT-VAL-01/05/06/08, REQ-OPS-101/102, REQ-SEC-101.
- Owner: deployment templates and processing-controller launcher assembly.
- Acceptance: source-bound prepared static bundle; exact observed prerequisites; no application
  activation unless actual release, signed configuration and host enforcement evidence pass.
- Contracts affected: none. Reuse existing configuration/execution/host-binding contracts.
- Reference assets/adoption: existing preflight, bootstrap, socket helper, daemon loaders and tests;
  reuse only KSI-owned code. No reference-submodule edits or imports.
- Files: this plan, private task evidence/checkpoint, a create-once root-owned template release,
  and the exact installed dormant socket helper if its predecessor is identified and preserved.
- Invariants: INV-054 source/image/SBOM/scanner binding remains mandatory; INV-055 Core admission
  remains authoritative; INV-051/053 external bytes do not become managed/quantitative authority;
  INV-060 no customer/foreign-tenant data or credential access.
- Tests: existing deployment, inspector host proof, listener identity, catalog, operator artifacts,
  measurement configuration and release-evidence tests. Prepared dependencies only, offline/no sync.
- HIL/real-device assumptions: none; actual containment and customer/field acceptance remain distinct.
- License/data: acquired CC BY4 public originals remain private/ignored and unopened by raster code.
- No scanner/tool installation, credential/key generation, customer data, public exposure, push,
  staging restart, rootful daemon operation, bootstrap replay, or test-authority promotion.
- Rollback: preserve predecessor helper bytes/hash/mode before replacement; retain both template
  releases. No service/ACL activation, account/subordinate-map changes, or automatic rollback execution.

## Review focus

- Installed template drift: do not overwrite an unknown bundle; create a new immutable release path.
- Older helper protocol: identify the predecessor in Git; back it up before replacing only that file.
- Source mismatch or substitution: pin clean HEAD and every copied file hash, reject symlinked or
  writable target ancestry, recheck after copy and before replacement.
- Static installation confused with activation: no enable/start/reload/ACL operation in this task's
  static preparation; dormant services must remain dormant.
- Absent release/authority inputs: do not generate placeholder manifests, trust roots, policy values,
  credentials or synthetic inspection reports to unlock public data.

## Tasks

### Task 1: Observe the existing dedicated runtime

- [x] Revalidate clean task branch and local-main integration target.
- [x] Run existing root preflight into a fresh private ledger; inspect fixed runtime metadata only.
- [x] Read dedicated rootless Engine metadata, unit state, template/helper hashes, not credentials.
- [x] Record image/source uncertainty and distinguish unreadable paths from absent paths.

Expected: observations, not application readiness or permission to parse data.

### Task 2: Prepare current source-bound static resources

- [x] Run relevant existing contract tests; require zero failures before installation.
- [x] Prepare exactly the bootstrap's twelve required template files and canonical checksum list
  from clean `928436f68ea271eaf4045112ab2a03bb590bbbeb`; independent read-only review.
- [x] Create a new root-owned release under `/usr/share/ksi-external-runtime/releases/<source SHA>/`
  without changing the older template tree or user units.
- [x] Preserve the known predecessor helper in a create-once root-private backup; replace only
  `/usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl` with reviewed exact bytes.
- [x] Verify ownership/mode, required file hashes and unchanged dormant unit/daemon state.

Expected: current static prerequisite installed; no functional contained runtime claim.

### Task 3: Respect application activation gates

- [x] Check actual application bundle and protected configuration availability (absent).
- [ ] Require exact image/source/SBOM/scanner and signed execution/OCI-pair/revocation evidence.
- [ ] Install/start daemons only if those inputs genuinely exist and the established host checks pass.
  Otherwise record this task as blocked, with exact missing inputs; no fallback or placeholder.
- [x] Keep public inspection/preparation/independent pixel-mask comparison explicitly unrun until
  its own approved and verified execution route is available.

## Evidence and state

Private task ledger: `.opencode/artifacts/contained-runtime-preparation-20261003/progress.md`.
Source baseline: `928436f68ea271eaf4045112ab2a03bb590bbbeb` on the existing isolated
`integration/readiness-20261002` worktree; local-main target initially equal and clean.
The current EXT-VAL product slice and human acceptance state are unchanged.

## Result — static preparation verified; application activation blocked

- Existing relevant tests:159passed7.67s. Four operator admission regressions observed RED,
  then operator plus same suite:163passed7.60s; prepared dependencies, offline/no sync.
- Independent review verified source/predecessor/template identity and bounded scope. Important
  operator findings were fixed before root application: root-owned reviewed script snapshot,
  shared bootstrap lock, inactive+disabled/static admission and actual account UID resolution.
- Actual root copy/hash/mode, all twelve installed files, predecessor backup and unchanged old
  template/user-unit state verified. Existing rootless daemon unchanged; no application activated.
- Root receipt: `/var/lib/ksi-external-runtime-preflight/static-install-20261003-928436f.json`;
  SHA-256 `10d97bc00cd94add128b45e9da6330d646cefe9846f88d70e0d859d5623a4259`.
- Backup: `/var/lib/ksi-external-runtime-preflight/helper-backup-20261003-928436f/`.
- Installed static checksum-list SHA-256:
  `5d1e95e25ac5eeaa6a4f419a1bee7884ab6483e0a49d59857ba73edcdd03bb35`.
  The list is reordered, content-equivalent to the source list, not its original file hash.
- Installed helper's actual negative proof command returned1/no positive JSON with absent
  application sockets. This proves blocking, not functional parsing or host containment.
- Task3 remains blocked: configured application binaries/configs absent; current immutable
  image/SBOM/scanner/host and signed execution/OCI-pair/revocation/trust inputs not supplied.
  No credential/key provisioning, scanner installation, synthetic authority or TIFF decode ran.

Minor audit limitations of the private one-shot installer remain recorded in its task ledger:
terse assertion diagnostics, partial predecessor metadata, named-tree hash rather than live-HEAD
binding, and one parent stat following an already verified root-only chain. None is represented as
application release evidence; the established application activation gates remain mandatory.

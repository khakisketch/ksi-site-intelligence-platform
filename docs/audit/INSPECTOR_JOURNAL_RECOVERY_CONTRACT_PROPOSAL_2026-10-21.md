# Audit-ledger recovery design — shared inspection launcher journal (2026-10-21 incident)

Status: **design proposal only — NOT approved, NOT implemented, NOT a repair.**
Subordinate to product authority and to the rebaseline task ledger.
Does not change any milestone, quantitative verdict, or Core report.
Sibling evidence doc: `docs/audit/PRODUCT_USE_INSPECTOR_JOURNAL_INCIDENT_2026-10-21.md`
(preserved/unresolved; this document does not alter it).

Why `docs/audit/` and not `docs/design/`: per repo routing this is an
audit-ledger preservation/recovery contract proposal, not a product-feature
design. It must live next to the incident evidence it references and must never
be mistaken for an approved product capability.

Scope constraints honored: no repo source edits, no commits, no servers, no
journal/daemon/cgroup/staging mutation, no inspection launch, no secrets, no
claim that the incident is repaired.

---

## 1. Verification of the two branches (read-only)

### 1.1 Preserved copies inspected

Under `/home/ksi/.cache/ksi-product-use-incident-20261021/` (directory 0700,
copies 0400; local `sha256sum` recomputed 2026-10-21, matches manifest):

| Copy | Bytes | Events | SHA-256 | Manifest match |
|---|---|---:|---|---|
| `pre-trim-backup-bdce3eed2cfd.jsonl` | 312594 | 384 | `bdce3eed…95ab64` | yes |
| `active-branch-snapshot-b56465cf8676.jsonl` | 462323 | 545 | `b56465cf…5745e84` | yes |
| `preservation-manifest.json` | — | — | — | `commonEventPrefix: 378`, `removedAttemptNonce: 511774dc-…`, `newBranchEventsAfterCommonPrefix: 167` |

Both files independently validate as hash chains (each event's
`previousEventDigest` equals the prior event's `eventDigest`; tails
`sha256:c1542bd3…` and `sha256:254a6ee4…` respectively). All six removed
events' `eventDigest` values recompute correctly from canonical JSON, and the
removed attempt's binding digest recomputes correctly
(`sha256:de1aa6e7…0ed`).

### 1.2 Divergence point (verified, not assumed)

- First 378 events are **parsed-identical** in both copies (378/378 equal).
- Shared anchor: line 378 (1-based) in both branches —
  `CLEANED`, nonce `602ef037-…`, `eventDigest sha256:79777bd1…093352`.
- Branch A (pre-trim) line 379: `INTENDED`, nonce `511774dc-…`,
  `previousEventDigest sha256:79777bd1…093352` (continues from the anchor).
- Branch B (active) line 379: `INTENDED`, nonce `303e2092-3929-4f91-92db-4d4eb0a93f2f`
  (timestamp `2026-10-20T15:03:45.258344Z`),
  `previousEventDigest sha256:79777bd1…093352` (**same anchor** — descends
  from event 378, skipping the six removed events).
- Branch B lines 379–545: 167 events across 23 distinct attempt nonces.
- **Laundering mechanism confirmed:** the retained 378 rows in the active file
  were reserialized (whitespace/canonical form), so a naive byte-prefix
  comparison would understate commonality; parsed-event comparison is the
  correct check, and it shows exact prefix equality through event 378.

### 1.3 The missing six events — exact content and order (backup lines 379–384)

Nonce `511774dc-9c52-4e7d-afd2-b872bba792ff` throughout; binding digest
`sha256:de1aa6e7…0ed` throughout. Timestamps are UTC canonical (`Z`).

| # | Phase | Timestamp | Linkage / payload |
|---|---|---|---|
| 379 | `INTENDED` | `2026-10-20T14:49:42.676376Z` | `previousEventDigest sha256:79777bd1…093352`; `eventDigest sha256:1cf322c1…ffc4a36`; full binding: `operation INSPECT`, `owner 48e4408a-…`, `containerName external-inspector-479103386d3df3f641ed6402d7a5ef6a`, `systemdSliceName ksi-inspector-a479103386d3df3f641ed6402d7a5ef6a.slice`, `systemdBaseSlice ksi-inspector.slice`, `cpuBudgetCounter 300000000`, 9 profile/manifest digests, staging plan `stagingName attempt-479103386d3df3f641ed6402d7a5ef6a`, `allocationNonce 8c2a3f9101bb19affc95dd4ec950b444`, root `{device 64769, inode 305297, mode 0o700, uid 997, gid 986}`, marker `markerLength 351`, `markerSha256 sha256:13cfca43…9f713` |
| 380 | `STAGING_ALLOCATED` | `2026-10-20T14:49:42.709060Z` | `prev sha256:1cf322c1…`, `ev sha256:7bf4d236…83c3299`; allocation receipt: marker `{dev 64769, ino 264876, mode 0o600, uid 997, gid 986, nlink 1, size 351}`, directory `{ino 524294, mode 0o700, nlink 2, size 4096}`, artifact `{ino 524295, mode 0o600, nlink 1, size 0}` |
| 381 | `INPUT_BOUND` | `2026-10-20T14:49:43.437083Z` | `prev sha256:7bf4d236…`, `ev sha256:46f2a05c…d4ee00`; sealed input: artifact `{dev 64769, ino 524295, size 80418}` (same inode as receipt — inode continuity holds), `observedSizeBytes 80418`, `observedSha256 sha256:9319a3ff…bb0638`, `readerMappingWitness sha256:ea95efed…802bcba` |
| 382 | `RUNTIME_PARENT_CREATING` | `2026-10-20T14:49:43.500523Z` | `prev sha256:46f2a05c…`, `ev sha256:cf73fe56…060677`; no additions (pending-create marker) |
| 383 | `CLEANUP_REQUIRED` | `2026-10-20T14:49:43.529905Z` | `prev sha256:cf73fe56…`, `ev sha256:94b1cb04…9874987866`; `disposition RUNTIME_PARENT_CREATE_AMBIGUOUS`, `cleanupOrigin RUNTIME_PARENT_CREATING` |
| 384 | `CLEANUP_FAILED` | `2026-10-20T14:49:43.557623Z` | `prev sha256:94b1cb04…`, `ev sha256:c1542bd3…f77083d751`; `reason EXACT_CREATE_OUTCOME_UNAVAILABLE` |

Lifecycle: `INTENDED → STAGING_ALLOCATED → INPUT_BOUND → RUNTIME_PARENT_CREATING → CLEANUP_REQUIRED(RUNTIME_PARENT_CREATE_AMBIGUOUS) → CLEANUP_FAILED(EXACT_CREATE_OUTCOME_UNAVAILABLE)`.
Terminal recorded state is **cleanup-failed with unknown create outcome** —
this is the state the startup-recovery proof in
`external_inspector_attempts.py:1251–1275` is designed to refuse to launder
(see §3).

### 1.4 Live-host check (read-only; NOT fully verifiable from here)

- `ssh … ubuntu@127.0.0.1 -p 2223` with the read-only key: `stat`/`sha256sum`/`wc -l`
  on `/var/lib/ksi-external-runtime/launcher/journal/attempts.jsonl` returned
  **Permission denied** (file is uid 997/gid 986, mode 0600; the `ubuntu` SSH
  user is not in that group). This is expected hardening, not evidence of
  tampering.
- The VM backup `/tmp/ksi-inspector-journal-backup-20261020-511774dc.jsonl`
  **is** stat-able: `size=312594`, matching the manifest's preserved pre-trim
  size exactly.
- Consequence: **concurrent-mutation stability of the live journal could not be
  re-verified in this pass.** All chain facts above rest on the two preserved
  copies whose hashes match the manifest. A future implementation pass must
  re-stat/hash the live journal (with a suitably privileged read-only identity)
  and record size/mtime/ctime stability across the read before admitting any
  recovery record (see §2.5 prerequisite P3).

---

## 2. Proposed recovery contract (append-only, separate stream)

### 2.1 Non-goals (hard constraints from the Human instruction)

1. **Neither branch is declared the validated canonical.** Both remain readable
   evidence; the incident is not repaired by this contract.
2. The six events are **never appended** to the live journal (would break
   predecessor validation at `external_inspector_attempts.py:862–863`,
   `_reload_from_handle`), **never inserted-and-rehashed** (rewrites recorded
   identities of all 167 later events), and the backup is **never restored
   wholesale** (destroys later evidence).
3. No `cleaned()` bypass of the recovery proof, no manufactured receipt.
4. The recovery is a **separately approved contract**, not an ad-hoc fix.

### 2.2 Stream placement (proposal — decision D1)

New file alongside the journal, owned by the same launcher persistence layer:

```text
/var/lib/ksi-external-runtime/launcher/journal/recovery-records.jsonl
```

- Same private-parent discipline as the journal
  (`external_inspector_attempts.py:887–928`: mode 0700 dir, 0600 file,
  uid/gid ownership, `O_NOFOLLOW`, fsync) — reuse, do not relax.
- Own independent hash chain (`previousRecoveryDigest`), **never interleaved**
  with `attempts.jsonl`. The V1 journal reader
  (`_reload_from_handle`, lines 844–874) must not accept recovery records;
  a separate reader validates them.
- Rationale for a file rather than Core journal/Core API: this is
  launcher-local persistence/recovery evidence. Core owns durable product
  authority (`services/core/`); letting Core adjudicate launcher-local
  lifecycle identity would cross the owner boundary (see §3.4).

### 2.3 Record shape — `external-inspector-recovery.v1` (proposal)

One record per incident nonce (exactly one for `511774dc-…` unless a future
approved record supersedes it, which itself must be a new record, never an
edit). Closed field set; unknown fields reject. Suggested exact fields:

```jsonc
{
  "version": "external-inspector-recovery.v1",
  "timestamp": "2026-..-..T..Z",            // canonical UTC, recorder clock
  "recordKind": "JOURNAL_TRIM_DISCLOSURE",  // closed enum, see below
  "attemptNonce": "511774dc-9c52-4e7d-afd2-b872bba792ff",
  "bindingDigest": "sha256:de1aa6e7…",
  // A. Removed-branch pointer (bytes, not trust)
  "removedBranch": {
    "sourcePath": "/tmp/ksi-inspector-journal-backup-20261020-511774dc.jsonl",
    "sourceSha256": "bdce3eed…",
    "eventRangeLines": [379, 384],
    "tailDigest": "sha256:c1542bd3…",
    "removedEventDigests": ["sha256:1cf322c1…", "sha256:7bf4d236…",
      "sha256:46f2a05c…", "sha256:cf73fe56…", "sha256:94b1cb04…",
      "sha256:c1542bd3…"],
    "terminalPhase": "CLEANUP_FAILED",
    "terminalReason": "EXACT_CREATE_OUTCOME_UNAVAILABLE"
  },
  // B. Retained-branch divergence pointer
  "retainedBranch": {
    "anchorDigest": "sha256:79777bd1…",     // shared event 378
    "anchorLine": 378,
    "firstDivergentNonce": "303e2092-…",
    "snapshotSha256AtRecord": "sha256:…",   // live head when recorded (P3)
    "snapshotEventsAtRecord": 0             // live count when recorded (P3)
  },
  // C. Staging linkage (the retained physical fact)
  "stagingBinding": {
    "stagingName": "attempt-479103386d3df3f641ed6402d7a5ef6a",
    "allocationNonce": "8c2a3f9101bb19affc95dd4ec950b444",
    "rootDevice": 64769, "rootInode": 305297,
    "artifactDevice": 64769, "artifactInode": 524295,
    "markerSha256": "sha256:13cfca43…",
    "observedAt": "2026-..-..T..Z",         // when re-observed (P4)
    "observationMethod": "READ_ONLY_STAT"   // closed enum
  },
  // D. Evidence relied upon
  "evidence": {
    "preservationManifestSha256": "sha256:…", // hash of the manifest file itself
    "observer": "…",                            // human/role identity, no secrets
    "observationWindow": ["2026-..T..Z", "2026-..T..Z"],
    "liveStabilityCheck": "STABLE|UNVERIFIABLE",
    "notes": "…"
  },
  // E. Outcome claim — the uncertainty representation (see §2.6)
  "outcomeClaim": "UNKNOWN_HISTORICAL_OUTCOME", // closed enum, see below
  "currentness": {
    "asOf": "2026-..-..T..Z",
    "liveHeadDigest": "sha256:…",
    "guarantee": "NONE"                      // this record never promises liveness
  },
  // F. Approval binding
  "approval": {
    "authorityRef": "…",                     // Human approval id / ledger entry
    "scope": "LAUNCHER_LOCAL_RECOVERY_RECORD_ONLY",
    "forbids": ["JOURNAL_REWRITE", "STAGING_DELETE", "CLEANED_BYPASS",
                "CORE_CANONICAL_DECLARATION"]
  },
  "previousRecoveryDigest": "sha256:…|null",
  "recordDigest": "sha256:…"                  // canonical-JSON hash over all above
}
```

`recordKind` closed enum (proposal): `JOURNAL_TRIM_DISCLOSURE`
(this incident) | `ABANDONMENT_ATTESTATION` (staging retired only after P4
proof) | `SUPERSESSION` (points at a prior recordDigest; original retained).

`outcomeClaim` closed enum (proposal — §2.6):
`UNKNOWN_HISTORICAL_OUTCOME` | `PROVEN_ABSENCE_AS_OF` (with `asOf` + method;
never retroactive) | `RETIRED_AFTER_PROOF` (only after the P4 retirement
proof; still references, never deletes, the disclosure).

`recordDigest` = `sha256:` + hex(canonical-JSON of the record minus
`recordDigest`), mirroring `_event_digest`
(`external_inspector_attempts.py:1468–1470`).

### 2.4 Admission (who may write, with what authority)

- Writer: the launcher maintenance path only, gated on an explicit
  `approval.authorityRef` that resolves to a Human-signed ledger entry whose
  `scope` includes `LAUNCHER_LOCAL_RECOVERY_RECORD_ONLY`. No daemon hot path
  (`external_inspector_launcher.py`, `external_inspector_daemon.py`) may mint
  recovery records during normal admission; the writer is a separate,
  explicitly invoked maintenance entrypoint (new module, see §3.1).
- The recorder clock must satisfy the same aware-UTC canonical-timestamp rule
  as `_append` (`external_inspector_attempts.py:809–812`) and
  `_canonical_timestamp` (lines 1552–1563).
- Duplicate `attemptNonce` with `recordKind JOURNAL_TRIM_DISCLOSURE` rejects
  (one disclosure per nonce); further facts arrive as `SUPERSESSION` records
  chained via `previousRecoveryDigest`.

### 2.5 Replay treatment (both branches readable; neither canonical)

- Provide a **dual-branch read API** (new, launcher-local): given the live
  journal plus the preserved pre-trim copy (referenced by hash, mounted
  read-only at verification time), expose:
  - `branch_a_events(nonce)` — the 6 removed events, verified against
    `removedEventDigests`;
  - `branch_b_events()` — the live journal as today;
  - `reconstructed_history()` — an **explicit, labeled derivation**: anchor
    (events 1–378) + flagged gap marker `REMOVED_NONCE_511774dc (see recovery
    record <digest>)` + branch B tail. The gap marker is part of the output;
    there is **no merged chain** and no synthesized `previousEventDigest`
    that would make the tail look continuous.
- V1 replay (`tests/replay/test_external_inspector_attempt_replay.py`) keeps
  failing closed on the removed nonce exactly as today
  (lines 532–561, 662–767): a recovery record must not make
  `recover_startup()` succeed for `RUNTIME_PARENT_CREATING`-origin attempts
  without an exact receipt. The recovery record is **evidence for humans and
  auditors**, not an input that softens `AttemptRecoveryUnavailable`.
- Conformance rule for any future test: replaying branch A must still raise
  `AttemptRecoveryUnavailable("runtime parent creation outcome is
  unavailable")` at `external_inspector_attempts.py:1272–1275`; replaying
  branch B must behave exactly as it does now.

### 2.6 Uncertainty representation (proven absence vs unknown outcome)

The incident doc's key epistemic line must become machine-readable vocabulary:

| Claim value | Meaning | Permitted downstream use |
|---|---|---|
| `UNKNOWN_HISTORICAL_OUTCOME` (current truth for `511774dc-…`) | A runtime parent may or may not have existed during `RUNTIME_PARENT_CREATING`; current absence proves nothing retroactively | Blocks staging retirement, blocks `cleaned()`, blocks any canonical declaration; human-readable "unknown, retained" |
| `PROVEN_ABSENCE_AS_OF <ts>` | At time `<ts>`, by method `<m>`, no exact container/cgroup for this nonce was observable | Supports *current* operational statements only; expires immediately (no caching as historical fact); never upgrades the historical outcome |
| `RETIRED_AFTER_PROOF` | Staging retired under a separately approved proof (P4), disclosure retained | Permits physical cleanup; journal history unchanged |

What is known today maps to: outcome `UNKNOWN_HISTORICAL_OUTCOME` +
a `PROVEN_ABSENCE_AS_OF` observation (prior read-only review: no exact Docker
container or bound parent/cgroup now; staging inode/hash bindings intact).
The design must carry **both facts side by side** and forbid the inference
"absent now ⇒ never existed ⇒ cleanup complete."

### 2.7 Fail-closed invariants preserved (must NOT be laundered)

- Uncertain identity → `STAGING_OWNERSHIP_UNCERTAIN` → `CLEANUP_FAILED`
  (`external_inspector_attempts.py:1455–1465`).
- Pending creation without exact receipt → `AttemptRecoveryUnavailable`
  (lines 1259–1275).
- Missing/unavailable observation → `EXACT_*_UNAVAILABLE` reasons, staging
  retained (replay tests 532–561, 662–767).
- Substitution/unavailable cleanup → admission closed, evidence retained
  (amendment lines 121–122, 146–149).
- A recovery record **adds a second stream**; it grants no transition in the
  V1 lifecycle (`_validate_transition` table, lines 1014–1066, untouched).

---

## 3. Contracts / touchpoints for a future implementation

### 3.1 Exact code touchpoints (all read-verified at main `a79137e4`)

| # | Location | Role in this design |
|---|---|---|
| T1 | `services/processing-controller/src/ksi_processing_controller/external_inspector_attempts.py:605–609` (`_DurableAttemptJournalCore` header) | Owner class of the V1 journal; recovery reader must live beside it, not inside `_append`/`_reload` paths |
| T2 | same file `:798–874` (`_append`, `_reload_from_handle`) | Must remain closed to recovery records; new reader validates the separate stream |
| T3 | same file `:930–955` (`_validate_event`) | V1 event shape stays closed; recovery record has its own version string and validator |
| T4 | same file `:1012–1080` (`_validate_transition`) | Transition table untouched — no new phase, no new edge |
| T5 | same file `:1251–1285` (`_adopt_preparent_receipt`) | The fail-closed proof this design preserves; replay tests pin it |
| T6 | same file `:1430–1465` (`_record_*_cleanup_failed`, `_record_uncertainty`) | Failure-recording helpers; recovery path must call, never bypass, these if it ever touches lifecycle state (default: it doesn't) |
| T7 | same file `:1468–1470` (`_event_digest`) | Digest pattern to mirror for `recordDigest` |
| T8 | `services/processing-controller/src/ksi_processing_controller/external_attempt_lifecycle.py` | Lifecycle orchestration; a future maintenance entrypoint plugs here, not into the daemon hot path |
| T9 | `services/processing-controller/src/ksi_processing_controller/external_inspector_systemd.py` | `adopt_if_prebound`/`stop_exact`/verify proofs; source of any future `PROVEN_ABSENCE_AS_OF` observation method |
| T10 | `services/processing-controller/src/ksi_processing_controller/external_inspector_launcher.py:511–553, 649–650, 1166, 1431–1448` | Admission-close latch; recovery design must label this *launcher admission*, not product readiness (§4) |
| T11 | `tests/replay/test_external_inspector_attempt_replay.py:532–561, 662–767` | Pin fail-closed behavior; new tests extend, never weaken, these |
| T12 | `docs/superpowers/specs/2026-09-07-external-inspector-docker-sandbox-amendment.md:120–148` | Accepted amendment: retained immutable attempts, admission-off rollback |

### 3.2 Owner boundary

**Launcher-local persistence/recovery contract.** Owner:
`services/processing-controller/` (journal + lifecycle + systemd adapter).
Explicitly **not**: a Core API change (no new endpoint, no Core journal
entry, no `services/core/` migration), **not** a new public security surface
(no new UDS, no new identity/daemon provisioning, no Docker access widening),
**not** a spatial-data change. The record file lives on the shared host's
launcher journal directory and is governed by shared-host maintenance scope.

### 3.3 Verification obligations (future implementation)

1. Replay: dual-branch reader tests — branch A validates against
   `removedEventDigests`; branch B replays as today; `reconstructed_history()`
   always contains the gap marker; replay of nonce `511774dc-…` through
   `recover_startup()` still raises `AttemptRecoveryUnavailable`.
2. Contract: closed-field validation tests for `external-inspector-recovery.v1`
   (duplicate-key rejection mirroring `_reject_duplicate_json_keys :1566–1572`,
   canonical-timestamp rule, digest recomputation, enum closure, supersession
   chaining).
3. Negative tests: recovery record present ⇒ `cleaned("511774dc-…")` still
   raises; `cleanup_required` with a manufactured disposition still fails
   origin checks (`_validate_phase_additions :993–1008`); journal file with an
   interleaved recovery line still fails `_validate_event`.
4. Operational evidence: privileged read-only re-stat/hash of live journal
   across the read (P3), staging re-observation (P4), both logged in the record.

### 3.4 Operational prerequisites (all require explicit approval)

- **P1 — Shared-host maintenance scope:** window, operator identity, and exact
  commands for any privileged read on the VM; no writes to
  `attempts.jsonl`, staging, daemon/cgroup state, or the VM backup during
  record creation.
- **P2 — Backup immobility:** `/tmp/ksi-inspector-journal-backup-20261020-511774dc.jsonl`,
  retained staging, and both preserved copies stay untouched; rollback of the
  *record creation itself* is deletion of the single new recovery line only
  (or a `SUPERSESSION` record), never branch surgery.
- **P3 — Live-head binding:** at record time, capture live journal
  size/mtime/ctime/inode + SHA-256 with stability check; embed head digest and
  event count in `retainedBranch`; if stability cannot be shown, record
  `liveStabilityCheck: UNVERIFIABLE` and stop (no guessing).
- **P4 — Staging disposition:** re-observe staging (stat inode/hash/marker)
  read-only; retirement, if ever, is a separate `ABANDONMENT_ATTESTATION`
  under its own approval with owner/identity checks — never implied by this
  disclosure record.
- **P5 — Approver:** Human/owner sign-off on the contract (this document's
  successor), the exact record bytes, and P1–P4 scope. Per the Human
  instruction, shared-host mutation or on-the-spot rule finalization is
  **not** approved by this design.

---

## 4. Three-state separation (explicit, actionable)

The Human requires: audit integrity, data-validation suitability, and
spatial-data viewability are **three distinct states** — never collapsed into
one `READY`-style flag.

### 4.1 Where each lives today

| State | Owner / location today | Current vocabulary |
|---|---|---|
| **S1 — Audit integrity** (launcher history) | Launcher journal: `external_inspector_attempts.py` chain validation (`_reload_from_handle :844–874`), phase machine (`:1012–1066`), `AttemptRecoveryUnavailable` (`recover_startup :1216–1249`); incident docs in `docs/audit/` | Phase names (`CLEANUP_FAILED`, …), `EXACT_*_UNAVAILABLE` reasons, incident status words (`preserved, unresolved; not an accepted recovery`) |
| **S2 — Data-validation suitability** (per purpose) | Core: checkpoint validations (`services/core/src/ksi_core/domains/artifacts/checkpoint_validations.py`), external evidence validations (`…/external/ingress/external_evidence_validations.py`), use-decision store (`…/quantity/external_use_decisions.py`, wired at `composition/external_graph.py:361–365`), measurement verdict `INPUT_READY` (`services/processing-controller/src/ksi_processing_controller/external_measurement_core_client.py:172,186`), admission policy (`…/external/ingress/external_validation_policy.py:184–…`) | `INPUT_READY` (measurement-input verdict), checkpoint verdicts, `ExternalPairUseDecisionV1` decisions — each **per purpose**, never global |
| **S3 — Spatial-data viewability** (representation) | spatial-data-mcp: `ksi_list_spatial_data_assets` / `ksi_get_spatial_data_asset` (`services/spatial-data-mcp/src/ksi_spatial_data_mcp/server.py:339–356`), Core reason `NOT_READY → WAIT_FOR_COMPLETION` (`core_client.py:63`); Console preview failure kinds (`apps/dashboard/src/lib/spatial-data-preview.ts:29–53`: `UNSUPPORTED, BAD_RECEIPT, TOO_LARGE, TIMEOUT, CANCELLED`) | `NOT_READY`, preview failure kinds — representation facts, not data verdicts |

### 4.2 Existing conflation risks (exact locations)

- **C1 — Launcher admission latch reads like product readiness.**
  `external_inspector_launcher.py:1442–1448` (`_latch_admission_closed`,
  `_is_admission_closed`) and `:1166,1431–1440` close *launcher admission* on
  recovery failure. Correct behavior — but any surfacing must label it
  `launcherAdmission: OPEN|CLOSED`, never `systemReady`/`ready`.
- **C2 — `INPUT_READY` reads like a global verdict.**
  `external_measurement_core_client.py:172,186` — it is a
  measurement-input verdict for one inspection purpose. Callers must render it
  as `measurementInput: INPUT_READY (purpose: …)`, never bare `READY`.
- **C3 — `NOT_READY → WAIT_FOR_COMPLETION` reads like a data verdict.**
  `spatial-data-mcp/.../core_client.py:63` — it is a representation/progress
  fact. Render as `spatialView: NOT_READY (representation pending)`, never as
  a statement about measurement truth.
- **C4 — Qualified Core reports.**
  The incident doc (§"What is known") keeps new Core inspection reports
  factually valid *with the history incident disclosed*. Any consumer joining
  S2 rows to S1 state must carry the qualifier visibly; dropping it collapses
  S1 into S2.

### 4.3 Proposed vocabulary (normative for future work)

- `launcherHistory: INTACT | TRIM_DISCLOSED_UNRESOLVED | UNVERIFIABLE`
  (S1; current value for the shared journal: `TRIM_DISCLOSED_UNRESOLVED`).
- `measurementSuitability(<purpose>): SUITABLE | UNSUITABLE | UNASSESSED`
  (S2; one value per purpose — inspection, checkpoint, use-decision,
  admission — never a single global).
- `spatialView: AVAILABLE | NOT_READY | UNRENDERABLE(<kind>)`
  (S3; `<kind>` reuses the dashboard preview failure kinds).
- **Forbidden:** any single composite field named `ready`, `status`,
  `operational`, `healthy`, or `verified` that merges S1/S2/S3. Linters/docs
  should reject it where feasible.

### 4.4 Console display rule (proposal — decision D4)

Three independent badges, always rendered together when they appear together,
each with its own tooltip source link (journal evidence / Core decision id /
asset receipt). If any one is unknown, show `UNKNOWN` — never infer it from
the other two. No color/wording scheme may imply that three greens equal a
product-level "READY": the Console must not compute or display such a roll-up.

---

## 5. What could NOT be designed faithfully, and open decisions

### 5.1 Limits of this pass

- **L1 — Live journal unverified:** SSH read as `ubuntu` is permission-denied
  on the live journal (§1.4). Divergence/growth since snapshot `b56465cf…`
  (545 events at capture) is unknown to this author. P3 is therefore a
  prerequisite, not a checked box.
- **L2 — Staging not re-observed:** retained-staging inode/hash match rests on
  the prior reviewer's observation as recorded in the incident doc, not on a
  fresh read in this pass. P4 must re-observe before any retirement design.
- **L3 — No daemon/systemd source read:** `external_inspector_systemd.py` and
  `external_attempt_lifecycle.py` were cited from the task brief, not
  read-verified here; T8/T9 touchpoints need confirmation by the implementer.
- **L4 — Core/Console display inventory incomplete:** S2/S3 locations above
  are representative, not exhaustive; a full conflation audit (every `READY`/
  `ready`/`status` string in Console and MCP surfaces) is future work.
- **L5 — No cryptographic design:** record chain uses plain SHA-256 over
  canonical JSON mirroring `_event_digest`; no signatures, no key management
  — deliberate (launcher-local evidence, not a trust root), but stated so no
  one assumes more.

### 5.2 Explicit open decisions (Human/owner approval required — NOT decided here)

- **D1 — Stream placement and filename** (§2.2): `recovery-records.jsonl`
  beside the journal vs. a `journal-incidents/` subdirectory.
- **D2 — Exact record schema** (§2.3): field set, enum members, and whether
  removed events are embedded by value or by digest (proposal: digests +
  hash-pinned external copy, to keep the record small and the evidence
  byte-stable).
- **D3 — Dual-branch reader API shape** (§2.5): function signatures, where it
  lives (`processing-controller` package vs. tooling), and who may call it.
- **D4 — Console vocabulary and badge rendering** (§4.3–4.4): exact strings,
  placement, and the lint rule forbidding a composite READY.
- **D5 — Staging retirement proof** (P4): owner/identity check predicate,
  quorum/role, and whether `ABANDONMENT_ATTESTATION` can ever be issued for
  `511774dc-…` (proposal default: no — retention is the safe steady state).
- **D6 — Maintenance scope P1–P3**: window, privileged read-only identity,
  and the approval reference format that gates record admission.

No work under D1–D6 proceeds without separate Human approval. In particular:
no shared-host journal modification, no on-the-spot recovery-rule
finalization, and no declaration of any branch as canonical.

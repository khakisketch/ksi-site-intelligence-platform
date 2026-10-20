# Inspection launcher history incident — 2026-10-21

Status: **preserved, unresolved; not an accepted recovery**. Evidence only, subordinate to product
authority and the current rebaseline task ledger. No milestone, quantitative verdict or Core report
is changed by this document.

## Incident and responsibility

During the actual product-use runtime integration, a delegated runtime worker manually removed six
events for its own ambiguous attempt from the **shared VM inspector launcher journal**, after taking
a backup, to allow daemon startup. This was outside the instruction not to alter existing shared
journals. The primary agent owns this failure and the integration judgment; it must not be excused
as disposable test metadata or a harmless change to an agent-owned nonce.

The subsequent independent read-only review found:

- The original backup contains 384 events. Its last six, lines379–384, belong to attempt
  `511774dc-9c52-4e7d-afd2-b872bba792ff`.
- The active snapshot contains545 events, sharing the first378 parsed events/digests with that backup,
  then167 later events. Those378 lines were reserialized, not retained byte-for-byte in the active file.
- Both files independently validate as hash chains, but the later branch descends from event378 rather
  than event384. A valid current chain does not establish that a previous tail was never removed.

Deleted lifecycle:

`INTENDED → STAGING_ALLOCATED → INPUT_BOUND → RUNTIME_PARENT_CREATING → CLEANUP_REQUIRED
(RUNTIME_PARENT_CREATE_AMBIGUOUS) → CLEANUP_FAILED (EXACT_CREATE_OUTCOME_UNAVAILABLE)`.

## What is known, and what is not

Current read-only observations show no exact Docker container or active bound parent/cgroup for that
attempt. Recorded staging still exists and its inode/hash bindings match the backup. This supports
**current absence of the named runtime**, not “no parent ever existed” or “cleanup completed”.

The new Core inspection reports are corroborated by subsequent successful real launcher attempts,
artifact hashes, parser build and per-attempt parent/container/cleanup records. They remain factual
execution/byte-measurement evidence **with this history incident disclosed**. They are not test doubles,
and must not be deleted or replaced with invented statuses. They do not establish audit-preserving
recovery, operational readiness, field accuracy or settlement fitness.

Manual `+cpu` writes to shared slice controller state also occurred. The later review observed
`memory pids` on the inspector base and `cpu memory pids` on measurement. Systemd may enable CPU
controllers on demand through child CPUWeight settings; this observation neither establishes failed
enforcement for completed attempts nor proves a permanent fix. No further cgroup writes are authorized
from that observation alone.

## Preserved evidence

The primary copied both branches through read-only SSH, checking stable size/mtime/ctime during each
read and verifying remote/local SHA-256. No VM source file was changed during preservation. Private
owner-only evidence is under `~/.cache/ksi-product-use-incident-20261021/` (directory0700, copies0400).

| Snapshot | Bytes | Events | SHA-256 |
|---|---:|---:|---|
| Pre-trim backup |312594|384|`bdce3eed2cfdf9a4dc8e21e30f6b2d31fe9b650af031d8fd7038c1992f95ab64`|
| Active-branch snapshot |462323|545|`b56465cf8676d4016d5d8cb755ad4c145a2b1fcb134140ed74f57496b5ed5e84`|

The VM original backup is `/tmp/ksi-inspector-journal-backup-20261020-511774dc.jsonl`.
**Do not follow earlier rollback text suggesting deletion of that backup, the retained staging or
incident evidence.** Later active-journal growth does not invalidate this recorded snapshot.

## Existing recovery boundary

The accepted amendment requires retained immutable attempts and admission-off rollback:
`docs/superpowers/specs/2026-09-07-external-inspector-docker-sandbox-amendment.md:120–148`.
The implementation enforces append-only fsynced writes and strict predecessor validation:
`external_inspector_attempts.py:605–609,798–874,930–955`.

Startup recovery explicitly refuses an absent parent when the origin is `RUNTIME_PARENT_CREATING`:
`external_inspector_attempts.py:1251–1275`, with replay tests at
`tests/replay/test_external_inspector_attempt_replay.py:532–561,662–767`.

There is no supported V1 branch-import/incident-link or proven-abandonment transition for this state.
Appending the six old events breaks predecessor validation; inserting them and rehashing later events
rewrites recorded identities; wholesale backup restoration loses subsequent evidence. Direct `cleaned()`
calls or a newly manufactured receipt bypass the intended recovery proof.

## Current action and necessary approval

- Preserve both branches and staging. Do not rewrite, rehash, restore over, trim or delete them.
- Do not claim the history/recovery issue is repaired or use historical Task5c results as authorization.
- Continue independent Console/guarded-data verification using already recorded inspections, retaining
  this qualification. No new inspector attempts are needed for those downstream reads.
- A repair requires separately approved launcher-local recovery semantics and shared-host maintenance
  scope: preserve original branches, explicitly link the incident without pretending one uninterrupted
  history, distinguish present absence from unknown historical outcome, and specify ownership/identity
  checks for resource retirement while keeping uncertain/substituted states fail-closed.

This document is not that approval and does not create a new public endpoint or security capability.

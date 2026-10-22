# ADR-KSI-041 — Private download audit working set and retained history

- Status: ACCEPTED — Human-approved bounded implementation direction; runtime verification pending
- Date: 2026-10-22
- Human approval: explicit “기록 보존형 개선” selection after the 512-terminal-session refusal was demonstrated
- Task ledger: `docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md`
- Scope: private spatial-data download/cleanup audit only; not a global audit migration
- Preserves: INV-020/024/040/051/053/060/061, ADR-KSI-036/037/038/039 and original output/evidence identities

## Problem and evidence

The legacy finite audit projection retains every event and completed session in RAM. The actual
current journal replays to 1,531 events and 512 terminal sessions, with no unfinished sessions or
reserved slots. A new file-read admission is refused by the retained-session bound of
`maxPendingRecords × maxListRecords = 512`, although its prospective byte reservation fits the
unchanged `maxSnapshotBytes` bound. Restart replays the same state; it cannot reclaim capacity.

This is the existing fail-closed behavior, not permission to clear evidence, increase limits,
recreate output jobs or bypass audit. The prior delivery verification deliberately left audit
rotation/archival unapproved. This decision authorizes a specific history-preserving lifecycle
instead of silently changing that legacy behavior.

## Decision

Introduce an **explicitly selected, versioned indexed-history mode** for this private audit.
The old mode and its admission semantics remain the default when no valid opt-in configuration
is supplied. The new mode separates a bounded active working set from retained terminal history.

- The original fsynced event journal remains authoritative and append-only. Existing bytes,
  event/session IDs, digests, sequences, timestamps and handed-off byte meanings are unchanged.
- Completed/interrupted/denied/cleanup-terminal history is retained and remains queryable through
  the existing tenant-scoped private port. It may leave the live working set only after its
  terminal evidence is durably committed and its historical lookup is established.
- Unfinished sessions and their reserved terminal capacity are never discarded or declared
  completed by restart, cancellation, index rebuild or a lack of client acknowledgement.
- Historical event retries remain exact no-ops; conflicting retries, changed identities,
  corrupted history and attempts to reopen terminal sessions remain fail-closed.
- An index or checkpoint is a reconstructible private projection, never substitute authority.
  Missing/corrupt/stale derived state must be validated/rebuilt within bounds or refused. It must
  not manufacture absence, duplicate an event or hide retained history.
- No new public route, externally operated service, data grant, thumbnail producer or byte cache
  follows. An embedded standard-library backing/index is permitted only as a private derived
  implementation with explicit storage, replay and lookup bounds.

## Explicit resource and identity binding

The new mode has its own versioned audit-runtime/configuration identity bound to the exact sealed
data-policy digest and source-journal identity. It must not silently reinterpret an old policy
identity or change the immutable preparation/job policy to obtain access.

The existing numeric data-policy values are **not increased**:

- `maxSnapshotBytes` bounds the new live active projection, reservations and bounded lookup/cache/
  staging together. No uncounted global history-ID/offset dictionary or full replay list is allowed.
- The session-capacity value bounds active/unfinished working state in the explicitly approved
  new mode; it no longer means lifetime terminal-history volume. Legacy mode is unchanged.
- Per-event and per-query limits remain within existing `maxJsonBytes`/`maxListRecords`.
- New index, rebuild and historical I/O limits must be explicit, positive and finite, within the
  current resource envelope; index plus temporary rebuild storage must remain bounded together.
- Startup/rebuild and lookup have finite work/deadline limits. A per-query full-history scan or
  keeping all parsed journal records in RAM is not a valid implementation.
- Resource exhaustion, unavailable audit storage or a failed audit append still denies bytes
  before successful response headers; an interrupted stream still cannot record successful EOF.

The implementation must publish its exact local bounds and activation identity in the task
evidence before live activation. New configuration is owner-private and opt-in; no shared
directory chmod, resource-cap bump or security-setting workaround is authorized.

This recovery activation is download/read scoped. It must not incidentally unblock automatic S3
cleanup through the existing cleanup timer. New cleanup starts are explicitly unactivated/refused
before cleanup reservations or storage I/O; the owner diagnostic must not call that successful
cleanup. Historical cleanup records and unfinished state remain queryable and are never erased
or automatically completed. The signed retention policy and stopped workers are unchanged.

## Foundation and composition boundary

Additive bounded journal read/index primitives or a delivery-specific backing may be introduced
where causally required. Existing Foundation journal behavior/defaults and other domain owners
must remain unchanged. Audit composition alone selects the new mode. Existing journal framing,
corruption checks and writer ownership remain enforced; no implicit torn-tail repair or rewrite
of retained evidence is authorized by this recovery task.

All code and verification first run in isolated source/data copies. The primary owner applies an
approved patch only in the task-owned Core stop/restart window because its fresh SDK child may
import the live checkout. Replay is preflighted without shared writes/network/listeners.

## Verification and rollback

Require legacy-mode regression, more-than-legacy-cap terminal histories, old-session lookup,
exact/conflicting retries, unfinished restart, terminal reopening refusal, corruption/index crash
rebuild, audit-append failure before headers, cancellation, tenant isolation, bounded memory/I/O/
storage and real guarded existing-file hash/render evidence. Fixtures and imports alone do not
complete recovery.

No new preparation, S3 mutation, retention/TTL/grant change, stopped-inspector operation, journal
repair or production/field claim is authorized. Only the existing task-owned Core may be restarted.

Rollback preserves all original and newly appended audit history. Before new admissions exceed
legacy capacity, the original implementation remains a possible rollback. Afterwards, old code
may reject even bootstrap replay of valid extended history: retain a compatible indexed-history
implementation in an explicit **history-only/admissions-disabled recovery mode** instead. It must
load and retain old/unfinished history and keep Core metadata available while refusing new byte
and cleanup admissions before side effects. Removing the opt-in blindly is not a safe downgrade.

No rollback may restore an older journal snapshot, truncate records, delete derived state still
in use, bump the old limits to force startup, or claim restored photo delivery from denial mode.

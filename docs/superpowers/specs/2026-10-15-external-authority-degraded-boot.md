# External Authority Degraded Boot — 2026-10-15 (proposal, not implementation authority)

Status: **approved by the owner 2026-10-15** (window-expired and not-yet-effective both boot BLOCKED; one structured log line naming the gate; indefinite blocked-with-refusal). The snapshot-window half is implemented; the remaining gates are recorded below. This document creates no runtime authorization,
does not change the current slice/acceptance, and must not be executed as a work order by itself.
Source item: product-state backlog 2026-09-18 (owner decision: degrade to BLOCKED; needs a
degraded-boot spec with two time gates; runbook §3a meanwhile).

## 1. Problem

The external authority provider loads one signed snapshot from a protected file. The snapshot window
is short in local rigs (~7 days) and can legitimately end between a deployment's last snapshot
issuance and the next Core restart. The platform must decide what a restart does when the trusted,
signature-valid snapshot is outside its validity window at boot.

Observable outcomes wanted (owner decision 2026-09-18): the Core boots, the external authority
provider reports BLOCKED, and no external work is admitted until a current signed snapshot is
reloaded — instead of the whole platform refusing to start.

## 2. Current behavior (reproduced 2026-10-15 on the F-03 synthetic rig)

Reproduction material: `/home/ksi/.cache/ksi-f03-degraded-20261015/` (copy of the F-03 core-data
journals + provider directory; the snapshot re-signed by the rig's authority signer with an expired
window chained onto the receipt head, sequence 82). Runner: a scratch production Core on
`127.0.0.1:8095` with `KSI_CORE_DATA_DIR` and the provider/workflow paths pointed at the copy.

| Case | Result |
|---|---|
| Snapshot window **expired** (issuedAt = now-3d, validUntil = now-1h), key valid | **Boots**; `/ready` 200; `/ready/external-authority` → 503 (blocked) |
| Snapshot chain not matching the receipt head | Boot fails: `authority receipt history is blocked` (unchanged, correct) |
| Receipt/journal writer already owned by another process | Boot fails: single-writer journal protection (unchanged, correct) |
| Snapshot `issuedAt` **in the future** (now+2d) | Boot fails at load (`ValueError: authority snapshot is outside its validity interval`) / attach (`not yet issued at attach time`) — **fixed 2026-10-15/16: boots BLOCKED (§6)** |
| Snapshot signing key window ended | **fixed 2026-10-16 (§6): boots BLOCKED naming EXPIRED**; before the fix the loader validated the key at `now` and refused the boot (and it accepted signatures declared before the key's own start) |

Interpretation: the window-expired half of the 2026-09-18 item is **already implemented** by the
`allow_expired=True` load in `ksi_core.composition.platform_production` (lines ~158/174) plus the
graceful `EXPIRED` block in the provider's attach path
(`external_authority_provider.py` ~221-232: keeps the signed snapshot and the workflow graph for
replay, sets `_blocked_reason="EXPIRED"`, `_configured=False`, and never reconciles or appends a
receipt). The remaining open half is the **not-yet-effective** window (`now < issued_at`), which
still fails the boot at load and at attach.

## 3. Proposed contract (to be confirmed by the owner)

Two time gates, deliberately different:

1. **Structure / signature / history gate (fatal, unchanged).** Invalid signature, malformed JSON,
   unprotected path, key id mismatch, or a receipt chain not matching the snapshot → the boot fails.
   A platform that cannot trust its authority file must not start with external features half-open.
2. **Window gate (non-fatal, degrade).** A structurally valid, correctly chained, correctly signed
   snapshot whose window is `expired` **or** `not yet effective` at boot → the Core boots and the
   provider starts BLOCKED (`_blocked_reason` records `EXPIRED` / `NOT_YET_EFFECTIVE`). While
   blocked: no inspection/evidence/mapping/analysis admission, no reconciliation, no receipt append,
   `/ready/external-authority` reports unavailable; reads that replay signed history and the rest of
   the platform (sites, work orders, journals) keep working. A reload of a current signed snapshot
   restores `PROVIDER_CONFIGURED` without a restart; the window opening alone does **not** clear a
   running process's block (verified live 2026-10-16: after `issued_at` passed, the same process
   stayed BLOCKED until an explicit operator reload). The recovery path was exercised live on
   2026-10-15 (block → restore → reload → configured) and re-verified 2026-10-16 for the staged
   direction (block → window opens, still blocked → operator reload → configured).

   Rationale for treating `not yet effective` like `expired`: the snapshot is signed by the trusted
   administrator key, so a future window is an intentional staging/rotation decision, not an attack;
   the fail-closed guarantee ("no external work outside the window") is identical in both cases.
   Clock skew remains a real risk; the proposal is to accept a future window at boot and let the
   provider stay blocked until `now >= issued_at`, with the skew visible in operator status.

3. **No-external-configuration gate (fatal, unchanged).** A deployment that never configured the
   external authority paths must keep failing wherever policy replay requires external authority,
   as today. Degraded boot is about a *provisioned* authority whose window moved, never about
   silently running without one.

## 4. Operator / runbook impact

- The interim advice "reissue a signed snapshot before any restart" (runbook §3a) becomes
  unnecessary once gate 2 covers both window directions; the runbook should instead document:
  restart with a stale snapshot is safe (blocked), and the first external job after the restart
  requires a reload.
- Status surfaces keep today's vocabulary (`PROVIDER_CONFIGURED` / `BLOCKED`); the provider status
  projection should name which gate blocked (`EXPIRED` / `NOT_YET_EFFECTIVE`) to the same audience
  that may already see the boolean, without exposing exception content.

## 5. Test plan (when implementation is authorized)

1. `tests/contract/test_platform_core_production.py` (existing home of the boot-path tests):
   expired-window snapshot → `build_platform_production_app` succeeds; provider status unavailable;
   a following reload of a current snapshot → configured.
2. Same file: future-window snapshot → boot succeeds and stays blocked until the clock passes
   `issued_at` (fake clock), then behaves as configured.
3. Negative controls unchanged: broken signature, broken receipt chain, missing configuration.
4. Key-window expiry: verify current behavior first, then apply the same gate decision.

## 6. Owner decisions (2026-10-15) and implementation status

1. **Not-yet-effective window: boot + BLOCKED** (decided). Implemented: the loader's window flag is
   now `allow_out_of_window` and tolerates both directions (`provider_loading.py`), the signing key
   resolves at `issued_at` for any out-of-window snapshot, and the attach path turns the future case
   into `_blocked_reason = "NOT_YET_EFFECTIVE"` instead of raising
   (`external_authority_provider.py`). Contract coverage:
   `tests/contract/test_platform_core_production.py::test_not_yet_effective_authority_snapshot_stays_blocked_not_activated`.
2. **One structured startup log line naming the gate** (decided). Implemented: the attach block logs
   `external authority provider blocked: EXPIRED` / `NOT_YET_EFFECTIVE` (module logger; the API
   surface keeps the opaque posture).
3. **Indefinite blocked-with-refusal** (decided, no code change needed).

### Third gate: workflow-config catalog binding (found and fixed 2026-10-15/16)

A *fully staged* future snapshot (window plus actions effective when the window opens) initially
failed after the snapshot window gate at the external result workflow configuration
(`CATALOG_AUTHORITY`): `catalog_configuration_was_authorized` rejected a snapshot issued in the
future (`snapshot.issued_at > now`) and required its historical evaluation time to be `<= now`.
That is a third time gate beyond the original two.  Fixed in the same approved policy:
`catalog_configuration_was_authorized` now authorizes the binding structurally from the exact
signed window for **both** out-of-window directions (the still-current case still defers to the
live resolution path), while every live port keeps applying the current-time gate and the provider
stays blocked.  Contract coverage:
`tests/contract/test_platform_core_production.py::test_staged_snapshot_authorizes_its_catalog_binding_for_the_degraded_boot`
(future True, in-window False, unknown digest False).

**End-to-end live verification (2026-10-16, scratch core)**: a chained, correctly signed,
future-window snapshot that also stages an administration action effective when the window opens
now **boots**, `/ready` is 200, `/ready/external-authority` is 503 (blocked), and the startup log
carries exactly one line: `external authority provider blocked: NOT_YET_EFFECTIVE`.  The expired
direction had already been verified the same way.

### Full-factory boot and reload acceptance (2026-10-16)

Contract tests (`tests/contract/test_platform_core_production.py`):

- `test_factory_boots_blocked_for_an_expired_authority_snapshot` — the whole factory (provider plus
  an approved catalog/workflow pair) boots BLOCKED, `/ready/external-authority` is 503, exactly one
  named `EXPIRED` line is logged, no receipt is appended, and `reload_and_reconcile` with a
  reissued current snapshot (same key) restores `PROVIDER_CONFIGURED`, 200 readiness and exactly
  one receipt — without a restart.
- `test_factory_boots_blocked_for_a_staged_future_authority_snapshot` — the same boot path for the
  not-yet-effective direction (one named `NOT_YET_EFFECTIVE` line, 503, no receipt).
- `test_factory_refuses_a_tampered_authority_snapshot_signature` — signature tamper stays fatal for
  the whole boot (structure gate), with the loader-level cause `signature is invalid`.

Live scratch run (`/tmp/opencode/ksi-f03-20261015/degraded_window_check.py` on the copied F-03
journals, receipt head seq 81):

- CHECK0 tampered signature → boot refused, `signature is invalid` in the log.
- CHECK1 fully staged future snapshot (one staged administration action, window 2026-10-17) →
  boots, 503, exactly one `NOT_YET_EFFECTIVE` line, receipts byte-unchanged (81): the staged action
  was not applied.
- CHECK2/3 a window-test snapshot issued `now+90s` → boots blocked; after the window opened the
  same process stayed 503 (no auto-unblock).
- CHECK4 the operator `POST /v1/operations/external-authority/reload` (ADMIN principal in the
  provider's organization) returned `PROVIDER_CONFIGURED`, sequence 82 and
  `/ready/external-authority` 200; the receipts journal advanced to 82.
- CHECK5 a fresh restart after the reload was idempotent (200 immediately, no gate line, no
  duplicate receipt).

Note for test authors: `build_platform_production_app` installs structured logging on the root
logger and removes existing root handlers, so `caplog` cannot observe these startup lines; attach a
handler to `ksi_core.domains.external.authority.external_authority_provider` instead (see
`_GateLogs` in the contract test file).

### Fourth gate: signing-key window (found and fixed 2026-10-16)

Verifying the spec's remaining item surfaced two loader defects around the signing-key interval:

1. For a snapshot inside its own window the loader validated the key at `now`, so a key window that
   had ended between issuance and boot failed the **load** before the attach path could apply its
   intended `EXPIRED` gate (`now >= key_not_after`); an ordinary reissue-with-newer-key was the only
   way out of a boot refusal.
2. Symmetrically, validating at `now` accepted a snapshot whose declared signing time (`issuedAt`)
   preceded the key's own `notBefore` — a signature the declared facts say could not have been made.

Fix: the signing key is **always validated at `issued_at`** (a signature produced outside the key's
declared interval is structurally impossible, never a time gate), and the key window's end at boot
joins the time gate (`out_of_window` includes `now >= key_not_after`) so the production factory
boots BLOCKED naming `EXPIRED`, while the reload path (`allow_out_of_window=False`) stays fatal for
the same inputs — key-ended authority is never reconciled or receipted by a running Core.

Contract tests (`tests/contract/test_platform_core_production.py`):
`test_factory_boots_blocked_when_the_signing_key_window_ended` (factory boots, BLOCKED, one
`EXPIRED` line, 503 readiness, no receipt, reload path fatal) and
`test_loader_rejects_a_snapshot_signed_before_its_key_window` (structure gate in every mode).

Live scratch verification (`/tmp/opencode/ksi-f03-20261015/keyended_live_check.py` on the copied
F-03 journals, receipt head 82): CHECK1 key-ended variant (issued 10-15T02:14Z inside a key window
ending 10-15T06:00Z, snapshot window open) boots with `/ready/external-authority` 503, exactly one
`blocked: EXPIRED` line and byte-unchanged receipts; CHECK2 the same inputs with
`allow_out_of_window=False` are refused at load.

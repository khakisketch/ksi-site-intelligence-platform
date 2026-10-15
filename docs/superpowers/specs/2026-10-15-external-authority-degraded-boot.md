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
| Snapshot `issuedAt` **in the future** (now+2d) | Boot fails: `ValueError: authority snapshot is outside its validity interval` (load) / `not yet issued at attach time` (attach) |
| Snapshot signing key window ended | Not yet reproduced cleanly (the variant hit an unrelated administration-order validator); listed as a verification item |

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
   (or the window opening, re-evaluated at runtime) restores `PROVIDER_CONFIGURED` without a restart
   — the recovery path was exercised live on 2026-10-15 (block → restore → reload → configured).

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

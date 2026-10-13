# F-04 review persistence evidence (synthetic)

Status: 2026-10-13. Synthetic copy-stack verification only — not customer, real-material,
parser-sandbox or deployment evidence. Canonical record and boundaries live in the
[rebaseline ledger](../../../docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
("F-03 체인 재생성 — Console 검토 지속성 로컬 폐쇄" 항목).

## What this shows

The Console review flow for an external relative-volume report, driven end-to-end on the
isolated copy stack (issuer 9051 / Core 8051 / Console 3251) after regenerating the expired
F-03-generation authority chain with current windows:

1. The volume report renders in the Console with its numbers and ranges
   (`review-before-restart.png` after a page reload, and the site observations surface in
   `observations-page.png`).
2. A Console review write (Core 201) is durable: the same review record
   (`err-v1-0894a51a…`, reviewed 2026-10-13 13:37 KST) renders after a page reload and after
   a full copy-stack restart including Core journal replay (`review-after-core-restart.png`).

## Files

- `SUMMARY.md` — chain regeneration, lane runs, digests and the gates fixed on the way.
- `review-before-restart.png` — report + review line after a page reload.
- `review-after-core-restart.png` — same review after `relaunch.sh` (Core restart).
- `observations-page.png` — the site observations surface shows the same review.

## Tooling

- `tools/regenerate_external_validation_chain.py` renews an expired F-03-generation
  authority chain (policy record → policy body → contexts → catalog authority → snapshot)
  and preflight-validates the result with the real provider loader. Its contract test is
  `tests/contract/test_regenerate_external_validation_chain.py`.
- The lane drivers and one-off prep scripts used for this run live in
  `/tmp/opencode/ksi-f04-review-20261013/` (transient) and are summarised in `SUMMARY.md`.

## Boundaries

The scoped-operator review routes opened for this flow are in the reviewed auth matrix
(commit `b4a3905`); handler-level authority checks are unchanged. Parser sandbox
acceptance, real A–E materials, the separate verification host and customer/EXT-VAL
acceptance remain OPEN. The work orders used here carry a work-area/zone mismatch
(`wa-…-0001` vs the analysed `wa-…-0002`) that real materials must not repeat; see
`SUMMARY.md`.

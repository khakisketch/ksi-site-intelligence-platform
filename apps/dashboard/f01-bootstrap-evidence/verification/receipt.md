# F-01 mapped Site bootstrap — local synthetic acceptance (D3)

- Date: 2026-10-10 (KST)
- Status: PASSED for the recorded stages — local synthetic acceptance evidence only. This is **not**
  customer, field, production, deployment, or accuracy acceptance.
- Source: `feat: add registry v2 and mapped site bootstrap (F-01 core)` at **159698b** and
  `feat: wire F-01 bootstrap into dashboard registration flow` at **bb1c4bf** (working tree during
  the run matches those commits' feature content). Base `c34ac1b`.
- Runtime: isolated loopback stack — local issuer origin `http://localhost:9071`, Core
  `127.0.0.1:8071` (`--human-auth-mode OIDC`), dashboard `http://localhost:3235` (`next dev`,
  dist `.next-f01-d3`), `--tailscale disabled`. The pre-existing systemd dev stack
  (3210/9010/8012) was not touched or duplicated; only the run's own processes were started and
  stopped (ports verified free afterwards).
- Paths: run/evidence scratch `/tmp/opencode/f01-d3-20261010-113735/` (HAR 70 MB kept there);
  protected registry dir `/home/ksi/.cache/ksi-f01-d3-20261010-113735/` (0700 dir, 0600 file) —
  the registry file must live under a protected ancestor chain; a first attempt under
  `/tmp/opencode` was correctly rejected by the loader (`unsafe ancestor`), which is fail-closed
  behavior, not a workaround target.
- Registries: v2 `sha256 c4c347ff688ca948179e3e40b504f2df4e0f019c58c6ddc51d2a84b362d650b6`
  (accounts: local-admin org-local-pilot ADMIN `SITE_BOOTSTRAP` + null/null; field-operator,
  viewer: no capability; local-empty-org-admin org-local-empty). v1 file
  `sha256 3d5f7c3905910be2723ae9a7e26a8a345c74081652fd2ec24f1c5a9a19c76d3d`.

## Recorded stages

| # | Stage (registry / action) | Observed result | Evidence |
|---|---|---|---|
| 1 | v2 boot; browser login (default account); open `/sites/new` | Wizard renders **without 현장 ID field** (mapped mode): 현장 이름 first; step AOI/CRS accepted; confirm step lists 현장/범위/좌표계/AI only — no 현장 ID row | `01-sites-new-mapped.png`, `02-step1-aoi-crs.png`, `03-confirm-mapped.png` |
| 2 | Submit registration | BFF `POST /api/sites` **201**; request body has `bootstrapRequestId` (no `siteId`); response `site.siteId = site-c6095357-1e44-442d-a8fe-ab12e9c42b85` (server-issued), `status=UNMAPPED`, `registeredAt=2026-10-10T02:44:14.838974+00:00`; navigation to `/sites/<server id>` | `04a-bff-request.json`, `05-site-detail.png`, `sites.jsonl` |
| 3 | Create WorkArea on the new site | `POST .../work-areas` **201**; `workAreaId wa-site-c6095357-…-0001`, `status ACTIVE`; area immediately listed (사용 중인 작업구역 1건) | `04b-work-area-request.txt`, `07-work-area-created.png`, `work-areas.jsonl` |
| 4 | Restart same data dir; reload | Same site id listed; work-areas 200 with the same area; identical command re-run | `08-after-restart-work-areas.png` |
| 5 | Same key + same payload retry | **201 with the same site id** (idempotent); journal still one `site-registered` record with the `site-bootstrap-binding.v1` binding `{requestKey aa9034f9-…, requestDigest 0ed7684c…}` | `sites.jsonl` |
| 6 | Capability removed (`capabilities: []`) + restart | `/sites/new` → "현장 등록 권한이 없습니다" (DENIED); direct `POST /api/sites` → **403** `{"detail":"권한이 부족하다"}`; existing site stays readable (read scope retained) | `09-capability-removed-denied.png` |
| 7 | Scope narrowed (explicit list without the site; capability off) + restart | Site list 0곳; detail page "현장을 찾을 수 없습니다"; bootstrap POST 403 | `10-scope-narrowed-detail-404.png` |
| 8 | Capability restored, list still narrowed + restart | Same-key/same-payload retry → **404** `UNKNOWN_SITE` ("등록되지 않은 현장입니다") — hidden receipt is not returned | `11-narrowed-bootstrap-retry-hidden.png` (the 404 text is this row) |
| 9 | Explicit list re-issued containing the site + restart | Site visible again; work-areas 200 with the persisted area; same-key retry → **201 same site id** | `12-reissued-visible.png` |
| 10 | Status `REVOKED` + restart | `POST /api/sites` → **401** ("세션이 만료되었습니다" via BFF); UI shows re-login state on `/sites` | `13-revoked-session.png` |
| 11 | v1 registry file (explicit arrays) + restart | Site visible via v1 arrays; `/sites/new` → DENIED; bootstrap POST → **403** (v1 has no capability) | `14-v1-denied-newsite.png`, `registry-v1.json` |

Durable journal (copied): `sites.jsonl` — exactly one `site-registered` with
`actor=local-admin`, `organizationId=org-local-pilot`, server-issued `siteId`, and the versioned
bootstrap binding. `work-areas.jsonl` — one `work-area-registered`.

## D3 coverage mapping

- (a) protected registry v2 + real OIDC mode: stages 1–11 (OPAQUE test mode not used for the stack).
- (b) designated org-admin: create → list/detail → WorkArea → immediate use: stages 2–4, plus
  restart/reload reproduction (stage 4) and idempotent retry (stage 5).
- (c) general operator 403 / cross-org non-disclosure: capability-less denial shown with the real
  mapped account (stage 6) and v1 (stage 11). The in-browser **account switch to
  `local-empty-org-admin` was not exercised**; cross-org folding (same 404, no list/cursor
  disclosure) is pinned by the existing contract/replay suites and the F-01 contract tests.
- (d) creation actor/time audit: `sites.jsonl` actor + `registeredAt`/`ts`, area `createdAt`.
- (e) v1 compatibility: stage 11 (loads, scoped reads work, no capability inference).
- (f) negative/regression matrix: capability removal 403 (stage 6), REVOKED 401 (stage 10),
  hidden retry 404 + re-issued visibility + same-id idempotency (stages 5, 8, 9); forged
  JWT-claim rejection, null-null route-matrix containment, empty-vs-null distinction, and
  cross-site area-id injection 404 are pinned by the contract tests (`test_oidc_route_scope.py`,
  `test_oidc_subject_registry_v2.py`, `test_site_bootstrap_and_work_area_grant_levels.py`).

## Not exercised / open

- DUAL-mode stack run (the launcher is OIDC-only); DUAL coexistence is covered by in-process
  contract suites (`test_oidc_auth.py`, route-scope fixtures) — a DUAL browser run was not made.
- Cross-org browser account switch (see (c)).
- Mobile viewport capture: the wizard is desktop-only by design (`ResponsiveActionBoundary`);
  mobile gating is covered by the existing e2e suite, not re-captured here.
- Design review of the changed screens (wizard mapped mode) is a separate design-owned stage and
  was not performed in this D3 run.
- No production activation, live grants, deployment, or customer data were touched. All data is
  synthetic; the issuer/stack used only loopback.

## Reproduce (concise)

```bash
REG_DIR=~/.cache/ksi-f01-d3-<ts>   # 0700; registry file 0600 (protected ancestors)
node apps/dashboard/scripts/run-local-oidc-stack.mjs --tailscale disabled \
  --dashboard-port 3235 --core-port 8071 --issuer-port 9071 \
  --core-data-dir /tmp/opencode/f01-d3-<ts>/core-data \
  --identity-state-dir /tmp/opencode/f01-d3-<ts>/identity \
  --dashboard-dist-dir .next-f01-d3 \
  --oidc-subject-registry-file "$REG_DIR/registry-v2.json"
```

File hashes for everything in this directory: `MANIFEST.sha256` (HAR path + hash in
`f01-flow.har.sha256`; the HAR itself stays in the scratch directory).

# Current Task State

## 2026-08-31 — `civil_report_coverage_evidence_green_push_environment_blocked`

- Authority: `REQ-WRK-101`, `REQ-INT-101/102/103/104`, `REQ-SEC-101`, `REQ-UX-101`;
  `INV-010/040/053/060`.
- Implemented: Core `ReportExportSnapshot 1.1` binds the latest design-result mission's accepted and
  rejected CoverageReport history prefix; replay retains earlier prefixes and legacy `1.0`; idempotent
  retry is stable after later coverage suffixes. The existing report, print and CSV share attribution,
  plan reconciliation and rejection facts, and mismatched/unavailable evidence prevents output.
- Commits: feature `e576217`, authority/risk closure `164c2c2`; this task-state commit follows.
- Local evidence: Python `4216 passed / 24 skipped`; Ruff; Mypy `441` files; lock; Dashboard
  `62 files / 572 tests`, ESLint, TypeScript and production build; Playwright `62 passed / 14`
  intentional external-staging skips at 390/768/1024/1440; diff, hygiene, reference, PSDK and
  runtime-image-pin gates.
- Product truth: risk `coverage-reconciliation-not-in-print-or-csv` is resolved. Core still cannot
  recompute aircraft-reported zone ratios from raw classified cells, so INV-010's remaining limitation
  and report attribution warning remain.
- Delivery check: fetch showed `origin/main` `899c6c8` is an ancestor of local `164c2c2`, two commits
  ahead, with a clean worktree. `git push origin main` was rejected by the Codex execution policy before
  process launch; no remote mutation occurred. Owner-terminal fast-forward push and remote SHA comparison
  remain. GitHub run `33317220883` had six zero-step jobs under the account payment/spending-limit gate,
  so no remote-green claim is made.
- FIELD-0a stays `BLOCKED`; DJI capabilities stay `NOT_VERIFIED`/OFF. No device, DPK, flight, motor,
  waypoint, camera/gimbal, customer data, release or deployment action occurred.

---

## 2026-08-30 — `civil_runtime_resource_policy_software_green_push_environment_blocked`

- Authority: ADR-KSI-032; `REQ-OPS-101/102`, `REQ-WRK-101`, `REQ-INT-104`, `REQ-SEC-101`,
  `REQ-UX-101`; `INV-040/050/053/054/055/060`.
- Implemented: exact external runtime image digest pins and scanner; immutable
  `ksi-civil-pilot-r1` Core registry/admission snapshot; authoritative Mission/SourceMedia/
  organization-active-job derivation; fail-closed replay/idempotency and bounded metrics; existing
  Mission-card policy visibility and typed recovery; clean-source release-evidence schema/tool.
- Commits: authority `89c2fea`, runtime `273ab64`, Core `ddd1c8c`, Dashboard `427dec8`, release evidence
  `5f22f5e`, typed maximal-assembly fixture `04cb68a`; final ledger commit follows this entry.
- Current local evidence: Python `4215 passed / 24 skipped`; Ruff lint; Mypy `441` files; lock; Dashboard
  `62 files / 566 tests`, ESLint, TypeScript and production build; Playwright `62 passed / 14`
  intentional external-staging skips across 390/768/1024/1440; repository hygiene, reference import/
  pin, DJI third-party checksum, runtime image pin and diff gates.
- Release truth: the envelope tool is software-ready, but no actual KSI product image, SBOM/scanner
  package, signature, WORM/remote anchor, vulnerability approval, registry promotion, production deploy
  or customer-data approval was created or inferred. Those remain external release gates.
- Delivery check: the final fetch proved `origin/main` `0ff5f94` is an ancestor of local `fc711e0`, which
  was 14 commits ahead with a clean worktree. `git push origin main` was rejected by this Codex execution
  policy before process launch because approval is unavailable. No remote mutation occurred; owner-terminal
  fast-forward push and then new-HEAD SHA/CI inspection remain. Executed remote CI is independent, and the
  known GitHub billing/spending-limit condition must not be labeled remote green.
- FIELD-0a remains `BLOCKED`; all DJI capabilities remain `NOT_VERIFIED`/OFF. No device, DPK, flight,
  motor, waypoint or camera/gimbal action occurred.

---

## 2026-08-30 — `civil_operational_closure_software_green_push_environment_blocked`

- The owner push completed: local `main` and `origin/main` both resolve to
  `0ff5f94afad458527e71e7229fa015dc1d6136e0`, and the worktree was clean at the start of this
  increment.
- GitHub Actions run `33260008688` targets that exact SHA. All six jobs have an empty step list and
  the account annotation says recent payments failed or the Actions spending limit must be increased.
  This is an external account gate, not an application test failure, and it is not remote green.
- Implemented: immutable Core report-export audit plus Dashboard fail-closed export ordering;
  request-local Processing Controller/Core correlation including heartbeat threads; a manual,
  secret+digest-gated pinned NodeODM/MinIO live workflow; direct-spacing
  `plannedCoverageRatio=null`; and failed/cancelled reconstruction re-issue over the same sealed input.
- Feature commits: coverage truth `1e1c8d6`, Processing correlation/live gate `c55e58d`, Core export
  audit `9f5ae15`, Dashboard export audit `4446a5d`, reconstruction recovery `3dcbee8`, and evidence
  ledger `bd67fe7`.
- Local evidence: Python `4147 passed / 24 skipped`; Ruff, lock and Mypy (`434` files); Dashboard
  `60 files / 552 tests`, lint, TypeScript and production build; Playwright `62 passed / 14 intentional
  skips` across 390/768/1024/1440; repository/credential/large-file/reference/pin gates. Native runtime
  and ASan/UBSan each passed `7/7` without the unavailable SQLite backend; PSDK-independent logic
  passed `2/2` and missing-PSDK default configuration remained fail-closed.
- Fetch confirmed `origin/main` (`0ff5f94`) is an ancestor of local `main`; the worktree was clean.
  The subsequent `git push origin main` was rejected by the Codex command policy before a process
  launched because approval is unavailable. Remote `main` therefore remains `0ff5f94`; no partial
  remote mutation occurred. The new live workflow has not run owner imagery, and a zero-step run is
  not remote CI evidence.
- FIELD-0a remains `BLOCKED`; all DJI capabilities remain `NOT_VERIFIED`/OFF. No device, DPK,
  credential, flight, motor, waypoint or camera/gimbal action is authorized by this work.

---

## 2026-08-29 — `independent_checkpoint_validation_software_green_delivery_pending`

- Authority: ADR-KSI-031, `REQ-INT-104`, `REQ-INT-101`, `REQ-SEC-101`, `REQ-UX-101` and
  `INV-020/023/024/040/050/053/060`.
- Scope: an optional sealed CSV checkpoint producer. The client declares source provenance, CRS,
  vertical basis and an explicit independence attestation; only the Processing Controller computes
  checkpoint statistics against the immutable DSM. No client RMSE is accepted.
- Current evidence: implementation is complete. Python passed `4122` tests with `24` skips and `3`
  expected failures; Ruff and Mypy (`431` source files) passed. Dashboard Vitest passed `59` files /
  `545` tests, followed by ESLint, TypeScript, production build and Playwright `62 passed / 14`
  intentional skips at 390/768/1024/1440. Lock, diff, repository hygiene, reference-import and pin
  gates passed.
- Delivery state: local commits are split as `32e52b4`, `79bc5fe`, `95c72e8`, `cf6c9f9`, `30399ba`,
  `19c1819` and the acceptance-ledger commit. The 2026-08-30 fetch proves `origin/main` is an ancestor,
  but this execution environment rejects `git push` before launch. Remote run 33139495105 independently
  shows all six jobs failed at zero steps with GitHub's account-payment/spending-limit annotation.
  Owner billing restoration, fast-forward push and executed new-HEAD CI evidence remain required; no
  remote CI, release or deployment is claimed.
- Supplemental local CI evidence after identifying that account gate: MixERC-Seg import and contract
  tests passed `22/22`; PSDK-independent tap logic passed `2/2` and missing-PSDK default configuration
  remained fail-closed. The exact arm64 Ubuntu 20.04 target image reported gcc 9.4.0/CMake 3.16.3/glibc
  2.31; control-plane native, ASan/UBSan and Manifold-target builds each passed `7/7`, followed by the
  target ABI check. This does not replace GitHub's clean x86 extra install, QEMU/buildx/cache or remote
  runner evidence.
- Boundary: a `VALIDATED` technical result is not proof of physical checkpoint independence, survey
  accuracy, contract settlement suitability or civil field acceptance.
- Physical status is unchanged: FIELD-0a remains `BLOCKED`; every DJI capability remains
  `NOT_VERIFIED`/OFF. No flight, motor, waypoint, camera/gimbal, DPK, automatic media egress or
  device write is in scope.

---

## 2026-08-29 — `civil_processing_v1_software_and_foreign_benchmark_complete_field_gate_open`

- Authority: ADR-KSI-030, `CIVIL_PROCESSING_V1_ACCEPTANCE.md`, `REQ-INT-104` and `INV-053`
  establish the immutable NodeODM profile, LandXML ingress and fail-closed civil comparison scope.
- Local commits: `a215fbf` adds strict private field-input readiness; `7fe2593` adds the lawful
  two-acquisition live benchmark and non-sensitive digest evidence. Neither commit was pushed.
- Implemented: Core profile snapshot/digest and compatibility preflight; Processing Controller
  pinned NodeODM identity and secure LandXML→canonical GeoTIFF lineage; additive Source Upload,
  Design Surface and Comparison panel states; strict owner-private civil field-input manifest/auditor.
  Existing Home/Sites/Work/Items IA is protected.
- Software evidence: Python `4051 passed, 24 skipped, 3 xfailed`; private input audit `18 passed`;
  Ruff; Mypy `424 source files`; Dashboard `58 files / 541 tests`, ESLint, TypeScript and production
  build; Playwright `62 passed, 14 intentional skips` across 390/768/1024/1440; lock/diff/hygiene/
  reference-import gates. The exact pinned NodeODM reported 2.2.4 / ODM 3.5.6 and completed both a
  public 12-image reconstruction and a sealed Core→worker→real MinIO artifact digest round-trip.
- Real-data benchmark: `E2E-B01 BENCHMARK_PASS`. Two official USGS same-area acquisitions were exact-
  size/ZIP-CRC checked and 24 public preservation JPEGs per date ran through `ksi-odm-civil-v1` in
  `529.02 s`. Each produced seven mapped artifacts including DSM/DTM/point cloud; distinct DSMs had
  `4,290,788` common finite cells. The non-sensitive digest record is
  `CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`; raw inputs/selection/output archives remain private.
- Formal status: product E2E-01 remains `PARTIAL`. EPSG:32617, approximate EXIF GNSS, non-original
  preservation JPEGs and missing common independent control/vertical/design evidence make product
  quantitative comparison false and field acceptance `NOT_EVALUATED`. Do not relabel foreign CRS or
  interpret the `1.99291 m` technical mean delta as accuracy/change/quantity evidence.
- Boundary: v1 media ingress is `SD/저장매체 → 현장 PC → KSI 웹 업로드`; raw imagery/LandXML/
  GeoTIFF and generated artifacts stay outside Git. NodeODM stays an unmodified AGPL container over
  REST, and customer on-prem distribution requires a separate source-offer/legal gate.
- Independent physical state is unchanged: FIELD-0a remains `BLOCKED`; every DJI capability remains
  `NOT_VERIFIED`/OFF. No flight, motor, waypoint, camera/gimbal, DPK, automatic media egress,
  remote deployment, release or remote push occurred in this task. Civil field acceptance still
  requires anonymized Korean LandXML, two same-site original-image epochs and independent reference
  volume/checkpoints.

---

## 2026-08-27 — `no_usb_field0a_receiver_software_ready`

- Commit: `7d1aa88` implements a separate temporary HIL receiver; the Pilot JSBridge probe remains
  GET/HEAD-only and calls no DJI function.
- Receiver boundary: existing owner 0700 canonical root/direct-child session, in-memory capability
  URL, fixed A/B/C/export/M4D slots, 64 MiB cap, safe KMZ checks, exclusive no-follow 0600 writes,
  no overwrite/log/download/list/egress.
- Verification now: Python `3976 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `413 source files`;
  Dashboard `58 files / 529 tests`, ESLint, TypeScript, production build; canonical A/B/C checksums,
  lock/diff/hygiene/reference gates pass.
- Ledger correction: the M4D camera replacement risk is resolved from the existing original EXIF
  evidence (12.29mm, 5280×3956); 17.3mm sensor width remains a 4/3 nominal value and survey-grade
  accuracy is not claimed. Exact M4D + RC Plus 2 Wayline/Media field support remains an open risk.
- Formal gate: `field-0a-kmz-acceptance` stays `in_progress/BLOCKED`. A fresh same-session Pilot
  import, Pilot-native KMZ, M4D original and human attestation are still required. Android/Pilot 2
  file selection is `NOT_VERIFIED` until the user opens the temporary URL.
- Next user-safe action: reconfirm propellers removed and stable ground setup, then attempt only the
  local evidence upload. Do not press mission execution, takeoff, motor, gimbal or automated camera
  controls. DJI developer license bootstrap follows FIELD-0a as a separate gate.

---

## 2026-08-27 — `pilot_open_platform_jsbridge_surface_observed`

- Real-device scope: RC Plus 2/Pilot 2 loaded the read-only KSI probe while M4D propellers were
  removed. No flight, motor, camera/gimbal, mission execution or DJI function call occurred.
- Observation: `window.djiBridge` and six bootstrap method names were shown present:
  `platformGetVersion`, `platformIsVerified`, `platformVerifyLicense`, `platformLoadComponent`,
  `platformIsComponentLoaded`, `apiGetToken`.
- Evidence: owner-attested private 0600 JSON, SHA-256
  `9619c95404d10f19063ab3b8cc53b02d71bbc2402f6a637f75de4d4be1386010`. No raw screen was
  captured, and no IP, serial, GPS, credential or token is tracked in Git.
- Verdict: `JSBRIDGE_SURFACE_OBSERVED`. This does not verify license authentication, component
  loading, Wayline/Media/MQTT/WS/MOP paths or the exact M4D + RC Plus 2 support combination.
  Phase 3 remains `BLOCKED`; all five capabilities remain `NOT_VERIFIED`/OFF.
- Next gate: obtain DJI developer application credentials through an owner-private secret path and
  perform separately authorized Cloud API license authentication. Never paste App Key/License into
  chat, shell history, logs or Git.

---

## 2026-08-27 — `software_closure_complete_field0a_private_store_ready`

- Local feature commits: `2c7aee7` product authority/traceability, `fd78d11` Pilot-export
  FlightArtifact candidate, `2808c4e` CaptureQuality/AnalysisReadiness plus Dashboard,
  `9bd610d` DJI documentation-vs-field evidence, `3bb55df` assembly/hostile-input/FIELD
  attestation gates. No raw KMZ/photo/screenshot, serial, GPS, secret or device data is tracked.
- Requirements/invariants: `REQ-MSN-104`, `REQ-WRK-101`, `REQ-ACQ-102/103`, `REQ-INT-102/103`,
  `REQ-SEC-101`; `INV-011/012/016/017/018/040/041/050/060/061`. Pilot export remains
  `VALIDATED_CANDIDATE_UNBOUND`/non-executable, CaptureQuality is Edge-only immutable evidence,
  and AnalysisReadiness is additive fail-closed projection rather than a WorkOrder transition.
- Verification: Python `3948 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `409 source files`; Dashboard
  Vitest `58 files / 529 tests`, ESLint, TypeScript, production build; local OIDC Playwright
  `58 passed, 14 skipped`, including WorkOrder readiness/evidence-gap at 390/768/1024/1440;
  `uv lock --check`, diff and repository hygiene pass.
- FIELD-0a preflight: all pinned A/B/C checksums pass. No physical session has begun. The user chose
  `$HOME/.local/share/ksi-field-evidence` as the canonical owner-private local store; root/session
  must be 0700 and raw/attestation files 0600 with symlinks rejected. The software audit is correctly
  `BLOCKED` for missing Pilot import, Pilot-native export, M4D original and human attestation; it does
  not represent device contact or device write.
- Next physical action: create one 0700 direct-child session in the private local store, then
  collect the propeller-removed/no-flight Pilot 2 and M4D evidence exactly as
  `docs/hil/FIELD_0A_CHECKLIST.md` requires. Phase 3 and all five DJI capabilities remain
  `BLOCKED`/`NOT_VERIFIED`.

---

## 2026-08-26 — `local_main_dirty_integration_complete`

- Local commits: `35e73ef` Core/contract, `8674e86` DJI capability routing, `13f4a16`
  Dashboard, `9b6b1bc` deployment/OIDC, `b2d4f26` HIL gates, `a28eea1` prototype,
  `b82211e` product docs, `5f00a0f` repository hygiene, followed by this handoff metadata commit.
- Excluded: `download/` DJI flight record/M4D originals, root `Testing/`, runtime data, real attestation
  key manifest, signing keys and `deploy/secrets/*.secret`. No tracked reference pin changed.
- Verification: Python `3864 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `391 source files`;
  Dashboard `58 files / 527 tests`, ESLint, TypeScript, production build, npm audit 0;
  local OIDC Playwright `54 passed, 14 skipped`; prototype protected runtime `28 files`, build,
  Sites `4 passed`, Playwright `22 passed`; `uv lock --check` and `git diff --check` pass.
- Review verdict: software integration is ready in local `main`. The prototype emits a non-blocking
  ~501 kB minified chunk warning. FIELD-0a/Phase 3 remains BLOCKED and five DJI capabilities remain
  `NOT_VERIFIED`.
- Remote state: no push, release, tag, deployment mutation, device write or flight action.

---

## 2026-08-26 — `phase_3_read_only_hil_software_preflight`

- FIELD-0a kit: SHA-256, exact safe archive members, 80 waypoint/80 photo actions and 40m execute
  height pass for A/B/C.
- Existing evidence: Pilot 2 A-file map screen was visually rechecked. One original M4D WideCamera
  `.jpg` is an intact two-frame MPO with 5280×3956, 12.29mm/24mm focal metadata and VERIFIED
  capture-time extraction. Raw GPS and device serial were neither copied nor emitted.
- Audit: `audit_phase3_readiness.py` writes an exclusive 0600 private manifest, rejects unsafe KMZ,
  and cannot promote Pilot-export bytes without source attestation.
- Verification: related FIELD/KMZ/capture-time contracts `37 passed`; full Python `3864 passed,
  23 skipped, 3 xfailed`; Ruff; full Mypy `391 source files`; deterministic kit byte comparison and
  SQLite-required Manifold container CTest `7/7` PASS.
- Current verdict: `PILOT_EXPORT_KMZ_REQUIRED`; formal FIELD-0a and Phase 3 remain BLOCKED. All five
  capabilities remain `NOT_VERIFIED`; no device/network/flight/write/customer-data action occurred.

---

## 2026-08-25 — `phase_2_synthetic_cloud_ai_staging_accepted`

- Runtime: isolated `ksi-phase2-staging` Compose project is active behind Tailnet HTTPS at Console
  `:10000`, Identity `:10001`, Core `:10002`, Object API `:10003`; MinIO console `:10004` is loopback.
- Data/auth: synthetic `org-local-pilot` OIDC only. Five real-domain-store Site fixtures are isolated;
  one Site has explicit synthetic AI opt-in. A SHA-256-bound PNG exists in MinIO and opens through a
  public presigned URL.
- AI safety: production grounded adapter reaches only a local no-outbound fixture. Normal same-site
  citation passes; opt-out, provider 503 and cross-site citation are durable `BLOCKED` results. No
  Mission, approval, coordinates, flight command or device evidence is produced.
- Recovery: backup bundle `ksi-vm-20260825T124618Z` passed three SHA-256 checks and isolated
  journal/object/signing-key restore.
- Browser: Phase 2 dedicated 12 scenarios pass across 390/768/1024/1440. External full suite is
  46 passed/22 intentional local-only or viewport skips.
- Verification: Dashboard `58 files / 527 tests`, ESLint, TypeScript, production build, npm audit 0;
  full Python `3858 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy `389 source files`; lock and diff
  integrity pass.
- Boundary: Cloud due diligence/customer data/actual external AI/IdP/public release and Phase 3 HIL
  remain unapproved. DJI five capabilities remain `NOT_VERIFIED`. No commit/push/release.

---

## 2026-08-25 — `operations_console_phase_1_software_ui_ux_accepted`

- Product result: Phase 1 software UI/UX baseline is `PASS`. The Home→Site→evidence/decision journey,
  Work queue, Items review and Site next action are accepted for current synthetic software scope.
- Scenario evidence: an E2E-only seeder uses the real Site, WorkArea, WorkOrder and Event stores plus
  legal transitions to create five populated states. A separate `org-local-empty` OIDC account verifies
  organization-isolated empty states. Mission, processing result, report ref, spatial model and device
  facts are deliberately absent; registered evidence metadata with unavailable image bytes renders an
  explicit preview failure.
- UX evidence: Site next action precedes AI briefing; Home setup copy no longer repeats the CTA; Work
  and Items empty states use one responsive next action. Four baseline images cover 390/768/1024/1440.
- Browser evidence: Playwright `54 passed, 2 skipped` across all four viewports. The skips are the
  intentional desktop exclusions for coarse-pointer-only touch sizing. OIDC populated/empty isolation,
  invalid callback recovery, keyboard/focus, overflow, reduced motion and axe all pass. Authenticated
  Tailnet review of Home/Sites/Work/Items/Site detail found no horizontal overflow or console errors and
  confirmed next-action-first ordering.
- Verification: Dashboard `58 files / 527 tests`, ESLint, TypeScript, production build; full Python
  `3848 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `388 source files`.
- Boundary: no customer data, external deployment, actual IdP, device/DPK/credential/flight action,
  commit, push or release. All five DJI data-path capabilities and HIL/FIELD remain `NOT_VERIFIED`.
- Next: Phase 2 synthetic Cloud/AI staging remains `PLANNED` and requires separate scope/authorization.

---

## 2026-08-24 — `operations_console_phase_1_truthfulness_hardening_verified`

- Core projection: Site workspace review count now represents open human decisions, excluding dismissed
  and resolved/closed items. Event list/detail contracts expose the count of non-tombstoned evidence,
  so the Console no longer guesses `근거 없음` before opening a detail.
- Scale/scope correction: SiteWorkspace and every Console surface that reports review items now paginate
  past Core's 500-item per-request limit instead of silently truncating. SiteWorkspace passes its explicit
  organization scope into Event projection, so request-context-free Copilot/internal projection cannot
  count another organization's Event with the same site reference. The same explicit scope now reaches
  ProcessingJob through the authoritative Mission record, so latest analysis/observation cannot select a
  foreign organization's epoch when no HTTP request context exists.
- Console UX: Site briefing distinguishes empty data from failed reads, renders captured time,
  uncertainty and same-site citations, and never turns arbitrary `sourcePath` into a link. Work queue
  grouping is deterministic; customer copy uses `현장 범위`, `비행 임무`, `확인 항목` while technical
  IDs and recovery controls stay in the expert surface.
- Accessibility completion: client-side route changes now focus the canonical main landmark without
  moving scroll or stealing initial hydration focus. E2E coverage now exercises keyboard skip-link and
  route focus, actual coarse-pointer CSS, 44px marked controls and axe across Home/Sites/Work/Review.
- Acceptance evidence: Phase 1 acceptance now names pagination completeness and request-context-free
  Event/ProcessingJob organization isolation. The phase registry was synchronized with the current
  executable evidence instead of retaining earlier intermediate test counts.
- Verification: full Python `3845 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy `387 source files`;
  Dashboard `55 files / 514 tests`, ESLint, TypeScript, production build; `uv lock --check`, Dashboard
  full/production `npm audit` with `0 vulnerabilities`, and `git diff --check` pass.
- Remaining acceptance: the current changed screens still need a connected real browser capture at
  390/768/1024/1440 with OIDC, keyboard/focus, overflow, reduced motion and axe. No browser was available
  to the active Codex browser controller, so `phase-1-console` remains `IN_PROGRESS`.
- Boundary: no customer data, external deployment, device/DPK/credential/flight action, commit, push or
  release. All five DJI data-path capabilities remain `NOT_VERIFIED`.

---

## 2026-08-24 — `operations_console_phase_0_1_baseline_complete`

- Product/design authority: ADR-KSI-027 fixes the delivery order as Console UX → synthetic Cloud/AI
  staging → RC-first HIL → verified integration → single-customer Field Pilot. The Phase 1 standard
  and acceptance document make Home a portfolio entry, Site workspace an evidence/decision space, and
  Pilot 2 a flight-only surface. The generated design-system guidance was corrected to the existing
  neutral, evidence-first product system; marketing hero, WebGL, fake imagery and generic AI-chat
  patterns are explicitly prohibited.
- UX correction: `/sites` is now mobile/tablet-card projection through 1279px and the dense comparison
  table begins at 1280px. At 1024px desktop permissions remain available in the card, while 390/768
  remains read/triage/analysis-only. Technical Site IDs and the detached `World` CTA are absent from
  the normal list. `/field` now begins with a compact decision/progress/history summary rather than a
  tall system explanation; compact blocked-action notices no longer repeat Core implementation detail.
- Verification: Dashboard Vitest `52 files / 505 tests`, ESLint, TypeScript, and production build pass.
  Actual Tailnet Playwright against `http://dgx-spark-1.tailda9552.ts.net:3210` passed `20/20` across
  390/768/1024/1440, including the new compact site-list presentation, no horizontal overflow, workspace
  tabs, keyboard/axe severe/critical and reduced motion. `git diff --check` passes.
- Boundary: no Business API/device wire migration, customer data, external deployment, device/DPK/
  credential/flight action, commit/push/release was performed. This is software UX evidence only;
  `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, and `MEDIA_UPLOAD` remain
  `NOT_VERIFIED` until their separate HIL evidence.

---

## 2026-08-23 — `tailnet_authjs_state_cookie_isolation_verified`

- Root cause: the Tailnet callback was reading a generic `authjs.state` cookie. Browser cookies ignore
  port, so an earlier/parallel Auth.js flow on the same MagicDNS host could cause
  `InvalidCheck: state value could not be parsed` and redirect to the generic configuration error page.
- Fix: all Auth.js cookies are KSI-owned (`ksi_auth_session`, `ksi_auth_v1_*` callback/CSRF/PKCE/state/
  nonce/challenge). Auth errors now use the public `/login` recovery page instead of `/api/auth/error`.
  The opaque session remains HttpOnly; LOCAL Tailnet stays HTTP-only and EXTERNAL_VM stays secure-cookie
  HTTPS-only.
- Runtime: `ksi-operations-console-dev.service` was restarted at 21:59 KST and is active. An old open
  issuer tab cannot be resumed; start a new login at
  `http://dgx-spark-1.tailda9552.ts.net:3210/login`.
- Verification: Dashboard `52 files / 505 tests`, ESLint, TypeScript, production build; local Chromium
  4 widths `8 passed`; actual Tailnet fresh login plus foreign-cookie regression `2 passed`. An injected
  invalid KSI state deliberately logs `InvalidCheck` but returns the login recovery UI, not a generic
  Server error.

---

## 2026-08-23 — `local_oidc_restart_recovery_and_default_dev_entry_verified`

- Local Identity refresh grant는 raw bearer token을 저장하지 않고 SHA-256 verifier·account·scope·
  expiry만 `.dev-data/local-identity/local-oidc-refresh-grants.json`에 atomic 0600으로 보관한다.
  issuer restart 뒤 새 grant refresh와 rotation replay 거부를 contract test로 통과했다.
- Dashboard LOCAL fixture는 `개발 Operations Console 시작` 한 번으로 default `local-admin` OIDC
  redirect를 시작한다. Code+PKCE/state와 encrypted HttpOnly session은 유지된다. `권한별 화면
  테스트`만 Local Identity selector를 열며 EXTERNAL_VM은 local fixture opt-in을 기동 전 거부한다.
- invalid refresh 401은 base/chunk auth cookie를 모두 지우고 local-specific recovery copy를 보인다.
  21:20 KST stack restart 전 browser session은 한 번 다시 로그인해야 하며 이후 새 grant가 durable하다.
- Runtime: `ksi-operations-console-dev.service` active; Tailnet Console
  `http://dgx-spark-1.tailda9552.ts.net:3210/login`; Local Identity `:9010`; Core private `8012`.
- Verification: focused OIDC/prod profile `32 passed`; full Python `3841 passed, 23 skipped, 3 xfailed`;
  Mypy `387 source files`; Ruff; Dashboard `52 files / 503 tests`, ESLint, TypeScript, production build;
  actual Tailnet default authorize `302`; `git diff --check` pass.

---

## 2026-08-23 — `unblocked_software_complete_hil_physical_gate_pending`

- Console/AX: 현장 중심 workspace, 반응형 Operations Console, 현장 AI/브리핑·저장형 대화와
  기존 URL 호환은 소프트웨어로 검증됐다. AI는 citation이 있는 읽기/초안 경로만 가지며,
  Mission 발급·사람 승인·비행 좌표/명령에는 접근하지 않는다.
- Security: Event/evidence/triage와 설계 기준면·작업구역·관련 worker queue·device sequence까지
  요청 principal의 organization scope를 강제한다. 다른 조직 객체는 404/빈 결과로 처리한다.
  Dashboard 지도 dependency는 bounded direct GeoTIFF overlay로 전환했고 `npm audit` 및
  `npm audit --omit=dev` 모두 0 vulnerabilities다.
- Verification: full Python `3839 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy `387 source files`;
  Dashboard `52 files / 500 tests`, ESLint, TypeScript, production build; Playwright `16 passed`;
  native Manifold `4/4`, PSDK logic `2/2`; `git diff --check` pass. 경고 446건은 기존 dependency/
  ONNX 계열 deprecation 등이며 통과를 production/HIL 증명으로 해석하지 않는다.
- HIL readiness: private ignored `hil_raw_logs/SESS-20260823T103223Z-PENDING-SN` preflight는
  `172.30.1.33` ARP neighbour 없음 및 100% packet loss를 기록했다. `MANIFOLD_UNREACHABLE`이므로
  adapter/feature flag는 꺼져 있다. RC-first session
  `hil_raw_logs/CONNECTED-20260823T103253Z-PENDING-AIRCRAFT`은 다섯 capability를 모두
  `NOT_VERIFIED`로 고정한다.
- Next gate: 물리 연결 후 read-only HIL → FIELD-0a 실제 Pilot 2/M4D evidence → 승인된 external
  IdP/Cloud staging and restore rehearsal. 장비 write·DPK·credential·flight·고객 데이터·외부 배포·
  commit/push/release는 하지 않았다.

---

# Current Task State (2026-08-22, persistent Tailnet development access)

- Status: `tailnet_dev_service_active_and_enabled`.
- URL: `http://dgx-spark-1.tailda9552.ts.net:3210/login`; synthetic Identity is the same node on
  `:9010`. Both are Tailscale Serve-only proxies to `127.0.0.1`; Core remains private on `8012`.
- Default/rollback: `npm run dev` uses `--tailscale required`; `npm run dev:local` is the explicit
  loopback-only fallback. Missing/offline Tailscale fails startup instead of exposing LAN.
- Persistence: `ksi-operations-console-dev.service` is user-systemd `active` and `enabled` with
  `Linger=yes`, `Restart=on-failure`; it survives SSH disconnect and starts after reboot/login manager.
- Evidence: full Tailnet OIDC redirect/account selection/token callback completed to Home as
  `local-admin`; Core returned real local Site/next-action state. Remote Next asset `18/18` and
  `/_next/hmr` WebSocket passed. Existing Serve port 80→3100 remains unchanged.
- Verification: local issuer `5 passed`; dev/VM/production closure `64 passed`; Dashboard
  `49 files / 484 tests`, TypeScript, ESLint, Next build; focused Mypy/Ruff and `git diff --check` pass.
- Limitation: Tailnet HTTPS Serve is not enabled at the tailnet account level, so dev URLs use HTTP
  inside the encrypted Tailnet. Production external Cloud remains HTTPS/OIDC-only.
- Safety: synthetic data only; no public Funnel, LAN bind, customer data, device, commit/push/release.

---

# Current Task State (2026-08-22, Operations Console U0)

- Status: `operations_console_u0_implemented_field0a_gate_open`.
- Shared decision: 새 `OperatorNextAction`이 미조치 Event → BLOCKED 작업 → 승인/재관측 대기 →
  진행 중 Acquisition → 결과 준비 → 현장 등록 → AOI → 베이스라인/재조사 순서를 기존 사실로만
  결정한다. 조회 실패 시 일부 사실로 행동을 추측하지 않는다.
- Flow correction: Home 상단과 portfolio, `/field` 빈 상태, 현장 목록과 Site header가 같은
  결정을 사용한다. AOI 없는 `LOCAL-VALIDATION-001`은 모두
  `/sites/LOCAL-VALIDATION-001#site-aoi`의 `AOI 설정하기`로 연결되고 Site AOI section에 실제
  editor가 있다. `Mission 발급`은 Wizard 최종 단계 밖에서 새로 노출하지 않는다.
- Empty/mobile state: Event 0건에서 우측 선택 패널을 제거해 단일 빈 상태만 남겼다. 390/768은
  운영 행동 링크 없이 `노트북에서 계속`을 표시하고 1024/1440은 권한 있는 CTA를 표시한다.
- Verification: Dashboard `49 files / 484 tests`, TypeScript, ESLint, Next production build;
  Chromium 390/768/1024/1440 action boundary와 horizontal overflow; full Python `3819 passed,
  23 skipped, 3 xfailed`; Ruff; full Mypy `383 source files`; native non-SQLite CTest `7/7` 통과.
- Tooling correction: running local OIDC stack의 generated `.next-local-oidc`를 ESLint/Git ignore에
  추가했다. 호스트 SQLite3 development package는 없어 native WAL backend 검증은 이번 run에서
  수행되지 않았다.
- Open gates: FIELD-0a Pilot 2 export mapping KMZ와 실제 M4D EXIF/XMP 연결이 먼저다. 최종 IA,
  public Staging, 실제 IdP/Cloud 승인, DJI HIL/adapter, FIELD-1/2는 시작하지 않았다.
- Safety: 다섯 DJI capability는 모두 `NOT_VERIFIED`; device/DPK/credential/flight/customer data/
  external deployment/commit/push/tag/release는 수행하지 않았다.

---

# Current Task State (2026-08-21, production-equivalent local OIDC development)

- Status: `local_oidc_stack_implemented_and_verified`.
- Standard local command: `cd apps/dashboard && npm run dev` launches a loopback-only Local Identity
  issuer (`127.0.0.1:9010`, canonical public `localhost`), Core OIDC verifier (`127.0.0.1:8012`) and
  Operations Console (`localhost:3210`) together. The existing user-owned dev processes are not replaced.
- Human flow: Dashboard does not render the opaque Bearer form by default. It redirects to a clearly
  synthetic KSI Local Identity account selection, then Auth.js retains tokens in its encrypted HttpOnly
  server session while Core validates a signed access token through the issuer JWKS.
- Local persistence: Core journals are in ignored `.dev-data/local-oidc-core`; Local Identity key and
  client/session secret files are in ignored `.dev-data/local-identity` with owner-only file mode.
- Security/rollback: local issuer refuses non-loopback origin/bind; VM compose/image/start launcher do
  not reference the fixture. Gateway/Edge/worker opaque credentials remain separate. Only an explicit
  LOCAL `KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED=1` opens the legacy diagnostic field; EXTERNAL_VM
  remains OIDC-only fail-closed.
- Actual browser: synthetic `KSI 개발 관리자` account selection completed and landed at
  `http://localhost:3210/field`; the console showed `local-admin` without a Bearer input field.
- Verification: local issuer/Core/VM focused contract `79 passed`; full Python `3819 passed,
  23 skipped, 3 xfailed`; full Mypy `383 source files`; Dashboard `47 files / 465 tests`, ESLint,
  production build, Node syntax and `git diff --check` all passed.
- Hardware boundary: no device, DPK, credential, flight, customer data, external deployment, commit,
  push, tag or release action was performed. DJI/FIELD/HIL capability status is still `NOT_VERIFIED`.

---

# Previous Task State (2026-08-21, Operations Console + external VM readiness)

- Status: `responsive_console_and_vm_assembly_implemented_external_release_not_approved`.
- Product surface: `/field` is a normal Operations Console shell route. RC Plus 2/Pilot 2 owns
  flight and gateway connectivity only; there is no product Bridge entry point.
- Responsive boundary: below 1024px permits read/event triage/analysis/Copilot/report access and
  replaces WorkOrder/reobservation/Mission/site-device/media/recovery writes with a laptop notice.
  It is SSR-safe and not an authorization boundary; Core roles remain authoritative.
- HIL isolation: Pilot Bridge is under `/hil/pilot-bridge`, requires an explicit non-production flag,
  and disabled/production requests receive HTTP 404. `/api/auth/session` also returns 404.
- Human/device auth: Dashboard uses Auth.js custom OIDC with PKCE/state, encrypted HttpOnly JWT
  session and server refresh. Core validates JWT/JWKS and KSI identity claims; opaque gateway,
  edge and worker credentials remain independent. OPAQUE/DUAL/OIDC migration modes are explicit.
- VM assembly: additive `compose.vm.yaml` adds non-root Dashboard and Caddy. Compose resolution proves
  only Caddy publishes 80/443; Core/MinIO/NodeODM/worker remain private. Internal S3 I/O and public
  presigned endpoints are separate.
- Fail-closed: external VM launcher exits 1 before Next starts when secret/TLS/OIDC config is absent.
  Secrets are file-mounted; no plaintext example secret is committed.
- Backup/restore: production defaults are unchanged. Synthetic smoke substitutes unique temporary
  volumes, creates three archives, verifies SHA-256, restores into isolated volumes, and cleans up.
- Cloud legality: provider due diligence is `NOT APPROVED`; only development/synthetic data is allowed.
- Verification: full Python `3812 passed, 23 skipped, 3 xfailed`; post-change focused `66 passed`;
  Ruff and full Mypy `381 source files`; Dashboard `46 files / 463 tests`, ESLint and Next build;
  Chromium at 390/768/1024/1440 with no horizontal overflow or console error; SQLite-required
  arm64 Manifold CTest `7/7`; Caddy config, compose exposure, production image and backup/restore pass.
- Open gate: real external IdP login/logout/refresh, public DNS/ACME certificate and full VM restore
  rehearsal on the selected provider are not claimed. npm production audit reports critical 0,
  high 9, moderate 2, low 5 and remains a release blocker pending compatible upgrades/review.
- Hardware boundary: all DJI capabilities and FIELD/HIL stay `NOT_VERIFIED`; no device, flight,
  credential, customer-data, production, commit, push, tag or release action was performed.

---

# Current Task State (2026-08-21, KSI Cloud Coordination Foundation)

- Status: `cloud_coordination_implemented_rc_hil_not_verified`.
- Cloud boundary: no `cloud/` directory was created. `apps + services + deploy` is the
  logical KSI Cloud boundary, `contracts + packages` are shared contracts, and `edge`
  owns field-device runtime. No empty or fake DJI Gateway container was added.
- AcquisitionRun: Core now stores the durable key
  `(organizationId, workOrderId, cycleNumber)`, replays it fail-closed, links one Mission
  idempotently, and projects the fixed acquisition stages from existing authoritative
  WorkOrder/Mission/activation/SourceMedia/Processing journals.
- Approval boundary: WorkOrder human approval is durable before coordinator callback;
  coordinator failure does not roll back approval. GET progress reconciles a missing run.
  Temporary stale/offline readiness stays `WAITING_READINESS`, not permanent `BLOCKED`.
- Mission lineage: `MissionPlanRequest.workOrderId` accepts only same-organization,
  same-Site approved work. The Mission record, WorkOrder `missionIds`, and exact run cycle
  are reconciled idempotently after issuance without guessing aircraft profile or route.
- Gateway receipt: `POST /v1/gateway-sync/operation-receipts` is restricted to a bound
  `GATEWAY_DEVICE`. It validates organization/Site/profile/Mission/device, preserves one
  idempotency key across transport fallback, and rejects nonce or digest reuse conflicts.
- Progress API/UI: WorkOrder detail shows one operator action, Acquisition progress,
  separate RC/Manifold/direct/contract/raw-media states, then expert recovery. Only an
  Edge activation fact can display `READY_FOR_FLIGHT`; active-contract network loss is a
  warning and does not create automatic STOP or state regression.
- Rollback: `KSI_CORE_ACQUISITION_COORDINATION_ENABLED=true` independently controls the
  new coordinator surface. `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false` remains the
  HIL-safe default; Mission Contract writer remains `1.2`. Manual KMZ and ground ingest
  remain available.
- Verification: clean full Python `3782 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy
  `378 source files`; Dashboard `44 files / 440 tests`, ESLint and Next production build;
  real Chromium WorkOrder/progress/Wizard rendering with no console warning/error;
  SQLite-required Manifold CTest `4/4`; PSDK logic CTest `2/2`; `git diff --check` passed.
- Independent acceptance review: `Approved` for Cloud Coordination Foundation software,
  with no must-fix issues. Actual DJI/HIL/provider adoption remains `Blocked` pending
  the five capability evidence sets.
- Hardware boundary: the latest read-only probe still reports
  `172.30.1.33 dev enP7s7 FAILED` and 100% ping loss. `WAYLINE_DELIVERY`,
  `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, and `MEDIA_UPLOAD` remain
  `NOT_VERIFIED`; no Cloud/PSDK/MSDK/Dock/direct adapter was activated or fabricated.
- Safety: no device/DPK write, flight, external upload, production change, commit, push,
  tag, or release was performed. Existing `Testing/`, `download/` and concurrent changes
  were preserved.

---

# Current Task State (2026-08-20, MVP Integration Milestone 1)

- Status: `acceptance_kit_v1_2_ready_provider_hil_blocked`.
- Product boundary: closed-loop product foundation 위에서 concrete acquisition provider 하나를
  실증 선택하는 마일스톤이며, waypoint UI 자체 구현은 범위가 아니다.
- Capability research: PSDK는 Manifold 3의 M4D/4TD Pilot 지원과 camera media list/download를
  공식 문서화한다. Cloud API 공식 지원표는 M4D/M4TD를 Dock 3 경로에만 두고 RC Plus 2 +
  Pilot 2에는 M4E/M4T만 열거하므로 standalone M4D 조합은
  `UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX`로 BLOCKED다.
- Acceptance kit v1.2: check별 필수 assertion/operator attestation과 raw artifact SHA-256/size를
  가진 서로 다른 PASS envelope를 요구한다. session mismatch, 잘못된 stage, digest 변조,
  directory/symlink/non-private evidence, PENDING-SN/미종료 VERIFIED, decision record 없는 selection,
  Cloud가 BLOCKED가 아닌 PSDK 선택을 모두 거부한다. `preflight`는 read-only host 결과를 private
  JSON으로 수집하며 RFC1918 IPv4만 허용하고, 이미 VERIFIED/채택된 세션은 변경하지 못한다.
- Evidence storage: `session_manifest.json`과 `integration_manifest.json`은 0600, session과
  stage directory는 0700으로 생성한다. raw JPEG/GPS/SN/credential은 커밋 범위가 아니다.
- Host preflight (latest 2026-08-20T14:34:24Z): private session
  `SESS-20260820T134204Z-PENDING-SN`에서 `enP7s7`→`172.30.1.33`이 다시 실패했다. ARP는
  `FAILED`, ICMP는 3/3 손실이다. PSDK verdict는
  `MANIFOLD_UNREACHABLE`, aircraft link는 `UNKNOWN`; host USB는 PSDK blocker가 아니다.
- Current verification: M1 contract `36 passed`, M1 + Gateway `40 passed`; full Python
  `3722 passed, 23 skipped, 3 xfailed`; Ruff/format, full Mypy `357 source files`, real CLI
  v1.1→v1.2 upgrade/verify PASS; session/stage 0700, manifest/summary/evidence/lock 0600 확인.
  Independent v1.2 review는 acceptance-kit/security scope를 `Approved`(tracked must-fix 0), 실제
  provider adoption을 `Blocked`로 판정했다.
- Provider/runtime: 선택된 경로 없음, `ZeroTouchGateway` feature flag off, concrete adapter와
  WorkOrder→Mission→Gateway→Media orchestration은 미구현 상태를 유지한다.
- Safety: credential/DPK/device write/camera call/upload/flight/route/gimbal/firmware 작업을 하지
  않았고, commit/push/tag/release도 하지 않았다. Untracked `download/`와 `Testing/`은 현장
  media/GPS 가능 raw 자료로 취급해 이번 delivery/staging 대상에서 명시적으로 제외한다.

---

# Previous Task State (2026-08-20, closed-loop MVP)

- Status: `software_foundation_implemented_provider_hil_blocked`.
- Product: 단순 waypoint 편집기가 아니라 반복 관측→서버 계산→근거형 질문→
  사람 재관측 승인의 폐루프 건설현장 인텔리전스로 ADR-KSI-022를 확정했다.
- WorkOrder: 조직 범위 schedule/order/reobservation 원장, 단조 상태, optimistic
  approval, 재관측 초안+주문 atomic journal을 추가했다.
- Acquisition: Cloud/PSDK/MSDK 공통 Gateway는 feature flag와 실기 capability evidence가
  없으면 fail closed하며, 멱등 wayline/media 영수증만 원장에 남긴다.
- Edge: 흘림·GSD·overlap·가림 품질 결함에 대해 시도/시간/배터리/짐벌/
  사전 관측점·서명 정책 경계를 전부 통과할 때만 국소 행동을 허용한다.
- Copilot: 3개 읽기 tool + 1개 draft tool allowlist, 조직/현장 scope, 외부 AI
  egress opt-in, citation provenance, tool round/call/byte budget을 강제한다.
- Dashboard: `오늘 작업`과 5단계 상세, 화면당 기본 행동 하나, Copilot,
  사람 재관측 승인을 연결했다. 수동 임무/KMZ는 접힌 복구 도구다.
- Security boundary: 신규 WorkOrder/Copilot 표면은 조직 범위를 강제한다.
  기존 Site/Mission/Artifact 원장 전체의 다중 조직 migration은 완료되지 않아
  REQ-SEC-101/INV-060 전체 완료 및 다중 tenant 배포를 주장하지 않는다.
- Production boundary: 구체 DJI provider, 자동 media transfer, 실제 Intelligence
  query handler/LLM provider, WorkOrder→Mission orchestration은 아직 조립되지 않았다.
  Capability는 `NOT_VERIFIED`, feature flag는 off다.
- No production deployment, DB migration, device write, flight, push, tag, or release. The user
  authorized a local `main` checkpoint commit for next-session continuity.
- Verification: full Python `3686 passed, 23 skipped, 3 xfailed`; Ruff and full Mypy
  `355 source files`; Dashboard `41 files / 431 tests`, ESLint, TypeScript and Next production
  build; SQLite/WAL native CTest `7/7`; OpenAPI/contract, lock, hygiene, reference/pin, KMZ
  checksum and `git diff --check` gates pass.
- Independent acceptance follow-up: initial `Needs changes` found a Viewer-to-draft write bypass
  and WorkOrder list 200/404 contract mismatch. Both were fixed with negative tests; follow-up
  verdict is `Approved`, remaining must-fix `0` for software-foundation scope.

---

# Previous Task State (2026-08-20)

- Status: software_complete_field0a_residual_accepted_field0b_hil_blocked_on_lan
- Milestone: device evidence attestation + Mission Contract v1.3 ordering + AOL-1 capture-time
  lineage. Source implementation and fresh full-gate revalidation are complete.
- Device trust: CRITICAL machine evidence now requires an Ed25519 signature over exactly the seven
  public context fields. Core loads operator-provisioned `(deviceId,keyId)` public keys, distinguishes
  `deviceBound` from `deviceAttested`, and compares active dispatch mission/device/risk policy/
  calibration plus the pre-existing RiskField geometry/time/entity/uncertainty lineage. Manifold
  reads an external owner-only 0600 Ed25519 private key and signs through target-static OpenSSL;
  the PSDK app assembles `EdgePipeline → StoreForwardSyncDriver → CoreRestSyncTransport`.
- Mission Contract: v1.3 adds required server-issued `issuerId/siteSequence/issuedAt`. The consumer
  dual-reads v1.2/v1.3 and durably rejects sequence rollback, equal-sequence content changes, and
  v1.2 downgrade after a v1.3 high-water. The Core writer remains v1.2 by default; v1.3 activation
  is intentionally withheld until rollout/HIL evidence exists.
- Capture lineage: the processing worker extracts GPS UTC, offset EXIF, then explicit DJI XMP;
  naive time is unavailable and candidates over one second apart conflict. Core journals each
  result, snapshots the bundle window into a successful ProcessingJob, uses only `capturedTo` for
  freshness, and never falls back to registration time. Site detail nests this summary and the
  Dashboard consumes it; the legacy endpoint remains.
- Verification: final full Python `3635 passed, 23 skipped, 3 xfailed` with FD limit 8192; Ruff;
  full Mypy `345 source files`; Dashboard `39 files / 419 tests`, ESLint, TypeScript/Next production
  build; `uv lock --check`; API/contract/hygiene/reference guards; KMZ 12 tests and all SHA-256
  checks passed. Native SQLite/WAL CTest `6/6`, static-OpenSSL attestation CTest `6/6` with target
  binary free of dynamic `libcrypto`, and PSDK logic CTest `2/2` passed. The first whole-tree run
  exposed 12 assembly/fixture/contract-mirror regressions; all were fixed before this clean rerun.
- Independent acceptance follow-up: `Approved` for software handoff with no must-fix items. The
  approval explicitly excludes HIL/FIELD proof, production deployment, real key provisioning, and
  v1.3 writer activation. The official goal helper resolved only
  `mission-contract-no-issuance-ordering-field`; device-signature HIL and broad RiskField truth risks
  remain open/regressed as applicable.
- FIELD-0a (2026-08-20): `field-0a-kmz-acceptance` remains `in_progress`. Pilot 2 screenshots prove
  A-file import and map rendering. Operator-supplied original M4D WideCamera JPEGs are present only
  in the untracked `download/drone pictures/` folder: 5280×3956, EXIF focal length 12.29mm, 35mm
  equivalent 24mm, and explicit DJI XMP UTC capture time all verify. Dashboard shared camera focal
  length was corrected from 12.0mm to 12.29mm; focused Dashboard tests, lint, and production build
  pass. The raw files were not moved or committed. The remaining FIELD-0a acceptance artifact is a
  Pilot-exported mapping KMZ (plus its copy/source evidence).
- FIELD-0a transition decision (2026-08-20): the operator accepted
  `kmz-real-device-acceptance-still-unverified` as a residual risk after A-file import/map rendering and
  M4D WideCamera JPEG evidence. This does not alter the formal FIELD-0a criteria or claim a Pilot-export
  comparison; it permits FIELD-0b preparation while the goal remains `in_progress`.
- FIELD-0b HIL remains NOT_VERIFIED: on 2026-08-19T16:24:21Z, the read-only host probe
  again found `172.30.1.33 dev enP7s7 FAILED`; the host USB inventory contained no DJI
  target device. No DPK/device mutation or flight/gimbal command was issued. Manifold
  reachability, DPK startup, USB bulk, and frame/telemetry p95 therefore remain blocked.
- Connection follow-up (2026-08-20T03:32:32Z–03:34:28Z): `enP7s7` stayed link-up with
  carrier `1` and host address `172.30.1.43/24`, but the known Manifold candidate
  `172.30.1.33` remained `FAILED` for the full read-only watch. No new DJI USB device
  appeared and no network/device mutation was attempted.
- FIELD-0b preflight retries (2026-08-20T09:38:12Z and the standard read-only USB probe at
  2026-08-20T09:40:27Z): the host selected `enP7s7` for
  `172.30.1.33`, and its 1 Gbit/s physical carrier was up, but the neighbor remained `INCOMPLETE`, ICMP
  received no reply, and SSH returned `No route to host`. This is an observer-to-Manifold LAN blocker,
  not evidence that the DJI aircraft link failed. `scripts/manifold/probe_usb_bulk.sh` recorded
  `VERDICT=BLOCKED` before its remote collection could begin; no DPK, key, service, flight, gimbal, or
  firmware mutation was attempted.
- LAN detection follow-up (2026-08-20T03:49:44Z): `172.30.1.33` became ARP
  `REACHABLE` (`c0:ea:c3:6a:22:b0`) and answered ICMP. Read-only TCP probes found
  SSH/22 and HTTP-alt/8080 open, 80/443/8010 refused; the 8080 root returned an
  unauthenticated login page and SSH identified as `OpenSSH_8.2p1 Ubuntu-4ubuntu0.11`.
  This proves network reachability only, not Manifold identity, DPK startup, PSDK
  connectivity, USB bulk, or flight capability. No credentials were entered and no
  device or service mutation was attempted.
- HIL connection session `SESS-20260820T035115Z-PENDING-SN` (2026-08-20): read-only
  SSH probe and Manifold environment inventory succeeded (`tegra-ubuntu`, aarch64,
  Ubuntu 20.04.6, L4T R35.5, TensorRT 8.5.2.2); DJI `Smart3DExplore` is installed and
  `dji_app_mgr`/`dji_sdk_agent` are running. `/dev/usb-ffs/bulk2..bulk5` and the
  Realtek Ethernet USB adapter are present. However remote `rndis0` (`192.168.42.2/24`,
  carrier `1`) could not reach the aircraft endpoint `192.168.42.1` (`0/3` ping), and
  no `/dev/ttyACM*` or `/dev/ttyUSB*` appeared. Verdict: `AIRCRAFT_LINK_DOWN`;
  DPK/PSDK/frame-timing stages remain blocked. Raw evidence is staged under
  `hil_raw_logs/SESS-20260820T035115Z-PENDING-SN/`.
- RC Plus 2 powered-on follow-up (2026-08-20T04:02Z–04:03Z): the same read-only
  Manifold probe observed recurring DJI `Liveview uuid info` and `device_auth online
  to uav` messages after the RC was powered. `rndis0` remained `192.168.42.2/24`
  with carrier `1`; `192.168.42.1` still did not answer ICMP and no serial device
  appeared. This is positive aircraft-link evidence from the DJI service layer, not
  yet a PASS for PSDK/telemetry or an aircraft identity readout. No device mutation,
  firmware update, mission start, flight, or gimbal command was issued.
- Operator-reported RC screen follow-up (2026-08-20): RC Plus 2 displays Manifold 3
  and reports the aircraft connected. Screenshot and Pilot 2 status text are still
  pending, so this remains operator-reported connection evidence rather than a
  complete FIELD-0b telemetry PASS. No update or mission execution was requested.
- Route-transfer UX observation (2026-08-20): host USB enumeration detects `DJI RC
  PLUS 2` as an MTP device with an accessible internal `Download` directory, so an
  SD-card requirement is not fundamental. A read-only MTP listing did not yet show
  the FIELD-0a `.kmz` files in `Download`, `Documents`, `DJI`, `DCIM`, or common media
  folders after the operator reported copy/paste; transfer completion/target folder
  remains to be confirmed. No device-side write was performed by the agent.
- Operator-reported FIELD-0a follow-up (2026-08-20): Pilot 2 route library displays
  `KSI-FIELD0A-A-droneEnum-100-payload-98`. The deterministic kit geometry is a
  synthetic 80-waypoint grid (40 m execute height, 18 m spacing, 8 m capture interval)
  over approximately lon `127.000000..127.001359`, lat `37.500081..37.500728`; it is
  an acceptance fixture that may look like the Banpo area, not an approved production
  mission. Map-preview screenshot and import-success details remain pending. Do not
  execute the route.
- FIELD-0a screenshot evidence inspected (2026-08-20): `download/IMG_20260820_132132.jpg`
  and `download/Screenshot_20260820-132126.png` show Pilot 2 rendering
  `KSI-FIELD0A-A-droneEnum-100-payload-98` on the map with status `정상`, `N 모드 - 대기`,
  `거리 671 m`, `예상 시간 7분 43초`, `웨이포인트 80`, and `사진 80`; the 80-point
  grid and camera action markers are visible. This closes the A-file import/map-display
  subcriterion, but the overall `field-0a-kmz-acceptance` remains `in_progress` until
  the Pilot-exported KMZ and original ground JPEG/EXIF evidence are collected. The
  same screen shows a firmware-consistency warning and a blue route execute control;
  neither was selected.
- Previous milestone gate revalidation (before the current attestation/v1.3/capture-time diff,
  2026-08-20): `ulimit -n 8192 && uv run --locked pytest -q`
  passed `3591 passed, 23 skipped, 3 xfailed`; Ruff, full-scope Mypy (`341` files),
  `uv lock --check`, Dashboard `tsc`/`39 files · 419 tests`/ESLint/Next build, KMZ
  SHA-256, repo hygiene/reference/third-party pin checks all passed. SQLite-required
  normal CTest passed `6/6` in the pinned arm64 container; the same container with
  ASan/UBSan also passed `6/6`. PSDK tap logic passed `2/2` and the default configure
  remained fail-closed. Native activation, EventBundle, and vertical-slice oracles
  passed; target arm64 CTest, ABI, and flight-boundary checks passed.
- ABI note: the pre-existing host `build-main-verify` binaries were correctly rejected
  for `libstdc++`/newer GLIBC requirements; they are not target evidence. The rebuilt
  `KSI_TARGET_MANIFOLD3=ON` arm64 container binaries passed the ABI gate.

---

# Historical Task State

- Status: software_complete_hil_blocked
- Date: 2026-08-14
- Milestone: safety gate integration and H3/H4 evidence audit
- Baseline worktree: Dashboard audit follow-up changes plus DSM test-module rename are uncommitted and
  preserved. Initial `git diff --check` is clean.
- IFC: fixed the mm + `IfcMapConversion` double scale. Geometry-engine meter coordinates are restored
  to project units only for georeference transformation, then map scale is applied once. The
  `auto_local2global` output is normalized from explicit `TargetCRS.MapUnit`, or from project units
  when a present target CRS omits MapUnit; this closes the reverse 1000x expansion for mm
  `IfcRigidOperation` and MapUnit-omitted files. Focused IFC reference/conversion suite: 34 passed.
  Risk `bim-integration-ifc-mm-unit-double-scale` was audit-reopened for the follow-up regression and
  resolved again with those test refs in `.ksi/goals.json`.
- Mission Contract: added the installed `ksi-mission-contract-consumer` CLI and public-key-only registry.
  It calls `load_verified_contract`, rejects duplicate-key/oversized JSON, atomically persists exact
  bytes with mode 0600 only after VALID, keeps the previous active contract on candidate failure, and
  revalidates TTL/revocation on every active load. Its state directory must be a non-symlink directory
  owned by the process user with no group/other access (0700). This closes the package-level software
  caller gap but not the ledger risk: deployment through the Manifold PSDK application and HIL
  rejection evidence remain required, so `mission-contract-verification-unwired` stays open.
- CRITICAL RiskField: confirmation now requires all referenced artifacts to be registered and not
  tombstoned, reads the `application/json` RiskField bytes from storage, rejects malformed/oversized/
  empty geometry, checks validity covers `occurredAt`, entity coverage and positive finite horizon,
  and freezes exact content SHA-256 plus semantic metadata in `evidenceSnapshot`. Storage outage is
  503 and bundle/artifact races are 409. The old presence-only risk is resolved with these tests;
  residual RISK-003 production synthesis is separated as open `riskfield-production-generator-unwired`.
- Dashboard: integrated prior audit work. World now displays actual observation/Core receipt times,
  reporting-device count, uncertainty range and honest 2D/3D layer status without inferring online
  state. Fleet·Edge and Data·AI remain `준비 중` because heartbeat/device-lineage APIs do not exist.
- HIL: session `SESS-20260813T162327Z-PENDING-SN` was blocked before inventory. `ksi-manifold`
  (`172.30.1.33`) returned `No route to host` from both local addresses and neighbor state was
  `FAILED`; a 2026-08-13T17:04:01Z read-only retry had the same result. No DPK/device mutation or
  flight/gimbal command occurred. DPK startup, USB bulk channel, frame-telemetry p95 and RC Plus 2
  KMZ import remain NOT_VERIFIED. Evidence is staged under the ignored `hil_raw_logs/<session>/` path.
- Verification:
  - Full Python: `3031 passed, 22 skipped, 3 xfailed` (soft FD limit raised from 1024 to 8192; the
    unmodified limit caused infrastructure `Too many open files`, not test assertions).
  - Mission consumer trust-boundary tests: 11 passed; focused IFC/GeoTIFF suite: 34 passed; prior
    focused safety/API/IFC suite before the two follow-up regressions: 158 passed.
  - Ruff: pass. mypy CI scope: 296 source files pass. `git diff --check`: pass.
  - Dashboard: 23 files / 217 tests pass, ESLint pass, Next.js production build pass.
- Acceptance review: initial verdict was `Needs changes`; the stale IFC risk document and consumer
  state-directory trust checks identified by review have been corrected. The follow-up MapUnit and
  IfcRigidOperation regression fix also received `Approved` with no must-fix items. Hardware/Edge
  deployment findings remain explicit blockers rather than software completion claims.
- Git: no commit, push, tag or release was performed.

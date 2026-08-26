# Current implementation plan (2026-08-26, local main integration)

Requirement IDs:
- 기존 변경의 추적성 유지. 통합 자체는 신규 제품 요구사항을 추가하지 않는다.

Owner module:
- 저장소 전체 변경 분류와 Git history; 제품 소유권은 각 기존 모듈에 유지한다.

Acceptance criteria:
- raw 장비/매핑 원본, 생성물, secret/key를 제외한다.
- 제품 코드, E2E 안전 fence, 배포, HIL, 설계/문서, 메타데이터를 의미 있는 커밋으로 분리한다.
- 전체 software gate가 통과하고 로컬 `main`이 clean하다.
- 원격 push/release/tag/device write를 하지 않는다.

Contracts affected:
- 통합이 계약을 새로 바꾸지는 않는다. 포함된 Core/OpenAPI/schema 변경은 독립 기능 커밋이 소유한다.

Reference assets:
- 저장소 authority 문서와 현재 diff. `references/` runtime import 또는 pin 변경 없음.

Adoption decisions:
- ADOPT 검증된 변경; EXCLUDE `download/`, `Testing/`, ignored runtime data와 실제 secret;
  PRESERVE DJI `NOT_VERIFIED`와 FIELD gate.

Files to change:
- 검토된 dirty 파일과 `.gitignore`, `.ai` handoff만.

Tests:
- full Python, Ruff, Mypy, Dashboard Vitest/ESLint/TypeScript/build/audit/Playwright,
  prototype runtime integrity/build/Sites/Playwright, lock/diff/status integrity.

HIL or real-device assumptions:
- 없음. 소프트웨어 통합은 실장비 지원·비행 가능성·FIELD 통과 증거가 아니다.

License/data implications:
- 신규 dependency lock은 포함하되 실제 DJI/M4D 원본, customer data, credential은 포함하지 않는다.

Rollback:
- 아래 기능별 커밋을 역순으로 개별 revert한다. 원격 history는 변경하지 않았다.

Execution:
1. [완료] branch/remote/dirty/ignore/secret/large-file inventory.
2. [완료] 범주별 안전·추적성 review와 원본/생성물 제외.
3. [완료] 기능·배포·HIL·설계·문서·위생 커밋 분리.
4. [완료] 전체 software gate 재검증과 handoff 갱신.

---

# Current implementation plan (2026-08-26, Phase 3 read-only HIL software preflight)

Requirement IDs:
- FIELD-0a / ADR-KSI-020, REQ-ACQ-101/102; INV-001/002/040/041.

Owner module:
- `tools/hil/` and `docs/hil/`; no runtime or DJI adapter changes.

Acceptance criteria:
- A/B/C checksum, safe KMZ members, 80 waypoint/photo action and 40m height pass.
- Pilot import image and M4D WideCamera metadata are digest-bound without GPS/SN output.
- missing or merely present/unattested Pilot-export KMZ leaves FIELD-0a BLOCKED.
- Phase 3 and five capability flags remain BLOCKED/NOT_VERIFIED before physical approval.

Contracts affected:
- none. This is private evidence preparation only.

Reference assets:
- `FIELD_0A_CHECKLIST.md`, field0a-kit, capture-time extractor, Connected Edge v1.3 manifest.

Adoption decisions:
- REUSE existing capture-time truth gate; ADD read-only metadata/checksum audit; REJECT capability inference.

Files to change:
- HIL audit tool/test, Phase 3/FIELD-0a checklist and phase/task handoff ledgers.

Tests:
- targeted/full Python, Ruff/Mypy, checksum regeneration comparison and repository integrity.

HIL or real-device assumptions:
- none. No equipment contact; Pilot-export and physical session remain blocked.

License/data implications:
- no dependency or customer data. Raw JPEG/MPO stays ignored and is not copied; private output omits GPS/SN.

Rollback:
- remove the audit tool/test/document sections and ignored private manifest; runtime remains unchanged.

Execution:
1. [완료] authority/current evidence audit and safety boundary.
2. [완료] fail-closed FIELD-0a/private readiness audit tool and targeted tests.
3. [완료] full static/regression and deterministic kit verification.
4. [완료] final status/handoff with physical gate unchanged.

---

# Previous implementation plan (2026-08-25, Phase 2 synthetic Cloud/AI staging)

Requirement IDs:
- REQ-COP-101/102, REQ-SEC-101; INV-002, INV-040/041, INV-050/051, INV-060/061.

Owner module:
- `deploy/` isolated staging lifecycle, Core production OIDC/S3/Copilot adapters, Dashboard E2E fixture.

Acceptance criteria:
- Tailnet HTTPS, OIDC organization login, actual S3 evidence bytes, same-site grounded AI and fail-closed
  opt-out/provider/citation paths pass at 390/768/1024/1440.
- owner-only secrets and isolated journal/object/signing-key backup restore pass.
- no device, customer data, external AI, production release, or Business/Mission/device contract change.

Contracts affected:
- Business, Mission and device contracts unchanged. E2E seeder adds only synthetic bytes/digest and one
  scoped AI opt-in when explicitly requested.

Reference assets:
- production Core/Dashboard images, Local Identity fixture, S3 evidence adapter, VM backup scripts.

Adoption decisions:
- ADOPT isolated Compose/Tailnet HTTPS and production adapters; KEEP existing dev stack and HIL gates;
  REJECT external provider/customer data/fake device evidence.

Files to change:
- staging Compose/lifecycle/provider/state, E2E seeder/specs, acceptance/ops/phase and `.ai` ledgers.

Tests:
- Compose/Bash/contract, full Python/Ruff/Mypy, Dashboard Vitest/ESLint/TypeScript/build/audit,
  Playwright external suite and in-app Browser review.

HIL or real-device assumptions:
- none; all five DJI capabilities remain `NOT_VERIFIED`.

License/data implications:
- MinIO existing image and local fixture only; no customer data or external model egress.

Rollback:
- `phase2-staging.sh stop` preserves isolated volumes; `reset` removes only Phase 2 project/volumes.
  Existing 3210/8012/9010 stack and Tailscale Serve routes remain unchanged.

Execution:
1. [완료] Isolated TLS/OIDC/secrets and production profiles.
2. [완료] Actual MinIO bytes/presigned GET and backup/isolated restore.
3. [완료] Grounded AI opt-in/normal/provider/citation failure paths.
4. [완료] Four-viewport browser and software regression.
5. [차단] Phase 3 RC-first HIL until approved physical read-only session.

---

# Previous implementation plan (2026-08-25, Phase 1 final acceptance)

Requirement IDs:
- REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101.
- INV-002, INV-040/041, INV-050/051, INV-060/061.

Owner module:
- Dashboard E2E fixtures and Home/Site/Work/Items presentation.
- Local synthetic OIDC fixture and Phase 1 acceptance/state ledgers.

Acceptance criteria:
- Real domain-store populated scenarios and organization-isolated empty state cover next actions.
- Partial failure is visible and no Mission, processing, report, image-byte or device fact is invented.
- 390/768/1024/1440 OIDC/accessibility/visual E2E and authenticated Tailnet product review pass.
- Full repository and Dashboard gates pass without expanding claims into HIL or production.

Contracts affected:
- Business, Mission and device-wire contracts unchanged. E2E-only synthetic data is additive.

Reference assets:
- Existing Site/WorkArea/WorkOrder/Event stores, transition rules, neutral UI tokens and Local Identity.

Adoption decisions:
- ADOPT real store transitions and read-only populated E2E.
- KEEP truthful absent Mission/processing/report/image bytes and explicit preview failure.
- REJECT browser-side API mutation fixtures and fake device/HIL evidence.

Files to change:
- Dashboard E2E seeder/spec/snapshots, Local Identity fixture, small next-action/empty-state UI wiring,
  contract tests, Phase 1 acceptance and state ledgers.

Tests:
- Dashboard test/lint/type/build; Chromium 390/768/1024/1440; full Python and Mypy; diff integrity.

HIL or real-device assumptions:
- none; all five DJI capabilities remain `NOT_VERIFIED`.

License/data implications:
- no new dependency, customer data or external AI egress.

Rollback:
- E2E data is isolated and disposable; UI changes do not require data migration.

Execution:
1. [완료] authority/current structure audit.
2. [완료] populated, empty and partial-failure scenarios with real domain stores.
3. [완료] next-action-first and responsive empty-state UX polish.
4. [완료] 4-viewport OIDC/accessibility E2E and full static/repository gates.
5. [완료] authenticated in-app Browser review and formal acceptance/state ledgers.
6. [대기] separately authorized Phase 2 synthetic Cloud/AI staging.

---

# Previous implementation plan (2026-08-24, Phase 1 truthfulness hardening)

Requirement IDs:
- REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101.
- INV-002, INV-040/041, INV-050/051, INV-060/061.

Owner module:
- Dashboard: Site workspace, work/review queues, responsive action and citation presentation.
- Core: organization-scoped workspace and Event evidence projections.
- Docs/Acceptance: state honesty, citation navigation and independent HIL boundary.

Acceptance criteria:
- Failed reads are not rendered as zero/empty/success; open review counts and evidence counts match Core.
- Event pagination reads beyond the Core 500-item request cap, and explicit organization scope is enforced
  for Event and latest ProcessingJob even when SiteWorkspace projection runs outside an HTTP request
  context.
- AI citations only navigate through allowlisted Console routes and cannot become arbitrary links.
- Customer copy prioritizes 현장·근거·결정 and hides technical identifiers in expert recovery surfaces.
- Dashboard and full repository gates pass; current visual browser acceptance remains explicit if absent.

Contracts affected:
- Additive `evidenceCount` on Event summary/detail and matching OpenAPI/Dashboard types.
- SiteWorkspace shape unchanged; its review-count and next-action semantics are corrected.
- ProcessingJob wire shape unchanged; its internal site query accepts an optional explicit organization
  scope inherited from Mission authority.

Reference assets:
- Existing SiteWorkspace, Event evidence journal, WorkOrder projection, neutral UI tokens and
  ResponsiveActionBoundary.

Adoption decisions:
- ADOPT Core-derived evidence counts, deterministic queues and internal citation routing.
- REPLACE false empty states and developer-facing Mission/Gateway language in normal operations UI.
- KEEP Core RBAC, organization scope, legacy URLs and expert recovery paths.
- REJECT arbitrary source links, fake zeroes and unverified device status.

Files to change:
- Core Event/ProcessingJob/SiteWorkspace projections, OpenAPI/types, Site/Work/Event Dashboard surfaces
  and tests.
- Phase 1 standard, acceptance, registry and `.ai` state.

Tests:
- Full Python, Ruff, full Mypy; Dashboard Vitest/lint/type/build; diff integrity.
- 501-event Core/Dashboard pagination, partial-page failure, Event scope and ProcessingJob scope
  regressions.
- Browser 390/768/1024/1440 OIDC/keyboard/focus/overflow/reduced-motion/axe when controller is available.

HIL or real-device assumptions:
- none; all five DJI capabilities remain `NOT_VERIFIED`.

License/data implications:
- no new dependency, customer data or external AI egress.

Rollback:
- Additive schema/UI projection changes can roll back without journal or customer data migration.

Execution:
1. [완료] authority/current state audit and required implementation boundary.
2. [완료] Site workspace, Event evidence and work queue truthfulness hardening.
3. [완료] customer copy, safe citation route and partial-failure behavior.
4. [완료] full repository and Dashboard software gates.
5. [대기] connected real-browser acceptance for the current changed screens.
6. [차단] physical RC-first HIL and FIELD evidence.

---

# Previous implementation plan (2026-08-24, Operations Console Phase 0/1 completion)

Requirement IDs:
- REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101.
- INV-002, INV-040/041, INV-050/051, INV-060/061.

Owner module:
- Dashboard: 현장·작업·확인 항목의 반응형 UX, URL 호환, 접근성.
- Core: 기존 조직 범위 원장과 AI/권한 계약. 이번 UI 정리에서 Business API를 추측해 추가하지 않는다.
- Docs/Acceptance: 제품 역할, 단계 게이트, UX·AI·HIL 수용 경계.

Acceptance criteria:
- Home→현장→근거/결정 이동이 기술 ID를 요구하지 않고, Desktop/compact width가 동일한 사실을
  각자 읽기 좋은 방식으로 표현한다.
- compact UI에서 운영 write는 허위 버튼이나 빈 화면 대신 노트북 continuation으로 보이며,
  Core RBAC는 변경하지 않는다.
- 실제 HIL 증거가 없는 DJI 기능은 UI·문서에서 `NOT_VERIFIED`이며, Console test를 장비 실증으로
  해석하지 않는다.

Contracts affected:
- Business API, Mission Contract, device-wire 계약 변경 없음.
- Dashboard DOM 표현, UX acceptance/traceability와 design guardrail만 additive로 변경한다.

Reference assets:
- ADR-KSI-024/025/026, MASTER_PRD §7, 기존 `ResponsiveActionBoundary`, `EmptyState`,
  `SiteWorkspaceView`, WorkOrder/Event projection.

Adoption decisions:
- ADOPT: Phase 0→1→2→3→4→5 delivery gate와 현장명·근거·결정 우선 표현.
- REPLACE: compact width의 `/sites` 가로 비교표와 과도한 `/field` 시스템 설명.
- KEEP: legacy URL, Core RBAC, existing neutral tokens, Pilot 2 비행 전용 경계.
- REJECT: marketing hero, synthetic image, fake capability, AI 직접 승인·Mission·flight control.

Files to change:
- ADR/Phase standard/acceptance/traceability/phase registry/design-system documents.
- Dashboard `/sites`, `/field`, responsive action notice, browser regression.

Tests:
- Dashboard Vitest, ESLint, TypeScript, production build.
- Tailnet Chromium 390/768/1024/1440 navigation, compact site list, workspace tabs, overflow,
  keyboard/accessibility and reduced-motion checks.

HIL or real-device assumptions:
- none; all five DJI capabilities remain `NOT_VERIFIED`.

License/data implications:
- new dependency/customer data/external AI egress 없음; local synthetic identity/data only.

Rollback:
- Dashboard image and display components can roll back without data migration. Existing URLs, Core
  journals, manual recovery, feature flags and active Mission Contract behavior remain unchanged.

Execution:
1. [완료] Phase delivery ADR, UX standard, acceptance and traceability link.
2. [완료] mobile/tablet/1024 site-list projection and work-queue density correction.
3. [완료] real Tailnet browser and full Dashboard regression.
4. [대기] Phase 2 synthetic Cloud/AI staging gate.
5. [차단] Phase 3 RC-first HIL: physical equipment session and evidence.

---

# Previous implementation plan (2026-08-22, persistent Tailnet development access)

Requirement IDs:
- REQ-UX-101, REQ-SEC-101; INV-001/002, INV-040/041, INV-050/051, INV-060.

Owner module:
- Dashboard local stack runner, local-only Identity fixture, deploy user service.

Acceptance criteria:
- `npm run dev` requires an online Tailnet and exposes Dashboard `:3210`, Identity `:9010` through
  Tailscale Serve while all application processes bind only to loopback.
- remote OIDC login, Core-backed Home, Next assets and HMR work; service is enabled across SSH/reboot.

Contracts affected:
- Business/API/device contracts unchanged. Development origin policy accepts explicit same-node
  `*.ts.net` Serve origins only; production IdP HTTPS policy is unchanged.

Reference assets:
- existing local OIDC stack, `allowedDevOrigins`, Tailscale Serve and user systemd linger.

Adoption decisions:
- ADOPT Tailnet-only HTTP Serve because HTTPS Serve needs a one-time tailnet admin enablement.
- KEEP loopback binds and existing port 80 route; REJECT `0.0.0.0`/LAN fallback.

Files to change:
- Dashboard stack/package/config tests/README, local issuer/test, additive systemd unit, `.ai` state.

Tests:
- local issuer origin/redirect, production closure, Dashboard full test/type/lint/build,
  remote OIDC replay, assets and HMR, service active/enabled.

HIL or real-device assumptions:
- none; DJI capability remains `NOT_VERIFIED`.

License/data implications:
- no dependency/customer data. Tailnet development uses synthetic accounts/data only.

Rollback:
- `npm run dev:local`; disable user service; remove only Serve ports 3210/9010.

Execution:
1. [완료] current Tailnet/Serve/local OIDC audit.
2. [완료] Tailnet origin detection, same-node validation and persistent Serve configuration.
3. [완료] remote OIDC/assets/HMR and production closure regression.
4. [완료] linger-backed user systemd service enablement.

---

# Current implementation plan (2026-08-22, Operations Console U0)

Requirement IDs:
- REQ-UX-101, REQ-WRK-101, REQ-ACQ-101/102, REQ-MSN-101.
- INV-001/002, INV-010~013, INV-040~042, INV-050/051, INV-060.

Owner module:
- Dashboard: `OperatorNextAction`, Home/Today/Site/Event 화면과 responsive action boundary.
- Core: 변경 없음. 기존 조직 scope, RBAC, Site/WorkOrder/Acquisition 사실 원장을 사용한다.

Acceptance criteria:
- 로그인 뒤 최우선 실제 행동에 한 번의 CTA로 진입하고 빈 화면에서 막히지 않는다.
- AOI 없는 Site의 조사/Mission 우회가 없고 AOI 저장 뒤에만 조사 계획을 제안한다.
- Event 0건은 단일 빈 상태이며 모바일 운영 write는 1024px 미만에서 안내로 대체된다.

Contracts affected:
- Business API/OpenAPI/Mission/device-wire 계약 변경 없음.

Reference assets:
- 기존 `Headline`, `EmptyState`, `ResponsiveActionBoundary`, AOI editor, WorkOrder/Acquisition projection.

Adoption decisions:
- ADOPT: 기존 사실 원장과 권한을 입력으로 쓰는 순수 next-action 결정기.
- EXTRACT: Home·Today·Site가 공유하는 행동 우선순위.
- DEFER: 최종 6개 메뉴 IA와 정본 ADR/PRD 전환은 FIELD-0a 이후.
- REJECT: AOI 없는 Site에서 조사/Mission CTA를 직접 노출하는 경로.

Files to change:
- Dashboard next-action library, Home/Today/Site/Event/portfolio surfaces, EmptyState와 테스트.
- `.ai` 진행 상태. Business API와 장비 코드는 변경하지 않는다.

Tests:
- next-action 상태 매트릭스와 source wiring, Dashboard 전체 test/type/lint/build.
- 실제 Chromium 390/768/1024/1440과 전체 Python/Ruff/Mypy/native CTest 회귀.

HIL or real-device assumptions:
- 장비 없음. FIELD-0a와 다섯 DJI capability는 `NOT_VERIFIED`.

License/data implications:
- 새 dependency와 고객 데이터 없음. 합성 로컬 데이터만 사용.

Rollback:
- 데이터 migration·URL 변경 없음. Dashboard 코드만 이전 이미지로 되돌릴 수 있다.

Execution:
1. [완료] `OperatorNextAction` 상태 우선순위와 권한/반응형 행동 정의.
2. [완료] Home·`/field`·Site 목록/상세·Event 빈 상태 연결.
3. [완료] 단위/소스 wiring과 전체 소프트웨어 회귀.
4. [완료] 390/768/1024/1440 실제 브라우저 검증.
5. [대기] FIELD-0a 실제 Pilot 2 export 증거.
6. [대기] FIELD-0a 이후 최종 IA, 외부 Staging/HIL, FIELD-1/2.

---

# Current implementation plan (2026-08-21, production-equivalent local OIDC development)

Requirement IDs:
- REQ-SEC-101, REQ-UX-101, REQ-WRK-101.
- INV-001/002, INV-040/041, INV-050/051, INV-060.

Owner module:
- Dashboard: standard local entrypoint, Auth.js OIDC user session, no default Bearer UI.
- Core: development OIDC verifier assembly while preserving device credential separation.
- `tools/`: loopback-only synthetic OIDC fixture; never a production runtime dependency.
- Docs: Console local workflow and low-level opaque credential boundary.

Acceptance criteria:
- `apps/dashboard/npm run dev` starts Local Identity, Core in `OIDC`, and Dashboard with one canonical loopback origin.
- The login page redirects to synthetic Identity account selection and returns to `/field` without a Bearer field.
- PKCE token exchange, JWKS verification, Core KSI organization/role claims and refresh work in contract tests.
- The local issuer rejects non-loopback configuration and the VM profile has no local issuer/stack dependency.

Contracts affected:
- No Business API, Mission, device-wire, or production OIDC contract change.
- Local dev command and human login presentation change; opaque device/Gateway/Edge/worker contracts remain.

HIL or real-device assumptions:
- No device access. DJI capabilities and FIELD/HIL remain `NOT_VERIFIED`.

Rollback:
- `dev:dashboard` remains for explicit diagnostics; legacy opaque screen needs
  `KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED=1` in LOCAL only.
- EXTERNAL_VM never falls back to OPAQUE.

Execution:
1. [완료] Existing OIDC/session, Core verifier and local command audit.
2. [완료] Loopback PKCE issuer plus OIDC Core/Dashboard standard stack.
3. [완료] Default Bearer UI removal, documentation and production closure guard.
4. [완료] Full regression and real browser login verification.

---

# Previous implementation plan (2026-08-21, Operations Console + external VM readiness)

Requirement IDs:
- REQ-UX-101, REQ-WRK-101, REQ-MSN-101, REQ-ACQ-101/102, REQ-SEC-101.
- INV-001/002, INV-011/012, INV-040/041, INV-050/051, INV-060.

Owner module:
- Dashboard: one responsive Operations Console, SSR-safe action boundary, Auth.js BFF session.
- Core: OIDC JWT/JWKS validation, existing RBAC and organization isolation.
- Deploy: additive external VM composition, TLS ingress, secret files, backup/restore.
- DJI Gateway: UI 없음; RC connectivity only. Concrete adapter remains HIL-gated.

Acceptance criteria:
- `/field` is a normal shell route; 390/768 blocks operational writes with a laptop notice and
  1024/1440 exposes authorized actions on the same URL.
- mobile remains UX procedure, never an authorization identity; Core RBAC still decides writes.
- production HIL route and browser session token surface return 404.
- invalid OIDC JWT/claims and missing production OIDC/TLS/secrets fail closed.
- only Caddy publishes 80/443; private services have no published port in VM composition.
- synthetic backup/restore runs against isolated temporary volumes and verifies SHA-256.

Contracts affected:
- Business and acquisition schemas unchanged.
- static/runtime OpenAPI Bearer description distinguishes OIDC operators from opaque devices.
- deployment environment contract adds OIDC, origins, auth mode, public S3 endpoint and secret files.

Reference assets:
- Existing Dashboard tokens/shell/WorkOrder/Acquisition/Copilot surfaces.
- Existing Core Role/Permission and organization-scoped stores.
- Existing compose minimum, production parser, signing-key and object-storage procedures.

Adoption decisions:
- ADOPT: one responsive Web product, Pilot 2 flight-only ownership, existing role table.
- EXTRACT: shared `ResponsiveActionBoundary`; server-only OIDC session/token refresh.
- REPLACE: Pilot 2 webview/RC-specific Field shell and public inline login.
- REFERENCE_ONLY: HIL Bridge probe, gated outside production.
- REMOVE: product dependence on `window.djiBridge`; no DJI runtime/container added.

Files to change:
- Dashboard field shell/navigation/actions/auth/runtime/tests and production image.
- Core auth/OIDC/production/S3 public endpoint and contract tests.
- additive VM compose/Caddy/secrets/backup/restore/docs.
- ADR/product/system/UX/traceability and `.ai` state.

Tests:
- Core OIDC/JWKS/roles/device regression/org scope and production config.
- Dashboard action matrix, deep links, token exposure, test/lint/build and 4 viewport Chromium.
- compose port exposure, Caddy validation, image fail-closed, synthetic backup/restore.
- full Python/Ruff/Mypy and SQLite-required native CTest.

HIL or real-device assumptions:
- No equipment action. Five DJI capabilities and FIELD/HIL remain `NOT_VERIFIED`.
- No external IdP, public DNS/ACME, or real customer data is used in local verification.

License/data implications:
- Auth.js 5.0.0-beta.32 (ISC), PyJWT 2.13.0 (MIT), Caddy 2.10.2 (Apache-2.0),
  Node 22.18 image (MIT) are documented and locked at the declared boundary.
- Cloud due diligence remains `NOT APPROVED`; development/synthetic data only.
- Existing npm production audit high findings are an open release gate, not hidden as fixed.

Rollback:
- External VM profile is additive; local compose remains.
- OIDC migration may return to DUAL, but external public operation never falls back to OPAQUE.
- `/field`, WorkOrder/Mission journals and manual KMZ/ground ingest remain.
- HIL/Cloud/direct/MSDK/Dock feature flags remain independently off.

Execution:
1. [완료] Product ADR/system/ledger/UX and Cloud due-diligence boundary.
2. [완료] Responsive Console shell and action boundary; HIL probe isolation.
3. [완료] Dashboard Auth.js and Core OIDC/JWKS/device credential split.
4. [완료] External VM compose/Caddy/public S3/secrets/image/startup gates.
5. [완료] Backup/restore tooling, dependency baseline and synthetic smoke.
6. [완료] Full regression, four-width Chromium and honest unverified handoff.

---

# Current implementation plan (2026-08-21, KSI Cloud Coordination Foundation)

Requirement IDs:
- REQ-ACQ-101/102, REQ-WRK-101, REQ-MSN-101, REQ-EDGE-101/102,
  REQ-INT-101, REQ-SEC-101.
- INV-001/002, INV-010~013, INV-040~042, INV-050/051, INV-060.

Owner module:
- Core: WorkOrder, AcquisitionRun, Mission lineage, readiness/issuance policy.
- DJI Gateway: capability-specific operation receipt producer; concrete adapter는 HIL 뒤다.
- Dashboard: operator action, progress projection, recovery disclosure.
- deploy/docs: KSI Cloud composition and production configuration parity.

Acceptance criteria:
- `(organizationId, workOrderId, cycleNumber)` 승인 재시도가 run을 중복 생성하지 않는다.
- temporary readiness failure는 `WAITING_READINESS`, integrity failure만 `BLOCKED`다.
- active Mission Contract는 heartbeat 만료로 이전 단계로 돌아가지 않는다.
- workOrderId를 가진 Mission은 같은 조직·Site·APPROVED 회차에만 연결된다.
- Gateway receipt는 device/profile binding, org/site/mission, nonce/key/digest를 검증한다.
- `READY_FOR_FLIGHT` 전에는 UI가 준비 완료를 주장하지 않는다.

Contracts affected:
- Core OpenAPI additive `workOrderId`, acquisition progress, gateway operation receipt.
- Dashboard mirror types. Mission Contract와 기존 device wire schema는 변경하지 않는다.

Reference assets:
- ObservationWorkOrder status/lineage, MissionStore planRequest, AcquisitionConnectivityStore,
  EdgeDispatch activation receipt, SourceMediaStore, ProcessingJobStore, Gateway v1.3 receipt.

Adoption decisions:
- ADOPT: existing truth stores, server-component data fetch, manual KMZ/ground ingest recovery.
- EXTRACT: coordinator association/projection only; source facts are not duplicated.
- REPLACE: 없음. 빈 RC/Dock/MSDK/direct adapter를 만들지 않는다.
- REFERENCE_ONLY: HIL manifest and DJI headers until real evidence.

Files to change:
- Core acquisition context, WorkOrder/Mission assembly, OpenAPI/contracts.
- Dashboard WorkOrder detail/client/types/tests.
- deploy env/docs and `.ai` state/handoff.

Tests:
- replay/idempotency/crash recovery; org/site/cycle mismatch; stale heartbeat/no regression;
  Gateway receipt replay/tamper/device scope; OpenAPI mirror; Dashboard presenter and interaction.
- full Python/Ruff/Mypy, Dashboard test/lint/build, Chromium, native CTest, diff/hygiene.

HIL or real-device assumptions:
- `172.30.1.33` is currently unreachable. Five DJI capabilities stay `NOT_VERIFIED`.
- No device mutation or adapter rollout is included.

License/data implications:
- No new dependency. Raw device/media evidence stays in ignored private HIL storage.
- Presigned URL/digest and organization/site lineage remain mandatory.

Rollback:
- coordinator automation and issuance gate remain independently disableable.
- Existing Gateway facade/journal v1.2 reader and manual KMZ/ground ingest stay intact.
- Disabling new issuance never invalidates an already activated valid contract.

Execution:
1. [완료] Cloud boundary/deploy parity and `.ai` baseline.
2. [완료] AcquisitionRun/receipt/progress Core contract and implementation.
3. [완료] Mission WorkOrder lineage and approval linkage.
4. [완료] Dashboard progress UX and API mirror.
5. [완료] Full regression, Chromium/native checks and honest NOT_VERIFIED handoff.

---

# Current implementation plan (2026-08-21, RC-first Connected Edge foundation)

Requirement IDs:
- REQ-ACQ-101/102, REQ-WRK-101, REQ-MSN-101, REQ-EDGE-101/102,
  REQ-INT-101, REQ-SEC-101.
- INV-001/002, INV-010~013, INV-040~042, INV-050/051, INV-060.

Owner module:
- Core: profile·신원·readiness·신규 Mission 발급 정책.
- DJI Gateway: 기능별 port·route·receipt journal; 장비 adapter 경계.
- Manifold: 기존 로컬 계약·지능·transport-neutral outbox.
- Dashboard: preflight/postflight readiness projection.
- `docs/hil`/`tools/hil`: 기능별 실장비 evidence와 flag gate.

Acceptance criteria:
- RC Wi-Fi 기본 profile과 선택형 direct Edge profile이 strict schema/API round-trip한다.
- rollout flag가 켜진 배포에서는 만료/오프라인/binding 불일치/미검증 capability에서
  신규 Mission 발급이 409로 막힌다. flag 기본값은 HIL 전 OFF다.
- 활성 계약 유지 정책은 readiness 응답에 명시되고 연결 단절이 STOP을 생성하지 않는다.
- capability router는 기능·하드웨어·펌웨어·transport별 VERIFIED evidence만 선택한다.
- v1.2 journal은 추론 없이 읽고, v1.3 receipt는 capability·transport를 필수로 한다.
- Dashboard 상태가 한 개의 “연결됨”으로 합쳐지지 않는다.
- HIL v1.2 migration은 digest만 보존하고 모든 v1.3 capability를 `NOT_VERIFIED`로 둔다.

Contracts affected:
- additive `acquisition-deployment-profile.v1.json`, `connectivity-snapshot.v1.json`.
- Core OpenAPI v1.25.0 및 Dashboard mirror type.
- 기존 Mission/WorkOrder/Mission Contract wire schema는 변경하지 않는다.

Reference assets:
- 기존 Core journal/auth/API assembly, DJI Gateway v1.2 facade, Manifold outbox,
  Pilot 2 수동 KMZ와 ground ingest 복구 경로.
- 핀된 PSDK WebSocket header는 업링크 API 존재 확인에만 사용하며 지원 증거가 아니다.

Adoption decisions:
- ADOPT: 기존 서비스 경계·Mission 발급·store-and-forward·복구 경로.
- EXTRACT: Gateway combined provider에서 domain/ports/routing/persistence 책임.
- REPLACE: provider 하나 선택 가정을 capability별 route로 대체.
- REFERENCE_ONLY: DJI 문서·헤더와 과거 v1.2 provider evidence.
- REMOVE: 없음. 빈 미래 장비 adapter도 생성하지 않는다.

Files to change:
- `contracts/schemas`, `contracts/api/openapi-core.yaml`.
- `services/core/src/ksi_core/acquisition`, auth/app/mission assembly.
- `services/dji-gateway/src/ksi_dji_gateway/{domain,ports,routing,persistence}`와 facade.
- Dashboard Field readiness client/presenter/component.
- ADR·System Overview·Decision Ledger·HIL acceptance·`.ai` 상태.

Tests:
- schema/OpenAPI mirror, Core API/auth/org scope/Mission gate, Gateway router/journal,
  HIL migration, Dashboard presenter.
- full Python/Ruff/Mypy, Dashboard test/lint/build, native CTest와 필요한 Chromium UX.

HIL or real-device assumptions:
- 첫 대상은 RC Wi-Fi, Manifold SIM 없음이다.
- Cloud 업링크·하향·wayline·media는 각각 독립 `NOT_VERIFIED`에서 시작한다.
- Dock/MSDK/direct adapter는 실장비 증거 전 미구현·flag OFF다.

License/data implications:
- 새 외부 dependency와 라이선스 변화가 없다.
- raw device/media evidence는 `hil_raw_logs/` private 경로에만 두고 조직/site/mission
  lineage와 egress policy를 유지한다.

Rollback:
- capability별 flag를 독립 OFF하고 기존 `ZeroTouchGateway`/v1.2 reader를 유지한다.
- Pilot 2 수동 KMZ, SD/USB와 folder ingest 복구 경로를 제거하지 않는다.
- 새 발급을 닫아도 활성 Mission Contract를 네트워크 상태로 취소하지 않는다.

진행 순서:

1. [완료] 제품 책임 중심 소스 경계와 package 구조 확정.
2. [완료] Profile/Snapshot, 신원 분리, readiness API와 Mission 발급 gate.
3. [완료] capability port/router와 journal v1.2/v1.3 호환성.
4. [완료] Dashboard readiness와 HIL manifest v1.3.
5. [완료] ADR/정본/상태 문서 동기화.
6. [완료] 전체 회귀·보안 경계·Chromium 검증 후 handoff.

---

# Current implementation plan (2026-08-20, MVP Integration Milestone 1)

Requirement IDs:
- REQ-ACQ-101/102, REQ-WRK-101; INV-001/002/040/041/050/051/060.

Owner module:
- Acceptance/evidence: `docs/hil`, `tools/hil`.
- Provider 채택 후 구현: `services/dji-gateway`와 WorkOrder/Mission/Media orchestration owner.

Acceptance criteria:
- Cloud는 공식 지원 조합일 때만 workspace open, no-file wayline visibility, operator review,
  no-file media start, WorkOrder/Mission/Media lineage의 다섯 항목을 동일 환경에서 증명한다.
  현재 M4D + RC Plus 2 + Pilot 2 조합은 공식 matrix blocker evidence로 닫는다.
- PSDK는 Manifold/aircraft link, media list, original JPEG download+SHA-256, object/lineage,
  downloader-rights release의 다섯 항목을 증명한다.
- 모든 check와 세션 내부의 실제 evidence ref 없이는 `VERIFIED`와 provider selection을 거부한다.
- provider flag는 꺼진 상태를 유지하고 수동 KMZ/folder ingest를 복구 경로로 보존한다.

Contracts affected:
- 이번 준비 변경은 public API/계약을 바꾸지 않는다. `integration_manifest.json`은 HIL-local
  acceptance summary이며 저장소에 raw evidence나 secret를 넣지 않는다.

Reference assets:
- DJI Cloud API product support/firmware, FlightHub 2 product/FAQ, PSDK Manifold capability,
  camera-management tutorial/API reference, MSDK V5 support 문서.
- 로컬 `dji_camera_manager.h`, Manifold USB bulk HAL sample, `ZeroTouchGateway` capability journal.

Adoption decisions:
- Cloud는 현재 조합이 공식 지원표 밖이라 `BLOCKED`로 닫고 credential/기체 우회 실험을 하지
  않는다. PSDK를 실제 HIL 평가하며, 이것도 실패할 때만 MSDK spike를 별도 결정한다. 공식
  문서만으로 PSDK provider를 구현하거나 켜지 않는다.

Files to change:
- `docs/hil/MVP_INTEGRATION_M1_ACCEPTANCE.md`, `docs/hil/RAW_LOG_CONVENTIONS.md`,
  `tools/hil/prepare_mvp_integration_session.py`, focused contract tests, `.ai/` state/handoff.
- 실제 provider 소스는 acceptance PASS 전에는 변경하지 않는다.

Tests:
- manifest v1.2 check-specific PASS envelope, raw artifact digest/size 재검증, 서로 다른 per-check
  evidence, BLOCKED evidence, secret-like field 거부, relative evidence containment, symlink/owner/mode,
  실제 aircraft SN/종료시각, READY/decision record, Cloud-first 선택, read-only preflight, CLI summary.
- Ruff, formatting, Mypy, focused/full pytest, CLI init/preflight/verify smoke, diff/secret checks.

HIL or real-device assumptions:
- 2026-08-20T14:34:24Z 최신 재탐지에서도 host 유선은 link-up이지만 `172.30.1.33`은
  ARP `FAILED`, ICMP 3/3 실패 상태다.
  PSDK blocker는 `MANIFOLD_UNREACHABLE`이고 aircraft link는 `UNKNOWN`이다. host USB inventory는
  direct-host/MSDK 참고일 뿐 Manifold 내부 USB bulk를 쓰는 PSDK blocker가 아니다.

License/data implications:
- credential/token/private key는 CLI/manifest/log에 넣지 않는다. GPS, SN, original media는
  ignored `hil_raw_logs/`에만 두고 site egress policy 승인 전 외부 반출하지 않는다.

Rollback:
- 추가한 준비 도구/문서는 provider runtime과 독립적이며 제거 가능하다. Feature flag는 off이고
  기존 수동 Pilot 2 KMZ/folder ingest에는 변화가 없다.

Execution:
1. 이전 CLI checkpoint와 제품/안전 경계 복원 — complete.
2. 공식 DJI capability와 로컬 PSDK/Gateway 표면 대조 — complete.
3. secret-free Cloud/PSDK acceptance procedure와 fail-closed evidence tool v1.2 — complete.
4. private evidence session + read-only host preflight — complete;
   `SESS-20260820T134204Z-PENDING-SN`, PSDK HIL은 현재 연결 부재로 blocked.
5. 실제 PSDK HIL 5항목과 provider 채택 — pending, 장비/명시적 현장 승인 필요.
6. 통과 provider 하나의 orchestration 조립과 전체 검증 — pending.

---

# Previous implementation plan (2026-08-20, closed-loop MVP)

Requirement IDs:
- REQ-WRK-101, REQ-ACQ-101/102, REQ-INT-101, REQ-COP-101/102,
  REQ-SEC-101, REQ-UX-101; INV-001/002/010/020/040/041/050~052/060/061.

Owner module:
- Product/architecture contracts, Core, DJI Gateway, Manifold Runtime, Processing Controller,
  Dashboard.

Acceptance criteria:
- Observation Work Order가 반복 관측과 사람 승인, 수집·처리·결과,
  근거가 연결된 재관측 초안을 내구적으로 표현한다.
- DJI adapter는 feature flag와 실기 `VERIFIED` capability 근거가 둘 다 있을 때만
  wayline/media 작업을 수행하고 멱등 재시도한다.
- Edge는 검증된 Mission/Capture Policy 범위에서만 제한된 재촬영·짐벌·
  사전 승인 관측점을 허용하며 PSDK를 직접 호출하지 않는다.
- Copilot은 조직·현장 범위 typed tools가 반환한 근거만 인용하고,
  외부 AI 반출은 명시적 허용이 없으면 거부한다.
- Dashboard는 정상 흐름을 5단계·화면당 기본 행동 하나로 표시하고
  USB/SD/KMZ를 접힌 복구 도구로만 남긴다.

Contracts affected:
- Observation Work Order v1, Capture Policy/Quality v1, Copilot Answer v1, Core OpenAPI 1.24.

Reference assets:
- DJI 기본 비행/Pilot 2는 채택하되 실행 런타임은 참조 저장소에서
  import하지 않는다. Cloud/PSDK/MSDK 세부 지원은 실기 증거까지
  `NOT_VERIFIED`다.

Adoption decisions:
- Cloud/Pilot-to-Cloud → PSDK/Manifold → 얇은 MSDK 순으로 검증한다.
- LLM은 수치 계산기·비행 권위가 아니다. 재관측은 초안과 사람 승인을
  분리한다.
- 수동 KMZ·folder ingest는 제거하지 않고 rollback/장애 복구로 남긴다.

Files to change:
- `docs/product`, `docs/architecture`, `contracts`, `packages/event-contracts`,
  `services/core`, `services/dji-gateway`, `edge/manifold-runtime`, `apps/dashboard`, tests,
  `.ai/`.

Tests:
- WorkOrder replay/scope/version/approval, Gateway capability/idempotency/torn journal,
  Capture Policy negative decisions, Copilot allowlist/citation/egress/human approval,
  OpenAPI sync, Dashboard UX mapping, full Python/static/native/Dashboard gates.

HIL or real-device assumptions:
- Provider adapter·자동 media·PSDK 촬영 행동은 실기 증거 없이 활성화하지
  않는다. 현재 변경은 비행·장비 write를 수행하지 않는다.

License/data implications:
- 외부 LLM은 site egress policy 명시 허용 전에 호출하지 않는다.
  DJI SDK/Cloud, static OpenSSL의 약관·license·SBOM은 배포 전 게이트다.

Rollback:
- 각 adapter/feature flag를 독립적으로 끄고 기존 Pilot 2 수동 KMZ·folder ingest로
  되돌린다. 기록된 v1.3 high-water·attested evidence는 강등하지 않는다.

Execution:
1. Product decision/ADR/requirements/invariants — implemented.
2. Organization-scoped WorkOrder/schedule/reobservation ledger — implemented for the new surface.
3. Fail-closed provider-neutral DJI Gateway — implemented; concrete providers blocked on HIL.
4. Signed-policy capture-quality authorizer — implemented as pure native decision boundary;
   live PSDK wiring blocked on HIL.
5. Grounded Copilot orchestration and human-approved draft boundary — implemented;
   production model/query provider not configured.
6. Five-stage field Dashboard and recovery-only manual file path — implemented.
7. Full verification and current-state handoff — complete. Release remains blocked on the
   documented production migration/provider/HIL gates.

---

# Previous implementation plan (2026-08-20)

Requirement IDs:
- REQ-EVT-101, REQ-MSN-101, AOL-1 G1/G4.
- INV-011, INV-020, INV-021, INV-030, INV-040, INV-042, INV-051, INV-052.

Owner module:
- `services/core`, `packages/mission-contracts`, `edge/manifold-runtime`, `edge/psdk-app`,
  `services/processing-controller`, `apps/dashboard`.

Acceptance criteria:
- CRITICAL machine evidence is accepted only with a valid Ed25519 artifact signature and matching
  active-dispatch mission/device/risk-policy/calibration plus existing RiskField lineage.
- Mission Contract v1.3 is dual-read with v1.2, assigns a durable positive site sequence before
  signing, and rejects lower/equal-different replay and v1.2 downgrade after a v1.3 high-water.
- Every measured image has explicit capture-time source/status; bundle and ProcessingJob snapshots
  preserve a complete/incomplete/conflict window; freshness uses only `capturedTo`.
- `GET /v1/sites/{id}` returns a non-null nested spatial-model summary while list and legacy
  `/spatial-model` responses remain compatible.
- Full software gates pass without claiming production, HIL, flight, or field completion.

Contracts affected:
- Evidence `attestation={keyId,algorithm:"Ed25519",signature}` and response
  `deviceAttested`/`attestationKeyId`.
- Mission Contract v1.3 `issuance={issuerId,siteSequence,issuedAt}` plus dispatch schema dual-read.
- Per-file `captureTime`, bundle/ProcessingJob `captureWindow`, `SpatialModelView` capture fields,
  and `SiteDetailView`; OpenAPI/AsyncAPI/Dashboard mirrors are updated.

Reference assets:
- `docs/00_READ_FIRST.md`, Product Constitution, Final Decision Ledger, Master PRD,
  `DOMAIN_INVARIANTS.md`, ADR-KSI-019/020, relevant contract schemas, and pinned DJI samples.
- `references/` remains read-only and contributes no runtime imports.

Adoption decisions:
- Keep the Core writer default at v1.2 until dual-reader/high-water rollout and HIL are proven;
  v1.3 issuer identity is server configuration only.
- Keep `deviceBound` as channel identity and `deviceAttested` as artifact-signature truth. A device
  signature does not prove the sensor inference itself, so geometry/time/entity/uncertainty checks stay.
- Device public keys are operator-provisioned with no registration API. Edge private keys are read
  only from external owner-only 0600 files and never placed in DPK, env output, logs, fixtures, or repo.
- Link Ed25519 through target-static OpenSSL and reject dynamic `libcrypto` in the target ABI gate.
- Missing/conflicting capture time fails closed; never substitute `registeredAt`.

Files to change:
- Core evidence/dispatch/event/mission/site/source-media/processing/spatial-model/production assembly.
- Mission-contract models/signing/consumer/dispatch and v1.3 schema.
- Manifold attestation signer, Core REST sync, PSDK app assembly, CMake/Docker/ABI gates.
- Processing-controller capture extractor/client/worker; Dashboard site/detail types and labels.
- OpenAPI/AsyncAPI/contracts, contract/E2E/native tests, and `.ai` state/handoff records.

Tests:
- Attestation forged/context/digest/cross-device/unknown/revoked/expired/missing/dispatch mismatch.
- v1.3 gap/duplicate/tampered/new-mission rollback/downgrade/cross-site/issuer/v1.2 replay.
- GPS UTC/offset EXIF/explicit XMP/naive/1-second boundary/conflict/partial/legacy/late-upload/site detail.
- Full Python with FD limit, Ruff, full Mypy, Dashboard test/lint/build, native SQLite/WAL and static
  OpenSSL CTest, PSDK logic/ABI negative gate, API/contract/hygiene/reference guard, KMZ checksums.

HIL or real-device assumptions:
- A-file import/map rendering and original M4D WideCamera JPEG metadata are evidenced. Pilot-exported
  KMZ comparison remains formally incomplete, but the operator accepted it as a residual risk that does
  not block FIELD-0b preparation. Real key provisioning, signed device upload, DPK/USB/frame-telemetry
  and rollback HIL are NOT_VERIFIED. No route execution, flight, firmware update, or device mutation is
  part of this build.

License/data implications:
- Static OpenSSL requires license/SBOM/third-party notice clearance before release.
- No private key, credential, customer data, raw field image, GPS record, or DPK is added to source.
  Existing untracked `download/` and `Testing/` are preserved and excluded from delivery.

Rollback:
- Source and writer activation are independent rollback units. Deploy dual-reader and durable
  high-water first, pass HIL, then enable the v1.3 writer. Never lower a recorded high-water or
  verified evidence to v1.2/unsigned state. No production mutation is performed in this task.

Execution:

1. Device attestation, CRITICAL lineage hardening, static signer, and live sync wiring — implemented.
2. Mission Contract v1.3 dual-reader/durable high-water with writer default retained at v1.2 — implemented.
3. Capture-time lineage, immutable job snapshot, freshness, nested site detail, Dashboard — implemented.
4. Full software verification and independent acceptance follow-up — complete (`Approved`).
5. FIELD-0a Pilot-export comparison remains an accepted residual risk; it does not close the goal.
6. FIELD-0b HIL readiness — current next milestone; FIELD-1/2 and FIELD-3 terrain work remain later.

## FIELD-0b next execution plan

Requirement IDs:
- REQ-EVT-101, REQ-MSN-101; INV-011, INV-021, INV-030, INV-040, INV-042, INV-052.

Owner module:
- `edge/psdk-app`, `edge/manifold-runtime`, `packages/mission-contracts`, `services/core`, and
  `tools/hil`/`scripts/manifold`.

Acceptance criteria:
- With no route execution or flight command, capture a reproducible HIL session manifest and prove the
  Manifold network identity, DJI app-framework state, USB bulk mapping, and capture-only DPK
  install/restart state.
- Only after that, prove 30 seconds of telemetry and 10 seconds of RGB reception. `recv` timing is
  diagnostic only; sensor-time p95 <= 50 ms remains blocked until a verified RGB sensor timestamp exists.
- Separately prove real-Manifold rejection for unsigned, expired, and rollback Mission Contracts before
  enabling the v1.3 Core writer.
- Separately prove a signed evidence registration/upload with an external 0600 Ed25519 key and matching
  Core public-key registry. This does not claim that the signature proves sensor truth.

Contracts affected:
- No new public contract is planned. Existing Evidence attestation, Mission Contract v1.3 dual reader,
  native activation handoff, and Core edge-sync contracts are exercised unchanged.

Reference assets:
- `docs/hil/HARDWARE_SESSION_PLAYBOOK.md` (step 8 before steps 3/4/7),
  `docs/hil/RAW_LOG_CONVENTIONS.md`, `edge/psdk-app/README.md`, and
  `scripts/manifold/probe_usb_bulk.sh`.

Adoption decisions:
- Preserve `field-0a-kmz-acceptance` as `in_progress`; the accepted Pilot-export residual is not a
  substitute for formal field acceptance.
- Start with a capture-only DPK. Native activation, perception, Core sync, and any writer activation
  stay disabled until their own prerequisites and evidence pass.
- Keys, credential headers, bearer tokens, CA bundles, and SPKI pins remain external files; no secret is
  copied into the repository, DPK, CMake cache, command line, or HIL log.

Files to change:
- `.ai/` state and handoff evidence only, unless the HIL session exposes a reproducible implementation
  defect. Device-side raw evidence is placed outside delivery scope under `hil_raw_logs/<session>/`.

Tests:
- Before device work: existing static OpenSSL/ABI/flight-boundary, SQLite/WAL, PSDK logic, and contract
  gates remain the software baseline.
- In HIL: read-only USB probe; official `dji_app_ctl` DPK install/restart/status evidence; raw telemetry,
  RGB, contract rejection, and signed-upload evidence. Each failed stage remains BLOCKED, not inferred.

HIL or real-device assumptions:
- At 2026-08-20T09:38:12Z, the host wired link was healthy at 1 Gbit/s but `172.30.1.33` was ARP
  `INCOMPLETE` and SSH returned `No route to host`; no device action can start until this path is restored.
- The first DPK build/install requires an operator-supplied DJI-issued App credential header and
  `user_app_id`. The signed Core-sync phase additionally requires an operator-provisioned external 0600
  Ed25519 key, registered public key, token file, CA bundle, and pins. The operator enters/provisions
  secret values directly; this plan never requests their contents.
- No `DjiWaypoint*Action`, route upload/start, gimbal command, firmware update, or flight is in scope.

License/data implications:
- A sync-enabled DPK remains release-blocked until static OpenSSL/libcurl third-party notices and SBOM
  evidence are produced. Raw image, telemetry, serial, location, and credential data remain untracked.

Rollback:
- A DPK installation is a distinct device change and is only attempted after reachability and credential
  prerequisites are recorded. Stop/uninstall is the device rollback path; it does not alter Core high-water
  or downgrade signed evidence. The v1.3 writer stays v1.2 by default throughout FIELD-0b.

---

# Historical plan

Requirement IDs:
- REQ-MSN-101, REQ-EVT-101, REQ-GEO-101
- SPATIAL-002, RISK-003, RISK-004, EDGE-001
- INV-010, INV-011, INV-020, INV-021, INV-040, INV-041, INV-050, INV-052

Owner module:
- `packages/mission-contracts` executable activation consumer (Manifold deployment is the remaining HIL gate)
- `services/core` event/evidence gate
- `services/bim-integration`
- `apps/dashboard` only for existing change integration and truthful readiness display

Acceptance criteria:
- A concrete Edge-facing consumer refuses malformed, unsigned, wrong-digest, wrong-schema,
  unknown/revoked/expired-key and out-of-TTL contracts, and persists an active digest only after
  successful `load_verified_contract` validation.
- CRITICAL confirmation refuses a RiskField reference unless a registered non-tombstoned artifact
  exists, its bytes can be read, JSON/model validation passes, geometry is non-empty, the RiskField
  covers the event time and references the event entities; the verified content digest is frozen in
  the transition evidence snapshot.
- mm-unit georeferenced IFC geometry returns meter-correct local offsets without applying the unit
  scale twice; the transformed output is then normalized from the declared `MapUnit`, or from the
  project length unit when `IfcProjectedCRS.MapUnit` is omitted. The same meter contract applies to
  `IfcRigidOperation`, which has no scale field. IFC-to-GeoTIFF uses the corrected mesh.
- Root Python and Dashboard gates exit 0. No hardware result is promoted without HIL evidence.

Contracts affected:
- Mission Contract v1.2 semantics are unchanged; a new activation receipt/runtime boundary consumes it.
- Event transition behavior becomes stricter for CRITICAL confirmation. Evidence uploads add
  `application/json` for typed machine evidence; EventBundle v1.2 wire fields stay unchanged.
- RiskField v1.0 wire schema stays unchanged; server-side semantic validation is strengthened.
- IFC public extraction return contract remains meters, with corrected implementation.

Reference assets:
- ADR-KSI-002, ADR-KSI-007, ADR-KSI-009, ADR-KSI-010
- `contracts/schemas/mission-contract.v1.2.json`, `risk-field.v1.json`,
  `event-bundle.v1.2.json`
- `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`, existing `psdk_tap` and timing capture tools
- Reference repositories are `REFERENCE_ONLY`; no runtime import or modification.

Adoption decisions:
- Reuse `load_verified_contract` as the only structure+signature+TTL gate; do not duplicate crypto.
- Keep tactical RiskField generation on Manifold. Core validates persisted evidence content and
  relationships, but does not recompute tactical geometry.
- Use ifcopenshell geometry output's measured meter units once; map conversion adds map offsets once.
- Treat `auto_local2global` output as map-unit coordinates. Resolve that unit from
  `IfcCoordinateOperation.TargetCRS.MapUnit`; when a present target CRS omits `MapUnit`, apply the
  IFC4.3 project-unit fallback. Preserve the existing half-set behavior when `TargetCRS` itself is
  absent because its output unit is not described by a CRS entity.
- Existing UI changes are preserved unless a gate proves a conflict.

Files to change:
- `.ai/goal.md`, `.ai/plan.md`, `.ai/task-state.md`, optional `.ai/handoff.md`
- Mission activation consumer under `packages/mission-contracts` and tests under `tests/contract`
- `services/core/src/ksi_core/events.py`, evidence/RiskField verifier and tests/OpenAPI
- `services/bim-integration/src/ksi_bim_integration/ifc_reference_model.py` and IFC tests
- risk/phase ledgers and remaining-work docs only after evidence is available

Tests:
- Focused contract tests for activation, event triage/evidence, RiskField and IFC conversion
- Explicit mm regressions for `IfcProjectedCRS` without `MapUnit` and `IfcRigidOperation`
- Edge native control-plane build/ctest where touched
- `uv run --locked pytest -q`
- `uv run --locked ruff check .`
- `uv run --locked mypy packages services tests tools`
- Dashboard Vitest (expected baseline 214), ESLint and production build
- `git diff --check`, reference-import guard and relevant hygiene checks

HIL or real-device assumptions:
- Prior repo evidence says M4D, RC Plus 2, Manifold 3 and PSDK entitlement exist, but current reachability
  must be rechecked. `.dpk` install/start, USB bulk and RC import are device writes explicitly within
  this task; secrets/OTP are not handled. Failure or absence remains BLOCKED/SPIKE_REQUIRED.

License/data implications:
- No customer/production data or new external asset is introduced.
- Existing PSDK/ifcopenshell licenses remain unchanged; no reference-repository runtime code is adopted.

Rollback:
- Remove the activation consumer and stricter confirmation wiring, revert the IFC extraction change,
  and restore prior docs/ledger states. No schema migration or production mutation is involved.

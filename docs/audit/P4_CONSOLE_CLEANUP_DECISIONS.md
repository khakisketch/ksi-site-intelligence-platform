# P4 Console Cleanup — Decision Inventory and Scope Contract

Base: `main fb3310a` (clean). Plan: `docs/superpowers/plans/2026-10-08-operations-console-cleanup-p4.md` (SHA `c7fd91df`, Human-approved 2026-10-08).
Docs-only task — no app/backend edits. This document is the design run's (Task 2) scope contract:
every row is actionable, every RETIRE/REPOINT row cites evidence.

Conventions: **KEEP** = survives against the platform inventory as-is (minor call-level fixes noted).
**RETIRE** = delete route/proxy/module/component (or its managed-era calls); retired URLs 404/redirect deliberately.
**REPOINT** = screen/shell survives but one or more calls/links must move to the named platform replacement or typed empty state.

## 1. Platform profile mounted-route inventory (authoritative)

Built the platform app **in-process** (no server, no network), reusing the established harness:

- Base profile: `tests/contract/test_platform_core_assembly.py` `_assemble` pattern
  (`assemble_platform_app` with defaults + stub auth registry/storage).
- Full profile: `tests/contract/test_platform_core_http_integration.py` `_PlatformFlowContext`
  with `with_spatial_data=True` (adds `external_result_workflow` + `external_analysis_local_graph` + `spatial_data`
  participants — the same participants the Console's surviving external-result/analysis/spatial surfaces need).

Route enumeration unfolds `_IncludedRouter` wrappers (`original_router`), same pattern as
`test_api_contract_sync._walk_routes` / `test_platform_core_assembly._walk_routes`;
`app.routes` alone hides conditionally included routers.

Exact commands (from repo root, read-only):

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/opencode/p4_routes.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/opencode/p4_routes_full.py
```

Result: **base 64 routes; full 128 routes.** The full list below is the KEEP/RETIRE authority —
any Console call to a path prefix absent here is platform-unmounted.

```text
GET /health
GET /metrics
GET /ready
GET /v1/auth/whoami
GET /v1/external-decisions/pending
GET /v1/external-relative-volume-reports/{report_ref}
POST /v1/external-relative-volume-reports/{report_ref}/reviews
POST /v1/external-relative-volume-reports/{report_ref}/shares
POST /v1/external-reobservation-proposals
POST /v1/external-reobservation-proposals/approve
GET /v1/external-reobservation-proposals/{proposal_ref}
GET /v1/external-result-reviews/{review_ref}
GET /v1/external-single-volume-reports/{report_ref}
POST /v1/external-single-volume-reports/{report_ref}/reviews
POST /v1/external-single-volume-reports/{report_ref}/shares
GET /v1/internal/analysis-jobs
GET /v1/internal/analysis-jobs/{analysis_id}/input
POST /v1/internal/analysis-jobs/{analysis_id}:failure
POST /v1/internal/analysis-jobs/{analysis_id}:lease
POST /v1/internal/analysis-jobs/{analysis_id}:renew
POST /v1/internal/analysis-jobs/{analysis_id}:report
GET /v1/internal/external-validation/evidence-validations
POST /v1/internal/external-validation/evidence-validations/{validation_id}/heartbeat
POST /v1/internal/external-validation/evidence-validations/{validation_id}/incomplete-failure
GET /v1/internal/external-validation/evidence-validations/{validation_id}/input
POST /v1/internal/external-validation/evidence-validations/{validation_id}/lease
POST /v1/internal/external-validation/evidence-validations/{validation_id}/measurement
GET /v1/internal/external-validation/inspections
POST /v1/internal/external-validation/inspections/{request_id}/display-artifacts/upload-grants
POST /v1/internal/external-validation/inspections/{request_id}/display-artifacts/{display_id}/seal
POST /v1/internal/external-validation/inspections/{request_id}/heartbeat
POST /v1/internal/external-validation/inspections/{request_id}/incomplete-failure
GET /v1/internal/external-validation/inspections/{request_id}/input
POST /v1/internal/external-validation/inspections/{request_id}/lease
POST /v1/internal/external-validation/inspections/{request_id}/report
GET /v1/internal/external-validation/relative-volumes
POST /v1/internal/external-validation/relative-volumes/{request_ref}/heartbeat
POST /v1/internal/external-validation/relative-volumes/{request_ref}/incomplete-failure
GET /v1/internal/external-validation/relative-volumes/{request_ref}/input
POST /v1/internal/external-validation/relative-volumes/{request_ref}/lease
POST /v1/internal/external-validation/relative-volumes/{request_ref}/report
GET /v1/internal/external-validation/single-volumes
POST /v1/internal/external-validation/single-volumes/{request_ref}/heartbeat
POST /v1/internal/external-validation/single-volumes/{request_ref}/incomplete-failure
GET /v1/internal/external-validation/single-volumes/{request_ref}/input
POST /v1/internal/external-validation/single-volumes/{request_ref}/lease
POST /v1/internal/external-validation/single-volumes/{request_ref}/report
GET /v1/internal/spatial-data-jobs
POST /v1/internal/spatial-data-jobs/{job_id}/complete
POST /v1/internal/spatial-data-jobs/{job_id}/failure
GET /v1/internal/spatial-data-jobs/{job_id}/input
POST /v1/internal/spatial-data-jobs/{job_id}/lease
POST /v1/internal/spatial-data-jobs/{job_id}/output-upload
POST /v1/internal/spatial-data-jobs/{job_id}/renew
GET /v1/observation-work-order-operations
GET /v1/observation-work-orders
GET /v1/observation-work-orders/{work_order_id}
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-context
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v2
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/display-artifacts/{sanitized_display_ref}/download
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/seal
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/upload-grant
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/inspection
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/seal
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/upload-grants
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions/pair
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions/single
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions/single-volume
GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions/{decision_id}
GET /v1/observation-work-orders/{work_order_id}/operations
POST /v1/observation-work-orders/{work_order_id}/operations/assignment
POST /v1/observation-work-orders/{work_order_id}/operations/close
PUT /v1/observation-work-orders/{work_order_id}/operations/due-date
POST /v1/observation-work-orders/{work_order_id}/operations/reopen
GET /v1/observation-work-orders/{work_order_id}/relative-volume-requests
POST /v1/observation-work-orders/{work_order_id}/relative-volume-requests
GET /v1/observation-work-orders/{work_order_id}/relative-volume-requests/{request_ref}
GET /v1/observation-work-orders/{work_order_id}/reobservation-drafts
GET /v1/observation-work-orders/{work_order_id}/single-volume-requests
POST /v1/observation-work-orders/{work_order_id}/single-volume-requests
GET /v1/observation-work-orders/{work_order_id}/single-volume-requests/{request_ref}
GET /v1/organization-work-roster
PUT /v1/organization-work-roster/{principal_id}
GET /v1/sites
POST /v1/sites
GET /v1/sites/{site_id}
GET /v1/sites/{site_id}/analyses
GET /v1/sites/{site_id}/analyses/{analysis_id}
GET /v1/sites/{site_id}/analyses/{analysis_id}/evidence
GET /v1/sites/{site_id}/analyses/{analysis_id}/result
GET /v1/sites/{site_id}/analysis-observations
PUT /v1/sites/{site_id}/aoi
GET /v1/sites/{site_id}/external-relative-volume-reports
GET /v1/sites/{site_id}/external-volume-reports
PUT /v1/sites/{site_id}/model-age-policy
GET /v1/sites/{site_id}/observation-schedules
GET /v1/sites/{site_id}/observation-work-orders
POST /v1/sites/{site_id}/observation-work-orders
GET /v1/sites/{site_id}/observations/{report_ref}
POST /v1/sites/{site_id}/transitions
GET /v1/sites/{site_id}/work-areas
POST /v1/sites/{site_id}/work-areas
POST /v1/sites/{site_id}/work-areas/{work_area_id}/analyses
POST /v1/sites/{site_id}/work-areas/{work_area_id}/archive
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets/{asset_ref}
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests
POST /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests/{request_ref}
POST /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests/{request_id}/cancel
GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests/{request_id}/file
GET /v1/work-inbox
POST /v1/work-inbox/{notification_ref}/read
GET /v2/sites/{site_id}/analyses
GET /v2/sites/{site_id}/analyses/{analysis_id}
GET /v2/sites/{site_id}/analyses/{analysis_id}/coverage
GET /v2/sites/{site_id}/analyses/{analysis_id}/evidence
GET /v2/sites/{site_id}/analyses/{analysis_id}/review-target
GET /v2/sites/{site_id}/analyses/{analysis_id}/reviews
POST /v2/sites/{site_id}/analyses/{analysis_id}/reviews
POST /v2/sites/{site_id}/work-areas/{work_area_id}/analyses
```

Verified ABSENT from all 128 (each checked against the dump above — no matching prefix):
`/v1/missions*`, `/v1/events*`, `/v1/checkpoint-validations*`, `/v1/copilot*`,
`/v1/processing-jobs*`, `/v1/comparison*` (incl. `/v1/comparison-policy`),
`/v1/missions/plans`, `/v1/sites/*/processing-jobs`, `/v1/sites/*/design-*`,
`/v1/sites/*/report-exports`, `/v1/sites/*/civil-readiness`, `/v1/sites/*/spatial-model`,
`/v1/sites/*/briefings*`, `/v1/site-briefings*`, `/v1/sites/*/workspace`,
`/v1/equipment-support*`, `/v1/sites/*/equipment-states`, `/v1/sites/*/risk-assessment`,
`/v1/observation-work-orders/*/approve`, `POST .../reobservation-drafts`,
`/v1/reobservation-drafts/*/approve`, `/v1/processing-resource-policies`.
Present and relevant: `/v1/internal/external-validation*` (worker lanes — Console never calls these directly;
`checkpoint-validations` Console proxy has no platform counterpart).

## 2. Console API-usage inventory (function → path)

Source: `apps/dashboard/src/lib/core-api/**` (template + plain-string `/v1|/v2` extraction) and
`apps/dashboard/src/app/api/**` proxy→lib imports (every proxy delegates to a lib module; mapping table
in §4). Inline browser fetches hit Console `/api/*` proxies, never the platform directly
(except presigned storage PUTs) — so proxy disposition follows lib-module disposition.

| Lib module | Calls (platform paths) | Mounted? |
|---|---|---|
| `acquisition-connectivity.ts` | `/v1/sites/{id}/acquisition-profile`, `.../acquisition-readiness` | NO |
| `acquisition-coordination.ts` | `/v1/observation-work-orders/{id}/acquisition-progress` | NO |
| `analysis.ts` | `/v1/sites/{id}/analysis-observations`, `/v2/sites/{id}/analyses*` (list/get/evidence/create) | YES |
| `auth.ts` (`verifyToken`) | `/v1/auth/whoami` | YES |
| `checkpoint-validations.ts` | `/v1/checkpoint-validations*`, `/v1/processing-jobs/{id}/.../checkpoint-validations` | NO |
| `civil-readiness.ts` | `/v1/sites/{id}/civil-readiness` | NO |
| `comparison.ts` | `/v1/comparison-requests/{id}`, `/v1/missions/{id}/{comparison-preflight,comparison-requests}`, `/v1/sites/{id}/processing-jobs`, `/v1/comparison-policy` | NO (all) |
| `copilot.ts` | `/v1/copilot/query` | NO |
| `copilot-conversations.ts` | `/v1/copilot/conversations*`, `/v1/sites/{id}/copilot/conversations` | NO |
| `coverage.ts` | pure summarizer, no fetch | YES (n/a) |
| `design.ts` | `/v1/missions/{id}/design-conformance*`, `/v1/sites/{id}/{design-progress,design-surfaces*}` | NO (all) |
| `events.ts` | `/v1/events`, `/v1/events/{key}/{evidence,transitions}` | NO |
| `external-decisions.ts` | `/v1/external-decisions/pending` | YES |
| `external-reconstruction.ts` | `/v1/observation-work-orders/{id}/external-reconstruction-{context,submissions...}` | YES |
| `external-result-workflow.ts` | `/v1/external-{relative-volume-reports,single-volume-reports,result-reviews,reobservation-proposals}*`, `/v1/sites/{id}/{external-relative-volume-reports,external-volume-reports,observations/{ref}}`, `.../relative-volume-requests`, `.../single-volume-requests` | YES |
| `mission-plans.ts` | `/v1/missions/plans` | NO |
| `missions.ts` | `/v1/missions`, `/v1/missions/{id}/{coverage-report*,execution*,kmz}` | NO (all) |
| `observation-work-orders.ts` | list/get/operations* + `POST sites/{id}/observation-work-orders` YES; BUT `.../approve`, `POST .../reobservation-drafts`, `/v1/reobservation-drafts/{id}/approve` | PARTIAL (3 fns unmounted) |
| `phase34.ts` | `/v1/missions/{id}/{defect-candidates,change-detection,volume-changes}`, `/v1/missions/{id}/source-media/{media}/view`, `/v1/processing-jobs/{id}*`, `/v1/sites/{id}/{equipment-states,risk-assessment}`, `/v1/equipment-support*` | NO (all) |
| `phase34-labels.ts` | pure labels, no fetch | YES (n/a) |
| `processing-jobs.ts` | `/v1/missions/{id}/processing-jobs` | NO |
| `processing-resource-policies.ts` + `lib/processing-resource-policy.ts` | `/v1/processing-resource-policies` | NO |
| `region-extraction.ts` | `/v1/missions/{id}/region-extraction*` | NO |
| `report-exports.ts` | `/v1/sites/{id}/report-exports` | NO |
| `site-progress.ts` | pure derivation, no fetch | YES (n/a) |
| `site-workspace.ts` | `/v1/site-briefings/latest`, `/v1/sites/{id}/briefings/{latest,refresh}`, `/v1/sites/{id}/workspace` | NO (all) |
| `sites.ts` | `GET/POST /v1/sites*`, `PUT aoi`, `PUT model-age-policy`, `POST transitions` YES; BUT `/v1/sites/{id}/spatial-model` | PARTIAL (1 fn unmounted) |
| `source-media.ts` | `/v1/missions/{id}/source-media{,/seal}` | NO |
| `spatial-assets.ts` | `/v1/sites/{id}/work-areas/{area}/spatial-assets*` | YES |
| `work-collaboration.ts` | `.../shares`, `/v1/organization-work-roster*`, `/v1/work-inbox*` | YES |
| `workAreas.ts` | `/v1/sites/{id}/work-areas*` | YES |
| `labels.ts`, `permissions.ts`, `missionSiteGate.ts`, `siteAutonomyGate.ts`, `triage.ts`, `types.ts`, `surveyEntryPreset.ts`, `external-report-display.ts` | pure/no platform fetch | YES (n/a) |
| `client.ts`, `session.ts`, `session-cookie.ts`, `env.ts`, `origin-guard.ts`, `route-handler-util.ts`, `cached.ts` (wrapper) | plumbing | n/a (follow callers) |
| `lib/design-conformance.ts` | managed-era design helpers (imported by `field/[missionId]`, `missions/[missionId]`, `DesignSurfacePanel`, map overlays, `SourceUploadPanel`) | NO (callers retire) |
| `lib/home-evidence.ts` | `core-api/events` (`getEvent`, `getEvidenceViewUrl`) | NO |
| `lib/comparison-failure.ts`, `lib/reports/coverage-evidence.ts` | comparison/coverage formatting for retired reports | NO (callers retire; `coverage.ts` itself stays) |

## 3. Disposition tables (scope contract)

### 3a. Navigation (`src/components/nav/nav-items.ts`; palette in `components/console/palette-source.ts` derives from `DESKTOP_NAV_ITEMS` — inherits)

| Nav | href | Disposition | Evidence / replacement |
|---|---|---|---|
| 홈 | `/` | REPOINT | Shell KEEP; drop `listAllEventsCached` (§1: no `/v1/events*`) and `listLatestSiteBriefings` (§1: no `/v1/*briefings*`); keep sites + `listExternalPendingDecisions` (`GET /v1/external-decisions/pending` mounted) |
| 현장 | `/sites` | KEEP | Strip per-site mission/event badges (`app/sites/page.tsx:145-188` calls `listMissions`/`listAllEvents` — both unmounted); site CRUD/links use mounted reads |
| 작업 | `/field` | REPOINT | Work-order-centric surface: keep `work-orders`, `inbox`, `team`; retire `[missionId]` + acquisition/copilot cards (§3b) |
| 확인 항목 | `/events` | RETIRE | `event_store` retired-guarded → routes unmountable on both paths (plan §Discovery + §1 absence of `/v1/events*`); no surviving review surface — external-result reviews live under site observations/work orders |
| 비행 임무 이력 | `/missions` | RETIRE | §1: no `/v1/missions*`; source-media prefix nuance resolved — source-media routes also absent, so no surviving mission call |
| 장비 연결·지원 상태 | `/settings` | RETIRE | Sole data `listEquipmentSupport` (`phase34.ts:139` → `/v1/equipment-support`, §1 absent); `/coming-soon/fleet` keeps the support-scope note |
| Dock·Edge 지원 범위 | `/coming-soon/fleet` | KEEP | Static placeholder (`coming-soon/[section]/page.tsx` imports only `NAV_ITEMS` + `EmptyState` — no backend call) |
| 더보기 (mobile) | `/more` | REPOINT | Renders `NAV_ITEMS` — inherits above automatically; no own fetch |

### 3b. Route dirs (`src/app/`)

| Route dir | Disposition | Evidence / replacement |
|---|---|---|
| `page.tsx` (home) + `HomeAttentionCarousel/TopUnattendedHeadline/HomeRecentUpdates/HomeSituationList/PortfolioTable/ProcessingCard` | REPOINT | `app/page.tsx:6,34-35` + `lib/home-evidence.ts:5` (events, §1 absent) and `site-workspace` briefings (§1 absent) → remove/typed-empty; keep `listSitesCached`, `listExternalPendingDecisions`, `resolveSiteOperatorNextAction` |
| `portfolio.ts` | NOTE (file, not a route dir) | KEEP as type module; `lastMissionAt`/`unattendedCount` fields lose feeders (missions/events unmounted) → typed-null/empty, no invented values (INV-040 per file header) |
| `login/` | KEEP | `verifyToken` → `/v1/auth/whoami` mounted; OIDC/next-auth untouched |
| `sites/`, `sites/new/` | KEEP | `GET/POST /v1/sites*` mounted |
| `sites/[siteId]/page.tsx` (workspace home) | REPOINT | Imports `comparison` (:14), `events` (:23), `missions` (:24), `phase34.getVolumeChanges` (:27) — all §1 absent — plus links to `/missions/*` (:296); keep platform sections (observations, work orders, analyses, assets, external results) |
| `sites/[siteId]/observations/**` (list/new/`[reportRef]`) | KEEP | `external-reconstruction` + `external-result-workflow` paths all §1 mounted |
| `sites/[siteId]/analysis/` | KEEP | `analysis.ts` → `/v1/.../analysis-observations` + `/v2/.../analyses*`, all mounted |
| `sites/[siteId]/spatial-assets/`, `work-areas/` | KEEP | `spatial-assets.ts`, `workAreas.ts` paths mounted |
| `sites/[siteId]/{SiteHeader,SiteAoiEditor,SiteTransitionActions,WorkAreaPanel,AnalysisRequestPanel}` | KEEP | `PUT aoi`, `POST transitions`, work-area/analysis reads mounted |
| `sites/[siteId]/ai/` | RETIRE | `SiteCopilotChat` → `copilot-conversations` (`/v1/copilot*`, §1 absent) |
| `sites/[siteId]/design/` + `DesignSurfacePanel` | RETIRE | `design.ts` paths (§1 absent) + `lib/design-conformance.ts` |
| `sites/[siteId]/changes/` + `ChangeRegionExplorer` | REPOINT | Managed-era change/region calls (`phase34` change-detection, `region-extraction`, `comparison` — §1 absent) → repoint to mounted analysis (`/v2/.../analyses*`) + external-result reads, else typed empty state; no KEEP screen may call unmounted routes |
| `sites/[siteId]/progress/` | REPOINT | `getSiteWorkspace` (§1 absent) + `phase34` calls → repoint to mounted `GET sites/work-areas/spatial-assets` + `site-progress.ts` (pure, KEEP); typed empty where no replacement |
| `sites/[siteId]/report/` | REPOINT | `design` (:5), `phase34` (:6), `site-workspace` (:13), `missions` coverage (:24) — §1 absent — strip; keep `ExternalSiteResultSummary` + `OrthophotoOverlay` (mounted external-result/display-artifact reads) |
| `sites/[siteId]/surveys/new/` + `SurveyWizard` | RETIRE | Mission-planning era (`missionSiteGate`, `app/missions/format`, `KmzDownloadButton` → retired `/api/missions` proxy); no platform mission-planning surface (§1) |
| `field/`, `field/page.tsx` | REPOINT | `AcquisitionReadinessCard` + `getAcquisitionReadiness` (`acquisition-connectivity`, §1 absent), `AcquisitionProgressCard` + `getAcquisitionProgress` (`acquisition-coordination`, §1 absent), `CopilotPanel` (`/v1/copilot*` absent), `getSiteWorkspace`/`getLatestSiteBriefing` (§1 absent) → remove; keep `WorkQueueOperationsNotices`, external-workflow panels (mounted) |
| `field/new/` | KEEP | Site picker only (`listSitesCached` mounted; links to KEEP `observations/new`) |
| `field/inbox/`, `field/team/` | KEEP | `GET /v1/work-inbox`, `GET/PUT /v1/organization-work-roster*` mounted |
| `field/work-orders/`, `field/work-orders/[workOrderId]/` | KEEP (screen) + strip 3 calls | `observation-work-orders`/`external-reconstruction`/`external-result-workflow`/`sites`/`workAreas` reads mounted; REMOVE `getAcquisitionProgress`/`getAcquisitionReadiness` (§1 absent) and `getLatestSiteBriefing`/`getSiteWorkspace` (`site-workspace.ts`, §1 absent) |
| `field/[missionId]/` + `AcquisitionProgressCard/CopilotPanel/OperationsWorkHeader/actions.ts` | RETIRE | Mission-execution era (`missions`, `design-conformance`, acquisition libs — §1 absent) |
| `field/{ExternalEvidencePanel,ExternalHeaderRecognition,ExternalReconstructionPanel,ExternalResultWorkflowPanel,ExternalSanitizedOrthophoto*,WorkOrderActionPanel,WorkOrderOperationsPanel}` | KEEP | Mounted external-reconstruction/workflow/inbox reads |
| `missions/`, `missions/[missionId]/` + `format.ts`, `mission-labels.ts` (only if unused after) | RETIRE | §1: no `/v1/missions*` (incl. source-media prefix) |
| `events/`, `events/[eventKey]/` + `EventDetailPanel/EventRowLink/AckElapsedFact/DwellBar/FilterSelect/EventActions/EvidencePanel` | RETIRE | Flag resolution §5a |
| `assets/`, `assets/DefectOverlay.tsx` | RETIRE | `assets/page.tsx:5-6` (`listMissions`, `phase34.listDefectCandidates` — §1 absent); defect review's surviving home is mounted `external-result-reviews`, not this screen |
| `reports/` | RETIRE | `reports/page.tsx:4,6` (`comparison`, `missions` — §1 absent); `VolumeChangeSummary`, `ReportExportControls` (`report-exports`, §1 absent) retire with it |
| `world/`, `world/SitePlanView.tsx` | RETIRE | `world/page.tsx:6,15` (`phase34.listEquipmentStates`, `comparison.listSiteProcessingJobs` — §1 absent) |
| `hil/pilot-bridge/` | RETIRE | Managed-era `PilotBridgeProbe`; no platform flight/pilot surface (§1: no `*flight*`, `*edge*`, `*pilot*`) |
| `settings/` | RETIRE | See nav row; `phase34.listEquipmentSupport` §1 absent |
| `more/` | REPOINT | Inherits nav dispositions |
| `coming-soon/[section]/` | KEEP | No backend call (static) |

### 3c. API proxies (`src/app/api/` — each delegates to the named lib module)

| Proxy | ← lib | Disposition | Evidence |
|---|---|---|---|
| `auth/`, `health/` | session/next-auth | KEEP | No platform-shape change |
| `sites/`, `sites/[siteId]/aoi`, `.../transitions`, `.../work-areas/**`, `.../analyses**`, `.../analysis-observations`, `.../observation-work-orders`, `.../observations/[reportRef]`, `.../external-relative-volume-reports`, `.../external-volume-reports` | `sites`, `workAreas`, `analysis`, `observation-work-orders`, `external-result-workflow` | KEEP | All upstream paths §1 mounted |
| `observation-work-orders/**` (excl. none — all under mounted paths) | `observation-work-orders`, `external-reconstruction`, `external-result-workflow` | KEEP | Upstream paths §1 mounted (approve/draft-approve fns have no proxy — lib-only, §3d) |
| `organization-work-roster/**`, `work-inbox/**` | `work-collaboration` | KEEP | §1 mounted |
| `external-relative-volume-reports/**`, `external-single-volume-reports/**`, `external-result-reviews/**`, `external-reobservation-proposals/**` | `external-result-workflow`, `work-collaboration` (shares) | KEEP | §1 mounted |
| `checkpoint-validations/**`, `processing-jobs/**/checkpoint-validations` | `checkpoint-validations` | RETIRE | §5b |
| `comparison-requests/**`, `missions/**/comparison-*`, `sites/[siteId]/processing-jobs` | `comparison` | RETIRE | §1: no `/v1/comparison*`, no `/v1/sites/*/processing-jobs` |
| `copilot/**`, `sites/[siteId]/copilot` | `copilot-conversations` | RETIRE | §1: no `/v1/copilot*` |
| `events/**` (no top-level `route.ts` — `[eventKey]/{evidence,transitions}` only) | `events` | RETIRE | §5a |
| `mission-plans/` | `mission-plans` | RETIRE | §1: no `/v1/missions/plans` |
| `missions/**` (execution-transitions, kmz, processing-jobs, source-media*) | `missions`, `processing-jobs`, `source-media`, `comparison`, `design` | RETIRE | §1: no `/v1/missions*`; §5c |
| `processing-jobs/**` | `phase34`, `checkpoint-validations` | RETIRE | §1: no `/v1/processing-jobs*` |
| `sites/[siteId]/{design-progress,design-surfaces/**}` | `design` | RETIRE | §1: no `/v1/sites/*/design-*`, no `/v1/missions/*/design-conformance*` |
| `sites/[siteId]/report-exports` | `report-exports` | RETIRE | §1: no `/v1/sites/*/report-exports` |

### 3d. Lib modules (`src/lib/core-api/` + named `src/lib/` helpers)

| Module | Disposition | Evidence |
|---|---|---|
| `analysis.ts`, `auth.ts`, `external-decisions.ts`, `external-reconstruction.ts`, `external-result-workflow.ts`, `spatial-assets.ts`, `work-collaboration.ts`, `workAreas.ts`, `observation-work-orders.ts` (minus 3 fns), `sites.ts` (minus `spatial-model` fn) | KEEP | §2 YES rows |
| `coverage.ts`, `phase34-labels.ts`, `site-progress.ts`, `labels.ts`, `permissions.ts`, `missionSiteGate.ts`, `siteAutonomyGate.ts`, `triage.ts`, `types.ts`, `surveyEntryPreset.ts`, `external-report-display.ts` | KEEP (pure — no fetch) | §2 n/a rows; stay only while a KEEP screen imports them |
| `client.ts`, `session.ts`, `session-cookie.ts`, `env.ts`, `origin-guard.ts`, `route-handler-util.ts`, `cached.ts` (minus `listAllEventsCached` + mission list fns) | KEEP (plumbing) | Follow callers; cached event/mission helpers retire with `events`/`missions` |
| `acquisition-connectivity.ts`, `acquisition-coordination.ts`, `checkpoint-validations.ts`, `civil-readiness.ts`, `comparison.ts`, `copilot.ts`, `copilot-conversations.ts`, `design.ts`, `events.ts`, `mission-plans.ts`, `missions.ts`, `phase34.ts`, `processing-jobs.ts`, `processing-resource-policies.ts`, `region-extraction.ts`, `report-exports.ts`, `site-workspace.ts`, `source-media.ts` | RETIRE | §2 NO rows — every path each calls is §1 absent |
| `observation-work-orders.ts` approve + `POST reobservation-drafts` + `approveReobservationDraft` fns; `sites.ts` spatial-model fn | RETIRE (fns only) | Restricted-router test pattern (`test_platform_core_assembly.py::test_restricted_router_omits_only_managed_mutation_routes`) + §1 absence |
| `lib/design-conformance.ts`, `lib/processing-resource-policy.ts`, `lib/civil-readiness.ts`, `lib/home-evidence.ts`, `lib/comparison-failure.ts`, `lib/reports/coverage-evidence.ts` (only if unused after) | RETIRE | Importers all retire (§2 last row; `home-evidence` → `events`) |
| `lib/home-external-decision.ts`, `lib/operator-next-action.ts`, `lib/home-operations.ts`, `lib/work-areas.ts`(root), `lib/external-*.ts` (upload/submission/references/display/sanitized) | KEEP | Feed KEEP screens via mounted paths |

### 3e. Components with managed-era references

| Component | Disposition | Evidence / replacement |
|---|---|---|
| `design/DesignConformancePanel.tsx`, `missions/ComparisonSubmitPanel.tsx`, `missions/SourceUploadPanel.tsx`, `missions/KmzDownloadButton.tsx`, `missions/CoverageReportSection.tsx`, `reports/ReportExportControls.tsx`, `reports/VolumeChangeSummary.tsx`, `map/DiffHeatmapOverlay*.tsx`, `map/ChangeRegionMapInner.tsx` (only if unused after) | RETIRE | Backed by retired proxies/modules (§3c/§3d); `CoverageReportSection` consumes `missions.getCoverageReport` (§1 absent) |
| `map/OrthophotoOverlay.tsx`, `map/AoiPolygonMap.tsx`, `site/SiteAreaPicker.tsx`, `site/SiteProgressBar.tsx`, `external-results/*`, `wizard/*`, `ui/*`, `responsive/*`, `console/CommandPalette.tsx` + `palette-source.ts` + `palette-items.ts`, `auth/*` | KEEP | Mounted reads / pure / palette inherits nav |
| `site/ReobsSuggestions.tsx`, `site/ZoneVolumeBars.tsx` | REPOINT | `phase34` formatting/imports only (`phase34-labels` is pure KEEP) → re-feed from mounted `GET .../reobservation-drafts` + `POST .../external-reobservation-proposals` / external-result reads, else typed empty |
| `field/AcquisitionProgressCard.tsx`, `field/AcquisitionReadinessCard.tsx`, `field/CopilotPanel.tsx`, `field/PilotBridgeProbe.tsx`, `field/copilot-citation.ts`, `field/acquisition-*.ts`, `field/resolve-session.ts` (only if acquisition-bound) | RETIRE | `acquisition-*`/`copilot*` paths §1 absent |
| `field/WorkOrderActionPanel.tsx`, `field/WorkOrderOperationsPanel.tsx`, `field/OperationsWorkHeader.tsx`, `field/work-queue.ts`, `field/work-order-stage.ts`, `field/external-work-order-stage.ts` | REPOINT (KEEP shell) | Strip acquisition/site-workspace calls (§3b); operations/drafts/external calls mounted |
| `HomeAttentionCarousel.tsx`, `HomeRecentUpdates.tsx`, `HomeSituationList.tsx`, `PortfolioTable.tsx`, `TopUnattendedHeadline.tsx`, `ProcessingCard.tsx` | REPOINT | §3b home row; `TopUnattendedHeadline` (event-count) → repoint to `GET /v1/work-inbox` pending items or typed empty |
| `assets/DefectOverlay.tsx`, `app/sites/[siteId]/changes/ChangeRegionExplorer.tsx` (managed parts), `app/sites/[siteId]/design/DesignSurfacePanel.tsx` | RETIRE / REPOINT per §3b | As the owning screen |

## 4. Console endpoint-call map (function → paths, sample anchors)

Proxies never call the platform directly — each `app/api/**/route.ts` imports its lib module
(full proxy→lib map verified by import grep; representative anchors):

- `api/sites/route.ts` → `core-api/sites` (`registerSite` → `POST /v1/sites` mounted).
- `api/missions/[missionId]/execution-transitions/route.ts` → `core-api/missions` (unmounted) → RETIRE.
- `api/missions/[missionId]/{comparison-requests,comparison-preflight,processing-jobs,source-media*,kmz,design-conformance*}` → `comparison`/`processing-jobs`/`source-media`/`missions`/`design` (all unmounted) → RETIRE.
- `api/processing-jobs/[jobId]/**` → `phase34`/`checkpoint-validations` (unmounted) → RETIRE.
- `api/{checkpoint-validations,comparison-requests,copilot,events,mission-plans}/**` →同名 retired libs → RETIRE.
- `api/sites/[siteId]/{copilot,design-progress,design-surfaces,processing-jobs,report-exports}` → retired libs → RETIRE.
- `api/sites/[siteId]/{analyses,analysis-observations,aoi,transitions,work-areas,observations,external-*,observation-work-orders}` → mounted libs → KEEP.
- `api/observation-work-orders/**`, `api/{organization-work-roster,work-inbox,external-relative-volume-reports,external-single-volume-reports,external-result-reviews,external-reobservation-proposals}/**` → mounted libs → KEEP.
- Browser inline fetches (`/api/mission-plans`, `/api/missions/*`, `/api/events/*`, `/api/checkpoint-validations/*`, `/api/comparison-requests/*`, `/api/copilot/*`, `/api/processing-jobs/*`) all target RETIRE proxies → their call sites retire/repoint with the owning screen. Inline fetches to KEEP proxies (`/api/sites*`, `/api/observation-work-orders*`, `/api/work-inbox*`, `/api/organization-work-roster*`, `/api/external-*`, `/api/auth/refresh`) stay.

## 5. Flag resolutions (explicit)

- **(a) `events` (retired-guarded → RETIRE).** Console `/events`, `/events/[eventKey]`, `api/events/**`, `lib/core-api/events.ts`,
  `cached.listAllEventsCached`, `lib/home-evidence.ts`, home/→sites event badges all RETIRE. Evidence: §1 has zero
  `/v1/events*` among 128 routes (guarded-unmountable per plan §Discovery). No surviving review surface exists —
  review workflows live on mounted `external-result-reviews`/`use-decisions`/work-inbox, reached via site/work-order screens.
- **(b) `checkpoint-validations` (platform-unmounted → Console RETIRE with note).** Core retains the transitional
  `ksi_core/checkpoint_validations.py` module, but the platform profile mounts no `/v1/checkpoint-validations*`;
  external-validation ingestion uses mounted `/v1/internal/external-validation*` worker lanes (Console never calls
  worker lanes directly). So `api/checkpoint-validations/**`, `api/processing-jobs/**/checkpoint-validations`,
  `lib/core-api/checkpoint-validations.ts` RETIRE with this note — not "Core deleted it".
- **(c) `missions` / source-media / phase34 (per-endpoint resolution).** §1 has zero `/v1/missions*` — the prefix
  nuance is resolved: source-media routes live under the same unmounted prefix, so `source-media.ts`,
  `missions.ts`, and ALL of `phase34.ts`'s `/v1/missions/{id}/{defect-candidates,change-detection,volume-changes}`
  (+ `source-media/{media}/view`) RETIRE. Per-endpoint replacements for KEEP screens:
  - volume/change questions → mounted analysis (`GET /v2/sites/{id}/analyses*`, `GET .../analysis-observations`) and
    external-result reads (`GET /v1/sites/{id}/{external-relative-volume-reports,external-volume-reports,observations/{ref}}`,
    `GET .../relative-volume-requests`, `GET .../single-volume-requests`);
  - defect-candidate overlay (`assets/`) → no platform equivalent → RETIRE screen (defect review via mounted
    `external-result-reviews`/`use-decisions` on work-order screens);
  - `phase34`'s `/v1/processing-jobs/{id}*`, `/v1/sites/{id}/{equipment-states,risk-assessment}`,
    `/v1/equipment-support*` → no replacement → RETIRE callers (`world`, `settings`, reports);
  - `observation-work-orders.ts` approve/reobservation-draft-POST fns → no replacement (restricted router omits them) → RETIRE fns;
    surviving draft visibility is mounted `GET .../reobservation-drafts` + `POST .../external-reobservation-proposals`.
- **(d) Minor inventory facts.** `src/app/portfolio.ts` is a file, not a route dir (type module — §3b NOTE row).
  `assets/**` = `assets/page.tsx` + `DefectOverlay.tsx` (RETIRE, §3b). `field/**` has NO `missions/` subdir;
  its subdirs are `[missionId]` (RETIRE), `inbox` (KEEP), `new` (KEEP), `team` (KEEP), `work-orders` (KEEP) —
  plus co-located `*.ts` helpers and `*.tsx` panels disposed per §3e.

## 6. Design-run handoff (Task 2 scope)

1. Apply every table row; no KEEP/REPOINT screen may call a §1-absent route when done
   (verify by re-grepping `/v1/` in `lib/core-api` + proxy imports against §1).
2. Retired URLs (`/missions*`, `/events*`, `/assets*`, `/reports`, `/world*`, `/hil/*`, `/settings`,
   `/field/[missionId]`, site `ai/` + `design/`, retired `/api/*`) 404 or redirect deliberately; nav/palette/home/`more`
   leave no dead links (palette inherits nav — item 3a covers it).
3. Brand/tokens/components untouched; `tsc`/`eslint`/`vitest`/`next build` green; e2e fixture
   `apps/dashboard/e2e/fixtures/seed_operations_console.py` (imports archived modules) is P4-owned — update with the cleanup.
4. Open questions for the run (not decisions): exact redirect targets for retired URLs; `progress/` typed-empty copy;
   `surveyEntryPreset.ts`/`siteAutonomyGate.ts` retention if unimported after cleanup.

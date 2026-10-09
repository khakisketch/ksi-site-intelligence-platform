# Physical Site rebaseline — integrated local verification (P5)

Updated: 2026-10-09. **Final P5 local evidence received; cleanup/whole-product/goal acceptance remains OPEN.**
Authority and actual approval: [rebaseline ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md).
Approved [P5 plan](../superpowers/plans/2026-10-08-physical-site-rebaseline-integrated-verification-p5.md)
SHA256 `4119e5d1dca5f89c6f6c1edbb9880289c183d7529b03f53f45224a51fbfe374a`;
[spec](../superpowers/specs/2026-10-07-physical-site-platform-rebaseline-design.md)
SHA256 `14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`.
The frozen proposal header is drafting history, not current approval state.

## 1. Scope, source and environment

- One writer in the original checkout, local `main`; P5 base
  `1dac44aeca503221f924687ea1631e10d7cdcc86`. Four foreign worktrees remain untouched.
- Task1 checker/tests committed `268678921286f42203fe4410eb8d8edeb89f4028`.
  Task2 source committed `c5cca2a` (parent2686789): only
  `services/core/src/ksi_core/composition/routes/external.py` and
  `tests/contract/test_platform_core_http_integration.py`.
  Their tested SHA256 values are respectively
  `d8c06899f07dfcf3f3472083c6bfbc7fc75a8a683a628f3aa5f3e2747fe85c86` and
   `c731f2619edd35461d8482c032813844b45eb3a4dd4fcb035d9e9dc6583be854`.
- Integrated tested source is `a8f6e938c8a8c633983f12792973dcdb24aaecd6` plus the
  assignment-only parent-ledger prose; final independent pre/post 21-file snapshot SHA256
  `8ef5ab5a0c64bbdf46ed195338c5543753790f6ee10ddbeff9fbe65065fb0e76` matches.
  Task4 routing is `efae2af`, preserved-consumer repair `eeea71c`, test-only observer repair
  `a8f6e93`. Final closeout changes are records/proposal only; affected checks and the local
  record commit are linked from the parent ledger, not inferred from the earlier source run.
- Prepared Linux/aarch64 Python3.12.13 environment, uv0.11.15. All Python runs use
  `--no-sync`; the lock check is offline. No dependency installation, fresh resolution,
  image build/pull/start, CI dispatch, live credentials/activation/grants, device action,
  customer data/contact, push, publish or deployment was performed.
- Invariants INV-020/024/040/050/051/053/054/055/060/061 remain enforced by existing
  coordinate/provenance, evidence, numerical, resource, image, permission and consent
  gates. Signed-Mission/device meanings remain historical; no acquisition authority is remounted.
- Local logs/receipts are in
  `.superpowers/sdd/2026-10-08-physical-site-rebaseline-integrated-verification-p5/`.
  This report preserves sanitized conclusions, commands, source and hashes; scratch logs are not
  product authority or portable customer evidence.

## 2. Archive integrity and recovery

`uv run --no-sync python tools/verify_physical_site_archive.py` with explicit
`--root . --execution docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json
--extras docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json` produced:

| Check | Result | Limit |
| --- | --- | --- |
| Record traversal | 251checked/251expected (194main+57extras) | These manifests cover251rows, not every one of432 archived files |
| Independently bound original Git blobs | 251SHA256 matches | Recoverable originals, not a current-destination pass |
| Current destination content | 249matches; strict exit1/four findings on two rows | **P5-ARCH-01 OPEN** |
| Disposable checker controls | 29passed/exit0, RED missing checker → GREEN | Missing/changed/duplicate/escaping/symlink/blob/inverse/input controls |
| Tooling/boundary set | 100passed/exit0 (29new+71existing) | Read-only checker; no inverse execution or checkout mutation |
| Independent recovery | 12original blobs restored into owned scratch, all hashes match | One per10decision groups + both adapted files; no real-path restore/archive import |

Original record hashes: main `7fa85601a2c461d32bd99cab48939e7b010d1d08c35ff4634210c26a16c67abd`;
extras `a1867fad9461981b901c4695743066d21319e922c72044a9675788664ad31896`.
Audit report hash `4f84e25292dee0418ce812b95c61e1775df1fc88b409d7b804dbbb4ac2e364dc`;
recovery receipt hash `cef1ffb919ff2f327d7d529ce48043e7415357ef8662e5b72f2a401dd6554338`.

The two differences are P3 commit`dc9d681`'s explicit post-move field-kit path adaptations:

| Destination | Recorded original SHA256 | Current SHA256 |
| --- | --- | --- |
| `archive/acquisition-2026/tools/build_field0a_kit.py` | `abc3d8b606a23c3e636366726a0faf872ae763c41000bd01e7e19f46a9be156a` | `5cfaac4fdac7019258f5eebf9b180f77ccefe33cb40d48be1621218504f22459` |
| `archive/acquisition-2026/tests/contract/test_field0a_kit.py` | `65a1efc2b47ca44f5dcc1e6aef498cd4f6c582f4e3a4df97e07180f28f8318e9` | `03d522ef54408fe1228f7b5a60c5c7344e63b50e8aec5dfe5223fe178a70c2f8` |

Originals remain bound to their baseline Git blobs; neither immutable inverse record was rewritten.
The historical claim of blob-identical movement is accurate at move time, not for all final
destinations. The strict gate stays failed; no implicit adaptation allowlist or normalization.

## 3. Actual-platform SDK/HTTP/history evidence

Fresh task matrix:

```text
uv run --no-sync pytest -q
  tests/contract/test_platform_core_assembly.py
  tests/contract/test_platform_core_http_integration.py
  tests/contract/test_historical_managed_readers.py
  tests/contract/test_analysis_mcp_actual_inspection.py
  tests/contract/test_spatial_data_mcp_http_integration.py
  tests/replay/test_platform_core_replay.py
  tests/replay/test_spatial_data_mcp_replay.py
```

**49passed/0failed/exit0**,85.65s; log SHA256
`b9c433d079165d3f8390cd3d77bfbf9758460463da8888f29e416bcd2406c7c5`.
The two new named SDK parity tests instantiate the genuine `assemble_platform_app`, not a
router-only `FastAPI`. Existing router-only Spatial Data tests remain lower-level evidence.

| Preserved contract | Observed check |
| --- | --- |
| Analysis SDK vs HTTP | Same analysis ID/result/evidence/idempotent retry; epoch source and inspection-report hashes; real inspected DSMs and bounded worker |
| Spatial Data SDK vs HTTP | Same job/receipt; separate HTTP-only consumer downloads and hashes exact bytes/size |
| Independent platform raster oracle | 2×2 `[[101,99],[100,100]]`, mask255, NoDataNone, EPSG:5186+5773, native transform`[0.1,0,200000,0,-0.1,550000]` |
| Numerical separation | Platform cut0.01/fill0.01/net0/unknown uncertainty remains provisional; separate standard cut1/fill5/net+4/±5m³ oracle is unchanged |
| SDK nondisclosure | Forbidden raster/link/key fields absent; output reference remains a relative Core path, not a byte payload |
| Tenant, consent and rights | Foreign-tenant nondisclosure, missing/revoked consent, grant expiry/replacement/ambiguity/READ-only, exact purpose/scope controls |
| Recovery and history | Existing restart/idempotency/historical readers, two-cycle reuse and currentness controls; retained managed rows remain non-executable |
| Bytes and cleanup | Revoked midstream bytes do not become a successful partial file; cancellation and worker/private workspace cleanup |
| HTTP historical limit | External retained result routes are verified. Retained managed readers do **not** imply mounted managed ProcessingJob/artifact HTTP access |

**P5-SDK-01 (self finding, fixed atc5cca2a):** full-platform Spatial Data CREATE returned
503`AUDIT_UNAVAILABLE` because the existing job router was not given the verified AI-egress
participant, though discovery had it. The only product change passes
`egress=spatial_data.ai_egress` into the existing builder. No permission/default/schema/policy changes.
Positive SDK RED→GREEN and additional real-platform consent RED503→GREEN403 bind the repair;
list/create/get/cancel deny without acknowledgment, metadata publication or PUT when consent is absent.

Test-only identities/grants/consent/activation are exact generated Site/WorkArea opt-ins. The local
decoder uses the existing generated SDK lane's finite1GiB/1MB-output/6MB-workspace budgets, not the
metadata-only fixture's unusable1MiB/4KiB limits. Its storage checks the real Core durable output
reservation before PUT. The Spatial Data worker's HTTPS-only Core boundary is unchanged; a test-only
forwarding transport calls real loopback Core rather than fabricating response bodies. Real source/PUT
sockets and child decoding are exercised, but production TLS/kernel/host containment is **not verified**.

## 4. Active build/package/runtime gates

These checks ran against the source in §1; they do not constitute fresh image or CI evidence.

| Command/check | State | Actual result |
| --- | --- | --- |
| `uv lock --offline --check` | PASSED | exit0;157packages resolved from prepared/cache state,3ms |
| `uv run --no-sync ruff check .` | PASSED | exit0; active configured lint scope, archive excluded |
| `uv run --no-sync python tools/check_core_module_boundaries.py` | PASSED | exit0;140inventory records |
| `uv run --no-sync python tools/check_runtime_image_pins.py` | PASSED | exit0; static image reference pins, not image execution |
| `uv run --no-sync python tools/validate_repository_normalization.py` | PASSED | exit0; R0–R3 contract |
| Same validator with`--check-r3-migration` | PASSED | exit0; explicit R3 request (R3 is also current default) |
| `uv run --no-sync python tools/check_physical_site_disposition.py --manifest docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv` | PASSED | exit0; frozen baseline72c526b, no moves |
| `uv run --no-sync mypy packages services tests tools` | FAILED, pre-existing | exit1;109errors/14files,753checked; **not green** |
| Scoped mypy/Ruff on both Task2 files | PASSED | exit0;2source files clean; Task1's2files separately clean |
| Entrypoint/config/recovery/boundary matrix | Historical aggregate PASS; selection evidence limited |264passed/2warnings/exit0,85.04s; reported17-file selection, full original argv not preserved |
| Retained utility tests | Historical aggregate PASS; selection evidence limited |79passed/2warnings/exit0,1.89s; reported6-file selection, full original argv not preserved |
| Task1 full active Python | PASSED at Task1 revision |6042passed/30skipped/98warnings/exit0,741.87s; not final Task2/P5 |
| Task2 full active Python | PASSED at Task2 source |6045passed/30skipped/98warnings/exit0,751.23s; actual committed source hashes match §1 |
| Independent whole-P5 Reviewer/Test Runner | RECEIVED; scope separated in §7 | No required source findings; fresh full6047passed/30skipped/98warnings/0failed; broad types still FAIL |

Broad-type control: immutable pre-P5`1dac44a` source was extracted into owned scratch and parsed
with the same prepared mypy, no sync/install. It fails with109errors/14files/751checked. Current vs
control diagnostics have an identical multiset of `(file,message)` ignoring line numbers;
**added0/removed0**. The older recorded pre-P3 count is also109/14, but three diagnostic-producing
files changed since`8aaba33`; count equality alone was not treated as proof of identical old messages.
Control source tar hash `965b15c8ca1982aa8d383cf038c19a1478de05acc1f6f26d9a6a60c6cbd093b2`;
control log hash `b20d548ab008a24da25d901d37c53e2c4edab5c2526e2c59dbb4f4fb44603380`.
Task2 full-suite log SHA256
`0e8885760d74fe25a6b6c9d39aec6f8a3e64df07765c45d07e18a30c10abf695`;
post-commit skill Task2 matrix rerun49passed/exit0,87.66s. Warnings are disclosed, not fixed or hidden.

The recorded17-file selection describes archive deny-hooks and allowed supported imports, platform boot switches,
validation worker/config/runner/integration, Analysis config/loop/recovery, inspector entrypoint/
systemd/runtime controls, measurement entrypoint/daemon, Spatial Data config/worker/sandbox.
No production listener/config is supplied. First selection used a nonexistent Analysis-runner test
filename (exit4/no tests); corrected from actual runner imports. That no-op is not counted as a pass.
The Core boot-switch test's legacy-import naming is historical: actual acquisition-closure tests
prove the retired legacy assembly/module aliases are absent.

Task3 evidence reception SHA256 `33bb1ff5fecfa98540d8882167c2d2254693cf698367434a72082c2786583dc8`
rehashed all seven original static logs. Entrypoint aggregate log SHA256
`daea787c1b8152ddd33f723578ee27221fe345fa886023c3539f54d22cdd5f38` and utility log SHA256
`9dce1beabca91ea12e551ddb997d809799109eccf4dd2d4068b6e7cc7cb19643` have the actual264/79
tails above, but neither artifact preserves its complete17/6-file argv. That historical selection
cannot be reconstructed from a count or retroactively made exact by the final full-suite result.
This is a self-origin evidence-hygiene limit, not a new product failure or a reason to repeat a
completed suite. Final configured active-suite evidence is independently specified in §7.

Actual `services/processing-controller/pyproject.toml` SHA256
`49f6be1ef0cc32bb0fc1e6a02e43dd00f4a0e70d2eff43a4fce87a1a9fe77c4a` registers:

| Script | Source entry in `ksi_processing_controller` |
| --- | --- |
| `ksi-external-inspector-daemon` | `external_inspector_daemon:main` |
| `ksi-external-inspector-entrypoint` | `external_inspector_container_entrypoint:main` |
| `ksi-external-measurement-entrypoint` | `external_measurement_container_entrypoint:main` |
| `ksi-external-measurement-daemon` | `external_measurement_daemon:main` |
| `ksi-external-validation-worker` | `external_validation_worker:main` |
| `ksi-external-analysis-worker` | `external_analysis_runner:main` |
| `ksi-spatial-data-worker` | `spatial_data_runner:main` |

This is the registered source map, not proof that any production daemon/configuration was launched.

### Installed environment is not fresh

Read-only distribution metadata found17installed KSI distributions, including five dangling editable
records for retired roots: `ksi-mission-planning`, `ksi-mission-contracts`,
`ksi-equipment-intelligence`, `ksi-perception`, `ksi-dji-gateway`. Their old source roots and `.pth`
targets do not exist; deny-hook tests confirm they are not an alternate successful acquisition import.
No environment cleanup or synchronization was performed. Environment receipt SHA256
`9e2a570dd5cc33cc652135aff5eba682fe1a85b15972842b2fa08b4f9858bf58`.

| Separate runtime/acceptance gate | State | Blocker / owner |
| --- | --- | --- |
| Fresh dependency resolution and locked sync | UNVERIFIED | Prepared environment only; Human-authorized isolated dependency/build environment needed |
| Fresh Core image/native-library boot | UNVERIFIED | Dockerfile/static CMD inspected; no build/run authorized or performed; build/operations owner |
| Fresh inspector/measurement images | UNVERIFIED | Separate Dockerfiles/pinned CI configuration exist, no execution on P5 revision; build owner |
| CI including locked sync, images, Dashboard | UNVERIFIED | Workflow source is not a CI result; no push/dispatch authorized |
| Worker production TLS, UDS identities, ACLs, kernel containment/current config | UNVERIFIED | Local generated seams are not deployed host evidence; operations owner |
| Customer exports/rights, selected actual external consumer/host, repeated acceptance | UNVERIFIED | Required external inputs unavailable; Human/customer/operations owner |

## 5. Remaining lane classification (no source moves/deletion)

Tracked active-source AST imports plus literal consumer/entrypoint searches were compared against
`services/processing-controller/pyproject.toml`'s seven scripts and actual platform composition.
Consumer receipt SHA256 `b83bee9b06c2fbbfd6699997b80a5b7efffbfc416d655a3ef6d86dde4fb84047`.

| Module | Exact uses / status | Decision and limit |
| --- | --- | --- |
| `checkpoint_validator` | Imported by active `external_measurement_algorithms`; checkpoint tests | Active platform aggregate helper. Its historical Core-client wrapper is not a new producer |
| `comparison_worker` | `LeaseHeartbeat` used by retained `design_conformance_worker`/`region_extraction_worker`; `test_comparison_worker.py` | Retained import-only historical utility; its comparison-job executor has no active script/poller or platform route |
| `design_conformance_worker` | Only active-tree importer is `test_design_conformance_worker.py`; calls retained algorithm/Core client | Retained import-only historical utility, not a supported current external workflow |
| `region_extraction_worker` | `test_region_extraction_worker.py`; depends on retained comparison heartbeat/client | Same retained/unwired status; no producer revived |
| `design_surface_verifier` | `test_design_surface_verifier.py`, `test_convert_ifc_design_surface.py` | Retained historical verification utility; no current worker entrypoint |
| `landxml` | Retained verifier; `tools/audit_civil_field_acceptance.py`; `test_landxml_design_surface.py` | Retained bounded parser/audit utility, not external LandXML ingress or format-support acceptance |
| `core_client`, `workspace`, `capture_time` | Named above utility consumers; core_client reads capture_time,5lanes use workspace | Retained support code; presence is not active managed job/API support |

No lane is deleted because of its name, and no new move/endpoint/producer is authorized. Reclassification
or extraction of shared helpers can be separately proposed only with consumer/build/recovery evidence.

**P5-COMP-01 OPEN (self, configuration gap):** `deploy/compose.yaml:107` still defines an unprofiled
NodeODM service and `ksi-odm` volume; `compose.vm.yaml` overrides it. No current platform worker
consumes it. This retained mixed deployment template is **not an acquisition-free default stack**.
The external candidate Compose is separate and has no NodeODM. Dockerfile's leading comments also
name retired production/Mission dependencies although its actual CMD uses platform production.
No template/volume is changed or runtime started under this verification-only task. A bounded local
deployment-template decision/repair is required before advertising an acquisition-free base Compose;
historical volume/data preservation must remain explicit.

## 6. Routing, product binding and first-flow gaps

### Current-owner/document corrections

| Stale active statement | Corrected route/status | Evidence/limit |
| --- | --- | --- |
| Root components / AGENTS / structure delegated to former Gateway/Edge paths | Platform Core, independent external workers, MCP and packages; archive is labeled historical, not an instruction entry | Current dependency/route/import gates; root AGENTS still governs |
| Core README / structure advertised signing/device/acquisition/managed assembly aliases | `platform_assembly` and `platform_production`; retired shims absent, selected historical readers retained |140record inventory + real import/factory controls |
| README/docs described the 2026-09-30 pause as current | Dated initial planning snapshot separated from subsequent development and actual P5 approval in the parent ledger | No execution inferred from a frozen proposal header |
| Read-first / product-state described P4 screens as pending | Local P4 technical closure reused under exact source/render/functional hashes | No fresh UI/measurement/customer acceptance |
| System overview confused old equipment diagrams with current runtime | Current platform source table added; old diagrams explicitly historical/out-of-product | Safety/quantitative meanings preserved |
| Dashboard README described three draft-only fixtures and old Mission/fleet UI | Five synthetic Sites/areas, four historical rows + one external APPROVED/OPEN, exact E2E-only scopes and current five-tab Console | Normal accounts still empty-scoped; no mock result |
| Processing README's “kept lanes” implied current producers | Exact test/helper/entrypoint classification in §5 | No code move/deletion/revival |
| Capability registry's PAUSED_BY_USER looked like current task control | Literal status/state snapshot retained with dated comments and execution/evidence pointers | Frozen registry status multiset and product-state Milestones/Current slice unchanged |

Historical ADRs, milestone/approval records and the two move manifests remain unchanged. Current
instructions do not delegate to archived AGENTS/READMEs. An archive provenance link grants neither
runtime use nor authority. These corrections change routing/status only, not contracts or policy.
Task4 verification: product-boundary/disposition/normalization/archive-boundary **69passed/exit0**,
4.17s; explicit R3 validator exit0. Changed documents'145local Markdown links +2new YAML record
paths resolve; frozen plan/spec/manifests and P4 source hashes remain unchanged. Link-check receipt
SHA256 `c476d7e68616f657da39ed9c9eb49002a8efec3d891371b65c838ef91376d3ee`.
This is a file/link/status check, not a deployed-site or missing-customer gate pass.

### Product binding and P4 evidence reuse

- Repository/actual source: `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform`,
  `apps/dashboard`; locally integrated P4 source/evidence`7f44d11`, closeout`1dac44a`.
  Representative design project`6edb22d8-bd56-43df-9e13-521a30700925` (existing KSI Operations
  Console binding; no new run/project/rebinding). P5 has no design/UI writer.
- Start entry: `apps/dashboard/scripts/run-local-oidc-stack.mjs`; the existing prepared standard
  loopback start is `npm run dev:local` in`apps/dashboard`. Last P4 evidence target used that entry
  with `--dashboard-port 3241 --core-port 8041 --issuer-port 9041 --tailscale disabled`, run-owned
  data/identity paths, `.next-p4-resume` and `--seed-operations-console-e2e`. These are recorded
  commands, **not a P5 restart/install/grant authorization**.
- Last actual-product URL`http://localhost:3241/` and Core8041/Identity9041 are temporary
  host-loopback only (not customer workstation/tailnet/public). P5 read-only GETs now fail
  `ConnectError` on all three; no substitute demo or duplicate runtime was started.
  Prior Studio context`http://127.0.0.1:7456/projects/6edb22d8-bd56-43df-9e13-521a30700925/`
  is separate design context, not actual auth/API verification or a verified live link.
- Brand source: `apps/dashboard/src/app/globals.css` SHA256
  `0cab25cb895182296a0fdc565ce4445565bab3502e20cffe21b736c5fe300b47` and existing approved
  components. No token, Home image, timestamp mask, `maxDiffPixels3500` or visual source change.
- Final P4 source snapshot`p4-cleanup-evidence/t5-final-source-v1/source-snapshot.json` SHA256
  `8256911ce314281e04e2b3b57852033d54d1e07333bfc46106a8fafa66701a1c`:
  **353/353 workspace hashes match**,352tracked Git blobs match; the remaining ignored `.pyc`
  is explicitly nonportable and not product source. P5's Dashboard README is outside this snapshot.
- Design-owned rendered report`p4-cleanup-final-render-review.md` SHA256
  `5635f47bc2979adfd38358bb0a2f7a708be5709fc78b9c33c1aa8c14260ecc19` confirms reading all18
  actual accessible/denied Analysis/assets/More PNGs at390/768/1440. Concrete heading/copy/alert
  findings fixed; previous four-width keyboard/CTA/Home and empty/loading/motion bindings explicitly
  reused. Required design-owned residuals0. It is not a new Build aesthetic review.
- Independent final-P4 Runner`ses_ee3cff067ffenNG7tq5WksJSvI`, receipt SHA256
  `e6267cebe7e6d49eb4b6c9a70d7a2241460b0c9e46e859f3141869f52596718d`:
  typecheck/lint/build exit0, Vitest762/100; authenticated E2E77passed/15explicit conditional skips/
  0failed/0flaky at390/768/1024/1440. Genuine login, navigation, work assignment persistence/reload,
  denial and honest optional-unavailable states were tested, **not successful configured full analysis**.
  Receipt's remaining unresolved conditional coverage remains disclosed.
- Before/after/state evidence and reports: `apps/dashboard/p4-cleanup-evidence/`,
  `apps/dashboard/p4-cleanup-final-render-review.md`, `apps/dashboard/p4-cleanup-evidence/verification/`.
  Task4 reuse/reachability receipt SHA256
  `4508f7f66ed8413ac3d9de61f7a6e212c606f6f242abf17b12ea1d3af2d70fde`.

### First useful experience: intended vs actual vs acceptance

The approved target is Site/WorkArea → two supported DSM observations → deterministic compatible
area/pair selection → evidence-bound change or actionable blockers → same area for next epoch.
Analysis and data preparation are separate uses of the same authorized records, not two backends.

| Step | Actual Core HTTP/API and SDK | Console / local evidence | Remaining input/decision |
| --- | --- | --- | --- |
| Create Site | Existing POST`/v1/sites` works for authorized unscoped human in actual-platform tests. Scoped OIDC allowlist lacks this method/path; human403 is intentional current contract. MCP has no Site-admin tool | Existing registration UI/proxy present but scoped default operator cannot create; P4 does not establish onboarding success | **F-01** explicit human Site-bootstrap/grant ownership decision; no simple allowlist widening. Product target remains, not silently downgraded to precreated Sites |
| Create/reuse WorkArea | Scoped POST/list/archive is already audited; frozen polygon/revision and exact grants retained. New identity does not automatically enlarge a caller's allowed-area mapping | Existing WorkAreaPanel/proxy; original API/generated setup and reuse tests. No complete default-account first-onboarding browser proof | Grant provisioning for a newly created area's use needs the F-01 contract; do not broaden all resources |
| Register t0/t1 DSMs | External-only WorkOrder; V2 context/registration, direct upload grants/PUT/seal, inspected revision/report/source digests through real byte lanes | External registration UI exists. P4 runner uses unavailable evidence storage without explicit S3; real upload/seal/display therefore not verified there | **F-02** permitted derived exports/rights and configured owned storage/inspection/worker environment |
| Select area/compatible inputs | Existing Analysis V2 and Spatial Data V1 discovery bind exact area/revision/digests; ambiguity/foreign/stale inputs fail closed. SDK uses those same selectors | Current AnalysisRequestPanel and assets selector exist; default Analysis graph not configured; no synthesized empty-success substituted | **F-03** protected graph/authority/runtime configuration and reviewed signed worker/inspection pins, not new computation/format |
| Retrieve result/evidence/blockers | Full-platform Analysis SDK vs HTTP compares same IDs/result/evidence; Spatial SDK vs HTTP receipt/download pixels match. V1 strict / V2 provisional remain distinct | P4 actual unavailable and denied states verified; configured result-bearing Console journey is **not** end-to-end proved by the separate SDK fixture | Configured same-origin/auth/real-byte browser flow; no live grant/policy activation implicit. Numbers never establish progress/settlement |
| t1→t2, reuse area | Existing Analysis actual-inspection SDK, Spatial next-epoch and platform replay tests cover repeated area/history/idempotency/currentness | New-observation CTA/navigation and historical follow-up views retained; full repeated configured browser workflow still unverified | **F-04** permitted same-Site t0/t1/t2, one selected external consumer/host, two-cycle operational/customer acceptance |

Known roster/team/pending denial/unmounted optional endpoints are not permission to create a new
workflow. They remain limits/backlog unless they block the selected approved first experience.
MCP registration/admin omissions are deliberate human-authority boundaries, not “missing tools”.
Finite generated fixtures demonstrate software behavior only; repeating them cannot replace rights,
customer data, accuracy evidence, external host or operational acceptance.

### Smallest justified successor direction (proposal, not execution)

Before expanding features, resolve the concrete standalone-runtime gap: an acquisition-free **default
deployment template** preserving existing historical data/volumes, followed by separately authorized
fresh locked dependency/image/boot evidence. This addresses P5-COMP-01/RB-08 rather than inventing
another API/format/State/feed/remote transport. The stricter archive gate still needs a reviewed
append-only adaptation-lineage decision, never edited original inverse hashes.

The first-flow follow-on should then connect the **existing** UI/API/SDK and configured storage/
workers, not rewrite the supported engines. F-01 is a material auth/bootstrap decision; F-02..04
require named rights/environment inputs. Until those are available, do not claim full first-flow
acceptance or run a new feature plan. The [P6 written proposal](../superpowers/plans/2026-10-09-platform-only-default-deployment-template.md)
addresses only the template gap, with the same historical-volume/configuration preservation and
approval/external-effect gates. It is not approved implementation or a full-goal replacement.

## 7. RB-01..09 and independent closeout

Whole-P5 source Reviewer `ses_ee156b61dffeI89kzc3v8ZTeRl` reviewed `1dac44a..efae2af`:
no Critical/Important findings, two deferred evidence-hygiene minors, report SHA256
`7bcb406a7ce74ff8e8d4af724b24f4790a96e1207c42985cb88b71f22f13dd08`.
Its repair-delta review `efae2af..a8f6e93` found no required/new minor findings, report SHA256
`f08feaa8f1187498af2eb96c7418ec6d08741461f3c7b37b1f34a59062127ef8`.
Source review does not replace independent execution or design-owned rendered review.

| Independent state | Actual result | Disposition |
| --- | --- | --- |
| `efae2af` first Runner | 1failed/6044passed/30skipped/98warnings; logSHA `3b892cad9b81687989dfc2232903b704577244d721bf5749dab6f68cc568d730` | P5-ROUTE-01: lost historical Edge consumer reference. RED→provenance-only `eeea71c` repair; actual committed-HEAD gates99passed |
| `eeea71c` completion Runner | 1failed/6044passed/30skipped/98warnings; logSHA `e3a2a5ddd7a6eb29d05b8e33ad7368f213ba3ece82778d5c31c39a6da0bd1ded` | Repaired routing witness passes. P5-OBS-01: private worker observer incorrectly requires concurrent AI-list projection to stay stable; no waiver |
| Narrow observer repair `a8f6e93` | Deterministic original409/200 RED; preservedAI409/noack controlPASS; affected matrix122passed/exit0 | Test-only authenticated worker-queue observation, not changed permissions/SDK/metadata guard |
| Final Runner at `a8f6e93` | **6047passed/30skipped/98warnings/0failed/exit0**,754.96s; logSHA `6bccdbc2e3ad9da4b3cb49476ecc411e4598d04bc791f9cc4e8347572c2b8fc9` | Both required repair witnesses included; previous failed suites remain historical evidence, not relabeled green |

Completion receipt SHA256`8a72834e56dedf7ddc917bea8ea9659ab3ccd6915222a79835ef58ce0d1500ce`
confirms unchanged HEAD/pre/post20inputs and supplies all unfinished required checks: strict archive
251checked/251original/249destination (exit1), twelve recovered original blobs match, scoped4files
clean, broad/control109errors/14files with0added/removed,146local links/0broken+YAML paths, matching
P4source353/input22(18PNGs)/reports/logs. SDK49/checker29/routing69/static6 are unchanged-input reuse,
not another fresh run. P4reuse remains77E2E/15explicit skips/0fail/0flaky, not a live browser claim.

P5-OBS-01 controlled real-HTTP overlap proves the preserved contract: emptyAIpage → genuine jobPOST
→ send-time digest mismatch409`REPORT_CONFLICT`, no acknowledgement/items; a new page and existing
authenticated worker queue both200 with the correct job. The fixture's worker dispatch now observes
that queue using its already-generated worker token/activation instance, without generic retries,
ADMIN impersonation, sleep extension or consumer downgrade. Two deterministic tests protect both
dispatch and the unchanged AI refusal; original example SDK/result/bytes assertions remain strict.
Repair receipt SHA256`64c92c94e7e8742906d2f159f981bd5eb3bf1475f48afba1ed0138715d60104a`
binds testSHA525b754e/RED/GREEN logs. Full-suite failures remain historical evidence, not green.

### Final execution receipt and reception

Final Runner `ses_ee103b8c0ffeHhl4qT8rAFSozC` finished at2026-10-09T05:06:35Z.
The completed artifact was recovered after the outer session interruption; prior waiting summaries
are superseded by the actual finished receipt, not evidence of a new test run. Receipt SHA256
`124a13d45083eec069ffa245253497fc2bbaae433ec89712d54f36df30a577de`, local location
`/tmp/opencode/p5-observer-independent-final-20261009/receipt.json`.

| Exact final command | Exit / observed output | Log SHA256 |
| --- | --- | --- |
| `uv run --no-sync pytest -q -p no:cacheprovider` |0;6047passed/30skipped/98warnings/0failed,754.96s | `6bccdbc2e3ad9da4b3cb49476ecc411e4598d04bc791f9cc4e8347572c2b8fc9` |
| `uv run --no-sync ruff check .` |0;All checks passed | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| `uv run --no-sync mypy packages services tests tools` |1;109errors/14files,753checked; pre-P5 control added0/removed0 | `546479e8501427592ac20d842058ad7c424a76171e0b7f72898052cf5d4378ef` |
| `uv run --no-sync mypy --follow-imports=silent tests/contract/test_spatial_data_mcp_workflow_example.py examples/spatial-data/native_window_client.py` |0;2files clean | `f9b031e5c45aa702cd4fef028d465551cb20a2c4698e0913c7b00766b20ac4d8` |

The final receipt binds pre/post HEAD, sole pending assignment-ledger bytes, ambientumask0002,
Python3.12.13, approved spec/plan, all21frozen inputs and19unchanged reused inputs. It reuses the
completed archive/recovery/SDK/static/P4 results only where their inputs match. Broad comparison
uses the error `(file,message)` multiset, not equal counts alone:109/14 unchanged; two additional
mypy note-hint lines are not new errors or a broad pass. Thirty configured Python skips remain
unexercised coverage; this final `-q` log does not enumerate their reasons. They are not counted as
successful cases or proof of optional/host readiness. The archive is excluded, not silently green.

Primary reception `/tmp/opencode/p5-final-evidence-reception.json` SHA256
`6d4fc44d1a0e8aa6a12645ea17b34f58d01bcb7f24232f3d9699bfdd99ddeb18` independently rehashed
the actual receipt/four logs/control/review reports, all21+19inputs,251recorded destinations and
original Git blobs,12recovered scratch blobs,353P4workspace/352Git source hashes,22render inputs
(18PNGs) and10P4verification inputs. No suite, daemon or browser was restarted. One initial
reception-script label/path mismatch was corrected against the report schema; it did not mutate
source or count as a product failure. The now-completed source run permits doc-only closeout;
its affected consumer/link checks and local record commit are recorded separately in the ledger.

### RB adjudication — local evidence is not full acceptance

| ID | Evidence and current disposition | Remaining condition |
| --- | --- | --- |
| RB-01 | Local authority/routing verified: ADR039, product documents and preserved-status checks agree | No new product obligation inferred from history |
| RB-02 | Disposition/link/instruction boundary locally verified;251originals recoverable; **strict destination gate FAILED** on2adaptations | Separate reviewed adaptation-lineage decision; do not rewrite inverses or claim249means251 |
| RB-03 | Genuine platform factory/byte flow, registered workers and acquisition deny-hooks verified locally; **PARTIAL overall** | P5-COMP-01 default NodeODM plus fresh isolated boot not resolved |
| RB-04 | Local generated actual-platform SDK/API result/receipt/source parity and typed negatives verified | Selected real consumer/customer acceptance and production transport remain open |
| RB-05 | Local retained historical reader/replay and strictV1/provisionalV2/profile/numeric semantics verified | No universal managed HTTP access or quantitative/settlement certification |
| RB-06 | Controlled restart/idempotency/tenant/rights/consent/currentness/cancel/cleanup negatives verified | Production TLS/UDS/ACL/kernel/configuration unverified |
| RB-07 | Changed P4 cleanup's auth/reload/mobile/error and design-owned actual rendered review reused under matching hashes | Old target offline; configured real-byte/repeated first-customer flow unverified |
| RB-08 | Active offline lock/pins/inventory/package/archive exclusions verified; **PARTIAL overall** | Broad109/14FAILED,5dangling editables, fresh sync/images/CI/host unverified; P6 only a proposal |
| RB-09 | Independent integrated source checks received; task-owned record reconciliation is the final P5 closeout step | Parent ledger binds affected record checks/local commit; human acceptance/external delivery remain separate |

No whole-cleanup/goal/customer/EXT-VAL/vendor/accuracy/operational acceptance is established.
The P5 deliverable is a verified local preservation/repair and discrepancy report, not a waiver of
RB-02/03/08 or the first experience. Author6045pass belongs to Task2 before Task4; it is not final evidence.

## 8. Full objective to artifact / gate checklist

The objective remains: industry-neutral evidence-bound Site State/Change; independently built/run
platform excluding acquisition/reconstruction; preserved existing data/Analysis/MCP/history; and
the actual reusable first experience with permitted customer inputs and one selected external consumer.
P5 reporting or P6 template cleanup does not substitute a smaller objective.

| Explicit requirement / deliverable | Concrete artifact and evidence | Achieved boundary / open gate |
| --- | --- | --- |
| Written design, plan review, goal and chosen sequential method | Approvedspec14ded50b, frozenP5plan4119e5d1, parent-ledger approvals, native goalb13320f7 | P5 authorized; no P6 execution inferred from goal continuation |
| Physical Site identity, long-term exclusions, unchanged milestones | ADR039, Constitution/Ledger/PRD, current routing, status pin tests | Local RB01; original acquisition history/status retained |
| File-level dependencies/moves/recovery, no folder-name deletion | Frozen disposition/decision/main+extras manifests,251row checker29controls,12original recovery | Strict2adaptation gate failed; manifests cover251rows, not all432archivefiles |
| No runtime/build/import/instruction delegation to archive | Active Core/worker inventory and deny-hook positive controls, exclusions/currentAGENTS | Local boundary checks; P5-ROUTE-01 restored provenance only at `eeea71c`/99checks |
| Registration/inspection/catalog/data/Analysis/API-MCP same authority | §3 genuine seven-file49matrix, exactIDs/revisions/digests/receipt and independent pixels/CRS/NoData/hash | Local generated software; one-line P5-SDK-01 fix `c5cca2a`; no second backend or fake bytes |
| History/replay, rights/consent/currentness, strictV1/provisionalV2 meanings | Existing historical/replay/negative matrices and §3 numerical oracles | Local RB05/06; preserve422external-required, non-executable managed history and legitimateAI409/noack |
| Narrow demonstrated repair, independent final evidence | `eeea71c` routing and `a8f6e93` observer RED→GREEN; Reviewer+delta reports; final6047/30/98/0 | Product/auth/numeric contracts unchanged; no blind retries or test waiver |
| Console/design ownership and actual changed states | P4source353/352,22inputs/18PNGs, report5635f47b, independentreceipt e6267ceb;77E2E/15explicit skips | Unchanged-source reuse only, not live or configured full-result/customer verification |
| Independent build/package/CI structure | §4 lock157/static140/pins/normalization/disposition, source-owned seven scripts | BroadtypesFAILED; fresh dependency/image/CI/host unverified; NodeODM default OPEN |
| Site/WorkArea creation then t0/t1/result then t1/t2 reuse | §6 step matrix; actual unscoped SitePOST, scoped denial, audited WorkAreaPOST and non-automatic grants | F01material bootstrap/grant decision; target not downgraded to precreatedSites |
| Actual permitted bytes, storage/worker/graph and one real consumer | Existing byte ports, protected production configuration and localSpatialData assembly distinction | F02–04data/rights/config/host missing; productionfactory does not injectspatial_data; no invented env switch |
| Private data/keys/state/HIL/foreign workspaces protected | Scope-bound diff/index/commands and four preserved foreign worktrees | No install, activation, live grants, push/publish/deploy/registry/device/customer-contact action |
| Durable evidence/Git/checkpoint/stop report and next plan | This audit, parentledger/product-state/checkpoint, [P6 proposal](../superpowers/plans/2026-10-09-platform-only-default-deployment-template.md) | Local record closure separate from product acceptance/external delivery; pending approvals stated |

All named P5 tasks/commands map to §§2–7 and the approved plan. Quiet264/79selection argv is
explicitly unavailable, not filled by inference. Generated fixtures, review advice and green pytest
do not cover required customer rights, operating environment, accuracy or unrun build/host gates.

## 9. Remaining decisions and responsible owners

1. **Human written review:** [P6 two-task local template/test/docs proposal](../superpowers/plans/2026-10-09-platform-only-default-deployment-template.md).
   Recommended next engineering step; no successor source change before approval.
2. **Human/build/operations:** separately scoped isolated dependency sync/image/boot/CI authorization
   and prepared capability. P6 approval is not this authorization and cannot close RB08 by itself.
3. **Human/lineage owner:** append-only adaptation-lineage decision for the2historical files;
   keep original inverse hashes and strict checker unchanged until separately reviewed.
4. **Human/security/product:** F01scoped Site bootstrap and newly-created WorkArea grant ownership;
   do not silently widen allowlists or automatic grants.
5. **Human/customer/operations:** permitted same-Site t0/t1/t2exports/rights, protected storage/
   Analysis/worker configuration, selected real external consumer/host and two-cycle acceptance.
   A Spatial Data production assembly/activation interface, if needed, is a separate material contract,
   not an omitted existing environment switch. No generated-data substitute or automatic live activation.

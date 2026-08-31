# Current Handoff

## 2026-08-31 — Automatic PSDK media ingest now fails closed instead of using a production fake

The immediate operator workflow stays simple: remove the aircraft SD/storage media, copy photos to the
field PC, and upload them through the existing KSI source-media flow. This is the accepted pre-HIL product
path, not an embarrassment or a temporary hidden workaround.

The audit found that the packaged PSDK app previously could opt into a `FakeMediaSourcePort` with zero
photos and call it a production media worker. Replacing that fake with `DownloadFileList` would still be
unsafe: the active dispatch supplies only a `missionId`; there is no completed-sortie signal, verified
capture window or pre-mission SD-card baseline. Old photos could therefore be sealed into the wrong
mission. `ksi_psdk_app` now contains no fake camera source or automatic media worker, and the historical
`KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD=ON` request fails at CMake configure with that exact reason.

Reusable software was preserved. The PSDK-independent rights marker, bounded spool, SQLite lifecycle,
digest checking and Core upload conveyor remain in `edge/manifold-runtime` with their test double. The
production option can reopen only after exact list/download identity, mission-scoped selection, one M4D
ground JPEG HIL, rights release/Pilot album recovery and a cross-mission negative test.

Current local evidence at `32e4a71`: focused combined suite `322 passed`; full Python `4228 passed /
24 skipped`; Ruff; Mypy `443` files; lock, diff, hygiene, reference and runtime/PSDK pin gates; native
Ubuntu 20.04/gcc 9.4 CTest `7/7`. Default host CMake configure and full `ksi_psdk_app` build pass;
media option ON fails intentionally at the new blocker. Canonical risk
`psdk-media-offload-mission-attribution-unbound` is open. Spatial-model lifecycle has new `315 passed`
evidence for the old capture-time gap, but remains `in_progress` pending independent review.

Nothing physical was inferred. FIELD-0a and actual camera-media capability remain `BLOCKED`/
`NOT_VERIFIED`; no DPK install, camera/gimbal action, flight, motor, waypoint, customer data, raw JPEG,
credential, release or deployment occurred. After full local gates and commit, delivery still requires
the owner-terminal fast-forward push and separately scheduled no-flight HIL.

---

## 2026-08-31 — Perception runtime boundary is closed; field acceptance remains separate

The repository no longer gives two contradictory answers about Python perception. The recorded
`ksi_perception.pipeline` path is offline replay/model evaluation. It keeps the production EventBundle
shape so contract drift remains detectable, but every generated bundle self-identifies with
`executionClass=OFFLINE_REPLAY_EVALUATION`, `productionEvidence=false` and the legacy
`vertical-slice-demo` rule. Native `ksi_psdk_app` remains the only production Edge runtime.

Core now returns `NON_PRODUCTION_EVIDENCE` (HTTP 422) before an offline bundle can reserve the durable
Edge journal or device sequence. The same policy is enforced when internal code calls EventStore
directly, and startup fails closed if an old projected/updated journal contains replay evidence. Policy
rejection does not consume sequence zero, so the next normal native-style bundle proceeds. OpenAPI
`1.31.0`, ADR-KSI-009 D8 and the Final Decision Ledger record that exact behavior.

Local evidence: implementation `ad8d899`, authority `6530989`; focused boundary/API/replay suite
`217 passed`; full Python `4225 passed / 24 skipped`; Ruff; Mypy `442` files; lock, diff, hygiene,
reference-import, reference/PSDK and runtime-image pin gates. Canonical risk
`perception-pipeline-production-status-undecided` is resolved.

What remains is not silently green. The five open risks require real Manifold/Pilot/HIL evidence or an
explicit Python 3.12 activation-runtime deployment decision. `riskfield-evidence-chain-not-hil-verified`
and mission-contract rejection remain device gates; DJI Pilot Cloud and patrol cadence remain field
gates. FIELD-0a stays `BLOCKED`, every physical capability stays `NOT_VERIFIED`/OFF, and no DPK,
device write, flight, motor, waypoint, camera/gimbal, customer-data, release or deployment action was
performed.

Delivery is pending. `origin/main` remains `899c6c8`; these local commits have not been pushed and
remote Actions have not executed them. After an owner-terminal fast-forward push, compare remote SHA
and restore the GitHub Actions account payment/spending gate before making any remote-green claim.

---

## 2026-08-31 — Edge RiskField software assembly is green; real-device chain is not verified

The native RiskField chain was already present but the risk ledger still described it as libraries with
no production host. `ksi_psdk_app` is now explicitly documented and regression-tested as the one DPK
service process that receives PSDK ingress, drives `EdgePipeline`, writes a shared SQLite WAL/artifact
vault, and continuously calls `StoreForwardSyncDriver` through `CoreRestSyncTransport`. Perception and
sync state must be identical when both are enabled; partial activation/TLS/bearer/Ed25519 configuration
fails closed. A second daemon was deliberately not added.

The existing security path was re-proven rather than assumed. Edge signs the canonical seven-field
artifact payload with an external owner-only Ed25519 key. Core checks the registered active key, device,
content digest and active dispatch/policy/calibration lineage. CRITICAL confirmation then verifies stored
bytes, v1.1 schema, geometry, bounded validity, exact entities, uncertainty, horizon, race state and the
post-confirmation digest. Missing/forged/cross-device/revoked/expired signatures and semantic mutations
remain rejected.

Local evidence: commit `3afeb73`; new guard `4 passed`; focused assembly/security/CRITICAL suites
`90 passed`; pinned Manifold Ubuntu 20.04/gcc 9.4 CTest `7/7`; full Python `4220 passed / 24 skipped`;
Ruff; Mypy `442` files; lock, diff, hygiene, reference, PSDK and runtime-image pins. No Dashboard file
changed; the immediately preceding same-turn full UI evidence remains `62 files / 572 tests`, lint,
type, build and four-viewport Playwright `62 passed / 14 intentional skips`.

Canonical risks now distinguish facts: three stale software risks are resolved, while
`riskfield-evidence-chain-not-hil-verified` remains open. The new playbook §8.2 requires an exact DPK SHA,
private key/public registry binding, bearer/CA/SPKI configuration, Core registration→storage PUT→ACK,
offline/restart recovery and a private evidence URI. It forbids treating a fixture transport test or
`SENSOR_ALIGNMENT_REQUIRED` producer as end-to-end PASS and performs no CRITICAL confirmation.

Delivery is pending. `origin/main` is still `899c6c8`; this environment cannot launch `git push`, and
remote Actions must actually execute after the account payment/spending gate is restored. FIELD-0a stays
`BLOCKED`; all DJI/physical Edge capabilities stay `NOT_VERIFIED`/OFF. No device, DPK, flight-control,
camera/gimbal, customer-data, release or deployment action is part of this increment.

---

## 2026-08-31 — Civil report coverage evidence is locally green; push environment is blocked

The civil report no longer presents progress/quantity numbers without their observation basis. Core
`ReportExportSnapshot 1.1` derives the latest design-result mission's accepted CoverageReport prefix and
server rejection prefix from organization-scoped immutable journals. Later reports do not rewrite an
earlier export, idempotent retries remain stable, and pre-coverage `1.0` records replay without inferred
facts. Rejected raw claims are not copied into the snapshot.

The existing report page now shows the same report status, principal, termination state, three
aircraft-reported ratios, unobserved-cell count, recovery recommendation, attribution warning, plan
reconciliation and rejection details that its CSV and browser print use. `NOT_REPORTED` is not rendered
as zero. If either coverage read fails, or the returned Core audit snapshot differs from the rendered
Site/progress/mission/evidence facts, print/Blob creation never starts. Existing Home/Sites/Work/Items IA
and visual language are unchanged.

Local verification is green at feature commit `e576217`: Python `4216 passed / 24 skipped`; Ruff;
Mypy `441` files; Dashboard `62 files / 572 tests`, ESLint, TypeScript and production build; Playwright
`62 passed / 14 intentional external-staging skips` across 390/768/1024/1440; lock, diff, hygiene,
reference-import, reference/PSDK pin and runtime-image-pin gates. Risk
`coverage-reconciliation-not-in-print-or-csv` is resolved in `164c2c2`. This does not claim that Core
recomputes aircraft-reported ratios from raw classified cells; that INV-010 limitation remains explicit.

Delivery is not complete. At the push attempt, the final fetch showed remote `899c6c8` is a safe
ancestor and local `164c2c2` is two commits ahead with a clean worktree; this handoff entry follows
locally. This environment rejected `git push origin main` before process launch because approval is unavailable, so no remote mutation occurred. Run the owner
terminal fast-forward push, then compare local and remote SHA. Remote CI remains separate: historical
run `33317220883` had six jobs and zero executed steps under the account payment/spending-limit gate.

Korean same-site civil evidence, FIELD-0a, DJI SDK artifacts and physical HIL remain external gates.
FIELD-0a is `BLOCKED`, all DJI capabilities are `NOT_VERIFIED`/OFF, and no device or flight-control
action is authorized by this increment.

---

## 2026-08-30 — Civil runtime/resource software is green; external release gates remain

ADR-KSI-032 is implemented without changing the Operations Console information architecture. Every
production-owned external runtime reference is exact-digest pinned and statically scanned. Core owns an
immutable `ksi-civil-pilot-r1` policy and derives file count, per-file/bundle size, megapixels and active
same-organization jobs from authoritative records; callers cannot submit limits or policy overrides.
New jobs retain the exact snapshot/digest, replay rejects forged or internally violating records, and an
identical active-job retry returns its existing immutable record rather than being reinterpreted by a new
policy. The existing Mission card shows the Core policy and typed next action while preserving upload and
history behavior.

`tools/build_release_evidence.py` adds a create-once owner-only local provenance envelope. It refuses a
dirty source, evaluates runtime refs from the exact committed Git tree, requires exact KSI image tag+digest
and paired external CycloneDX/scanner JSON, and rejects symlink/path-swap, malformed/oversized input and
partial-output hazards. Its SHA sidecar is not a signature or WORM proof, and structural artifact/image
association is not proof that the artifacts were generated from that image.

Local verification is green: Python `4215 passed / 24 skipped`; Ruff; Mypy `441` files; Dashboard
`62 files / 566 tests`, ESLint, TypeScript and production build; Playwright `62 passed / 14 intentional
external-staging skips` at 390/768/1024/1440; lock, hygiene, reference, third-party checksum, runtime-pin
and diff gates. Functional commits are `89c2fea`, `273ab64`, `ddd1c8c`, `427dec8`, `5f22f5e` and
`04cb68a`, followed by the state-ledger commit.

The final fetch and clean-worktree check passed: `origin/main` `0ff5f94` is an ancestor and local
`fc711e0` was 14 commits ahead. This Codex environment rejected `git push origin main` before process
launch because approval is unavailable, so no remote mutation occurred. The owner terminal must perform
the fast-forward push and compare the resulting remote SHA. Remote CI must actually execute; the historical
GitHub account billing/spending-limit failure is not application failure and not green evidence. A real release still requires actual
product-image builds, SBOM/scanner review, registry promotion, signature/WORM/remote anchoring, Cloud/data
approval and restore evidence. Korean same-site civil acceptance is separate. FIELD-0a stays `BLOCKED`,
all DJI capabilities stay `NOT_VERIFIED`/OFF, and no device or flight-control action is authorized.

---

## 2026-08-30 — Civil operational closure is locally green; push environment is blocked

The owner pushed `0ff5f94afad458527e71e7229fa015dc1d6136e0`; local and remote `main` match and the
starting worktree is clean. GitHub Actions run `33260008688` targets that SHA, but all six jobs stopped
before any step because the account has a failed payment or insufficient Actions spending limit. The
delivery record must therefore say **push complete / remote execution blocked**, not push pending and
not remote green.

The implementation preserves the approved Console and civil contracts while adding immutable
report-export audit, Core/Processing correlation, safe opt-in pinned NodeODM+MinIO live CI,
direct-spacing `plannedCoverageRatio=null`, failed/cancelled reconstruction recovery and corrected
Python/C++ activation-enforcement documentation. Local verification passed: Python `4147/24 skipped`,
Ruff/Mypy/lock; Dashboard `60 files / 552 tests`, lint/type/build; four-viewport Playwright
`62 passed / 14 intentional skips`; hygiene/reference/pin gates; native runtime+sanitizer `7/7` each
(SQLite backend unavailable on this host); and PSDK logic `2/2` plus default fail-closed.

Feature commits are `1e1c8d6`, `c55e58d`, `9f5ae15`, `4446a5d`, `3dcbee8` and `bd67fe7`. Fetch proved
remote `0ff5f94` is a safe ancestor. The Codex command policy then rejected `git push origin main`
before launch because approval is unavailable, so remote `main` is unchanged and the owner terminal
must perform the fast-forward push. The owner-triggered live workflow has not run owner imagery.
Korean field data, FIELD-0a, DJI SDK artifacts and physical HIL remain external gates. No device
action or capability promotion is part of this work.

---

## 2026-08-29 — Independent checkpoint-validation software is green; historical delivery record

ADR-KSI-031 adds an optional independent-checkpoint producer to the existing civil processing flow.
The user declares a sealed CSV's provenance, hash/size, CRS, vertical reference and explicit
independence attestation; the client cannot supply RMSE. Core retains an organization-scoped immutable
register → seal → `VALIDATED`/`REJECTED` journal. Processing Controller must re-hash both the sealed
CSV and immutable DSM, parse the strict CSV and compute all statistics server-side. Any invalid input,
CRS/vertical mismatch, point outside the DSM or nodata point rejects the complete validation. A verified
metric can document an operational uncertainty source, but never proves physical independence,
survey-grade accuracy, settlement suitability or field acceptance.

Implementation and full software verification are complete. Python passed `4122` tests with `24`
skips and `3` expected failures; Ruff and Mypy (`431` source files) passed. Dashboard Vitest passed
`59` files / `545` tests, followed by ESLint, TypeScript, production build and Playwright `62 passed /
14 intentional skips` at 390/768/1024/1440. Lock, diff, repository hygiene, reference-import and pin
gates passed. Local commits are split as `32e52b4`, `79bc5fe`, `95c72e8`, `cf6c9f9`, `30399ba`,
`19c1819` and the acceptance-ledger commit. The 2026-08-30 fetch proved `origin/main` is a safe ancestor,
but this execution environment rejects `git push` before launch. GitHub Actions run 33139495105 shows
all six jobs at zero steps with the same account-payment/spending-limit failure annotation. Restore the
owner account's Actions billing, run the fast-forward push, and verify that the new HEAD's jobs actually
execute; no remote CI/release/deployment is claimed before those two external gates close.

Additional local CI-parity checks passed while the remote account was blocked: MixERC-Seg import plus
contracts `22/22`; PSDK-independent logic `2/2` plus default missing-PSDK fail-closed; and an exact arm64
Ubuntu 20.04 target container (gcc 9.4.0/CMake 3.16.3/glibc 2.31) with native, ASan/UBSan and Manifold
target control-plane tests each `7/7` plus ABI verification. The temporary image was removed. These
checks increase confidence but do not stand in for GitHub's clean x86 installation, QEMU/buildx/cache
or an actually executed remote run.

The existing UI is protected: this adds an optional card to the civil flow rather than a new navigation
area or a visual-system redesign. Existing NodeODM/LandXML/foreign benchmark evidence remains historical
baseline context, not acceptance for the new producer.

FIELD-0a remains `BLOCKED`, and all DJI capabilities remain `NOT_VERIFIED`/OFF. This increment does
not perform or authorize flight, motor, waypoint, camera/gimbal, DPK, Pilot 2/Manifold automatic
egress, device write or capability promotion.

---

## 2026-08-29 — Civil processing v1 software and foreign benchmark complete; field gate remains

ADR-KSI-030 fixes the product direction for the first civil flow: KSI-managed immutable
`ksi-odm-civil-v1` (NodeODM 2.2.4 / ODM 3.5.6; digest-pinned image; DSM/DTM; medium point-cloud
quality; masking OFF), original-preserving LandXML TIN design surfaces, and a server-owned
fail-closed comparison compatibility decision. `REQ-INT-104` and `INV-053` prohibit a quantitative
comparison when Analysis Readiness, profile, source lineage, CRS, vertical reference or the required
design revision/normalization evidence is unknown or mismatched.

The normal v1 media entrance is intentionally simple: `SD/저장매체 → 현장 PC → KSI 웹 업로드`.
The existing local uploader must use the same profile. GeoTIFF upload and IFC→GeoTIFF remain; DWG/DXF
direct parsing is out of scope. Existing Operations Console Home·Sites·Work·Items structure and visual
language remain; the existing upload/design/comparison panels receive only additive status/actions.

The implementation and software regression are complete. Python passed `4051` tests with `24` skips
and `3` expected failures; Ruff and Mypy (`424` source files) passed. Dashboard Vitest passed `58`
files / `541` tests, followed by ESLint, TypeScript and production build. Playwright passed `62` tests
with `14` intentional skips across 390/768/1024/1440. Lock, diff, repository hygiene and reference-
import gates passed. The exact pinned NodeODM `/info` reported 2.2.4 / ODM 3.5.6; a 12-image public
reconstruction and a separate sealed Core→worker→real MinIO artifact digest round-trip both passed.
Commit `a215fbf` adds a strict private field-input manifest/auditor; its success is only `INPUT_READY`
and always leaves field acceptance `NOT_EVALUATED`. Commit `7fe2593` adds the opt-in live benchmark,
non-sensitive digest ledger and acceptance/phase synchronization. Neither commit was pushed.

Foreign technical benchmark `E2E-B01` is `BENCHMARK_PASS`: two official USGS same-area acquisitions,
24 preservation JPEGs each, ran with the exact profile in `529.02 s`; each produced seven mapped
artifacts including DSM/DTM/point cloud, and the distinct DSMs had `4,290,788` common finite cells.
The digest record is `CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`; owner-private storage retains the
source distributions, selection manifest and output archives. The `1.99291 m` mean delta is not an
accuracy/change/quantity result because this is foreign EPSG:32617 with approximate EXIF GNSS,
preservation derivatives and no common independent control/vertical/design contract.

`CIVIL_PROCESSING_V1_ACCEPTANCE.md` therefore remains `PARTIAL`, not a fabricated product PASS. The
foreign CRS was not relabeled and product quantitative comparison stays false. The remaining field
gate is an anonymized Korean LandXML, two same-site camera-original epochs and an independent reference
volume or checkpoints; until then results are operational relative quantities, not survey/settlement
evidence.

This work does not change physical-device facts. FIELD-0a remains `BLOCKED`; all five DJI capability
paths remain `NOT_VERIFIED`/OFF. It neither performs nor authorizes flight, motor/waypoint, camera/gimbal,
DPK, Pilot 2/Manifold automatic egress, remote deployment, release or remote push. On failure, disable
new profile issuance, LandXML conversion or comparison creation independently, preserve existing evidence
and never relax the compatibility gate.

---

## 2026-08-27 — No-USB FIELD evidence receiver ready; physical upload still gated

Commit `7d1aa88` adds a temporary, stdlib-only Tailnet receiver for owner-private FIELD-0a evidence.
It accepts only fixed Pilot import A/B/C, Pilot-export KMZ and M4D-original slots through an in-memory
capability URL. It rejects unsafe root/session ownership or modes, symlinks, unknown/oversized/chunked
input, path traversal, ambiguous/unsafe KMZ, duplicate slots and overwrites; accepted bytes are written
once with server-fixed names, no-follow semantics and mode 0600. It provides no log, download, listing,
external egress or DJI call and leaves the read-only JSBridge probe unchanged.

Current validation is green: Python `3976 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `413 source
files`; Dashboard `58 files / 529 tests`, ESLint, TypeScript and production build; A/B/C SHA-256,
lock, diff, repository hygiene and reference-import gates. The Dashboard now accurately says focal
length/resolution use M4D WideCamera original EXIF while sensor width is a 4/3 nominal value; the stale
camera risk is resolved without claiming calibrated intrinsics or survey-grade accuracy.

Formal FIELD-0a is still `BLOCKED`: historical A import/map and M4D EXIF are partial evidence, but
the canonical same-session Pilot import, Pilot-native export, M4D original and operator attestation
are not bound. The next physical gate is a fresh 0700 session, renewed propeller-removal confirmation,
and a real Pilot 2 file-picker upload attempt. File-picker success is not yet verified. Phase 3 and all
five DJI capabilities remain `BLOCKED`/`NOT_VERIFIED`/OFF; no license, component, Wayline/Media path,
flight, motor, mission execution, DPK or camera automation was performed.

---

## 2026-08-27 — Pilot 2 read-only JSBridge surface observed; capability unchanged

On real RC Plus 2/Pilot 2, with M4D propellers removed and no flight or motor action, the operator
opened the KSI read-only Open Platform probe from local commit `301c722`. Pilot 2 displayed the
JSBridge contact message and reported all six inspected bootstrap method names present:
`platformGetVersion`, `platformIsVerified`, `platformVerifyLicense`, `platformLoadComponent`,
`platformIsComponentLoaded` and `apiGetToken`.

The probe called no DJI function, read no identifier/token and sent no result. Its owner-private 0600
operator attestation digest is `9619c95404d10f19063ab3b8cc53b02d71bbc2402f6a637f75de4d4be1386010`;
raw screen evidence was not captured. The durable verdict is therefore `JSBRIDGE_SURFACE_OBSERVED`,
not Cloud API license or data-path verification. Phase 3 remains `BLOCKED`, every DJI capability
remains `NOT_VERIFIED`/OFF, and the next separate gate is DJI Cloud API license authentication.

---

## 2026-08-27 — Software closure ready; private FIELD-0a store prepared

Five local commits close the approved software scope: product authority/invariants (`2c7aee7`),
unbound Pilot-export FlightArtifact retention (`fd78d11`), Edge CaptureQuality plus derived
AnalysisReadiness and Dashboard (`2808c4e`), DJI documentation-vs-field capability evidence
(`9bd610d`), and assembly/hostile-input/FIELD attestation gates (`3bb55df`). The candidate API
never changes Mission Contract or dispatch, and `X-KSI-Executable: false` remains mandatory.
Analysis readiness only becomes `READY` from coverage, final quality, sealed/verified media,
capture time, temporal policy and processing lineage; it does not replace WorkOrder status.

The exact software gates passed: Python `3948 passed, 23 skipped, 3 xfailed`; Ruff; Mypy
`409 source files`; Dashboard Vitest `58 files / 529 tests`, ESLint, TypeScript, production build;
Playwright `58 passed, 14 skipped` across 390/768/1024/1440. Repository hygiene, lock and diff
checks pass. Raw FIELD evidence, M4D media, Pilot KMZ, screenshots, serial/GPS and secrets remain
untracked.

FIELD-0a is not a PASS and no device was touched. The user selected a simple owner-private local
store at `$HOME/.local/share/ksi-field-evidence`; the audit requires a 0700 canonical root and
direct-child session, 0600 raw files/attestation, current-user ownership and no symlinks. Use the
updated checklist to create the session and use the then-current `git rev-parse HEAD` as
`build_commit`. Until the audit binds real human-attested artifacts, FIELD-0a and Phase 3 remain
`BLOCKED`, and all five DJI capabilities remain `NOT_VERIFIED`; Phase 3B/DPK writes, motor/flight,
waypoint action, camera/gimbal automation and any capability promotion remain out of scope.

---

## 2026-08-26 — Dirty change set integrated into local main; no push

현재 변경분을 안전 경계와 추적성 기준으로 검토해 로컬 `main`에 기능별 커밋으로 통합했다.
Core/계약, capability별 DJI Gateway routing, evidence-first Operations Console, OIDC·합성 staging,
RC-first HIL 증거 도구, Sites 프로토타입, 제품/배포 문서, 저장소 위생과 이 handoff가 분리돼 있다.

원본 증거와 생성물은 커밋하지 않았다. `download/`의 DJI 비행 기록·M4D JPEG/MPO·압축본,
루트 `Testing/`, `.dev-data/`, raw HIL log, 실제 attestation/signing key와 secret은 ignored 상태다.
저장소 또는 원격에서 삭제하지 않았으므로 로컬 원본은 그대로 보존된다.

최종 검증:

- Python: `3864 passed, 23 skipped, 3 xfailed`; Ruff; Mypy `391 source files`.
- Dashboard: Vitest `58 files / 527 tests`, ESLint, TypeScript, production build, npm audit 0.
- Browser E2E: 로컬 OIDC/합성 원장 Playwright `54 passed, 14 intentional skipped`.
- Prototype: protected runtime 28-file integrity, production/Sites build, Sites `4 passed`,
  Playwright `22 passed`. 약 501 kB minified chunk 경고만 남으며 실패는 아니다.
- Integrity: `uv lock --check`, `git diff --check`, 비밀/대용량 후보 검토 통과.

이 결과는 software-only다. FIELD-0a와 Phase 3은 Pilot-export KMZ provenance와 승인된 물리
세션이 없어 계속 BLOCKED이며, DJI 다섯 capability는 모두 `NOT_VERIFIED`다. 원격 push,
release, tag, 외부 배포 변경, 장비 접촉/write와 비행은 수행하지 않았다.

---

## 2026-08-26 — Phase 3 software preflight complete, physical gate remains

장비 없이 가능한 FIELD-0a/Phase 3 사전검증을 자동화했다. 새 audit는 pinned A/B/C kit의
checksum·KMZ member·80 waypoint·80 촬영 action·40m 높이를 검사하고, Pilot import 화면과
M4D 원본의 digest/비민감 metadata를 private manifest에 기록한다. GPS와 serial은 출력하지 않으며
raw JPEG/MPO를 복사하지 않는다.

현재 로컬 증거를 적용한 결과 A-file map 표시와 M4D WideCamera 5280×3956, 12.29mm/24mm,
capture-time metadata는 확인됐다. M4D `.jpg`는 정상적인 두-frame MPO이므로 재인코딩하면 안 된다.
Pilot 2가 직접 export한 mapping KMZ와 회수 출처 증거는 없어서 `PILOT_EXPORT_KMZ_REQUIRED`다.

검증은 관련 FIELD/KMZ/capture-time 계약 `37 passed`, 전체 Python `3864 passed, 23 skipped,
3 xfailed`, Ruff, full Mypy `391 source files`, A/B/C 결정론적 byte 재생성 대조와
SQLite-required Manifold container CTest `7/7`을 통과했다.

따라서 FIELD-0a와 `phase-3-rc-first-hil`은 계속 BLOCKED다. byte 파일만 생겨도 출처 attestation
없이 자동 PASS하지 않는다. 다섯 capability는 모두 `NOT_VERIFIED`이며 장비 접촉, device write,
비행, 외부 배포, 고객 데이터, commit/push/release는 수행하지 않았다.

---

## 2026-08-25 — Phase 2 synthetic Cloud/AI staging accepted

Phase 2 software staging은 격리된 DGX Spark에서 PASS다. Console은
`https://dgx-spark-1.tailda9552.ts.net:10000`이며 Local Identity/Core/Object API는 각각
`:10001/:10002/:10003`이다. production Dashboard/Core의 OIDC, secure session, S3 public
presign, grounded Copilot 경계를 실제 실행했고 기존 Tailnet 개발 stack과 Serve route는 보존했다.

합성 원장은 실제 domain store 전이를 쓰며 한 현장만 AI opt-in이다. MinIO에는 SHA-256 digest가
연결된 PNG 실바이트가 있고 browser가 presigned GET으로 연다. 정상 답변은 `site_snapshot`의
same-site citation을 표시한다. AI 미동의, provider 503, 허위 cross-site citation은 모두
`BLOCKED`이며 AI가 Mission/승인/비행 명령을 만들 수 있는 도구는 없다.

`deploy/bin/phase2-staging.sh verify`는 journal/object/signing key의 SHA-256과 격리 restore를
통과했다. 최신 bundle은 ignored `.dev-data/phase2-synthetic-staging/backups/
ksi-vm-20260825T124618Z`이다. 운용은 `start|status|verify|stop|reset`; `stop`은 volume을 보존하고
`reset`만 Phase 2 전용 volume을 제거한다.

Phase 2 Chromium은 4개 viewport 12/12, 전체 external suite는 46 passed/22 intentional skipped다.
Dashboard 58 files/527 tests, lint/type/build/audit도 통과했다. 고객 Cloud/data, 실제 외부 AI/IdP,
full Python `3858 passed, 23 skipped, 3 xfailed`, Ruff, full Mypy `389 source files`, lock/diff
integrity도 통과했다. 고객 Cloud/data, 실제 외부 AI/IdP, public release, DJI/device/HIL,
commit/push/release는 수행하지 않았다. Phase 3 준비 체크리스트만 작성했으며 다섯 DJI
capability는 모두 `NOT_VERIFIED`다.

---

## 2026-08-25 — Phase 1 software UI/UX accepted

Operations Console Phase 1 software UI/UX baseline is now `PASS`. The final gap was closed with an
E2E-only realistic ledger seeded through the real Site, WorkArea, ObservationWorkOrder and Event stores
and their legal transitions. Five sites exercise setup, approval review, observation progress, result
review and completed states. A separate Local Identity account scopes an empty organization. The fixture
does not invent a Mission, processing job/result, report, spatial model, actual evidence bytes or any
DJI/HIL fact; evidence metadata with an unavailable preview is intentionally rendered as a recoverable
partial failure.

The visible refinements put Site `다음 행동` before `KSI 현장 브리핑`, remove repeated Home setup
instructions, and make Work/Items empty states a single responsive next-action surface. Populated E2E is
read-only after stack seeding and no longer mutates Core from browser tests.

Verification:

- Dashboard Vitest `58 files / 527 tests`; ESLint, TypeScript and Next production build pass.
- Chromium/Playwright `54 passed, 2 skipped` at 390/768/1024/1440. The two skips are intentional
  desktop exclusions for coarse-pointer-only touch targets. OIDC organization isolation, invalid-state
  recovery, populated/empty/preview-failure paths, keyboard/focus, overflow, reduced motion, axe and
  Home snapshots pass.
- Full Python `3848 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy `388 source files`.
- Authenticated in-app Browser review of the durable Tailnet Home, Sites, Work, Items and Site detail
  found no horizontal overflow or console warning/error. Site next action precedes AI briefing. The
  durable ledger's three current sites are empty/setup states; populated visual acceptance is the
  isolated E2E ledger above.

No device action, customer/external deployment, actual IdP, commit, push or release was performed.
`WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`, HIL and FIELD evidence
remain `NOT_VERIFIED`. `phase-2-synthetic-cloud-ai-staging` is the next planned delivery stage and was
not started by this handoff.

---

## 2026-08-24 — Phase 1 projection and truthfulness hardening

The current Console now distinguishes unknown/failed data from a real empty result. Core computes open
human-decision count for Site workspace and non-tombstoned `evidenceCount` for Event list/detail. The
Dashboard shows that evidence count in the review queue, presents briefing citations through an
allowlisted same-site route mapper, and leaves unrecognized source paths as text rather than arbitrary
links. Site briefing/report/change surfaces retain partial-failure recovery instead of inventing zeroes.

A follow-up non-browser audit removed a silent scale boundary: Core requests remain capped at 500 items,
but SiteWorkspace and the Home/Sites/Work/navigation/site-detail/review surfaces now paginate to the end
before reporting counts or queues. A later-page failure rejects the whole projection instead of rendering
the first page as complete. SiteWorkspace also forwards its explicit organization scope to EventStore,
closing request-context-free cross-organization counting. It now forwards that scope to ProcessingJobStore
as well; the store resolves each job through its authoritative Mission organization before selecting the
latest analysis or observation, while retaining the existing HTTP request scope as a second boundary.

Work queue grouping is now a tested pure projection and customer-facing acquisition copy consistently
uses `비행 임무`, `확인 항목`, and `현장 범위`; device IDs, raw receipts and manual recovery remain in
expert-only surfaces. Contracts/OpenAPI/Dashboard types and tests were updated together.

The canonical Phase 1 acceptance now includes pagination completeness and request-context-free
Event/ProcessingJob organization isolation. `PHASE_REGISTRY.yaml` was synchronized from its stale
intermediate `3842` and `54/511` counts to the current full evidence below.

The accessibility audit found that the acceptance text named keyboard/focus and coarse-pointer sizing,
but the executable E2E covered only Home axe and bottom navigation height. `RouteFocusManager` now moves
focus to `#main-content` after client pathname changes without moving scroll or stealing initial focus.
The four-width suite now runs touch CSS at 390/768, checks marked 44px controls, skip-link/route focus,
and axe on Home/Sites/Work/Review.

Verification: full Python `3845 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy `387 source files`;
Dashboard `55 files / 514 tests`, ESLint, TypeScript, production build; `uv lock --check`, full and
production-only Dashboard `npm audit` with `0 vulnerabilities`, and `git diff --check` pass. The active
Codex browser controller had no browser attached and its available-browser list was empty on the final
retry, so current-screen 390/768/1024/1440 visual/OIDC/axe evidence is still required and Phase 1 remains
`IN_PROGRESS`. No standalone Playwright substitution, device action, external deployment, customer data,
commit/push/release, or capability enablement occurred; all five DJI capabilities remain `NOT_VERIFIED`.

---

## 2026-08-24 — Operations Console Phase 0/1 baseline and responsive site/work UX

The product and delivery boundary is now explicit in ADR-KSI-027: first finish the evidence-first
Operations Console, then synthetic Cloud/AI staging, then RC-first HIL, verified integration and the
single-customer Field Pilot. `05_OPERATIONS_CONSOLE_PHASE_1_STANDARD.md` and
`OPERATIONS_CONSOLE_PHASE_1_ACCEPTANCE.md` turn that into an implementation/test checklist. They also
corrected the generated design-system files, which had unsuitable marketing/3D/newsletter guidance;
the active rule is the existing neutral, compact, evidence-first Console system.

The visible UX fixes are in `apps/dashboard/src/app/sites/page.tsx`, `/field/page.tsx`, and
`ResponsiveActionBoundary.tsx`. `/sites` now uses readable cards below 1280px (with actual 1024px
desktop actions inside cards), removing compact-width table clipping, raw Site ID, and detached World
CTA. The dense table remains at 1280px+. `/field` has a compact `작업 현황` summary and shorter
notebook-only guidance rather than a system-internals hero. `operations-console.spec.ts` adds a
four-width regression for the responsive list.

Verification completed on the live Tailnet development Console:

- Dashboard Vitest: `52 files / 505 tests`
- ESLint, TypeScript, Next production build: pass
- Playwright external Console: `20/20` at 390/768/1024/1440; navigation, compact/desktop site list,
  workspace areas, overflow, reduced motion and axe critical/serious checks pass
- `git diff --check`: pass

No device action, Cloud/customer-data deployment, commit, push, release, or capability enablement was
performed. All five DJI data-path capabilities remain `NOT_VERIFIED`; the next physical work is still
the separately approved read-only RC-first HIL session, not a UI test continuation.

---

## 2026-08-23 — Tailnet Auth.js callback cookie isolation and recovery UX

Tailnet Console의 `/api/auth/error?error=Configuration`은 Local Identity나 Core 인증 실패가 아니라
Auth.js의 `InvalidCheck: state value could not be parsed`였다. 쿠키는 port를 scope에 포함하지 않으므로,
같은 MagicDNS host의 다른 포트·이전 탭이 남긴 범용 `authjs.state`가 Console callback의 transient state를
덮을 수 있었다. `apps/dashboard/src/lib/auth/auth-cookie.ts`가 session뿐 아니라 callback URL, CSRF,
PKCE, state, nonce, WebAuthn challenge를 `ksi_auth_v1_*` namespace로 모두 분리한다. LOCAL은 HTTP
Tailnet 개발 때문에 secure=false를 유지하고 EXTERNAL_VM은 secure=true를 사용한다.

Auth.js error page도 `/login`으로 지정했다. 그래서 실제 KSI state가 만료·손상됐을 때는 generic
framework `Server error` 대신 “이전 로그인 요청을 검증하지 못했습니다”라는 복구 화면과 새 시작
동작을 보인다. 서비스는 21:59 KST에 재시작했고, 이미 열린 과거 `/authorize` 탭은 유효하지 않으므로
`http://dgx-spark-1.tailda9552.ts.net:3210/login`에서 새로 시작해야 한다.

검증: Dashboard unit `52 files / 505 tests`, ESLint, TypeScript, production build, local Chromium
4 widths `8 passed`, 그리고 실제 Tailnet에서 default development login 및 foreign `authjs.state`
주입 회귀 `2 passed`를 확인했다. deliberate invalid KSI state test는 로그에 `InvalidCheck`를 남기는
것이 정상이며, 브라우저는 `/login?error=Configuration` recovery page로 이동한다. 이 검증은
synthetic local identity/data만 사용했고 HIL/DJI capability에는 영향을 주지 않는다.

---

## 2026-08-23 — Local Identity restart recovery and daily-development login UX

Local Identity의 refresh grant가 process memory에만 있어 stack restart 뒤 Dashboard가
`/token 400 → /api/auth/refresh 401`을 내던 결함을 고쳤다. 새 grant는 bearer token 원문이
아닌 SHA-256 verifier·principal·scope·expiry만 owner-only atomic state file에 저장하며,
rotation·one-time replay 거부·재시작 뒤 refresh를 계약 테스트로 검증한다. short-lived
authorization code는 의도적으로 메모리에만 남겨 restart 뒤 새 PKCE authorization을 요구한다.

일상 개발 login은 LOCAL launcher가 명시한 `KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED=1`일 때만
allowlisted `local-admin` login hint로 바로 OIDC callback에 간다. Code+PKCE·state·HttpOnly
Dashboard session은 그대로다. RBAC는 Console의 접힌 `권한별 화면 테스트`에서만
`prompt=select_account`로 Local Identity selector를 연다. EXTERNAL_VM 또는 일반 local OIDC에
이 hint/selector는 전달되지 않으며, Local Identity opt-in은 external profile에서 fail-closed다.

만료 refresh가 발견되면 base 및 Auth.js chunk session cookie를 먼저 없애 재시도 loop를 막고,
LOCAL fixture에는 “개발 인증 서비스가 다시 시작되었거나 이전 세션이 만료”됐다는 정확한
복구 문구를 보인다. 21:20 KST에 Tailnet dev service를 재시작했으므로 그 이전 browser session은
한 번 재로그인이 필요하다. 새로 발급되는 grant는 이후 restart recovery 대상이다.

검증: issuer/OIDC/production-profile contract `32 passed`, targeted Ruff/Mypy, Dashboard
auth tests, typecheck, build, full Python `3841 passed, 23 skipped, 3 xfailed`, full Mypy
`387 source files`, Ruff, Dashboard `52 files / 503 tests`, ESLint와 `git diff --check` 통과.
Tailnet login HTML은 `개발 Operations Console 시작`과 접힌 `권한별 화면 테스트`를 렌더했고,
실제 Local Identity default request는 selector 없이 callback으로 `302`를 반환했다.

---

## 2026-08-23 — unblocked Console·AX·security work complete; physical acceptance remains gated

장비·고객 데이터·외부 Cloud 승인이 없어도 끝낼 수 있는 이번 범위는 마무리했다. Operations
Console의 현장 중심 IA·반응형 경계·저장형 현장 AI/브리핑 계약·OIDC 로컬 개발 흐름은 기존
실제 구현과 함께 회귀 검증했고, 이번 마무리에서는 조직 격리를 Event와 현장 하위 데이터까지
확장했다. 다른 조직의 Event·triage·evidence, 설계 기준면, 작업구역, worker pending queue,
device sequence는 동일한 `UNKNOWN`/404 또는 빈 결과로 처리한다. 사람 OIDC와 장치 자격은
계속 분리되어 있으며, 모델은 근거형 읽기 도구와 재관측 초안만 사용할 수 있고 Mission·승인·
비행 명령을 만들 수 없다.

Dashboard 지도는 보안 취약점이 있던 `georaster` 계열 대신 직접 `geotiff` overlay로 교체했다.
지원 CRS·raster 크기를 명시적으로 제한하고, 알 수 없거나 회전된 GeoTIFF는 fail-closed 한다.
현재 `npm audit`와 production-only audit은 모두 0 vulnerabilities다. 검증은 전체 Python
`3839 passed, 23 skipped, 3 xfailed`, Ruff, full Mypy `387 source files`, Dashboard
`52 files / 500 tests`·ESLint·TypeScript·production build, Chromium/Playwright `16 passed`,
Manifold native CTest `4/4`, PSDK logic CTest `2/2`, `git diff --check`까지 통과했다.

실증 시작 패키지도 만들었다. private ignored session
`hil_raw_logs/SESS-20260823T103223Z-PENDING-SN`의 read-only preflight는 host `enP7s7`
`172.30.1.43/24`에서 target `172.30.1.33`의 ARP neighbour 없음·ping 3/3 loss를 기록했다.
따라서 Manifold는 `MANIFOLD_UNREACHABLE`이고 실제 adapter/feature flag는 켜지지 않았다.
별도 RC-first capability session
`hil_raw_logs/CONNECTED-20260823T103253Z-PENDING-AIRCRAFT`에는 Wi-Fi·SIM 없음 기본 profile과
다섯 capability의 `NOT_VERIFIED` 상태만 들어 있다. 이 증거는 장비를 수정하거나 SSH·DPK·
credential·camera·flight 호출을 하지 않았다.

다음 실제 관문은 (1) Manifold를 물리적으로 reachable하게 만든 뒤 지상 read-only HIL,
(2) Pilot 2 A/B/C import 및 Pilot-export mapping KMZ와 실제 M4D EXIF/XMP로 FIELD-0a 닫기,
(3) 승인된 외부 IdP·Cloud provider·DNS/ACME·backup restore rehearsal이다. 이 전에는
`WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD` 모두
`NOT_VERIFIED`이며 고객 데이터, 외부 배포, commit/push/release는 수행하지 않았다.

---

# Current Handoff (2026-08-22, persistent Tailnet development access)

원격 SSH와 무관하게 Operations Console이 계속 실행되도록 Tailnet 개발 경로를 기본값으로
전환했다. 접속 주소는 `http://dgx-spark-1.tailda9552.ts.net:3210/login`이며, 로그인 버튼은
같은 Tailnet node의 합성 Identity `:9010`으로 이동한다. 전체 Authorization Code + PKCE 왕복,
Core whoami/Site 조회와 Home 복귀를 실제 Tailnet 경로로 확인했다. Next asset 18개와 HMR
WebSocket도 통과해 HTML만 보이고 interaction이 깨지는 과거 external-origin 문제를 막았다.

Dashboard·Identity·Core는 각각 `127.0.0.1:3210/9010/8012`에만 bind한다. Tailscale Serve가
3210/9010만 Tailnet에 proxy하며 기존 port 80→3100 설정은 보존했다. `npm run dev`는 Tailscale
Running/Online과 MagicDNS를 요구하고, `npm run dev:local`만 명시적인 localhost rollback이다.
Tailnet HTTPS는 계정-level enablement가 필요해 현재는 WireGuard-encrypted Tailnet HTTP를 쓴다;
production HTTPS/OIDC 정책에는 영향이 없다.

`deploy/systemd/ksi-operations-console-dev.service`를 user systemd에 link·enable·start했다.
`Linger=yes`, `Restart=on-failure`이므로 SSH 연결이 끊겨도 유지되고 재부팅 뒤 자동 시작한다.
상태/로그는 `systemctl --user status ksi-operations-console-dev.service`와
`journalctl --user -u ksi-operations-console-dev.service -f`로 본다. source는 hot reload되므로
두 번째 `npm run dev`를 띄우지 않는다.

검증은 local issuer `5 passed`, dev/VM/production closure `64 passed`, Dashboard
`49 files / 484 tests`·TypeScript·ESLint·Next build, focused Mypy/Ruff, remote OIDC/assets/HMR,
`git diff --check`를 통과했다. 합성 데이터만 사용했고 public Funnel, LAN bind, 장비, 고객 데이터,
commit/push/release는 수행하지 않았다. DJI capability는 계속 `NOT_VERIFIED`다.

---

# Current Handoff (2026-08-22, Operations Console U0)

FIELD-0a 이전에 허용된 P0 UX 결함을 닫았다. Dashboard의 새 `OperatorNextAction`은 기존
Site·Event·WorkOrder·Acquisition 사실만 읽어 지금 해야 할 행동 하나를 정한다. Home 상단,
portfolio, `/field` 빈 상태, 현장 목록과 Site 상세가 이 결정을 공유하므로, 현재 합성 Site처럼
AOI가 없을 때 어느 화면에서도 조사나 Mission으로 건너뛰지 않고 `AOI 설정하기`로 이동한다.
AOI section에는 hash deep link를 연결했고 저장 뒤에만 베이스라인 조사 계획이 다음 단계가 된다.

Event가 0건이면 “이벤트를 선택하세요” 패널을 렌더하지 않고 `검토할 이벤트가 없습니다`라는
단일 상태만 보인다. 390/768px에서는 write 행동 링크가 없고 `노트북에서 계속` 안내가 나오며,
1024/1440px에서는 권한 있는 같은 CTA가 열린다. 기존 Core RBAC와 조직 검사는 바뀌지 않았다.

검증은 Dashboard `49 files / 484 tests`, TypeScript, ESLint, Next build, 실제 Chromium
390/768/1024/1440 및 가로 overflow 없음, full Python `3819 passed, 23 skipped, 3 xfailed`,
Ruff, full Mypy `383 source files`, native non-SQLite CTest `7/7`을 통과했다. 실행 중 Local OIDC가
만드는 `.next-local-oidc`는 생성물로 명시해 lint/Git 대상에서 제외했다. 호스트에 SQLite3 개발
패키지가 없어 native WAL backend는 이번 CTest에서 비활성 상태였으며 별도 환경 개선 gate다.

현재 로컬 Operations Console은 `http://localhost:3210/`에서 합성 OIDC 관리자 세션으로 열어
두었다. 다음 제품 단계는 코드 추가가 아니라 FIELD-0a의 Pilot 2 A/B/C import와 export KMZ
실증이다. 이를 닫기 전에는 최종 6개 메뉴 IA나 새 제품 기능을 구현하지 않는다. 이후에만
작업 중심 IA → 합성 public Staging → RC 기본형 다섯 capability HIL → FIELD-1/2 순으로 간다.

`WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`은 모두
`NOT_VERIFIED`다. 장비/DPK write, credential, 비행, 고객 데이터, 외부 배포, commit/push/release는
수행하지 않았다.

---

# Current Handoff (2026-08-21, production-equivalent local OIDC development)

기본 로컬 Dashboard 개발은 더 이상 Bearer 토큰을 붙여넣는 별도 UX가 아니다.
`apps/dashboard`에서 `npm run dev`를 실행하면 loopback 전용 KSI Local Identity, OIDC 모드
Core, Operations Console이 함께 뜬다. `http://localhost:3210/login`에서 “조직 계정으로 로그인”을
누른 뒤 합성 개발 계정을 고르면 Auth.js Authorization Code + PKCE, 서명 JWT/JWKS, Core role/org
claim 검증을 실제로 지나 `/field`로 돌아온다. 실제 browser에서도 `KSI 개발 관리자` 선택 뒤
`local-admin` Console 진입을 확인했다.

Core DB/journal은 `.dev-data/local-oidc-core`, local issuer RSA key와 Dashboard client/session secret은
`.dev-data/local-identity`에 durable하게 남고 Git에서 제외된다. 따라서 재시작 후에도 같은 실제
개발 데이터에서 Dashboard/Core 흐름을 점검할 수 있다. Local Identity는 loopback 밖 issuer/bind를
거부하고 합성 계정만 제공한다. VM compose, Dashboard production image와 launcher에는 이를 넣지
않았으며 external VM은 기존대로 HTTPS OIDC와 file secret 없이는 기동하지 않는다.

Gateway·Edge·processing worker의 opaque 자격은 사람 로그인과 섞지 않는다. 구형 diagnostic만
LOCAL에서 `KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED=1`을 명시해야 열리며, 기본 개발과
EXTERNAL_VM에는 Bearer 입력이 없다. `dev:dashboard`는 Core/OIDC 환경을 수동으로 준 특수 조사
경로다.

## 검증과 남은 경계

Local issuer/Core/VM focused contract는 `79 passed`, 전체 Python은 `3819 passed, 23 skipped,
3 xfailed`, full Mypy는 `383 source files`, Dashboard는 `47 files / 465 tests`·ESLint·production
build, Node syntax와 `git diff --check`를 통과했다. 실장비/DPK write, credential 입력, 비행,
customer data, public deployment, commit/push/release는 수행하지 않았다. 모든 DJI capability와
FIELD/HIL은 `NOT_VERIFIED`다.

---

# Previous Handoff (2026-08-21, Operations Console + external VM readiness)

KSI 업무 화면을 별도 모바일 제품으로 나누지 않고 하나의 반응형 `KSI Operations Console`로
전환했다. `/field` bookmark는 유지되지만 일반 Dashboard shell의 오늘 작업 큐이며, RC Plus 2와
Pilot 2에는 KSI 업무 UI나 `window.djiBridge` 의존 기능이 없다. 1024px 미만에서는 읽기·event
triage·분석 검토·Copilot·보고서만 허용하고, 승인·Mission·장비 전이·원본/복구 행동은 이유와
“노트북에서 계속” 안내를 보인다. 화면 폭은 보안 신원이 아니며 Core RBAC를 우회하지 않는다.

사람 인증은 Auth.js custom OIDC Authorization Code + PKCE와 암호화 HttpOnly server session으로
분리했다. 브라우저 session API는 404이고 access/refresh token은 서버 BFF만 사용한다. Core는
signature, issuer, audience, exp/nbf, algorithm, kid와 KSI principal/org/role claims를 검증하며
unknown kid 1회 갱신과 만료 cache+issuer 장애 fail-closed를 구현했다. 사람 OIDC와 Gateway/Edge/
worker opaque 자격은 동일 Bearer 표면에서 신원 종류별로 분리된다.

외부 배포는 기존 local compose를 건드리지 않는 `compose.vm.yaml`이다. non-root Dashboard,
Caddy TLS ingress, file-mounted secrets와 public presigned object endpoint를 추가하고 외부 publish는
80/443만 남긴다. production image는 외부 VM OIDC/TLS/secret 입력이 빠지면 Next 시작 전에 exit 1
하며, 비활성 HIL 경로와 browser session 표면은 실제 HTTP 404다. 백업은 journal/object/signing
key를 digest와 함께 봉인하고, 합성 전용 smoke가 격리 볼륨 restore까지 실제 통과했다.

검증은 full Python `3812 passed, 23 skipped, 3 xfailed`, 마지막 변경 focused `66 passed`, Ruff,
full Mypy `381 source files`, Dashboard `46 files / 463 tests`·ESLint·Next build, 390/768/1024/1440
실제 Chromium action/overflow/console 검증, SQLite-required arm64 Manifold CTest `7/7`, compose port
exposure, Caddy validation, Dashboard image build/startup failure와 synthetic backup/restore를 통과했다.

## 다음 release 전 단계

1. Cloud Provider Due Diligence와 기존 legacy Site/Mission/Artifact 조직 migration을 승인한다.
2. 선택한 외부 IdP test tenant에서 실제 login/logout/refresh failure와 조직 404를 브라우저로 닫는다.
3. 선택한 VM에서 DNS/ACME, 실제 secret manager, 백업 보관소와 새 VM restore rehearsal을 수행한다.
4. 기존 npm production audit(critical 0/high 9/moderate 2/low 5)의 georaster/webpack 4 및 Next
   dependency 계보를 호환성 검증과 함께 해소하거나 명시적으로 보안 승인한다.
5. 그 뒤에만 개발·합성 배포에서 pilot 조직으로 전환한다. 고객 데이터는 법무·보안 승인 전 금지다.

실제 IdP·공개 TLS/ACME·고객 데이터 배포와 장비/HIL은 완료로 주장하지 않는다.
`WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`은 모두
`NOT_VERIFIED`다. 기존 Pilot 2 수동 KMZ, SD/USB, folder ingest와 local compose rollback은 남아
있다. 장비/DPK write, credential 입력, 비행, production 변경, commit/push/tag/release는 수행하지
않았고 `Testing/`, `download/`를 보존했다.

---

# Current Handoff (2026-08-21, KSI Cloud Coordination Foundation)

장비가 없어도 개발할 수 있는 Cloud coordination 범위를 구현했다. `cloud/` 폴더를
새로 만들지 않고 `apps + services + deploy`를 KSI Cloud로 문서화했으며, production
환경변수와 `deploy/.env.example`의 drift를 계약 테스트로 막았다. 실제 adapter가 정해지기
전에는 DJI Gateway container나 가짜 장비 runtime을 만들지 않는다.

Core에는 WorkOrder 승인 회차별 내구성 있는 `AcquisitionRun`과 진행 projection을 추가했다.
승인 재시도는 같은 run을 반환하고 coordinator 실패가 사람 승인을 되돌리지 않는다.
Mission Plan의 선택적 `workOrderId`는 조직·Site·승인 상태를 검증하고 Mission record,
WorkOrder `missionIds`, exact cycle run을 멱등 연결한다. `GATEWAY_DEVICE` 전용 operation
receipt API는 다섯 capability를 독립 기록하며 device/profile/org/Site/Mission binding,
receipt nonce, transport-neutral idempotency key와 digest 충돌을 fail-closed 검증한다.

Dashboard WorkOrder 상세는 `지금 할 일 → Acquisition progress → 장비·연결 상세 → 전문가
복구 정보` 순서다. Edge activation 전에는 “비행 준비 완료”를 쓰지 않으며, 활성 계약 뒤
인터넷 단절은 경고로만 표시하고 자동 중단을 주장하지 않는다. readiness가 성립하면 기존
Mission Wizard를 `workOrderId`와 함께 열고, Pilot 2 비행 화면을 대체하지 않는다.

독립 rollback은 `KSI_CORE_ACQUISITION_COORDINATION_ENABLED`; 신규 Mission issue gate는
여전히 `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false`가 기본이고 Mission Contract writer는
`1.2`다. 기존 Gateway facade/v1.2 reader, Pilot 2 수동 KMZ와 ground ingest는 유지했다.

검증은 full Python `3782 passed, 23 skipped, 3 xfailed`, Ruff, full Mypy `378 source files`,
Dashboard `44 files / 440 tests`·ESLint·Next build, 실제 Chromium WorkOrder/progress/Wizard
렌더링과 빈 console, SQLite-required Manifold CTest `4/4`, PSDK logic CTest `2/2`,
`git diff --check`를 통과했다. 첫 full run에서 새 receipt 라우트의 hostile-input 조사 누락
1건을 찾았고 6종 적대적 JSON 직접 발사 회귀를 추가한 뒤 clean full run을 다시 통과했다.
독립 acceptance review는 software-foundation 범위를 `Approved`(must-fix 0), 실제 DJI/HIL/
provider adoption을 `Blocked`로 판정했다.

## 다음 안전 단계

장비가 연결되면 비행 없이 지상에서 `M4D + Manifold 3 + RC Plus 2 + RC Wi-Fi`, Manifold
SIM 없음 조합으로 `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`,
`MEDIA_UPLOAD`을 각각 검증한다. 성공한 capability의 실제 adapter와 flag만 추가한다.
Cloud 하향이 실패하면 preflight contract Bridge만, media 회수가 실패하면 postflight Bridge만
검토하며 Virtual Stick·이륙·경로·짐벌 제어는 넣지 않는다.

최신 read-only 재탐지도 `172.30.1.33` ARP `FAILED`, ping 100% 손실이다. 따라서 모든 DJI
capability는 계속 `NOT_VERIFIED`이고 RC/Dock/MSDK/direct adapter는 구현·활성화하지 않았다.
장비/DPK write, credential, 비행, 외부 upload, production 변경, commit/push/tag/release는
수행하지 않았다. 사용자 소유 가능성이 있는 `Testing/`, `download/`와 concurrent 변경은
보존했다.

---

# Previous Handoff (2026-08-21, RC-first Connected Edge foundation)

KSI의 소스 구조를 장비별 복제가 아니라 **제품 책임별 context + 장비 adapter**로
확정하고 실제 코드에 반영했다. 선택지는 `RC/Manifold/Dock` 최상위 분리, 단일 거대
Integration 서비스, polyrepo, 책임별 context를 비교했다. 현재 팀과 계약 변경 빈도에는
monorepo의 책임별 context가 가장 안전하며, 독립 배포 주기·팀·접근권한이 실제로 갈릴
때만 polyrepo를 재검토한다. 정본은 `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md`와
`docs/architecture/ADR-KSI-023-rc-first-connected-edge.md`다.

구현된 기반은 다음과 같다.

- Core `acquisition/`: Site별 deployment profile, 짧은 TTL connectivity snapshot,
  capability별 readiness, 조직/site/device scope와 replay 방어.
- Core 발급 gate: rollout flag가 켜진 배포에서만 새 Mission 발급을 강제 차단한다.
  flag는 HIL과 profile migration 전 기본 OFF이며 활성 계약 지속 정책은 별도다.
- DJI Gateway: `domain/ports/routing/persistence` 분리, 다섯 capability의 독립 route,
  journal v1.2 dual-reader와 v1.3 명시 receipt. `gateway.py`는 호환 facade다.
- Dashboard: RC 인터넷, Manifold, 직접망 Add-on, 계약 동기화, 원본 동기화를 각각
  보여 주며 “연결됨” 한 상태로 합치지 않는다.
- HIL v1.3: 기능마다 독립 evidence를 요구하고 v1.2 provider 판정에서 capability를
  추론하지 않는다. 모든 기능은 실제 증거 전 `NOT_VERIFIED`다.

최종 검증은 full Python `3759 passed, 23 skipped, 3 xfailed`, Ruff, full Mypy
`374 source files`, lock check, Dashboard `42 files / 433 tests`·ESLint·Next build,
실제 Chromium production UI/console, SQLite-required Manifold CTest `4/4`, PSDK logic
CTest `2/2`, diff check를 통과했다. 첫 전체 실행에서 드러난 assembly/hostile-input/
기존 수동 Mission 회귀 13개는 rollout gate 분리와 fixture/contract mirror 보완 후
최종 전체 실행에서 해소됐다.

## 다음 마일스톤

1. `M4D + Manifold 3 + RC Plus 2 + RC Wi-Fi`, Manifold SIM 없음으로 다섯 capability를
   각각 HIL한다. 헤더나 문서만으로 `VERIFIED` 처리하지 않는다.
2. Cloud 하향 전달이 실패하면 preflight Mission Contract용 MSDK/MOP Bridge만,
   media 회수가 실패하면 postflight Bridge만 구현한다. 비행 API는 넣지 않는다.
3. 통과한 adapter만 기능별 flag로 켠 뒤 WorkOrder 승인→wayline/contract→activation
   receipt→media completeness→Processing coordinator를 연결한다.
4. FIELD-0b/1/2를 닫은 다음 Connectivity Add-on과 Dock adapter를 순서대로 연다.

현재 소프트웨어 구조 완료는 실장비 연결 완료가 아니다. `WAYLINE_DELIVERY`,
`EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`은 모두 실제 조합에서
`NOT_VERIFIED`이며, Dock/MSDK/direct adapter도 아직 구현하지 않았다. 기존 Pilot 2 수동
KMZ, SD/USB, folder ingest는 복구 경로로 남아 있다. 비행·장비 write·credential·외부
upload·commit/push/tag/release는 수행하지 않았다. 사용자 소유일 수 있는 `Testing/`,
`download/`와 기존 concurrent 변경은 건드리지 않았다.

---

# Current Handoff (2026-08-20, MVP Integration Milestone 1)

이전 CLI의 다음 단계였던 provider 실증을 시작했다. 공식 DJI 문서와 vendored PSDK header를
대조한 결과, Manifold 3 PSDK camera media list/download 표면은 문서화돼 있지만 KSI 장비에서
아직 통과하지 않았다. 최신 Cloud API 공식 지원표는 M4D/M4TD를 Dock 3에만 두고 RC Plus 2 +
Pilot 2에는 M4E/M4T만 열거하므로 standalone M4D Cloud track은 우회 실험하지 않고 공식 matrix
blocker로 닫았다.

acceptance schema를 v1.2로 강화했다. check별 필수 assertion/operator attestation과 raw artifact
SHA-256/size를 가진 서로 다른 PASS envelope, 실제 aircraft SN, 종료시각, digest provider decision
record 없이는 VERIFIED/selection이 불가능하다. `attest-check`, `record-check`, `record-blocker`,
`select-provider`가 JSON 수동 편집을 없애며 stage/path/symlink/owner/mode/secret/동시 갱신을
fail-closed 검증한다. CLI `preflight`는 RFC1918 read-only host 증거만 수집하고 이미
READY/VERIFIED/채택된 세션은 변경하지 않으며 다른 구체 blocker도 덮어쓰지 않는다. 현재 M1
`36 passed`, M1 + Gateway `40 passed`, full Python `3722 passed, 23 skipped, 3 xfailed`,
Ruff/format, full Mypy `357 source files`, 실제 v1.1→v1.2 upgrade/verify가 PASS다. 독립 v1.2
review는 acceptance-kit/security scope를 `Approved`(tracked must-fix 0), 실제 provider adoption을
`Blocked`로 판정했다.

## 현재 blocker와 다음 안전 단계

- `hil_raw_logs/SESS-20260820T134204Z-PENDING-SN/`에 0700/0600 actual session을 만들었다.
- 최신 2026-08-20T14:34:24Z `172.30.1.33` preflight도 ARP `FAILED`, ICMP 3/3 손실로 실패해
  PSDK는 `MANIFOLD_UNREACHABLE`,
  aircraft link는 `UNKNOWN`이다. host USB 부재는 Manifold 내부 USB bulk blocker가 아니다.
- 장비가 다시 연결되면 먼저 read-only identity/app-framework/aircraft-link preflight를 수행한다.
- 그 뒤 PSDK media list와 사용자가 지정한 지상 원본 JPEG 한 장의
  download/hash/upload/lineage/rights-release를 검증한다. Cloud는 공식 지원 조합이 바뀌거나
  DJI의 서면 확인을 받기 전까지 다시 열지 않는다.
- 현장 capture/비행, downloader-rights 획득, DPK 설치, credential 입력, 외부 업로드는 각각
  필요한 시점에 사용자 승인과 보안 경계를 확인한 뒤 수행한다.
- 한 track의 모든 check와 실제 evidence가 통과하기 전에는 provider code를 조립하거나 feature
  flag를 켜지 않는다. 수동 Pilot 2 KMZ/folder ingest는 복구 경로로 유지한다.

Git은 기존 local `main` checkpoint `434b92b` 위에 이번 변경이 미커밋 상태다. 사용자 소유일 수
있는 `.ai/audits/2026-08-19-codex-config-audit.md`, `Testing/`, `download/`는 건드리지 않았다.
특히 untracked `Testing/`과 `download/`는 원본 사진·flight record·GPS 가능 raw 자료로 취급해
이번 delivery와 향후 staging에서 명시적으로 제외해야 한다. commit/push/tag/release,
production/device write는 수행하지 않았다.

주의: 읽기 전용으로 지시한 보조 에이전트가 `apps/dashboard/src/app/page.tsx`와
`apps/dashboard/src/app/field/page.tsx`를 수정했다. main Codex는 이를 되돌리거나 추가 수정하지
않고 별도 concurrent UI 변경으로 보존했다. provider acceptance diff와 섞어 해석하지 말 것.

---

# Previous Handoff (2026-08-20, closed-loop MVP)

KSI의 제품 축을 `DJI waypoint 자체 구현`에서 `반복 관측 데이터를
변화·공정·상대 물량으로 바꾸고, 근거형 Copilot으로 설명하며, 사람이
재관측을 승인하는 폐루프`로 고정했다. ADR-KSI-022와 PRD/ledger/
invariant/traceability를 이 결정에 맞춰다.

소프트웨어로는 조직 범위 Observation Work Order 원장, 반복 일정,
사람 승인 재관측 초안, provider-neutral DJI Gateway, 서명 Capture Policy
범위의 native 품질 행동 허용기, typed-tool/citation Copilot, 5단계 `오늘
작업` Dashboard를 추가했다. OpenAPI 1.24는 실구현 경로·요청·응답과
다시 맞춄다.

## 엄격한 완료 경계

- Software foundation: implemented and locally tested.
- Concrete DJI Cloud/PSDK/MSDK provider: not implemented; capability remains `NOT_VERIFIED`.
- Automatic wayline/media round trip: not HIL/field proven; normal UX target is not yet operational.
- Production Copilot: orchestration exists, but no production model or deterministic query backend is configured.
- Tenant safety: new WorkOrder/Copilot surface is organization-scoped. Legacy Site/Mission/Artifact stores
  still need a migration before multi-tenant release, so INV-060 is only partially implemented.
- WorkOrder-to-Mission automatic coordinator and live Capture Policy-to-PSDK execution are not wired.
- FIELD-0a residual, FIELD-0b/1/2, device keys, DPK, media transfer and flight remain separate blockers.

## Verification

- Python: `3686 passed, 23 skipped, 3 xfailed` (`ulimit -n 8192`).
- Ruff and full Mypy: pass (`355 source files`).
- Dashboard: `41 files / 431 tests`, ESLint, TypeScript, Next production build pass.
- Native SQLite/WAL and capture policy: CTest `7/7` pass in the pinned arm64 container.
- OpenAPI sync, hostile-input route coverage, `uv lock --check`, repository hygiene,
  reference/third-party pins, KMZ SHA-256, staged secret-pattern scan and diff check: pass.
- Independent acceptance: `Approved`, remaining must-fix `0`. The first review found and the
  implementation closed Viewer-to-Copilot-draft write authorization and unknown-site list
  200/404 contract drift before this handoff.

## 배포 순서

1. 기존 단일 tenant 원장에 organization migration·rollback·backfill 검증을 먼저 한다.
2. 실장비에서 Cloud 5항목을 검증하고, 불가능하면 PSDK media를 검증한다.
3. 증거를 통과한 adapter 하나만 켜고 WorkOrder→Mission→Gateway→Media를 조립한다.
4. 서버 Intelligence query backend과 site egress policy 후 Copilot model provider를 켠다.
5. HIL·FIELD KPI가 세워진 뒤에만 Manifold active capture를 순차적으로 켠다.

수동 Pilot 2 KMZ·folder ingest는 복구 경로로 보존했다. 사용자가 다음 세션
연속성을 위한 로컬 `main` 체크포인트 커밋을 승인했다. 푸시·태그·릴리스·
프로덕션/장비 write는 수행하지 않았다.

## Next session start

다음 세션은 `main`의 이 핸드오프와 ADR-KSI-022를 읽고 **MVP Integration
Milestone 1**만 진행한다. 목표는 구체 provider를 추측해 만드는 것이 아니라,
실장비 Cloud 5항목과 PSDK media 경로의 capability evidence를 수집해 하나의
adapter 경로를 채택하는 것이다. 장비 접근·자격증명·비밀키·빌링·폄웨어
변경은 사용자의 명시적 현장 지시 없이 실행하지 않는다.

복사해 쓸 시작 요청:

> `main`의 `docs/architecture/ADR-KSI-022-closed-loop-product-and-zero-touch-field-ux.md`,
> `.ai/goal.md`, `.ai/plan.md`, `.ai/task-state.md`, `.ai/handoff.md`를 읽어라.
> 이번 세션은 MVP Integration Milestone 1로 한정한다. 먼저 실장비에서
> DJI Cloud/Pilot-to-Cloud 5항목과 PSDK camera-media 경로를 재탐지하고,
> 증명된 경로 하나만 채택한다. 추측으로 capability를 VERIFIED로 올리지
> 말고, WorkOrder→Mission→Gateway→Media 조립 계획과 HIL 증거를 같이 남겨라.
> 기존 수동 Pilot 2/KMZ/folder ingest는 복구 경로로 보존하고 비행·장비
> write, 자격증명, commit/push/release는 해당 세션의 명시 승인 경계를 따라라.

---

# Previous Handoff (2026-08-20)

세 소프트웨어 안전 범위를 구현했다. 첫째, CRITICAL RiskField evidence는 채널의
`deviceBound`와 별개로 artifact Ed25519 서명을 검증하고, 활성 dispatch의 mission/device/
risk-policy/calibration과 기존 geometry/time/entity/uncertainty lineage가 모두 맞아야 한다.
공개키 registry는 운영자 파일 프로비저닝 전용이며 등록 API가 없다. Manifold 개인키는
외부 owner-only 0600 파일에서만 읽고 target-static OpenSSL을 사용한다. PSDK 앱은 journal
replay와 상시 Core sync 경로를 실제 실행 조립에 연결한다.

둘째, Mission Contract v1.3은 server-issued `issuance={issuerId,siteSequence,issuedAt}`와
durable per-site/issuer high-water를 가진다. v1.2/v1.3 dual-reader는 gap을 허용하되 낮은
sequence, equal-sequence 변조, v1.3 이후 v1.2 downgrade를 거부한다. 운영 writer 기본값은
안전한 staged rollout을 위해 계속 v1.2다.

셋째, 워커는 사진마다 고정 우선순위로 capture time을 측정하고 Core는 파일 상태와 번들
window를 원장에 기록한다. 성공 ProcessingJob은 그 window를 불변 스냅샷으로 보유한다.
공간모델 freshness는 오직 `capturedTo`를 쓰며 incomplete/conflict에서 `registeredAt`으로
대체하지 않는다. 단일 site 응답은 비-null spatial summary를 포함하고 Dashboard는 그
응답을 직접 쓴다. 기존 `/spatial-model`은 유지된다.

## Verification status

- 최종 full Python: `3635 passed, 23 skipped, 3 xfailed` (FD limit 8192).
- Ruff, full Mypy `345 source files`, `uv lock --check`, API/contract/hygiene/reference guards,
  KMZ 12 tests 및 A/B/C SHA-256 모두 통과.
- Dashboard: `39 files / 419 tests`, ESLint, TypeScript/Next production build 통과.
- Native: SQLite/WAL CTest `6/6`; static OpenSSL attestation CTest `6/6`와 target binary의
  dynamic `libcrypto` 부재 확인; PSDK logic CTest `2/2` 통과.
- 첫 full run에서 나온 12개 assembly/fixture/contract-mirror 회귀는 수정 후 최종 full
  run에서 모두 해소됐다.
- Independent acceptance follow-up: `Approved`, no must-fix items, software handoff scope only.
  `mission-contract-no-issuance-ordering-field` was resolved through the official goal-ledger helper;
  HIL/device-signature and sensor-truth residual risks were intentionally not closed.

## Rollout and rollback

1. v1.3 dual-reader와 durable high-water를 먼저 배포하고 writer는 v1.2로 둔다.
2. 실제 장비 키를 외부 보안 경로에 프로비저닝한 뒤 FIELD-0b에서 signed upload,
   DPK/USB/network/frame-telemetry 및 v1.3 rollback 거부를 검증한다.
3. HIL 통과 후에만 Core v1.3 writer를 활성화한다. 기록된 high-water와 attested evidence는
   v1.2/unsigned 상태로 강등하지 않는다.

## Field and release blockers

- FIELD-0a는 A KMZ import/map rendering과 원본 M4D WideCamera JPEG metadata를 증명했다.
  5280×3956·12.29mm·24mm equivalent·explicit DJI XMP UTC를 확인해 Dashboard shared focal
  length를 12.0mm→12.29mm로 교정했다(focused Dashboard 7 tests/lint/build pass). 원본은
  사용자 untracked `download/drone pictures/`에만 있고 이동·커밋하지 않았다. Pilot-exported
  mapping KMZ와 그 회수 증거가 없어 전체는 여전히 `in_progress`다. 운영자는 이 Pilot-export
  비교를 `kmz-real-device-acceptance-still-unverified` 수용 리스크로 기록해 FIELD-0b 준비를
  진행하기로 했지만, 이것은 formal FIELD-0a 완료나 비행 수용을 뜻하지 않는다.
- FIELD-0b/1/2, 실제 Manifold 서명 키, DPK/USB/frame-telemetry, 실사진 NodeODM 종단,
  2회차 re-observation lineage는 NOT_VERIFIED다.
- 현재 FIELD-0b LAN preflight(2026-08-20T09:38:12Z): PC 유선 `enP7s7`은 1 Gbit/s link-up이나
  `172.30.1.33`은 ARP `INCOMPLETE`, SSH `No route to host`였다. 이는 Manifold/기체 능력 실패
  판정이 아니며, USB probe·DPK install/start·키 provision은 수행하지 않았다.
- 정적 OpenSSL은 배포 전 license/SBOM/third-party notice evidence가 필요하다.
- Core DTM→WPML은 FIELD-2와 ceiling-reference 결정을 통과한 FIELD-3 전에는 시작하지 않는다.
- `download/`와 `Testing/`은 사용자 원본일 수 있어 이동/삭제하지 않았고 전달·커밋 대상이
  아니다. Git commit/push/tag/release, 프로덕션 배포, device write는 수행하지 않았다.

---

# Historical Handoff

## Outcome

The software safety gates are implemented and locally verified. Field readiness is **not** claimed.
IFC mm georeference is fixed and its high-risk ledger item is resolved. Mission Contract activation
and CRITICAL RiskField consumption are fail-closed in software, while their hardware/generation risks
remain open under their original resolve conditions. The consumer also rejects untrusted state
directories (symlink, wrong owner, or any group/other permission) before writing or loading active
contracts.

The IFC meter contract now covers three distinct georeference cases: an explicit map unit, the IFC4.3
project-unit fallback when a present target CRS omits `MapUnit`, and scale-free `IfcRigidOperation`.
A coordinate operation whose `TargetCRS` itself is missing remains a compatibility-only half-set; its
unit cannot be proven from the CRS and must not be advertised as verified georeferencing.

## Remaining blockers

1. Restore network/device access to `ksi-manifold`. The latest read-only retry at
   `2026-08-20T09:38:12Z` returned `No route to host` with neighbor `INCOMPLETE`, although the PC's
   wired carrier was up. Once reachable, run `scripts/manifold/probe_usb_bulk.sh` and collect the
   app-framework state, firmware/SDK inventory, and USB bulk channel before any DPK change.
2. Run `psdk_tap` through the installed DJI application framework, collect at least 100 valid
   frame/telemetry pairs and evaluate official p95 against 50 ms.
3. Import the generated KMZ on RC Plus 2 and record `wpmz/`, `droneEnumValue`, payload values and route
   display. Do not promote camera/flight/battery/RTH capability without that evidence.
4. Deploy `ksi-mission-contract-consumer` at the Manifold-facing execution boundary and HIL-test
   malformed/tampered/expired/revoked rejection before resolving `mission-contract-verification-unwired`.
5. Decide RISK-003 geometry synthesis ownership/shape and wire the producer before resolving
   `riskfield-production-generator-unwired`; the Core consumer now validates real bytes but
   intentionally does not invent tactical geometry.
6. Define a durable Edge device heartbeat/presence contract before implementing Fleet·Edge connection
   state. Event or equipment observations must not be relabeled as an online connection.

## Re-run commands

```bash
ulimit -n 8192 && uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
cd apps/dashboard && npm test && npm run lint && npm run build
```

The raised soft FD limit is currently required for the monolithic Python suite on this host; the
default 1024 limit exhausts descriptors across the large number of journal-backed tests.

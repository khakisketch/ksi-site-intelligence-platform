# Current goal (2026-08-31, automatic media mission-attribution software boundary)

Complete the repository-owned mission-attribution boundary for future automatic media ingest without
pretending that host software is a working DJI adapter. `REQ-ACQ-103`, `REQ-INT-101`, `REQ-SEC-101`
and `INV-018/040/041/051/060` apply.

Completion conditions:

- a verified mission-completion or operator one-shot context binds Mission, dispatch, Mission Contract,
  trigger evidence and a pre-activation SD baseline;
- only post-baseline exact `fileIndex + fileName + fileSize` identities enter the SourceMedia journal;
- list/download drift, baseline mutation, duplicate identity, no-new-media and cross-mission reuse fail
  closed with typed verdicts;
- context and selected-file digests survive restart in the SQLite/WAL journal, while legacy rows replay
  without invented values and cannot be resumed by the new worker;
- packaged `ksi_psdk_app` remains OFF until a real adapter/device provider and no-flight M4D HIL pass.

Repository-owned implementation is green at `ae7448b`. Pinned Ubuntu 20.04/gcc 9.4 with real SQLite
passes native CTest `8/8`, including legacy migration and cross-mission/identity-drift cases; ASan/UBSan
also passes `8/8`. Full Python is `4228 passed / 24 skipped`; Ruff, Mypy `443` files, lock, diff,
hygiene, reference, PSDK and runtime-image pin gates pass. Default `ksi_psdk_app` configure/build passes;
requesting media offload still fails at the explicit device-provider/HIL blocker.

Risk `psdk-media-offload-mission-attribution-unbound` is resolved by the host evidence. Its replacement
`psdk-media-offload-adapter-hil-not-verified` remains open: no real `DjiCameraManager` adapter, DJI
completion/baseline provider, DPK/device write or M4D HIL was performed. SD/PC/Web remains the normal
product path, automatic media capability remains `NOT_VERIFIED`/OFF, and no raw media, credential,
camera/gimbal, motor, waypoint or flight action occurred. Commit/push/deployment remain separate.

---

# Previous goal (2026-08-31, perception runtime boundary closure)

Close the contradictory status of the Python perception pipeline without promoting offline replay into
field evidence. `REQ-EVT-101`, `REQ-MODEL-101`, `REQ-SEC-101` and
`INV-021/040/041/042/060` apply.

Completion conditions:

- native `edge/psdk-app/ksi_psdk_app` remains the sole production Edge runtime;
- Python `pipeline.py` and `recorded_pipeline.py` explicitly identify as offline replay/model evaluation
  while continuing to share the EventBundle contract for conformance;
- Core rejects explicit and legacy offline markers before durable Edge journal/device-sequence
  reservation, rejects direct EventStore projection, and refuses a polluted legacy replay journal;
- ADR, API contract, final decision ledger, canonical risk and handoff state all state the same boundary;
- no software result is presented as DPK, device, model-support or HIL acceptance.

Repository-owned software is green at `ad8d899`; the authority decision is `6530989`. Focused runtime
boundary/API/replay tests pass `217`; full Python passes `4225` with `24` skips. Ruff and Mypy (`442`
source files), lock, diff, hygiene, reference and runtime/third-party pin gates pass. Risk
`perception-pipeline-production-status-undecided` is resolved with executable evidence.

The remaining five open risks all require device/HIL or an explicit deployment-runtime decision.
FIELD-0a stays `BLOCKED`, DJI and physical Edge capabilities stay `NOT_VERIFIED`/OFF. Remote delivery is
separate: `origin/main` remains `899c6c8`, the local branch contains unpublished commits, and remote CI
has not executed them under the known Actions account payment/spending gate.

---

# Previous goal (2026-08-31, Edge RiskField production assembly truth)

Make the existing native RiskField evidence path non-regressible and reconcile the canonical risk
ledger without converting software evidence into device acceptance. `REQ-EDGE-101`, `REQ-EVT-101`,
`REQ-GEO-101`, `REQ-SEC-101` and `INV-001/012/021/040/041/042/060` apply.

Completion conditions:

- the packaged `ksi_psdk_app`, rather than only a library/test target, is proven by contract to assemble
  `EdgePipeline → shared SQLite WAL/ArtifactVault → StoreForwardSyncDriver → CoreRestSyncTransport`;
- activation, perception, Core sync, TLS pins, bearer file and Ed25519 key remain explicit fail-closed
  deployment inputs, and producer/sender cannot silently use separate journals;
- Core CRITICAL confirmation continues to reject unsigned, wrong-device, stale-key, wrong-lineage,
  digest-mismatched or semantically invalid RiskField evidence;
- stale software risks are resolved only with executable evidence, while the real Manifold DPK/key/TLS/
  storage path remains a precise `NOT_VERIFIED` HIL risk.

Repository-owned software is green at `3afeb73`: the new production-wiring guard passes `4` tests;
targeted assembly/device-attestation/CRITICAL suites pass `90`; the pinned Ubuntu 20.04/gcc 9.4
Manifold container builds and passes native CTest `7/7`; full Python passes `4220` with `24` skips.
Ruff, Mypy (`442` source files), lock, diff, hygiene, reference, PSDK and runtime-image-pin gates pass.
Risks `riskfield-evidence-daemon-not-assembled`, `riskfield-provenance-no-device-signature` and
`critical-event-riskfield-evidence-gate-presence-only` are resolved. The replacement
`riskfield-evidence-chain-not-hil-verified` is open and has an explicit no-flight HIL procedure.

Remote delivery is still separate: `origin/main` remains `899c6c8` because this environment cannot
launch `git push`; GitHub Actions account payment/spending remains an external zero-step execution gate.
FIELD-0a stays `BLOCKED`, DJI and physical Edge capabilities stay `NOT_VERIFIED`/OFF, and no DPK,
device write, flight, motor, waypoint, camera/gimbal, customer-data, release or deployment action is
claimed.

---

# Previous goal (2026-08-31, civil report coverage-evidence closure)

Close `coverage-reconciliation-not-in-print-or-csv` without changing the approved Operations Console
information architecture. `REQ-WRK-101`, `REQ-INT-101/102/103/104`, `REQ-SEC-101` and `REQ-UX-101`
apply with `INV-010/040/053/060`.

Completion conditions:

- the existing civil report, browser print and CSV expose the same accepted CoverageReport attribution,
  plan reconciliation and rejected-claim history rather than presenting progress numbers without their
  observation basis;
- Core derives and journals those facts from immutable organization-scoped records, preserves legacy
  export replay, and does not let later coverage suffixes rewrite an earlier document;
- unavailable or mismatched screen/Core evidence blocks browser output before print or Blob creation;
- full local Python, Dashboard, browser and repository gates pass, and remote delivery/CI are reported
  independently from local evidence and physical-device acceptance.

Repository-owned software is green at feature commit `e576217`; authority/risk closure is `164c2c2`.
Python passed `4216` tests with `24` skips; Ruff and Mypy (`441` files) passed. Dashboard passed
`62 files / 572 tests`, ESLint, TypeScript, production build and Playwright `62 passed / 14 intentional
external-staging skips` at 390/768/1024/1440. Lock, diff, hygiene, reference, PSDK and runtime-image-pin
gates passed. The canonical risk is `resolved` with evidence, while the separate INV-010 inability to
recompute aircraft-reported zone ratios remains explicit.

Delivery remains environment-blocked: at the push attempt, the final fetch showed `origin/main` at
`899c6c8` as an ancestor and local `164c2c2` two commits ahead with a clean worktree. This Codex environment rejected
`git push origin main` before process launch because approval is unavailable; no remote mutation
occurred; the state metadata commit follows locally. Remote Actions execution is also independent, and historical run `33317220883` stopped all
six jobs before their first step under the account payment/spending-limit gate.

FIELD-0a remains `BLOCKED`; every DJI capability remains `NOT_VERIFIED`/OFF. No device, DPK, flight,
motor, waypoint, camera/gimbal, customer data, release or deployment action is claimed.

---

# Previous goal (2026-08-30, civil runtime and resource-policy software closure)

Complete the repository-owned portion of ADR-KSI-032 without changing the approved Operations Console
information architecture. `REQ-OPS-101/102`, `REQ-WRK-101`, `REQ-INT-104`, `REQ-SEC-101` and
`REQ-UX-101` apply with `INV-040/050/053/054/055/060`.

Completion conditions:

- every production-owned external runtime reference is an exact approved version/digest and floating
  references fail the repository gate;
- Core alone expands and journals the immutable `ksi-civil-pilot-r1` admission policy from authoritative
  Mission, sealed SourceMedia and organization-active-job records;
- the existing Mission processing card shows the server policy and typed next action without a new menu,
  hardcoded client limits or hidden history;
- a clean-source release candidate can create an owner-only local provenance envelope that binds exact
  product image identities and hashes of separately supplied SBOM/scanner bytes, without claiming the
  envelope is a signature, WORM storage or proof of artifact-to-image generation;
- full Python/Dashboard/browser/hygiene gates pass, changes are split into reversible commits and the
  remote fast-forward/push result is verified independently from remote CI execution.

Repository-owned software is green: Python `4215 passed / 24 skipped`; Ruff; Mypy `441` source files;
Dashboard `62 files / 566 tests`, ESLint, TypeScript and production build; Playwright `62 passed / 14`
intentional external-staging skips at 390/768/1024/1440; lock, hygiene, reference, third-party checksum,
runtime-pin and diff gates. Functional commits through `04cb68a` are split by authority/runtime/Core/UI/
release evidence/test typing. The final fetch proved `origin/main` (`0ff5f94`) is an ancestor and local
`main` was 14 commits ahead at `fc711e0`, but this Codex environment rejected `git push origin main`
before launch because approval is unavailable. Delivery and remote-CI evidence therefore remain pending.

Actual product-image build/promotion, SBOM/scanner review, release signing/WORM/remote anchoring, public
Cloud/customer-data approval and Korean civil field acceptance remain external gates. FIELD-0a remains
`BLOCKED`; every DJI capability remains `NOT_VERIFIED`/OFF. This goal performs no device, DPK, flight,
motor, waypoint or camera/gimbal action.

---

# Previous goal (2026-08-30, civil operational closure and trust hardening)

Close the next repository-owned product gaps without changing the approved Operations Console
information architecture: immutable report-export audit, Core-to-Processing correlation, an opt-in
live civil E2E workflow, honest direct-spacing coverage claims, and the production trust-chain gates
that can be proven without DJI device actions. `REQ-WRK-101`, `REQ-MSN-103/104`,
`REQ-INT-101/102/103/104`, `REQ-SEC-101` and `REQ-UX-101` apply with
`INV-010/015/016/017/018/020/024/040/050/051/053/060`.

Completion conditions:

- report PDF/CSV actions create organization- and Site-scoped append-only audit records bound to the
  exact server-side report inputs; the client cannot assert an organization or fabricated result;
- one correlation identifier follows a processing operation across Processing Controller and Core
  HTTP calls without logging credentials or raw civil data;
- the pinned NodeODM/MinIO live path has a safe opt-in CI entry that never commits or invents input
  imagery and distinguishes missing owner input from an executed failure;
- direct-spacing recovery always emits `plannedCoverageRatio=null`, while only the canonical
  CameraSpec route may issue and preflight a planned photogrammetric coverage claim;
- targeted and full regression, Dashboard/browser, hygiene, commit, push and actually executed remote
  CI evidence are recorded separately from civil field and DJI acceptance.

Local completion evidence for this increment: Python `4147 passed / 24 skipped`; Ruff, lock and Mypy
(`434` source files); Dashboard `60 files / 552 tests`, ESLint, TypeScript and production build;
Playwright `62 passed / 14 intentional external-staging skips` at 390/768/1024/1440; repository,
credential-pattern, large-file, reference and third-party-pin gates. Fresh native runtime and
sanitizer builds passed `7/7` each with the SQLite/WAL backend explicitly unavailable on this host;
PSDK-independent logic passed `2/2` and the missing-PSDK default stayed fail-closed.

Starting delivery fact: the owner pushed `0ff5f94afad458527e71e7229fa015dc1d6136e0`, and local
`main` initially matched `origin/main`. GitHub Actions run `33260008688` targets that SHA but all six
jobs ended before runner steps because the account payment failed or its Actions spending limit must
be increased. That prior push is complete; remote code execution is not. The current increment is
split into `1e1c8d6`, `c55e58d`, `9f5ae15`, `4446a5d`, `3dcbee8` and documentation commit `bd67fe7`.
The 2026-08-30 fetch/ancestor check passed, but this Codex environment rejected `git push` before the
process launched because approval is unavailable. Remote delivery therefore remains pending.

FIELD-0a remains `BLOCKED`; every DJI capability remains `NOT_VERIFIED`/OFF. This goal performs no
flight, motor, waypoint, camera/gimbal, DPK, credential or device write.

---

# Previous goal (2026-08-29, independent checkpoint-validation producer v1)

Extend the existing civil temporal/quantity processing path with the optional, fail-closed
ADR-KSI-031 independent-checkpoint producer. `REQ-INT-104`, `REQ-INT-101`, `REQ-SEC-101` and
`REQ-UX-101`; `INV-020/023/024/040/050/053/060` apply. Core owns the immutable checkpoint
register/seal/result journal and comparison lookup; Processing Controller owns strict sealed-byte and
DSM sampling verification; Dashboard adds an optional existing-panel card only.

Completion conditions:

- The client can declare only checkpoint provenance, CRS/vertical basis and explicit independence;
  it cannot submit RMSE or turn a value into a survey/settlement claim.
- The Controller re-hashes sealed checkpoint and DSM bytes, rejects an entire invalid dataset and
  reports server-computed metrics through an immutable Core observation.
- Comparison uses a verified server result where present, preserves `null + reason` when absent and
  never treats technical validation as physical field acceptance.
- Contract/replay/organization-isolation/hostile-input/controller tests, full regression, Dashboard
  and hygiene runs are recorded before a software-pass claim.

Current state: implementation and the complete software verification matrix are green. Python passed
`4122` tests with `24` skips and `3` expected failures; Ruff and Mypy (`431` source files) passed.
Dashboard Vitest passed `59` files / `545` tests, followed by ESLint, TypeScript, production build and
Playwright `62 passed / 14 intentional skips` at 390/768/1024/1440. Lock, diff, repository hygiene,
reference-import and pin gates passed. The local functional commit series is complete and the
2026-08-30 fetch proved `origin/main` is a fast-forward-safe ancestor. Remote delivery remains blocked
outside the repository: this execution environment rejects `git push` before launch, and GitHub Actions
run 33139495105 shows every job at zero steps because the account payment failed or its spending limit
must be increased. No push/release/deployment is claimed until remote SHA and executed CI evidence exist.

FIELD-0a remains `BLOCKED`; every DJI capability remains `NOT_VERIFIED`/OFF. This work excludes flight,
motor, waypoint execution, camera/gimbal, DPK and Pilot 2/Manifold automatic egress.

---

# Previous goal (2026-08-29, civil temporal/quantity processing consistency v1 closure)

`REQ-WRK-101`, `REQ-INT-101/102/103/104`, `REQ-SEC-101`, `REQ-UX-101`과
`INV-017/018/020/023/024/040/050/051/053/060`을 적용해 토목 시계열·물량의 기본
처리 계약을 일관되게 만든다. Core는 immutable `ksi-odm-civil-v1` NodeODM profile과
comparison compatibility 원장을, Processing Controller는 LandXML→canonical GeoTIFF와
NodeODM identity를, Dashboard는 기존 Console 패널의 additive 상태 표현을 소유한다.

완료 조건:

- profile ID→snapshot/digest 확장, legacy `LEGACY_UNMANAGED` 재생, pinned OCI `/info`
  identity와 masking OFF fail-closed 검증.
- GeoTIFF/IFC 유지와 LandXML TIN Surface 원본·selector·normalization lineage, 안전한
  parser/rasterizer 및 typed rejection 검증.
- readiness/profile/lineage/CRS/vertical/design revision·normalization 중 하나라도
  불일치하면 정량 비교를 거부하는 typed blocker와 기존 Console 패널 표현 검증.
- `CIVIL_PROCESSING_V1_ACCEPTANCE.md`의 Python/Console/NodeODM/hygiene evidence를 실제
  실행해 기록한다. software 결과는 실제 토목 측량·정산 수용이 아니다.

현재 상태: implementation, 전체 software regression, private field-input fail-closed audit와
공개 실데이터 E2E-B01 기술 benchmark를 완료했다. exact profile은 USGS 동일 영역 두 취득분
24장씩에서 각각 DSM/DTM/점군을 만들고 두 DSM의 유한 중첩을 확인했다. 이 자료는
EPSG:32617·EXIF GNSS·보존용 JPEG이므로 product quantitative comparison은 계속 false이며,
E2E-01과 실제 국내 토목 현장 수용은 `PARTIAL/GATED`다. 외국 CRS를 국내 CRS로 바꿔 표시해
증거를 만들지 않는다. 새 기본 media ingress는 `SD/저장매체 → 현장 PC → KSI 웹 업로드`이고,
향후 자동 반출은 이 ingress adapter만 교체한다. raw 원본/좌표는 owner-private 외부 경로에
남기고 Git에는 digest·판정만 기록한다. remote push, deploy, release는 수행하지 않았다.

FIELD-0a는 별도 physical evidence gate로 계속 `BLOCKED`, DJI capability는 모두
`NOT_VERIFIED`/OFF다. 이 작업은 비행·motor·waypoint 실행, camera/gimbal·DPK, Pilot 2/
Manifold 자동 미디어 반출 또는 capability 승격을 열지 않는다.

---

# Previous goal (2026-08-27, no-USB FIELD-0a evidence completion)

완료된 소프트웨어 기준선 위의 no-USB evidence commit `7d1aa88`을 유지하면서, USB 재시험
없이 Pilot 2/M4D의 formal FIELD-0a 증거를 owner-private local store에 같은 세션으로 결속한다.
`REQ-ACQ-101/103`, `REQ-INT-101`, `REQ-SEC-101`과 `INV-040/041/060`을 적용한다.

현재 사실:

- Pilot 2에서 `window.djiBridge`와 6개 bootstrap 함수 이름이 보인 것은
  `JSBRIDGE_SURFACE_OBSERVED`다. 함수 호출·license·component·Wayline/Media는 미검증이다.
- 2026-08-20 A KMZ import/map 표시와 M4D WideCamera 원본 EXIF(12.29mm, 5280×3956)는
  부분 증거이며 카메라 SSOT에는 반영됐다.
- canonical FIELD-0a 세션에는 같은-session 원본/attestation이 아직 없고 Pilot-native
  mapping KMZ도 없다. 무입력 audit의 4개 typed blocker 때문에 formal FIELD-0a와 Phase 3은
  `BLOCKED`, 다섯 capability는 `NOT_VERIFIED`/OFF다.
- USB 없는 회수를 위해 Tailnet capability URL로 고정 슬롯만 0600 저장하는 임시 HIL
  수신기를 구현·검증했다. Pilot 2 Android file picker 동작은 실기에서 아직 미검증이다.

완료 조건:

- 새 0700 session에서 A import 화면, Pilot-native KMZ, M4D 원본과 0600 attestation을 결속한다.
- `audit_phase3_readiness.py`가 `FIELD-0a PASS` 또는 정확한 typed blocker를 반환한다.
- raw 파일·session ID·local path·serial/GPS/token은 Git에 넣지 않는다.
- 비행·motor·waypoint 실행, DPK write, camera/gimbal automation과 capability 승격은 하지 않는다.

FIELD-0a가 닫힌 뒤에만 별도 DJI developer app/license bootstrap을 다음 독립 게이트로 연다.

---

# Previous goal (2026-08-27, software closure and FIELD-0a durable-share gate)

`REQ-MSN-104`, `REQ-WRK-101`, `REQ-ACQ-102/103`, `REQ-INT-102/103`, `REQ-SEC-101`의
소프트웨어 개선을 기능별 local `main` 커밋으로 닫고, FIELD-0a는 Pilot 2/M4D의
무비행 물리 증거가 **사용자 전용 private evidence store**에 있을 때만 판정한다. `INV-011/012/016/017/018/
040/041/050/060/061`은 조직·Mission·WorkOrder·device binding, immutable journal, exact
digest, evidence-derived fail-closed projection으로 강제한다.

현재 software build는 `3bb55df`까지의 5개 기능 커밋이며, 전체 Python `3948 passed, 23
skipped, 3 xfailed`, Ruff, Mypy `409 source files`, Dashboard Vitest `58 files / 529 tests`,
ESLint, TypeScript, production build, Playwright `58 passed, 14 skipped`를 통과했다.

FIELD-0a physical session은 아직 시작하지 않았다. 사용자가 NAS 없는 단순 로컬 운영을
선택했으므로 canonical root는 `$HOME/.local/share/ksi-field-evidence`이며 root/session 0700,
raw/attestation 0600, owner-only, no-symlink로 fail closed한다. 현재 blocker는
`PILOT_IMPORT_EVIDENCE_REQUIRED`,
`M4D_ORIGINAL_METADATA_REQUIRED`, `PILOT_EXPORT_KMZ_REQUIRED`,
`FIELD0A_ATTESTATION_REQUIRED`다. owner-only direct-child session에서
propeller-removed/no-flight 절차와 human attestation을 수행한다.

Phase 3B DPK write/restart, flight/motor/waypoint action, camera/gimbal automation, capability
`VERIFIED` 승격은 범위 밖이며 다섯 capability는 `NOT_VERIFIED`를 유지한다.

---

# Previous goal (2026-08-26, local main integration complete)

현재 dirty 변경을 제품 권위·안전 경계에 따라 검토하고 원본 증거·생성물·secret을 제외한 뒤,
기능·배포·HIL·설계·문서 단위의 의미 있는 로컬 `main` 커밋으로 통합한다.

완료 결과:

- Core/계약, DJI Gateway, Dashboard, 배포/OIDC, HIL 증거 게이트, Sites 프로토타입,
  제품 문서, 저장소 위생과 handoff를 각각 독립적으로 되돌릴 수 있게 정리했다.
- `download/`의 DJI 비행 기록·M4D 원본과 `Testing/` 생성물, 실제 secret/key는 커밋하지 않았다.
- 전체 Python, Ruff/Mypy, Dashboard 정적·단위·빌드·E2E, 프로토타입 runtime/Sites 검증을 통과했다.
- FIELD-0a/Phase 3과 다섯 DJI capability는 계속 `BLOCKED`/`NOT_VERIFIED`다.
- 원격 push, release, tag, 장비 접촉/write, 비행은 수행하지 않았다.

---

# Current goal (2026-08-26, Phase 3 read-only HIL software preflight)

FIELD-0a 이전 신규 기능 동결을 유지하면서 장비 없이 가능한 Phase 3 사전검증과 증거 준비를
닫는다. 기존 A/B/C KMZ kit, Pilot 2 import 화면과 M4D 원본을 다시 판정하고, Pilot-export
KMZ·물리 세션 승인이 없으면 FIELD-0a와 Phase 3을 `BLOCKED`로 유지한다.

완료 조건:

- checksum·KMZ 구조·waypoint·촬영 action을 재현 가능하게 검사한다.
- M4D 원본에서 GPS·serial을 유출하지 않고 카메라·촬영시각 metadata만 private manifest로 남긴다.
- Pilot-export byte가 생겨도 출처 attestation 없이 자동 PASS하지 않는다.
- 다섯 DJI capability와 비행·배터리·RTH·camera 기능은 `NOT_VERIFIED`를 유지한다.

장비 접촉·device write·비행·외부 배포·고객 데이터·commit/push/release는 수행하지 않는다.

---

# Previous goal (2026-08-25, Phase 2 synthetic Cloud/AI staging accepted)

DJI 장비 없이 production-equivalent Operations Console의 OIDC/TLS/S3/grounded-AI/backup
경계를 격리된 DGX Spark 합성 Staging에서 종단 검증한다.

완료 결과:

- 별도 Compose project와 named volume에서 Dashboard `EXTERNAL_VM`, Core OIDC, Local Identity,
  MinIO, outbound client가 없는 deterministic OpenAI-compatible provider를 기동했다.
- 실제 PNG bytes와 digest를 presigned HTTPS로 열고, 한 Site의 명시적 AI opt-in만 정상 답변을
  허용했다. provider 503, 다른 Site citation, opt-out은 모두 저장형 `BLOCKED`로 닫혔다.
- journal/object/signing key backup의 SHA-256과 격리 restore를 실제 실행했고 4개 viewport
  Chromium 및 전체 software 회귀를 통과했다.

고객 Cloud/data, 실제 외부 AI/IdP, public release, DJI/device/HIL, commit/push/release는 수행하지
않았다. 다음 단계는 승인된 물리 RC-first read-only HIL이며 다섯 DJI capability는 여전히
`NOT_VERIFIED`다.

---

# Previous goal (2026-08-25, Phase 1 software UI/UX accepted)

Operations Console Phase 1의 populated·empty·부분 실패 흐름, 다음 행동 우선 정보 구조,
4개 뷰포트 접근성/OIDC E2E와 실제 Tailnet 제품 검토를 닫는다.

완료 결과:

- 실제 도메인 store와 전이를 쓰는 격리 합성 원장으로 Home·Sites·Work·Items·Site detail의
  populated 상태를 검증하고, 별도 빈 조직 OIDC 계정으로 actionable empty state를 검증했다.
- evidence metadata는 있지만 이미지 storage가 없는 상태를 실패로 숨기지 않고
  `관측 이미지 열람 불가`로 표시한다. Mission·processing·report·spatial model·device evidence는
  합성하지 않는다.
- 390/768/1024/1440 Chromium, 접근성, OIDC 조직 격리, 실제 Tailnet browser 검토와 전체
  repository 회귀가 통과했다. Phase 1 software UI/UX baseline은 PASS다.

다음 delivery 단계는 `phase-2-synthetic-cloud-ai-staging`이며 별도 승인·범위 확정 전에는
시작하지 않는다. 외부 고객 Cloud/실제 IdP, device write·DPK·credential·비행, DJI adapter/HIL,
commit/push/release는 수행하지 않았고 다섯 DJI capability는 `NOT_VERIFIED`다.

---

# Previous goal (2026-08-24, Phase 1 truthfulness hardening)

Operations Console의 현장·작업·확인 항목 흐름이 실제 Core 원장과 일치하도록 완성한다. 조회 실패를
0건으로 바꾸지 않고, 확인 항목의 근거 유무와 현장 검토 건수를 서버 투영으로 제공하며, AI 근거는
허용된 같은 현장 Console 경로로만 이동한다. 고객 화면에서는 내부 계약·장치 용어보다 현장·근거·
결정·다음 조사를 우선한다.

완료 조건:

- SiteWorkspace의 검토 건수는 열린 사람 결정만 포함하고, Event 목록 근거 건수는 삭제되지 않은
  evidence와 일치한다. Core의 요청당 500건 상한은 제품 수치·목록 상한이 아니며, 명시한
  organization 범위 밖 Event나 최신 ProcessingJob이 request context 없는 projection에도
  섞이지 않는다.
- 브리핑·보고서·변화 화면은 실패를 빈 결과로 위장하지 않으며 임의 citation path를 링크하지 않는다.
- 작업 큐와 고객 용어가 테스트로 고정되고 전체 Python/Ruff/Mypy/Dashboard 게이트가 통과한다.
- 현재 변경 화면의 실제 브라우저 수용이 없으면 Phase 1을 완료로 올리지 않는다.

외부 고객 Cloud/데이터, 실제 IdP, device write·DPK·credential·비행, DJI adapter/HIL,
commit/push/release는 범위 밖이며 다섯 DJI capability는 `NOT_VERIFIED`다.

---

# Previous goal (2026-08-24, Operations Console Phase 0/1 completion)

장비 실증보다 먼저 KSI 제품 정본과 Operations Console의 현장 중심 UX를 완성한다. 제품은
현장 데이터를 AI가 읽어 변화·중요성·사용자 결정을 근거와 함께 제시하고 다음 조사와 업무로
연결하는 AX 제품이다. Home은 다현장 책임자·경영진의 포트폴리오 입구, 현장 작업공간은 현장
담당자의 근거·결정 공간, Pilot 2는 드론 운영 공간으로 분리한다.

완료 조건:

- ADR-KSI-027과 Phase 1 UX 표준/acceptance가 Console → 합성 Cloud/AI → HIL → 통합 →
  Field Pilot 순서와 HIL 이전 `NOT_VERIFIED` 경계를 고정한다.
- `/sites`는 390/768에서 가로 표를 강요하지 않고 현장명·상태·다음 확인·현장 열기 카드로,
  1024~1279에서는 전체 권한을 유지한 비교 카드로, 1280 이상에서는 밀도 있는 비교표로 읽힌다.
- `/field`는 시스템 설명보다 결정 필요·진행·완료 작업을 먼저 보여 주고, 모바일 안내는
  불필요한 구현 세부 없이 다음 행동을 설명한다.
- 390/768/1024/1440 Chromium, Dashboard test/lint/type/build와 URL·조직·권한 경계를 회귀한다.

외부 고객 Cloud/데이터, 실제 IdP, device write·DPK·credential·비행, 실제 DJI adapter/HIL,
commit/push/release는 이 목표의 범위 밖이다. 다섯 DJI capability는 `NOT_VERIFIED`다.

---

# Previous goal (2026-08-22, persistent Tailnet development access)

원격 SSH 개발에서도 localhost 포워딩이나 Bearer 입력 없이 동일한 Operations Console을
항상 열 수 있게 한다. 표준 `npm run dev`는 Tailscale을 필수로 확인하고 Dashboard와 합성
Local Identity를 loopback에 둔 채 Tailnet 전용 Serve로만 노출한다. 사용자 systemd service는
SSH 종료와 재부팅 뒤에도 stack을 자동 복구한다.

완료 조건:

- Tailnet MagicDNS URL에서 OIDC Authorization Code + PKCE 전체 왕복과 실제 Core DB 조회가 된다.
- Next dev asset과 HMR WebSocket이 외부 origin에서 동작한다.
- 기존 Serve port 80과 production VM/import closure는 변경하지 않는다.
- 서비스는 LAN/public에 bind하지 않고 Tailscale이 없으면 fail-closed한다.
- localhost 전용 rollback과 systemd/Tailscale endpoint 해제 명령이 문서화된다.

장비/HIL, 외부 고객 Cloud, commit/push/release는 범위 밖이며 DJI capability는 `NOT_VERIFIED`다.

---

# Current goal (2026-08-22, Operations Console U0 next-action usability)

FIELD-0a 이전 신규 기능 동결을 유지하면서, 로그인 뒤 사용자가 빈 화면이나 잘못된 Mission
행동에서 막히지 않도록 기존 Site·Event·WorkOrder·Acquisition 사실만으로 다음 행동을
결정한다. Home, 오늘 작업, Site 상세, 현장 목록과 Event 빈 상태가 같은 우선순위를 사용하고,
1024px 미만에서는 기존 반응형 행동 경계를 그대로 지킨다.

완료 조건:

- 미조치 Event, BLOCKED/승인 대기/진행 중/결과 준비 WorkOrder, 현장 없음, AOI 없음,
  베이스라인·재조사 순서가 하나의 결정기와 회귀 테스트로 고정된다.
- AOI가 없는 Site는 Home·현장 목록·Site 상세 어디에서도 조사/Mission 발급으로 건너뛰지 않고
  AOI 편집기로 이동한다.
- `/field` 빈 상태가 실제 다음 행동을 제공하고 Event 0건 화면은 상충하는 선택 패널을 숨긴다.
- 390/768/1024/1440 실제 브라우저에서 모바일 제한과 데스크톱 행동 경계가 성립한다.

FIELD-0a 증거, 최종 6개 메뉴 IA, 외부 Staging, DJI adapter, FIELD-1/2는 후속 gate다.
다섯 DJI capability는 계속 `NOT_VERIFIED`이며 장비/외부 배포/commit/push/release는 수행하지 않는다.

---

# Current goal (2026-08-21, production-equivalent local OIDC development)

일반 로컬 Dashboard 개발도 상용과 같은 사람 OIDC 경로로 고정한다. `npm run dev`는
loopback 전용 Local Identity issuer, OIDC 검증 Core, Operations Console을 함께 기동하고,
사람은 Bearer 토큰을 붙여넣지 않는다. Core DB/journal과 local signer/client/session secret은
`.dev-data/`에 내구적으로 남아 실제 개발 데이터 흐름을 재현한다.

완료 조건:

- 사람 로그인은 Authorization Code + PKCE → 서명 JWT/JWKS → Core OIDC claim 검증을 실제로 통과한다.
- 개발 issuer는 loopback만 허용하며 합성 계정만 제공하고 production VM/image/import graph에는 없다.
- 기본 Dashboard 실행에서 opaque 토큰 입력은 보이지 않으며, legacy 조사는 명시적 non-production flag에서만 가능하다.
- 외부 VM은 기존처럼 HTTPS OIDC·file secret 누락 시 fail-closed하며 Gateway/Edge/worker opaque 자격은 분리된다.
- login redirect와 `/field` Console 진입을 실제 browser로 확인한다.

장비/DPK write, credential 입력, 비행, 고객 데이터 upload, 외부 배포,
commit/push/tag/release는 이번 목표 범위가 아니다. 다섯 DJI capability와 FIELD/HIL은 계속
`NOT_VERIFIED`다.

---

# Previous goal (2026-08-21, responsive Operations Console and external VM readiness)

Pilot 2와 RC Plus 2를 비행·gateway 전용으로 유지하고, 현장 업무는 하나의 반응형
`KSI Operations Console`에서 수행하도록 제품·코드 경계를 확정한다. `/field`는 기존 링크를
유지한 일반 Console 작업 큐이며 1024px 미만에서는 조회·event triage·분석·Copilot만 허용하고
승인·Mission·장비 전이·원본 복구는 안전한 안내로 노트북에 넘긴다.

동시에 승인된 Cloud 사업자에 실제 배포하기 전 단계로 사람 OIDC와 장비 opaque 자격을 분리하고,
Dashboard/Core/Caddy/MinIO/worker를 외부 VM에 조립할 수 있는 fail-closed profile을 만든다.
완료 조건은 다음과 같다.

- `/field`와 deep link가 일반 Dashboard shell에서 동작하고 모바일 행동 경계가 SSR-safe하다.
- production 제품은 Pilot Bridge나 `window.djiBridge`에 의존하지 않으며 비활성 HIL 경로는 HTTP 404다.
- Auth.js는 OIDC Authorization Code + PKCE, HttpOnly encrypted session을 사용하고 브라우저에
  Core access/refresh token을 노출하지 않는다.
- Core는 OIDC JWT의 signature/issuer/audience/time/algorithm/kid/KSI claims를 검증하고,
  Gateway/Edge/worker opaque 자격은 별도로 유지한다.
- additive VM profile은 Caddy 80/443만 외부 publish하고 secret·public object endpoint·백업 및
  restore 검증을 제공한다.
- 특정 Cloud 사업자 승인과 실제 고객 데이터 배포는 별도 적법성 gate로 남긴다.

장비 write, DPK 설치, credential 입력, 비행, 고객 데이터 upload, 외부 배포,
commit/push/tag/release는 이번 목표 범위가 아니다. 다섯 DJI capability와 FIELD/HIL은 계속
`NOT_VERIFIED`다.

---

# Current goal (2026-08-21, KSI Cloud Coordination Foundation)

RC-first Connected Edge 소프트웨어 기반 위에 WorkOrder 중심 acquisition 진행 원장을
추가한다. 사람 승인 뒤에는 조직·Site·회차에 묶인 `AcquisitionRun`이 생기고,
Mission·Gateway receipt·Edge activation·SourceMedia·Processing의 기존 사실 원장을
한 진행상태로 투영한다. 장비 capability는 실제 HIL 전 `NOT_VERIFIED`로 유지하며
비행 경로·adapter를 추측해 만들지 않는다.

완료 조건:

- KSI Cloud 경계와 production env 예제가 현재 Core 신원·rollout flag와 일치한다.
- WorkOrder 승인 재시도는 같은 run을 반환하고 coordinator 실패가 승인을 되돌리지 않는다.
- Mission Plan의 선택적 `workOrderId`가 조직·Site·APPROVED 상태를 검증하고 lineage를 보존한다.
- Gateway operation receipt가 장치 binding·조직 scope·idempotency/digest를 fail-closed 검증한다.
- WorkOrder 상세가 주 행동 하나와 acquisition 단계, 연결 상세, 전문가 복구 정보를 분리한다.
- 전체 소프트웨어 회귀를 통과하고 실제 다섯 DJI capability는 계속 `NOT_VERIFIED`다.

장비 write, DPK 설치, credential, 비행, 외부 upload, production 변경,
commit/push/tag/release는 이번 마일스톤 범위가 아니다.

---

# Current goal (2026-08-21, RC-first Connected Edge foundation)

확정된 `Matrice 4D + Manifold 3 + RC Plus 2` 기본 제품을 SIM 없는 고객에게도
성립시키도록 제품 정본과 소프트웨어 경계를 재정렬한다. 제품 책임을 Core·DJI
Gateway·Manifold·Processing·Dashboard로 나누고 RC/Dock/직접망/MSDK 차이는
장비 adapter로 격리한다.

이번 마일스톤의 완료 조건은 다음과 같다.

- `AcquisitionDeploymentProfile v1`과 `ConnectivitySnapshot v1`을 additive 계약으로
  제공하고, 사람/Gateway/Edge 신원을 분리한다.
- 새 Mission 발급 gate는 유효한 RC heartbeat·인터넷·binding·기능별 VERIFIED receipt가
  없으면 fail-closed로 막는다. production rollout flag는 HIL·profile migration 전 기본
  OFF이고, 이미 활성화된 계약은 연결 단절만으로 취소하지 않는다.
- DJI Gateway를 기능별 port/router/journal로 분리하고 모든 새 feature flag를 OFF로 둔다.
- Dashboard가 RC 인터넷·Manifold·직접망·계약·원본 동기화를 별도 상태로 표시한다.
- HIL v1.3이 기능별 evidence를 요구하고 v1.2 provider 판정에서 capability를 추론하지 않는다.
- ADR-KSI-023과 소스 경계 문서를 정본에 반영하고 전체 회귀를 통과한다.

실장비 Cloud 하향·Pilot 업링크·wayline·media 회수, MSDK Bridge, Dock adapter,
WorkOrder부터 activation/media/Processing까지의 실제 coordinator는 이번 소프트웨어
완료 주장 밖이다. 전 기능은 실제 M4D/RC Plus 2/Manifold 3 HIL 전 `NOT_VERIFIED`다.
비행·장비 write·credential·외부 upload·commit/push/release는 수행하지 않는다.

---

# Current goal (2026-08-20, MVP Integration Milestone 1)

DJI Cloud/Pilot-to-Cloud와 Manifold 3 PSDK camera-media 경로를 실제 증거로 평가하고,
둘 중 HIL/FIELD acceptance를 통과한 한 경로만 `WorkOrder → Mission → ZeroTouchGateway →
Media`의 concrete provider로 채택한다.

현재 범위는 안전한 provider acceptance 준비와 read-only preflight다. 공식 문서상 API 또는
제품 지원표를 KSI capability `VERIFIED`로 승격하지 않는다. 비행·route start·장비 write·
credential 처리·외부 upload는 별도 사용자 승인과 장비 준비 전에는 수행하지 않는다.

완료 조건:

- Cloud 5항목 또는 PSDK camera-media 5항목이 동일 lineage의 실제 evidence로 모두 통과한다.
- 선택 provider가 `VERIFIED`이고 evidence ref가 실제 세션 내부에 존재할 때만 채택한다.
- 실패/접근 불가 경로는 원문 blocker와 환경 조합을 보존하고 추측으로 구현하지 않는다.
- 기존 Pilot 2 수동 KMZ와 folder ingest는 rollback/복구 경로로 유지한다.

현재 상태는 acceptance kit v1.2와 실제 private preflight session까지 준비됐다. Cloud는
공식 지원표가 M4D/M4TD를 Dock 3에만 두고 RC Plus 2 + Pilot 2에는 M4E/M4T만 열거하므로
`BLOCKED`; PSDK는 `MANIFOLD_UNREACHABLE`로 `BLOCKED`다. aircraft link는 `UNKNOWN`, 선택
provider는 없다. host의 DJI USB 부재는 Manifold 내부 USB bulk 경로의 blocker로 쓰지 않는다.

---

# Previous goal (2026-08-20, closed-loop MVP)

건설현장의 반복 관측을 `오늘 작업 → 사람 승인 → 무파일 수집 →
결정적 변화·공정·상대 물량 계산 → 근거형 Copilot → 재관측 사람 승인`으로
닫는 KSI Site Intelligence MVP의 소프트웨어 기반을 만든다. DJI의 기본 비행
UI를 복제하는 대신 Cloud/Pilot 2를 우선 연결하고, Manifold 3는 비행 중
촬영 품질 보충과 offline store-and-forward에만 쓴다.

이 마일스톤은 REQ-WRK-101, REQ-ACQ-101/102, REQ-INT-101,
REQ-COP-101/102, REQ-SEC-101, REQ-UX-101과 INV-060/061을 추가하고 다음을
구현한다.

- 조직 범위의 일정·Observation Work Order·재관측 초안·내구성 승인
- 실기 capability 증거 전에는 열리지 않는 provider-neutral DJI Gateway
- 서명 Mission/Capture Policy 범위 안의 Manifold 촬영 품질 행동 허용기
- typed read tools와 근거 ID만 쓰고 재관측 초안만 만드는 Copilot
- 현장 사용자에게 파일·KMZ·기술 ID를 숨긴 5단계 `오늘 작업` UX

완료 경계는 소프트웨어다. 실제 DJI Cloud/PSDK adapter, 자동 media 회수,
실제 LLM provider, 생산 조직 데이터 마이그레이션, HIL·FIELD 증거는 없다.
따라서 zero-touch·active acquisition·현장 완료를 주장하지 않는다.

---

# Previous milestone goal (2026-08-20)

FIELD-0a의 확인된 A-file import와 M4D WideCamera 원본 사진 증거를 보존하면서,
Pilot-export KMZ 대조는 공식 FIELD-0a 완료 전제로 남긴다. 운영자가 수용한 이 잔여
리스크는 FIELD-0b HIL 준비를 더 이상 막지 않는다. 현재 milestone은 Manifold 3에서
capture-only DPK 배포 경로와 PSDK 읽기 경로를 안전하게 실증할 준비를 끝내는 것이다.
HIL·FIELD 증거와 프로덕션 writer 활성화는 계속 별도 상태로 둔다.

구현 범위:

- CRITICAL 기계 증거의 Ed25519 artifact attestation 및 operator-provisioned device key registry
- 활성 dispatch의 mission/device/risk policy/calibration/RiskField lineage 대조
- Manifold `EdgePipeline → StoreForwardSyncDriver → CoreRestSyncTransport` 상시 sync와 외부
  0600 개인키 기반 정적 OpenSSL 서명
- Mission Contract v1.3 `issuance={issuerId,siteSequence,issuedAt}`, durable high-water,
  v1.2/v1.3 dual-reader 및 v1.3 이후 rollback/downgrade 거부
- 파일별 captureTime, ProcessingJob 불변 captureWindow, `capturedTo` 전용 freshness,
  site detail 중첩 공간모델 요약과 Dashboard 소비자 전환

명시적 차단/보류: FIELD-0a Pilot-export KMZ(수용 리스크로 기록하되 목표는
`in_progress`), 실제 device key provisioning, Manifold DPK/USB/frame-telemetry HIL,
v1.3 writer 활성화, FIELD-1/2, Core DTM→WPML 지형추종, 프로덕션 배포 및 Git
commit/push. 외부 0600 개인키·DJI App credential·Core token은 운영자가 보안 경로에만
두며, 네트워크 복구 전에는 장비 쓰기를 시도하지 않는다.

---

# Historical goal

현재 작업 트리의 Dashboard 후속 변경을 안전하게 통합하고, 현장 운용을 차단하는 세
항목(Mission Contract 소비자 검증, CRITICAL RiskField 실증거 검증, IFC mm
georeference 이중 배율)을 코드·계약 테스트·원장 증거로 닫는다.

## Scope

- 기존 Dashboard/DSM 테스트 변경의 충돌·중복 검토와 전체 게이트
- Manifold에서 실행 전 Mission Contract 서명·digest·schema·TTL을 fail-closed 검증하는
  구체적 소비자 및 활성화 기록
- CRITICAL 확정 전 등록된 RiskField artifact의 실존, 스토리지 바이트, 계약 내용,
  event 시점·entity 연계를 확인하는 Core 게이트
- IFC mm + georeference의 단위 이중 적용 수정과 설계면 변환 소비자 회귀
- H3/H4 장비 접근 가능성 확인 및 실증거/미검증 상태의 정직한 기록

## Out of scope

- 검증되지 않은 비행·배터리·RTH·카메라·DJI 제어 기능의 지원 승격
- RiskField 3D geometry 합성 정책 자체의 신규 제품 결정
- H2 Cellular Dongle 2/유심 조달
- 프로덕션 배포, Git commit/push/tag/release

## Domain invariants

- INV-011: 계약 활성화 전에 구조·서명·digest·schemaVersion·TTL을 함께 검증한다.
- INV-020: IFC 프로젝트 단위와 map CRS 단위를 섞거나 이중 환산하지 않는다.
- INV-021: 실제 RiskField 증거가 event 시점과 entity를 뒷받침할 때만 CRITICAL 확정을 허용한다.
- INV-010/040/041/050/052: 기존 완료 근거·mock 금지·지원 단계·반출·임무 발급 게이트를 보존한다.

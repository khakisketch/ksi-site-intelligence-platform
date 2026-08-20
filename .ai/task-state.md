# Current Task State (2026-08-20, closed-loop MVP)

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

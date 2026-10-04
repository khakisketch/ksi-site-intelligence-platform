# Protected Offline Application Bundle Implementation Plan

> **For agentic workers:** Role split per updated AGENTS.md: `developer` implements bounded tasks, `reviewer` reviews, `test-runner` runs milestone verification; Primary verifies, commits and integrates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify a frozen-source offline wheel bundle for the three existing host programs, with separately verifiedCPython3.12.15 and installation preparation only.
**Architecture:** A focused shared artifact codec validates bounded wheel/manifest identities. An offline builder freezes the selected source and uses the prepared toolchain; the verifier optionally prepares a new private environment only after genuine explicit Python binding. No global installer, service, API or authority producer is introduced.
**Tech Stack:** existing Python3.12 stdlib, prepared uv0.11.15/build backends, pytest/jsonschema/Ruff/mypy. No new dependencies/downloads or lock changes.
**Spec:** [approved written design](../specs/2026-10-04-external-runtime-application-bundle-design.md).
**State:** Tasks 1–3 delivered plus the Task 4 review fix pass (I1–I4): combined **169 passed/1 skipped**;
Ruff/mypy clean. Remaining Task 4: post-fix full regression, docs, local integration. No completion,
release or installation acceptance is claimed.

## Execution log

- 2026-10-04: Task1 frozen contract authored by Primary: `tests/support/external_application_bundle_fixture.py`
  and `tests/contract/test_external_application_bundle.py` (70 cases incl. resource budgets, ZIP/entry
  safety, fixed entrypoints, distribution/tag/RECORD negatives). RED 70 failed/0.41s retained in
  `.opencode/artifacts/contained-runtime-preparation-20261003/bundle-analysis/task1-red.log`.
  Developer `ses_efa7a4848ffe1i5J3jkFGUPmB0` dispatched for exactly the tool + schema; tests frozen.
- Ruling: the updated AGENTS.md role policy supersedes this plan's earlier preserved-inline note;
  no gate, test or evidence rule is weakened and no new product scope is added.
- 2026-10-04 Task1 GREEN: developer `ses_efa7a4848ffe1i5J3jkFGUPmB0` implemented the tool + schema and
  correctly STOPPED on Primary-owned fixture defects (no test edits, no commit). Primary fixes:
  corrected the `make_bundle` wheel-membership filter, made file kinds spec-exact
  (`workspace-wheel`/`external-wheel`, tool tightened from a union), removed one invalid
  duplicate-bytes test parameter, and suppressed an expected duplicate-entry warning.
  Verified: 69 passed/0.33s; Ruff 3 files clean; mypy tool clean. Commit:
  `feat: verify bounded offline application bundle artifacts`.
- 2026-10-04 Task2 GREEN: developer `ses_efa6ffeedffeGDnJRY7SV56QpO` delivered
  `tools/build_external_runtime_application_bundle.py` + 27 contract tests; TDD RED 26 failed/1 passed
  (the single pass was CLI-misuse exit-2 before the tool existed) → GREEN; Primary fresh re-run
  **96 passed/2.57s**; Ruff + mypy clean. Accepted deviations: read-only git subprocess for freeze
  checks, literal wheelhouse closure-set equality, backend name allowlist, documented canonical
  inventory ordering. Commit: `feat: build source-frozen offline application wheel bundles`.
- 2026-10-04 Task3 GREEN: developer `ses_efa5a2bcbffexVg27BVpca6LqQ` delivered
  `tools/verify_external_runtime_application_bundle.py`,
  `contracts/schemas/external-runtime-python-binding.v1.json`, 61 contract tests + support fixture.
  TDD RED 61 failed/1 skipped (tool unavailable) → GREEN **157 passed/1 skipped/9.49s** (Primary fresh
  re-run); Ruff + mypy clean. Accepted deviations: ancestor checks to the allowed-root prefix (not
  `/`), uv discovered via PATH pinned to 0.11.15 (installer-tool discovery only; no `--uv` flag in
  this CLI), interpreter single-link, native entries may live outside the runtime root with full
  chain checks, `verification_code.commit_sha` = source commit. The genuine-input test is an explicit
  NOT_RUN skip (no protected CPython 3.12.15/wheelhouse); a real offline venv install test genuinely
  blocks at the probe version gate. Commit: `feat: verify protected Python and prepare private
  application installs`.
- 2026-10-04 Task4 review fix pass: reviewer `ses_efa29b790ffe3GXRzFltx1kKol` found no Critical and
  four Important (I1 whole-request read budget, I2 metadata decompression trusting a lying header,
  I3 zero-length wheel entries, I4 runtime symlinks). Developer `ses_efa24bbd5ffeXFgrLGBzQUAzDw`
  fixed all four plus the schema `files.kind` enum; RED 12 failed → GREEN **169 passed/1 skipped**
  (Primary fresh re-run 9.68s); Ruff/mypy clean. Deviations: I2 caps a copied `ZipInfo`
  (`file_size=_MAX_METADATA_BYTES+1`, CRC off) with RECORD digests as the integrity gate; I3 adds
  the empty-digest↔`"0"` pairing plus a bounded emptiness probe; new codes `READ_TOTAL`,
  `LINK_TARGET`, `RECORD_READ`. Commit: `fix: bound bundle reads and support declared empty files
  and runtime symlinks`.

## Global Constraints

- Keep canonical release-evidence v1, host-binding v1/v2, signed/operator/Core/API/image/lock contracts unchanged. Only additive bundle/Python records; no new platform function.
- Deployment source is one fixed40lowercasehex commit. Record build artifact/toolchain and verification-code identities separately; never move an existing candidate merely becausemain/docs/verifier changes. Existing stage still uses its exact clean selected-source checkout.
- Application bundle has onlymanifest.json, uv.lock, requirements.txt andcanonicalwheels/. No interpreter, editable/copiedvenv, checkout, credentials/configs/keys/customer data/helper or mutablecurrent symlink.
- Exactly three prepared global entrypoints: inspector daemon, measurement daemon, validation worker with the spec's exact module:function mappings. Preserve fixed arguments, separate identities, daemonPID/LISTEN_PID/LISTEN_FDS and worker clean-env behavior.
- Pure KSI workspace wheels only (`py3-none-any`) from selected source. BuilderPython3.12-family may build those wheels; it is not deploymentPython. External wheels matchuv.lock and complete target-specific closure offline. No sdist/direct-path/editable/network/source-build fallback.
- Prepared uv0.11.15/buildPython/backend inventories are explicitly hash-pinned. No backend/dependency/systemPython installation merely because a manifest declares it. `uv build` has no`--locked` flag here; freeze source/lock and use prepared no-build-isolation checks.
- Deployment runtime is separately supplied/root-ownedCPython3.12.15/LinuxARM64/GNU, with explicit libcVersion/platformTag and complete protected inventories. NoPATH/home/devcheckout fallback or inferred ABI. Root prefixes exactlyas spec; caller-pinned operator-owned0400/0600 Pythonbinding.
- Static verify executes/imports no application. Optional preparation requires all explicit runtime flags; success stages distinct. No root/global installation, unit changes, Docker/Core/network/raster operation or authority/key/credential fabrication.
- Bundle≤1GiB,≤256wheels, wheel≤256MiB, JSON/metadata≤1MiB, ZIPcentraldirectory≤16MiB,≤65536ZIPentries/wheel, aggregate≤262144entries, declaredexpanded≤4GiB. Runtime≤8192files/1GiB,≤16ancestorsteps/input, nativeABI≤512libraryentries. Probe15seconds/output64KiB; finite whole-request counters, no repeated expansion loophole.
- Preserve all original source/lock/images/reports/archives/helpers/refs/worktrees/private evidence. Reuse existingtaskworktree/ledger, no disposable evidence deletion, no push/publication/deployment.
- First later live product probe is one expressly permittedDSM→actualInspector/worker→durableCoreinspectionresult. Bundles/imports/generated tests do not prove it; current runtime/config/security/signing/Core/credential/containment gates remain open.

## Required implementation packet

Requirement IDs: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/06/08 preparation.
Owner: tools artifact creation/verification, additive contracts and existingprocessing-controller entrypoint metadata.
Acceptance: frozen correct bundle/static proof and optional genuinely supplied runtime preparation; incorrect/partial/host-dependent/substituted inputs block, all external gates remain separate.
Contracts: two new schemas only; no v2/canonical/source/authority wire change.
Reference assets/adoption: existing stdlib safe readers/JSON/manifest/source fixtures, prepareduv; no references imports/edits.
Files: exact file map below. Tests: task RED→GREEN, actual local metadata/bundle evidence where inputs exist, affected/full regressions, one read-only final review and local integration.
HIL/device: none. License/data: retain suppliedtool/wheel/license origins; no customer/raster execution or new license approval.
Rollback: stop new tooling, retain all outputs/receipts; no data deletion or older-version reinterpretation.
Invariants: INV-054 source/lock/wheel/runtime byte links; preserveINV-051/053/055/060.

## File map

| Path | Responsibility |
| --- | --- |
| tools/external_runtime_application_bundle.py (new) | Shared safe readers, strict models, bounded wheel/manifest/static verification; import-only tooling |
| tools/build_external_runtime_application_bundle.py (new) | Frozen source/locked external closure/prepared offline builder CLI |
| tools/verify_external_runtime_application_bundle.py (new) | Static verifier CLI, protected runtime validation and opt-in private preparation |
| contracts/schemas/external-runtime-application-bundle.v1.json (new) | Exact bundle record shape, fixed mappings/resource/type constraints |
| contracts/schemas/external-runtime-python-binding.v1.json (new) | Exact independently supplied protected runtime/inventory record |
| tests/support/external_application_bundle_fixture.py (new) | Tiny labeled wheels/records/source fixture utilities; never genuine release/runtime evidence |
| tests/contract/test_external_application_bundle.py (new) | Real static readers/ZIP/record/resource/source negatives |
| tests/contract/test_external_application_bundle_build.py (new) | Frozen source/lock/offline builder/closure and real tool boundaries |
| tests/contract/test_external_application_bundle_runtime.py (new) | Protected runtime/probe/preparation/wrapper/cleanup behavior |
| Existing runtime README, release/local evidence, spec/plan/ledger/checkpoint | Honest stages/genuine missing inputs and fixed next-release/live target |

## Interfaces

Shared module exports frozen dataclasses (validated before construction):

- `BundleTarget(implementation, python_version, os, architecture, libc_family, libc_version, platform_tag)` — allstrings; exactfixedprofile fields, explicit targetfacts as spec.
- `BoundBundleFile(relative_path: str, sha256: str, bytes: int, kind: str)`.
- `FixedEntryPoint(name: str, module: str, function: str)` — fixed three mappings only.
- `ToolFileDigest(relative_path: str, sha256: str)` and `VerificationCodeSnapshot(commit_sha: str, files: tuple[ToolFileDigest, ...])` — actual requiredthree tool-file hashes, not only a wrapper hash.
- `VerifiedApplicationBundle(bundle_root: Path, manifest_sha256: str, source_commit: str, lock_sha256: str, target: BundleTarget, files: tuple[BoundBundleFile, ...], entrypoints: tuple[FixedEntryPoint, ...])`.
- `BundleEvidenceError(ValueError)` withsafe`.code`/`APPLICATION_BUNDLE_BLOCKED: <CODE>`.
- `verify_application_bundle(root: Path, *, expected_manifest_sha256: str, expected_source_commit: str, expected_lock_sha256: str) -> VerifiedApplicationBundle` — static only; no process imports/installation.

Builder module exports:

- `BuildToolchainPins(uv_path: Path, uv_sha256: str, build_python: Path, build_python_sha256: str, backend_inventory_path: Path, backend_inventory_sha256: str)`.
- `BundleCreationReceipt(manifest_sha256: str, source_commit: str, lock_sha256: str, verification_code: VerificationCodeSnapshot)`.
- `build_application_bundle(repo: Path, *, source_commit: str, wheelhouse: Path, toolchain: BuildToolchainPins, target: BundleTarget, destination: Path) -> BundleCreationReceipt`.

Verifier/preparation module exports:

- `VerifiedPythonRuntime(interpreter: Path, runtime_root: Path, interpreter_sha256: str, inventory_sha256: str, native_inventory_sha256: str, target: BundleTarget)`.
- `verify_python_binding(path: Path, *, expected_sha256: str, target: BundleTarget) -> VerifiedPythonRuntime` — protected static runtime proof before any probe.
- `PreparationReceipt(bundle_sha256: str, source_commit: str, python_binding_sha256: str, prepared_inventory_sha256: str, status: str, verification_code: VerificationCodeSnapshot)`.
- `prepare_application_installation(bundle: VerifiedApplicationBundle, *, python_binding: Path, expected_python_binding_sha256: str, destination: Path) -> PreparationReceipt` — revalidate input identities/stage verified copies; new private destination only, never global deployment.

CLIs use required explicit flags andsafe JSONsuccess/exit0; blockerstdoutempty/safe stderr/exit1; argparse misuse mayexit2:

- Builder: `--repo --source-commit --wheelhouse --uv --uv-sha256 --build-python --build-python-sha256 --backend-inventory --backend-inventory-sha256 --libc-version --platform-tag --destination`.
- Verifier: `--bundle --manifest-sha256 --source-commit --lock-sha256`; optional `--python-binding --python-binding-sha256 --prepare-root` must appear together or reject. No dynamic factory/module/command option.
- Outputstatus onlystage actuallyexercised: BUNDLE_BYTES_VERIFIED or INSTALLATION_PREPARED. Runtimeproof is recorded separately; no service/eligibility/currentrelease success state.

## Review Focus

1. ZIPmetadata budget checked too late: a tiny compressed bomb/hugecentraldirectory/count cannot allocate/decompress before individual AND whole-request ceilings; incoming aliases cannot reset the budget (Task1).
2. Honest wheel names hide the wrong source/lock or incomplete native dependencies: outer manifest rehash still cannot admit unpinned/extra/editable/platform-invalid payloads or a builder-host resolver result as target closure (Tasks1/2).
3. Verified old input is swapped before UV/probe: verify/copy/hash the same protected descriptors into private stage, revalidate all actual-use identities; a cache/status or plausible failed output must not grant authority (Tasks2/3).
4. RuntimePython/native facts differ from declaredtarget or use a home/PATH fallback: version/hash/inventory/ABI and exactroot protection must block before executable preparation; symlinks cannot hide unsafe libraries (Task3).
5. Wrapper starts another child/losesPIDFDs or installs into existing global paths: private preparation must preserve exec/activation/cleanenv semantics and never mutate units/helper/old release; source tests cannot claim actualhostactivation (Task3/4).

---

## Task 1: Independent bounded static bundle codec and schemas

Consumes: spec's exact bundle fields, provided manifest/source/lock pins and byte-bound wheel files.
Produces: shared frozen models/`verify_application_bundle`, additive bundle schema, synthetic fixtures.

- [ ] Write `test_bundle_static_verification_accepts_three_fixed_entrypoints_without_execution`: tiny generatedwheel withliteral three mappings, source`a`×40, targetCPython3.12.15/Linuxarm64/GNU/libc2.39/platformmanylinux_2_39_aarch64. Bind actualfixture bytes/hash and lock; result returns same three mappings/source. Guardsubprocess/process-launch so any static invocation fails. Missingtool is the intendedRED.
- [ ] Run `.venv/bin/python -m pytest -q tests/contract/test_external_application_bundle.py`; ExpectedRED because sharedtool not implemented, not bad fixture/import.
- [ ] Implement models andsafe regular-file same-descriptor hash/read/recheck, strictJSON/version/exactkeys, inventory/file/hash/size/source/lock checks. Define schema root/nestedfields exactlyas spec; useDraft202012Validator fixture tests. Wire fields camelCase, Pythondataclass fields snake_case; metadata values never grant authenticity.
- [ ] Add beforeimplementation tests for pathsymlink/FIFO/directory/substitution/truncate/grow, bool/fractional/oversize inputs, extra/missingfiles, lock/source mismatch, invalid fixedmapping, duplicateJSON/root fields and stablecleanup. ExpectedRED for each missinggate; thenminimalGREEN.
- [ ] Add `test_rehashed_wheel_metadata_or_record_conflict_blocks`: rebind outermanifest afterinner name/version/tag/RECORD/entrypoint mutation. Assertinner typedblocker, notmereouterhashfailure. Rejecteditable/direct-path/sdist/non-pure KSI sourcewheel, native tags incompatiblewith declaredprofile; no code import/extraction.
- [ ] Add `test_zip_limits_apply_before_allocation_or_metadata_expansion`: forgeEOCD/count/centraldirectory, metadata bomb/duplicate/traversal/symlink/special/RECORDinventory conflict, individual+aggregate count/byte/work budgets; guardedread requests≤1MiB. Readboundedcentraldirectory beforeadvancedZIPparser, validateentrytypes/offsets, thenbounded metadata only. Budget counters live perrequest, memoization byverified fileidentity; validateincomingreferences evenwhencached.
- [ ] Run wholeTask1 GREEN, changedfileRuff/sharedmodulemypy/schema checks; Expectednofailures/errors. CommitonlyTask1 files: `feat: verify bounded offline application bundle artifacts`.

## Task 2: Frozen-source offline bundle builder

Consumes: Task1sharedverifier/models/schema; currentGit source/uv.lock, explicit preparedtoolchain, existingexternalwheelhouse.
Produces: builderfunction/CLI andgenuine source-wheel/preparation receipts wheninputs exist. No installedPython or globalartifact.

- [ ] Write `test_builder_freezes_named_source_without_mutating_lock_or_old_output`: tiny temporaryGitworkspace withtracked manifests/source andignored hostileextra files; explicitpreparedtool pins. Assertonlyallowedselected-sourceinputs, source/lock hashes unchanged, destinationcreateonce, no originalwheel/source replacement. Missingbuilder isRED; testtool seams mustremain explicitlysynthetic.
- [ ] Run `.venv/bin/python -m pytest -q tests/contract/test_external_application_bundle_build.py`; ExpectedmissingbuilderRED.
- [ ] Implement `build_application_bundle` usingexact cleanselectedGitcommit/tree andconservative base workspaceclosure from uv.lock names/declaredbase dependencyedges; marker resolution remainsuv's. Validateeveryselectedmember path/source/manifest andbuild-backend pins beforefreezing. Newprivate allowlistedcontext only; excludereferences/env/keys/configs/localstate/testinputs. No silentstash/index/source cleanup.
- [ ] Usepreparedhash-pinneduv0.11.15 offline/noPython-download behavior in an allowlistedcleanenvironment with task-privateHOME/cache; stripambientVIRTUAL_ENV/PYTHON*/UVconfig/index/auth overrides. Exportexternal requirements using `uv export --locked --no-dev --package ksi-processing-controller --no-editable --no-emit-workspace --format requirements-txt`; frozenprojectconfiguration remains the source of approvedworkspace settings, checklockbefore/after. Buildselectedpure workspacewheels via supported`uv build --python <explicit> --no-build-isolation --wheel --package <name> --out-dir <private>`; nofake--locked/no backend install. Missingpreparedbackend returnsblocker.
- [ ] Select suppliedtargetcompatibleexternalwheel identities fromuv.lock, copy via protecteddescriptors into privateoutput, requireexactwheel hashes/name/version/metadata. Appendexactlocalworkspaceversion/hash requirementstoexportedrequirements. Useexistinguv's offline `pip install --dry-run --require-hashes --no-index --find-links <privatewheels> --only-binary :all: --python <verified-build-python> --python-version 3.12.15 --python-platform <explicit supported GNU target> --target <private-plan-only-target> --no-config -r <requirements>` toprove completeclosure; nopython-marker reimplementation/network/sdist/backend fallback. ExplicitPython/cleanenv avoidambientvenv; targetversion/platform describe resolution, not deploymentruntimeproof. Dryrun maycreate onlya private target`.lock`; no packagesinstalled, no globalwrites.
- [ ] Add `test_incomplete_or_rehashed_target_closure_cannot_become_bundle`: missingtransitive/wrongarchitecture/hash/extra distribution/directpath, swappedtool/source/lock, dirtycheckout, ignoredsecret leakage, nonzeroUVwithplausiblestdout, outputalreadyexists, requestedunknownplatform andhostileambientVIRTUAL_ENV/UVconfiguration. ExpectedRED thenminimalclosedhandling/GREEN. Rejectunsupportedexplicittarget; never deriveitfrombuilderhost. Useactual localUVcommand wherepossible; a small pinned wheel/resolver fixture is not a genuineapplication bundle.
- [ ] Emitexactmanifest/source/toolchain inventories andfixedentrypoints, invokeTask1verifier on completedoutput beforepublishreceipt. Recordbuildtoolchain vs verificationcode versions separately. Sourcefreezewheel completionis not releaseapproval; retainedprivatefailure/context records remainhonest.
- [ ] Run Task1+2 GREEN/Ruff/mypy onnewownedtools; Expectednofailures/errors andnopyproject/uv.lock/image diff. Commit: `feat: build source-frozen offline application wheel bundles`.

## Task 3: Protected Python input and private installation preparation

Consumes: Task1staticbundle proof andindependentlysuppliedcaller-pinnedruntime record; noPATH/discoveredPython.
Produces: Python-binding schema/validatedruntime andoptionalprivatepreparation CLI/receipt; no root/globalinstallation.

- [ ] Write `test_missing_or_wrong_runtime_binding_blocks_before_any_probe`: staticbundleverification succeedswithoutPython; addingpartialruntimeflagset, wrongversion/hash/root/owner/libraryinventory/ABI orhome/devPATH candidate failsbeforeprobe. Missingruntimevalidator/preparer isRED; fixtureslabelsyntheticroot/stat/probe observations, neverhostacceptance.
- [ ] Run `.venv/bin/python -m pytest -q tests/contract/test_external_application_bundle_runtime.py`; Expectedmissingruntime/preparerRED.
- [ ] ImplementstrictnewPythonbindingschema and`verify_python_binding`: operator-owned0400/0600record; actualroot-ownednon-group/other-writableruntimeunder exacttwoallowedprefixes; explicitresolvedinterpreter/libraries/standard-library inventories. Fullhashes/lengths/mode/ancestor/count/total-read budgets matchactualfiles; noauto-provision/discovery or unverifiedsymlink. Returneddata isnotreusableauthorityafterinputchange.
- [ ] Implementoptional`prepare_application_installation`: allthreeCLIflags requiredtogether; newprivateoutput only. Revalidatesbundle/runtimeactual-use identities, copiesverifiedwheel bytes sameFD into privateimmutable stage, creates a newprivate noneditableenvironment with explicitverifiedPython/preparedUVofflinewheel-only/noindex/no-build/no-download path. Useonlyfixedprobe code withisolatedclearenvironment; no Core/Docker/listener/app main/raster open.
- [ ] Add `test_probe_timeout_or_nonzero_with_good_stdout_never_grants_runtime`: fixed15second deadline/output64KiB, expectedCPython3.12.15/ARM64/GNU/libc/nativeclosure, wrongobservations/malformedoutput block. Reap ownedgroup onfailure; incompletecleanup retainsownedpath withtypedblocker, no broaddeletion. Actualnativeimportproof remainsmissingif realPython/inputsabsent.
- [ ] Add `test_private_wrappers_preserve_exec_pid_activated_fd_and_clean_env`: runnewprivatepreparedfixture wrappers withlabelledsafeprogram/pinnedexplicitinterpreter; assertPIDunchanged/inheritedFD readable/LISTEN_PID andLISTEN_FDS unchanged. Threefixedmappings/args only, no dynamicfactory or ambientPATH/PYTHONPATH/HOME dependency. ExpectedRED ifwrapperforks/dropsFD/usesambientruntime; implementexec-only fixedpathbootstrap. No installedunits/helper/globalpath changes.
- [ ] Add `test_verified_inputs_swapped_before_prepare_are_not_cached_authority`: manifest/wheel/runtime/inventory/tool substitution duringactual-use, oldsuccessreceipt, symlinkedexistingdestination, declaredexpanded>4GiB, wholeinventory/walk budget andprobefailures. ReturnnoINSTALLATION_PREPARED onanyfailure. Rehash/stability-check stagedfiles andexplicitruntimeagain before finalreceipt.
- [ ] Emitprivate`preparation.json`/sortedinstallinventory forfutureoperator: boundsource/bundle/Python/requiredfile hashes/status INSTALLATION_PREPARED only. Fixedglobalpaths areplan entries, notcopytargets. StateBUNDLE_BYTES_VERIFIED separatelywhenruntime unavailable. Runall3newtestfiles/Ruff/mypy/schema checksGREEN; commit`feat: verify protected Python and prepare private application installs`.

## Task 4: Real evidence, single independent review and local integration

Consumes: committedTask1–3source, approvedspec, actuallysuppliedtool/wheelhouse/runtime facts.
Produces: verifiedsource/evidence andauthorized localintegration; actualproductexecution remainsexternallygated.

- [ ] RevalidateGit/currentledger/owner/source/tool identities; inspectonly task-scopedpreparedinputs. Actualbackend/wheelhouse/runtime supplier absence is anexplicitblocker. Continueindependentsourceverification; do not acquiretools/Python/packages,build/loadnewimages,readcustomer/publicTIFFs orfakeprovisionauthority.
- [ ] Wheregenuineinputspermit, freezeonecandidate sourcecommit andbuild/verifybundleonce; recordbuilder/verifiercommit/filehash separately. Rehashoriginalsource/lock/inputs; demonstratebadsource/lock/wheel/platform/runtime pins blocked. IfexplicitPython3.12.15isabsent, genuineINSTALLATION_PREPARED/nativeclosure remainsNOT_RUN; truthfulBUNDLE_BYTES_VERIFIED isnotaninstalledapp.
- [ ] Run wholepreparedtaskPython withcommand-localumask022/offline/nosync/nodownload, logscreated0600beforetestmask. Recordactualrevision/count/time/skips/warnings/failures. Systematicdebugging/TDD scopedrepairs only, no skips/weakenedproduction/SDK permissiongates.
- [ ] ObtainONE independentread-onlywhole-unit review withactualBASE/HEAD/spec/plan/ReviewFocus/rulings/receipts, no per-taskagent/modeloverride. Regradebyeffect; oneCritical/ImportantRED→GREEN repairpass plus affected/fullregressions; minors/rulingsdeferredrecorded. Neverreview-impliedactivation.
- [ ] UpdateexistingREADME/release/localops/spec/plan/ledger withdistinctsuccessstages, frozenreleasecandidateprotocol, supplier/security/host/config/authority blockers andfirstactualDSM→Inspector→Core target. Checklocallinks/anchors/diff; no checkpoint/rawprivateevidence/secrets inGit.
- [ ] Recheckagreedlocalmain HEAD/status/index andtaskownedrange; safefast-forward onlywithinexistingauthorization, recheckintegratedaffected/fullsource. Preserveall4existingworktrees/originalWIP/refs/data/evidence; no push/publish/cleanup.
- [ ] Finalreportseparatescompletedtoolsource, anygenuinebundle/runtimepreparation, actualhostinstallation andfirstliveproductacceptance. Do notrunactualDSMwithoutgenuineinputs andseparatecontainment/activation/testdata authorization; showthespecificremaininginputinstead ofinventinganother broadproductmilestone.

## Pre-flight and self-review

- Task1→Task2: fixedtuplemodels/bytes/source/lock/target/threeentrypoints agreewithmanifest; builderinvokesstaticverifier, notaprocessingservice.
- Task1/2→Task3: validatedproofis recheckedatuse, notcachedauthority; runtimeflagsallornone/privateoutputonly; noPythoninapplicationbundle.
- Task3→Task4: INSTALLATION_PREPARED excludesglobaldeployment/hostcontainment; missingrealruntime isNOT_RUN, notpassbysyntheticprobe.
- Specsections1–3/7 mapconstraints/fixedsource/actualproductgate;4–5 mapTasks1–3schema/builder/runtime;6mapsnegatives/full/review/integration.
- Interfaces/wire/Pythonnames andresourceconstants matchspec; purebuildPython vs deploy3.12.15 explicit; stage/canonical/image/lockunchanged. No undefinedprovider/signer/credentialsupplier or impliedinstallation/acquisition.
- ReviewFocuseach hasownednegatives; contextverifieduv0.11.15supportslistedexport/build/pip flags andlacksbuild--locked. A flag/table isnotaverifiedbuilder/runtime result.
- Verificationreceipts includeallthreeactualrequiredtool-file hashes, notjustentryCLI; syntheticunit
  code/source snapshots remainlabelled and cannotbe usedas a genuinecommittedrelease receipt.
- Actualemptyrequirements UVdryrun confirmedflags/no packageinstallation butcreatesprivate`.lock`
  andotherwiseusesambientvenv; fixedexplicitPython/cleanenv/pip--no-config andprivatetarget assumption.
  Retainedprobe iscommand-format evidence only, notrealclosure/Python3.12.15/nativeacceptance.
- Writtenplanapprovalstillrequired; the Human's writtenspecapproval authorizesplanningonly. Preserveddirectmethod, noexecutorquestion ornewnativegoal.

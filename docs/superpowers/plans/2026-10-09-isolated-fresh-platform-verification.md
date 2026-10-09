# Isolated fresh platform verification — Implementation Plan (P7 proposal)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans with the already selected sequential inline method. Steps use checkbox (`- [ ]`) syntax for tracking. Independent final Reviewer/Test Runner remain required. This proposal is not execution authority.

**Status:** PROPOSAL FOR HUMAN WRITTEN REVIEW — not approved or executed. P6 is locally closed at source `12547470e5c1abfa2a5b232995429a6c0bf4bb25`, record commit `4a0a08ed1f47b5e66b2b0a42d7f3f2ea0936c9bb`. Actual approval belongs in the [parent ledger](2026-10-07-agent-first-platform-rebaseline.md), tied to this plan's SHA256; goal continuation alone grants no installation or runtime effects.

**Goal:** Obtain revision-bound fresh dependency, candidate-image and isolated Core/storage boot evidence without changing product sources, existing environments or customer data.

**Architecture:** Use a task-owned detached checkout of `4a0a08ed1f47b5e66b2b0a42d7f3f2ea0936c9bb`, a new Python environment/cache and the unchanged three Dockerfiles. Start only the default three-service Core/storage graph under a unique temporary Compose project, with scratch-only port/security overrides and newly generated test credentials. Preserve every failed or unverified gate; this is not production deployment or the first customer flow.

**Tech Stack:** Prepared Linux `aarch64`, existing Python 3.12, uv `0.11.15`, Docker CLI/Compose `v5.2.0`, current locked Python workspace, existing production Core factory and pinned BusyBox/MinIO images. No CLI, Python, browser or host-package installation.

**Spec:** [Approved Physical Site rebaseline design](../specs/2026-10-07-physical-site-platform-rebaseline-design.md), SHA256 `14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`, §§2–4,6,8–10. ADR-KSI-036/037/038/039 and current contracts remain authority. This proposal covers only missing fresh-environment evidence, not all RB-01..09 or F-01..04.

## Global Constraints

- “Flight, autonomous acquisition, tactical perception/control and customer production reconstruction are outside long-term Site Intelligence responsibility” — no archived runtime, managed worker or NodeODM build/start/import.
- “Preserve identities and current API behavior during extraction.” No product source, lock, digest pin, profile, public API, auth/consent rule or serialized record changes in this verification plan.
- “Existing V1 strict and V2 provisional/evaluation rules and numerical meanings remain unchanged.” No numerical calculation, alignment, accuracy claim or synthetic substitute for permitted customer epochs.
- “Private state, credentials, originals and foreign worktrees” are protected in place. Never copy the original `.venv`, `.env`, user profiles, private artifacts, signing keys or existing volumes into this trial.
- “No new dependencies or host installation are implied.” The separate approval requested here is limited to installing **already locked** dependencies in new scratch environments/images, not adding dependencies or modifying the host.
- Current local target remains `main`. No push, registry publication, production deployment, CI dispatch, remote host, real grant/activation, device operation or customer contact.
- Platform production remains `ksi_core.composition.platform_production:build_platform_production_app`; external worker HTTPS/signed-manifest/UDS/containment requirements are not bypassed for a localhost demonstration.
- Existing P4 render/functional evidence remains unchanged-input **REUSED**, not a fresh browser or real-byte Console claim. No visual changes or design run in P7.

## Review Focus

1. **Contaminated installation:** a fresh environment must have no installed editable path to the original checkout or five retired roots; pin this in Task1 metadata/path assertions.
2. **Private build input:** untracked credentials, archive, references and foreign worktrees must not enter the image context/runtime import closure; pin fresh-checkout and image assertions in Tasks1–2.
3. **Wrong Docker ownership:** a top-level Compose `name: ksi` or reused volume must not affect existing services/state; pin merged config and every created resource's project labels in Task3.
4. **False persistence/auth proof:** a healthy response is not evidence of journal replay, storage persistence or tenant non-disclosure; pin TCP create/read/duplicate/denial checks before and after Task3 restart.
5. **Overstated readiness:** unavailable wheels/pinned snapshots, missing Analysis/SpatialData activation or synthetic-only results must remain failed/unverified, not trigger a pin/lock/security waiver; pin gate status and claim limits in all three receipts.

## Requirement and effect contract

| Required field | Binding |
| --- | --- |
| Requirement IDs | RB-03 boot-only evidence, RB-05/06 bounded Site-journal restart, RB-08 fresh install/build/active checks, RB-09 revision-bound independent evidence |
| Owner modules | Root workspace/build, `services/core/`, `services/processing-controller/`, `deploy/`; product sources are read-only |
| Acceptance criteria | New locked environment works without archive/old editable paths; three unchanged candidate images build; real isolated Core authenticates and persists a synthetic Site; new object-store bytes survive restart; failures/skips/limits and ownership reconcile |
| Contracts affected | **None changed**; current factory/environment, auth/Sites HTTP and image/worker entrypoint contracts are exercised only |
| Reference assets | Exact current tracked sources, P6 receipt `58a17d1f…`, P4 reused evidence, broad-type control `546479e8…`; reference submodules remain uninitialized/read-only |
| Adoption decisions | Reuse current factory, locked dependencies, Dockerfiles and base Compose; no copied demo server, historical script, new profile or new analysis backend |
| Files to change | Only final report plus parent-ledger/audit/product-state status summaries; ignored checkpoint and scratch proof are not committed |
| Tests | Task1 fresh active Python/static suite; Task2 image import/packaging probes; Task3 real TCP auth/tenant/idempotency and restart probes; independent evidence reception |
| HIL/real-device assumptions | None; no equipment connected or operated; software proof cannot establish host/kernel containment, field accuracy or customer acceptance |
| License/data implications | Downloads/builds use only lockfile indexes and pinned Debian/image sources. No model weights, customer exports or commercial processing. Existing license/AGPL boundaries unchanged; no publication |
| Rollback | Stop/remove only owned trial containers/network; preserve trial volumes/evidence by default; remove only a verified clean task-owned detached worktree. No original environment/data restore or broad prune required |

Approval explicitly permits the following **new local effects**, within these bounds:

- One detached worktree at `.worktrees/p7-fresh-verification-20261009`; scratch root `/tmp/opencode/p7-fresh-verification-20261009` with mode0700. If either exists, inspect ownership/status and safely reuse only this task's recorded state; never overwrite an unfamiliar path.
- Public network downloads of existing locked packages/build dependencies, digest-pinned Python/uv/BusyBox/MinIO images and the Dockerfiles' fixed Debian sources. No credentials/private index, paid cloud, model download or host install. A credential challenge or unavailable pin is a blocker, not permission to use the user's accounts or another source.
- Three uniquely tagged local candidate images and corresponding daemon build-cache writes. `--no-cache --pull` avoids build-layer reuse but **does not create a pristine Docker daemon**; exact base blobs may already be present. No daemon restart, privileged runtime, Docker-socket mount, registry push or global cache prune.
- One unique Compose project `ksi-p7-<12hex-run-id>`, one private network and only newly created data/object volumes with matching project labels. Short-lived image-import/storage probe containers use only this task's resources. Core/MinIO publish API ports only on `127.0.0.1` with dynamically assigned ports; no public/tailnet listener, Dashboard/Caddy, MinIO console publication or existing volume mount.
- Temporary random OPAQUE test credentials for FIELD_OPERATOR/VIEWER in a synthetic organization plus VIEWER in a separate synthetic organization, and local MinIO credentials; TTL24h, files0600. These exercise an existing auth mode **only in scratch**, not OIDC onboarding, real users/grants, Mission trust, Analysis activation or external worker authority.
- Expected cold-run cost: roughly1–3hours, several GiB of downloads and up to60GiB scratch/image storage; no new paid service. Before effects, check availability of60GiB disk headroom and32GiB usable RAM. Runtime limits: Core4CPU/8GiB/256PIDs, MinIO2CPU/4GiB/256PIDs, image/storage probe2CPU/4GiB/256PIDs; init0.25CPU/64MiB/64PIDs. Resource shortfall requires a revised bounded proposal, not deleting other work. Four-hour trial safety rail; report preserved evidence if reached, do not replay completed checks.

## Source and output map

Freeze full tracked-file SHA256/size/mode manifest at the exact source commit, plus explicit hashes for:
`pyproject.toml`, `uv.lock`, all workspace member manifests, `Dockerfile`, `.dockerignore`,
`Dockerfile.external-inspector`, `Dockerfile.external-inspector.dockerignore`,
`Dockerfile.external-measurement`, `Dockerfile.external-measurement.dockerignore`,
`deploy/compose.yaml`, Core/worker READMEs, current platform composition/runtime/auth/Sites sources
and the tests/tools named below. The worktree's branch/HEAD and original checkout's pre/post Git
state are receipt fields; a later documentation-only commit is not a new tested-source claim.

| Output | Responsibility |
| --- | --- |
| `$RUN/freeze.json` | Source/plan/spec identities, protected original-state witnesses and actual prepared capabilities |
| `$RUN/uv.toml`, `$RUN/env/`, `$RUN/uv-cache/` | Isolated configuration, newly installed environment and initially empty dependency cache |
| `$RUN/task1-receipt.json` + exact logs/XML | Fresh install, metadata, full active tests and static gates |
| `$RUN/task2-receipt.json` + build/import logs | Three source-bound candidate image IDs, architecture, import/packaging checks and failures |
| `$RUN/compose.override.yaml`, protected `$RUN/trial.env` | Scratch-only runtime overrides and ephemeral credentials; never a product deployment template |
| `$RUN/task3-receipt.json` | Owned resources, sanitized merged configuration, HTTP/byte digests, restart evidence and teardown limits |
| `docs/audit/PHYSICAL_SITE_FRESH_ENVIRONMENT_VERIFICATION_P7.md` | Durable sanitized results, exact argv, revision, proof hashes, open gates and replay instructions; create only after execution approval |
| Parent ledger / integrated audit / product-state | Actual approval, result links, gate disposition only; no slice/milestone/customer-acceptance change |

Each command receipt records `argv`, `cwd`, start/end, exit, source/plan hash, log SHA256 and
`passed|failed|unverified`. No shell tracing, raw environment/token output or unsanitized Docker
configuration in durable records. Scratch drivers may be written only after approval; record their
exact bytes/hash with the evidence. No production code is implemented, so verification assertions
replace artificial TDD failure; a failed real gate is never changed to green by editing its guard.

### Task 1: Fresh locked workspace evidence

**Files:** Consume frozen workspace/tests/tools; create Task1 scratch outputs and a first report section only. No original environment or product-file modifications.

**Interfaces:** Consume exact source/spec/approved-plan hashes. Produce `freeze.json` and `task1-receipt.json`, including absolute worktree/environment paths for Tasks2–3.

- [ ] Record original checkout HEAD/status/index/worktree inventory and prepared CLI/interpreter paths. Verify local Docker endpoint is still `unix:///var/run/docker.sock`; daemon reachability is not yet proven by previous CLI metadata. Confirm native uv flags from installed help. Do not print private config/environment.
- [ ] Create the owned detached worktree at the exact source commit; no submodule initialization. Freeze tracked hashes, ensure no unexpected untracked/private files and archive exclusion; create new scratch/cache/environment directories. Use existing Python3.12's base executable, not an interpreter installation or inherited site-packages.
- [ ] Generate `$RUN/uv.toml` from the source's `[tool.uv]` filesystem settings: preserve `exclude-dependencies`, `index`, `extra-build-dependencies`; project-only `package`, `workspace`, `sources` remain in unchanged `pyproject.toml`. Assert exact semantic equality for preserved settings. Use explicit `--config-file` so no user/system settings are merged; **do not use `--no-config` or `--no-sources` to lose project rules**. If installed uv disagrees about metadata/config handling, report that preflight failure before network sync rather than rewriting the lock.
- [ ] In a minimal environment with no `PYTHONPATH`, inherited UV/PIP/AWS/KSI/token variables or credential/profile access, run from `$WT`:

```text
uv --config-file "$RUN/uv.toml" --no-python-downloads lock --offline --check
uv --config-file "$RUN/uv.toml" --no-python-downloads sync --locked --all-packages --python "$PYTHON312"
```

Set only controlled `PATH`, isolated `HOME`/XDG directories, `UV_PROJECT_ENVIRONMENT=$RUN/env`,
`UV_CACHE_DIR=$RUN/uv-cache` and `UV_NO_ENV_FILE=1`; preserve recorded ambientumask0002 for tests,
with the scratch parent0700. Expected: exit0, unchanged lock/source, new environment path and157
locked package records. Resolver/index/architecture failures remain actual failures; never install
from an unpinned fallback, add extras or sync the original `.venv`.

- [ ] Assert `sys.prefix == $RUN/env`, no original `.venv`/retired source in installed editable URLs or `sys.path`, and all seven `services/processing-controller/pyproject.toml` entrypoints load as callable from the **new** worktree without calling their polling/protocol `main()`. Load Core, Analysis MCP and Spatial Data MCP imports; reject archived/acquisition-only module prefixes. Persist normalized package/version/path evidence, not secrets.
- [ ] Independent Test Runner runs once in the new environment, using its Python directly to avoid auto-sync:

```text
"$RUN/env/bin/python" -m pytest -q -p no:cacheprovider -rs --junitxml="$RUN/fresh-active.xml"
"$RUN/env/bin/python" tools/check_core_module_boundaries.py
"$RUN/env/bin/python" tools/validate_repository_normalization.py --check-r3-migration
"$RUN/env/bin/python" tools/check_runtime_image_pins.py
"$RUN/env/bin/python" -m ruff check .
"$RUN/env/bin/python" -m mypy --follow-imports=silent tests/contract/test_platform_deployment_template.py tests/contract/test_vm_deployment_contract.py tests/contract/test_runtime_image_pins.py
"$RUN/env/bin/python" -m mypy packages services tests tools
```

Expected active baseline:6058passed/30skipped/98warnings/0failed at the same product source;
record actual node IDs/counts/skips/warnings, not an assumed match. No archive discovery, no live
S3/model/bundle/root-only fixture invented to remove skips. Record architecture/environment deltas
with actual causes. Compare broad mypy `(file,message)` Counter against controlSHA
`546479e8501427592ac20d842058ad7c424a76171e0b7f72898052cf5d4378ef`; baseline109/14 remains
FAILED, not an allowed new diagnostic. Unavailable control is an explicit comparison gap.

- [ ] Rehash frozen inputs/original-state witnesses and save Task1 receipt. Primary receives actual logs/hashes rather than rerunning the completed full suite. Store sanitized results in the new audit report and make a task-owned local record commit; do not commit scratch environment or checkpoint.

### Task 2: Three unchanged candidate images

**Files:** Consume the three Dockerfiles/ignore files and frozen clean worktree; create Task2 build/probe receipts and report section only.

**Interfaces:** Consume `freeze.json`; independent of successful host dependency installation. Produce local candidate references and image IDs for Task3; inspector/measurement images are packaging evidence only.

- [ ] Confirm prepared Docker daemon/build capability and empty task Docker CLI config. Use `docker --host unix:///var/run/docker.sock --config "$RUN/docker-config"`; no imported registry credentials or remote builder. If a required CLI plugin/daemon/build capability is unavailable, report it; do not install/restart/change context or permissions. Inspect remaining scratch/disk limits.
- [ ] Build from `$WT` with unchanged Dockerfiles. Each candidate uses `--pull --no-cache --platform linux/arm64`, its own `--iidfile`, unique tag `ksi-p7-<lane>:<source12>-<run12>` and source/run labels. Exact lanes: Core=`Dockerfile`, inspector=`Dockerfile.external-inspector`, measurement=`Dockerfile.external-measurement`. Save exact argv/log/timing/IID. No overwrite of an existing image tag, fallback base version, Dockerfile edit, registry push or new build dependency.
- [ ] Inspect each completed image's OS/architecture, local image ID, base/source identity and default User/Cmd. Resolve the image's named default user via its own passwd data/probe: assert Core UID10001 and its exact factory CMD, inspector UID10003/entrypoint and measurement UID10004/entrypoint, not that `Config.User` is a numeric string. A local image/config ID is **not** a published OCI RepoDigest or signed release.
- [ ] Run import-only probes using each exact image ID: `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --cpus 2 --memory 4g`, scratch-only tmpfs and `/app/.venv/bin/python` as probe entrypoint. No listener, socket mount, signed execution manifest, daemon, worker loop or inspection/measurement job. Assert required modules/console-script targets load; no `archive/`/`references/` image input, retired installed editable path or acquisition-only import. Distinguish packaged files from imported closure. Remove only these owned probe containers.
- [ ] Bind successful candidates and every failed build/probe to source/log/input hashes. Continue unaffected lanes rather than replaying a deterministic unavailable pin. Record report section/local commit. Do not call packaging/import success external worker containment, TLS/UDS/ACL acceptance or numerical readiness.

### Task 3: Isolated real boot, auth and persistence

**Files:** Consume successful Core candidate, base Compose and Task1/2 receipts. Create scratch override/env/HTTP driver/Task3 receipt; complete audit/status records only.

**Interfaces:** Consume exact Core image ID and project/resource ownership manifest. Produce real TCP/auth/restart and owned-state evidence plus independent final receipt; no Site/WorkArea OIDC bootstrap policy decision.

- [ ] Generate only scratch credentials/organization IDs and a new Site payload. FIELD_OPERATOR/VIEWER use organization `p7-org-<run12>`; foreign VIEWER uses `p7-foreign-<run12>`. No ADMIN or MCP wildcard grant, signing/activation trust, real account or customer token. Use current principal-digest format, role values and `notAfter`; files0600/TTL24h. Explicit `KSI_CORE_HUMAN_AUTH_MODE=OPAQUE` is isolated test mode, **not** F-01 OIDC acceptance.
- [ ] Merge `$WT/deploy/compose.yaml` with `$RUN/compose.override.yaml`, using explicit `--project-name ksi-p7-<run12>` and protected scratch `--env-file`/`KSI_DEPLOY_ENV_FILE`. Override only: Core build removed with `!reset`, image set to built candidate (`pull_policy: never`); Core/MinIO restart=`no`; `ports: !override` publishes only target8000/9000, `host_ip: 127.0.0.1`, `published: "0"`; volume declarations `!override` contain only new `ksi-data`/`ksi-objects`; default network is internal. Core read-only root/tmpfs, cap-dropALL/no-new-privileges and CPU/memory/PID limits; MinIO scratch-only volume plus limits. Init retains only its current root/chown action against the **new** data volume. No host bind/sock/device/privileged/network-host/external volume.
- [ ] Before any `up`, parse protected merged config: service set exactly `{init-volumes,core,minio}`, correct candidate ID, loopback-only ports, no ODM/worker/dashboard/caddy, no existing explicit volume/network name and no private mount. Ensure the unique project/resources do not pre-exist outside recorded task ownership. Record only sanitized configuration/hash. Pull only the exact BusyBox/MinIO digests already pinned in base Compose; never start the ordinary `ksi` project.
- [ ] Start init/MinIO first; verify created volume/network/container ownership labels and obtain actual loopback S3 port. Configure scratch Core with its new data volume, internal MinIO endpoint, bucket `ksi-p7-<run12>`, new AWS credentials/metadata-disabled, opaque principal digests and docs=false. Omit all Mission/device/Analysis/external-authority paths. Use the candidate Core image's installed boto3 in a short-lived, owned `compose run --rm -T --no-deps --entrypoint /app/.venv/bin/python core -` storage probe; create only that bucket and write exact bytes `KSI P7 synthetic persistence probe\n` under `p7/<run12>/probe.txt`, saving SHA256. No original environment dependency or storage mock. Start Core from its unchanged CMD; readiness200 required within180s. Do not fix a connectivity failure by weakening internal-network/loopback/security boundaries.
- [ ] Through actual TCP HTTP, with headers read from protected files and never logged, assert: missing/bad bearer401; valid operator/viewer whoami200; operator creates `p7-site-<run12>` with current SiteFrame `{crs: EPSG:5186, verticalDatum: KNGeoid2018, unit: meter, transformVersion: 1.0.0}`→201/UNMAPPED; viewer read200; duplicate create409/DUPLICATE_SITE_ID; viewer create403; foreign existing Site and nonexistent Site both404 with equal nondisclosing response; foreign list excludes it. `/openapi.json` is not exposed; authenticated known Mission/Edge route probes must not expose acquisition services. No fake Analysis result/eligibility or fabricated historical result.
- [ ] Restart only this project's Core/MinIO, retaining exactly the same owned volumes/credentials/image. Require readiness200, same Site identity/status/organization-scoped visibility and duplicate409 via HTTP after replay; use the same owned storage-probe method to retrieve the S3 object and compare exact bytes/SHA256. Assert the actual Core container's image ID matches the frozen candidate. The HTTP driver uses only the prepared base Python's standard library. This is **one synthetic journal/storage restart trial**, not customer `t0/t1`→`t1/t2`, rights/revocation or two-cycle result acceptance. A direct S3 byte probe is not evidence of the product's full evidence-upload path.
- [ ] Independent final Reviewer checks unchanged product inputs, merged graph/resource ownership, auth/no-disclosure assertions and all five Review Focus items. Independent Test Runner performs/rechecks the live changed-flow probes once on the recorded candidate state and finalizes receipts; reuses already completed matching Task1/2 outputs. Require actual argv/exit/log hashes and pre/post state, not source review or a health response alone. No redundant full-suite replay.
- [ ] Stop/remove only the exact owned trial containers/network after receipt capture; never `down -v`, `--remove-orphans`, daemon/global prune or removal of existing volumes/images. Retain trial volumes/images/evidence for inspection, recording labels/IDs/size and shutdown status. Remove only the verified clean task-owned detached worktree after durable source/receipt identity is preserved; retain if dirty/missing evidence. Final local record commit excludes secrets/checkpoint/scratch. Recheck record links, original clean/index state and affected record consumers.

## Invariants and limits

| Invariant | Enforcement in this plan |
| --- | --- |
| INV-040 | Unchanged production factory/real image/TCP server; failure is not replaced by dev assembly, mock transport or demo result |
| INV-054 | Exact existing external image version+digest; source-bound local candidate IDs clearly labeled, no pin substitution or release claim |
| INV-060 | Organization derived from test principal, foreign HTTP404/list omission before/after restart; no existing grant changes |
| INV-020/024/050/051/053/055/061 | Preserved source/contract/full-active checks only; no real observation/job, LLM egress, measurement or safety action. Fresh full suite does not establish their customer/host acceptance |

P7 can improve RB-03 **boot** and RB-08 **fresh install/build** evidence, not close RB-03's
activated data/analysis path, RB-04 customer API/MCP parity, full RB-05/06, RB-07 fresh real-byte
Console, real production host/security/AMD64/CI gates, or RB-02's strict two-adaptation hash failures.
Broad mypy, archive failures and P6's three deferred minor findings remain separate dispositions.
Customer-owned permitted same-Site `t0/t1/t2`, rights, selected consumer/host and protected Analysis/
worker configuration plus OIDC bootstrap/grant ownership still require the responsible Human/customer/
ops/security inputs. A successful synthetic boot cannot satisfy those gates or complete the goal.

## Recovery, self-review and approval handoff

- Recover scratch path/driver/report mistakes within this fixed contract, rechecking affected evidence. Product defects, unavailable pins/wheels, architecture changes, credentials, host preparation, lock/dependency/security/policy or broader effects require a concrete finding and scoped decision; do not silently change immutable inputs. Continue safe independent tasks where possible.
- Preserve terminal logs and interrupted output first. Resume only missing receipt/probes at the same source/resources; no blind replay of full tests/builds. Four-hour/no-progress stopping records actual status, cause, retained resources and responsible next decision, never an invented pass.
- Self-review: exact frozen source and five Review Focus classes are mapped; tasks share only explicit receipt/image/resource interfaces; no source implementation or extra universal-State/analysis feature. Remaining spec requirements are consciously excluded, not claimed fulfilled. Sequential execution method is already selected and need not be selected again.
- **Approval requested:** written review of this exact plan and permission for the bounded new worktree, locked scratch/image installs/downloads, three local builds, scratch credential generation, isolated three-service boot/restart and task-owned teardown above. No action begins before that approval is recorded in the parent ledger with planSHA. Local P6/report closure alone is not this approval.

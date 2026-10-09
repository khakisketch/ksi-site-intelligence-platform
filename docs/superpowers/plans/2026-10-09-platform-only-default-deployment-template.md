# Platform-only default deployment template — Implementation Plan (P6 proposal)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans with the already selected sequential method. Steps use checkbox (`- [ ]`) syntax for tracking. Independent final Reviewer/Test Runner remain required; this proposal is not execution authority.

**Status:** PROPOSAL FOR HUMAN WRITTEN REVIEW — not approved or executed. Based on P5-COMP-01 and reconciled final P5 source evidence at `a8f6e93`: independent6047passed/30skipped/98warnings/0failed, receipt SHA256 `124a13d45083eec069ffa245253497fc2bbaae433ec89712d54f36df30a577de`. P5's local verification report does not establish whole-cleanup, customer or operational acceptance. Preserve the already selected sequential method; this proposal grants no new runtime action.

**Goal:** Make the repository's default platform deployment template acquisition-free without touching historical data, volumes, contracts or running deployments.

**Architecture:** Keep the existing platform Core, object storage and bounded volume initializer. Remove the unused NodeODM service from the base and VM overlay, preserve the historical named-volume declaration and recovery identity, and correct stale Dockerfile/ops descriptions. This changes declarative defaults only, not the Analysis/Spatial Data engines, HTTP surfaces or permissions.

**Tech Stack:** Existing YAML/Compose templates, Python/pytest/PyYAML validation and existing pinned Core Dockerfile; no new dependency or service.

**Spec:** `docs/superpowers/specs/2026-10-07-physical-site-platform-rebaseline-design.md` §§2/6/8/9, SHA256 `14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`; ADR-KSI-039. Actual gap/authority: parent rebaseline ledger and `docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md` §5 P5-COMP-01, not a new product design.

## Global Constraints

- One writer in the recorded current checkout/local main; revalidate base/status and record exact base before writes. No foreign worktree cleanup or forced history edits.
- Flight, autonomous acquisition, tactical perception/control and customer production reconstruction remain outside long-term responsibility.
- Preserve existing Core/MinIO/init-volumes service configuration, image references, hardening, addresses, ports, credentials interfaces and durable state. Only the unused NodeODM service/overlay entries and inaccurate documentation change.
- Preserve existing `ksi-data`, `ksi-objects`, `ksi-odm` declaration names and actual host volumes. `ksi-odm` becomes unused historical compatibility metadata, not an active platform mount. Never execute `down -v`, delete or migrate historical data, touch existing containers, or rename Compose projects.
- No new endpoint, format, profile, producer, dependency version, policy activation, live credentials/grant, tenant scope, resource ceiling, public exposure or device operation.
- Keep original archive manifests/inverse hashes and strict checker unchanged; P5-ARCH-01's two adaptations stay explicitly open. Broad pre-existing type errors remain reported, not concealed.
- Generated/static checks do not prove fresh images, production boot, customer data/rights, accuracy or acceptance. Missing actual runtime evidence stays UNVERIFIED.
- Plan approval permits local template/docs/test edits and prepared-toolchain verification only. Isolated dependency installation/sync, image pull/build/start or CI dispatch require separately explicit authorization covering exact environment and effects; no system/live setup implied.
- Invariants: INV-040 is enforced by truthful configured/unverified reporting and existing platform boot/import controls; INV-054 by unchanged pinned platform images, revised active-reference assertions in `test_runtime_image_pins.py`, the unchanged pin CLI, and retained historical digest controls. Preserve INV-020/024/050/051/053/055/060/061 by leaving algorithms, wire contracts, profiles, identities, resource/auth/egress participants, journals and historical sources unchanged. Device/signed-Mission safety invariants retain historical meaning; no acquisition execution or invariant removal.

## Required implementation binding

```text
Requirement IDs: RB-03/08; P5-COMP-01; preserve EXT-VAL/SDP-REQ acceptance.
Owner module: deploy templates + Dockerfile comments + tests/ops docs; no service-code ownership change.
Acceptance criteria: default+VM template has no NodeODM/managed worker/device service or acquisition mount; Core/object-store configuration and existing named volumes unchanged; independent static/boundary verification passes; no runtime mutation.
Contracts affected: none. Existing state, identities, V1 strict/V2 provisional and data-delivery semantics unchanged.
Reference assets: accepted spec/ADR039; current exact Compose/Dockerfile; historical recovery identifiers as evidence only, never archive imports/instructions.
Adoption decisions: retain current platform runtime, remove unused default service; protect historical volume rather than creating a new managed runtime.
Files to change: named below; no blind Docker/ops rewrite.
Tests: new template contract RED→GREEN; existing deployment/image/boundary controls; independent final verification.
HIL or real-device assumptions: none.
License/data implications: no new vendor/dependency; no customer bytes, source originals or AGPL engine execution; historical data untouched.
Rollback: reviewed inverse of task-owned local commits; no reset/clean, deployment or volume operation.
```

## Review Focus

1. A VM overlay can silently reintroduce a removed service; the combined declarative service graph must stay platform-only (Task1).
2. A historical `ksi-odm` volume may contain unique customer/test data; removal of its service must not imply deletion, migration or a new data owner (Task1).
3. Default service removal can disturb Core/MinIO/init health/security/ports; preserve their exact configurations, not just names (Task1).
4. Old ops instructions can restart NodeODM or present managed fields as required platform inputs; update active startup references while retaining dated evidence (Task1).
5. A prepared editable environment/static pin pass is not a fresh production boot; leave actual dependency/image/runtime proof open until explicitly authorized (Task2).

## File map / interfaces

| Task | Output | Dependency |
| --- | --- | --- |
| 1 | `deploy/compose.yaml`, `deploy/compose.vm.yaml`, Dockerfile comments, `deploy/README.md`, `docs/ops/DEPLOYMENT.md`, `docs/ops/VM_DEPLOYMENT_READINESS.md`, new template test, existing VM contract and image-reference test | Exact pre-change source snapshots and P5-COMP-01 |
| 2 | Parent ledger/integrated audit/product-state linkage and independent receipt | Task1 unchanged platform graph + controlled source diff |

No other Compose template, archived source, backup/restore/bootstrap/lifecycle script, service implementation, `.env`/credential example or Dashboard source is edited. A discovered high-risk runtime/contract change is a decision, not permission to broaden this file map.

Observed-input revision `a8f6e938c8a8c633983f12792973dcdb24aaecd6` (P5's test-only observer repair; later closeout records may change). Input snapshot `/tmp/opencode/p6-template-input-snapshot.json` SHA256`02970d38a91f50b00f13a0330bdfe7568e92cb7ae8bcd79de6df8ff32c63bfb8`; all normalized preservation values below are retained here, not dependent on scratch survival. These identify read inputs, not permissions or a running stack. Revalidate actual checkout/base before execution.

| Existing required file | Observed SHA256 |
| --- | --- |
| `deploy/compose.yaml` | `a5e8294722ec64259a94d1c4cb27c4c7d6636613a9c85dc25d01f7261dc2da67` |
| `deploy/compose.vm.yaml` | `93f12719663dc58215685c19a2ee596403a0ca57866bb0976b6ff53d86e39cdd` |
| `Dockerfile` | `dd83db2646490e7007abd5502a07f4d25c06ecdab3601cb236d4bcfb64b9afc3` |
| `deploy/README.md` | `3fde44b014a8cbe9453d33dede26dcb05f5a010cf6d78534e1f36adbcdeb63ad` |
| `docs/ops/DEPLOYMENT.md` | `d8e7289f3e0b41ce9931b316fb9fb440f3575982d397c63171e5eedbf6642a13` |
| `docs/ops/VM_DEPLOYMENT_READINESS.md` | `6f914af0c65a27e171f2b1cb249358092a4f05813005b8480559f6a4cf489c67` |
| `tests/contract/test_vm_deployment_contract.py` | `39cc7f1ed2bcef5a5100ffb2e4b047387451c9ba73e2c46da7f74ea0e259ec42` |
| `tests/contract/test_deploy_env_contract.py` (read-only) | `5350c4bc9e3aabf4f14f4c09201f7c26485306ad6eb95da0f748335077f1a83c` |
| `tests/contract/test_runtime_image_pins.py` | `8400cef15db5a2a00e6f005e04517268e89cc5d18f8628a8b815cb0b894cbd28` |
| `tools/check_runtime_image_pins.py` (read-only) | `583458d2e4199e7ebef4db2a6eb3cc2277bd078ba0597d78a51a7fca18fe0e87` |
| `tests/contract/test_release_evidence.py` (read-only) | `5e20326df5230697ebcf21a327f26378fd6ed1aa584f8fd8bfc0d0e1807df1e5` |
| `tests/contract/test_external_runtime_deployment_contract.py` (read-only) | `63f2b0fc0d19507aea7dde2f38efbed33e749bcb074510c6155dcf0ffb1991f3` |
| `deploy/bin/external-runtime-stage.sh` (read-only) | `e59bba8e2dc49dc6babd9a8936f31e36dc62ed9d7b2a00bfd6d3cc715aa6a541` |

The first eight files are the original input snapshot; the five additional consumer files above were subsequently inspected at the same HEAD. These are independent source hashes, not a modified original snapshot. The canonical historical NodeODM digest-only exception in the pin validator, release schema/generator and external-runtime script remains unchanged; removal from the default service graph is not reinterpretation of historical runtime identity.

### Task 1: Remove dormant acquisition from the default declarative graph

**Files:** Modify `deploy/compose.yaml` comments plus the `nodeodm` service at107–117, `deploy/compose.vm.yaml` introductory comments plus23–25, `Dockerfile` comments only (1–8 and58–62; executable lines unchanged), `deploy/README.md` current component/startup descriptions and retired optional Copilot section, `docs/ops/DEPLOYMENT.md` current template inputs vs historical signing/managed sections, `docs/ops/VM_DEPLOYMENT_READINESS.md` topology/preflight descriptions, `tests/contract/test_vm_deployment_contract.py:20-55`, and `tests/contract/test_runtime_image_pins.py:307-325` plus one historical pin control. Create `tests/contract/test_platform_deployment_template.py`. The pin CLI, release evidence schema/generator, external-runtime script and its tests are read-only preservation inputs, not edit targets.

**Interfaces:** Consume the current base/overlay YAML and unchanged platform Dockerfile CMD. Produce no new API: base `services` keys exactly `{init-volumes, core, minio}`; VM overlay keys exactly `{core, minio, dashboard, caddy}` (its existing additive Dashboard/Caddy preserved), merged service names `{init-volumes, core, minio, dashboard, caddy}`; historical `ksi-odm` remains declared but unused. Every remaining base/VM service mapping and all executable Dockerfile lines match the recorded base. Test-only `_load_template(path: Path) -> dict[str, Any]` uses existing PyYAML SafeLoader with only the existing `!reset` sequence constructor; never expand environment variables or read live files.

- [ ] Record Git/source baselines and current base service dictionaries, all remaining VM service mappings, named-volume map and executable Dockerfile lines. Inspect nearest deploy/ops instructions and existing owner tests. Classify any variable expansion requirement separately; do not load live `.env`/secrets or perform container/Compose lifecycle actions.
- [ ] Write new static tests with `_load_template` as the test-only safe tagged loader:

```python
def test_default_and_vm_services_are_platform_only() -> None:
    base = _load_template(_ROOT / "deploy/compose.yaml")
    vm = _load_template(_ROOT / "deploy/compose.vm.yaml")
    assert set(base["services"]) == {"init-volumes", "core", "minio"}
    assert set(vm["services"]) == {"core", "minio", "dashboard", "caddy"}
    assert set(base["services"]) | set(vm["services"]) == {
        "init-volumes", "core", "minio", "dashboard", "caddy"
    }

def test_removed_service_preserves_named_volume_identity() -> None:
    base = _load_template(_ROOT / "deploy/compose.yaml")
    vm = _load_template(_ROOT / "deploy/compose.vm.yaml")
    assert base["name"] == "ksi"
    assert base["volumes"] == {"ksi-data": None, "ksi-objects": None, "ksi-odm": None}
    assert vm["volumes"] == {"caddy-data": None, "caddy-config": None}
    for template in (base, vm):
        for service in template["services"].values():
            assert all(not mount.startswith("ksi-odm:") for mount in service.get("volumes", []))
```

- [ ] Add `test_remaining_service_configuration_is_unchanged` and `test_core_dockerfile_instructions_are_unchanged`: compare remaining parsed service dictionaries against the normalized literal hashes below; compare all nonempty, noncomment Dockerfile lines joined with `\n` plus final newline to SHA256`5e9bb9b180da181315312ddbbf39fd9f9ce9512d9769f7d4da911bae2d35e33b`. These preservation controls pass before the removal and continue to pass after it; do not manufacture RED for unchanged behavior.
- [ ] Run `uv run --no-sync pytest -q tests/contract/test_platform_deployment_template.py`. Expected: service/volume absence tests fail on actual NodeODM service/mount, not collection/loader errors; remaining-service and Dockerfile controls pass. Preserve VM `!reset` ports, OIDC/secrets, Caddy80/443-only publication and private networks.
- [ ] Remove only the `nodeodm` service from base/VM; keep current `ksi-odm` named volume declaration with an explicit historical-unused comment. Do not create an optional managed service/profile or edit archived inverse records. Keep Core/MinIO/init dictionaries unchanged. Fix stale Dockerfile comments naming the retired production factory/Mission dependencies; executable instructions must not change.
- [ ] Update the existing VM resolve/network test to assert exact merged platform service names and explicit NodeODM absence; keep all four long-running services' private-network checks and unchanged Caddy-only port assertions. Compose `config` uses `.env.example` only and makes no container or host-network changes. The existing test skips only when the Docker CLI is absent; an installed CLI with missing/broken Compose is a real capability failure to report, not a new skip or installation permission. Mandatory static YAML controls still run independently.
- [ ] Update `test_expected_multi_arch_digest_references_are_present` to retain the exact current Python and MinIO pin assertions but assert `"opendronemap/nodeodm" not in compose`; the old assertion requires a removed default service and is not a historical-profile contract. Add `test_canonical_historical_nodeodm_digest_still_validates`: call the existing `_tool()._validate_reference` with `"opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"`, `path=Path("deploy/bin/external-runtime-stage.sh")`, `line=1`, and assert an empty violation list. Keep the arbitrary digest-only-image rejection and every other pin-control assertion intact; do not edit the tool or add another exception.
- [ ] Make `test_vm_compose_resolves_with_only_caddy_80_443_published`'s child-process interpolation environment deterministic: copy the inherited environment excluding `KSI_*` and `COMPOSE_*`, then set only `KSI_DEPLOY_ENV_FILE=.env.example`; do not mutate the host environment or print inherited values. Explicit `--env-file .env.example` alone is insufficient because shell values take precedence. Keep explicit `-f` paths and no `--resolve-image-digests`/`--lock-image-digests`, `up`, `run`, `build` or `pull`. This is test-only preparation, not a product environment change.
- [ ] Correct only the named current startup/topology/factory sections. Use the existing platform boot section in `deploy/README.md`, with base/VM service sets, real platform required/optional inputs and a warning that editing templates does not stop old containers or remove volumes. Label retired acquisition/coordinator/Gateway/Edge observer/Copilot/signing/managed-recovery instructions historical and evidence-only; preserve their provenance links and dated staging evidence. `docs/ops/DEPLOYMENT.md` gets a current platform path separated from historical sections; VM preparation no longer requires Mission keys. Never advertise unchanged legacy backup/restore/staging scripts as verified current platform recovery, or create an activation/cleanup procedure here. Human prose is reviewed against actual source/links, not a text-presence pytest gate.
- [ ] Bind those descriptions to the actual factory rather than a generic OIDC claim: `platform_production.py:67-87` requires data dir, S3 endpoint/bucket, a nonempty principal digest list, and in OIDC/DUAL mode the protected `KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE` plus issuer/audience/JWKS. Its existing Analysis trio is all-or-none and requires exactly one `ANALYSIS_WORKER`; external workflow/provider paths are both-or-none. State that this template-only change neither provisions these inputs nor adds Spatial Data production activation: the current production factory does not inject `spatial_data`, while the genuine local lane uses `SpatialDataLocalAssemblyConfig`. Do not invent a new env variable, missing mount or worker service to close F-02/03.
- [ ] Run `uv run --no-sync pytest -q tests/contract/test_platform_deployment_template.py tests/contract/test_vm_deployment_contract.py tests/contract/test_deploy_env_contract.py tests/contract/test_runtime_image_pins.py tests/contract/test_release_evidence.py tests/contract/test_external_runtime_deployment_contract.py::test_release_image_binding_accepts_the_canonical_nodeodm_digest_only_exception tests/contract/test_acquisition_archive_boundary.py tests/contract/test_platform_boot_switch.py tests/contract/test_physical_site_move_tooling.py` and `uv run --no-sync python tools/check_runtime_image_pins.py`. Expected: mandatory static/contract/consumer-reference and historical-pin checks pass, pins exit0; only intended declarative/comment/doc differences. The release script test uses its existing Docker stub and is not real NodeODM execution. Optional missing-Compose execution is an explicitly unverified gate, not overall resolved-Compose readiness. Missing required prepared dependency is blocked, never auto-installed. The HEAD-aware consumer test is run against the actual committed change as well, not only uncommitted files.
- [ ] Run `git diff --check`, validate changed document-relative local links, and inspect the actual index/diff against the approved path list. Expected: no broken link/whitespace/source/credential/default drift. Commit only Task1 paths locally with `git commit -m "fix: make default platform template acquisition-free"`. No container-changing Docker/deployment/volume command or push; prepared `compose config` above is read-only syntax/merge verification only.

### Frozen preservation controls

Semantic dictionaries use SHA256 of UTF-8 `json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`. No environment expansion, Git lookup, time, network or live `.env` dependency in these tests.

| Template/service | Required semantic SHA256 |
| --- | --- |
| base/init-volumes | `a3b6a71b7be633785a3dd23f17c1fd16ec8c5a6d68e81ffcf18577fffaf26e3a` |
| base/core | `ec0264cd4641d3cf8d4fd5db5a6c8a51d4b2cf4867c6a77ea4841cc55eb89445` |
| base/minio | `c6f7d274c722357dc3347d793feaaf5942268cd6da40f2f4e4cd45e8b96ca4a0` |
| vm/core | `3d8f7b2173295b88afb5a746d9db8121867396f3d5d5d3848e454a32d2f9348b` |
| vm/minio | `f1f6b7dba79949171a1164bc724e57837ec0c34ac278460c24aee6c29fd30233` |
| vm/dashboard | `4580f2b765207ea5fa3e09e811043a955e12a78e6d266e622d57ac3e65162560` |
| vm/caddy | `79a28e93f3e96e3a8426083e70fcbcd33d19e0a88e010053a416460bb67d88ec` |

### Task 2: Independent verification and truthful runtime handoff

**Files:** Parent rebaseline ledger, integrated audit and product-state summary; ignored checkpoint never committed. Immutable source receipt and independent output logs; no product code changes planned.

**Interfaces:** Consume Task1 actual commit/source hashes and protected service/volume/config snapshots. Produce independent exact command/result evidence and `passed/failed/unverified` gate rows; no endpoint, permission or operational-readiness promotion.

- [ ] Freeze actual HEAD/required files and request one read-only Reviewer for default/overlay graph, preserved Core config/state/volume implications and changed active instructions. Review findings are not authority to touch live deployments or historical data.
- [ ] Independent Test Runner runs `uv run --no-sync pytest -q -p no:cacheprovider` under ambient umask plus the Task1 command above and `tests/contract/test_repository_normalization.py tests/contract/test_runtime_image_pins.py`. Run `uv lock --offline --check`, `uv run --no-sync python tools/check_core_module_boundaries.py`, and `uv run --no-sync python tools/validate_repository_normalization.py --check-r3-migration`. Expected: mandatory software/static gates0, actual full-suite counts and explicit environmental skips recorded. Missing Docker yields the already-explicit skip; installed but broken Compose is a failure, not green. Check pre/post source snapshots. Reuse unchanged P4 source-bound render evidence only for unchanged source; no frontend source/runtime change or UI redesign is authorized.
- [ ] Run `uv run --no-sync ruff check .` and `uv run --no-sync mypy --follow-imports=silent tests/contract/test_platform_deployment_template.py tests/contract/test_vm_deployment_contract.py tests/contract/test_runtime_image_pins.py`; expected exit0 on changed tests. Compare `uv run --no-sync mypy packages services tests tools` diagnostics with the unchanged pre-P6 source/control; expected pre-existing109errors/14files FAIL, zero newly introduced errors, never a broad pass. Run `uv run --no-sync python tools/verify_physical_site_archive.py --root . --execution docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json --extras docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json`; expected strict exit1 with the same2adaptation rows/4findings, original251matches/destination249matches. No v2 waiver.
- [ ] Keep fresh isolated dependency sync/resolution, Core/worker images/boot, CI and production host identity/containment marked UNVERIFIED unless Human separately authorizes an exact isolated environment. If later approved, verify there under the same pinned sources, generated safe state and no live configuration; missing cache/image/tool access returns a concrete blocker rather than a network/install/deployment fallback.
- [ ] Reconcile actual diffs, returned findings and evidence. Commit only task-owned records locally and report default-template usable level, passed/failed/unverified gates, historical-volume protection and missing operational/customer inputs. P5/Cleanup RB08 stays open if its required fresh gate is unverified.

## Excluded successors / decisions

- Scoped human Site-bootstrap/new-area grant ownership (F-01), protected storage/graph/workers (F-02/03), permitted same-Site t0/t1/t2 and selected actual consumer/host (F-04) are separate first-flow contracts/inputs. This plan neither grants them nor declares the first experience complete.
- No generalized Site State wire model, new computation/format, change feed, remote MCP topology or universal customer onboarding.
- Original archive records stay immutable; append-only adaptation lineage needs its own written decision if the strict gate is to change. No wholesale type-hygiene repair.

## Plan self-review / written handoff

- This is the smallest standalone-runtime **template** repair justified by P5, not a whole fresh-runtime or first-flow acceptance plan. It implements only the spec's acquisition-free default/configuration subset; all other acceptance gaps remain explicit.
- Interfaces match literal existing service/volume names; each removal has a failing contract witness, and preservation controls use recorded baselines rather than trusting a renamed path.
- P5-ROUTE-01 lesson: named documents may still be manifest consumers; preserve useful provenance-only references and include the unchanged committed-HEAD consumer check in the P6 gate. Never add a closed-map exception merely to suppress a failure.
- Self-review correction: VM intentionally adds Dashboard/Caddy; it must not be constrained to override-only services. `init-volumes` has no private-network declaration, so preserve the four existing long-running VM network checks rather than incorrectly requiring it to be on that network. Static loader recognizes only the existing `!reset` sequence tag. Dockerfile's final factory comments are included without changing CMD. Legacy backup/Copilot startup examples are labeled historical, not converted into a new workflow.
- Self-review correction: human startup prose earns source/link review, not a presence-test that would freeze wording. Existing template/runtime consumer tests stay intact. P5-OBS-01's deterministic worker observer and AI stale-page refusal remain unchanged; no P6 test should replace protected conflicts with success to make the suite green.
- Self-review correction: `test_runtime_image_pins.py:325` still requires NodeODM in the base Compose. Task1 now reconciles that active-reference assertion and explicitly preserves the canonical historical digest-only exception through the pin, release-evidence and external-runtime controls. This closes a planning dependency omission, not an execution finding or permission to edit release contracts.
- Actual `platform_production.py`/`runtime_config.py`, Core README and existing deploy-env contract were read for the current startup binding. Protected OIDC subject-registry loading, optional trusted graph activation and local-only Spatial Data assembly must remain distinct; acquisition-free template syntax is not a configured full analysis/data environment or verified production boot.
- Current Docker docs checked through Context7 (`/docker/docs`): `compose config` renders/validates the merged model, `--format json` is supported, and digest resolution is a separately requested option. [Interpolation precedence](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/) confirms shell values outrank `--env-file`; child-process input filtering is therefore part of Task1's safe example-only syntax check. No CLI, Compose plugin or container was run to prepare this proposal.
- Source/self-reviewv2 on the scratch proposal performed38read-only checks/0failures against13inputs and all seven service hashes; receipt SHA256 `d5b158c2024db50f6573ac745331ab6abeb4a72cb020776224c186446ebba813`. The canonical transfer updates the status/receipt handoff and names the exact VM child-process test to remove an ambiguous pronoun; scope and preservation values are unchanged. Canonical source/plan checks are separately recorded in the parent ledger; no proposed P6 test has run.
- No dependency installation/container operation is implied by plan review or code-only execution approval. Preserve the already selected sequential execution method after Human confirms this written scope; no P6 source changes begin before approval.

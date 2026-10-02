# First Pilot Analysis Security Implementation Plan

> **For agentic workers:** Apply `superpowers:test-driven-development` and `superpowers:verification-before-completion` to each bounded task. This checkout has no authorization to commit, deploy, provision credentials, or change a host; those steps in generic skill workflows do not apply.

**Plan ID:** FPC-P2-20260929

**Goal:** Require an independently signed Analysis activation and dedicated identities before new operational Analysis runs, while preserving authorized historical reads.

**Architecture:** Core owns activation, admission, and access decisions. The measurement worker receives only an Analysis credential; external AI clients receive a separate scoped credential. Signed activation is separate from the existing external-artifact authority snapshot. Customer OIDC is verified as `iss+sub` and resolved through KSI-controlled grants.

**Tech Stack:** Python, FastAPI, Pydantic, Ed25519, existing Core journals and identity registry; contract and replay tests.

**Spec:** `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`; `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`; user-approved first customer pilot plan.

## Global Constraints

- Preserve `INV-040/053/060/061`, existing V1 calculations/history, organization and WorkArea isolation, and lease fencing.
- No activation is inferred from an existing external authority snapshot, local runtime config, request header, or generic processing token.
- An absent, invalid, or expired activation blocks new calculation work and does not erase historical results.
- Do not claim customer OIDC, Terra compatibility, host operation, or release acceptance from generated tests.

## Review Focus

- A generic processing credential tries each Analysis internal route and direct calculation/capability seam.
- A signed activation is valid but its organization, policy, runtime, resource, or worker identity differs from the mounted graph.
- Activation expires between request and worker lease, or before a Core restart with existing history.
- A customer JWT contains forged KSI role/organization claims despite a valid `iss+sub`.
- An external AI caller omits or changes the purpose header, or requests another Site/WorkArea.

## Requirement and owner map

| Task | Owner and deliverable | Depends on | Focused validation |
| --- | --- | --- | --- |
| P2-T1 | Core identity + Analysis worker: separate `ANALYSIS_WORKER`/`ANALYSIS_WORK` from generic processing in route, store and capability checks | Existing local graph | RED→GREEN auth, route, execution and generic ProcessingJob contracts; independent security review |
| P2-T2 | Core contract/authority: strict signed `AnalysisActivationV1` loader binding organization, policy/runtime/resource digests, dedicated worker principal and validity interval; no ambient fallback | T1 | Signature, substitution, expiry, replay and permission negative tests; independent security review |
| P2-T3 | Core composition/admission: production activation only from T2, no new execution after expiry, historical reads survive; independent GIS worker uses dedicated credential | T2 | Production assembly, request/lease/restart and recovery contracts; independent security review |
| P2-T4 | Core identity: verified customer `iss+sub` resolves to protected user, organization, Site and WorkArea grants; JWT KSI claims confer no authority | T2 | Forged-claim, cross-org/site/area, revoked user and JWKS failure tests; independent security review |
| P2-T5 | Core + MCP: dedicated Analysis client credential/scope and server-side Site AI consent control egress; caller header cannot grant or evade the restriction | T4 | Missing/forged header, wrong Site/scope, consent revocation and MCP denial tests; independent security review |

## P2-T1 evidence

Frozen baseline/current inventory: `.opencode/artifacts/first-product-completion-20260929/p2-analysis-worker-review-freeze.json`. Dedicated Analysis kind/permission and guards were added in 12 files, reviewed PASS on those exact hashes. Reviewer ran 71 auth/worker API tests. Lead copied the 12 files byte-exact to main and ran 75 focused auth, worker API, execution and production-flow tests; Ruff passed. No production activation or customer credential was provisioned.

## Task execution contract

For each remaining task, state requirement IDs, owner module, acceptance, contracts, reference assets, adoption, files, tests, HIL assumptions, license/data implications, and rollback before editing. Write a failing contract test first, then the smallest implementation. Freeze exact changed-file hashes and dirty Git baseline for independent review. Reviewers are read-only. The Lead integrates only a PASS diff, reruns focused checks, and updates this ledger and the shared checkpoint at milestones. No commit, push, PR, merge, host change, credential installation or deployment without separate authorization.

## P2-T2 evidence

Frozen four-file baseline and candidate hashes: `.opencode/artifacts/first-product-completion-20260929/p2t2-analysis-activation-review-freeze.json`. The worker established RED for the missing contract/loader, then 12 focused tests passed with Ruff, mypy and diff-check. Independent security/contract review PASS on unchanged hashes/status; reviewer reran 12 tests. Lead integrated the four files byte-exact and reran activation/auth/worker API tests: **83 passed**, Ruff and diff-check passed. No production mount or signing material was installed.

Review carry-forward: the loader requires a current activation and cannot load an expired record after restart. P2-T3 must keep historical Analysis reads available without requiring this current-authority loader to succeed; new execution stays blocked. The loader docstring's historical-record sentence is limited by this behavior and must not be used as evidence of historical replay after expiry.

## P2-T3 evidence

Frozen 12-file baseline and candidate hashes: `.opencode/artifacts/first-product-completion-20260929/p2t3-production-activation-review-freeze.json`. Production Core now requires the explicit runtime, signed activation, and verification-key paths together and exactly one registered dedicated Analysis worker identity. A verified expired activation mounts the same journal graph for historical reads; current-time guards deny new create and all six worker operations. Independent security review PASS on the frozen diff; reviewer ran 69 production/activation tests and one real HTTP worker/restart case. Lead integrated byte-exact and ran **80** activation/production/worker API tests plus the expired-restart HTTP case (**1 passed, 13 deselected**); Ruff and diff-check passed. Synthetic keys and local GeoTIFFs only; no host/credential/deployment claim.

## P2-T4a identity-resolution evidence

Verified JWT `iss+sub` now resolves through a private, bounded KSI subject registry; JWT `ksi_*` claims do not grant authority. Production OIDC/DUAL requires `KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE`. Local dev and browser fixtures use explicit synthetic mappings. Review first found duplicate OIDC `principalId`; second found OIDC/opaque collisions across other principal kinds. The same worker reproduced each as RED and rejected all duplicate/colliding IDs, including revoked rows. Final frozen diff: `.opencode/artifacts/first-product-completion-20260929/p2t4a-oidc-mapping-review-freeze-v3.json`; independent security review PASS with 85 tests. Lead integrated 12 paths byte-exact and ran **173** focused OIDC/auth/production/dev tests plus Ruff. The worker ran one Analysis OIDC browser case before the freeze. Site/WorkArea grant enforcement remains P2-T4b; no customer issuer or account was configured.

## P2-T4b resource-scope evidence

Frozen six-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t4b-resource-scope-review-freeze-v2.json`. Mapped grants now filter Analysis creation/selectors/list/detail/result/evidence/AI consent, Site list/get and WorkArea list; opaque `None` grants retain their old behavior. First security review found an idempotent retry that could issue NX from an existing AP despite ungranted multi-area WorkOrder selectors and reveal its history. A RED interrupted-before-NX test reproduced it; the corrected pre-recovery and historical-read checks received independent PASS. Lead integrated exact bytes and ran **135** Analysis/HTTP/replay/Site/WorkArea tests plus Ruff. WorkArea writes, ObservationWorkOrder routes and external reconstruction ingress still need scoped authorization; this is not customer access acceptance.

## P2-T4c write/ingress-scope evidence

Frozen four-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t4c-write-ingress-review-freeze.json`. Mapped Site/WorkArea grants now constrain WorkArea writes, observation schedule and WorkOrder creation/list/detail, and external reconstruction register/list/detail/upload/seal. Multi-area WorkOrders require every area grant; inaccessible known IDs return 404. Independent security review PASS on unchanged hashes/status; reviewer ran 41 focused tests. Lead integrated exact bytes and reran **111** focused contract/replay tests and Ruff. WorkOrder operations/approval/reobservation and other generic Core routes remain separate access-review scope; customer OIDC operation is not accepted.

## P2-T5 MCP client and AI egress evidence

Final frozen 14-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t5-mcp-client-egress-review-freeze-v3.json`. Dedicated `ANALYSIS_MCP_CLIENT` has only Analysis API read/create permissions, explicit nonempty Site/WorkArea grants in production token config, and an exact six-route method/template allowlist at the authenticated request boundary. Core checks current Site AI consent from that identity on every public Analysis request; caller purpose header cannot grant access or acknowledgment. MCP sends no purpose header and requires Core's identity/consent acknowledgment. AP/NX internal seams enforce Analysis permission and resource scope. First independent review found generic auth-only route exposure; RED tests reproduced two 200 responses and the same worker added central deny-by-default enforcement. Second review found a bearer OpenAPI description regression; RED test reproduced it and the same worker restored explicit device kinds. Final independent security/contract review PASS on v3. Lead integrated the 14 paths byte-exact and ran **235** focused auth/OIDC/Analysis/MCP/production/API-sync tests, Ruff and diff-check passed. No customer credential, host change, or deployment occurred. Exact allowlist must be extended for approved V2 Analysis routes; unrelated customer OIDC route scope remains a separate gate.

## P2-T4d WorkOrder operations/reobservation evidence

Frozen three-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t4d-workorder-operations-review-freeze.json`. Mapped Site and all-WorkArea grants now constrain WorkOrder operations detail/list/assignment/due-date/close/reopen, WorkOrder approval, and reobservation draft create/list/approve before store calls. RED tests reproduced same-organization list disclosure and ungranted approval; worker's focused 64 passed. Independent authorization review PASS on frozen hashes; reviewer ran 20 focused tests. Lead integrated exact bytes and reran **23** targeted tests, Ruff and diff-check. Separate review found `work_inbox.py` can disclose assignment notification IDs for an inaccessible order; P2-T4e must close that customer route before OIDC operation.

## P2-T4e WorkInbox evidence

Frozen two-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t4e-work-inbox-review-freeze-v2.json`. Mapped grants filter assignment and report notifications before paging; mark-read rechecks current access before an existing receipt or idempotent retry; report sharing and notifications require current Core WorkOrder Site and **all** its WorkAreas. Initial RED reproduced an unauthorized first-page assignment and ungranted report share. First independent review found a multi-area order grant gap; the same worker reproduced A-only access to an A+B order as RED, fixed it, and final independent review PASS on v2 hashes. Lead integrated exact bytes and ran **42** focused inbox/operations tests, Ruff and diff-check. Opaque `None` grants retain historical behavior; no customer registry or host was configured.

## P2-T4f customer OIDC route closure evidence

Frozen three-file diff: `.opencode/artifacts/first-product-completion-20260929/p2t4f-oidc-route-closure-review-freeze.json`. Restricted mapped operators now pass only an exact method/FastAPI route-template allowlist of already scoped first-pilot routes; generic/auth-only/lookalike routes and Site registration/transitions/AOI/model-age writes are denied. Signed synthetic OIDC RED reproduced generic 200, Site registration 201, model-age 200, and lookalike 200 before the guard. A stale scope test was corrected to require no AI-egress acknowledgment for an operator with a caller purpose header. Independent security review PASS on frozen hashes; reviewer ran 25 focused tests. Lead integrated exact bytes and reran **112** focused OIDC/Analysis/WorkOrder/Inbox tests, Ruff and diff-check. New V2 routes are intentionally absent from the allowlist until P3-T2's scoped implementation. Actual customer issuer, registry, and host remain unconfigured.

## External gates

Customer IT must provide issuer, audience, JWKS URL and test identities; KSI can implement and test the mapping without these values. The customer must authorize the `t0/t1/t2` Terra files and processing rights. Host installation and credentials are separate approval gates. None of these gates is satisfied by this plan.
